package local.rtp2httpd;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** One mutation queue owns core replacement and the durable configuration. */
final class RelayController implements AutoCloseable {
    interface Runtime {
        Process launch(AppConfig config) throws IOException;
        boolean ready(AppConfig config) throws IOException;
    }
    private final ConfigStore store;
    private final Runtime runtime;
    private final ExecutorService queue = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "config-control"); thread.setDaemon(true); return thread;
    });
    private final AtomicBoolean busy = new AtomicBoolean();
    private final ArrayDeque<String> logs = new ArrayDeque<>();
    private volatile AppConfig config;
    private volatile RelayRunner runner;
    private volatile boolean closed;
    private volatile long generation;
    private volatile String state = "STOPPED";
    private volatile String error;
    private volatile String candidateError;
    private volatile long retryAt;
    private volatile Map<String, Object> operation = Json.object("id", 0, "done", true, "outcome", "idle");
    private long sequence;

    RelayController(ConfigStore store, AppConfig config, Runtime runtime) {
        this.store = store; this.config = config; this.runtime = runtime;
    }

    synchronized void start() { if (!closed) queue.execute(() -> launch(config, false)); }
    AppConfig config() { return config; }

    synchronized Map<String, Object> status() {
        return Json.object("state", state, "revision", config.revision(), "error", error,
            "retry_at", retryAt, "operation", operation, "busy", busy.get(),
            "upstream_interface", config.upstreamInterface, "port", config.port,
            "version", "3.17.2", "core_version", "3.17.2");
    }

    synchronized void log(String line) {
        // The core never receives management credentials. Keep each record and the ring bounded.
        String safe = line.substring(0, Math.min(512, line.length()))
            .replaceAll("(?i)authorization[=:][^\\r\\n]*", "authorization=[redacted]")
            .replaceAll("(?i)(token|password|secret|authorization)([=:]\\s*)[^\\s&]+", "$1$2[redacted]")
            .replaceAll("((?:https?|rtsp)://)[^/\\s@]+@", "$1[redacted]@");
        logs.addLast(safe);
        while (logs.size() > 256) logs.removeFirst();
    }

    synchronized Object logs() { return new ArrayList<>(logs); }

    synchronized long apply(AppConfig candidate, String expectedRevision) {
        if (closed) throw new IllegalStateException("服务正在停止");
        if (!config.revision().equals(expectedRevision)) throw new Conflict("配置已更新，请重新读取后再保存");
        if (!config.sameManagement(candidate))
            throw new IllegalArgumentException("管理地址和端口需通过 ADB 停止服务后修改，网页仅应用转发配置");
        if (!busy.compareAndSet(false, true)) throw new Conflict("另一项配置操作尚未完成");
        long id = ++sequence;
        operation = Json.object("id", id, "done", false, "outcome", "applying");
        queue.execute(() -> replace(id, candidate));
        return id;
    }

    AppConfig previous() throws IOException { return store.previous(); }

    private void replace(long id, AppConfig candidate) {
        AppConfig old = config;
        boolean stopped = false;
        try {
            store.stage(candidate);
            state = "APPLYING";
            stopChild(); stopped = true;
            candidateError = null;
            launch(candidate, true);
            if (candidate.relayEnabled && candidate.upstreamInterface != null) {
                long deadline = System.nanoTime() + 10_000_000_000L;
                long healthySince = 0;
                while (!closed) {
                    if (candidateError != null) throw new IOException(candidateError);
                    RelayRunner child = runner;
                    boolean ready = child != null && child.isAlive() && runtime.ready(candidate);
                    if (ready) {
                        if (healthySince == 0) healthySince = System.nanoTime();
                        if (System.nanoTime() - healthySince >= 750_000_000L) break;
                    } else healthySince = 0;
                    if (System.nanoTime() >= deadline) throw new IOException("核心启动检测超时（10 秒）");
                    Thread.sleep(100);
                }
            }
            if (closed) throw new InterruptedException("服务已停止");
            if (candidateError != null) throw new IOException(candidateError);
            store.commit(candidate);
            config = candidate;
            error = null;
            if (runner != null) state = "RUNNING";
            operation = Json.object("id", id, "done", true, "outcome", "applied");
        } catch (Exception failure) {
            if ("APPLYING".equals(state)) state = "ERROR";
            String failureReason = message(failure);
            error = failureReason;
            log("配置应用失败：" + error);
            try { store.discardPending(); } catch (IOException ignored) { }
            boolean restored = !stopped && !"ERROR".equals(state) && !closed;
            if (stopped && !closed) {
                try { stopChild(); launch(old, false); restored = true; }
                catch (Exception cleanup) { state = "ERROR"; log("恢复失败：" + message(cleanup)); }
            }
            operation = Json.object("id", id, "done", true, "outcome", restored ? "failed_rolled_back" : "failed", "error", failureReason);
        } finally { busy.set(false); }
    }

    private synchronized void launch(AppConfig target, boolean candidate) {
        if (closed) return;
        retryAt = 0;
        if (!target.relayEnabled) { state = "STOPPED"; return; }
        if (target.upstreamInterface == null) { state = "WAITING_CONFIG"; return; }
        state = candidate ? "APPLYING" : "STARTING";
        final long owner = ++generation;
        RelayRunner child = new RelayRunner(() -> runtime.launch(target), new RelayRunner.Listener() {
            private boolean current() { return !closed && generation == owner; }
            @Override public void onLog(String line) { if (current()) log(line); }
            @Override public void onRunning() {
                synchronized (RelayController.this) {
                    if (current()) { if (!busy.get()) state = "RUNNING"; error = null; retryAt = 0; }
                }
            }
            @Override public void onRetry(long delay, Exception failure) {
                synchronized (RelayController.this) {
                    if (!current()) return;
                    String reason = message(failure);
                    if (candidate && busy.get()) candidateError = reason;
                    error = reason; retryAt = System.currentTimeMillis() + delay;
                    if (!busy.get()) state = "RETRY_WAIT";
                    log("核心重试：" + reason);
                }
            }
            @Override public void onFatal(Exception failure) {
                synchronized (RelayController.this) {
                    if (!current()) return;
                    error = message(failure); candidateError = error; state = "ERROR"; log(error);
                }
            }
        });
        runner = child; child.start();
    }

    private void stopChild() throws InterruptedException, IOException {
        RelayRunner child;
        synchronized (this) { ++generation; child = runner; }
        if (child == null) return;
        child.stop();
        if (!child.awaitStopped(8000)) throw new IOException("旧核心未退出，拒绝并行启动新核心");
        runner = null; retryAt = 0;
    }

    @Override public synchronized void close() {
        closed = true; ++generation;
        RelayRunner child = runner; if (child != null) child.stop();
        queue.shutdownNow(); state = "STOPPED";
    }

    private static String message(Exception error) {
        String text = error.getMessage(); return text == null ? error.getClass().getSimpleName() : text;
    }
    static final class Conflict extends IllegalStateException { Conflict(String message) { super(message); } }
}
