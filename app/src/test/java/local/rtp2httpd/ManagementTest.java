package local.rtp2httpd;

import org.junit.Test;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import local.rtp2httpd.ManagementServer.Request;
import local.rtp2httpd.ManagementServer.Response;
import static org.junit.Assert.*;

public class ManagementTest {
    private static Request request(String method, String path, String body) {
        Map<String,String> headers = new HashMap<>(); headers.put("host","127.0.0.1:5141");
        return new Request(method,path,headers,body.getBytes(StandardCharsets.UTF_8));
    }
    @Test public void framingRejectsSmugglingOversizeAndInvalidUtf8() throws Exception {
        for (String wire : new String[]{
            "POST / HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 1\r\n\r\na",
            "POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
            "POST / HTTP/1.1\r\nContent-Length: 32769\r\n\r\n",
            "POST / HTTP/1.1\r\nContent-Length: -1\r\n\r\n",
            "GET / HTTP/1.1\n\n", "GET / HTTP/1.1\r\n Host: abc\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: abc\r\nExpect: 100-continue\r\n\r\n"}) {
            try {Request.read(new ByteArrayInputStream(wire.getBytes(StandardCharsets.US_ASCII))); fail(wire);} catch (IOException expected) { }
        }
        Request valid = Request.read(new ByteArrayInputStream("POST /api/config/validate HTTP/1.1\r\nHost: 127.0.0.1:5141\r\nContent-Length: 2\r\n\r\nok".getBytes(StandardCharsets.US_ASCII)));
        assertEquals("ok", valid.text());
        try {new Request("POST","/",new HashMap<>(),new byte[]{(byte)0xff}).text(); fail();} catch (IOException expected) { }
    }
    @Test public void hostOriginAndIpv6RulesBlockCrossSiteAccess() throws Exception {
        Request valid = request("POST","/api/config/validate","relay: {}");
        ManagementApi.checkOrigin(valid,"127.0.0.1",5141);
        valid.headers.put("host","[::1]:5141"); ManagementApi.checkOrigin(valid,"0:0:0:0:0:0:0:1",5141);
        valid.headers.put("host","localhost:5141"); ManagementApi.checkOrigin(valid,"127.0.0.1",5141);
        for (String host : new String[]{"attacker.test:5141","127.0.0.2:5141","127.0.0.1:9999"}) {
            valid.headers.put("host",host);
            try {ManagementApi.checkOrigin(valid,"127.0.0.1",5141); fail();} catch (IOException expected) { }
        }
        valid.headers.put("host","127.0.0.1:5141"); valid.headers.put("origin","http://evil.test");
        try {ManagementApi.checkOrigin(valid,"127.0.0.1",5141); fail();} catch (IOException expected) { }
    }
    @Test public void apiWorksWithoutCredentialsAndStillRejectsCrossSiteWritesAndStaleRevision() throws Exception {
        AppConfig config = AppConfig.parse("management: {enabled: true}\nrelay: {enabled: false}");
        ConfigStore store = new ConfigStore(Files.createTempDirectory("relay-api").toFile()); store.commit(config);
        RelayController controller = new RelayController(store, config, new RelayController.Runtime() {
            public Process launch(AppConfig config) { throw new AssertionError("Disabled core must not launch"); }
            public boolean ready(AppConfig config) { return false; }
        });
        ManagementApi api = new ManagementApi(controller, name -> "asset".getBytes(StandardCharsets.UTF_8));
        try {
            for (String path : new String[]{"/", "/api/status", "/api/config", "/api/logs", "/api/interfaces", "/api/config/export"}) {
                Response response = api.handle(request("GET", path, ""), "127.0.0.1", 5141);
                assertEquals(path, 200, response.status);
                assertFalse(response.headers.containsKey("Set-Cookie"));
            }
            for (String method : new String[]{"GET", "POST", "DELETE"})
                assertEquals(404, api.handle(request(method, "/api/session", ""), "127.0.0.1", 5141).status);
            assertEquals(200, api.handle(request("POST", "/api/config/validate", config.yaml()), "127.0.0.1", 5141).status);
            Request write = request("POST", "/api/config/apply", config.yaml());
            write.headers.put("if-match", config.revision());
            write.headers.put("origin", "http://evil.test");
            assertEquals(403, api.handle(write, "127.0.0.1", 5141).status);
            write.headers.remove("origin"); write.headers.put("sec-fetch-site", "cross-site");
            assertEquals(403, api.handle(write, "127.0.0.1", 5141).status);
            write.headers.remove("sec-fetch-site"); write.headers.put("if-match", "stale");
            assertEquals(409, api.handle(write, "127.0.0.1", 5141).status);
            write.headers.put("if-match", config.revision()); write.headers.put("origin", "http://127.0.0.1:5141");
            assertEquals(202, api.handle(write, "127.0.0.1", 5141).status);
            Response data = api.handle(request("GET", "/api/config", ""), "127.0.0.1", 5141);
            ByteArrayOutputStream output = new ByteArrayOutputStream(); ManagementServer.write(output, data);
            String wire = output.toString("UTF-8");
            assertTrue(wire.contains("frame-ancestors 'none'")); assertFalse(wire.contains("Access-Control-Allow-Origin"));
        } finally { controller.close(); }
    }
    @Test public void crossSiteTopLevelNavigationCanOpenWorkspaceButNotApi() throws Exception {
        Request page = request("GET", "/", "");
        page.headers.put("sec-fetch-site", "cross-site");
        page.headers.put("sec-fetch-mode", "navigate");
        page.headers.put("sec-fetch-dest", "document");
        ManagementApi.checkOrigin(page, "127.0.0.1", 5141);
        Request api = new Request("GET", "/api/config", page.headers, new byte[0]);
        try { ManagementApi.checkOrigin(api, "127.0.0.1", 5141); fail(); }
        catch (ManagementServer.HttpError expected) { assertEquals(403, expected.status); }
        page.headers.put("host", "evil.test:5141");
        try { ManagementApi.checkOrigin(page, "127.0.0.1", 5141); fail(); }
        catch (ManagementServer.HttpError expected) { assertEquals(403, expected.status); }
    }
}
