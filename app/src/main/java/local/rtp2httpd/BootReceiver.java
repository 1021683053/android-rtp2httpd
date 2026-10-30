package local.rtp2httpd;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.util.Log;

/** Restore an already configured relay after boot, without inventing new settings. */
public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        SharedPreferences preferences = context.getSharedPreferences("relay", Context.MODE_PRIVATE);
        if (!new ConfigStore(context.getFilesDir()).exists()
            && !preferences.getBoolean("configured", false)
            && !preferences.getBoolean("management_enabled", false)) return;
        try {
            // No extras: the service restores YAML and respects relay.enabled=false.
            context.startForegroundService(new Intent(context, RelayService.class));
        } catch (RuntimeException failure) {
            Log.e("Rtp2httpd", "Cannot restore relay after boot: " + failure.getMessage());
        }
    }
}
