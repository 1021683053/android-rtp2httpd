package local.rtp2httpd;

import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Small bounded HTTP/1.x server. No proxying, keep-alive, chunking or arbitrary file access. */
final class ManagementServer implements AutoCloseable {
    interface Assets { byte[] read(String name) throws IOException; }
    private final RelayController controller;
    private final ManagementApi api;
    private final ServerSocket listener;
    private final Set<Socket> sockets = Collections.newSetFromMap(new ConcurrentHashMap<Socket, Boolean>());
    private final ThreadPoolExecutor workers = new ThreadPoolExecutor(4, 4, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<>(16), task -> daemon("management-http", task));
    private final ScheduledThreadPoolExecutor timer = new ScheduledThreadPoolExecutor(1, task -> daemon("http-deadline", task));
    private volatile boolean closed;

    ManagementServer(AppConfig config, RelayController controller, Assets assets) throws IOException {
        this.controller = controller; this.api = new ManagementApi(controller, assets);
        timer.setRemoveOnCancelPolicy(true);
        listener = new ServerSocket();
        try {
            listener.setReuseAddress(true);
            listener.bind(new InetSocketAddress(InetAddress.getByName(config.managementAddress), config.managementPort), 16);
        }
        catch (IOException failure) { listener.close(); workers.shutdownNow(); timer.shutdownNow(); throw failure; }
    }

    void start() {
        daemon("management-accept", () -> {
            while (!closed) {
                try {
                    Socket socket = listener.accept();
                    try {
                        socket.setSoTimeout(5000); sockets.add(socket);
                        if (closed) { sockets.remove(socket); close(socket); continue; }
                        ScheduledFuture<?> timeout = timer.schedule(() -> close(socket), 10, TimeUnit.SECONDS);
                        try { workers.execute(() -> {
                            try { serve(socket); } finally { timeout.cancel(false); sockets.remove(socket); close(socket); }
                        }); } catch (java.util.concurrent.RejectedExecutionException error) {
                            timeout.cancel(false); sockets.remove(socket); close(socket);
                        }
                    } catch (IOException | java.util.concurrent.RejectedExecutionException failure) {
                        sockets.remove(socket); close(socket);
                    }
                } catch (IOException error) { if (!closed) controller.log("管理监听连接失败"); }
                catch (java.util.concurrent.RejectedExecutionException ignored) { /* Service shutdown. */ }
            }
        }).start();
    }

    private void serve(Socket socket) {
        try {
            ScheduledFuture<?> readTimeout = timer.schedule(() -> close(socket), 5, TimeUnit.SECONDS);
            Request request;
            try { request = Request.read(socket.getInputStream()); }
            finally { readTimeout.cancel(false); }
            String local = socket.getLocalAddress().getHostAddress();
            Response response = api.handle(request, local, listener.getLocalPort());
            write(socket.getOutputStream(), response);
        } catch (HttpError failure) {
            try { write(socket.getOutputStream(), Response.json(failure.status, Json.object("error", failure.getMessage()))); }
            catch (IOException ignored) { }
        } catch (IOException ignored) { /* Closed or timed out. Never log request data or credentials. */ }
        catch (Exception failure) {
            try { write(socket.getOutputStream(), Response.json(500, Json.object("error", "管理请求失败"))); }
            catch (IOException ignored) { }
        }
    }

    @Override public void close() {
        closed = true; try { listener.close(); } catch (IOException ignored) { }
        for (Socket socket : sockets) close(socket);
        workers.shutdownNow(); timer.shutdownNow();
    }
    private static void close(Socket socket) { try { socket.close(); } catch (IOException ignored) { } }
    private static Thread daemon(String name, Runnable task) { Thread thread = new Thread(task, name); thread.setDaemon(true); return thread; }

    static final class Request {
        final String method, path;
        final Map<String, String> headers;
        final byte[] body;
        Request(String method, String path, Map<String, String> headers, byte[] body) {
            this.method = method; this.path = path; this.headers = headers; this.body = body;
        }
        String text() throws HttpError {
            try { return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(body)).toString();
            } catch (java.nio.charset.CharacterCodingException error) { throw new HttpError(400, "请求必须使用 UTF-8"); }
        }
        static Request read(InputStream input) throws IOException {
            long deadline = System.nanoTime() + 5_000_000_000L;
            String[] start = line(input, deadline).split(" ", -1);
            if (start.length != 3 || !start[0].matches("GET|POST|DELETE") || !start[1].startsWith("/")
                || !(start[2].equals("HTTP/1.1") || start[2].equals("HTTP/1.0"))) throw new HttpError(400, "无效的 HTTP 请求");
            Map<String, String> headers = new HashMap<>();
            int size = 0;
            while (true) {
                String line = line(input, deadline); size += line.length() + 2;
                if (size > 8192) throw new HttpError(431, "请求头过大");
                if (line.isEmpty()) break;
                int colon = line.indexOf(':');
                if (colon <= 0) throw new HttpError(400, "无效请求头");
                String name = line.substring(0, colon).toLowerCase(Locale.ROOT);
                if (!name.matches("[a-z0-9!#$%&'*+.^_`|~-]+")) throw new HttpError(400, "无效请求头");
                String value = line.substring(colon + 1).trim();
                if (headers.put(name, value) != null) throw new HttpError(400, "重复请求头");
            }
            if (headers.containsKey("transfer-encoding") || headers.containsKey("expect")) throw new HttpError(400, "不支持此请求传输方式");
            String rawLength = headers.get("content-length");
            if (rawLength != null && !rawLength.matches("[0-9]{1,6}")) throw new HttpError(400, "无效 Content-Length");
            int length = rawLength == null ? 0 : Integer.parseInt(rawLength);
            if (length > AppConfig.MAX_BYTES) throw new HttpError(413, "请求最大为 32 KiB");
            byte[] body = new byte[length];
            int offset = 0;
            while (offset < length) {
                if (System.nanoTime() > deadline) throw new HttpError(408, "请求超时");
                int count = input.read(body, offset, length - offset);
                if (count < 0) throw new EOFException(); offset += count;
            }
            return new Request(start[0], start[1], headers, body);
        }
        private static String line(InputStream input, long deadline) throws IOException {
            ByteArrayOutputStream line = new ByteArrayOutputStream();
            while (line.size() <= 2048) {
                if (System.nanoTime() > deadline) throw new HttpError(408, "请求超时");
                int item = input.read(); if (item < 0) throw new EOFException();
                if (item == '\r') { if (input.read() != '\n') throw new HttpError(400, "无效换行"); return line.toString("US-ASCII"); }
                if (item < 32 || item >= 127) throw new HttpError(400, "无效请求头字符");
                line.write(item);
            }
            throw new HttpError(431, "请求行过长");
        }
    }
    static final class Response {
        final int status;
        final String type;
        final byte[] body;
        final Map<String, String> headers = new HashMap<>();
        Response(int status, String type, byte[] body) { this.status = status; this.type = type; this.body = body; }
        static Response json(int status, Object value) { return new Response(status, "application/json; charset=utf-8", Json.encode(value).getBytes(StandardCharsets.UTF_8)); }
    }
    static void write(OutputStream output, Response response) throws IOException {
        StringBuilder header = new StringBuilder("HTTP/1.1 " + response.status + " Response\r\nContent-Type: " + response.type
            + "\r\nContent-Length: " + response.body.length + "\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff"
            + "\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'\r\n");
        for (Map.Entry<String, String> entry : response.headers.entrySet()) header.append(entry.getKey()).append(": ").append(entry.getValue()).append("\r\n");
        output.write(header.append("\r\n").toString().getBytes(StandardCharsets.US_ASCII));
        output.write(response.body); output.flush();
    }
    static final class HttpError extends IOException {
        final int status;
        HttpError(int status, String message) { super(message); this.status = status; }
    }
}
