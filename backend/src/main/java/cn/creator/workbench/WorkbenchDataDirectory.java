package cn.creator.workbench;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.springframework.boot.EnvironmentPostProcessor;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.system.ApplicationHome;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

/** 根据程序位置确定默认数据目录，避免启动工作目录改变数据源。 */
public class WorkbenchDataDirectory implements EnvironmentPostProcessor {
    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        String configured = environment.getProperty("CREATOR_DATA_DIR");
        if (configured != null && !configured.isBlank()) return;
        var source = new ApplicationHome(WorkbenchApplication.class).getSource();
        Path location;
        try {
            // IDE 和测试中的 classes 目录不是 JAR，ApplicationHome 可能返回 null。
            location = source != null ? source.toPath()
                    : Path.of(WorkbenchApplication.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        } catch (Exception e) {
            throw new IllegalStateException("无法确定应用位置，请设置 CREATOR_DATA_DIR", e);
        }
        Path data = resolve(location);
        environment.getPropertySources().addLast(new MapPropertySource("workbenchDataDirectory",
                Map.of("workbench.default-data-dir", data.toString().replace('\\', '/'))));
    }

    static Path resolve(Path source) {
        Path absolute = source.toAbsolutePath().normalize();
        boolean jar = absolute.getFileName().toString().endsWith(".jar");
        Path directory = jar ? absolute.getParent() : absolute;
        for (Path current = directory; current != null; current = current.getParent()) {
            if (isBackend(current)) return current.resolve("data");
            if (isBackend(current.resolve("backend"))) return current.resolve("backend/data");
        }
        if (jar && directory != null) return directory.resolve("data");
        throw new IllegalStateException("无法定位 backend 目录，请设置 CREATOR_DATA_DIR");
    }

    private static boolean isBackend(Path path) {
        return Files.isRegularFile(path.resolve("pom.xml")) && Files.isRegularFile(path.resolve(
                "src/main/java/cn/creator/workbench/WorkbenchApplication.java"));
    }
}
