<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import {useWorkbench} from '../stores/workbench'
import {comfyApi,ComfyApiError,type ComfyReadiness,type ComfyRun} from '../lib/comfy-api'
import Icon from './Icon.vue'

const props=defineProps<{projectId:string;reasons:string[]}>()
const store=useWorkbench(),readiness=ref<ComfyReadiness>({online:false,enabled:false,templates:[]}),runs=ref<ComfyRun[]>([])
const templateId=ref(''),prompt=ref(''),seed=ref(42),error=ref(''),busy=ref(false),loaded=ref(false),uncertainId=ref('')
const pendingKey=()=>`creator-comfy-pending-${props.projectId}`
function rememberPending(id:string){uncertainId.value=id;try{if(id)localStorage.setItem(pendingKey(),id);else localStorage.removeItem(pendingKey())}catch{/* 存储不可用时仍阻止当前页面重复提交 */}}
const statusNames:Record<string,string>={QUEUED:'等待投递',SUBMITTING:'正在提交',RUNNING:'生成中',COLLECTING:'正在回收素材',UNKNOWN:'结果未知 · 等待对账',FAILED:'生成失败',SUCCEEDED:'候选已生成'}
const active=computed(()=>!!uncertainId.value||runs.value.some(r=>['QUEUED','SUBMITTING','RUNNING','COLLECTING','UNKNOWN'].includes(r.state)))
const template=computed(()=>readiness.value.templates.find(t=>t.id===templateId.value))
const canStart=computed(()=>store.connection==='server'&&readiness.value.enabled&&readiness.value.online&&template.value?.ready&&prompt.value.trim()&&Number.isSafeInteger(seed.value)&&seed.value>=0&&seed.value<=2147483647&&!props.reasons.length&&!active.value&&!busy.value)
let timer:ReturnType<typeof setInterval>|undefined,polling=false,stopped=false,lastReadiness=0
async function refresh(manual=false){
 if(polling||store.connection!=='server')return
 polling=true
 try{
  const checkReady=manual||!loaded.value||Date.now()-lastReadiness>=30000
  const [ready,list]=await Promise.all([checkReady?comfyApi<ComfyReadiness>('/readiness'):Promise.resolve(readiness.value),comfyApi<ComfyRun[]>('?projectId='+encodeURIComponent(props.projectId))])
  if(stopped)return
  if(checkReady)lastReadiness=Date.now()
  readiness.value=ready;runs.value=list.filter(r=>r.projectId===props.projectId&&r.nodeId==='N27');loaded.value=true
  if(uncertainId.value&&runs.value.some(r=>r.id===uncertainId.value))rememberPending('')
  if(!ready.templates.some(t=>t.id===templateId.value))templateId.value=ready.templates.find(t=>t.ready)?.id??''
  if(!uncertainId.value)error.value=''
 }catch(e){if(!stopped){lastReadiness=0;readiness.value={...readiness.value,online:false};if(manual||!loaded.value||!uncertainId.value)error.value=e instanceof Error?e.message:'无法连接视频生成服务'}}finally{polling=false}
}
async function start(){
 if(!canStart.value)return
 busy.value=true;error.value='';const id='comfy_'+crypto.randomUUID();rememberPending(id)
 try{
  await comfyApi<ComfyRun>('',{id,projectId:props.projectId,nodeId:'N27',templateId:templateId.value,prompt:prompt.value.trim(),seed:seed.value})
  await refresh(true);store.toast('视频任务已提交，完成后请检查候选素材')
 }catch(e){
  if(e instanceof ComfyApiError&&e.status<500&&e.status!==408)rememberPending('')
  await refresh()
  error.value=uncertainId.value?'提交结果未知，请刷新记录并检查后端状态；不要重复提交。':e instanceof Error?e.message:'提交失败，请检查状态'
 }
 finally{busy.value=false}
}
async function adopt(run:ComfyRun){
 if(busy.value||run.state!=='SUCCEEDED'||run.adopted)return
 busy.value=true;error.value=''
 try{await comfyApi<ComfyRun>('/'+encodeURIComponent(run.id)+'/adopt',{});await store.init();await refresh(true);store.toast('候选视频已保存到素材库，节点仍需核对后手动完成')}
 catch(e){error.value=e instanceof Error?e.message:'采纳失败，请检查当前作品与制作方案'}finally{busy.value=false}
}
function safeFileRef(ref:string|undefined){return !!ref&&/^\/api\/v1\/files\/[a-zA-Z0-9_-]+$/.test(ref)}
onMounted(()=>{try{uncertainId.value=localStorage.getItem(pendingKey())??''}catch{/* 保留当前页面的保护 */}refresh(true);timer=setInterval(()=>{if(!document.hidden)refresh()},3000)})
onUnmounted(()=>{stopped=true;if(timer)clearInterval(timer)})
</script>

<template>
 <section class="comfy-panel" aria-label="ComfyUI 视频生成">
  <div class="comfy-heading"><div><h3>本机视频生成</h3><p>按已确认的制作方案生成候选视频，检查后再放入素材库。</p></div><span :class="['badge',readiness.enabled&&readiness.online?'success':'neutral']">{{readiness.enabled&&readiness.online?'ComfyUI 已连接':'暂不可用'}}</span></div>
  <p v-if="store.connection!=='server'" class="comfy-note">请连接后端和远端数据库后使用视频生成。</p>
  <template v-else>
   <p v-if="readiness.message" class="comfy-note">{{readiness.message}}</p>
   <p v-if="error" class="comfy-error" role="alert">{{error}}</p>
   <p v-if="uncertainId" class="comfy-note">待核对的提交编号：{{uncertainId}}。若记录始终未出现，请先检查后端及 ComfyUI 状态。</p>
   <form @submit.prevent="start">
    <label>已配置工作流<select v-model="templateId" aria-label="视频工作流" :disabled="!readiness.enabled||!readiness.online"><option value="">选择工作流</option><option v-for="item in readiness.templates" :key="item.id" :value="item.id" :disabled="!item.ready">{{item.name}}{{item.ready?'':' · 不可用'}}</option></select></label>
    <p v-if="template?.message" class="comfy-note">{{template.message}}</p>
    <label>画面与声音描述<textarea v-model="prompt" aria-label="视频生成描述" maxlength="2000" rows="4" placeholder="填写经确认的镜头内容和声音要求"/></label>
    <p class="comfy-note">请核对描述与已确认的分镜一致；系统检查版本和依赖，但不会自动判断描述的语义是否符合分镜。</p>
    <div class="comfy-controls"><label>随机种子<input v-model.number="seed" aria-label="随机种子" type="number" min="0" max="2147483647" step="1" required></label><button class="btn primary" type="submit" :disabled="!canStart"><Icon name="Play" :size="15"/>生成候选视频</button><button type="button" class="btn" @click="refresh(true)"><Icon name="RotateCcw" :size="15"/>刷新状态</button></div>
    <p v-if="reasons.length" class="comfy-note">{{reasons[0]}}。完成依赖并确认制作方案后可生成。</p>
    <p v-else-if="active" class="comfy-note">已有任务正在处理或结果待核对；请先等待对账，不要重复提交。</p>
    <p class="comfy-note">任务可能耗时数分钟。生成文件是候选，不会自动完成节点或发布。</p>
   </form>
   <div v-if="runs.length" class="comfy-runs" aria-live="polite"><h4>本作品的生成记录</h4><article v-for="run in runs" :key="run.id" class="comfy-run"><div class="comfy-run-heading"><b>{{statusNames[run.state]??run.state}}</b><small>{{new Date(run.createdAt).toLocaleString('zh-CN')}}</small></div><p v-if="run.message">{{run.message}}</p><p v-if="run.state==='UNKNOWN'">任务可能已被接收，请等待服务对账；不要重新提交。</p><template v-if="run.state==='SUCCEEDED'&&safeFileRef(run.fileRef)"><video :src="run.fileRef" controls preload="metadata" aria-label="生成的视频候选"/><div class="comfy-actions"><a class="text-link" :href="run.fileRef" target="_blank" rel="noopener">打开候选视频</a><button class="btn" type="button" :disabled="busy||run.adopted" @click="adopt(run)">{{run.adopted?'已放入素材库':'采纳到素材库'}}</button></div></template></article></div>
  </template>
 </section>
</template>

<style scoped>
.comfy-panel{border:1px solid #dfe7db;background:#f9fbf7;border-radius:14px;padding:20px;margin:20px 0}.comfy-heading,.comfy-run-heading,.comfy-controls,.comfy-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.comfy-heading h3,.comfy-runs h4{margin:0;font-size:15px}.comfy-heading p,.comfy-note,.comfy-run p{font-size:12px;line-height:1.65;color:#6d7768;margin:8px 0}.comfy-panel form{display:grid;gap:12px;margin-top:14px}.comfy-panel label{display:grid;gap:6px;font-size:12px;font-weight:600}.comfy-panel select,.comfy-panel textarea,.comfy-panel input{width:100%;border:1px solid #dce3d9;background:#fff;border-radius:8px;padding:9px 10px;font:inherit;color:#34422f}.comfy-panel textarea{resize:vertical;min-height:90px}.comfy-controls label{min-width:120px;flex:1}.comfy-controls button{margin-top:20px}.comfy-error{font-size:12px;color:#a23d34;background:#fff0ee;padding:10px;border-radius:8px}.comfy-runs{border-top:1px solid #e0e8dd;margin-top:18px;padding-top:16px}.comfy-run{background:white;border:1px solid #e7ece3;border-radius:10px;padding:12px;margin-top:10px}.comfy-run-heading small{color:#8b9588}.comfy-run video{display:block;max-width:100%;max-height:320px;margin:12px auto;background:#101510;border-radius:8px}.comfy-actions{margin-top:10px}@media(max-width:600px){.comfy-controls{align-items:stretch;flex-direction:column}.comfy-controls button{margin-top:0}}
</style>
