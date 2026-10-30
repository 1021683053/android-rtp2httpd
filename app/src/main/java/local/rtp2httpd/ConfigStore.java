package local.rtp2httpd;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;

/** Atomic primary/backup files. A pending candidate is never promoted during recovery. */
final class ConfigStore {
    private final File directory;
    private final File primary;
    private final File backup;
    private final File pending;

    ConfigStore(File directory) {
        this.directory = directory;
        primary = new File(directory, "config.yml");
        backup = new File(directory, "config.yml.bak");
        pending = new File(directory, "config.pending.yml");
    }

    synchronized boolean exists() { return primary.exists() || backup.exists(); }

    synchronized AppConfig read() throws IOException {
        try { return parse(primary);
        } catch (IOException | IllegalArgumentException error) {
            try { return parse(backup);
            } catch (IOException | IllegalArgumentException ignored) {
                throw new IOException("保存的配置和备份均不可用，请通过管理页面修复", error);
            }
        }
    }

    synchronized AppConfig previous() throws IOException {
        try { return parse(backup);
        } catch (IllegalArgumentException error) { throw new IOException("备份配置无效", error); }
    }

    synchronized void stage(AppConfig config) throws IOException { atomicWrite(pending, config.yaml()); }

    synchronized void commit(AppConfig config) throws IOException {
        if (exists()) {
            AppConfig old = null;
            try { old = read(); } catch (IOException ignored) { /* Explicit repair of invalid files. */ }
            if (old != null && !old.revision().equals(config.revision())) atomicWrite(backup, old.yaml());
        }
        atomicWrite(primary, config.yaml());
        try { discardPending(); } catch (IOException ignored) { /* Never promoted on recovery. */ }
    }

    synchronized void discardPending() throws IOException { Files.deleteIfExists(pending.toPath()); }

    private static AppConfig parse(File file) throws IOException {
        if (!file.isFile() || file.length() > AppConfig.MAX_BYTES) throw new IOException("配置文件缺失或超出大小限制");
        String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(Files.readAllBytes(file.toPath()))).toString();
        return AppConfig.parse(text);
    }

    private void atomicWrite(File target, String value) throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("无法创建私有配置目录");
        File temporary = new File(directory, target.getName() + ".tmp");
        try {
            try (FileOutputStream stream = new FileOutputStream(temporary)) {
                stream.write(value.getBytes(StandardCharsets.UTF_8));
                stream.getFD().sync();
            }
            Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally {
            try { Files.deleteIfExists(temporary.toPath()); }
            catch (IOException ignored) { /* Never report a committed rename as failed during cleanup. */ }
        }
    }
}
