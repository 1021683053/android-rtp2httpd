package local.rtp2httpd;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.SocketException;
import java.net.UnknownHostException;
import java.util.Collections;
import java.util.Enumeration;
import java.util.Map;

/** TV launcher surface: status, service addresses and three direct controls. */
public final class MainActivity extends Activity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private RelayService.LocalBinder service;
    private boolean bound;
    private boolean visible;
    private TextView status;
    private TextView managementAddress;
    private TextView proxyAddress;
    private final Button[] buttons = new Button[3];
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            service = (RelayService.LocalBinder) binder;
            render();
        }
        @Override public void onServiceDisconnected(ComponentName name) { service = null; render(); }
        @Override public void onBindingDied(ComponentName name) {
            if (bound) unbindService(this);
            bound = false; service = null; render();
        }
    };
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            if (!visible) return;
            if (!bound) bound = bindService(new Intent(MainActivity.this, RelayService.class), connection, 0);
            render();
            main.postDelayed(this, 1000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(16, 27, 43));
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setGravity(Gravity.CENTER);
        int width = Math.min(dp(720), getResources().getDisplayMetrics().widthPixels - dp(48));
        FrameLayout.LayoutParams frame = new FrameLayout.LayoutParams(width, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER);
        root.addView(content, frame);
        status = new TextView(this);
        status.setTextSize(26); status.setTextColor(Color.rgb(232, 239, 247));
        status.setGravity(Gravity.CENTER); status.setMaxLines(3);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        content.addView(status, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        LinearLayout addresses = new LinearLayout(this);
        addresses.setOrientation(LinearLayout.VERTICAL);
        FrameLayout.LayoutParams addressFrame = new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.START);
        addressFrame.leftMargin = dp(24); addressFrame.rightMargin = dp(24); addressFrame.topMargin = dp(12);
        root.addView(addresses, addressFrame);
        managementAddress = addressView(addresses);
        proxyAddress = addressView(addresses);
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams row = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(64));
        row.topMargin = dp(32); content.addView(actions, row);
        String[] labels = {"启动", "重启", "停止"};
        String[] commands = {RelayService.ACTION_START, RelayService.ACTION_RESTART, RelayService.ACTION_STOP};
        for (int i = 0; i < buttons.length; i++) {
            Button button = new Button(this); buttons[i] = button;
            button.setId(View.generateViewId()); button.setText(labels[i]); button.setTextSize(20);
            button.setAllCaps(false); button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            button.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},
                new int[]{Color.rgb(115, 130, 150),Color.WHITE}));
            StateListDrawable background = new StateListDrawable();
            background.addState(new int[]{android.R.attr.state_focused}, surface(0xFF286CD1));
            background.addState(new int[]{android.R.attr.state_pressed}, surface(0xFF205AB0));
            background.addState(new int[]{}, surface(0xFF243C56));
            button.setBackground(background);
            final String command = commands[i]; button.setOnClickListener(view -> control(command));
            LinearLayout.LayoutParams item = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1);
            item.leftMargin = dp(6); item.rightMargin = dp(6); actions.addView(button, item);
        }
        for (int i = 0; i < buttons.length; i++) {
            buttons[i].setNextFocusLeftId(buttons[Math.max(0, i - 1)].getId());
            buttons[i].setNextFocusRightId(buttons[Math.min(buttons.length - 1, i + 1)].getId());
        }
        setContentView(root); render(); buttons[0].requestFocus();
    }

    @Override protected void onStart() { super.onStart(); visible = true; refresh.run(); }
    @Override protected void onStop() {
        visible = false; main.removeCallbacksAndMessages(null);
        if (bound) unbindService(connection);
        bound = false; service = null;
        super.onStop();
    }

    private void control(String command) {
        try {
            if (service != null) service.control(command);
            else if (!RelayService.ACTION_STOP.equals(command)) {
                Intent intent = new Intent(this, RelayService.class).setAction(command);
                if (!new ConfigStore(getFilesDir()).exists()
                    && !getSharedPreferences("relay", MODE_PRIVATE).getBoolean("configured", false)
                    && !getSharedPreferences("relay", MODE_PRIVATE).getBoolean("management_enabled", false)) {
                    intent.putExtra("management_enabled", true).putExtra("management_listen", "0.0.0.0");
                }
                startForegroundService(intent);
            }
            render();
        } catch (RuntimeException failure) { showStatus("报错：" + failure.getMessage(), 0xFFEF626B); }
    }

    private void render() {
        Map<String, Object> snapshot = service == null ? null : service.status();
        String state = snapshot == null ? "STOPPED" : String.valueOf(snapshot.get("state"));
        Object error = snapshot == null ? null : snapshot.get("error");
        boolean busy = snapshot != null && Boolean.TRUE.equals(snapshot.get("busy"));
        if (error != null || "ERROR".equals(state) || "RETRY_WAIT".equals(state)) showStatus("报错" + (error == null ? "" : "：" + error), 0xFFEF626B);
        else if ("RUNNING".equals(state)) showStatus("服务正常", 0xFF48C982);
        else if ("WAITING_CONFIG".equals(state)) showStatus("等待配置", 0xFF98A3AF);
        else if ("STARTING".equals(state) || "APPLYING".equals(state)) showStatus("启动中", 0xFF98A3AF);
        else showStatus("已停止", 0xFF98A3AF);
        AppConfig config = service == null ? null : service.config();
        String management = "未启动", proxy = "未启动";
        if (config != null) {
            management = config.managementEnabled ? managementUrl(config) : "未启用";
            proxy = url(interfaceAddress(config.listenInterface, false), config.port);
        }
        int managementColor = config == null || !config.managementEnabled ? 0xFF98A3AF
            : service.managementReady() ? 0xFF48C982 : 0xFFEF626B;
        int proxyColor = "RUNNING".equals(state) ? 0xFF48C982
            : "ERROR".equals(state) || "RETRY_WAIT".equals(state) ? 0xFFEF626B : 0xFF98A3AF;
        showAddress(managementAddress, "管理地址", management, managementColor);
        showAddress(proxyAddress, "代理地址", proxy, proxyColor);
        for (Button button : buttons) if (button != null) button.setEnabled(!busy);
    }

    private TextView addressView(LinearLayout content) {
        TextView view = new TextView(this);
        view.setTextSize(18); view.setTextColor(0xFFB8CBDD); view.setGravity(Gravity.START);
        view.setLineSpacing(dp(3), 1);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(18); content.addView(view, params);
        return view;
    }

    private void showAddress(TextView view, String label, String address, int color) {
        String text = label + "  ●\n" + address;
        if (text.contentEquals(view.getText()) && Integer.valueOf(color).equals(view.getTag())) return;
        SpannableString styled = new SpannableString(text);
        int dot = label.length() + 2;
        styled.setSpan(new ForegroundColorSpan(color), dot, dot + 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        styled.setSpan(new ForegroundColorSpan(0xFF8495A8), text.indexOf('\n') + 1, text.length(),
            Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        view.setText(styled); view.setTag(color);
        String state = color == 0xFF48C982 ? "正常" : color == 0xFFEF626B ? "报错" : "未运行";
        view.setContentDescription(label + "，" + state + "，" + address);
    }

    private String managementUrl(AppConfig config) {
        try {
            InetAddress address = InetAddress.getByName(config.managementAddress);
            if (address.isAnyLocalAddress()) address = interfaceAddress(null, !(address instanceof Inet4Address));
            return url(address, config.managementPort);
        } catch (UnknownHostException failure) { return "等待网络"; }
    }

    private InetAddress interfaceAddress(String interfaceName, boolean ipv6) {
        try {
            if (interfaceName != null) {
                NetworkInterface nic = NetworkInterface.getByName(interfaceName);
                if (nic == null || !nic.isUp()) return null;
                for (InetAddress address : Collections.list(nic.getInetAddresses()))
                    if (usable(address, ipv6, true)) return address;
                return null;
            }
            ConnectivityManager networks = getSystemService(ConnectivityManager.class);
            Network active = networks == null ? null : networks.getActiveNetwork();
            LinkProperties link = active == null ? null : networks.getLinkProperties(active);
            if (link != null) for (LinkAddress item : link.getLinkAddresses())
                if (usable(item.getAddress(), ipv6, false)) return item.getAddress();
            // Ethernet/Wi-Fi can remain usable locally even without a default internet network.
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            if (interfaces == null) return null;
            for (NetworkInterface nic : Collections.list(interfaces)) {
                String name = nic.getName();
                if (!(name.startsWith("eth") || name.startsWith("en") || name.startsWith("wlan") || name.startsWith("wifi"))) continue;
                if (!nic.isUp() || nic.isLoopback()) continue;
                for (InetAddress address : Collections.list(nic.getInetAddresses()))
                    if (usable(address, ipv6, false)) return address;
            }
        } catch (SocketException | SecurityException failure) { /* No usable address yet. */ }
        return null;
    }

    private static boolean usable(InetAddress address, boolean ipv6, boolean allowLoopback) {
        return (address instanceof Inet4Address) != ipv6 && !address.isAnyLocalAddress()
            && !address.isMulticastAddress() && !address.isLinkLocalAddress()
            && (allowLoopback || !address.isLoopbackAddress());
    }

    private static String url(InetAddress address, int port) {
        if (address == null) return "等待网络";
        String host = address.getHostAddress();
        if (!(address instanceof Inet4Address)) host = "[" + host.split("%", 2)[0] + "]";
        return "http://" + host + ":" + port;
    }

    private void showStatus(String text, int color) {
        String value = "●  " + text;
        if (value.contentEquals(status.getText())) return;
        SpannableString styled = new SpannableString(value);
        styled.setSpan(new ForegroundColorSpan(color), 0, 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        status.setText(styled); status.setContentDescription("状态：" + text);
    }
    private GradientDrawable surface(int color) {
        GradientDrawable drawable = new GradientDrawable(); drawable.setColor(color); drawable.setCornerRadius(dp(8)); return drawable;
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
