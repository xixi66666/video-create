import {computed,ref} from 'vue'
import {defineStore} from 'pinia'
import data from '../data/catalog.json'
import {applyCommand,initialState,migrateWorkspace,uid,type Catalog,type Command,type WorkspaceState,type Asset} from '../lib/domain'
export const useWorkbench=defineStore('workbench',()=>{
 const catalog=data as Catalog,state=ref<WorkspaceState>(initialState(catalog)),connection=ref<'local'|'server'>('local'),ready=ref(false),saving=ref(false),notice=ref(''),noticeKind=ref<'success'|'error'>('success')
 const key='creator-workbench-v1';let noticeTimer:ReturnType<typeof setTimeout>;let pending=Promise.resolve()
 function toast(message:string,kind:'success'|'error'='success'){notice.value=message;noticeKind.value=kind;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>notice.value='',5000)}
 async function init(){
  // 数据源只在首次初始化时选择，避免服务临时断线后把浏览器缓存当成服务端数据。
  const load=async()=>{
   const initialized=ready.value
   try{
    if(initialized&&connection.value==='local'){toast('当前是浏览器本地工作区；如需连接本机服务，请先备份本地数据再刷新页面','error');return false}
    const response=await fetch('/api/v1/workspace',{signal:AbortSignal.timeout(1800)})
    if(!response.ok)throw new Error('工作区请求失败')
    const body=await response.json();state.value=migrateWorkspace(body.data);connection.value='server';return true
   }catch{
    if(initialized){toast('无法刷新本机服务工作区，已保留当前数据；请检查连接后重试','error');return false}
    try{const stored=localStorage.getItem(key);if(stored){const parsed=JSON.parse(stored);if(parsed.projects&&parsed.models&&typeof parsed.version==='number')state.value=migrateWorkspace(parsed)}}catch{toast('本地存储无法读取，当前使用新工作区','error')}
    return true
   }finally{ready.value=true}
  }
  // 与写命令串行，避免刷新覆盖正在保存的工作区。
  const result=pending.then(load);pending=result.then(()=>{},()=>{});return result
 }
 async function command(cmd:Command,success='已保存'){
  const run=async()=>{saving.value=true;try{if(connection.value==='server'){const response=await fetch('/api/v1/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...cmd,expectedVersion:state.value.version})});const result=await response.json();if(!response.ok)throw new Error(result.message??'保存失败');state.value=result.data}else{
   if(cmd.type==='ADOPT_VISUAL_CANDIDATE'){
    const project=state.value.projects.find(p=>p.id===cmd.payload.projectId),candidate=project?.visualWorkbench?.candidates.find(c=>c.id===cmd.payload.candidateId),asset=state.value.assets.find(a=>a.id===candidate?.assetId)
    if(!candidate||!asset?.fileRef.startsWith('indexeddb:'))throw new Error('候选原件不存在，请重新上传')
    const url=await assetUrl(asset)
    try{const bytes=await(await fetch(url)).arrayBuffer();const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');if(hash!==candidate.sha256)throw new Error('视频原件已变化，请重新上传并登记候选')}finally{URL.revokeObjectURL(url)}
   }
   const next=applyCommand(state.value,cmd,catalog);localStorage.setItem(key,JSON.stringify(next));state.value=next}if(success)toast(success);return true}catch(e){toast(e instanceof Error?e.message:'操作失败，请重试','error');return false}finally{saving.value=false}}
  const result=pending.then(run);pending=result.then(()=>{});return result
 }
 const actualProjects=computed(()=>state.value.projects.filter(p=>!p.sample))
 async function addAsset(file:File,projectId='',source='人工上传'){
  const id=uid('asset');let fileRef='',sha256=''
  try{
  if(connection.value==='server'){const form=new FormData();form.append('file',file);const r=await fetch('/api/v1/files',{method:'POST',body:form});if(!r.ok){toast('文件上传失败','error');return}const saved=(await r.json()).data;fileRef=saved.fileRef;sha256=saved.sha256}
  else{sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');const db=await openFiles();await new Promise<void>((resolve,reject)=>{const tx=db.transaction('files','readwrite');tx.objectStore('files').put(file,id);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)});db.close();fileRef='indexeddb:'+id}
  const asset:Asset={id,name:file.name,type:file.type||'application/octet-stream',size:file.size,source,fileRef,projectId,createdAt:new Date().toISOString(),sha256};if(await command({type:'ADD_ASSET',payload:{asset}},'素材已保存'))return asset
  }catch(e){toast(e instanceof Error?e.message:'文件保存失败','error')}
 }
 async function assetUrl(asset:Asset){if(!asset.fileRef.startsWith('indexeddb:'))return asset.fileRef;const db=await openFiles();const blob=await new Promise<Blob>((resolve,reject)=>{const req=db.transaction('files').objectStore('files').get(asset.id);req.onsuccess=()=>req.result?resolve(req.result):reject(new Error('素材文件不存在'));req.onerror=()=>reject(req.error)});db.close();return URL.createObjectURL(blob)}
 function openFiles():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const req=indexedDB.open('creator-workbench-files',1);req.onupgradeneeded=()=>req.result.createObjectStore('files');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error)})}
 function exportState(){const blob=new Blob([JSON.stringify({exportedAt:new Date().toISOString(),schemaVersion:1,state:state.value},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='creator-workbench-backup.json';a.click();URL.revokeObjectURL(url);toast('工作区数据已导出；文件素材需单独备份')}
 return {catalog,state,connection,ready,saving,notice,noticeKind,actualProjects,init,command,toast,addAsset,assetUrl,exportState}
})
