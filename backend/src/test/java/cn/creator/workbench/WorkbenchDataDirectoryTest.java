package cn.creator.workbench;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assumptions.assumeFalse;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class WorkbenchDataDirectoryTest {
    @TempDir Path temp;

    @Test void usesSameBackendDataForIdeaMavenAndJar() throws IOException {
        Path backend = temp.resolve("backend");
        Files.createDirectories(backend.resolve("src/main/java/cn/creator/workbench"));
        Files.createFile(backend.resolve("pom.xml"));
        Files.createFile(backend.resolve("src/main/java/cn/creator/workbench/WorkbenchApplication.java"));
        Path expected = backend.resolve("data");
        assertEquals(expected, WorkbenchDataDirectory.resolve(temp.resolve("out/production/backend")));
        assertEquals(expected, WorkbenchDataDirectory.resolve(backend.resolve("target/classes")));
        assertEquals(expected, WorkbenchDataDirectory.resolve(backend.resolve("target/app.jar")));
    }

    @Test void standaloneJarUsesItsOwnDirectory() {
        assumeOutsideProject();
        assertEquals(temp.resolve("data"), WorkbenchDataDirectory.resolve(temp.resolve("app.jar")));
    }

    @Test void unknownClassesLocationDoesNotSilentlyUseWorkingDirectory() {
        assumeOutsideProject();
        assertThrows(IllegalStateException.class, () -> WorkbenchDataDirectory.resolve(temp.resolve("classes")));
    }

    private void assumeOutsideProject() {
        for (Path parent = temp; parent != null; parent = parent.getParent()) {
            assumeFalse(Files.isRegularFile(parent.resolve("backend/pom.xml")), "临时目录位于项目内");
            assumeFalse(Files.isRegularFile(parent.resolve("pom.xml")) && Files.isDirectory(parent.resolve("src/main/java/cn/creator/workbench")), "临时目录位于后端内");
        }
    }
}
