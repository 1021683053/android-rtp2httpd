package local.rtp2httpd;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;
import java.io.File;
import java.io.IOException;

/** Headless shell-controlled host. Native core must be supplied separately. */
public final class RelayService extends Service {
    private static final String TAG = "Rtp2httpd";
    private static final String CHANNEL = "relay";
    private static final long WAKE_TIMEOUT_MS = 10 * 60 * 1000L;
    private static final long WAKE_RENEW_MS = 5 * 60 * 1000L;
    private final Handler main = new Handler(Looper.getMainLooper());
    private RelayRunner runner;
    private WifiManager.MulticastLock multicastLock;
    private PowerManager.WakeLock wakeLock;
    private boolean destroyed;

    private final Runnable renewWakeLock = new Runnable() {
        @Override public void run() {
            if (destroyed || wakeLock == null) return;
            // Bounded leases provide a fallback if normal service cleanup fails.
            wakeLock.acquire(WAKE_TIMEOUT_MS);
            main.postDelayed(this, WAKE_RENEW_MS);
        }
    };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        try {
            // Repeated starts must not replace an active configuration or retry loop.
            if (runner != null) return START_STICKY;
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL,
                "IPTV relay", NotificationManager.IMPORTANCE_LOW));
            startForeground(1, notification("Starting IPTV relay"));
            SharedPreferences preferences = getSharedPreferences("relay", MODE_PRIVATE);
            RelayConfig config = intent == null ? restore(preferences) : fromIntent(intent);
            File core = new File(getApplicationInfo().nativeLibraryDir, "librtp2httpd.so");
            if (!core.isFile() || !core.canExecute())
                throw new IllegalArgumentException("Android native core is not bundled or executable");
            // Finish the disk write before accepting a start that the system may later recreate.
            if (intent != null && !save(preferences, config))
                throw new IOException("Cannot persist startup parameters");

            acquireLocks();
            runner = new RelayRunner(() -> {
                if (!core.isFile() || !core.canExecute())
                    throw new IllegalArgumentException("Android native core is not bundled or executable");
                ProcessBuilder builder = new ProcessBuilder(config.command(core.getAbsolutePath()))
                    .directory(getCacheDir()).redirectErrorStream(true);
                builder.environment().put("TMPDIR", getCacheDir().getAbsolutePath());
                builder.environment().put("RTP2HTTPD_PARENT_PID", Integer.toString(android.os.Process.myPid()));
                return builder.start();
            }, new RelayRunner.Listener() {
                @Override public void onLog(String line) { Log.i(TAG, line); }
                @Override public void onRunning() { showStatus("IPTV relay running"); }
                @Override public void onRetry(long delayMs, Exception error) {
                    Log.w(TAG, "Core unavailable; retry in " + delayMs + " ms", error);
                    showStatus("Retrying IPTV relay in " + delayMs / 1000 + "s");
                }
                @Override public void onFatal(Exception error) {
                    Log.e(TAG, "Cannot run relay", error);
                    main.post(() -> { if (!destroyed) stopSelf(); });
                }
            });
            runner.start();
            return START_STICKY;
        } catch (Exception error) {
            Log.e(TAG, "Cannot start relay", error);
            stopSelf();
            return START_NOT_STICKY;
        }
    }

    private static RelayConfig fromIntent(Intent intent) {
        return new RelayConfig(intent.getStringExtra("upstream_interface"),
            intent.getStringExtra("listen_interface"), intent.getIntExtra("port", 5140),
            intent.getIntExtra("maxclients", 5), intent.getIntExtra("verbose", 2));
    }

    private static RelayConfig restore(SharedPreferences preferences) {
        if (!preferences.getBoolean("configured", false))
            throw new IllegalArgumentException("No saved startup parameters");
        return new RelayConfig(preferences.getString("upstream_interface", null),
            preferences.getString("listen_interface", null), preferences.getInt("port", 5140),
            preferences.getInt("maxclients", 5), preferences.getInt("verbose", 2));
    }

    private static boolean save(SharedPreferences preferences, RelayConfig config) {
        return preferences.edit().putBoolean("configured", true)
            .putString("upstream_interface", config.upstreamInterface)
            .putString("listen_interface", config.listenInterface)
            .putInt("port", config.port).putInt("maxclients", config.maxClients)
            .putInt("verbose", config.verbose).commit();
    }

    private Notification notification(String text) {
        return new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_upload).setContentTitle("rtp2httpd")
            .setContentText(text).setOngoing(true).build();
    }

    private void showStatus(String text) {
        main.post(() -> {
            if (!destroyed) startForeground(1, notification(text));
        });
    }

    private void acquireLocks() {
        PowerManager power = getSystemService(PowerManager.class);
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "rtp2httpd:relay");
        wakeLock.setReferenceCounted(false);
        renewWakeLock.run();
        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
        if (wifi != null) {
            multicastLock = wifi.createMulticastLock(TAG);
            multicastLock.setReferenceCounted(false);
            multicastLock.acquire();
        }
    }

    @Override public void onDestroy() {
        destroyed = true;
        main.removeCallbacksAndMessages(null);
        if (runner != null) { runner.stop(); runner = null; }
        if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }
}
