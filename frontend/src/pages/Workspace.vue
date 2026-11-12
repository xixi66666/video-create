<script setup lang="ts">
import {computed,reactive,ref,watch,onMounted,onBeforeUnmount} from 'vue'
import {useRoute,useRouter,onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router'
import {useWorkbench} from '../stores/workbench'
import {stages,statusNames,progress,blockingReasons,resolveModel,validApproval,fingerprint,templateNode,canSkipNode,projectActive} from '../lib/domain'
import Icon from '../components/Icon.vue'
import Dialog from '../components/Dialog.vue'
import VisualPlanHandoff from '../components/VisualPlanHandoff.vue'
import ModelDefaultSelect from '../components/ModelDefaultSelect.vue'
const store=useWorkbench(),route=useRoute(),router=useRouter(),search=ref(''),text=ref(''),savedText=ref(''),skipReason=ref('')
const project=computed(()=>store.state.projects.find(p=>p.id===route.params.id))
const reviewGate=computed(()=>store.catalog.gates.find(g=>g.id===route.query.gate))
const platformNames:Record<string,string>={DOUYIN:'抖音',XIAOHONGSHU:'小红书'}
const platformName=(id:string)=>platformNames[id]??id
const projectStatusNames:Record<string,string>={ACTIVE:'进行中',PAUSED:'已暂停',ABANDONED:'已放弃'}
const projectStatus=computed(()=>project.value?.status??'ACTIVE')
const gatePlatforms=computed(()=>reviewGate.value?.scope==='PLATFORM'?project.value?.platforms??[]:[])
const settingsOpen=ref(false)
const settings=reactive({title:'',brief:'',budget:0,platforms:[] as string[]})
const selectedId=computed(()=>String(route.query.node??reviewGate.value?.after[0]??store.catalog.nodes[0].id))
const selected=computed(()=>store.catalog.nodes.find(n=>n.id===selectedId.value)??store.catalog.nodes[0])
const nodeState=computed(()=>project.value?.nodes[selected.value.id])
const dirty=computed(()=>text.value!==savedText.value)
const agentReview=computed(()=>nodeState.value?.agentDraftReview)
const reviewAcknowledged=ref(false),fixtureReplaced=ref(false)
const reviewRequired=computed(()=>!!agentReview.value&&!(nodeState.value?.status==='COMPLETED'&&nodeState.value?.output===text.value&&agentReview.value.reviewedByHuman===true&&(store.connection==='server'||agentReview.value.localReviewedText===text.value)))
const reviewReady=computed(()=>!reviewRequired.value||(reviewAcknowledged.value&&(!agentReview.value?.fixture||fixtureReplaced.value)))
const groups=computed(()=>Object.entries(stages).map(([id,name])=>({id,name,nodes:store.catalog.nodes.filter(n=>n.stage===id&&(n.id+n.name).toLowerCase().includes(search.value.toLowerCase()))})).filter(g=>g.nodes.length))
const reasons=computed(()=>project.value?blockingReasons(project.value,selected.value,store.catalog):[])
const effectiveSelected=computed(()=>project.value?templateNode(store.catalog,project.value.template,selected.value):selected.value)
const canSkipSelected=computed(()=>!!project.value&&canSkipNode(project.value,selected.value,store.catalog))
const pendingGates=computed(()=>project.value?store.catalog.gates.filter(g=>g.after.every(id=>project.value!.nodes[id].status==='COMPLETED')&&!validApproval(project.value!,g)):[])
const reviewMaterials=computed(()=>reviewGate.value?.watches.map(id=>({definition:store.catalog.nodes.find(n=>n.id===id)!,state:project.value?.nodes[id]}))??[])
function approvalProblem(id:string){
 const pr=project.value,g=store.catalog.gates.find(g=>g.id===id)
 if(!pr||!g)return '找不到拍板材料'
 if(!projectActive(pr))return '项目当前不是进行中，请先恢复项目'
 if(dirty.value)return '请先保存或放弃当前未保存的修改'
 if(g.after.some(id=>pr.nodes[id].status!=='COMPLETED'))return '请先完成对应阶段的审阅材料'
 if(g.watches.some(id=>pr.nodes[id].status==='COMPLETED'&&pr.nodes[id].draft!==pr.nodes[id].output))return '材料含未采用草稿，请先标记完成或恢复已采用产物'
 return ''
}
function loadText(){text.value=nodeState.value?.draft??'';savedText.value=text.value;skipReason.value=''}
watch([()=>project.value?.id,()=>selected.value.id],loadText,{immediate:true,flush:'sync'})
// 任何内容或候选版本变化都要求重新确认，避免沿用旧版本的勾选。
watch([text,()=>selected.value.id,()=>agentReview.value?.runId,()=>agentReview.value?.candidateHash],()=>{reviewAcknowledged.value=false;fixtureReplaced.value=false},{flush:'sync'})
// 外部更新不覆盖正在编辑的缓冲区，保存成功后再更新基线。
watch(()=>nodeState.value?.draft,()=>{if(!dirty.value)loadText()})
function nextNode(currentId:string){
 const nodes=store.catalog.nodes,index=nodes.findIndex(n=>n.id===currentId)
 return nodes.slice(index+1).find(n=>!['COMPLETED','SKIPPED'].includes(project.value?.nodes[n.id]?.status??'NOT_STARTED'))
}
const blockedAction=computed(()=>{
 const pr=project.value
 if(!pr||!reasons.value.length||!projectActive(pr))return
 const missing=selected.value.dependsOn.find(id=>!['COMPLETED','SKIPPED'].includes(pr.nodes[id]?.status??'NOT_STARTED'))
 if(missing)return {label:`去完成 ${missing}`,nodeId:missing}
 const gate=store.catalog.gates.find(g=>g.blocks.includes(selected.value.id)&&!validApproval(pr,g))
 if(!gate)return
 const awaiting=gate.after.find(id=>pr.nodes[id]?.status!=='COMPLETED')
 if(awaiting)return {label:`去完成 ${awaiting}`,nodeId:awaiting}
 return {label:`去确认 ${gate.id}`,gateId:gate.id}
})
function followBlockedAction(){
 const action=blockedAction.value
 if(action?.nodeId)choose(action.nodeId)
 else if(action?.gateId)openGate(action.gateId)
}
function openGate(id:string){router.push({query:{...route.query,gate:id}})}
async function save(complete=false){
 if(!project.value)return false
 const content=text.value
 if(complete&&!reviewReady.value){store.toast('请先核对专家草稿并完成确认','error');return false}
 const next=complete?nextNode(selected.value.id):undefined
 const confirmation=complete&&reviewRequired.value&&agentReview.value?{agentReview:{runId:agentReview.value.runId,acknowledged:true,fixtureReplaced:fixtureReplaced.value}}:{}
 const ok=await store.command({type:'SAVE_NODE',payload:{projectId:project.value.id,nodeId:selected.value.id,text:content,complete,...confirmation}},complete?(next?`节点产物已完成，已进入 ${next.id} ${next.name}`:'节点产物已完成'):'草稿已保存')
 if(ok){savedText.value=content;if(complete&&next)router.push({query:{node:next.id}})}
 return ok
}
const changePrompt=ref(''),changeKind=ref<'leave'|'replace'>('leave'),changeOpen=ref(false),resolving=ref(false)
let decide:((proceed:boolean)=>void)|undefined
function finishChange(proceed:boolean){if(resolving.value)return;const resolve=decide;decide=undefined;changeOpen.value=false;resolve?.(proceed)}
function confirmChange(message:string,kind:'leave'|'replace'){
 if(decide)return Promise.resolve(false)
 changePrompt.value=message;changeKind.value=kind;changeOpen.value=true
 return new Promise<boolean>(resolve=>{decide=resolve})
}
async function saveAndContinue(){resolving.value=true;let ok=false;try{ok=await save(false)}finally{resolving.value=false}if(ok&&!dirty.value)finishChange(true)}
const guard=()=>!dirty.value||confirmChange('当前节点有未保存的修改。保存草稿后继续，或明确放弃修改。','leave')
onBeforeRouteLeave(guard)
onBeforeRouteUpdate((to,from)=>to.fullPath===from.fullPath||guard())
function beforeUnload(event:BeforeUnloadEvent){if(dirty.value){event.preventDefault();event.returnValue=''}}
onMounted(()=>window.addEventListener('beforeunload',beforeUnload))
onBeforeUnmount(()=>{window.removeEventListener('beforeunload',beforeUnload);decide?.(false)})
async function approve(id:string,platform?:string){
 const pr=project.value,g=store.catalog.gates.find(x=>x.id===id)
 if(!pr||!g||approvalProblem(id))return
 if(g.scope==='PLATFORM'&&!platform)return
 await store.command({type:'APPROVE_GATE',payload:{projectId:pr.id,gateId:id,platform,fingerprint:fingerprint(pr,g,platform)}},platform?`${platformName(platform)}平台已确认`:'阶段已确认，后续节点可以继续')
}
function platformApproved(id:string,platform:string){const pr=project.value,g=store.catalog.gates.find(x=>x.id===id);return !!pr&&!!g&&validApproval(pr,g,platform)}
function openSettings(){if(!project.value)return;settings.title=project.value.title;settings.brief=project.value.brief;settings.budget=project.value.budget;settings.platforms=[...project.value.platforms];settingsOpen.value=true}
async function saveSettings(){if(await store.command({type:'UPDATE_PROJECT',payload:{projectId:project.value!.id,title:settings.title,brief:settings.brief,budget:settings.budget,platforms:[...settings.platforms]}},'项目设置已保存'))settingsOpen.value=false}
async function setProjectStatus(status:'ACTIVE'|'PAUSED'|'ABANDONED'){if(!project.value)return;if(status==='ABANDONED'&&!window.confirm('放弃后仍保留历史，但不能继续完成节点或发起协作。确定放弃这个项目？'))return;await store.command({type:'SET_PROJECT_STATUS',payload:{projectId:project.value.id,status}},`项目已标记为${projectStatusNames[status]}`)}
function choose(id:string){if(id!==selected.value.id)router.push({query:{...route.query,node:id}})}
function setBinding(capability:string,modelId:string,scope='NODE'){store.command({type:'SET_BINDING',payload:{projectId:project.value!.id,nodeId:selected.value.id,capability,modelId,scope}},'模型绑定已更新')}
async function replaceText(content:string){
 if(text.value&&!(await confirmChange('此操作会替换编辑区的全部文字。你可以先保存当前草稿。','replace')))return false
 text.value=content;return true
}
async function template(){await replaceText(JSON.stringify(Object.fromEntries(selected.value.output.requiredFields.map(k=>[k,''])),null,2))}
async function importText(e:Event){
 const input=e.target as HTMLInputElement,file=input.files?.[0];input.value='';if(!file)return
 if(file.size>2_000_000){store.toast('文字产物请控制在 2MB 内，大文件请上传到素材库','error');return}
 const projectId=project.value?.id,nodeId=selected.value.id
 try{const content=await file.text();if(project.value?.id!==projectId||selected.value.id!==nodeId)return
 if(content.length>200000){store.toast('文字产物最多 200,000 字符，请缩短后重新导入','error');return}
 if(await replaceText(content))store.toast('文本已读取，请检查后保存')
 }catch{store.toast('文本读取失败，请重新选择文件','error')}
}
</script>
<style scoped>
/* 操作入口增加后允许换行，避免小屏将整个工作区撑宽。 */
.heading-actions{flex-wrap:wrap}
.agent-review{margin:16px 0;padding:16px;border:1px solid #d9dce9;border-radius:10px;background:#f7f8fc;color:#262a35;overflow-wrap:anywhere}
.agent-review h3{font-size:13px;margin-bottom:6px}
.agent-review p,.agent-review li{font-size:12px;line-height:1.7}
.agent-review ul{margin:6px 0 10px;padding-left:20px}
.agent-review label{display:flex;align-items:flex-start;gap:9px;margin-top:10px;font-size:12px;line-height:1.6;cursor:pointer}
.agent-review label input{flex:none;margin-top:3px}
.agent-review .review-help{margin-top:8px;color:#505767}
.blocked-note .text-link{margin-top:6px;color:var(--accent)}
@media(max-width:700px){.heading-actions{width:100%}.heading-actions .btn{flex:1 1 auto}}
</style>
<template><div v-if="project" class="page-content workspace-page"><div class="workspace-heading"><div><RouterLink to="/projects" class="back-link"><Icon name="ArrowLeft" :size="14"/>我的作品</RouterLink><div class="workspace-title"><h1>{{project.title}}</h1><span v-if="project.sample" class="badge neutral">示例作品</span></div><p>{{project.brief||'把你的创作想法，逐步变成一条作品。'}}</p></div><div class="heading-actions"><RouterLink v-if="['N27','N29'].includes(selected.id)" class="btn" :to="{path:'/candidates',query:{projectId:project.id,node:selected.id}}"><Icon name="Film"/>画面抽卡</RouterLink><RouterLink v-if="selected.id==='N28'" class="btn" :to="{path:'/voice',query:{projectId:project.id}}"><Icon name="AudioLines"/>配音工作台</RouterLink><button class="btn" @click="store.command({type:'PLAN_PROJECT',payload:{projectId:project.id}},'下一步计划已记录到任务中心')"><Icon name="Route"/>检查下一步</button><button class="btn" @click="openSettings"><Icon name="Settings2" :size="15"/>项目设置</button><RouterLink class="btn primary" :to="{path:'/runs',query:{projectId:project.id,node:selected.id}}"><Icon name="Play" :size="15"/>启动 Agent 协作</RouterLink></div></div><div class="project-model-default"><ModelDefaultSelect scope="PROJECT" :project-id="project.id" label="作品默认模型"/><label class="project-status">项目状态<select :value="projectStatus" @change="setProjectStatus(($event.target as HTMLSelectElement).value as 'ACTIVE'|'PAUSED'|'ABANDONED')"><option value="ACTIVE">进行中</option><option value="PAUSED">已暂停</option><option value="ABANDONED">已放弃</option></select></label><RouterLink :to="{path:'/workflow',query:{projectId:project.id}}" class="text-link"><Icon name="Workflow" :size="14"/>查看此作品的完整流程</RouterLink></div><div class="workspace-summary"><span><Icon name="Workflow" :size="15"/>{{progress(project)}} / {{store.catalog.nodes.length}} 个节点</span><div class="progress-line"><span :style="{transform:'scaleX('+progress(project)/store.catalog.nodes.length+')'}"/></div><span :class="{paused:projectStatus!=='ACTIVE'}"><i class="status-dot"/>{{projectStatusNames[projectStatus]}}</span><span>预算 ¥{{project.budget.toFixed(2)}}</span><span><i class="status-dot"/>{{store.connection==='server'?'数据库保存':'浏览器保存'}}</span></div><section v-if="reviewGate" class="gate-review" aria-label="拍板审阅材料"><div class="gate-review-heading"><div><h2>{{reviewGate.id}} · {{reviewGate.name}}</h2><p>{{reviewGate.decision}}</p><p>确认针对已采用产物；逐项核对材料状态与版本后再拍板。</p></div><button v-if="reviewGate.scope!=='PLATFORM'" class="btn primary" :disabled="store.saving||!!approvalProblem(reviewGate.id)||validApproval(project,reviewGate)" @click="approve(reviewGate.id)">{{validApproval(project,reviewGate)?'当前版本已确认':'确认当前版本'}}</button><span v-else class="badge neutral">{{validApproval(project,reviewGate)?'全部平台已确认':'按平台分别确认'}}</span></div><p v-if="approvalProblem(reviewGate.id)" class="gate-review-warning" role="status">{{approvalProblem(reviewGate.id)}}</p><p v-if="reviewGate.id==='G01'" class="gate-review-warning" role="status">当前版本账号基础 N02—N07 仍按项目保存；跨作品复用尚未实现，请在本项目完成后再确认。</p><div class="gate-materials"><button v-for="material in reviewMaterials" :key="material.definition.id" :class="['gate-material',{selected:selected.id===material.definition.id}]" @click="choose(material.definition.id)"><span>{{material.definition.id}} {{material.definition.name}}</span><small>{{statusNames[material.state?.status??'NOT_STARTED']}} · 版本 {{material.state?.revision??0}}<span v-if="material.state?.draft!==material.state?.output"> · 有草稿</span></small></button></div><div v-if="reviewGate.scope==='PLATFORM'" class="gate-platforms"><p>当前发布节点仍按项目保存；以下按平台分别记录确认，全部平台完成后才放行。</p><div v-for="p in gatePlatforms" :key="p" class="gate-platform-row"><b>{{platformName(p)}}</b><span class="muted small">{{platformApproved(reviewGate.id,p)?'已确认':'未确认'}}</span><button class="btn" :disabled="store.saving||!!approvalProblem(reviewGate.id)||platformApproved(reviewGate.id,p)" @click="approve(reviewGate.id,p)">{{platformApproved(reviewGate.id,p)?'已确认':'确认'+platformName(p)}}</button></div></div><div v-if="reviewGate.id==='G02'" class="gate-lifecycle"><button class="btn" :disabled="store.saving" @click="setProjectStatus('PAUSED')">暂存项目</button><button class="btn danger-text" :disabled="store.saving" @click="setProjectStatus('ABANDONED')">放弃项目</button><button v-if="projectStatus!=='ACTIVE'" class="btn" :disabled="store.saving" @click="setProjectStatus('ACTIVE')">恢复制作</button></div></section><p v-else-if="route.query.gate" class="gate-review-warning" role="alert">找不到此拍板事项，请返回待拍板列表重新打开。</p><div class="gate-banner" v-for="gate in pendingGates.filter(g=>g.id!==reviewGate?.id)" :key="gate.id"><span class="gate-symbol"><Icon name="CheckCheck" :size="20"/></span><div><b>{{gate.name}} · 等你拍板</b><p>{{gate.decision}}</p></div><button v-if="gate.scope!=='PLATFORM'" class="btn" :disabled="store.saving||!!approvalProblem(gate.id)" :title="approvalProblem(gate.id)" @click="approve(gate.id)">确认当前版本<Icon name="ArrowRight" :size="14"/></button><RouterLink v-else class="btn" :to="{query:{...route.query,gate:gate.id}}">按平台确认<Icon name="ArrowRight" :size="14"/></RouterLink></div><div class="workspace-grid"><aside class="node-sidebar"><div class="node-sidebar-title"><b>制作流程</b><span>{{store.catalog.nodes.length}}</span></div><div class="node-search"><Icon name="Search" :size="14"/><input v-model="search" placeholder="搜索节点" aria-label="搜索制作节点"></div><div class="node-groups"><section v-for="group in groups" :key="group.id"><h3>{{group.name}}</h3><button v-for="node in group.nodes" :key="node.id" :class="['node-item',{selected:selected.id===node.id}]" @click="choose(node.id)"><span :class="['node-indicator',project.nodes[node.id].status]"><Icon v-if="project.nodes[node.id].status==='COMPLETED'" name="Check" :size="11"/><Icon v-else-if="project.nodes[node.id].status==='NEEDS_REVALIDATION'" name="RotateCcw" :size="10"/></span><span>{{node.name}}</span><small>{{node.id}}</small></button></section></div></aside><section class="node-editor"><div class="editor-top"><span class="node-id">{{selected.id}}</span><span :class="['badge',nodeState?.status==='COMPLETED'?'success':'neutral']">{{statusNames[nodeState?.status??'NOT_STARTED']}}</span><span class="muted small">版本 {{nodeState?.revision??0}}</span></div><h2>{{selected.name}}</h2><p class="node-description">{{selected.inputDescription}}</p><div class="node-role"><Icon name="Bot" :size="15"/>{{store.catalog.agents.find(a=>a.id===selected.agentRole)?.name}}<span/>{{effectiveSelected.responsibility==='A'?'规则明确后可自动执行':effectiveSelected.responsibility==='B'?'人机协作':'由你主导'}}<span v-if="effectiveSelected.templateMode"> · 模板模式 {{effectiveSelected.templateMode}}</span></div><div class="input-requirements"><span class="field-heading">需要的输入</span><p>{{selected.inputDescription}}</p><div class="dependency-tags"><button v-for="dep in selected.dependsOn" :key="dep" @click="choose(dep)" :class="{done:project.nodes[dep].status==='COMPLETED'}"><Icon :name="project.nodes[dep].status==='COMPLETED'?'CheckCircle2':'Circle'" :size="12"/>{{dep}} {{store.catalog.nodes.find(n=>n.id===dep)?.name}}</button><span v-if="!selected.dependsOn.length" class="muted small">从你的真实想法开始，无前置依赖。</span></div></div><section v-if="agentReview" class="agent-review" aria-labelledby="agent-review-heading"><h3 id="agent-review-heading">{{agentReview.fixture?'测试产物 · 仅供流程验证':'专家草稿 · 请人工核对'}}</h3><p v-if="agentReview.fixture && reviewRequired">这份草稿来自测试模型，不能作为真实产物。请在下方编辑区替换测试正文和占位内容，填入你核实过的材料。</p><p v-else-if="agentReview.fixture">这份草稿最初来自测试模型；当前完成版本已记录你对真实材料的确认。</p><p v-else>草稿由专家生成，完成前请核对事实、来源及适用条件。</p><p v-if="agentReview.candidateVersion">候选第 {{agentReview.candidateVersion}} 版</p><template v-if="agentReview.uncertainties?.length"><p><b>待核实事项</b></p><ul><li v-for="(item,index) in agentReview.uncertainties" :key="index">{{item}}</li></ul></template><p v-else class="review-help">专家未列出待核实事项；仍需检查草稿及其依据。</p><fieldset v-if="reviewRequired"><legend>完成前的人工确认</legend><label><input type="checkbox" v-model="reviewAcknowledged"><span>我已核对草稿和待核实事项，并已处理或明确记录仍未解决的问题。</span></label><label v-if="agentReview.fixture"><input type="checkbox" v-model="fixtureReplaced"><span>我已移除测试正文与占位内容，并填入真实材料。</span></label><p class="review-help">修改内容或更换候选后需要重新确认。确认是人工判断，并不表示系统验证了事实。</p></fieldset><p v-else class="review-help">当前完成版本已记录人工确认；修改后需重新确认。</p></section><p class="editor-save-state" role="status">{{dirty?'有未保存的修改':'内容已保存'}}</p><div class="editor-label"><label for="node-output">本节点产物</label><div><button class="text-link" @click="template"><Icon name="Braces" :size="13"/>插入字段模板</button><label class="text-link import-label"><Icon name="Upload" :size="13"/>导入文本<input type="file" accept=".txt,.md,.json" hidden @change="importText"></label></div></div><textarea id="node-output" v-model="text" class="artifact-editor" :placeholder="'在这里整理'+selected.name+'的结果，也可以导入你在其他工具完成的文本。\n\n没有执行器时，手工交付同样可以继续完整流程。'" spellcheck="false"/><VisualPlanHandoff v-if="['N31','N32'].includes(selected.id)" :project-id="project.id" :node-id="selected.id"/><div class="required-fields"><span>交付字段</span><code v-for="field in selected.output.requiredFields" :key="field">{{field}}</code></div><div class="blocked-note" v-if="reasons.length"><Icon name="Info" :size="16"/><span>{{reasons[0]}}<small>可以先保存草稿，满足依赖后再标记完成。</small><button v-if="blockedAction" class="text-link" @click="followBlockedAction">{{blockedAction.label}}<Icon name="ArrowRight" :size="12"/></button></span></div><div class="editor-actions"><button class="btn" @click="save(false)" :disabled="store.saving"><Icon name="Save" :size="16"/>保存草稿</button><button class="btn primary" @click="save(true)" :disabled="store.saving||!text.trim()||!!reasons.length||!reviewReady"><Icon name="Check" :size="16"/>标记产物完成</button></div><details class="skip-control" v-if="canSkipSelected"><summary>该步骤不适用于当前制作路线？</summary><input v-model="skipReason" placeholder="说明原因及替代方式"><button class="btn" @click="store.command({type:'SKIP_NODE',payload:{projectId:project.id,nodeId:selected.id,reason:skipReason}},'已记录不适用原因')">记录并跳过</button></details></section><aside class="node-inspector"><section><h3><Icon name="SlidersHorizontal" :size="16"/>执行配置</h3><p class="small muted">未单独配置时继承作品、角色或全局模型。</p><ModelDefaultSelect scope="NODE" :project-id="project.id" :node-id="selected.id" label="本节点默认模型"/><div v-for="cap in effectiveSelected.recommendedCapabilities" :key="cap" class="model-binding"><label>{{store.catalog.capabilities.find(c=>c.id===cap)?.name}}</label><select :value="project.nodeBindings[selected.id]?.[cap]??''" @change="setBinding(cap,($event.target as HTMLSelectElement).value)"><option value="">继承上级配置</option><option v-for="m in store.state.models.filter(m=>m.capabilities.includes(cap))" :key="m.id" :value="m.id">{{m.name}} · 未验证</option></select><small>{{resolveModel(store.state,project,selected,cap).source}} · {{resolveModel(store.state,project,selected,cap).model?.name??'未配置'}}</small><details><summary>项目级默认</summary><select :value="project.bindings[cap]??''" @change="setBinding(cap,($event.target as HTMLSelectElement).value,'PROJECT')"><option value="">继承 Agent / 全局</option><option v-for="m in store.state.models.filter(m=>m.capabilities.includes(cap))" :key="m.id" :value="m.id">{{m.name}}</option></select></details></div><p v-if="!effectiveSelected.recommendedCapabilities.length" class="inspector-note">该步骤优先使用确定性工具或手工操作，无需强行选择大模型。</p><RouterLink to="/models" class="text-link">管理模型<Icon name="ArrowUpRight" :size="14"/></RouterLink></section><section><h3><Icon name="ShieldCheck" :size="16"/>完成标准</h3><p>{{selected.acceptanceCriteria}}</p></section><section><h3><Icon name="UserRoundCheck" :size="16"/>你的决定</h3><p>{{selected.humanAction}}</p></section><section><h3><Icon name="RotateCcw" :size="16"/>需要返工时</h3><p>{{selected.reworkAction}}</p></section><div class="inspector-info"><Icon name="Info" :size="16"/><p>支持手工交付和流程管理。LIVE 模型调用可能产生费用；外部执行能力取决于当前配置和服务状态。</p></div></aside></div></div><div v-else class="page-content empty-state"><Icon name="FolderSearch" :size="40"/><h1>找不到这条作品</h1><p>作品可能位于另一个工作区。</p><RouterLink to="/projects" class="btn primary">返回我的作品</RouterLink></div><Dialog :open="settingsOpen" title="项目设置" @close="settingsOpen=false"><form class="form-stack" @submit.prevent="saveSettings"><label>作品名称<input v-model="settings.title" required maxlength="100"></label><label>最初的想法<textarea v-model="settings.brief" rows="4" maxlength="10000"/></label><div class="form-row"><label>项目预算（元）<input v-model.number="settings.budget" type="number" min="0" max="1000000" step="0.01"></label><fieldset class="platform-field"><legend>发布平台</legend><label class="checkbox-label"><input type="checkbox" value="DOUYIN" v-model="settings.platforms">抖音</label><label class="checkbox-label"><input type="checkbox" value="XIAOHONGSHU" v-model="settings.platforms">小红书</label></fieldset></div><p class="form-hint">修改平台会使对应平台的发布授权失效，需要重新确认。</p><div class="dialog-actions"><button type="button" class="btn" @click="settingsOpen=false">取消</button><button class="btn primary" :disabled="store.saving||!settings.title.trim()||!settings.platforms.length">保存设置</button></div></form></Dialog><Dialog :open="changeOpen" title="保护当前编辑内容" @close="finishChange(false)"><p>{{changePrompt}}</p><div class="dialog-actions"><button class="btn" :disabled="resolving" @click="finishChange(false)">取消</button><button class="btn danger-text" :disabled="resolving" @click="finishChange(true)">{{changeKind==='replace'?'替换当前内容':'放弃修改并继续'}}</button><button v-if="dirty" class="btn primary" :disabled="resolving||store.saving" @click="saveAndContinue">保存草稿并继续</button></div></Dialog></template>
