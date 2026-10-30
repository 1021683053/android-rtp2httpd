package local.rtp2httpd;

import org.junit.Test;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Collections;
import static org.junit.Assert.*;

public class AppConfigTest {
    @org.junit.Test public void managementOnDefaultRelayPortCanRestoreAndRecover() throws Exception {
        java.io.File directory = java.nio.file.Files.createTempDirectory("port-restore").toFile();
        ConfigStore store = new ConfigStore(directory);
        AppConfig saved = AppConfig.parse("management: {enabled: true, port: 5140}\nrelay: {port: 5143}");
        store.commit(saved);
        org.junit.Assert.assertEquals(saved.revision(), store.read().revision());
        java.util.Map<String,Object> binding = new java.util.LinkedHashMap<>();
        binding.put("management_enabled", true); binding.put("management_port", 5140);
        AppConfig recovered = AppConfig.fallback(binding, java.util.Collections.emptyMap());
        org.junit.Assert.assertEquals(5140, recovered.managementPort);
        org.junit.Assert.assertEquals(5142, recovered.port);
        AppConfig overridden = AppConfig.fallback(binding, java.util.Collections.singletonMap("port", 5145));
        org.junit.Assert.assertEquals(5145, overridden.port);
    }

    @Test public void defaultsRoundTripAndExplicitOverridesPreserveSavedValues() {
        AppConfig config = AppConfig.parse("relay:\n  port: 8080\n  upstream_interface: eth0\n");
        assertEquals(8080, config.override(Collections.singletonMap("verbose", 3)).port);
        assertEquals(5, config.maxClients); assertEquals(2, config.verbose);
        assertEquals(config.revision(), AppConfig.parse(config.yaml()).revision());
        assertFalse(config.yaml().contains("token"));
    }
    @Test public void strictSchemaRejectsMalformedUnsafeOrUnsupportedYaml() {
        for (String text : new String[]{"", "[]", "relay: [1]", "relay: {port: 20}", "relay: {verbose: 5}",
            "relay: {maxclients: 0}", "relay: {port: '5140'}", "relay: {enabled: null}",
            "schema_version: 2", "relay: {workers: 2}", "relay: {shell: x}", "token: abc",
            "relay: {port: 5140, port: 5142}", "relay: &a {port: 5140}\nmanagement: *a",
            "relay: {<<: {port: 5140}}", "relay: !!map {port: 5140}",
            "relay: !!java/object:java.lang.ProcessBuilder {}", "management: {listen_address: example.com}",
            "management: {enabled: true, port: 5140}", "relay: {upstream_interface: 'eth0;id'}",
            "relay: {port: [[[[[[[1]]]]]]]}"}) {
            try { AppConfig.parse(text); fail("Accepted: " + text); } catch (IllegalArgumentException expected) { }
        }
        try {AppConfig.parse(String.join("",Collections.nCopies(32769,"x"))); fail();} catch (IllegalArgumentException expected) { }
    }
    @Test public void pendingNeverBecomesSavedAndBackupSurvivesUnchangedCommits() throws Exception {
        File directory = Files.createTempDirectory("relay-config").toFile();
        ConfigStore store = new ConfigStore(directory);
        AppConfig old = AppConfig.parse("relay: {port: 5142}"), current = AppConfig.parse("relay: {port: 5143}");
        store.commit(old); store.stage(current);
        assertEquals(old.revision(), new ConfigStore(directory).read().revision());
        store.commit(current); store.commit(current);
        assertEquals(old.revision(), store.previous().revision());
        assertFalse(new File(directory,"config.pending.yml").exists());
        Files.write(new File(directory,"config.yml").toPath(), "broken: [".getBytes(StandardCharsets.UTF_8));
        assertEquals(old.revision(), store.read().revision());
        store.commit(current); assertEquals(current.revision(), store.read().revision());
    }
    @Test public void invalidFilesCanBeRepairedAndWriteFailurePreservesPrimary() throws Exception {
        File directory = Files.createTempDirectory("relay-repair").toFile();
        Files.write(new File(directory,"config.yml").toPath(), "bad: [".getBytes(StandardCharsets.UTF_8));
        ConfigStore store = new ConfigStore(directory);
        try {store.read(); fail();} catch (IOException expected) { }
        store.commit(AppConfig.defaults());
        String revision = store.read().revision();
        assertTrue(new File(directory,"config.yml.tmp").mkdir());
        try {store.commit(AppConfig.parse("relay: {port: 8080}")); fail();} catch (IOException expected) { }
        assertEquals(revision, store.read().revision());
    }
}
