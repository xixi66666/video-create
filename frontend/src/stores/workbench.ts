import {computed,ref} from 'vue'
import {defineStore} from 'pinia'
import data from '../data/catalog.json'
import {initialState,migrateWorkspace,uid,type Catalog,type Command,type WorkspaceState,type Asset} from '../lib/domain'
export const useWorkbench=defineStore('workbench',()=>{
 const catalog=data as Catalog,state=ref<WorkspaceState>(initialState(catalog)),connection=ref<'local'|'server'>('local'),ready=ref(false),saving=ref(false),notice=ref(''),noticeKind=ref<'success'|'error'>('success')
 let noticeTimer:ReturnType<typeof setTimeout>;let pending=Promise.resolve()
 function toast(message:string,kind:'success'|'error'='success'){notice.value=message;noticeKind.value=kind;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>notice.value='',5000)}
 async function init(){
  // 所有作品始终从服务端读取，连接失败时不切换至浏览器存储。
  const load=async()=>{
   try{
    const response=await fetch('/api/v1/workspace',{signal:AbortSignal.timeout(10000)})
    if(!response.ok)throw new Error('工作区请求失败')
    const body=await response.json();state.value=migrateWorkspace(body.data);connection.value='server';ready.value=true;return true
   }catch{
    toast('无法连接远端作品数据库，请检查后端和网络后重试','error');return false
   }
  }
  // 与写命令串行，避免刷新覆盖正在保存的工作区。
  const result=pending.then(load);pending=result.then(()=>{},()=>{});return result
 }
 async function command(cmd:Command,success='已保存'){
  const run=async()=>{saving.value=true;try{
   if(connection.value!=='server')throw new Error('远端数据库未连接，无法保存')
   const response=await fetch('/api/v1/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...cmd,expectedVersion:state.value.version})});const result=await response.json();if(!response.ok)throw new Error(result.message??'保存失败');state.value=result.data
   if(success)toast(success);return true
  }catch(e){toast(e instanceof Error?e.message:'操作失败，请重试','error');return false}finally{saving.value=false}}
  const result=pending.then(run);pending=result.then(()=>{});return result
 }
 const actualProjects=computed(()=>state.value.projects.filter(p=>!p.sample))
 async function addAsset(file:File,projectId='',source='人工上传'){
  const id=uid('asset');let fileRef='',sha256=''
  try{
  if(connection.value!=='server')throw new Error('远端数据库未连接，无法保存素材')
  const form=new FormData();form.append('file',file);const r=await fetch('/api/v1/files',{method:'POST',body:form});if(!r.ok){toast('文件上传失败','error');return}const saved=(await r.json()).data;fileRef=saved.fileRef;sha256=saved.sha256
  const asset:Asset={id,name:file.name,type:file.type||'application/octet-stream',size:file.size,source,fileRef,projectId,createdAt:new Date().toISOString(),sha256};if(await command({type:'ADD_ASSET',payload:{asset}},'素材已保存'))return asset
  }catch(e){toast(e instanceof Error?e.message:'文件保存失败','error')}
 }
 async function assetUrl(asset:Asset){if(!asset.fileRef.startsWith('indexeddb:'))return asset.fileRef;const db=await openFiles();const blob=await new Promise<Blob>((resolve,reject)=>{const req=db.transaction('files').objectStore('files').get(asset.id);req.onsuccess=()=>req.result?resolve(req.result):reject(new Error('素材文件不存在'));req.onerror=()=>reject(req.error)});db.close();return URL.createObjectURL(blob)}
 function openFiles():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const req=indexedDB.open('creator-workbench-files',1);req.onupgradeneeded=()=>req.result.createObjectStore('files');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error)})}
 function exportState(){const blob=new Blob([JSON.stringify({exportedAt:new Date().toISOString(),schemaVersion:1,state:state.value},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='creator-workbench-backup.json';a.click();URL.revokeObjectURL(url);toast('工作区数据已导出；文件素材需单独备份')}
 return {catalog,state,connection,ready,saving,notice,noticeKind,actualProjects,init,command,toast,addAsset,assetUrl,exportState}
})
