package cn.creator.workbench.service;

import cn.creator.workbench.persistence.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;

@Service
public class MediaService {
    private final Path root;
    private final WorkspaceMapper mapper;
    public MediaService(@Value("${workbench.files-dir}")String root,WorkspaceMapper mapper)throws IOException{this.root=Path.of(root).toAbsolutePath().normalize();Files.createDirectories(this.root);this.mapper=mapper;}
    @Transactional
    public MediaRecord save(MultipartFile file)throws IOException{
        if(file.isEmpty()||file.getSize()>50L*1024*1024)throw new BusinessException(400,"请选择非空文件，且不超过 50MB。");
        String original=Optional.ofNullable(file.getOriginalFilename()).orElse("file").replace('\\','/');original=original.substring(original.lastIndexOf('/')+1).replaceAll("[\\p{Cntrl}]", "");if(original.isBlank())original="file";if(original.length()>240)original=original.substring(original.length()-240);
        String id=UUID.randomUUID().toString();Path target=root.resolve(id).normalize();if(!target.startsWith(root))throw new BusinessException(400,"文件路径无效");
        MessageDigest digest;try{digest=MessageDigest.getInstance("SHA-256");}catch(NoSuchAlgorithmException e){throw new IllegalStateException(e);}
        try(var input=new DigestInputStream(file.getInputStream(),digest)){Files.copy(input,target);}catch(Exception e){Files.deleteIfExists(target);throw e;}
        var record=new MediaRecord();record.setId(id);record.setOriginalName(original);record.setStorageName(id);record.setMediaType(Optional.ofNullable(file.getContentType()).filter(t->t.length()<120).orElse("application/octet-stream"));record.setByteSize(Files.size(target));record.setSha256(HexFormat.of().formatHex(digest.digest()));
        try{mapper.insertFile(record);}catch(RuntimeException e){Files.deleteIfExists(target);throw e;}
        // 外层候选回收事务失败时同时清理本次新建文件，避免数据库回滚后留下无主原件。
        if(org.springframework.transaction.support.TransactionSynchronizationManager.isSynchronizationActive())org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization(){
            @Override public void afterCompletion(int status){if(status==STATUS_ROLLED_BACK)try{Files.deleteIfExists(target);}catch(IOException ignored){/* 文件无法移除时保留，不能覆盖原始事务异常。 */}}
        });
        return record;
    }
    public MediaRecord find(String id){if(!id.matches("[a-zA-Z0-9_-]{1,64}"))throw new BusinessException(404,"素材不存在");var record=mapper.findFile(id);if(record==null)throw new BusinessException(404,"素材不存在");return record;}
    /** 本机生成候选使用与手工上传相同的容量边界，不接受调用者提供路径。 */
    public MediaRecord saveGeneratedVideo(byte[] bytes,String id)throws IOException{
        if(bytes.length==0||bytes.length>50L*1024*1024)throw new BusinessException(413,"生成视频超过 50MB 素材上限");
        if(bytes.length<12||bytes[4]!='f'||bytes[5]!='t'||bytes[6]!='y'||bytes[7]!='p')throw new BusinessException(400,"生成文件不是有效的 MP4 容器");
        if(!id.matches("[a-f0-9-]{36}"))throw new BusinessException(400,"候选文件标识无效");
        Path target=root.resolve(id);String hash;
        try{hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(NoSuchAlgorithmException e){throw new IllegalStateException(e);}
        var existing=mapper.findFile(id);
        if(existing!=null){if(!hash.equals(existing.getSha256())||!Files.isRegularFile(target))throw new IOException("候选文件与任务不一致");verify(existing);return existing;}
        // 仅在数据库尚无素材记录时恢复由同一任务 ID 派生的中断文件。
        if(Files.exists(target)){String disk=Files.size(target)==bytes.length?HexFormat.of().formatHex(digestFile(target)):"";if(!disk.equals(hash))Files.write(target,bytes,StandardOpenOption.TRUNCATE_EXISTING,StandardOpenOption.WRITE);}
        else Files.write(target,bytes,StandardOpenOption.CREATE_NEW);
        var record=new MediaRecord();record.setId(id);record.setOriginalName("comfy-"+id+".mp4");record.setStorageName(id);record.setMediaType("video/mp4");record.setByteSize(bytes.length);record.setSha256(hash);
        mapper.insertFile(record);return record;
    }
    private static byte[] digestFile(Path file)throws IOException{
        try{return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file));}catch(NoSuchAlgorithmException e){throw new IllegalStateException(e);}
    }
    /** 正式采用前重新核对原件，避免缺失或被外部修改的文件进入采用清单。 */
    public void verify(MediaRecord record){
        var resource=resource(record);
        try(var input=resource.getInputStream()){
            var digest=MessageDigest.getInstance("SHA-256");byte[] buffer=new byte[8192];int count;long size=0;
            while((count=input.read(buffer))!=-1){digest.update(buffer,0,count);size+=count;}
            if(size!=record.getByteSize()||!HexFormat.of().formatHex(digest.digest()).equals(record.getSha256()))throw new BusinessException(409,"素材原件已变化，请重新上传并登记候选");
        }catch(IOException e){throw new BusinessException(404,"素材原件无法读取，请重新上传");}catch(NoSuchAlgorithmException e){throw new IllegalStateException(e);}
    }
    public Resource resource(MediaRecord record){Path path=root.resolve(record.getStorageName()).normalize();if(!path.startsWith(root)||!Files.isRegularFile(path))throw new BusinessException(404,"素材原件不存在");return new FileSystemResource(path);}
}
