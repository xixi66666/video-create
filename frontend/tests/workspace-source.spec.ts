import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import {initialState,type Catalog} from '../src/lib/domain'

const catalog=JSON.parse(fs.readFileSync(new URL('../src/data/catalog.json',import.meta.url),'utf8')) as Catalog
function workspace(title:string){const state=initialState(catalog);state.projects[0].title=title;return state}
async function refreshStore(page:import('@playwright/test').Page){
 return page.evaluate(async()=>{
  const module=await new Function("return import('/src/stores/workbench.ts')")()
  const store=module.useWorkbench()
  const ok=await store.init()
  return {ok,connection:store.connection,title:store.state.projects[0].title,notice:store.notice}
 })
}

test('服务端刷新失败时保留原工作区，不混入浏览器本地数据',async({page})=>{
 await page.addInitScript(state=>localStorage.setItem('creator-workbench-v1',JSON.stringify(state)),workspace('浏览器本地项目'))
 let count=0
 await page.route('**/api/v1/workspace',route=>++count===1?route.fulfill({json:{data:workspace('服务端项目')}}):route.fulfill({status:503,json:{message:'不可用'}}))
 await page.goto('/')
 await expect(page.getByText('服务端项目').first()).toBeVisible()
 const result=await refreshStore(page)
 expect(result.ok).toBe(false)
 expect(result.connection).toBe('server')
 expect(result.title).toBe('服务端项目')
 expect(result.notice).toContain('刷新')
})

test('工作区刷新等待排队中的保存，避免旧快照覆盖新修改',async({page})=>{
 const state=workspace('服务端项目')
 let commandCompleted=false,refreshAfterSave=false,count=0
 await page.route('**/api/v1/workspace',route=>{
  if(++count>1)refreshAfterSave=commandCompleted
  return route.fulfill({json:{data:state}})
 })
 await page.route('**/api/v1/commands',async route=>{
  await new Promise(resolve=>setTimeout(resolve,150))
  commandCompleted=true
  await route.fulfill({json:{data:state}})
 })
 await page.goto('/')
 await expect(page.getByText('服务端项目').first()).toBeVisible()
 await page.evaluate(async()=>{
  const module=await new Function("return import('/src/stores/workbench.ts')")()
  const store=module.useWorkbench()
  await Promise.all([store.command({type:'ADD_IDEA',payload:{text:'测试保存'}},''),store.init()])
 })
 expect(refreshAfterSave).toBe(true)
})

test('本地工作区不会在后台刷新时被服务器工作区替换',async({page})=>{
 await page.addInitScript(state=>localStorage.setItem('creator-workbench-v1',JSON.stringify(state)),workspace('浏览器本地项目'))
 let count=0
 await page.route('**/api/v1/workspace',route=>++count===1?route.fulfill({status:503,json:{message:'不可用'}}):route.fulfill({json:{data:workspace('服务端项目')}}))
 await page.goto('/')
 await expect(page.getByText('浏览器本地项目').first()).toBeVisible()
 const result=await refreshStore(page)
 expect(result.ok).toBe(false)
 expect(result.connection).toBe('local')
 expect(result.title).toBe('浏览器本地项目')
 await page.route('**/api/v1/agent-runs/readiness',route=>route.fulfill({json:{data:{online:true,liveModelsEnabled:false}}}))
 await page.route('**/api/v1/agent-runs',route=>route.fulfill({json:{data:[]}}))
 await page.getByRole('link',{name:'协作运行'}).click()
 await expect(page.getByText(/当前使用浏览器本地工作区/)).toBeVisible()
 await expect(page.getByRole('button',{name:'启动测试协作'})).toBeDisabled()
})

test('已删除的待采纳运行不能从界面采纳或拒绝',async({page})=>{
 const state=workspace('服务端项目'),id='run_deleted_0001'
 const candidate={body:'待核对候选',fields:{},sources:[],uncertainties:[],fixture:true,executionMode:'GENERATE_TEXT',version:1,sha256:'a'.repeat(64)}
 const run={id,projectId:state.projects[0].id,nodeId:'N08',state:'SUBMITTED',deletedAt:'2026-01-01T00:00:00Z',createdAt:'2026-01-01T00:00:00Z',mode:'FIXTURE',executionMode:'GENERATE_TEXT',models:{},limits:{maxModelCalls:30,maxReworks:1},runtime:{status:'WAITING_ACCEPTANCE',artifacts:[{kind:'CANDIDATE',version:1,content:candidate}]},events:[]}
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{data:state}}))
 await page.route('**/api/v1/agent-runs/readiness',route=>route.fulfill({json:{data:{online:true,liveModelsEnabled:false}}}))
 await page.route('**/api/v1/agent-runs/'+id,route=>route.fulfill({json:{data:run}}))
 await page.route('**/api/v1/agent-runs',route=>route.fulfill({json:{data:[run]}}))
 await page.goto('/runs?run='+id)
 await expect(page.getByText('待核对候选')).toBeVisible()
 await expect(page.getByRole('button',{name:'恢复记录'})).toBeVisible()
 await expect(page.getByRole('button',{name:'采纳为草稿'})).toHaveCount(0)
 await expect(page.getByRole('button',{name:'拒绝候选'})).toHaveCount(0)
})

test('协作服务轮询失败后不再显示已连接，恢复后可重新显示',async({page})=>{
 let available=true
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{data:workspace('服务端项目')}}))
 await page.route('**/api/v1/agent-runs/readiness',route=>available?route.fulfill({json:{data:{online:true,liveModelsEnabled:true}}}):route.fulfill({status:503,json:{message:'服务暂时不可用'}}))
 await page.route('**/api/v1/agent-runs',route=>route.fulfill({json:{data:[]}}))
 await page.goto('/runs')
 await expect(page.getByText('协作运行服务已连接')).toBeVisible()
 available=false
 await page.getByRole('button',{name:'刷新状态'}).click()
 await expect(page.getByText('运行服务未连接')).toBeVisible()
 await expect(page.getByRole('alert')).toContainText('服务暂时不可用')
 await expect(page.getByRole('button',{name:'启动测试协作'})).toBeDisabled()
 available=true
 await page.getByRole('button',{name:'刷新状态'}).click()
 await expect(page.getByText('协作运行服务已连接')).toBeVisible()
})

test('取消未确认时显示重试入口，并在确认前禁止删除',async({page})=>{
 const state=workspace('服务端项目'),id='run_cancel_0001'
 const run={id,projectId:state.projects[0].id,nodeId:'N08',state:'CANCEL_SYNC_FAILED',createdAt:'2026-01-01T00:00:00Z',mode:'FIXTURE',executionMode:'GENERATE_TEXT',models:{},limits:{maxModelCalls:30,maxReworks:1},runtime:{status:'RUNNING',artifacts:[]},events:[]}
 let action=''
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{data:state}}))
 await page.route('**/api/v1/agent-runs/readiness',route=>route.fulfill({json:{data:{online:true,liveModelsEnabled:false}}}))
 await page.route('**/api/v1/agent-runs/'+id+'/control',route=>{action=route.request().postDataJSON().action;run.state='CANCEL_PENDING_SYNC';return route.fulfill({json:{data:run}})})
 await page.route('**/api/v1/agent-runs/'+id,route=>route.fulfill({json:{data:run}}))
 await page.route('**/api/v1/agent-runs',route=>route.fulfill({json:{data:[run]}}))
 await page.goto('/runs?run='+id)
 await expect(page.getByRole('heading',{name:'取消结果未确认'})).toBeVisible()
 await expect(page.getByRole('button',{name:'删除运行记录'})).toBeDisabled()
 await page.getByRole('button',{name:'重试取消'}).click()
 await expect(page.getByRole('heading',{name:'取消同步中'})).toBeVisible()
 await expect(page.getByRole('button',{name:'删除运行记录'})).toBeDisabled()
 expect(action).toBe('RETRY')
})

test('投递失败时保留取消入口并提示远端状态未知',async({page})=>{
 const state=workspace('服务端项目'),id='run_failed_0001'
 const run={id,projectId:state.projects[0].id,nodeId:'N08',state:'SUBMISSION_FAILED',createdAt:'2026-01-01T00:00:00Z',mode:'FIXTURE',executionMode:'GENERATE_TEXT',models:{},limits:{maxModelCalls:30,maxReworks:1},events:[]}
 let action=''
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{data:state}}))
 await page.route('**/api/v1/agent-runs/readiness',route=>route.fulfill({json:{data:{online:true,liveModelsEnabled:false}}}))
 await page.route('**/api/v1/agent-runs/'+id+'/control',route=>{action=route.request().postDataJSON().action;run.state='CANCEL_PENDING_SYNC';return route.fulfill({json:{data:run}})})
 await page.route('**/api/v1/agent-runs/'+id,route=>route.fulfill({json:{data:run}}))
 await page.route('**/api/v1/agent-runs',route=>route.fulfill({json:{data:[run]}}))
 await page.goto('/runs?run='+id)
 await expect(page.getByText('请求可能已经到达远端；取消需要确认远端状态。')).toBeVisible()
 await expect(page.getByRole('button',{name:'删除运行记录'})).toBeDisabled()
 await page.getByRole('button',{name:'取消运行'}).click()
 await expect(page.getByRole('heading',{name:'取消同步中'})).toBeVisible()
 expect(action).toBe('CANCEL')
})
