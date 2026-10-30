package local.rtp2httpd;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Binder;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** One foreground host owns the management listener and native core. */
public final class RelayService extends Service {
    static final String ACTION_START = "local.rtp2httpd.START";
    static final String ACTION_RESTART = "local.rtp2httpd.RESTART";
    static final String ACTION_STOP = "local.rtp2httpd.STOP";
    private static final String TAG = "Rtp2httpd";
    private static final String CHANNEL = "relay";
    private static final long WAKE_TIMEOUT_MS = 10 * 60 * 1000L;
    private static final long WAKE_RENEW_MS = 5 * 60 * 1000L;
    private final Handler main = new Handler(Looper.getMainLooper());
    private RelayController controller;
    private ManagementServer management;
    private AppConfig managementConfig;
    private boolean managementRequested;
    private long managementRetryMs = 1000;
    private WifiManager.MulticastLock multicastLock;
    private PowerManager.WakeLock wakeLock;
    private boolean destroyed;

    private final Runnable renewWakeLock = new Runnable() {
        @Override public void run() {
            if (destroyed || wakeLock == null) return;
            wakeLock.acquire(WAKE_TIMEOUT_MS);
            main.postDelayed(this, WAKE_RENEW_MS);
        }
    };
    private final Runnable updateNotification = new Runnable() {
        @Override public void run() {
            if (destroyed || controller == null) return;
            String state = String.valueOf(controller.status().get("state"));
            if (!managementRequested && "ERROR".equals(state)) { stopSelf(); return; }
            startForeground(1, notification("IPTV relay · " + state));
            main.postDelayed(this, 5000);
        }
    };

    private final Runnable bindManagement = new Runnable() {
        @Override public void run() {
            if (destroyed || !managementRequested || controller == null || management != null) return;
            try {
                management = new ManagementServer(managementConfig, controller, RelayService.this::readAsset);
                management.start();
                managementRetryMs = 1000;
            } catch (IOException failure) {
                // A configured LAN address may not exist yet when BOOT_COMPLETED arrives.
                controller.log("管理监听暂不可用，稍后重试：" + failure.getMessage());
                main.postDelayed(this, managementRetryMs);
                managementRetryMs = Math.min(60000, managementRetryMs * 2);
            }
        }
    };

    final class LocalBinder extends Binder {
        AppConfig config() { return controller == null ? null : controller.config(); }
        boolean managementReady() { return management != null; }
        Map<String, Object> status() {
            return controller == null ? Json.object("state", "STARTING", "error", null, "busy", true) : controller.status();
        }
        void control(String action) { applyControl(action); }
    }

    @Override public IBinder onBind(Intent intent) { return new LocalBinder(); }

    private void applyControl(String action) {
        if (controller == null) return;
        AppConfig current = controller.config();
        if (ACTION_START.equals(action) || ACTION_RESTART.equals(action)) {
            controller.apply(current.withRelayEnabled(true), current.revision());
        } else if (ACTION_STOP.equals(action)) {
            controller.apply(current.withRelayEnabled(false), current.revision());
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (controller != null) {
            try { if (intent != null) applyControl(intent.getAction()); }
            catch (RuntimeException failure) { Log.w(TAG, failure.getMessage()); }
            return START_STICKY;
        }
        try {
            destroyed = false;
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, "IPTV relay", NotificationManager.IMPORTANCE_LOW));
            startForeground(1, notification("Starting IPTV relay"));
            SharedPreferences preferences = getSharedPreferences("relay", MODE_PRIVATE);
            ConfigStore store = new ConfigStore(getFilesDir());
            AppConfig config = AppConfig.defaults();
            Map<String, Object> fallback = savedBinding(preferences);
            boolean restored = false;
            String recoveryError = null;
            boolean hasFiles = store.exists();
            if (hasFiles) {
                try { config = store.read(); restored = true; }
                catch (IOException failure) {
                    recoveryError = failure.getMessage();
                    // Binding metadata is retained separately so a broken YAML can still be repaired.
                    // Construct fallback only after all startup overrides are collected.
                }
            } else if (!preferences.getBoolean("yaml_migrated", false) && preferences.getBoolean("configured", false)) {
                Map<String, Object> legacy = new LinkedHashMap<>();
                legacy.put("upstream_interface", preferences.getString("upstream_interface", null));
                legacy.put("listen_interface", preferences.getString("listen_interface", null));
                legacy.put("port", preferences.getInt("port", 5140));
                legacy.put("maxclients", preferences.getInt("maxclients", 5));
                legacy.put("verbose", preferences.getInt("verbose", 2));
                fallback.putAll(legacy);
            }
            config = restored ? config.override(overrides(intent))
                : AppConfig.fallback(fallback, overrides(intent));
            if (intent != null && (ACTION_START.equals(intent.getAction()) || ACTION_RESTART.equals(intent.getAction())))
                config = config.withRelayEnabled(true);
            if (!config.managementEnabled && config.relayEnabled && config.upstreamInterface == null)
                throw new IllegalArgumentException("upstream_interface is required unless management is enabled");
            controller = new RelayController(store, config, new RelayController.Runtime() {
                @Override public Process launch(AppConfig target) throws IOException { return launchCore(target); }
                @Override public boolean ready(AppConfig target) { return coreReady(target); }
            });
            managementRequested = config.managementEnabled;
            managementConfig = config;
            if (recoveryError == null) store.commit(config);
            SharedPreferences.Editor editor = preferences.edit().putBoolean("yaml_migrated", true)
                .putBoolean("management_enabled", config.managementEnabled)
                .putString("management_listen", config.managementAddress).putInt("management_port", config.managementPort);
            editor.remove("management_token_hash");
            if (!editor.commit()) throw new IOException("无法保存管理设置或迁移标记");
            store.discardPending();
            if (recoveryError != null) controller.log(recoveryError);
            acquireLocks();
            bindManagement.run();
            controller.start(); updateNotification.run();
            return START_STICKY;
        } catch (Exception failure) {
            Log.e(TAG, "Cannot start relay: " + failure.getMessage());
            if (management != null) { management.close(); management = null; }
            if (controller != null) { controller.close(); controller = null; }
            stopSelf(); return START_NOT_STICKY;
        }
    }

    private static Map<String, Object> savedBinding(SharedPreferences preferences) {
        Map<String, Object> values = new LinkedHashMap<>();
        values.put("management_enabled", preferences.getBoolean("management_enabled", false));
        values.put("management_listen", preferences.getString("management_listen", "127.0.0.1"));
        values.put("management_port", preferences.getInt("management_port", 5141));
        return values;
    }

    private static Map<String, Object> overrides(Intent intent) {
        Map<String, Object> values = new LinkedHashMap<>();
        if (intent == null || intent.getExtras() == null) return values;
        for (String key : new String[]{"upstream_interface", "listen_interface", "management_listen"}) {
            if (intent.hasExtra(key)) {
                Object value = intent.getExtras().get(key);
                if (!(value instanceof String)) throw new IllegalArgumentException(key + " 必须使用 --es");
                values.put(key, value);
            }
        }
        for (String key : new String[]{"port", "maxclients", "verbose", "management_port"}) {
            if (intent.hasExtra(key)) {
                Object value = intent.getExtras().get(key);
                if (!(value instanceof Integer)) throw new IllegalArgumentException(key + " 必须使用 --ei");
                values.put(key, value);
            }
        }
        for (String key : new String[]{"management_enabled", "relay_enabled"}) {
            if (intent.hasExtra(key)) {
                Object value = intent.getExtras().get(key);
                if (!(value instanceof Boolean)) throw new IllegalArgumentException(key + " 必须使用 --ez");
                values.put(key, value);
            }
        }
        return values;
    }

    private Process launchCore(AppConfig config) throws IOException {
        File core = new File(getApplicationInfo().nativeLibraryDir, "librtp2httpd.so");
        if (!core.isFile() || !core.canExecute()) throw new IllegalArgumentException("Android native core is not bundled or executable");
        ProcessBuilder builder = new ProcessBuilder(config.relay().command(core.getAbsolutePath()))
            .directory(getCacheDir()).redirectErrorStream(true);
        builder.environment().put("TMPDIR", getCacheDir().getAbsolutePath());
        builder.environment().put("RTP2HTTPD_PARENT_PID", Integer.toString(android.os.Process.myPid()));
        return builder.start();
    }

    private static boolean coreReady(AppConfig config) {
        try {
            String address = "127.0.0.1";
            if (config.listenInterface != null) {
                NetworkInterface nic = NetworkInterface.getByName(config.listenInterface);
                if (nic == null) return false;
                address = null;
                for (InetAddress ip : Collections.list(nic.getInetAddresses())) if (ip instanceof Inet4Address) { address = ip.getHostAddress(); break; }
                if (address == null) return false;
            }
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress(address, config.port), 250); socket.setSoTimeout(300);
                socket.getOutputStream().write(("GET /status HTTP/1.0\r\nHost: " + address + "\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                byte[] prefix = new byte[12]; int offset = 0;
                while (offset < prefix.length) { int count = socket.getInputStream().read(prefix, offset, prefix.length - offset); if (count < 0) return false; offset += count; }
                return new String(prefix, StandardCharsets.US_ASCII).matches("HTTP/1\\.[01] 200");
            }
        } catch (IOException failure) { return false; }
    }

    private byte[] readAsset(String name) throws IOException {
        try (InputStream input = getAssets().open("management/" + name); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096]; int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            return output.toByteArray();
        }
    }

    private Notification notification(String text) {
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("rtp2httpd").setContentText(text).setOngoing(true).build();
    }
    private void acquireLocks() {
        PowerManager power = getSystemService(PowerManager.class);
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "rtp2httpd:relay");
        wakeLock.setReferenceCounted(false); renewWakeLock.run();
        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
        if (wifi != null) { multicastLock = wifi.createMulticastLock(TAG); multicastLock.setReferenceCounted(false); multicastLock.acquire(); }
    }
    @Override public void onDestroy() {
        destroyed = true; main.removeCallbacksAndMessages(null);
        if (management != null) { management.close(); management = null; }
        if (controller != null) { controller.close(); controller = null; }
        if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        stopForeground(STOP_FOREGROUND_REMOVE); super.onDestroy();
    }
}
