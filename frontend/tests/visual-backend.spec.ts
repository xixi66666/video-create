import {test,expect} from '@playwright/test'
import {api,useIsolatedBackend} from './support/isolated-backend'
import fs from 'node:fs'
useIsolatedBackend()
test('服务端按毫秒采用、图片参考、原件范围播放与版本冲突',async({request,page})=>{
 const projectId='visual_browser_'+Date.now();let state=(await(await request.get(api+'/api/v1/workspace')).json()).data
 async function command(type:string,payload:Record<string,unknown>){const r=await request.post(api+'/api/v1/commands',{data:{type,payload:{projectId,...payload},expectedVersion:state.version}});expect(r.ok(),await r.text()).toBe(true);state=(await r.json()).data}
 await command('CREATE_PROJECT',{id:projectId,title:'任意画面范围隔离验收'});await command('SAVE_NODE',{nodeId:'N08',text:'原想法',complete:true});await command('SAVE_NODE',{nodeId:'N09',text:'原来源',complete:true});await command('CREATE_VISUAL_NEED',{id:'need',title:'第12秒画面',productionNodeId:'N27'});await command('CREATE_VISUAL_BATCH',{id:'batch',needId:'need',mediaKind:'VIDEO',prompt:'自然表情',externalModel:'fixture',budgetCents:0})
 const bytes=fs.readFileSync(new URL('./fixtures/blue.webm',import.meta.url));const file=(await(await request.post(api+'/api/v1/files',{multipart:{file:{name:'clip.webm',mimeType:'video/webm',buffer:bytes}}})).json()).data;await command('ADD_ASSET',{asset:{id:'asset',projectId,name:'clip.webm',type:'video/webm',size:bytes.length,fileRef:file.fileRef,sha256:file.sha256,createdAt:'',source:'fixture'}});await command('IMPORT_VISUAL_CANDIDATE',{id:'candidate',batchId:'batch',assetId:'asset',durationMs:600,costCents:0})
 const decision={id:'placement',candidateId:'candidate',purpose:'TIMELINE',sourceInMs:100,sourceOutMs:300,targetStartMs:12340,targetEndMs:12540,reason:'取其中200毫秒'};await command('ADOPT_VISUAL_CANDIDATE',decision);await command('ADOPT_VISUAL_CANDIDATE',decision);const p=state.projects.find((p:any)=>p.id===projectId);expect(p.visualWorkbench.placements).toHaveLength(1);expect(p.nodes.N08.output).toBe('原想法');expect(p.nodes.N08.status).toBe('COMPLETED');expect(p.nodes.N09.status).toBe('COMPLETED');expect(p.nodes.N29.status).toBe('NOT_STARTED')
 const range=await request.get(api+file.fileRef,{headers:{Range:'bytes=0-15'}});expect(range.status()).toBe(206);expect((await range.body()).length).toBe(16)
 await page.goto('/candidates?projectId='+projectId);await expect(page.locator('.placement-row')).toHaveCount(1);await expect(page.locator('.placement-row')).toContainText('12.34–12.54 秒');await page.locator('.video-candidate video').evaluate(async element=>{const v=element as HTMLVideoElement;v.muted=true;await v.play()});await expect.poll(()=>page.locator('.video-candidate video').evaluate(v=>(v as HTMLVideoElement).currentTime)).toBeGreaterThan(0);await page.reload();await expect(page.locator('.placement-row')).toHaveCount(1)
 const conflict=await request.post(api+'/api/v1/commands',{data:{type:'REMOVE_VISUAL_PLACEMENT',payload:{projectId,placementId:'placement',reason:'x'},expectedVersion:state.version-1}});expect(conflict.status()).toBe(409)
})

test('未配置执行端明确关闭，任意业务节点不能新建抽卡需求',async({request})=>{
 const readiness=await request.get(api+'/api/v1/visual-jobs/readiness');expect(readiness.ok()).toBe(true);expect((await readiness.json()).data.online).toBe(false)
 let state=(await(await request.get(api+'/api/v1/workspace')).json()).data;const projectId='production_boundary_'+Date.now();const created=await request.post(api+'/api/v1/commands',{data:{type:'CREATE_PROJECT',payload:{id:projectId,title:'制作边界隔离验收'},expectedVersion:state.version}});expect(created.ok()).toBe(true);state=(await created.json()).data
 const rejected=await request.post(api+'/api/v1/commands',{data:{type:'CREATE_VISUAL_NEED',payload:{projectId,id:'wrong',title:'不能绑定选题',productionNodeId:'N08'},expectedVersion:state.version}});expect(rejected.status()).toBe(400)
 const list=await request.get(api+'/api/v1/visual-jobs?projectId='+projectId);expect((await list.json()).data).toEqual([])
})
