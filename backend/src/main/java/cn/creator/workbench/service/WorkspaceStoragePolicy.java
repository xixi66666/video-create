package cn.creator.workbench.service;

import jakarta.annotation.PostConstruct;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/** 避免正式工作台因遗漏配置而静默写入本机数据库。 */
@Component
public class WorkspaceStoragePolicy {
    private final Environment environment;
    public WorkspaceStoragePolicy(Environment environment){this.environment=environment;}
    @PostConstruct
    public void validate(){
        String url=environment.getProperty("spring.datasource.url", "");
        boolean localAllowed=environment.getProperty("workbench.allow-local-workspace", Boolean.class, false);
        if(!url.startsWith("jdbc:mysql:") && !localAllowed)
            throw new IllegalStateException("作品存储必须连接远端 MySQL；本地数据库仅允许用于隔离测试。");
    }
}
