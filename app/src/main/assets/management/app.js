'use strict';
const $ = id => document.getElementById(id);
let submitting = false;
let revision = '', model = null, mode = 'form', dirty = false, pending = null, ready = false, polling = false, messageTimer;
const stateNames = {STOPPED:'已停止',WAITING_CONFIG:'等待配置',STARTING:'启动中',RUNNING:'运行中',RETRY_WAIT:'等待重试',APPLYING:'正在应用',ERROR:'运行异常'};
function setConnection(status, text) {
  $('connection').dataset.status = status;
  $('connection-label').textContent = text;
}
function renderServiceStatus(status) {
  if (status.error || status.state === 'ERROR' || status.state === 'RETRY_WAIT') setConnection('error', '服务报错');
  else if (status.state === 'RUNNING') setConnection('normal', '服务正常');
  else setConnection('inactive', status.state === 'STARTING' ? '启动中' : status.state === 'APPLYING' ? '应用中' : '未启用');
}
function showError(text) {
  clearTimeout(messageTimer); $('message').textContent = text; $('message').hidden = false;
  messageTimer = setTimeout(() => {$('message').hidden = true;}, 12000);
}
function hideMessage() {
  clearTimeout(messageTimer); $('message').hidden = true;
}
async function api(path, method = 'GET', body, headers = {}) {
  const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 8000);
  try {
    const response = await fetch(path, {method, credentials:'omit', signal:abort.signal,
      headers:{...(method !== 'GET' ? {'Content-Type':'text/plain; charset=utf-8'} : {}), ...headers}, body});
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `请求失败（${response.status}）`);
    }
    return data;
  } catch (error) { if (error.name === 'AbortError') throw new Error('请求超时，请检查机顶盒连接'); throw error;
  } finally { clearTimeout(timeout); }
}
function markDirty(value = true) { dirty = value; }
function setBusy(value) {
  value = value || submitting || !!pending;
  for (const id of ['apply','rollback','reload']) $(id).disabled = value;
  document.querySelectorAll('[data-control]').forEach(button => button.disabled = value);
}
function options(select, interfaces, selected, empty) {
  select.replaceChildren(new Option(empty, ''));
  for (const nic of interfaces) select.add(new Option(`${nic.name} · ${nic.addresses.join(', ') || '无地址'}${nic.up ? '' : '（未启用）'}`, nic.name));
  if (selected && ![...select.options].some(option => option.value === selected)) select.add(new Option(`${selected}（当前不可用）`, selected));
  select.value = selected || '';
}
let interfaces = [];
function fillForm(config) {
  const relay = config.relay;
  options($('upstream'), interfaces, relay.upstream_interface, '暂不配置');
  options($('listen'), interfaces, relay.listen_interface, '全部 IPv4 地址');
  $('enabled').checked = relay.enabled;
  $('port').value = relay.port; $('maxclients').value = relay.maxclients; $('verbose').value = relay.verbose;
}
function formYaml() {
  const relay = {enabled:$('enabled').checked, upstream_interface:$('upstream').value || null,
    listen_interface:$('listen').value || null, port:Number($('port').value), maxclients:Number($('maxclients').value), verbose:Number($('verbose').value), workers:1};
  const serialize = (name, fields) => `${name}:\n${Object.entries(fields).map(([key,value]) => `  ${key}: ${JSON.stringify(value)}`).join('\n')}\n`;
  return 'schema_version: 1\n\n' + serialize('management', model.management) + '\n' + serialize('relay', relay);
}
async function loadConfig(force = false, ownOperation = false) {
  const data = await api('/api/config');
  if (force || !dirty || ownOperation) revision = data.revision;
  $('revision').textContent = `REV ${revision.slice(0,12)}`;
  model = data.config;
  if (force || !dirty) { $('yaml').value = data.yaml; fillForm(data.config); markDirty(false); }
  const address = model.management.listen_address;
  $('management-address').textContent = `${address.includes(':') ? `[${address}]` : address}:${model.management.port}`;
}
async function connect() {
  const data = await api('/api/interfaces'); interfaces = data.interfaces;
  await loadConfig(!dirty);
  ready = true; setBusy(false);
}
$('config-form').addEventListener('input', () => markDirty());
$('yaml').addEventListener('input', () => markDirty());
async function validate() {
  if (!ready) return false;
  if (mode === 'form' && !$('config-form').reportValidity()) throw new Error('请检查参数范围');
  const sourceMode = mode, content = mode === 'form' ? formYaml() : $('yaml').value;
  const data = await api('/api/config/validate','POST',content);
  if (mode !== sourceMode || content !== (mode === 'form' ? formYaml() : $('yaml').value)) return false;
  $('yaml').value = data.yaml; fillForm(data.config); return true;
}
async function switchMode(next) {
  if (next === mode) return;
  try {
    if (!await validate()) return;
    mode = next;
    $('form-view').hidden = next !== 'form'; $('yaml-view').hidden = next !== 'yaml';
    $('form-tab').setAttribute('aria-selected', String(next === 'form')); $('yaml-tab').setAttribute('aria-selected', String(next === 'yaml'));
  } catch (error) { showError(error.message); }
}
$('form-tab').addEventListener('click', () => switchMode('form'));
$('yaml-tab').addEventListener('click', () => switchMode('yaml'));
$('validate').addEventListener('click', async () => {
  try { await validate(); hideMessage(); } catch (error) { showError(error.message); }
});
$('import').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 32768) throw new Error('文件超过 32 KiB');
    const content = new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
    $('yaml').value = content; markDirty(); hideMessage();
  } catch (error) { showError(error.message); }
  finally { event.target.value = ''; }
});
async function submit(path, body, reloadConfig) {
  if (!ready || submitting || pending) return;
  hideMessage();
  submitting = true;
  if (reloadConfig) markDirty(false);
  setBusy(true);
  try {
    const result = await api(path,'POST',body);
    pending = {id:result.operation_id, reloadConfig};
    submitting = false;
    await poll();
  } catch(error) {
    if (reloadConfig) markDirty();
    submitting = false; showError(error.message); setBusy(false);
  }
}
$('apply').addEventListener('click', async () => {
  if (!ready || mode === 'form' && !$('config-form').reportValidity()) return;
  await submit('/api/config/apply',mode === 'form' ? formYaml() : $('yaml').value,true);
});
$('rollback').addEventListener('click', () => submit('/api/config/rollback',undefined,true));
$('reload').addEventListener('click', async () => {
  try { await loadConfig(true); hideMessage(); } catch (error) { showError(error.message); }
});
document.querySelectorAll('[data-control]').forEach(button => button.addEventListener('click',
  () => submit('/api/relay/' + button.dataset.control,undefined,false)
));
async function poll() {
  if (polling || document.hidden) return;
  polling = true;
  try {
    if (!ready) await connect();
    const status = await api('/api/status');
    $('state').textContent = stateNames[status.state] || status.state; $('state').dataset.state = status.state;
    $('active-interface').textContent = status.upstream_interface || '未配置'; $('active-port').textContent = ':' + status.port;
    $('version').textContent = `应用 ${status.version} / 核心 ${status.core_version}`;
    $('runtime-note').textContent = status.error || '';
    $('runtime-note').hidden = !status.error;
    if (status.state === 'RETRY_WAIT') $('runtime-note').textContent += ` · ${Math.max(0,Math.ceil((status.retry_at-Date.now())/1000))} 秒后重试`;
    renderServiceStatus(status);
    if (pending && status.operation.id === pending.id && status.operation.done) {
      const result = pending; pending = null;
      const success = status.operation.outcome === 'applied';
      if (!success && result.reloadConfig) markDirty();
      await loadConfig(false, true);
      if (success) hideMessage();
      else showError((status.operation.outcome === 'failed_rolled_back' ? '应用失败，已恢复原配置：' : '应用失败，请检查核心状态：') + status.operation.error);
    } else if (pending && status.operation.id !== pending.id && !status.busy) {
      pending = null; showError('无法确认操作结果，请重新读取配置');
    }
    setBusy(status.busy || !!pending);
    const logs = await api('/api/logs'); const area = $('logs');
    const nearBottom = area.scrollTop + area.clientHeight >= area.scrollHeight - 25;
    area.textContent = logs.lines.join('\n') || '暂无日志'; if (nearBottom) area.scrollTop = area.scrollHeight;
  } catch(error) { setConnection('error', '连接异常'); showError(error.message); }
  finally { polling = false; }
}
document.addEventListener('visibilitychange',() => {if (!document.hidden) poll();});
setInterval(poll,2000);
setBusy(true);
poll();
