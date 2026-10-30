# SnakeYAML uses the Android field-access path; JavaBeans introspection is not used.
-dontwarn java.beans.**

-keep public class local.rtp2httpd.MainActivity {
    public <init>();
    protected void onCreate(android.os.Bundle);
    protected void onStart();
    protected void onStop();
}

-keep public class local.rtp2httpd.BootReceiver {
    public <init>();
    public void onReceive(android.content.Context,android.content.Intent);
}

# Android EnumMap/EnumSet reflectively call enum values(); keep the synthetic
# methods for SnakeYAML enums in both SDK-only R8 and Gradle Release builds.
-keepclassmembers enum org.yaml.snakeyaml.** {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}
