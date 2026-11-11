package cn.creator.workbench.persistence;

import org.apache.ibatis.annotations.*;
import java.util.List;

/** 关系化工作区读写。所有语句只用标准 SQL，H2(MySQL 模式) 与 MySQL 通用。 */
@Mapper
public interface RelationalMapper {

    // ---------- 根版本 ----------
    @Select("SELECT lock_version FROM workspace_meta WHERE id='1'")
    Long version();

    @Insert("INSERT INTO workspace_meta(id,lock_version,updated_at) VALUES('1',#{v},#{at})")
    void insertVersion(@Param("v") long v, @Param("at") String at);

    @Update("UPDATE workspace_meta SET lock_version=lock_version+1, updated_at=#{at} WHERE id='1' AND lock_version=#{expected}")
    int bumpVersion(@Param("expected") long expected, @Param("at") String at);

    /** 仅推进全局计数器，不参与根聚合的乐观锁，避免不同作品的写互相冲突。 */
    @Update("UPDATE workspace_meta SET lock_version=lock_version+1, updated_at=#{at} WHERE id='1'")
    int touchVersion(@Param("at") String at);

    // ---------- 作品 ----------
    @Select("SELECT * FROM project ORDER BY created_at DESC")
    List<Rows.Project> projects();

    @Select("SELECT COUNT(*) FROM project")
    int countProjects();

    @Select("SELECT lock_version FROM project WHERE id=#{id}")
    Long projectVersion(@Param("id") String id);

    @Insert("INSERT INTO project(id,title,brief,template,budget,sample,poster,created_at,lock_version) " +
            "VALUES(#{id},#{title},#{brief},#{template},#{budget},#{sample},#{poster},#{createdAt},#{lockVersion})")
    void insertProject(Rows.Project p);

    @Update("UPDATE project SET title=#{title},brief=#{brief},template=#{template},budget=#{budget}," +
            "sample=#{sample},poster=#{poster},lock_version=lock_version+1 " +
            "WHERE id=#{id} AND lock_version=#{lockVersion}")
    int updateProject(Rows.Project p);

    // ---------- 平台 ----------
    @Select("SELECT platform FROM project_platform WHERE project_id=#{pid} ORDER BY position")
    List<String> platforms(@Param("pid") String pid);

    @Delete("DELETE FROM project_platform WHERE project_id=#{pid}")
    void deletePlatforms(@Param("pid") String pid);

    @Insert("INSERT INTO project_platform(project_id,platform,position) VALUES(#{pid},#{platform},#{pos})")
    void insertPlatform(@Param("pid") String pid, @Param("platform") String platform, @Param("pos") int pos);

    // ---------- 节点 ----------
    @Select("SELECT * FROM node_instance WHERE project_id=#{pid}")
    List<Rows.Node> nodes(@Param("pid") String pid);

    @Insert("INSERT INTO node_instance(project_id,node_id,status,draft,output,revision,skip_reason,updated_at) " +
            "VALUES(#{projectId},#{nodeId},#{status},#{draft},#{output},#{revision},#{skipReason},#{updatedAt})")
    void insertNode(Rows.Node n);

    @Update("UPDATE node_instance SET status=#{status},draft=#{draft},output=#{output},revision=#{revision}," +
            "skip_reason=#{skipReason},updated_at=#{updatedAt} WHERE project_id=#{projectId} AND node_id=#{nodeId}")
    void updateNode(Rows.Node n);

    @Delete("DELETE FROM node_instance WHERE project_id=#{pid} AND node_id=#{nid}")
    void deleteNode(@Param("pid") String pid, @Param("nid") String nid);

    // ---------- 依赖 ----------
    @Select("SELECT * FROM node_dependency WHERE project_id=#{pid}")
    List<Rows.Dependency> dependencies(@Param("pid") String pid);

    @Delete("DELETE FROM node_dependency WHERE project_id=#{pid}")
    void deleteDependencies(@Param("pid") String pid);

    @Insert("INSERT INTO node_dependency(project_id,node_id,depends_on,dep_revision) VALUES(#{projectId},#{nodeId},#{dependsOn},#{depRevision})")
    void insertDependency(Rows.Dependency d);

    // ---------- 拍板 ----------
    @Select("SELECT * FROM approval_decision WHERE project_id=#{pid} ORDER BY decided_at")
    List<Rows.Approval> approvals(@Param("pid") String pid);

    @Delete("DELETE FROM approval_decision WHERE project_id=#{pid}")
    void deleteApprovals(@Param("pid") String pid);

    @Insert("INSERT INTO approval_decision(project_id,gate_id,fingerprint,decision,decided_at) VALUES(#{projectId},#{gateId},#{fingerprint},#{decision},#{decidedAt})")
    void insertApproval(Rows.Approval a);

    // ---------- 归档节点 ----------
    @Select("SELECT * FROM archived_node WHERE project_id=#{pid}")
    List<Rows.Archived> archived(@Param("pid") String pid);

    @Delete("DELETE FROM archived_node WHERE project_id=#{pid}")
    void deleteArchived(@Param("pid") String pid);

    @Insert("INSERT INTO archived_node(project_id,node_id,payload) VALUES(#{projectId},#{nodeId},#{payload})")
    void insertArchived(Rows.Archived a);

    // ---------- 模型 ----------
    @Select("SELECT * FROM model_profile ORDER BY id")
    List<Rows.Model> models();

    @Delete("DELETE FROM model_profile")
    void deleteModels();

    @Insert("INSERT INTO model_profile(id,name,payload) VALUES(#{id},#{name},#{payload})")
    void insertModel(Rows.Model m);

    // ---------- 绑定 ----------
    @Select("SELECT * FROM model_binding")
    List<Rows.Binding> bindings();

    @Delete("DELETE FROM model_binding WHERE scope_type IN ('GLOBAL','AGENT')")
    void deleteRootBindings();

    @Delete("DELETE FROM model_binding WHERE (scope_type='PROJECT' AND scope_id=#{pid}) " +
            "OR (scope_type='NODE' AND scope_id LIKE #{prefix})")
    void deleteProjectBindings(@Param("pid") String pid, @Param("prefix") String prefix);

    @Insert("INSERT INTO model_binding(scope_type,scope_id,capability,model_id) VALUES(#{scopeType},#{scopeId},#{capability},#{modelId})")
    void insertBinding(Rows.Binding b);

    // ---------- 任务 / 素材 / 灵感 / 账目 ----------
    @Select("SELECT * FROM task ORDER BY created_at DESC")
    List<Rows.Task> tasks();

    @Delete("DELETE FROM task")
    void deleteTasks();

    @Insert("INSERT INTO task(id,project_id,node_id,title,status,detail,created_at,deleted_at) VALUES(#{id},#{projectId},#{nodeId},#{title},#{status},#{detail},#{createdAt},#{deletedAt})")
    void insertTask(Rows.Task t);

    @Select("SELECT * FROM asset ORDER BY created_at DESC")
    List<Rows.Asset> assets();

    @Delete("DELETE FROM asset")
    void deleteAssets();

    @Insert("INSERT INTO asset(id,name,type,size,source,file_ref,project_id,created_at) VALUES(#{id},#{name},#{type},#{size},#{source},#{fileRef},#{projectId},#{createdAt})")
    void insertAsset(Rows.Asset a);

    @Select("SELECT * FROM idea ORDER BY created_at DESC")
    List<Rows.Idea> ideas();

    @Delete("DELETE FROM idea")
    void deleteIdeas();

    @Insert("INSERT INTO idea(id,text,created_at) VALUES(#{id},#{text},#{createdAt})")
    void insertIdea(Rows.Idea i);

    @Select("SELECT * FROM ledger_entry ORDER BY created_at DESC")
    List<Rows.Ledger> ledger();

    @Delete("DELETE FROM ledger_entry")
    void deleteLedger();

    @Insert("INSERT INTO ledger_entry(id,label,amount,kind,created_at) VALUES(#{id},#{label},#{amount},#{kind},#{createdAt})")
    void insertLedger(Rows.Ledger l);

    // ---------- 创作档案 ----------
    @Select("SELECT * FROM creator_profile WHERE id='1'")
    Rows.Profile profile();

    @Delete("DELETE FROM creator_profile")
    void deleteProfile();

    @Insert("INSERT INTO creator_profile(id,payload,updated_at) VALUES('1',#{payload},#{updatedAt})")
    void insertProfile(@Param("payload") String payload, @Param("updatedAt") String at);

    // ---------- 旧 JSON ----------
    @Select("SELECT id,payload,revision FROM workspace_document WHERE id='local'")
    Rows.Legacy legacy();

    @Delete("DELETE FROM workspace_document")
    void clearLegacy();
}
