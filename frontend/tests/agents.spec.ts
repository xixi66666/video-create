import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import {api,useIsolatedBackend} from './support/isolated-backend'
useIsolatedBackend()

test('真实框架协作、返工、采纳为草稿、删除与恢复',async({page,request})=>{
 const ready=await(await request.get(api+'/api/v1/agent-runs/readiness')).json();expect(ready.data.online).toBe(true);expect(ready.data.liveModelsEnabled).toBe(false);expect(ready.data.profiles).toHaveLength(19)
 let state=(await(await request.get(api+'/api/v1/workspace')).json()).data
 const projectId='agent_browser_'+Date.now()
 expect((await request.post(api+'/api/v1/commands',{data:{type:'CREATE_PROJECT',expectedVersion:state.version,payload:{id:projectId,title:'Agent 协作浏览器验收',brief:'隔离测试数据，不调用付费模型'}}})).ok()).toBe(true)
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/projects/'+projectId+'?node=N08');await page.getByRole('link',{name:'启动 Agent 协作'}).click();await expect(page).toHaveURL(new RegExp('/runs\\?projectId='+projectId+'&node=N08'))
 await page.getByRole('button',{name:'启动测试协作'}).click();await expect(page.getByRole('heading',{name:'等你采纳',exact:true})).toBeVisible({timeout:25000})
 await expect(page.locator('.candidate-panel')).toContainText('第 2 版候选');await expect(page.locator('.candidate-panel')).toContainText('要求返工');await expect(page.locator('.run-timeline')).toContainText('task → 选题研究');await expect(page.locator('.run-timeline')).toContainText('独立评审')
 fs.mkdirSync('ui-artifacts',{recursive:true});await page.screenshot({path:'ui-artifacts/agent-run-desktop.png',fullPage:false,animations:'disabled'})
 await page.getByRole('button',{name:'采纳为草稿'}).click();await expect(page.getByRole('heading',{name:'已采纳为草稿',exact:true})).toBeVisible({timeout:12000})
 state=(await(await request.get(api+'/api/v1/workspace')).json()).data;const node=state.projects.find((p:any)=>p.id===projectId).nodes.N08;expect(node.status).toBe('DRAFT');expect(node.output).toBe('');expect(node.draft).toContain('测试模型产物')
 await page.getByRole('button',{name:'删除运行记录'}).click();await expect(page.locator('.run-inbox .run-card')).toHaveCount(0);await page.getByRole('button',{name:'已删除',exact:true}).click();await expect(page.locator('.run-inbox .run-card')).toHaveCount(1);await page.getByRole('button',{name:'恢复记录'}).click();await expect(page.locator('.run-inbox .run-card')).toHaveCount(0)
 await page.getByRole('button',{name:'返回运行列表'}).click();await expect(page.locator('.run-inbox .run-card')).toHaveCount(1)
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'ui-artifacts/agent-run-mobile.png',fullPage:false,animations:'disabled'});expect(errors).toEqual([])
})

test('采纳过期草稿被拒绝，缺失依赖与真实调用被拦截',async({request})=>{
 const state=(await(await request.get(api+'/api/v1/workspace')).json()).data
 const projectId='agent_stale_'+Date.now()
 await request.post(api+'/api/v1/commands',{data:{type:'CREATE_PROJECT',expectedVersion:state.version,payload:{id:projectId,title:'过期候选测试'}}})
 const id='run_'+crypto.randomUUID();expect((await request.post(api+'/api/v1/agent-runs',{data:{id,projectId,nodeId:'N08',mode:'FIXTURE'}})).ok()).toBe(true)
 await expect.poll(async()=>((await(await request.get(api+'/api/v1/agent-runs/'+id)).json()).data.runtime?.status),{timeout:25000}).toBe('WAITING_ACCEPTANCE')
 const current=(await(await request.get(api+'/api/v1/workspace')).json()).data
 await request.post(api+'/api/v1/commands',{data:{type:'SAVE_NODE',expectedVersion:current.version,payload:{projectId,nodeId:'N08',text:'更新后的人工草稿',complete:false}}})
 const response=await request.post(api+'/api/v1/agent-runs/'+id+'/decision',{data:{decision:'ACCEPT'}});expect(response.status()).toBe(409);expect((await response.json()).message).toContain('过期')
 expect((await request.post(api+'/api/v1/agent-runs',{data:{id:'run_'+crypto.randomUUID(),projectId,nodeId:'N15',mode:'FIXTURE'}})).status()).toBe(409)
 expect((await request.post(api+'/api/v1/agent-runs',{data:{id:'run_'+crypto.randomUUID(),projectId,nodeId:'N08',mode:'LIVE'}})).status()).toBe(409)
})
