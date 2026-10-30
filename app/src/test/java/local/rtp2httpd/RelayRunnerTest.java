package local.rtp2httpd;

import org.junit.Test;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;

public class RelayRunnerTest {
    @Test public void launchFailuresRecoverAndDuplicateStartsDoNotSpawnAnotherCore() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        Events events = new Events();
        Child child = new Child();
        RelayRunner runner = new RelayRunner(() -> {
            if (attempts.incrementAndGet() < 3) throw new IOException("Network not ready");
            return child;
        }, events, 10, 40, 60000);
        try {
            runner.start();
            runner.start();
            assertEquals(Long.valueOf(10), events.retries.poll(2, TimeUnit.SECONDS));
            assertEquals(Long.valueOf(20), events.retries.poll(2, TimeUnit.SECONDS));
            assertTrue(events.running.await(2, TimeUnit.SECONDS));
            assertEquals(3, attempts.get());
            // EOF is not a process exit: the core can keep running without logging.
            assertNull(events.retries.poll(100, TimeUnit.MILLISECONDS));
        } finally { runner.stop(); }
        assertTrue(child.exited.await(2, TimeUnit.SECONDS));
    }

    @Test public void repeatedExitsIncludingZeroUseCappedBackoff() throws Exception {
        Events events = new Events();
        RelayRunner runner = new RelayRunner(() -> {
            Child child = new Child();
            child.exit(0);
            return child;
        }, events, 10, 40, 60000);
        try {
            runner.start();
            for (long delay : new long[] {10, 20, 40, 40, 40})
                assertEquals(Long.valueOf(delay), events.retries.poll(2, TimeUnit.SECONDS));
            assertTrue(events.fatal.isEmpty());
        } finally { runner.stop(); }
    }

    @Test public void stableRunResetsBackoff() throws Exception {
        Events events = new Events();
        AtomicInteger attempts = new AtomicInteger();
        Child stable = new Child();
        CountDownLatch stableStarted = new CountDownLatch(1);
        RelayRunner runner = new RelayRunner(() -> {
            if (attempts.incrementAndGet() < 3) throw new IOException("Temporarily unavailable");
            stableStarted.countDown();
            return stable;
        }, events, 10, 40, 30);
        try {
            runner.start();
            assertEquals(Long.valueOf(10), events.retries.poll(2, TimeUnit.SECONDS));
            assertEquals(Long.valueOf(20), events.retries.poll(2, TimeUnit.SECONDS));
            assertTrue(stableStarted.await(2, TimeUnit.SECONDS));
            assertTrue(events.running.await(2, TimeUnit.SECONDS));
            assertFalse(stable.exited.await(80, TimeUnit.MILLISECONDS));
            stable.exit(1);
            assertEquals(Long.valueOf(10), events.retries.poll(2, TimeUnit.SECONDS));
        } finally { runner.stop(); }
    }

    @Test public void stopCancelsPendingRetry() throws Exception {
        Events events = new Events();
        AtomicInteger attempts = new AtomicInteger();
        RelayRunner runner = new RelayRunner(() -> {
            attempts.incrementAndGet();
            throw new IOException("Offline");
        }, events, 200, 200, 60000);
        try {
            runner.start();
            assertNotNull(events.retries.poll(2, TimeUnit.SECONDS));
            runner.stop();
            runner.stop();
            assertNull(events.retries.poll(350, TimeUnit.MILLISECONDS));
            assertEquals(1, attempts.get());
        } finally { runner.stop(); }
    }

    @Test public void stopDuringLaunchDestroysLateChildAndDoesNotRestart() throws Exception {
        Events events = new Events();
        CountDownLatch launching = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        Child child = new Child();
        RelayRunner runner = new RelayRunner(() -> {
            launching.countDown();
            try {
                if (!release.await(2, TimeUnit.SECONDS)) throw new IOException("Test launch timed out");
            } catch (InterruptedException error) { throw new IOException(error); }
            return child;
        }, events, 10, 40, 60000);
        try {
            runner.start();
            assertTrue(launching.await(2, TimeUnit.SECONDS));
            runner.stop();
            release.countDown();
            assertTrue(child.exited.await(2, TimeUnit.SECONDS));
            assertEquals(1, child.destroys.get());
            assertEquals(1, events.running.getCount());
            assertNull(events.retries.poll(100, TimeUnit.MILLISECONDS));
        } finally { release.countDown(); runner.stop(); }
    }

    @Test public void fatalConfigurationDoesNotRetry() throws Exception {
        Events events = new Events();
        RelayRunner runner = new RelayRunner(() -> {
            throw new IllegalArgumentException("Missing native core");
        }, events, 10, 40, 60000);
        try {
            runner.start();
            assertTrue(events.fatal.poll(2, TimeUnit.SECONDS) instanceof IllegalArgumentException);
            assertNull(events.retries.poll(100, TimeUnit.MILLISECONDS));
        } finally { runner.stop(); }
    }

    @Test public void stopBeforeStartNeverLaunches() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        RelayRunner runner = new RelayRunner(() -> {
            attempts.incrementAndGet();
            return new Child();
        }, new Events(), 10, 40, 60000);
        runner.stop();
        runner.start();
        assertEquals(0, attempts.get());
    }

    @Test public void stopTerminatesARealProcessWithoutRetrying() throws Exception {
        assumeTrue(new File("/bin/sleep").canExecute());
        Events events = new Events();
        Process child = new ProcessBuilder("/bin/sleep", "30").start();
        RelayRunner runner = new RelayRunner(() -> child, events, 10, 40, 60000);
        try {
            runner.start();
            assertTrue(events.running.await(2, TimeUnit.SECONDS));
            runner.stop();
            assertTrue(child.waitFor(2, TimeUnit.SECONDS));
            assertNull(events.retries.poll(100, TimeUnit.MILLISECONDS));
        } finally { runner.stop(); child.destroyForcibly(); }
    }

    @Test public void unresponsiveChildIsForciblyTerminatedOnStop() throws Exception {
        Events events = new Events();
        AtomicInteger forced = new AtomicInteger();
        Child child = new Child() {
            @Override public void destroy() { destroys.incrementAndGet(); }
            @Override public boolean waitFor(long timeout, TimeUnit unit) throws InterruptedException {
                return forced.get() != 0 && super.waitFor(timeout, unit);
            }
            @Override public Process destroyForcibly() {
                forced.incrementAndGet();
                exit(137);
                return this;
            }
        };
        RelayRunner runner = new RelayRunner(() -> child, events, 10, 40, 60000);
        try {
            runner.start();
            assertTrue(events.running.await(2, TimeUnit.SECONDS));
            runner.stop();
            assertTrue(child.exited.await(2, TimeUnit.SECONDS));
            assertEquals(1, forced.get());
            assertEquals(1, child.destroys.get());
            assertNull(events.retries.poll(100, TimeUnit.MILLISECONDS));
        } finally { runner.stop(); }
    }

    private static final class Events implements RelayRunner.Listener {
        final BlockingQueue<Long> retries = new LinkedBlockingQueue<>();
        final BlockingQueue<Exception> fatal = new LinkedBlockingQueue<>();
        final CountDownLatch running = new CountDownLatch(1);
        @Override public void onLog(String line) { }
        @Override public void onRunning() { running.countDown(); }
        @Override public void onRetry(long delay, Exception error) { retries.add(delay); }
        @Override public void onFatal(Exception error) { fatal.add(error); }
    }

    private static class Child extends Process {
        final CountDownLatch exited = new CountDownLatch(1);
        final AtomicInteger destroys = new AtomicInteger();
        private volatile int code;
        void exit(int code) { this.code = code; exited.countDown(); }
        @Override public OutputStream getOutputStream() { return new ByteArrayOutputStream(); }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public InputStream getErrorStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public int waitFor() throws InterruptedException { exited.await(); return code; }
        @Override public boolean waitFor(long timeout, TimeUnit unit) throws InterruptedException {
            return exited.await(timeout, unit);
        }
        @Override public int exitValue() {
            if (exited.getCount() != 0) throw new IllegalThreadStateException();
            return code;
        }
        @Override public void destroy() { destroys.incrementAndGet(); exit(143); }
    }
}
