> 历史版本说明：本文记录 0.1 状态，以下旧版 H2 和浏览器本地存储描述不适用于当前正式工作台。当前作品存储和启动规则以 [作品存储规范](30-workspace-storage.md) 为准；多 Agent 的能力边界见 [运行说明](20-multi-agent-runtime.md)。

# 14 首个可运行版本：功能、运行与边界

更新：2026-10-26。当前已由文档阶段进入 0.1 实现阶段。原 01—13 是目标设计；本章记录实际实现，不能把全部设计当作已完成。

本轮更新见 [交互与兼容调整](17-workflow-update.md)：N01 已退役，旧产物归档；增加全局模型入口、局部默认、任务软删除和明确作品上下文。Agent 的真实实现见 [详细说明](16-agent-implementation.md)。

## 1. 已实现

- Vue 3 + TypeScript + Vite + Pinia + Router 的中文操作台，按页面分包；图标按需引用，GSAP 流程动效，支持减少动画偏好和手机布局。
- 桌面工作台、作品列表、项目内完整 49 个活动节点、依赖提示、草稿、手工产物、条件跳过、版本引用与下游待复查。
- 六类人工拍板，版本键绑定当前节点状态、版本和平台集合；服务端重验前提和并发版本。
- 模型档案：协议、服务地址、真实模型 ID、能力、JSON 参数及认证环境变量引用；全局、角色、项目和节点四级绑定。
- 灵感保存、创作档案、19 职责、外部工具说明、计划前提检查、素材上传预览下载、基础经营账目与数据导出。
- Spring Boot 4.0.9、Java 21、MyBatis 4.0.0；默认 H2 文件数据库，提供 MySQL 配置。真实后端接口可以保存并在刷新后恢复。
- 后端不可用时切换为浏览器本地模式：localStorage 保存记录，IndexedDB 保存文件。页面清楚显示保存位置。

首页初始作品均标注“示例”，仅演示流程；新建作品不继承其进度。实际模型执行和平台发布均关闭。

## 2. 尚未实现

真实模型调用、能力测试与凭据读取；有预算约束的自动内容生产；ComfyUI/渲染/录屏等连接器；外部发布、评论和指标读取；多镜头、多音轨、多平台节点实例展开；正式结构化产物编辑器与完整 Schema 校验；时间点审片；配置导入；后台任务恢复、SSE 与多用户认证。

“自动推进”当前执行依赖与待拍板检查，生成真实的检查记录，随后明确阻塞。没有伪造模型调用、视频产物、费用或发布结果。

## 3. 运行环境

Node.js 22.6+（推荐 24）、Java 21+、Maven 3.6.3+。本次构建实际使用 Java 21、Maven 3.9.9。不要修改系统全局 Java；可仅对当前终端设置 JAVA_HOME。

### 首次安装与构建

```powershell
Set-Location 'D:\Code\creator-workbench'
node scripts/sync-catalog.mjs
Set-Location frontend
npm ci
npm test
npm run build
Set-Location ..\backend
# 当前终端的 JAVA_HOME 指向自己的 JDK 21 目录
mvn test package
Set-Location ..
```

### 一键启动

```powershell
.\scripts\start-local.ps1
# 或显式指定自己的 JDK：
.\scripts\start-local.ps1 -JavaHome 'C:\your-jdk-21-directory'
```

脚本检查 JDK、依赖、JAR 与端口，隐藏启动两个进程，等待健康检查；不修改全局环境变量。也支持查找已安装 VS Code Java 扩展中的 JDK。访问 http://127.0.0.1:5178/，API 健康检查 http://127.0.0.1:8088/api/v1/health。

```powershell
.\scripts\stop-local.ps1
```

停止脚本只处理记录中 PID、可执行文件与启动时间匹配的本项目进程，避免误停其他 Java/Node 程序。日志位于 `.run/`。

### 手工启动

```powershell
# 终端 1，在 backend 中；java 必须来自 JDK 21+
java -jar target/creator-workbench-0.1.0.jar
# 终端 2，在 frontend 中
npm run dev
```

## 4. 数据与数据库

后端默认使用 `backend/data/workbench.mv.db` 与 `backend/data/files`。仅监听 127.0.0.1；本版面向可信本机单用户，没有多用户身份认证，不应直接对公网开放。

初期使用 `workspace_document` 聚合快照 + `media_file` 文件元数据表。原因是先验证单用户全流程交互，以一笔事务提供版本 CAS，避免先铺大量未使用的业务表。49 个活动节点及产物记录真实持久化，非内存假接口。数据量和并行协作增长后，按文档 06 迁移为分表结构；该迁移仍未实施。

MySQL 模式通过 CREATOR_DB_URL、CREATOR_DB_USER、CREATOR_DB_PASSWORD 设置环境变量后，以 `--spring.profiles.active=mysql` 启动。需先建立数据库，运行账号的权限按部署需要配置。**本次实际验证的是 H2，MySQL 未联调。**

浏览器本地模式和后端数据库是两个独立工作区，当前不会自动合并。后端启动后刷新会读取后端数据；可先导出浏览器记录，避免误以为消失。原件需要独立备份，JSON 导出不包含文件。

## 5. 实际接口

| 接口 | 行为 |
| --- | --- |
| GET /api/v1/health | 本机服务状态和关闭的外部执行标记 |
| GET /api/v1/catalog | 从规格生成的完整节点与角色能力目录 |
| GET /api/v1/workspace | 当前数据库工作区快照 |
| POST /api/v1/commands | 校验命令、expectedVersion、依赖、审批和配置并保存 |
| POST /api/v1/files | 最大 50MB，文件与校验信息持久化 |
| GET /api/v1/files/{id} | 受限预览/下载，不接受任意本机路径 |

文档 06 中其余接口属于后续目标合同，未实现。命令类型在前后端领域层分别验证，不允许任意写入整个工作区快照。

## 6. 模型信息与保密

当前只保存认证环境变量**名称**，不会读取或发送真实密钥。模型默认未启用、未验证。地址不允许嵌入用户名、密码或查询凭据；参数中不允许保存认证头、API Key、密码等字段。后续接入时再实现适配器和凭据加载。

## 7. 前端参考与视觉实现

参考用户提供的 [MotionSites](https://motionsites.ai/) 公开页面中强调的排版、层级、动效与克制原则；没有获取或复制付费提示词。采用浅色工作区、海报式作品封面、流程线动效、状态反馈和页面切换。封面为本项目制作的示例图形，不是用户已完成的视频证据。系统字体回退保证无外部字体依赖。

## 8. 后续实施优先级

先实现用户实际模型协议和小额能力测试，再打通 G03 前的选题/脚本/分镜自动制作。保持 ComfyUI 等接入后置，按照原文档在目标机器验证。完善分范围实例、结构化编辑、任务恢复后再启用批量生成与真实发布。
