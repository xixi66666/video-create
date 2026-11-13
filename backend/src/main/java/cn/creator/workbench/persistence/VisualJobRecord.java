package cn.creator.workbench.persistence;

/** 不可变任务输入与独立执行状态，运行结果须另行采用。 */
public class VisualJobRecord {
    private String id,projectId,needId,batchId,state,payload,error,createdAt,updatedAt,submittedAt;
    public String getId(){return id;} public void setId(String value){id=value;}
    public String getProjectId(){return projectId;} public void setProjectId(String value){projectId=value;}
    public String getNeedId(){return needId;} public void setNeedId(String value){needId=value;}
    public String getBatchId(){return batchId;} public void setBatchId(String value){batchId=value;}
    public String getState(){return state;} public void setState(String value){state=value;}
    public String getPayload(){return payload;} public void setPayload(String value){payload=value;}
    public String getError(){return error;} public void setError(String value){error=value;}
    public String getCreatedAt(){return createdAt;} public void setCreatedAt(String value){createdAt=value;}
    public String getUpdatedAt(){return updatedAt;} public void setUpdatedAt(String value){updatedAt=value;}
    public String getSubmittedAt(){return submittedAt;} public void setSubmittedAt(String value){submittedAt=value;}
}
