package cn.creator.workbench.persistence;

public class ComfyRunRecord {
    private String id,projectId,nodeId,templateId,promptId,payload,inputFingerprint,state,createdAt,message,fileRef,sha256;
    private Long byteSize;
    private boolean adopted;
    public String getId(){return id;} public void setId(String v){id=v;}
    public String getProjectId(){return projectId;} public void setProjectId(String v){projectId=v;}
    public String getNodeId(){return nodeId;} public void setNodeId(String v){nodeId=v;}
    public String getTemplateId(){return templateId;} public void setTemplateId(String v){templateId=v;}
    public String getPromptId(){return promptId;} public void setPromptId(String v){promptId=v;}
    public String getPayload(){return payload;} public void setPayload(String v){payload=v;}
    public String getInputFingerprint(){return inputFingerprint;} public void setInputFingerprint(String v){inputFingerprint=v;}
    public String getState(){return state;} public void setState(String v){state=v;}
    public String getCreatedAt(){return createdAt;} public void setCreatedAt(String v){createdAt=v;}
    public String getMessage(){return message;} public void setMessage(String v){message=v;}
    public String getFileRef(){return fileRef;} public void setFileRef(String v){fileRef=v;}
    public String getSha256(){return sha256;} public void setSha256(String v){sha256=v;}
    public Long getByteSize(){return byteSize;} public void setByteSize(Long v){byteSize=v;}
    public boolean isAdopted(){return adopted;} public void setAdopted(boolean v){adopted=v;}
}
