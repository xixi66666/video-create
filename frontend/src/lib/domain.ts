import {applyVisualCommand,visualCommands,migrateVisualWorkbench,type VisualWorkbench} from './visual-candidates.ts'
import {validateModelParameters} from './model-parameters.ts'
export type NodeStatus='NOT_STARTED'|'DRAFT'|'COMPLETED'|'SKIPPED'|'NEEDS_REVALIDATION'
export interface TemplateOverride {mode?:string;skipReasonRequired?:boolean;responsibility?:string;recommendedCapabilities?:string[]}
export interface NodeDefinition {id:string;name:string;stage:string;responsibility:string;scope:string;dependsOn:string[];agentRole:string;recommendedCapabilities:string[];inputDescription:string;output:{artifactType:string;requiredFields:string[]};humanAction:string;acceptanceCriteria:string;reworkAction:string;applicability:string;templateMode?:string}
export interface AgentDraftReview {runId:string;fixture:boolean;uncertainties:string[];candidateVersion?:number;candidateHash?:string;fixtureBody?:string;reviewedAt?:string;reviewedTextSha256?:string;reviewedByHuman?:boolean;localReviewedText?:string}
export interface NodeState {status:NodeStatus;draft:string;output:string;revision:number;dependencies:Record<string,number>;updatedAt?:string;skipReason?:string;visualInputRevision?:number;agentDraftReview?:AgentDraftReview}
export interface Approval {id:string;gateId?:string;platform?:string;scope?:string;fingerprint:string;at:string;decision:'APPROVED'|'REJECTED'}
export interface Project {voiceCast?:{speaker:string;roleId:string;name:string;version:string}[];visualWorkbench?:VisualWorkbench;videoWorkbench?:{shots:Record<string,any>[];batches:Record<string,any>[];candidates:Record<string,any>[];adoptions:Record<string,any>[]};id:string;title:string;brief:string;template:string;platforms:string[];budget:number;sample:boolean;poster:string;createdAt:string;status?:'ACTIVE'|'PAUSED'|'ABANDONED';updatedAt?:string;nodes:Record<string,NodeState>;archivedNodes?:Record<string,NodeState>;archivedNodeBindings?:Record<string,Record<string,string>>;approvals:Record<string,Approval>;bindings:Record<string,string>;nodeBindings:Record<string,Record<string,string>>}
export interface Model {id:string;name:string;provider:string;protocol:string;baseUrl:string;remoteModelId:string;credentialRef:string;capabilities:string[];parameters:Record<string,unknown>;enabled:boolean;verified:boolean}
export interface Task {id:string;projectId:string;nodeId?:string;title:string;status:'COMPLETED'|'BLOCKED'|'PAUSED';detail:string;createdAt:string;deletedAt?:string}
export interface Asset {sha256?:string;id:string;name:string;type:string;size:number;source:string;fileRef:string;projectId:string;createdAt:string}
export interface Idea {id:string;text:string;createdAt:string}
export interface WorkspaceState {version:number;projects:Project[];models:Model[];tasks:Task[];assets:Asset[];ideas:Idea[];globalBindings:Record<string,string>;agentBindings:Record<string,Record<string,string>>;profile:Record<string,string>;ledger:{id:string;label:string;amount:number;kind:'income'|'cost';createdAt:string}[]}
export interface Catalog {nodes:NodeDefinition[];agents:{id:string;name:string;workUnit:string;responsibility:string}[];capabilities:{id:string;name:string;purpose:string}[];gates:{id:string;name:string;after:string[];watches:string[];blocks:string[];decision:string;scope?:string}[];templates:{id:string;name:string;nodeIds?:string[];overrides?:Record<string,TemplateOverride>;notes?:string}[]}
export interface Command {type:string;payload:Record<string,any>;expectedVersion?:number}
export const stages:Record<string,string>={FOUNDATION:'创作基础',IDEATION:'灵感与选题',PREPRODUCTION:'脚本与分镜',PRODUCTION:'素材制作',POSTPRODUCTION:'剪辑后期',DELIVERY:'包装与发布',REVIEW:'反馈与复盘',LIBRARY:'资产沉淀',BUSINESS:'副业经营'}
export const statusNames:Record<string,string>={NOT_STARTED:'未开始',DRAFT:'草稿',COMPLETED:'已完成',SKIPPED:'不适用',NEEDS_REVALIDATION:'需复查'}
export const uid=(prefix='id')=>`${prefix}_${globalThis.crypto?.randomUUID?.()??Math.random().toString(36).slice(2)}`
export function blankNode():NodeState{return {status:'NOT_STARTED',draft:'',output:'',revision:0,dependencies:{}}}
export function makeProject(data:Record<string,any>,nodes:NodeDefinition[]):Project{
 const title=String(data.title??'').trim();if(!title)throw new Error('请填写作品名称')
 const platforms=Array.isArray(data.platforms)?[...data.platforms]:['DOUYIN','XIAOHONGSHU']
 if(!platforms.length||platforms.some(p=>!['DOUYIN','XIAOHONGSHU'].includes(p)))throw new Error('至少选择一个有效发布平台')
 return {id:data.id??uid('project'),title,brief:String(data.brief??''),template:data.template??'SCREENCAST',platforms,budget:Number(data.budget??100),sample:Boolean(data.sample),poster:data.poster??'blue',createdAt:new Date().toISOString(),status:'ACTIVE',nodes:Object.fromEntries(nodes.map(n=>[n.id,blankNode()])),approvals:{},bindings:{},nodeBindings:{}}
}
export function initialState(catalog:Catalog):WorkspaceState{
 const titles=[['sample_focus','把时间，留给重要的事','把我的效率实践整理成一条有真实例子的短视频。','sage',22],['sample_ai','普通人的 AI 使用手册','用模拟会议材料演示 AI 纪要，再核对负责人和截止时间。','blue',14],['sample_studio','一个人的工作室','记录独立创作者从想法到成片的真实过程。','apricot',7]]
 const projects=titles.map(([id,title,brief,poster,count])=>{const p=makeProject({id,title,brief,poster,sample:true},catalog.nodes);catalog.nodes.slice(0,Number(count)).forEach(n=>{const text=`示例产物：${n.name}。此内容用于演示界面，不代表真实执行结果。`;p.nodes[n.id]={...blankNode(),status:'COMPLETED',revision:1,draft:text,output:text}});return p})
 return {version:0,projects,models:[],tasks:[],assets:[],ideas:[],globalBindings:{},agentBindings:{},profile:{},ledger:[]}
}
/** 移除退役节点的活动入口，保留历史产物和绑定，不改动其他节点 ID。 */
export function migrateWorkspace(input:WorkspaceState):WorkspaceState {
 const state=JSON.parse(JSON.stringify(input)) as WorkspaceState
 for(const p of state.projects){
  migrateVisualWorkbench(p)
  if(p.nodes.N01){(p.archivedNodes??={}).N01=p.nodes.N01;delete p.nodes.N01}
  if(p.nodeBindings.N01){(p.archivedNodeBindings??={}).N01=p.nodeBindings.N01;delete p.nodeBindings.N01}
  for(const n of Object.values(p.nodes))delete n.dependencies.N01
 }
 return state
}
export function approvalKey(gateId:string,platform?:string){return platform?`${gateId}:${platform}`:gateId}
export function fingerprint(project:Project,gate:Catalog['gates'][number],platform?:string){return `${project.id}|${platform?platform+'|':''}${project.platforms.join(',')}|${gate.watches.map(n=>`${n}@${project.nodes[n]?.revision??0}:${project.nodes[n]?.status??'NOT_STARTED'}${project.nodes[n]?.visualInputRevision?'~v'+project.nodes[n].visualInputRevision:''}`).join('|')}`}
export function validApproval(project:Project,gate:Catalog['gates'][number],platform?:string):boolean{
 if(!platform&&gate.scope==='PLATFORM')return project.platforms.length>0&&project.platforms.every(item=>validApproval(project,gate,item))
 const a=project.approvals[approvalKey(gate.id,platform)];return a?.decision==='APPROVED'&&a.fingerprint===fingerprint(project,gate,platform)
}
export function projectActive(project:Project){return !project.status||project.status==='ACTIVE'}
export function blockingReasons(project:Project,node:NodeDefinition,catalog:Catalog):string[]{
 const reasons:string[]=[]
 if(!projectActive(project))reasons.push('项目当前不是进行中，请恢复项目后再继续')
 node.dependsOn.filter(id=>!['COMPLETED','SKIPPED'].includes(project.nodes[id]?.status)).forEach(id=>reasons.push(`等待 ${id} ${catalog.nodes.find(n=>n.id===id)?.name??''}`))
 catalog.gates.filter(g=>g.blocks.includes(node.id)&&!validApproval(project,g)).forEach(g=>reasons.push(`等待${g.name}（${g.id}）`));return reasons
}
/** 模板只覆盖展示与条件适用，不改变节点依赖和产物合同。 */
export function templateNode(catalog:Catalog,templateId:string,node:NodeDefinition):NodeDefinition{
 const override=catalog.templates.find(t=>t.id===templateId)?.overrides?.[node.id]
 if(!override)return node
 return {...node,...(override.responsibility?{responsibility:override.responsibility}:{}),...(override.recommendedCapabilities?{recommendedCapabilities:override.recommendedCapabilities}:{}),...(override.mode?{templateMode:override.mode}:{})}
}
export function canSkipNode(project:Project,node:NodeDefinition,catalog:Catalog):boolean{
 return catalog.templates.find(t=>t.id===project.template)?.overrides?.[node.id]?.mode==='CONDITIONAL'
}
/** 结构化 JSON 产物检查必填字段；普通自由文本仍保留手工交付能力。 */
export function validateStructuredFields(node:NodeDefinition,text:string):void{
 const trimmed=text.trim();if(!trimmed.startsWith('{')||!trimmed.endsWith('}'))return
 let value:unknown;try{value=JSON.parse(trimmed)}catch{return}
 if(!value||typeof value!=='object'||Array.isArray(value))return
 const missing=node.output.requiredFields.filter(key=>{const item=(value as Record<string,unknown>)[key];return item===undefined||item===null||(typeof item==='string'&&!item.trim())})
 if(missing.length)throw new Error('结构化产物缺少必填字段：'+missing.join('、'))
}
export function resolveModel(state:WorkspaceState,project:Project,node:NodeDefinition,capability:string){
 const candidates=[['节点能力覆盖',project.nodeBindings[node.id]?.[capability]],['节点默认',project.nodeBindings[node.id]?.$default],['作品能力覆盖',project.bindings[capability]],['作品默认',project.bindings.$default],['Agent 能力覆盖',state.agentBindings[node.agentRole]?.[capability]],['Agent 默认',state.agentBindings[node.agentRole]?.$default],['全局能力默认',state.globalBindings[capability]],['全局默认',state.globalBindings.$default]]
 for(const [source,id] of candidates){const model=state.models.find(m=>m.id===id&&m.capabilities.includes(capability));if(model)return {model,source}}
 return {model:undefined,source:state.globalBindings.$default?'全局模型不支持此能力，请单独选择':'未配置'}
}
export function progress(project:Project){return Object.values(project.nodes).filter(n=>['COMPLETED','SKIPPED'].includes(n.status)).length}
export function applyCommand(input:WorkspaceState,command:Command,catalog:Catalog):WorkspaceState{
 // 状态来自 Vue 响应式对象，JSON 快照避免 structuredClone 无法复制 Proxy。
 const s=migrateWorkspace(input);const p=command.payload
 const project=()=>{const found=s.projects.find(x=>x.id===p.projectId);if(!found)throw new Error('作品不存在');return found}
 if(visualCommands.has(command.type)){
  const pr=project(),consumers=applyVisualCommand(s,pr,command,catalog)
  for(const id of new Set(consumers)){
   const node=pr.nodes[id];node.visualInputRevision=(node.visualInputRevision??0)+1
   if(node.status==='COMPLETED')node.status='NEEDS_REVALIDATION'
   invalidateNode(pr,id)
  }
  s.version++;return s
 }
 switch(command.type){
 case 'CREATE_PROJECT':s.projects.unshift(makeProject(p,catalog.nodes));break
 case 'SET_VOICE_CAST':{
  const pr=project(),cast=p.cast
  if(!Array.isArray(cast)||cast.length>50)throw new Error('选角列表无效')
  const names=new Set<string>()
  for(const row of cast){if(!row||typeof row.speaker!=='string'||!row.speaker.trim()||row.speaker.length>100||typeof row.roleId!=='string'||!/^[a-z][a-z0-9_]{2,31}$/.test(row.roleId)||typeof row.name!=='string'||!row.name.trim()||row.name.length>100||typeof row.version!=='string'||!row.version.trim()||row.version.length>30||names.has(row.speaker.trim()))throw new Error('选角信息无效或说话人重复');names.add(row.speaker.trim())}
  const next=cast.map(row=>({speaker:row.speaker,roleId:row.roleId,name:row.name,version:row.version}))
  if(JSON.stringify(pr.voiceCast??[])!==JSON.stringify(next)){pr.voiceCast=next;if(pr.nodes.N28.status==='COMPLETED')pr.nodes.N28.status='NEEDS_REVALIDATION';invalidateNode(pr,'N28')}
  break
 }
 case 'UPDATE_PROJECT':{
  const pr=project()
  if(p.title!==undefined){const title=String(p.title).trim();if(!title)throw new Error('请填写作品名称');pr.title=title}
  if(p.brief!==undefined)pr.brief=String(p.brief)
  if(p.budget!==undefined){const budget=Number(p.budget);if(!Number.isFinite(budget)||budget<0||budget>1_000_000)throw new Error('预算无效');pr.budget=budget}
  if(p.platforms!==undefined){const platforms=Array.isArray(p.platforms)?[...p.platforms]:[];if(!platforms.length||platforms.some(x=>!['DOUYIN','XIAOHONGSHU'].includes(x)))throw new Error('平台无效');pr.platforms=platforms}
  pr.updatedAt=new Date().toISOString();break
 }
 case 'SET_PROJECT_STATUS':{
  const pr=project(),status=String(p.status??'')
  if(!['ACTIVE','PAUSED','ABANDONED'].includes(status))throw new Error('项目状态无效')
  pr.status=status as Project['status'];pr.updatedAt=new Date().toISOString();break
 }
 case 'SAVE_NODE':{
  const pr=project(),definition=catalog.nodes.find(n=>n.id===p.nodeId);if(!definition)throw new Error('节点不存在')
  const node=pr.nodes[p.nodeId],complete=p.complete===true,text=String(p.text??'')
  if(complete){
   const reasons=blockingReasons(pr,definition,catalog);if(reasons.length)throw new Error(reasons[0]);if(!text.trim())throw new Error('请先填写或导入本节点产物');validateStructuredFields(definition,text)
   // 本地不伪造服务端的 SHA-256 记录，用已审阅文本判断幂等。
   const review=node.agentDraftReview,alreadyReviewed=node.status==='COMPLETED'&&node.output===text&&review?.reviewedByHuman===true&&review.localReviewedText===text
   if(review&&!alreadyReviewed){
    if(p.agentReview?.runId!==review.runId||p.agentReview?.acknowledged!==true)throw new Error('请先核对专家草稿并完成人工确认')
    if(review.fixture&&(p.agentReview?.fixtureReplaced!==true||(review.fixtureBody?.trim()&&text.includes(review.fixtureBody.trim()))))throw new Error('请替换测试正文并确认填入真实材料')
    review.reviewedByHuman=true;review.reviewedAt=new Date().toISOString();review.localReviewedText=text
   }
  }
  node.draft=String(p.text??'');if(complete&&node.status==='COMPLETED'&&node.output===node.draft)break;if(complete){node.output=node.draft;node.status='COMPLETED';node.revision++;node.dependencies=Object.fromEntries(definition.dependsOn.map(id=>[id,pr.nodes[id].revision]));
   invalidateNode(pr,p.nodeId)
  }else if(node.status==='NOT_STARTED')node.status='DRAFT';node.updatedAt=new Date().toISOString();break
 }
 case 'SKIP_NODE':{const pr=project(),definition=catalog.nodes.find(n=>n.id===p.nodeId);if(!definition)throw new Error('节点不存在');if(!canSkipNode(pr,definition,catalog))throw new Error('该节点不能直接跳过，请提交替代产物');if(!String(p.reason??'').trim())throw new Error('请填写不适用原因');const node=pr.nodes[p.nodeId];node.status='SKIPPED';node.skipReason=p.reason;node.revision++;break}
 case 'APPROVE_GATE':{
  const pr=project(),gate=catalog.gates.find(g=>g.id===p.gateId);if(!gate)throw new Error('确认节点不存在');if(!projectActive(pr))throw new Error('项目当前不是进行中，恢复或重新开始后才能拍板')
  const platform=String(p.platform??'')
  if(gate.scope==='PLATFORM'&&(!platform||!pr.platforms.includes(platform)))throw new Error('平台拍板必须指定当前作品的平台')
  if(gate.after.some(id=>pr.nodes[id]?.status!=='COMPLETED'))throw new Error('请先完成对应阶段的审阅材料')
  if(gate.watches.some(id=>pr.nodes[id].status==='COMPLETED'&&pr.nodes[id].draft!==pr.nodes[id].output))throw new Error('审阅材料含未采用草稿，请先标记完成或恢复当前产物')
  const value=fingerprint(pr,gate,platform||undefined);if(p.fingerprint!==value)throw new Error('内容版本已变化，请刷新后重新审阅')
  pr.approvals[approvalKey(gate.id,platform||undefined)]={id:gate.id,gateId:gate.id,platform:platform||undefined,scope:gate.scope,fingerprint:value,decision:'APPROVED',at:new Date().toISOString()};break
 }
 case 'SAVE_MODEL':{const m=p.model as Model;if(!m.name?.trim()||!m.remoteModelId?.trim())throw new Error('请填写显示名称和真实模型 ID');const u=new URL(m.baseUrl);if(!['https:','http:'].includes(u.protocol)||u.username||u.password||u.search||u.hash)throw new Error('模型地址须为不含凭据、查询参数或片段的 HTTP(S) 地址');validateModelParameters(m.parameters);if(!m.capabilities.length)throw new Error('至少选择一种模型能力');if(!/^[A-Z][A-Z0-9_]*$/.test(m.credentialRef))throw new Error('认证引用须为环境变量名称，不要输入密钥');m.verified=false;m.enabled=false;const at=s.models.findIndex(x=>x.id===m.id);if(at<0)s.models.push(m);else s.models[at]=m;break}
 case 'DELETE_MODEL':{s.models=s.models.filter(m=>m.id!==p.id);for(const map of [s.globalBindings,...Object.values(s.agentBindings),...s.projects.flatMap(pr=>[pr.bindings,...Object.values(pr.nodeBindings)])])for(const key of Object.keys(map))if(map[key]===p.id)delete map[key];break}
 case 'SET_BINDING':{if(p.modelId&&!s.models.some(m=>m.id===p.modelId&&m.capabilities.includes(p.capability)))throw new Error('所选模型不支持该能力');let target:Record<string,string>;if(p.scope==='GLOBAL')target=s.globalBindings;else if(p.scope==='AGENT')target=s.agentBindings[p.agentId]??= {};else {const pr=project();target=p.scope==='NODE'?(pr.nodeBindings[p.nodeId]??={}):pr.bindings}if(p.modelId)target[p.capability]=p.modelId;else delete target[p.capability];break}
 case 'SET_DEFAULT_MODEL':{
  if(p.modelId&&!s.models.some(m=>m.id===p.modelId))throw new Error('所选模型不存在')
  let target:Record<string,string>
  switch(p.scope){
   case 'GLOBAL':target=s.globalBindings;break
   case 'AGENT':if(!catalog.agents.some(a=>a.id===p.agentId))throw new Error('角色不存在');target=s.agentBindings[p.agentId]??={};break
   case 'PROJECT':target=project().bindings;break
   case 'NODE':if(!catalog.nodes.some(n=>n.id===p.nodeId))throw new Error('节点不存在');target=project().nodeBindings[p.nodeId]??={};break
   default:throw new Error('模型配置范围无效')
  }
  if(p.modelId)target.$default=p.modelId;else delete target.$default;break
 }
 case 'DELETE_TASK':case 'RESTORE_TASK':{
  const task=s.tasks.find(t=>t.id===p.id);if(!task)throw new Error('任务不存在')
  if(command.type==='DELETE_TASK')task.deletedAt??=new Date().toISOString();else delete task.deletedAt
  break
 }
 case 'ADD_IDEA':if(!String(p.text??'').trim())throw new Error('先写下你的想法');s.ideas.unshift({id:p.id??uid('idea'),text:p.text.trim(),createdAt:new Date().toISOString()});break
 case 'SAVE_PROFILE':s.profile=p.profile;break
 case 'ADD_ASSET':s.assets.unshift(p.asset);break
 case 'ADD_LEDGER':if(!String(p.label??'').trim()||!Number.isFinite(Number(p.amount))||Number(p.amount)<0)throw new Error('请输入有效名称和金额');s.ledger.unshift({id:uid('entry'),label:p.label,amount:Number(p.amount),kind:p.kind,createdAt:new Date().toISOString()});break
 case 'PLAN_PROJECT':{const pr=project(),next=catalog.nodes.find(n=>!['COMPLETED','SKIPPED'].includes(pr.nodes[n.id].status)&&!blockingReasons(pr,n,catalog).length);const waiting=catalog.gates.find(g=>!validApproval(pr,g)&&g.after.every(id=>pr.nodes[id].status==='COMPLETED'));
  s.tasks.unshift({id:uid('task'),projectId:pr.id,nodeId:next?.id,title:p.execute?'自动推进检查':'制作计划检查',status:p.execute?'BLOCKED':'COMPLETED',detail:waiting?`下一步需要人工拍板：${waiting.name}。`:next?`${next.id} ${next.name} 已具备业务前提。${p.execute?'当前版本尚未接入自动执行器，请手工提交产物；没有调用模型或产生费用。':'可继续填写产物或配置该节点模型。'}`:'当前没有可自动推进的节点，请检查待审阅或依赖。',createdAt:new Date().toISOString()});break}
 default:throw new Error('不支持的操作')
 }
 s.version++;return s
}

/** 按既有实际依赖传播失效，不把未引用的节点一起重置。 */
export function invalidateNode(project:Project,nodeId:string){
 const changed=new Set([nodeId]);let again=true
 while(again){again=false;for(const [id,node] of Object.entries(project.nodes)){
  if(!changed.has(id)&&node.status==='COMPLETED'&&Object.keys(node.dependencies).some(key=>changed.has(key))){node.status='NEEDS_REVALIDATION';changed.add(id);again=true}
 }}
}
