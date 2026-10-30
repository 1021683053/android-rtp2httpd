package local.rtp2httpd;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Serializes process creation, retries and cleanup away from Android's main thread. */
final class RelayRunner {
    interface Launcher { Process start() throws IOException; }
    interface Listener {
        void onLog(String line);
        void onRunning();
        void onRetry(long delayMs, Exception error);
        void onFatal(Exception error);
    }

    private final Launcher launcher;
    private final Listener listener;
    private final ScheduledThreadPoolExecutor executor;
    private final AtomicBoolean stopped = new AtomicBoolean();
    private final AtomicBoolean started = new AtomicBoolean();
    private final long initialDelayMs;
    private final long maxDelayMs;
    private final long stableRunMs;
    private long nextDelayMs;
    private Process process;

    RelayRunner(Launcher launcher, Listener listener) {
        this(launcher, listener, 1000, 60000, 60000);
    }

    RelayRunner(Launcher launcher, Listener listener, long initialDelayMs,
                long maxDelayMs, long stableRunMs) {
        this.launcher = launcher;
        this.listener = listener;
        this.initialDelayMs = initialDelayMs;
        this.maxDelayMs = maxDelayMs;
        this.stableRunMs = stableRunMs;
        nextDelayMs = initialDelayMs;
        executor = new ScheduledThreadPoolExecutor(1, task -> daemon("relay-control", task));
        executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
        executor.setRemoveOnCancelPolicy(true);
    }

    void start() {
        if (started.compareAndSet(false, true)) dispatch(this::launch);
    }

    void stop() {
        if (!stopped.compareAndSet(false, true)) return;
        // Queued before shutdown so even a start currently in progress is cleaned up.
        executor.execute(this::destroyChild);
        executor.shutdown();
    }

    private void dispatch(Runnable task) {
        if (stopped.get()) return;
        try { executor.execute(task); }
        catch (RejectedExecutionException ignored) { /* Stop won the race. */ }
    }

    private void launch() {
        if (stopped.get()) return;
        try {
            Process child = launcher.start();
            process = child;
            if (stopped.get()) { destroyChild(); return; }
            long startedAt = System.nanoTime();
            listener.onRunning();
            daemon("relay-log", () -> readLogs(child)).start();
            // Waiting must not depend on EOF: a surviving worker could keep stdout open.
            daemon("relay-wait", () -> {
                try {
                    int exit = child.waitFor();
                    long elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt);
                    dispatch(() -> {
                        if (process != child) return;
                        process = null;
                        closeStreams(child);
                        if (elapsedMs >= stableRunMs) nextDelayMs = initialDelayMs;
                        retry(new IOException("Core exited: " + exit));
                    });
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    dispatch(() -> {
                        destroyChild();
                        listener.onFatal(error);
                    });
                }
            }).start();
        } catch (IOException error) {
            retry(error);
        } catch (RuntimeException error) {
            destroyChild();
            listener.onFatal(error);
        }
    }

    private void retry(Exception error) {
        if (stopped.get()) return;
        long delay = nextDelayMs;
        nextDelayMs = Math.min(maxDelayMs, nextDelayMs * 2);
        listener.onRetry(delay, error);
        // stop() can race with a failure; shutdown cancels any accepted delayed retry.
        try { executor.schedule(this::launch, delay, TimeUnit.MILLISECONDS); }
        catch (RejectedExecutionException ignored) { /* Already stopped. */ }
    }

    private void readLogs(Process child) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(child.getInputStream()))) {
            String line;
            while (!stopped.get() && (line = reader.readLine()) != null) listener.onLog(line);
        } catch (IOException error) {
            if (!stopped.get()) listener.onLog("Core log stream closed: " + error.getMessage());
        }
    }

    private void destroyChild() {
        Process child = process;
        process = null;
        if (child == null) return;
        child.destroy();
        try {
            if (!child.waitFor(5, TimeUnit.SECONDS)) {
                child.destroyForcibly();
                if (!child.waitFor(1, TimeUnit.SECONDS))
                    listener.onLog("Core did not exit after forced termination");
            }
        } catch (InterruptedException error) {
            child.destroyForcibly();
            Thread.currentThread().interrupt();
        } finally { closeStreams(child); }
    }

    private static void closeStreams(Process child) {
        try { child.getOutputStream().close(); } catch (IOException ignored) { }
        try { child.getInputStream().close(); } catch (IOException ignored) { }
        try { child.getErrorStream().close(); } catch (IOException ignored) { }
    }

    private static Thread daemon(String name, Runnable task) {
        Thread thread = new Thread(task, name);
        thread.setDaemon(true);
        return thread;
    }
}
