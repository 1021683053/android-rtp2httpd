package local.rtp2httpd;

import org.junit.Test;
import java.io.*;
import java.nio.file.Files;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;

public class RelayControllerTest {
    private static AppConfig config(int port) {return AppConfig.parse("management: {enabled: true}\nrelay: {upstream_interface: eth0, port: "+port+"}");}
    private static void until(java.util.function.BooleanSupplier condition) throws Exception {
        long deadline = System.nanoTime()+4_000_000_000L;
        while (!condition.getAsBoolean()) {if(System.nanoTime()>deadline) fail("Timed out"); Thread.sleep(10);}
    }
    @Test public void successfulApplySerializesCoreReplacementAndRejectsConflicts() throws Exception {
        ConfigStore store = new ConfigStore(Files.createTempDirectory("relay-apply").toFile());
        AppConfig old = config(5140), next = config(5142); store.commit(old);
        FakeRuntime runtime = new FakeRuntime(); RelayController controller = new RelayController(store,old,runtime);
        try {
            controller.start(); until(() -> runtime.active.get()==1);
            long id = controller.apply(next,old.revision());
            try {controller.apply(old,old.revision()); fail();} catch (RelayController.Conflict expected) { }
            until(() -> !Boolean.TRUE.equals(controller.status().get("busy")));
            assertEquals(next.revision(),store.read().revision()); assertEquals(next.revision(),controller.config().revision());
            assertEquals(1,runtime.maximum.get()); assertEquals(1,runtime.active.get());
            assertEquals(id,((Number)((Map<?,?>)controller.status().get("operation")).get("id")).longValue());
            try {controller.apply(old,old.revision()); fail();} catch(RelayController.Conflict expected) { }
            controller.apply(next.withRelayEnabled(false),next.revision());
            until(() -> !Boolean.TRUE.equals(controller.status().get("busy")));
            assertEquals("STOPPED",controller.status().get("state")); assertEquals(0,runtime.active.get());
        } finally {controller.close();}
        until(() -> runtime.active.get()==0);
    }
    @Test public void candidateFailureRetainsSavedConfigAndRestartsPreviousCore() throws Exception {
        ConfigStore store = new ConfigStore(Files.createTempDirectory("relay-fail").toFile()); AppConfig old = config(5140); store.commit(old);
        FakeRuntime runtime = new FakeRuntime(); runtime.failPort=5145;
        RelayController controller = new RelayController(store,old,runtime);
        try {
            controller.start(); until(() -> runtime.active.get()==1);
            controller.apply(config(5145),old.revision());
            until(() -> !Boolean.TRUE.equals(controller.status().get("busy")));
            until(() -> runtime.active.get()==1);
            assertEquals(old.revision(),store.read().revision()); assertEquals(old.revision(),controller.config().revision());
            assertEquals("failed_rolled_back",((Map<?,?>)controller.status().get("operation")).get("outcome"));
            assertEquals(1,runtime.maximum.get());
        } finally {controller.close();}
        until(() -> runtime.active.get()==0);
    }
    @Test public void waitForConfigDoesNotLaunchAndManagementChangesAreRejected() throws Exception {
        ConfigStore store = new ConfigStore(Files.createTempDirectory("relay-wait").toFile()); AppConfig initial = AppConfig.parse("management: {enabled: true}");store.commit(initial);
        FakeRuntime runtime = new FakeRuntime();RelayController controller = new RelayController(store,initial,runtime);
        try {
            controller.start();until(() -> "WAITING_CONFIG".equals(controller.status().get("state")));
            assertEquals(0,runtime.active.get());
            try {controller.apply(AppConfig.defaults(),initial.revision());fail();}catch(IllegalArgumentException expected){}
            for(int i=0;i<300;i++)controller.log("token=secret http://user:pass@host/a "+i);
            List<?> lines=(List<?>)controller.logs();assertEquals(256,lines.size());assertFalse(lines.get(0).toString().contains("secret"));assertFalse(lines.get(0).toString().contains("user:pass"));
        } finally {controller.close();}
    }
    @Test public void failedTerminationNeverStartsAReplacementOrClaimsRollback() throws Exception {
        ConfigStore store = new ConfigStore(Files.createTempDirectory("relay-stubborn").toFile());
        AppConfig old = config(5140); store.commit(old);
        AtomicInteger active = new AtomicInteger(1), launches = new AtomicInteger();
        Child stubborn = new Child(active) {
            @Override public void destroy() { }
            @Override public Process destroyForcibly() { return this; }
            @Override public boolean waitFor(long time, TimeUnit unit) { return false; }
        };
        RelayController controller = new RelayController(store, old, new RelayController.Runtime() {
            public Process launch(AppConfig config) { launches.incrementAndGet(); return stubborn; }
            public boolean ready(AppConfig config) { return true; }
        });
        try {
            controller.start(); until(() -> "RUNNING".equals(controller.status().get("state")));
            controller.apply(config(5142), old.revision());
            until(() -> !Boolean.TRUE.equals(controller.status().get("busy")));
            assertEquals(1, launches.get());
            assertEquals(old.revision(), store.read().revision());
            assertEquals("ERROR", controller.status().get("state"));
            assertEquals("failed", ((Map<?,?>) controller.status().get("operation")).get("outcome"));
        } finally { controller.close(); stubborn.finish(); }
    }
    @Test public void automaticRetryClearsRecoveredRuntimeError() throws Exception {
        ConfigStore store = new ConfigStore(Files.createTempDirectory("relay-retry").toFile());
        AppConfig initial = config(5140); store.commit(initial);
        AtomicInteger attempts = new AtomicInteger(), active = new AtomicInteger();
        RelayController controller = new RelayController(store, initial, new RelayController.Runtime() {
            public Process launch(AppConfig config) throws IOException {
                if (attempts.incrementAndGet() == 1) throw new IOException("Network unavailable");
                active.incrementAndGet(); return new Child(active);
            }
            public boolean ready(AppConfig config) { return true; }
        });
        try {
            controller.start();
            until(() -> "RETRY_WAIT".equals(controller.status().get("state")));
            assertNotNull(controller.status().get("error"));
            until(() -> "RUNNING".equals(controller.status().get("state")));
            assertNull(controller.status().get("error"));
            assertEquals(0L, controller.status().get("retry_at"));
            assertEquals(initial.revision(), store.read().revision());
        } finally { controller.close(); }
        until(() -> active.get() == 0);
    }

    private static final class FakeRuntime implements RelayController.Runtime {
        final AtomicInteger active=new AtomicInteger(),maximum=new AtomicInteger(); int failPort;
        public Process launch(AppConfig config)throws IOException {
            if(config.port==failPort)throw new IOException("Port unavailable");
            int count=active.incrementAndGet();maximum.accumulateAndGet(count,Math::max);
            return new Child(active);
        }
        public boolean ready(AppConfig config){return true;}
    }
    private static class Child extends Process {
        final AtomicInteger active;final CountDownLatch exited=new CountDownLatch(1);
        Child(AtomicInteger active){this.active=active;}
        public OutputStream getOutputStream(){return new ByteArrayOutputStream();}
        public InputStream getInputStream(){return new ByteArrayInputStream(new byte[0]);}
        public InputStream getErrorStream(){return new ByteArrayInputStream(new byte[0]);}
        public int waitFor()throws InterruptedException{exited.await();return 0;}
        public boolean waitFor(long time,TimeUnit unit)throws InterruptedException{return exited.await(time,unit);}
        public int exitValue(){if(exited.getCount()>0)throw new IllegalThreadStateException();return 0;}
        synchronized void finish(){if(exited.getCount()>0){active.decrementAndGet();exited.countDown();}}
        public void destroy(){finish();}
    }
}
