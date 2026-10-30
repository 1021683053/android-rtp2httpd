package local.rtp2httpd;

import org.junit.Test;
import java.io.IOException;
import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.util.Collections;
import java.util.List;
import static org.junit.Assert.*;

public class RelayConfigTest {
    @Test public void rejectsInvalidParametersBeforeSaving() {
        for (String upstream : new String[] {null, "", " "})
            assertThrows(IllegalArgumentException.class, () -> new RelayConfig(upstream, null, 5140, 5, 2));
        for (int port : new int[] {1023, 65536})
            assertThrows(IllegalArgumentException.class, () -> new RelayConfig("eth0", null, port, 5, 2));
        assertThrows(IllegalArgumentException.class, () -> new RelayConfig("eth0", "", 5140, 5, 2));
        assertThrows(IllegalArgumentException.class, () -> new RelayConfig("eth0", null, 5140, 0, 2));
        assertThrows(IllegalArgumentException.class, () -> new RelayConfig("eth0", null, 5140, 5, 5));
    }

    @Test public void unavailableInterfacesAreRetryableInsteadOfInvalidConfiguration() {
        RelayConfig upstream = new RelayConfig("r2h-missing", null, 5140, 5, 2);
        assertThrows(IOException.class, () -> upstream.command("/core"));
    }

    @Test public void buildsArgumentVectorAndResolvesListenAddress() throws Exception {
        NetworkInterface loopback = Collections.list(NetworkInterface.getNetworkInterfaces()).stream()
            .filter(nic -> Collections.list(nic.getInetAddresses()).stream()
                .anyMatch(ip -> ip instanceof Inet4Address && ip.isLoopbackAddress()))
            .findFirst().orElseThrow(() -> new AssertionError("No IPv4 loopback interface"));
        String name = loopback.getName();
        List<String> all = new RelayConfig(name, null, 5140, 5, 2).command("/core with spaces");
        assertEquals("/core with spaces", all.get(0));
        assertEquals("0.0.0.0:5140", all.get(all.indexOf("--listen") + 1));
        assertTrue(all.contains("--noconfig"));
        assertEquals("1", all.get(all.indexOf("--workers") + 1));
        List<String> bound = new RelayConfig(name, name, 65535, 8, 4).command("/core");
        assertEquals("127.0.0.1:65535", bound.get(bound.indexOf("--listen") + 1));
        assertEquals("8", bound.get(bound.indexOf("--maxclients") + 1));
        assertEquals("4", bound.get(bound.indexOf("--verbose") + 1));
        RelayConfig missingListen = new RelayConfig(name, "r2h-missing", 5140, 5, 2);
        assertThrows(IOException.class, () -> missingListen.command("/core"));
    }
}
