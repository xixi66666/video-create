# 22 关系化存储：从单行 JSON 到按节点存行

日期：2026-11-09。本次把 `workspace_document` 的单行 JSON 拆成关系表；`agent_run`、`media_file` 结构不变。

## 1. 为什么要改

改之前整个工作区（所有作品 × 49 个节点 + 模型 + 账目 + 素材）是一行 `LONGTEXT`：

- 全库只有一个 `revision`，两个作品同时编辑必有一个 409；
- 改一个节点的 200 字草稿，要把整串 JSON 重写一遍；
- 数据库里搜不到 `N24`，不能建索引、不能按节点统计。

## 2. 现在的表

| 表 | 替换掉的 JSON 部分 | 主键 |
| --- | --- | --- |
| `workspace_meta` | 根 `version` | `id`（固定 `'1'`） |
| `project` | `projects[]` 元数据 | `id` |
| `project_platform` | `platforms[]` | `(project_id, platform)` |
| `node_instance` | `nodes["N02".."N50"]` | `(project_id, node_id)` |
| `node_dependency` | `nodes[].dependencies` | `(project_id, node_id, depends_on)` |
| `approval_decision` | `approvals{}` | `(project_id, gate_id)` |
| `archived_node` | `archivedNodes` / `archivedNodeBindings` | `(project_id, node_id)` |
| `model_profile` | `models[]` | `id` |
| `model_binding` | 四级绑定 | `(scope_type, scope_id, capability)` |
| `task` / `asset` / `idea` / `ledger_entry` / `creator_profile` | 同名部分 | `id` |
| `workspace_document` | 旧单行 JSON | 仅作导入源，新代码不写 |

节点级查询现在可以直接写：

```sql
SELECT status, draft, revision FROM node_instance
WHERE project_id = 'sample_focus' AND node_id = 'N24';
```

## 3. 并发与版本语义

- **作品级命令**（`SAVE_NODE`、`SKIP_NODE`、`APPROVE_GATE`，以及 `scope` 为 `PROJECT`/`NODE` 的绑定命令）用 `project.lock_version` 做乐观锁。两个作品、两个节点互不冲突。
- **根级命令**（模型、任务、灵感、账目、素材、档案、全局/角色绑定）用 `workspace_meta.lock_version` 做乐观锁。
- 客户端在 `GET /api/v1/workspace` 里拿到两套版本：根 `version` 和每个作品的 `lockVersion`；`POST /api/v1/commands` 的 `expectedVersion` 按命令类型选其一（前端 `versionFor()` 已实现）。
- 作品写入时会同时推进根计数器（`touchVersion`，不做 CAS），保证根 `version` 单调递增，但不会让不同作品的写互相 409。
- `synchronized` 已从 `WorkspaceService.execute` 移除，锁交给数据库的 `WHERE lock_version=?`。

## 4. 读取与写入

- `WorkspaceStore.load()`：从各表组装出与旧版完全相同的 JSON 视图，`GET /api/v1/workspace`、`AgentRunService.input()` 和前端都无需改动结构。
- `WorkspaceStore.save(before, after)`：比较命令前后的 JSON，只写变更的作品和变更的节点；依赖、审批、绑定、归档只在真正变化时重写。
- 节点的 JSON 字段顺序固定为 `status, draft, output, revision, dependencies, updatedAt?, skipReason?`，保证 `inputFingerprint` 与旧版一致。

## 5. 启动与迁移

### 本地 H2（默认）

`schema.sql` 已包含新表；首次启动时 `WorkspaceStore.bootstrap()` 会：

1. 若 `project` 表为空且 `workspace_document` 有行 → 导入旧 JSON（先归档退役的 N01）；
2. 否则导入 `initial-state.json` 的示例状态。

旧库不需要手工迁移，直接启动即可。

### MySQL

```powershell
# 1) 建表（一次性）
mysql -h <host> -P 3306 -u <user> -p < docs/sql/001_schema.sql

# 2) 可选：导入旧工作区（project 表必须为空）
mysql -h <host> -P 3306 -u <user> -p < docs/sql/002_import_legacy.sql

# 3) 用 mysql profile 启动
$env:CREATOR_DB_URL='jdbc:mysql://<host>:3306/creator_workbench?useUnicode=true&characterEncoding=utf8&serverTimezone=UTC'
$env:CREATOR_DB_USER='<user>'
$env:CREATOR_DB_PASSWORD='<password>'
java -jar backend/target/creator-workbench-0.2.0.jar --spring.profiles.active=mysql
```

`application-mysql.yml` 会把 `spring.sql.init.schema-locations` 指到 `schema-mysql.sql`，不会误执行 H2 版本。

## 6. 本轮没有做的

- 读取仍然是整份视图（`GET /workspace` 返回全部作品），前端契约未拆分为 `GET /projects/{id}/workspace`；作品很多时才需要。
- 节点的乐观锁粒度是作品（一次只锁一个作品），不是单个节点；同一作品的两个节点仍会互相 409。
- `DELETE_MODEL` 清理跨作品绑定时不加作品锁（属根级命令）。
- MySQL 未实机联调：本机无法连接目标库，验证只在 H2（`MODE=MySQL`）上完成。
