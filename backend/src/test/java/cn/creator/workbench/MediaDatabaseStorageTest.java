package cn.creator.workbench;

import cn.creator.workbench.persistence.WorkspaceMapper;
import cn.creator.workbench.service.MediaService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.support.TransactionTemplate;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:mediaDatabase;MODE=MySQL;DB_CLOSE_DELAY=-1", "workbench.media-storage=database"})
class MediaDatabaseStorageTest {
    @Autowired MediaService media;
    @Autowired WorkspaceMapper mapper;
    @Autowired JdbcTemplate jdbc;
    @Autowired TransactionTemplate transactions;

    @BeforeEach void schema(){jdbc.execute("CREATE TABLE IF NOT EXISTS creator_media_content (file_id VARCHAR(64) PRIMARY KEY, content BLOB NOT NULL)");}

    @Test void storesContentAndMetadataTogetherAndReadsThemBack() throws Exception {
        byte[] data="媒体原件".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        var saved=media.save(new MockMultipartFile("file","test.png","image/png",data));
        assertArrayEquals(data,media.resource(mapper.findFile(saved.getId())).getContentAsByteArray());
        media.verify(saved);
    }

    @Test void rollsBackContentAndMetadataTogether(){
        final String[] id={null};
        assertThrows(IllegalStateException.class,()->transactions.executeWithoutResult(status->{
            try { id[0]=media.save(new MockMultipartFile("file","test.png","image/png",new byte[]{1,2})).getId(); }
            catch(java.io.IOException ex){throw new RuntimeException(ex);}
            throw new IllegalStateException("rollback");
        }));
        assertNull(mapper.findFile(id[0]));
        assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM creator_media_content WHERE file_id=?",Integer.class,id[0]));
    }
}
