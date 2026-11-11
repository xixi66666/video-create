package cn.creator.workbench.service;

import cn.creator.workbench.persistence.*;
import com.google.gson.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;

/**
 * 工作区关系化存储：读时把行组装成原来的 JSON 视图，写时只落变更的行。
 * 乐观锁：根用 workspace_meta.lock_version，作品用 project.lock_version。
 */
@Component
public class WorkspaceStore {
    private final RelationalMapper mapper;
    private final String initial;
    private final Gson gson = new Gson();

    public WorkspaceStore(RelationalMapper mapper) throws IOException {
        this.mapper = mapper;
        try (InputStream in = new ClassPathResource("initial-state.json").getInputStream()) {
            this.initial = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    // ---------------- 初始化与迁移 ----------------

    /** 首次启动：优先导入旧单行 JSON，否则用示例初始状态。可重复执行。 */
    @Transactional
    public void bootstrap() {
        if (mapper.countProjects() > 0) return;
        JsonObject state = readLegacy();
        if (state == null) state = JsonParser.parseString(initial).getAsJsonObject();
        // 导入前先把退役的 N01 归档，避免旧数据把已退役节点带回活动流程
        WorkspaceService.archiveRetiredNode(state);
        importState(state);
    }

    private JsonObject readLegacy() {
        Rows.Legacy legacy = mapper.legacy();
        if (legacy == null || legacy.payload == null || legacy.payload.isBlank()) return null;
        return JsonParser.parseString(legacy.payload).getAsJsonObject();
    }

    private void importState(JsonObject state) {
        long version = state.has("version") ? state.get("version").getAsLong() : 0;
        mapper.insertVersion(version, now());
        for (JsonElement e : state.getAsJsonArray("projects")) insertProjectAggregate(e.getAsJsonObject());
        for (JsonElement e : array(state, "models")) {
            JsonObject m = e.getAsJsonObject();
            Rows.Model row = new Rows.Model();
            row.id = text(m, "id");
            row.name = text(m, "name");
            row.payload = m.toString();
            mapper.insertModel(row);
        }
        for (JsonElement e : array(state, "tasks")) {
            JsonObject t = e.getAsJsonObject();
            Rows.Task row = new Rows.Task();
            row.id = text(t, "id");
            row.projectId = text(t, "projectId");
            row.nodeId = t.has("nodeId") && !t.get("nodeId").isJsonNull() ? t.get("nodeId").getAsString() : null;
            row.title = text(t, "title");
            row.status = text(t, "status");
            row.detail = text(t, "detail");
            row.createdAt = text(t, "createdAt");
            row.deletedAt = t.has("deletedAt") ? t.get("deletedAt").getAsString() : null;
            mapper.insertTask(row);
        }
        for (JsonElement e : array(state, "assets")) {
            JsonObject a = e.getAsJsonObject();
            Rows.Asset row = new Rows.Asset();
            row.id = text(a, "id");
            row.name = text(a, "name");
            row.type = text(a, "type");
            row.size = a.has("size") ? a.get("size").getAsLong() : 0;
            row.source = text(a, "source");
            row.fileRef = text(a, "fileRef");
            row.projectId = text(a, "projectId");
            row.createdAt = text(a, "createdAt");
            mapper.insertAsset(row);
        }
        for (JsonElement e : array(state, "ideas")) {
            JsonObject i = e.getAsJsonObject();
            Rows.Idea row = new Rows.Idea();
            row.id = text(i, "id");
            row.text = text(i, "text");
            row.createdAt = text(i, "createdAt");
            mapper.insertIdea(row);
        }
        for (JsonElement e : array(state, "ledger")) {
            JsonObject l = e.getAsJsonObject();
            Rows.Ledger row = new Rows.Ledger();
            row.id = text(l, "id");
            row.label = text(l, "label");
            row.amount = l.has("amount") ? l.get("amount").getAsBigDecimal() : BigDecimal.ZERO;
            row.kind = text(l, "kind");
            row.createdAt = text(l, "createdAt");
            mapper.insertLedger(row);
        }
        if (state.has("profile")) {
            mapper.insertProfile(state.get("profile").toString(), now());
        }
        writeRootBindings(state);
    }

    // ---------------- 读取 ----------------

    public JsonObject load() {
        JsonObject root = new JsonObject();
        Long v = mapper.version();
        root.addProperty("version", v == null ? 0 : v);

        JsonArray projects = new JsonArray();
        for (Rows.Project p : mapper.projects()) projects.add(projectJson(p));
        root.add("projects", projects);

        JsonArray models = new JsonArray();
        for (Rows.Model m : mapper.models()) models.add(JsonParser.parseString(m.payload));
        root.add("models", models);

        JsonArray tasks = new JsonArray();
        for (Rows.Task t : mapper.tasks()) tasks.add(taskJson(t));
        root.add("tasks", tasks);

        JsonArray assets = new JsonArray();
        for (Rows.Asset a : mapper.assets()) assets.add(assetJson(a));
        root.add("assets", assets);

        JsonArray ideas = new JsonArray();
        for (Rows.Idea i : mapper.ideas()) {
            JsonObject o = new JsonObject();
            o.addProperty("id", i.id);
            o.addProperty("text", i.text);
            o.addProperty("createdAt", i.createdAt);
            ideas.add(o);
        }
        root.add("ideas", ideas);

        JsonObject global = new JsonObject();
        JsonObject agents = new JsonObject();
        for (Rows.Binding b : mapper.bindings()) {
            if ("GLOBAL".equals(b.scopeType)) global.addProperty(b.capability, b.modelId);
            else if ("AGENT".equals(b.scopeType)) ensure(agents, b.scopeId).addProperty(b.capability, b.modelId);
        }
        root.add("globalBindings", global);
        root.add("agentBindings", agents);

        Rows.Profile profile = mapper.profile();
        root.add("profile", profile == null || profile.payload == null ? new JsonObject() : JsonParser.parseString(profile.payload));

        JsonArray ledger = new JsonArray();
        for (Rows.Ledger l : mapper.ledger()) {
            JsonObject o = new JsonObject();
            o.addProperty("id", l.id);
            o.addProperty("label", l.label);
            o.addProperty("amount", l.amount);
            o.addProperty("kind", l.kind);
            o.addProperty("createdAt", l.createdAt);
            ledger.add(o);
        }
        root.add("ledger", ledger);
        return root;
    }

    private JsonObject projectJson(Rows.Project p) {
        JsonObject o = new JsonObject();
        o.addProperty("id", p.id);
        o.addProperty("title", p.title);
        o.addProperty("brief", p.brief);
        o.addProperty("template", p.template);
        JsonArray platforms = new JsonArray();
        for (String s : mapper.platforms(p.id)) platforms.add(s);
        o.add("platforms", platforms);
        o.addProperty("budget", p.budget == null ? BigDecimal.ZERO : p.budget);
        o.addProperty("sample", p.sample != 0);
        o.addProperty("poster", p.poster);
        o.addProperty("createdAt", p.createdAt);

        Map<String, Map<String, Integer>> deps = new HashMap<>();
        for (Rows.Dependency d : mapper.dependencies(p.id)) {
            deps.computeIfAbsent(d.nodeId, k -> new LinkedHashMap<>()).put(d.dependsOn, d.depRevision);
        }
        JsonObject nodes = new JsonObject();
        for (Rows.Node n : mapper.nodes(p.id)) nodes.add(n.nodeId, nodeJson(n, deps.get(n.nodeId)));
        o.add("nodes", nodes);

        JsonObject approvals = new JsonObject();
        for (Rows.Approval a : mapper.approvals(p.id)) {
            JsonObject item = new JsonObject();
            item.addProperty("id", a.gateId);
            item.addProperty("fingerprint", a.fingerprint);
            item.addProperty("decision", a.decision);
            item.addProperty("at", a.decidedAt);
            approvals.add(a.gateId, item);
        }
        o.add("approvals", approvals);

        JsonObject bindings = new JsonObject();
        JsonObject nodeBindings = new JsonObject();
        String prefix = p.id + "|";
        for (Rows.Binding b : mapper.bindings()) {
            if ("PROJECT".equals(b.scopeType) && p.id.equals(b.scopeId)) bindings.addProperty(b.capability, b.modelId);
            else if ("NODE".equals(b.scopeType) && b.scopeId.startsWith(prefix)) {
                ensure(nodeBindings, b.scopeId.substring(prefix.length())).addProperty(b.capability, b.modelId);
            }
        }
        o.add("bindings", bindings);
        o.add("nodeBindings", nodeBindings);

        List<Rows.Archived> archived = mapper.archived(p.id);
        if (!archived.isEmpty()) {
            JsonObject archivedNodes = new JsonObject();
            JsonObject archivedBindings = new JsonObject();
            for (Rows.Archived a : archived) {
                JsonObject payload = JsonParser.parseString(a.payload).getAsJsonObject();
                if (payload.has("node")) archivedNodes.add(a.nodeId, payload.get("node"));
                if (payload.has("bindings")) archivedBindings.add(a.nodeId, payload.get("bindings"));
            }
            if (!archivedNodes.isEmpty()) o.add("archivedNodes", archivedNodes);
            if (!archivedBindings.isEmpty()) o.add("archivedNodeBindings", archivedBindings);
        }
        o.addProperty("lockVersion", p.lockVersion);
        return o;
    }

    private static JsonObject nodeJson(Rows.Node n, Map<String, Integer> deps) {
        JsonObject o = new JsonObject();
        o.addProperty("status", n.status);
        o.addProperty("draft", n.draft == null ? "" : n.draft);
        o.addProperty("output", n.output == null ? "" : n.output);
        o.addProperty("revision", n.revision);
        JsonObject d = new JsonObject();
        if (deps != null) deps.forEach(d::addProperty);
        o.add("dependencies", d);
        if (n.updatedAt != null) o.addProperty("updatedAt", n.updatedAt);
        if (n.skipReason != null) o.addProperty("skipReason", n.skipReason);
        return o;
    }

    private static JsonObject taskJson(Rows.Task t) {
        JsonObject o = new JsonObject();
        o.addProperty("id", t.id);
        o.addProperty("projectId", t.projectId);
        if (t.nodeId != null) o.addProperty("nodeId", t.nodeId);
        o.addProperty("title", t.title);
        o.addProperty("status", t.status);
        o.addProperty("detail", t.detail);
        o.addProperty("createdAt", t.createdAt);
        if (t.deletedAt != null) o.addProperty("deletedAt", t.deletedAt);
        return o;
    }

    private static JsonObject assetJson(Rows.Asset a) {
        JsonObject o = new JsonObject();
        o.addProperty("id", a.id);
        o.addProperty("name", a.name);
        o.addProperty("type", a.type);
        o.addProperty("size", a.size);
        o.addProperty("source", a.source);
        o.addProperty("fileRef", a.fileRef);
        o.addProperty("projectId", a.projectId);
        o.addProperty("createdAt", a.createdAt);
        return o;
    }

    // ---------------- 写入 ----------------

    @Transactional
    public void save(JsonObject before, JsonObject after) {
        boolean changed = false;
        Map<String, JsonObject> beforeProjects = index(before.getAsJsonArray("projects"), "id");
        for (JsonElement e : after.getAsJsonArray("projects")) {
            JsonObject p = e.getAsJsonObject();
            String id = p.get("id").getAsString();
            JsonObject old = beforeProjects.get(id);
            if (old == null) { insertProjectAggregate(p); changed = true; }
            else if (!stripLock(old).equals(stripLock(p))) { saveProject(old, p); changed = true; }
        }
        if (!rootOf(before).equals(rootOf(after))) saveRoot(after);
        else if (changed) mapper.touchVersion(now());
    }

    private void saveRoot(JsonObject state) {
        Long current = mapper.version();
        if (current == null) mapper.insertVersion(0, now());
        else if (mapper.bumpVersion(current, now()) != 1) throw conflict();
        mapper.deleteModels();
        for (JsonElement e : array(state, "models")) {
            JsonObject m = e.getAsJsonObject();
            Rows.Model row = new Rows.Model();
            row.id = text(m, "id");
            row.name = text(m, "name");
            row.payload = m.toString();
            mapper.insertModel(row);
        }
        mapper.deleteRootBindings();
        writeRootBindings(state);
        mapper.deleteTasks();
        for (JsonElement e : array(state, "tasks")) {
            JsonObject t = e.getAsJsonObject();
            Rows.Task row = new Rows.Task();
            row.id = text(t, "id");
            row.projectId = text(t, "projectId");
            row.nodeId = t.has("nodeId") && !t.get("nodeId").isJsonNull() ? t.get("nodeId").getAsString() : null;
            row.title = text(t, "title");
            row.status = text(t, "status");
            row.detail = text(t, "detail");
            row.createdAt = text(t, "createdAt");
            row.deletedAt = t.has("deletedAt") ? t.get("deletedAt").getAsString() : null;
            mapper.insertTask(row);
        }
        mapper.deleteAssets();
        for (JsonElement e : array(state, "assets")) {
            JsonObject a = e.getAsJsonObject();
            Rows.Asset row = new Rows.Asset();
            row.id = text(a, "id");
            row.name = text(a, "name");
            row.type = text(a, "type");
            row.size = a.has("size") ? a.get("size").getAsLong() : 0;
            row.source = text(a, "source");
            row.fileRef = text(a, "fileRef");
            row.projectId = text(a, "projectId");
            row.createdAt = text(a, "createdAt");
            mapper.insertAsset(row);
        }
        mapper.deleteIdeas();
        for (JsonElement e : array(state, "ideas")) {
            JsonObject i = e.getAsJsonObject();
            Rows.Idea row = new Rows.Idea();
            row.id = text(i, "id");
            row.text = text(i, "text");
            row.createdAt = text(i, "createdAt");
            mapper.insertIdea(row);
        }
        mapper.deleteLedger();
        for (JsonElement e : array(state, "ledger")) {
            JsonObject l = e.getAsJsonObject();
            Rows.Ledger row = new Rows.Ledger();
            row.id = text(l, "id");
            row.label = text(l, "label");
            row.amount = l.has("amount") ? l.get("amount").getAsBigDecimal() : BigDecimal.ZERO;
            row.kind = text(l, "kind");
            row.createdAt = text(l, "createdAt");
            mapper.insertLedger(row);
        }
        mapper.deleteProfile();
        if (state.has("profile")) mapper.insertProfile(state.get("profile").toString(), now());
    }

    private void writeRootBindings(JsonObject state) {
        if (state.has("globalBindings")) {
            for (Map.Entry<String, JsonElement> e : state.getAsJsonObject("globalBindings").entrySet()) {
                Rows.Binding b = new Rows.Binding();
                b.scopeType = "GLOBAL";
                b.scopeId = "";
                b.capability = e.getKey();
                b.modelId = e.getValue().getAsString();
                mapper.insertBinding(b);
            }
        }
        if (state.has("agentBindings")) {
            for (Map.Entry<String, JsonElement> role : state.getAsJsonObject("agentBindings").entrySet()) {
                for (Map.Entry<String, JsonElement> e : role.getValue().getAsJsonObject().entrySet()) {
                    Rows.Binding b = new Rows.Binding();
                    b.scopeType = "AGENT";
                    b.scopeId = role.getKey();
                    b.capability = e.getKey();
                    b.modelId = e.getValue().getAsString();
                    mapper.insertBinding(b);
                }
            }
        }
    }

    private void saveProject(JsonObject before, JsonObject after) {
        String pid = after.get("id").getAsString();
        Rows.Project row = projectRow(after);
        row.lockVersion = before.has("lockVersion") ? before.get("lockVersion").getAsLong() : 0;
        if (mapper.updateProject(row) != 1) throw conflict();

        if (!platforms(before).equals(platforms(after))) {
            mapper.deletePlatforms(pid);
            insertPlatforms(pid, after);
        }

        Map<String, JsonObject> beforeNodes = index(before.getAsJsonObject("nodes"), null);
        Map<String, JsonObject> afterNodes = index(after.getAsJsonObject("nodes"), null);
        for (Map.Entry<String, JsonObject> e : afterNodes.entrySet()) {
            JsonObject old = beforeNodes.get(e.getKey());
            if (old == null) mapper.insertNode(nodeRow(pid, e.getKey(), e.getValue()));
            else if (!old.equals(e.getValue())) mapper.updateNode(nodeRow(pid, e.getKey(), e.getValue()));
        }
        for (String id : beforeNodes.keySet()) if (!afterNodes.containsKey(id)) mapper.deleteNode(pid, id);

        if (!dependencies(before).equals(dependencies(after))) {
            mapper.deleteDependencies(pid);
            for (Map.Entry<String, JsonObject> n : afterNodes.entrySet()) {
                JsonObject deps = n.getValue().getAsJsonObject("dependencies");
                if (deps == null) continue;
                for (Map.Entry<String, JsonElement> d : deps.entrySet()) {
                    Rows.Dependency dep = new Rows.Dependency();
                    dep.projectId = pid;
                    dep.nodeId = n.getKey();
                    dep.dependsOn = d.getKey();
                    dep.depRevision = d.getValue().getAsInt();
                    mapper.insertDependency(dep);
                }
            }
        }

        if (!obj(before, "approvals").equals(obj(after, "approvals"))) {
            mapper.deleteApprovals(pid);
            for (Map.Entry<String, JsonElement> e : obj(after, "approvals").entrySet()) {
                JsonObject a = e.getValue().getAsJsonObject();
                Rows.Approval rowA = new Rows.Approval();
                rowA.projectId = pid;
                rowA.gateId = e.getKey();
                rowA.fingerprint = text(a, "fingerprint");
                rowA.decision = text(a, "decision");
                rowA.decidedAt = text(a, "at");
                mapper.insertApproval(rowA);
            }
        }

        if (!archived(before).equals(archived(after))) {
            mapper.deleteArchived(pid);
            JsonObject nodes = obj(after, "archivedNodes");
            JsonObject binds = obj(after, "archivedNodeBindings");
            Set<String> ids = new LinkedHashSet<>(nodes.keySet());
            ids.addAll(binds.keySet());
            for (String id : ids) {
                JsonObject payload = new JsonObject();
                if (nodes.has(id)) payload.add("node", nodes.get(id));
                if (binds.has(id)) payload.add("bindings", binds.get(id));
                Rows.Archived rowArc = new Rows.Archived();
                rowArc.projectId = pid;
                rowArc.nodeId = id;
                rowArc.payload = payload.toString();
                mapper.insertArchived(rowArc);
            }
        }

        if (!bindings(before).equals(bindings(after))) {
            mapper.deleteProjectBindings(pid, pid + "|%");
            for (Map.Entry<String, JsonElement> e : obj(after, "bindings").entrySet()) {
                Rows.Binding b = new Rows.Binding();
                b.scopeType = "PROJECT";
                b.scopeId = pid;
                b.capability = e.getKey();
                b.modelId = e.getValue().getAsString();
                mapper.insertBinding(b);
            }
            for (Map.Entry<String, JsonElement> n : obj(after, "nodeBindings").entrySet()) {
                for (Map.Entry<String, JsonElement> e : n.getValue().getAsJsonObject().entrySet()) {
                    Rows.Binding b = new Rows.Binding();
                    b.scopeType = "NODE";
                    b.scopeId = pid + "|" + n.getKey();
                    b.capability = e.getKey();
                    b.modelId = e.getValue().getAsString();
                    mapper.insertBinding(b);
                }
            }
        }
    }

    private void insertProjectAggregate(JsonObject p) {
        String pid = p.get("id").getAsString();
        Rows.Project row = projectRow(p);
        row.lockVersion = p.has("lockVersion") ? p.get("lockVersion").getAsLong() : 0;
        mapper.insertProject(row);
        insertPlatforms(pid, p);
        for (Map.Entry<String, JsonObject> n : index(p.getAsJsonObject("nodes"), null).entrySet()) {
            mapper.insertNode(nodeRow(pid, n.getKey(), n.getValue()));
            JsonObject deps = n.getValue().getAsJsonObject("dependencies");
            if (deps == null) continue;
            for (Map.Entry<String, JsonElement> d : deps.entrySet()) {
                Rows.Dependency dep = new Rows.Dependency();
                dep.projectId = pid;
                dep.nodeId = n.getKey();
                dep.dependsOn = d.getKey();
                dep.depRevision = d.getValue().getAsInt();
                mapper.insertDependency(dep);
            }
        }
        for (Map.Entry<String, JsonElement> e : obj(p, "approvals").entrySet()) {
            JsonObject a = e.getValue().getAsJsonObject();
            Rows.Approval rowA = new Rows.Approval();
            rowA.projectId = pid;
            rowA.gateId = e.getKey();
            rowA.fingerprint = text(a, "fingerprint");
            rowA.decision = text(a, "decision");
            rowA.decidedAt = text(a, "at");
            mapper.insertApproval(rowA);
        }
        for (Map.Entry<String, JsonElement> e : obj(p, "bindings").entrySet()) {
            Rows.Binding b = new Rows.Binding();
            b.scopeType = "PROJECT";
            b.scopeId = pid;
            b.capability = e.getKey();
            b.modelId = e.getValue().getAsString();
            mapper.insertBinding(b);
        }
        for (Map.Entry<String, JsonElement> n : obj(p, "nodeBindings").entrySet()) {
            for (Map.Entry<String, JsonElement> e : n.getValue().getAsJsonObject().entrySet()) {
                Rows.Binding b = new Rows.Binding();
                b.scopeType = "NODE";
                b.scopeId = pid + "|" + n.getKey();
                b.capability = e.getKey();
                b.modelId = e.getValue().getAsString();
                mapper.insertBinding(b);
            }
        }
    }

    private void insertPlatforms(String pid, JsonObject p) {
        JsonArray platforms = p.getAsJsonArray("platforms");
        if (platforms == null) return;
        int i = 0;
        for (JsonElement e : platforms) mapper.insertPlatform(pid, e.getAsString(), i++);
    }

    private static Rows.Project projectRow(JsonObject p) {
        Rows.Project row = new Rows.Project();
        row.id = text(p, "id");
        row.title = text(p, "title");
        row.brief = text(p, "brief");
        row.template = text(p, "template");
        row.budget = p.has("budget") ? p.get("budget").getAsBigDecimal() : BigDecimal.ZERO;
        row.sample = p.has("sample") && p.get("sample").getAsBoolean() ? 1 : 0;
        row.poster = text(p, "poster");
        row.createdAt = text(p, "createdAt");
        return row;
    }

    private static Rows.Node nodeRow(String pid, String nodeId, JsonObject n) {
        Rows.Node row = new Rows.Node();
        row.projectId = pid;
        row.nodeId = nodeId;
        row.status = text(n, "status");
        row.draft = text(n, "draft");
        row.output = text(n, "output");
        row.revision = n.has("revision") ? n.get("revision").getAsInt() : 0;
        row.skipReason = n.has("skipReason") ? n.get("skipReason").getAsString() : null;
        row.updatedAt = n.has("updatedAt") ? n.get("updatedAt").getAsString() : null;
        return row;
    }

    // ---------------- 工具 ----------------

    private static BusinessException conflict() {
        return new BusinessException(409, "工作区已在其他窗口更新，请刷新后重试。");
    }

    private static String now() {
        return Instant.now().toString();
    }

    private static JsonObject rootOf(JsonObject state) {
        JsonObject root = new JsonObject();
        for (String key : new String[]{"models", "tasks", "assets", "ideas", "globalBindings", "agentBindings", "profile", "ledger"}) {
            if (state.has(key)) root.add(key, state.get(key));
        }
        return root;
    }

    private static JsonObject stripLock(JsonObject project) {
        JsonObject copy = project.deepCopy();
        copy.remove("lockVersion");
        return copy;
    }

    private static JsonArray array(JsonObject o, String key) {
        return o.has(key) && o.get(key).isJsonArray() ? o.getAsJsonArray(key) : new JsonArray();
    }

    private static JsonObject obj(JsonObject o, String key) {
        return o.has(key) && o.get(key).isJsonObject() ? o.getAsJsonObject(key) : new JsonObject();
    }

    private static String text(JsonObject o, String key) {
        return o.has(key) && !o.get(key).isJsonNull() ? o.get(key).getAsString() : "";
    }

    private static JsonObject ensure(JsonObject parent, String key) {
        if (!parent.has(key)) parent.add(key, new JsonObject());
        return parent.getAsJsonObject(key);
    }

    private static Map<String, JsonObject> index(JsonObject map, String ignored) {
        Map<String, JsonObject> result = new LinkedHashMap<>();
        for (Map.Entry<String, JsonElement> e : map.entrySet()) result.put(e.getKey(), e.getValue().getAsJsonObject());
        return result;
    }

    private static Map<String, JsonObject> index(JsonArray array, String keyField) {
        Map<String, JsonObject> result = new LinkedHashMap<>();
        for (JsonElement e : array) {
            JsonObject o = e.getAsJsonObject();
            result.put(o.get(keyField).getAsString(), o);
        }
        return result;
    }

    private static List<String> platforms(JsonObject p) {
        List<String> result = new ArrayList<>();
        if (p.has("platforms")) for (JsonElement e : p.getAsJsonArray("platforms")) result.add(e.getAsString());
        return result;
    }

    private static JsonObject dependencies(JsonObject project) {
        JsonObject result = new JsonObject();
        for (Map.Entry<String, JsonElement> n : obj(project, "nodes").entrySet()) {
            result.add(n.getKey(), obj(n.getValue().getAsJsonObject(), "dependencies"));
        }
        return result;
    }

    private static JsonObject archived(JsonObject project) {
        JsonObject result = new JsonObject();
        result.add("nodes", obj(project, "archivedNodes"));
        result.add("bindings", obj(project, "archivedNodeBindings"));
        return result;
    }

    private static JsonObject bindings(JsonObject project) {
        JsonObject result = new JsonObject();
        result.add("project", obj(project, "bindings"));
        result.add("nodes", obj(project, "nodeBindings"));
        return result;
    }
}
