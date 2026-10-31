const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../app/src/main/assets/management/app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../../app/src/main/assets/management/index.html'), 'utf8');
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve}; };

async function browser() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {id, value:'', disabled:false, hidden:true, checked:false,
      textContent:'', dataset:{}, options:[], listeners:{}, scrollTop:0, clientHeight:0, scrollHeight:0,
      addEventListener(name, fn) {this.listeners[name] = fn;}, setAttribute() {}, reportValidity() {return true;},
      replaceChildren(...options) {this.options = options;}, add(option) {this.options.push(option);}});
    return elements.get(id);
  };
  for (const match of html.matchAll(/id="([^"]+)"/g)) element(match[1]);
  const controls = ['start','stop','restart'].map(action => Object.assign(element(action), {dataset:{control:action}}));
  const editable = ['enabled','upstream','listen','port','maxclients','verbose','yaml','import','validate','form-tab','yaml-tab'].map(element);
  let saved = {schema_version:1, management:{enabled:true,listen_address:'127.0.0.1',port:5141},
    relay:{enabled:true,upstream_interface:'eth0',listen_interface:null,port:5140,maxclients:5,verbose:2,workers:1}};
  const yaml = config => 'schema_version: 1\nmanagement:\n  port: 5141\nrelay:\n  port: '+config.relay.port+'\n';
  let operation = {id:0,done:true,outcome:'idle'};
  const requests = [], gates = new Map();
  const response = (data, ok=true) => ({ok,status:ok?200:400,json:async()=>data});
  const context = vm.createContext({document:{hidden:false, getElementById:element, addEventListener() {},
    querySelectorAll:selector => selector==='[data-control]' ? controls : editable},
    Option:function(text,value) {return {text,value};}, AbortController, TextDecoder,
    setTimeout:()=>0, clearTimeout() {}, setInterval:()=>0,
    fetch:async (url, options) => {
      requests.push({url, body:options.body, headers:options.headers});
      const gate = gates.get(url);
      if (gate) {gates.delete(url); const result=await gate.promise; if (result) return result;}
      if (url==='/api/interfaces') return response({interfaces:[{name:'eth0',addresses:['192.168.1.2'],up:true}]});
      if (url==='/api/config') return response({config:saved,yaml:yaml(saved),revision:'revision'});
      if (url==='/api/status') return response({state:'RUNNING',port:saved.relay.port,operation,busy:false});
      if (url==='/api/logs') return response({lines:[]});
      const port = Number(options.body?.match(/relay:[\s\S]*?port:\s*(\d+)/)?.[1]);
      const config = {...saved,relay:{...saved.relay,port}};
      if (url==='/api/config/validate') return response({config,yaml:yaml(config)});
      if (url==='/api/config/apply') {saved=config; operation={id:operation.id+1,done:true,outcome:'applied'}; return response({operation_id:operation.id});}
      throw new Error('Unexpected request '+url);
    }});
  vm.runInContext(source, context);
  for (let n=0; n<20 && element('apply').disabled; n++) await new Promise(setImmediate);
  assert.equal(element('apply').disabled,false);
  return {element, context, requests, response,
    defer(url) {const gate=deferred(); gates.set(url,gate); return gate;},
    click(id) {const item=element(id); return item.disabled ? Promise.resolve() : item.listeners.click();},
    edit(id,value) {if (!element(id).disabled) {element(id).value=value; element('config-form').listeners.input();}},
    editable() {for (const item of editable) assert.equal(item.disabled,false,item.id);}
  };
}

test('save submits immediately and keeps edits made during the request', async () => {
  const b=await browser(), gate=b.defer('/api/config/apply');
  const saving=b.click('apply'); b.editable();
  assert.equal(b.requests.some(r=>r.url==='/api/config/validate'),false);
  const first=b.requests.find(r=>r.url==='/api/config/apply');
  assert.match(first.body,/port: 5140/);
  assert.equal(first.headers['If-Match'],undefined);
  b.edit('port',5142);
  await b.context.poll(); b.editable();
  assert.equal(b.element('apply').disabled,true);
  gate.resolve(); await saving;
  assert.equal(Number(b.element('port').value),5142);
  assert.equal(b.element('message').hidden,true);
  await b.click('apply');
  assert.match(b.requests.filter(r=>r.url==='/api/config/apply').at(-1).body,/port: 5142/);
  assert.equal(Number(b.element('port').value),5142);
});

test('old validation cannot replace later input or change modes', async () => {
  const b=await browser(), gate=b.defer('/api/config/validate');
  const switching=b.click('yaml-tab'); b.editable();
  b.edit('port',5142);
  await b.click('apply');
  gate.resolve(); await switching;
  assert.equal(Number(b.element('port').value),5142);
  assert.equal(b.element('yaml-view').hidden,true);
  await b.click('yaml-tab');
  assert.equal(b.element('yaml-view').hidden,false);
  const formatting=b.defer('/api/config/validate'), work=b.click('validate');
  b.editable(); b.edit('yaml','relay: {port: 5144}');
  formatting.resolve(); await work;
  assert.equal(b.element('yaml').value,'relay: {port: 5144}');
});

test('failed save preserves input through subsequent status refreshes', async () => {
  const b=await browser(); b.edit('port',5142);
  const gate=b.defer('/api/config/apply'), work=b.click('apply'); b.editable();
  gate.resolve(b.response({error:'Invalid configuration'},false)); await work;
  await b.context.poll(); b.editable();
  assert.equal(Number(b.element('port').value),5142);
  assert.equal(b.element('message').textContent,'Invalid configuration');
  assert.equal(b.element('apply').disabled,false);
});

test('file import and explicit reload leave editing enabled', async () => {
  const b=await browser();
  await b.click('yaml-tab');
  const file=deferred(), input=b.element('import'); input.files=[{size:10,arrayBuffer:()=>file.promise}];
  const importing=input.listeners.change({target:input}); b.editable();
  file.resolve(Buffer.from('relay: {port: 5142}')); await importing;
  assert.equal(b.element('yaml').value,'relay: {port: 5142}');
  const gate=b.defer('/api/config'), reload=b.click('reload'); b.editable();
  gate.resolve(); await reload;
  assert.match(b.element('yaml').value,/5140/);
});
