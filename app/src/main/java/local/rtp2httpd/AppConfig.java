package local.rtp2httpd;

import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.LinkedHashMap;
import java.util.Map;
import org.yaml.snakeyaml.LoaderOptions;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.SafeConstructor;
import org.yaml.snakeyaml.events.AliasEvent;
import org.yaml.snakeyaml.events.CollectionStartEvent;
import org.yaml.snakeyaml.events.Event;
import org.yaml.snakeyaml.events.NodeEvent;
import org.yaml.snakeyaml.events.ScalarEvent;

/** Strict application schema. YAML tags, anchors, aliases and merge keys are disabled. */
final class AppConfig {
    static final int MAX_BYTES = 32768;
    final boolean managementEnabled;
    final String managementAddress;
    final int managementPort;
    final boolean relayEnabled;
    final String upstreamInterface;
    final String listenInterface;
    final int port;
    final int maxClients;
    final int verbose;

    AppConfig(boolean managementEnabled, String managementAddress, int managementPort,
              boolean relayEnabled, String upstreamInterface, String listenInterface,
              int port, int maxClients, int verbose) {
        if (!literalAddress(managementAddress)) throw invalid("management.listen_address 必须是 IPv4/IPv6 地址");
        if (managementPort < 1024 || managementPort > 65535) throw invalid("management.port 范围为 1024–65535");
        if (port < 1024 || port > 65535 || maxClients < 1 || verbose < 0 || verbose > 4)
            throw invalid("relay.port 范围为 1024–65535，maxclients 必须大于 0，verbose 范围为 0–4");
        if (managementEnabled && managementPort == port) throw invalid("管理端口与转发端口不能相同");
        checkInterface(upstreamInterface, "upstream_interface");
        checkInterface(listenInterface, "listen_interface");
        this.managementEnabled = managementEnabled;
        this.managementAddress = managementAddress;
        this.managementPort = managementPort;
        this.relayEnabled = relayEnabled;
        this.upstreamInterface = upstreamInterface;
        this.listenInterface = listenInterface;
        this.port = port;
        this.maxClients = maxClients;
        this.verbose = verbose;
    }

    static AppConfig fallback(Map<String, Object> bindings, Map<String, Object> overrides) {
        Map<String, Object> values = new LinkedHashMap<>(bindings);
        values.putAll(overrides);
        // Keep a damaged/missing YAML repairable when management occupies the default relay port.
        if (!values.containsKey("port") && Integer.valueOf(5140).equals(values.get("management_port")))
            values.put("port", 5142);
        return defaults().override(values);
    }

    static AppConfig defaults() {
        return new AppConfig(false, "127.0.0.1", 5141, true, null, null, 5140, 5, 2);
    }

    static AppConfig parse(String text) {
        if (text.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) throw invalid("YAML 最大为 32 KiB");
        LoaderOptions options = new LoaderOptions();
        options.setAllowDuplicateKeys(false);
        options.setAllowRecursiveKeys(false);
        options.setMaxAliasesForCollections(0);
        options.setNestingDepthLimit(5);
        options.setCodePointLimit(MAX_BYTES);
        options.setTagInspector(tag -> false);
        Yaml yaml = new Yaml(new SafeConstructor(options));
        yaml.setBeanAccess(org.yaml.snakeyaml.introspector.BeanAccess.FIELD);
        try {
            for (Event event : yaml.parse(new StringReader(text))) {
                if (event instanceof ScalarEvent && "<<".equals(((ScalarEvent) event).getValue()))
                    throw invalid("不支持 YAML 合并键");
                if (event instanceof AliasEvent || (event instanceof NodeEvent && ((NodeEvent) event).getAnchor() != null))
                    throw invalid("不支持 YAML 锚点或别名");
                if (event instanceof ScalarEvent && ((ScalarEvent) event).getTag() != null
                    || event instanceof CollectionStartEvent && ((CollectionStartEvent) event).getTag() != null)
                    throw invalid("不支持 YAML 类型标签");
            }
            Object loaded = yaml.load(text);
            if (loaded == null) throw invalid("YAML 配置不能为空");
            Map<String, Object> root = mapping(loaded, "根配置", "schema_version", "management", "relay");
            if (integer(root, "schema_version", 1) != 1) throw invalid("仅支持 schema_version: 1");
            Map<String, Object> management = mapping(root.get("management"), "management", "enabled", "listen_address", "port");
            Map<String, Object> relay = mapping(root.get("relay"), "relay", "enabled", "upstream_interface",
                "listen_interface", "port", "maxclients", "verbose", "workers");
            if (integer(relay, "workers", 1) != 1) throw invalid("当前版本 workers 固定为 1");
            return new AppConfig(bool(management, "enabled", false), string(management, "listen_address", "127.0.0.1"),
                integer(management, "port", 5141), bool(relay, "enabled", true), string(relay, "upstream_interface", null),
                string(relay, "listen_interface", null), integer(relay, "port", 5140), integer(relay, "maxclients", 5),
                integer(relay, "verbose", 2));
        } catch (IllegalArgumentException error) { throw error;
        } catch (RuntimeException error) { throw invalid("YAML 格式不正确，请检查缩进、类型和重复字段"); }
    }

    AppConfig override(Map<String, Object> values) {
        return new AppConfig(value(values, "management_enabled", managementEnabled), value(values, "management_listen", managementAddress),
            value(values, "management_port", managementPort), value(values, "relay_enabled", relayEnabled),
            value(values, "upstream_interface", upstreamInterface), value(values, "listen_interface", listenInterface),
            value(values, "port", port), value(values, "maxclients", maxClients), value(values, "verbose", verbose));
    }

    AppConfig withRelayEnabled(boolean enabled) {
        return new AppConfig(managementEnabled, managementAddress, managementPort, enabled,
            upstreamInterface, listenInterface, port, maxClients, verbose);
    }

    boolean sameManagement(AppConfig other) {
        return managementEnabled == other.managementEnabled && managementPort == other.managementPort
            && managementAddress.equals(other.managementAddress);
    }

    RelayConfig relay() {
        return new RelayConfig(upstreamInterface, listenInterface, port, maxClients, verbose);
    }

    Map<String, Object> toMap() {
        return Json.object("schema_version", 1,
            "management", Json.object("enabled", managementEnabled, "listen_address", managementAddress, "port", managementPort),
            "relay", Json.object("enabled", relayEnabled, "upstream_interface", upstreamInterface,
                "listen_interface", listenInterface, "port", port, "maxclients", maxClients, "verbose", verbose, "workers", 1));
    }

    String yaml() {
        return "schema_version: 1\n\nmanagement:\n  enabled: " + managementEnabled
            + "\n  listen_address: " + Json.encode(managementAddress) + "\n  port: " + managementPort
            + "\n\nrelay:\n  enabled: " + relayEnabled + "\n  upstream_interface: " + Json.encode(upstreamInterface)
            + "\n  listen_interface: " + Json.encode(listenInterface) + "\n  port: " + port + "\n  maxclients: " + maxClients
            + "\n  verbose: " + verbose + "\n  workers: 1\n";
    }

    String revision() { return hash(yaml()); }

    static String hash(String text) {
        try {
            StringBuilder value = new StringBuilder();
            for (byte item : MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)))
                value.append(String.format("%02x", item & 255));
            return value.toString();
        } catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    private static boolean literalAddress(String address) {
        if (address == null || address.length() > 64) return false;
        if (address.indexOf(':') >= 0) {
            if (!address.matches("[0-9a-fA-F:]+")) return false;
            try { return java.net.InetAddress.getByName(address) instanceof java.net.Inet6Address;
            } catch (java.net.UnknownHostException error) { return false; }
        }
        if (!address.matches("[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+")) return false;
        for (String part : address.split("\\.")) {
            if (part.length() > 3 || Integer.parseInt(part) > 255 || part.length() > 1 && part.startsWith("0")) return false;
        }
        return true;
    }

    private static void checkInterface(String name, String field) {
        if (name != null && !name.matches("[a-zA-Z0-9_.:-]{1,15}")) throw invalid(field + " 不是有效的网卡名称");
    }

    private static Map<String, Object> mapping(Object value, String field, String... keys) {
        if (value == null) return new LinkedHashMap<>();
        if (!(value instanceof Map)) throw invalid(field + " 必须是映射");
        Map<String, Object> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
            String key = entry.getKey() instanceof String ? (String) entry.getKey() : "";
            boolean allowed = false;
            for (String candidate : keys) if (candidate.equals(key)) allowed = true;
            if (!allowed) throw invalid(field + " 存在未知字段");
            result.put(key, entry.getValue());
        }
        return result;
    }

    private static int integer(Map<String, Object> map, String key, int fallback) {
        if (!map.containsKey(key)) return fallback;
        Object value = map.get(key);
        if (!(value instanceof Integer)) throw invalid(key + " 必须是整数");
        return (Integer) value;
    }

    private static boolean bool(Map<String, Object> map, String key, boolean fallback) {
        if (!map.containsKey(key)) return fallback;
        if (!(map.get(key) instanceof Boolean)) throw invalid(key + " 必须是布尔值");
        return (Boolean) map.get(key);
    }

    private static String string(Map<String, Object> map, String key, String fallback) {
        if (!map.containsKey(key)) return fallback;
        Object value = map.get(key);
        if (value == null && fallback == null) return null;
        if (!(value instanceof String)) throw invalid(key + " 必须是字符串");
        return (String) value;
    }

    @SuppressWarnings("unchecked") private static <T> T value(Map<String, Object> map, String key, T fallback) {
        return map.containsKey(key) ? (T) map.get(key) : fallback;
    }

    private static IllegalArgumentException invalid(String message) { return new IllegalArgumentException(message); }
}
