import type {Catalog,Project,WorkspaceState,Command} from './domain.ts'
import {assertNoCredentials} from './model-parameters.ts'

export type MediaKind='IMAGE'|'VIDEO'
export interface VisualNeed {id:string;title:string;description:string;productionNodeId?:'N27'|'N29';shotId?:string;legacyBinding?:Record<string,unknown>;desiredStartMs?:number;desiredEndMs?:number;revision:number;createdAt:string;legacySelectedCandidateId?:string}
export interface VisualBatch {id:string;needId:string;mediaKind:MediaKind;prompt:string;modelSnapshot:Record<string,string>;parameters:Record<string,unknown>;budgetCents:number;sourceBatchId?:string;references?:{candidateId:string;fileRef:string;sha256:string;role:string}[];createdAt:string}
export interface VisualCandidate {id:string;needId:string;batchId:string;assetId:string;fileRef:string;sha256:string;mediaKind:MediaKind;durationMs?:number;seed:string;costCents:number;note:string;status:'PENDING'|'KEPT'|'REJECTED';createdAt:string}
export interface VisualPlacement {id:string;needId:string;candidateId:string;purpose:'TIMELINE'|'REFERENCE';referenceRole?:string;trackId?:string;targetStartMs?:number;targetEndMs?:number;sourceInMs?:number;sourceOutMs?:number;sourceDurationMs?:number;reason:string;active:boolean;createdAt:string;replacesId?:string;supersededBy?:string;removedAt?:string;removeReason?:string}
export interface VisualWorkbench {schemaVersion:3;revision:number;needs:VisualNeed[];batches:VisualBatch[];candidates:VisualCandidate[];placements:VisualPlacement[];uses:{nodeId:string;placementIds:string[]}[];legacyAdoptions:Record<string,any>[]}
export const emptyVisualWorkbench=():VisualWorkbench=>({schemaVersion:3,revision:0,needs:[],batches:[],candidates:[],placements:[],uses:[],legacyAdoptions:[]})
export const visualCommands=new Set(['CREATE_VISUAL_NEED','UPDATE_VISUAL_NEED','REMOVE_EMPTY_VISUAL_NEED','CREATE_VISUAL_BATCH','IMPORT_VISUAL_CANDIDATE','SET_VISUAL_CANDIDATE_STATUS','ADOPT_VISUAL_CANDIDATE','REMOVE_VISUAL_PLACEMENT','USE_VISUAL_PLAN'])
export const imageTypes=new Set(['image/png','image/jpeg','image/webp'])
export function mediaKind(type:string):MediaKind|undefined{return imageTypes.has(type)?'IMAGE':['video/mp4','video/webm'].includes(type)?'VIDEO':undefined}
const clone=<T>(value:T):T=>JSON.parse(JSON.stringify(value))
const text=(value:unknown,label:string,max:number,required=false)=>{if(value!==undefined&&typeof value!=='string')throw new Error(label+'格式无效');const s=String(value??'').trim();if(s.length>max||(required&&!s))throw new Error(label+'为空或过长');return s}
const integer=(value:unknown,label:string,max=86400000)=>{if(typeof value!=='number'||!Number.isSafeInteger(value)||value<0||value>max)throw new Error(label+'须为有效的非负整数');return value}
const id=(value:unknown)=>{const s=text(value,'编号',100,true);if(!/^[A-Za-z0-9_-]+$/.test(s))throw new Error('编号格式无效');return s}
function range(start:unknown,end:unknown,label:string){const a=integer(start,label+'起点'),b=integer(end,label+'终点');if(b<=a)throw new Error(label+'终点必须晚于起点');return [a,b] as const}
function find<T extends {id:string}>(items:T[],value:unknown,label:string){const item=items.find(x=>x.id===value);if(!item)throw new Error(label+'不存在');return item}
function insert<T extends {id:string}>(items:T[],item:T,limit:number){if(items.some(x=>x.id===item.id))throw new Error('编号已存在');if(items.length>=limit)throw new Error('当前记录数量已达上限');items.push(item)}
export const productionNodes=['N27','N29'] as const
export function productionOwner(value:unknown):'N27'|'N29'{if(value!=='N27'&&value!=='N29')throw new Error('画面需求只能归属主体内容 N27 或辅助画面 N29');return value}
/** 历史绑定仅归档；不猜测其他业务节点对应哪种视频制作任务。 */
export function migrateVisualWorkbench(project:Project):boolean {
 let changed=false
 if(!project.visualWorkbench&&project.videoWorkbench){
  const old=project.videoWorkbench,w=emptyVisualWorkbench()
  w.needs=(old.shots??[]).map((x:any)=>({id:x.id,title:x.title,description:'',...(productionNodes.includes(x.nodeId)?{productionNodeId:x.nodeId}:{}),legacyBinding:{sourceNodeId:x.nodeId,consumerNodeIds:[]},revision:x.selectionRevision??0,createdAt:x.createdAt,legacySelectedCandidateId:x.selectedCandidateId}))
  w.batches=(old.batches??[]).map((x:any)=>({...clone(x),needId:x.shotId,mediaKind:'VIDEO'}))
  w.candidates=(old.candidates??[]).map((x:any)=>({...clone(x),needId:x.shotId,mediaKind:'VIDEO'}))
  w.legacyAdoptions=clone(old.adoptions??[]);project.visualWorkbench=w;changed=true
 }
 const w=project.visualWorkbench
 if(w&&(w as any).schemaVersion!==3){
  for(const n of w.needs){const old=n as any;n.legacyBinding={sourceNodeId:old.sourceNodeId??'',consumerNodeIds:clone(old.consumerNodeIds??[])};if(productionNodes.includes(old.sourceNodeId))n.productionNodeId=old.sourceNodeId;delete old.sourceNodeId;delete old.consumerNodeIds}
  w.schemaVersion=3;w.uses=[];changed=true
 }
 return changed
}
/** 仅返回需复查的实际使用节点；不改写节点产物，不自动完成节点。 */
export function applyVisualCommand(state:WorkspaceState,project:Project,command:Command,catalog:Catalog):string[]{
 migrateVisualWorkbench(project)
 const w=project.visualWorkbench??=emptyVisualWorkbench(),p=command.payload,at=new Date().toISOString()
 const changed=(need:VisualNeed)=>{need.revision++;w.revision++;return [...new Set([...(need.productionNodeId?[need.productionNodeId]:[]),...w.uses.filter(u=>u.placementIds.some(id=>w.placements.some(x=>x.id===id&&x.needId===need.id))).map(u=>u.nodeId)])]}
 if(command.type==='USE_VISUAL_PLAN'){
  const nodeId=String(p.nodeId);if(!['N31','N32'].includes(nodeId))throw new Error('采用方案只能交给粗剪或精剪')
  if(!Array.isArray(p.placementIds)||!p.placementIds.length||p.placementIds.length>2000)throw new Error('请选择实际使用的成片画面')
  const ids=[...new Set<string>(p.placementIds)];for(const id of ids){const x=find(w.placements,id,'采用记录');if(!x.active||x.purpose!=='TIMELINE')throw new Error('只能交接有效成片画面');productionOwner(find(w.needs,x.needId,'需求').productionNodeId)}
  w.uses=w.uses.filter(u=>u.nodeId!==nodeId);w.uses.push({nodeId,placementIds:ids});return [nodeId]
 }
 if(command.type==='CREATE_VISUAL_NEED'||command.type==='UPDATE_VISUAL_NEED'){
  if(p.sourceNodeId!==undefined||p.consumerNodeIds!==undefined)throw new Error('请使用制作任务归属，不再接受任意节点绑定');const productionNodeId=productionOwner(p.productionNodeId),shotId=text(p.shotId,'分镜编号',100)
  const value={title:text(p.title,'画面需求名称',120,true),description:text(p.description,'画面描述',10000),productionNodeId,...(shotId?{shotId}:{}),...(p.desiredStartMs!==undefined||p.desiredEndMs!==undefined?(()=>{const [desiredStartMs,desiredEndMs]=range(p.desiredStartMs,p.desiredEndMs,'目标范围');return {desiredStartMs,desiredEndMs}})():{})}
  if(command.type==='CREATE_VISUAL_NEED'){insert(w.needs,{...value,id:id(p.id),revision:0,createdAt:at},300);return []}
  const need=find(w.needs,p.needId,'画面需求');if(need.productionNodeId&&need.productionNodeId!==productionNodeId&&w.placements.some(x=>x.active&&x.needId===need.id))throw new Error('已有采用时不能更换归属，请先撤销采用')
  if(w.placements.some(x=>x.active&&x.needId===need.id&&x.purpose==='TIMELINE'&&value.desiredStartMs!==undefined&&(x.targetStartMs!<value.desiredStartMs||x.targetEndMs!>value.desiredEndMs!)))throw new Error('新目标范围不能排除已有采用，请先调整采用区间')
  delete need.shotId;delete need.desiredStartMs;delete need.desiredEndMs;Object.assign(need,value)
  const used=w.placements.some(x=>x.active&&x.needId===need.id),current=changed(need)
  return used?current:[]
 }
 if(command.type==='REMOVE_EMPTY_VISUAL_NEED'){
  const need=find(w.needs,p.needId,'画面需求');if(w.batches.some(b=>b.needId===need.id)||w.placements.some(x=>x.needId===need.id))throw new Error('已有批次或采用历史的需求不能删除');w.needs=w.needs.filter(n=>n.id!==need.id);return []
 }
 if(command.type==='CREATE_VISUAL_BATCH'){
  const need=find(w.needs,p.needId,'画面需求');productionOwner(need.productionNodeId);const kind=p.mediaKind as MediaKind;if(!['IMAGE','VIDEO'].includes(kind))throw new Error('候选类型无效')
  const parameters=clone(p.parameters??{});assertNoCredentials(parameters);if(JSON.stringify(parameters).length>20000)throw new Error('参数过长')
  let modelSnapshot:Record<string,string>
  if(p.modelId){const m=find(state.models,p.modelId,'模型');if(!m.capabilities.includes(kind==='IMAGE'?'IMAGE_GENERATION':'VIDEO_GENERATION'))throw new Error('模型不支持此候选类型');modelSnapshot={id:m.id,name:m.name,provider:m.provider??'',remoteModelId:m.remoteModelId,protocol:m.protocol}}
  else modelSnapshot={name:text(p.externalModel,'外部模型名称与版本',200,true),provider:'MANUAL_IMPORT'}
  if(p.sourceBatchId&&find(w.batches,p.sourceBatchId,'来源批次').needId!==need.id)throw new Error('来源批次不属于当前需求')
  const references=(p.references??[]) as {candidateId:string;role:string}[];if(!Array.isArray(references)||references.length>8)throw new Error('参考图最多8张');const frozen=references.map(ref=>{const c=find(w.candidates,ref.candidateId,'参考候选');if(c.mediaKind!=='IMAGE'||c.status==='REJECTED')throw new Error('请选择未淘汰的图片参考');if(!['FIRST_FRAME','LAST_FRAME','CHARACTER','STYLE','GENERAL'].includes(ref.role))throw new Error('参考用途无效');return {candidateId:c.id,fileRef:c.fileRef,sha256:c.sha256,role:ref.role}})
  insert(w.batches,{references:frozen,id:id(p.id),needId:need.id,mediaKind:kind,prompt:text(p.prompt,'提示词',10000,true),modelSnapshot,parameters,budgetCents:integer(p.budgetCents,'费用上限',100000000),...(p.sourceBatchId?{sourceBatchId:p.sourceBatchId}:{}),createdAt:at},600);return []
 }
 if(command.type==='IMPORT_VISUAL_CANDIDATE'){
  const batch=find(w.batches,p.batchId,'批次'),asset=find(state.assets,p.assetId,'素材'),kind=mediaKind(asset.type)
  productionOwner(find(w.needs,batch.needId,'画面需求').productionNodeId)
  if(asset.projectId!==project.id||!kind||kind!==batch.mediaKind)throw new Error('请选择本作品且与批次类型一致的图片或视频')
  if(!asset.sha256||!/^[a-f0-9]{64}$/.test(asset.sha256))throw new Error('素材缺少校验值，请重新上传')
  if(w.candidates.some(c=>c.batchId===batch.id&&c.assetId===asset.id))throw new Error('素材已登记到此批次')
  const costCents=integer(p.costCents,'费用',100000000);if(w.candidates.filter(c=>c.batchId===batch.id).reduce((sum,c)=>sum+c.costCents,0)+costCents>batch.budgetCents)throw new Error('登记费用超过批次预算')
  const durationMs=p.durationMs===undefined?undefined:integer(p.durationMs,'素材时长');if(durationMs===0)throw new Error('素材时长必须大于零')
  insert(w.candidates,{id:id(p.id),needId:batch.needId,batchId:batch.id,assetId:asset.id,fileRef:asset.fileRef,sha256:asset.sha256,mediaKind:kind,...(durationMs?{durationMs}:{}),seed:text(p.seed,'seed',100),costCents,note:text(p.note,'备注',2000),status:'PENDING',createdAt:at},2000);return []
 }
 if(command.type==='REMOVE_VISUAL_PLACEMENT'){
  const placement=find(w.placements,p.placementId,'采用记录');if(!placement.active)return []
  placement.removeReason=text(p.reason,'撤销原因',2000,true);placement.removedAt=at;placement.active=false;return changed(find(w.needs,placement.needId,'画面需求'))
 }
 const candidate=find(w.candidates,p.candidateId,'候选'),need=find(w.needs,candidate.needId,'画面需求')
 if(command.type==='SET_VISUAL_CANDIDATE_STATUS'){
  if(!['PENDING','KEPT','REJECTED'].includes(p.status))throw new Error('候选状态无效')
  if(p.status==='REJECTED'&&w.placements.some(x=>x.active&&x.candidateId===candidate.id))throw new Error('正在使用的候选不能淘汰，请先撤销或替换采用')
  candidate.status=p.status;return []
 }
 if(command.type!=='ADOPT_VISUAL_CANDIDATE')throw new Error('不支持的画面操作')
 productionOwner(need.productionNodeId)
 if(candidate.status==='REJECTED')throw new Error('请先恢复已淘汰候选')
 const purpose=p.purpose;if(!['TIMELINE','REFERENCE'].includes(purpose))throw new Error('请指定采用用途和片段范围')
 const value:Omit<VisualPlacement,'createdAt'|'active'>={id:id(p.id),needId:need.id,candidateId:candidate.id,purpose,reason:text(p.reason,'采用原因',2000,true)}
 if(candidate.mediaKind==='VIDEO'){
  const [sourceInMs,sourceOutMs]=range(p.sourceInMs,p.sourceOutMs,'素材范围'),sourceDurationMs=candidate.durationMs??integer(p.sourceDurationMs,'素材时长')
  if(sourceOutMs>sourceDurationMs)throw new Error('素材出点超过素材时长')
  Object.assign(value,{sourceInMs,sourceOutMs,sourceDurationMs})
 }
 if(purpose==='TIMELINE'){
  const [targetStartMs,targetEndMs]=range(p.targetStartMs,p.targetEndMs,'成片范围');if(need.desiredStartMs!==undefined&&(targetStartMs<need.desiredStartMs||targetEndMs>need.desiredEndMs!))throw new Error('采用位置超出此需求的目标范围')
  if(candidate.mediaKind==='VIDEO'&&targetEndMs-targetStartMs!==value.sourceOutMs!-value.sourceInMs!)throw new Error('原速采用时，成片时长须与素材片段时长一致')
  Object.assign(value,{targetStartMs,targetEndMs,trackId:id(p.trackId??'V1')})
 }else{
  const referenceRole=p.referenceRole??'GENERAL';if(!['GENERAL','FIRST_FRAME','LAST_FRAME','CHARACTER','STYLE'].includes(referenceRole))throw new Error('参考用途无效');value.referenceRole=referenceRole
 }
 let replaced:VisualPlacement|undefined
 if(p.replacesId){replaced=find(w.placements,p.replacesId,'被替换记录');value.replacesId=replaced.id}
 const existing=w.placements.find(x=>x.id===value.id)
 if(existing){if(!existing.active||Object.entries(value).some(([key,v])=>existing![key as keyof VisualPlacement]!==v))throw new Error('采用编号已用于其他决定');return []}
 if(replaced&&(!replaced.active||replaced.needId!==need.id))throw new Error('只能替换此需求下仍在使用的采用记录')
 if(purpose==='TIMELINE'&&w.placements.some(x=>x.active&&x.id!==replaced?.id&&x.purpose==='TIMELINE'&&x.trackId===value.trackId&&x.targetStartMs!<value.targetEndMs!&&value.targetStartMs!<x.targetEndMs!))throw new Error('同一画面轨道已有重叠采用，请替换现有记录或调整范围')
 insert(w.placements,{...value,active:true,createdAt:at},2000)
 if(replaced){replaced.active=false;replaced.supersededBy=value.id}
 candidate.status='KEPT';return changed(need)
}

export function visualInputs(project:Project,nodeId:string){const w=project.visualWorkbench;if(!w)return undefined;const use=w.uses.find(u=>u.nodeId===nodeId);const placements=w.placements.filter(p=>use?.placementIds.includes(p.id));const needs=w.needs.filter(n=>n.productionNodeId===nodeId||placements.some(p=>p.needId===n.id));if(!needs.length)return undefined;return {needs,placements:use?placements:w.placements.filter(p=>p.active&&needs.some(n=>n.id===p.needId))}}
