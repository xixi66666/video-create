package cn.creator.workbench.persistence;

import org.apache.ibatis.annotations.*;
import java.util.List;

@Mapper
public interface VisualJobMapper {
    @Select("SELECT * FROM visual_generation_job WHERE id=#{id}") VisualJobRecord find(String id);
    @Select("SELECT * FROM visual_generation_job WHERE project_id=#{projectId} ORDER BY created_at DESC") List<VisualJobRecord> list(String projectId);
    @Select("SELECT * FROM visual_generation_job WHERE state IN ('QUEUED','SUBMITTING','SUBMITTED','RUNNING','UNKNOWN','CANCEL_REQUESTED','COLLECTION_FAILED') ORDER BY updated_at LIMIT 50") List<VisualJobRecord> pending();
    @Insert("INSERT INTO visual_generation_job(id,project_id,need_id,batch_id,state,payload,error,created_at,updated_at) VALUES(#{id},#{projectId},#{needId},#{batchId},#{state},#{payload},#{error},#{createdAt},#{updatedAt})") int insert(VisualJobRecord record);
    @Update("UPDATE visual_generation_job SET submitted_at=CASE WHEN state='QUEUED' AND #{state}='SUBMITTING' THEN #{at} ELSE submitted_at END,state=#{state},error=#{error},updated_at=#{at} WHERE id=#{id} AND state=#{expected}") int state(@Param("id")String id,@Param("expected")String expected,@Param("state")String state,@Param("error")String error,@Param("at")String at);
}
