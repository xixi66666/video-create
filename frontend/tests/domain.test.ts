import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {initialState,makeProject,applyCommand,resolveModel,fingerprint,validApproval,blockingReasons,canSkipNode,projectActive,validateStructuredFields,type Catalog,type Model} from '../src/lib/domain.ts'
const catalog=JSON.parse(fs.readFileSync(new URL('../src/data/catalog.json',import.meta.url),'utf8')) as Catalog
test('目录保留全部 49 个活动节点、19 职责与 6 个拍板',()=>{assert.equal(catalog.nodes.length,49);assert.equal(catalog.agents.length,19);assert.equal(catalog.gates.length,6);assert.equal(new Set(catalog.nodes.map(n=>n.id)).size,49)})
test('未立项不能越过 G02 完成选题卡',()=>{const s=initialState(catalog),p=s.projects[0];assert.throws(()=>applyCommand(s,{type:'SAVE_NODE',payload:{projectId:p.id,nodeId:'N15',text:'试图越过立项',complete:true}},catalog),/选题立项/);assert.ok(blockingReasons(p,catalog.nodes.find(n=>n.id=='N15')!,catalog).some(s=>s.includes('G02')))})
test('模型按节点、项目、角色、全局顺序继承，清除覆盖可回退',()=>{const s=initialState(catalog),p=s.projects[0],n=catalog.nodes.find(n=>n.id=='N22')!;const cap='TEXT_REASONING';s.models=['global','agent','project','node'].map(id=>({id,name:id,capabilities:[cap]} as Model));s.globalBindings[cap]='global';s.agentBindings[n.agentRole]={[cap]:'agent'};p.bindings[cap]='project';p.nodeBindings[n.id]={[cap]:'node'};assert.equal(resolveModel(s,p,n,cap).model?.id,'node');delete p.nodeBindings[n.id][cap];assert.equal(resolveModel(s,p,n,cap).model?.id,'project');delete p.bindings[cap];assert.equal(resolveModel(s,p,n,cap).model?.id,'agent')})
test('修改旁白只标记实际引用的下游，原成片确认失效',()=>{const s=initialState(catalog),p=s.projects[0];for(const n of Object.values(p.nodes)){n.status='COMPLETED';n.revision=1}p.nodes.N33.dependencies={N28:1};p.nodes.N37.dependencies={N33:1};p.nodes.N29.dependencies={N27:1};const g3=catalog.gates[2],g4=catalog.gates[3];p.approvals.G03={id:'G03',decision:'APPROVED',fingerprint:fingerprint(p,g3),at:''};p.approvals.G04={id:'G04',decision:'APPROVED',fingerprint:fingerprint(p,g4),at:''};const next=applyCommand(s,{type:'SAVE_NODE',payload:{projectId:p.id,nodeId:'N28',text:'修改后的旁白',complete:true}},catalog);const result=next.projects[0];assert.equal(result.nodes.N33.status,'NEEDS_REVALIDATION');assert.equal(result.nodes.N37.status,'NEEDS_REVALIDATION');assert.equal(result.nodes.N29.status,'COMPLETED');assert.equal(validApproval(result,g4),false);assert.equal(p.nodes.N33.status,'COMPLETED')})
test('未接入执行器时自动推进明确阻塞，不伪造生成产物',()=>{const s=initialState(catalog),p=s.projects[0];const next=applyCommand(s,{type:'PLAN_PROJECT',payload:{projectId:p.id,execute:true}},catalog);assert.equal(next.tasks[0].status,'BLOCKED');assert.equal(next.projects[0].nodes.N23.status,p.nodes.N23.status)})
test('不适用仅允许条件节点且必须填写原因',()=>{const s=initialState(catalog),p=s.projects[0];assert.throws(()=>applyCommand(s,{type:'SKIP_NODE',payload:{projectId:p.id,nodeId:'N43',reason:'跳过'}},catalog),/不能直接跳过/);assert.throws(()=>applyCommand(s,{type:'SKIP_NODE',payload:{projectId:p.id,nodeId:'N25',reason:''}},catalog),/填写/)})
test('新作品不包含示例进度或历史确认',()=>{const p=makeProject({title:'真实作品',id:'real'},catalog.nodes);assert.equal(p.sample,false);assert.equal(Object.keys(p.nodes).length,49);assert.ok(Object.values(p.nodes).every(n=>n.status==='NOT_STARTED'));assert.deepEqual(p.approvals,{})})
test('含未采用草稿的材料不能被误批准',()=>{const s=initialState(catalog),p=s.projects[0],g=catalog.gates[0];p.nodes.N02.draft='未采用的新目标';assert.throws(()=>applyCommand(s,{type:'APPROVE_GATE',payload:{projectId:p.id,gateId:g.id,fingerprint:fingerprint(p,g)}},catalog),/未采用草稿/)})
test('配置参数不接受认证密钥或带凭据的地址',()=>{const s=initialState(catalog);const model={id:'safe-id',name:'test',remoteModelId:'test',provider:'test',protocol:'CUSTOM_HTTP',baseUrl:'https://example.invalid',credentialRef:'CREATOR_TEST_KEY',capabilities:['TEXT_REASONING'],parameters:{apiKey:'EXAMPLE_ONLY'},enabled:false,verified:false};assert.throws(()=>applyCommand(s,{type:'SAVE_MODEL',payload:{model}},catalog),/不能保存密钥/);model.parameters={};model.baseUrl='https://example.invalid?key=EXAMPLE_ONLY';assert.throws(()=>applyCommand(s,{type:'SAVE_MODEL',payload:{model}},catalog),/凭据/)})
test('模板 overrides 决定哪些节点可以跳过',()=>{
 const real=makeProject({title:'真实口播',template:'REAL_PERSON'},catalog.nodes),screen=makeProject({title:'录屏',template:'SCREENCAST'},catalog.nodes),ai=makeProject({title:'AI 故事',template:'AI_STORY'},catalog.nodes)
 const node=(id:string)=>catalog.nodes.find(n=>n.id===id)!
 assert.equal(canSkipNode(real,node('N25'),catalog),false);assert.equal(canSkipNode(real,node('N26'),catalog),true)
 assert.equal(canSkipNode(screen,node('N25'),catalog),true);assert.equal(canSkipNode(screen,node('N26'),catalog),false)
 assert.equal(canSkipNode(ai,node('N25'),catalog),true);assert.equal(canSkipNode(ai,node('N26'),catalog),true)
 const s=initialState(catalog),p=s.projects[0];p.template='REAL_PERSON'
 assert.throws(()=>applyCommand(s,{type:'SKIP_NODE',payload:{projectId:p.id,nodeId:'N25',reason:'不想拍'}},catalog),/不能直接跳过/)
})
test('暂停项目阻塞完成、拍板和 Agent 前提检查',()=>{
 const s=initialState(catalog),p=s.projects[0]
 const paused=applyCommand(s,{type:'SET_PROJECT_STATUS',payload:{projectId:p.id,status:'PAUSED'}},catalog),pp=paused.projects[0]
 assert.equal(projectActive(pp),false);assert.ok(blockingReasons(pp,catalog.nodes.find(n=>n.id==='N02')!,catalog).some(x=>x.includes('不是进行中')))
 assert.throws(()=>applyCommand(paused,{type:'SAVE_NODE',payload:{projectId:p.id,nodeId:'N02',text:'新产物',complete:true}},catalog),/不是进行中/)
 assert.throws(()=>applyCommand(paused,{type:'APPROVE_GATE',payload:{projectId:p.id,gateId:'G01',fingerprint:fingerprint(pp,catalog.gates[0])}},catalog),/不是进行中/)
})
test('平台拍板逐平台记录，全部平台完成前不放行',()=>{
 let s=initialState(catalog),p=s.projects[0];for(let i=31;i<=41;i++){p.nodes['N'+i]={...p.nodes['N'+i],status:'COMPLETED',revision:1,draft:'x',output:'x'}}
 const gate=catalog.gates.find(g=>g.id==='G04')!
 const approve=(platform:string)=>{s=applyCommand(s,{type:'APPROVE_GATE',payload:{projectId:p.id,gateId:gate.id,platform,fingerprint:fingerprint(s.projects[0],gate,platform)}},catalog);return s.projects[0]}
 p=approve('DOUYIN');assert.equal(validApproval(p,gate,'DOUYIN'),true);assert.equal(validApproval(p,gate),false)
 p=approve('XIAOHONGSHU');assert.equal(validApproval(p,gate),true)
})
test('结构化 JSON 产物检查必填字段，自由文本仍可手工交付',()=>{
 const n=catalog.nodes.find(n=>n.id==='N22')!
 assert.throws(()=>validateStructuredFields(n,'{"segments":[]}'),/必填字段/)
 assert.doesNotThrow(()=>validateStructuredFields(n,'这是普通手工文本'))
})

test('本地专家草稿需要确认，测试正文未替换不能完成，新内容需重新确认',()=>{
 const s=initialState(catalog),p=s.projects[0],node=p.nodes.N08
 node.status='DRAFT';node.draft='【测试正文】';node.agentDraftReview={runId:'run_fixture',fixture:true,fixtureBody:'【测试正文】',uncertainties:['证据待核实']}
 const complete=(state:typeof s,text:string,agentReview?:Record<string,unknown>)=>applyCommand(state,{type:'SAVE_NODE',payload:{projectId:p.id,nodeId:'N08',text,complete:true,agentReview}},catalog)
 const review={runId:'run_fixture',acknowledged:true,fixtureReplaced:true}
 assert.throws(()=>complete(s,'真实材料'),/人工确认/)
 assert.throws(()=>complete(s,'真实材料',{...review,runId:'run_other'}),/人工确认/)
 assert.throws(()=>complete(s,'【测试正文】',review),/替换测试正文/)
 const reviewed=complete(s,'真实材料',review),result=reviewed.projects[0].nodes.N08
 assert.equal(result.status,'COMPLETED');assert.equal(result.agentDraftReview?.reviewedByHuman,true);assert.equal(result.agentDraftReview?.localReviewedText,'真实材料')
 assert.doesNotThrow(()=>complete(reviewed,'真实材料'))
 assert.throws(()=>complete(reviewed,'修改后的真实材料'),/人工确认/)
 result.agentDraftReview!.reviewedByHuman=false
 assert.throws(()=>complete(reviewed,'真实材料'),/人工确认/)
})
