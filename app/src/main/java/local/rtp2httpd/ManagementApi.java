package local.rtp2httpd;

import java.io.IOException;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import local.rtp2httpd.ManagementServer.Request;
import local.rtp2httpd.ManagementServer.Response;
import local.rtp2httpd.ManagementServer.HttpError;

/** HTTP contract independent of Android and the socket transport. */
final class ManagementApi {
    private final RelayController controller;
    private final ManagementServer.Assets assets;
    ManagementApi(RelayController controller, ManagementServer.Assets assets) {
        this.controller = controller; this.assets = assets;
    }

    Response handle(Request request, String local, int port) throws IOException {
        try {
            checkOrigin(request, local, port);
            if (request.method.equals("GET") && (request.path.equals("/") || request.path.equals("/app.js") || request.path.equals("/style.css"))) {
                String name = request.path.equals("/") ? "index.html" : request.path.substring(1);
                String type = name.endsWith("html") ? "text/html" : name.endsWith("js") ? "text/javascript" : "text/css";
                return new Response(200, type + "; charset=utf-8", assets.read(name));
            }
            String route = request.method + " " + request.path;
            switch (route) {
                case "GET /api/status": return Response.json(200, controller.status());
                case "GET /api/logs": return Response.json(200, Json.object("lines", controller.logs()));
                case "GET /api/interfaces": return Response.json(200, Json.object("interfaces", interfaces()));
                case "GET /api/config": return config(controller.config());
                case "GET /api/config/export":
                    Response export = new Response(200, "application/yaml; charset=utf-8", controller.config().yaml().getBytes(StandardCharsets.UTF_8));
                    export.headers.put("Content-Disposition", "attachment; filename=rtp2httpd.yml"); return export;
                case "POST /api/config/validate": return config(AppConfig.parse(request.text()));
                case "POST /api/config/apply": return apply(AppConfig.parse(request.text()), request);
                case "POST /api/config/rollback":
                    try { return apply(controller.previous(), request); }
                    catch (IOException failure) { throw new IllegalArgumentException("没有可用的上一份配置"); }
                case "POST /api/relay/start": return apply(controller.config().withRelayEnabled(true), request);
                case "POST /api/relay/stop": return apply(controller.config().withRelayEnabled(false), request);
                case "POST /api/relay/restart": return apply(controller.config(), request);
                default: throw new HttpError(404, "接口不存在");
            }
        } catch (RelayController.Conflict error) { return Response.json(409, Json.object("error", error.getMessage()));
        } catch (IllegalArgumentException error) { return Response.json(400, Json.object("error", error.getMessage()));
        } catch (HttpError error) { return Response.json(error.status, Json.object("error", error.getMessage())); }
    }

    private Response apply(AppConfig config, Request request) {
        return Response.json(202, Json.object("operation_id", controller.apply(config, request.headers.get("if-match"))));
    }
    private static Response config(AppConfig config) {
        return Response.json(200, Json.object("config", config.toMap(), "yaml", config.yaml(), "revision", config.revision()));
    }
    static void checkOrigin(Request request, String local, int port) throws HttpError {
        String host = request.headers.get("host");
        if (!validHost(host, local, port)) throw new HttpError(403, "Host 不符合当前管理地址，请使用 IP 地址访问");
        // A normal top-level link to the public workspace is safe. Fetch Metadata
        // can label that navigation cross-site; API fetches remain constrained.
        if (request.method.equals("GET") && request.path.equals("/")
            && "navigate".equals(request.headers.get("sec-fetch-mode"))
            && "document".equals(request.headers.get("sec-fetch-dest"))) return;
        String origin = request.headers.get("origin");
        if (origin != null && !origin.equals("http://" + host)) throw new HttpError(403, "不允许跨站访问");
        String site = request.headers.get("sec-fetch-site");
        if ("cross-site".equals(site)) throw new HttpError(403, "不允许跨站访问");
    }
    private static boolean validHost(String host, String local, int port) {
        if (host == null) return false;
        String address, suffix;
        if (host.startsWith("[")) {
            int end = host.indexOf(']'); if (end < 0) return false;
            address = host.substring(1, end); suffix = host.substring(end + 1);
        } else {
            int colon = host.indexOf(':');
            address = colon < 0 ? host : host.substring(0, colon); suffix = colon < 0 ? "" : host.substring(colon);
        }
        if (!(":" + port).equals(suffix) && !(port == 80 && suffix.isEmpty())) return false;
        try {
            InetAddress actual = InetAddress.getByName(local);
            if ("localhost".equals(address)) return actual.isLoopbackAddress();
            if (!address.matches("[0-9a-fA-F:.]+") || address.indexOf(':') < 0 && !address.matches("[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+")) return false;
            return java.util.Arrays.equals(actual.getAddress(), InetAddress.getByName(address).getAddress());
        } catch (IOException failure) { return false; }
    }
    private static List<Object> interfaces() throws IOException {
        List<Object> result = new ArrayList<>();
        java.util.Enumeration<NetworkInterface> enumeration = NetworkInterface.getNetworkInterfaces();
        if (enumeration == null) return result;
        for (NetworkInterface nic : Collections.list(enumeration)) {
            List<String> addresses = new ArrayList<>();
            for (InetAddress ip : Collections.list(nic.getInetAddresses())) addresses.add(ip.getHostAddress());
            result.add(Json.object("name", nic.getName(), "up", nic.isUp(), "addresses", addresses));
        }
        return result;
    }
}
