package cn.creator.workbench.persistence;

import org.apache.ibatis.annotations.*;
import java.util.List;

@Mapper
public interface AgentRunMapper {
    @Select("SELECT r.*,COALESCE(d.attempts,0) AS dispatch_attempts,d.last_error AS dispatch_error FROM agent_run r LEFT JOIN agent_run_dispatch d ON d.run_id=r.id WHERE r.id=#{id}")
    AgentRunRecord find(String id);
    @Select("SELECT r.*,COALESCE(d.attempts,0) AS dispatch_attempts,d.last_error AS dispatch_error FROM agent_run r LEFT JOIN agent_run_dispatch d ON d.run_id=r.id ORDER BY r.created_at DESC LIMIT 200")
    List<AgentRunRecord> list();
    // 不能复用展示用的最近 200 条：更早的待投递任务也必须得到处理。
    @Select("SELECT r.*,COALESCE(d.attempts,0) AS dispatch_attempts,d.last_error AS dispatch_error FROM agent_run r LEFT JOIN agent_run_dispatch d ON d.run_id=r.id WHERE r.state IN ('PENDING_SUBMISSION','ACCEPT_PENDING_SYNC','REJECT_PENDING_SYNC','CANCEL_PENDING_SYNC') ORDER BY COALESCE(d.updated_at,r.created_at),r.id LIMIT 200")
    List<AgentRunRecord> pending();
    @Insert("INSERT INTO agent_run(id,project_id,node_id,payload,input_fingerprint,state,created_at) VALUES(#{id},#{projectId},#{nodeId},#{payload},#{inputFingerprint},#{state},#{createdAt})")
    void insert(AgentRunRecord record);
    @Update("UPDATE agent_run SET state=#{state} WHERE id=#{id}") void state(@Param("id") String id,@Param("state") String state);
    @Update("UPDATE agent_run SET deleted_at=#{at} WHERE id=#{id}") void visibility(@Param("id") String id,@Param("at") String at);
    @Update("UPDATE agent_run_dispatch SET attempts=attempts+1,last_error=#{error},updated_at=#{at} WHERE run_id=#{runId}")
    int bumpDispatch(@Param("runId") String runId,@Param("error") String error,@Param("at") String at);
    @Update("UPDATE agent_run_dispatch SET last_error=#{error},updated_at=#{at} WHERE run_id=#{runId}")
    void noteDispatchFailure(@Param("runId") String runId,@Param("error") String error,@Param("at") String at);
    @Update("UPDATE agent_run_dispatch SET last_error=NULL,updated_at=#{at} WHERE run_id=#{runId}")
    void clearDispatchError(@Param("runId") String runId,@Param("at") String at);
    @Insert("INSERT INTO agent_run_dispatch(run_id,attempts,last_error,updated_at) VALUES(#{runId},1,#{error},#{at})")
    void insertDispatch(@Param("runId") String runId,@Param("error") String error,@Param("at") String at);
    @Update("UPDATE agent_run_dispatch SET attempts=0,last_error=NULL,updated_at=#{at} WHERE run_id=#{runId}")
    void clearDispatch(@Param("runId") String runId,@Param("at") String at);
}
