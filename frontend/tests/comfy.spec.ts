import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import {fingerprint,initialState,type Catalog} from '../src/lib/domain'

const catalog=JSON.parse(fs.readFileSync(new URL('../src/data/catalog.json',import.meta.url),'utf8')) as Catalog

test('本机视频候选需人工采纳，生成不会直接完成节点',async({page})=>{
 const state=initialState(catalog),project=state.projects.find(p=>p.id==='sample_ai')!
 for(const id of ['N16','N17','N18','N19','N20','N21','N22','N23','N24']){project.nodes[id].status='COMPLETED';project.nodes[id].revision=1}
 for(const id of ['N25','N26']){project.nodes[id].status='SKIPPED';project.nodes[id].revision=1}
 const gate=catalog.gates.find(g=>g.id==='G03')!;project.approvals.G03={id:'G03',decision:'APPROVED',at:new Date().toISOString(),fingerprint:fingerprint(project,gate)}
 let run:Record<string,unknown>|undefined,adopted=false
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{code:0,data:state}}))
 await page.route('**/api/v1/comfy-runs**',async route=>{
  const request=route.request(),url=new URL(request.url())
  if(url.pathname.endsWith('/readiness'))return route.fulfill({json:{code:0,data:{enabled:true,online:true,templates:[{id:'local-video',name:'本机视频模板',ready:true}]}}})
  if(url.pathname.endsWith('/adopt')){adopted=true;run={...run,adopted:true};return route.fulfill({json:{code:0,data:run}})}
  if(request.method()==='POST'){
   const input=request.postDataJSON();expect(input.projectId).toBe(project.id);expect(input.nodeId).toBe('N27');expect(input.templateId).toBe('local-video');expect(input.prompt).toBe('林间晨光');expect(input.seed).toBe(42)
   run={...input,state:'SUCCEEDED',createdAt:new Date().toISOString(),fileRef:'/api/v1/files/test-file',adopted:false}
   return route.fulfill({json:{code:0,data:run}})
  }
  return route.fulfill({json:{code:0,data:run?[run]:[]}})
 })
 await page.goto('/projects/sample_ai?node=N27')
 const panel=page.getByRole('region',{name:'ComfyUI 视频生成'})
 await expect(panel).toContainText('ComfyUI 已连接')
 await expect(panel.getByRole('button',{name:'生成候选视频'})).toBeDisabled()
 await panel.getByLabel('视频生成描述').fill('林间晨光')
 await panel.getByRole('button',{name:'生成候选视频'}).click()
 await expect(panel).toContainText('候选已生成')
 await expect(panel.locator('video')).toHaveAttribute('src','/api/v1/files/test-file')
 expect(adopted).toBe(false)
 await panel.getByRole('button',{name:'采纳到素材库'}).click()
 await expect(panel.getByRole('button',{name:'已放入素材库'})).toBeDisabled()
 expect(adopted).toBe(true)
 await expect(page.locator('.editor-top')).toContainText('未开始')
})

test('未满足拍板和依赖时不允许提交',async({page})=>{
 const state=initialState(catalog)
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{code:0,data:state}}))
 await page.route('**/api/v1/comfy-runs**',route=>route.fulfill({json:{code:0,data:route.request().url().includes('/readiness')?{enabled:true,online:true,templates:[{id:'local-video',name:'本机视频模板',ready:true}]}:[]}}))
 await page.goto('/projects/sample_ai?node=N27')
 const panel=page.getByRole('region',{name:'ComfyUI 视频生成'})
 await panel.getByLabel('视频生成描述').fill('林间晨光')
 await expect(panel.getByRole('button',{name:'生成候选视频'})).toBeDisabled()
 await expect(panel).toContainText('完成依赖并确认制作方案后可生成')
})

test('提交结果未知时阻止重复生成',async({page})=>{
 const state=initialState(catalog),project=state.projects.find(p=>p.id==='sample_ai')!
 for(const id of ['N16','N17','N18','N19','N20','N21','N22','N23','N24']){project.nodes[id].status='COMPLETED';project.nodes[id].revision=1}
 for(const id of ['N25','N26']){project.nodes[id].status='SKIPPED';project.nodes[id].revision=1}
 const gate=catalog.gates.find(g=>g.id==='G03')!;project.approvals.G03={id:'G03',decision:'APPROVED',at:new Date().toISOString(),fingerprint:fingerprint(project,gate)}
 let submissions=0
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{code:0,data:state}}))
 await page.route('**/api/v1/comfy-runs**',route=>{
  const request=route.request(),url=new URL(request.url())
  if(url.pathname.endsWith('/readiness'))return route.fulfill({json:{code:0,data:{enabled:true,online:true,templates:[{id:'local-video',name:'本机视频模板',ready:true}]}}})
  if(request.method()==='POST'){submissions++;return route.fulfill({status:503,json:{message:'临时连接失败'}})}
  return route.fulfill({json:{code:0,data:[]}})
 })
 await page.goto('/projects/sample_ai?node=N27')
 const panel=page.getByRole('region',{name:'ComfyUI 视频生成'})
 await panel.getByLabel('视频生成描述').fill('林间晨光')
 await panel.getByRole('button',{name:'生成候选视频'}).click()
 await expect(panel.getByRole('alert')).toContainText('提交结果未知')
 await expect(panel.getByRole('button',{name:'生成候选视频'})).toBeDisabled()
 expect(submissions).toBe(1)
 await page.reload()
 await panel.getByLabel('视频生成描述').fill('林间晨光')
 await expect(panel.getByRole('button',{name:'生成候选视频'})).toBeDisabled()
 await expect(panel).toContainText('已有任务正在处理或结果待核对')
 expect(submissions).toBe(1)
})
