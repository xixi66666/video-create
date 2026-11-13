package cn.creator.workbench.persistence;

/** Java 保存任务意图、业务输入快照和采纳状态；Python 保存执行 checkpoint。 */
public class AgentRunRecord {
    private String id, projectId, nodeId, payload, inputFingerprint, state, createdAt, deletedAt;
    private Integer dispatchAttempts;
    private String dispatchError;
    public String getId(){return id;} public void setId(String v){id=v;}
    public String getProjectId(){return projectId;} public void setProjectId(String v){projectId=v;}
    public String getNodeId(){return nodeId;} public void setNodeId(String v){nodeId=v;}
    public String getPayload(){return payload;} public void setPayload(String v){payload=v;}
    public String getInputFingerprint(){return inputFingerprint;} public void setInputFingerprint(String v){inputFingerprint=v;}
    public String getState(){return state;} public void setState(String v){state=v;}
    public String getCreatedAt(){return createdAt;} public void setCreatedAt(String v){createdAt=v;}
    public String getDeletedAt(){return deletedAt;} public void setDeletedAt(String v){deletedAt=v;}
    public Integer getDispatchAttempts(){return dispatchAttempts;} public void setDispatchAttempts(Integer v){dispatchAttempts=v;}
    public String getDispatchError(){return dispatchError;} public void setDispatchError(String v){dispatchError=v;}
}
