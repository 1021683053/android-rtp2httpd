package local.rtp2httpd;

import java.io.IOException;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Saved values stay independent of the addresses available at startup. */
final class RelayConfig {
    final String upstreamInterface;
    final String listenInterface;
    final int port;
    final int maxClients;
    final int verbose;

    RelayConfig(String upstreamInterface, String listenInterface, int port, int maxClients, int verbose) {
        if (upstreamInterface == null || upstreamInterface.trim().isEmpty())
            throw new IllegalArgumentException("upstream_interface is required");
        if (listenInterface != null && listenInterface.trim().isEmpty())
            throw new IllegalArgumentException("listen_interface must not be empty");
        if (port < 1024 || port > 65535 || maxClients < 1 || verbose < 0 || verbose > 4)
            throw new IllegalArgumentException("Invalid port, maxclients or verbose");
        this.upstreamInterface = upstreamInterface;
        this.listenInterface = listenInterface;
        this.port = port;
        this.maxClients = maxClients;
        this.verbose = verbose;
    }

    List<String> command(String core) throws IOException {
        // A missing interface/address can be temporary after boot or network loss.
        if (NetworkInterface.getByName(upstreamInterface) == null)
            throw new IOException("Upstream interface unavailable: " + upstreamInterface);
        String address = "0.0.0.0";
        if (listenInterface != null) {
            NetworkInterface nic = NetworkInterface.getByName(listenInterface);
            if (nic == null) throw new IOException("Listen interface unavailable: " + listenInterface);
            address = null;
            for (InetAddress ip : Collections.list(nic.getInetAddresses())) {
                if (ip instanceof Inet4Address) { address = ip.getHostAddress(); break; }
            }
            if (address == null) throw new IOException("No IPv4 address on " + listenInterface);
        }
        return Arrays.asList(core, "--noconfig", "--upstream-interface", upstreamInterface,
            "--listen", address + ":" + port, "--maxclients", Integer.toString(maxClients),
            "--workers", "1", "--verbose", Integer.toString(verbose));
    }
}
