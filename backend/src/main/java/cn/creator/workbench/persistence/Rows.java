package cn.creator.workbench.persistence;

import java.math.BigDecimal;

/** 关系表的行对象；字段公开，由 MyBatis 直接反射映射。 */
public final class Rows {
    private Rows() {}

    public static class Project {
        public String id, title, brief, template, poster, createdAt;
        public BigDecimal budget;
        public int sample;
        public long lockVersion;
    }

    public static class Node {
        public String projectId, nodeId, status, draft, output, skipReason, updatedAt;
        public int revision;
    }

    public static class Dependency {
        public String projectId, nodeId, dependsOn;
        public int depRevision;
    }

    public static class Approval {
        public String projectId, gateId, fingerprint, decision, decidedAt;
    }

    public static class Archived {
        public String projectId, nodeId, payload;
    }

    public static class Model {
        public String id, name, payload;
    }

    public static class Binding {
        public String scopeType, scopeId, capability, modelId;
    }

    public static class Task {
        public String id, projectId, nodeId, title, status, detail, createdAt, deletedAt;
    }

    public static class Asset {
        public String id, name, type, source, fileRef, projectId, createdAt;
        public long size;
    }

    public static class Idea {
        public String id, text, createdAt;
    }

    public static class Ledger {
        public String id, label, kind, createdAt;
        public BigDecimal amount;
    }

    public static class Profile {
        public String id, payload, updatedAt;
    }

    public static class Legacy {
        public String id, payload;
        public long revision;
    }
}
