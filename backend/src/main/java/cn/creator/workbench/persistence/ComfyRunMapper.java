package cn.creator.workbench.persistence;

import java.util.List;
import org.apache.ibatis.annotations.*;

@Mapper
public interface ComfyRunMapper {
    @Select("SELECT * FROM comfy_run WHERE id=#{id}") ComfyRunRecord find(String id);
    @Select("SELECT * FROM comfy_run ORDER BY created_at DESC LIMIT 200") List<ComfyRunRecord> list();
    @Select("SELECT * FROM comfy_run WHERE project_id=#{projectId} ORDER BY created_at DESC LIMIT 200") List<ComfyRunRecord> byProject(String projectId);
    @Select("SELECT * FROM comfy_run WHERE state IN ('QUEUED','SUBMITTING','RUNNING','UNKNOWN','COLLECTING') ORDER BY created_at") List<ComfyRunRecord> active();
    @Insert("INSERT INTO comfy_run(id,project_id,node_id,template_id,prompt_id,payload,input_fingerprint,state,created_at) VALUES(#{id},#{projectId},#{nodeId},#{templateId},#{promptId},#{payload},#{inputFingerprint},#{state},#{createdAt})") void insert(ComfyRunRecord r);
    @Update("UPDATE comfy_run SET state=#{next},message=#{message} WHERE id=#{id} AND state=#{previous}") int transition(@Param("id") String id,@Param("previous") String previous,@Param("next") String next,@Param("message") String message);
    @Update("UPDATE comfy_run SET state='COLLECTING',file_ref=#{fileRef},message='正在回收候选素材' WHERE id=#{id} AND state=#{previous}") int claimCollect(@Param("id") String id,@Param("previous") String previous,@Param("fileRef") String fileRef);
    @Update("UPDATE comfy_run SET state='SUCCEEDED',file_ref=#{fileRef},sha256=#{sha256},byte_size=#{size},message=#{message} WHERE id=#{id} AND state='COLLECTING'") int result(@Param("id") String id,@Param("fileRef") String fileRef,@Param("sha256") String sha256,@Param("size") long size,@Param("message") String message);
    @Update("UPDATE comfy_run SET adopted=TRUE WHERE id=#{id} AND adopted=FALSE AND state='SUCCEEDED'") int adopt(String id);
}
