import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import {initialState,type Catalog} from '../src/lib/domain'

test('专家测试草稿显示风险，修改后重新确认，并将人工确认送至服务端',async({page})=>{
 const catalog=JSON.parse(fs.readFileSync(new URL('../src/data/catalog.json',import.meta.url),'utf8')) as Catalog
 const state=initialState(catalog),node=state.projects[0].nodes.N08
 node.status='DRAFT';node.draft='测试正文';node.agentDraftReview={runId:'run_test_example',fixture:true,uncertainties:['未核验事实'],candidateVersion:2,fixtureBody:'测试正文'}
 await page.route('**/api/v1/workspace',route=>route.fulfill({json:{data:state}}))
 let payload:Record<string,unknown>|undefined
 await page.route('**/api/v1/commands',route=>{
  const command=route.request().postDataJSON();payload=command.payload
  node.draft=String(command.payload.text);node.output=node.draft;node.status='COMPLETED';node.agentDraftReview!.reviewedByHuman=true
  return route.fulfill({json:{data:state}})
 })
 await page.goto('/projects/sample_focus?node=N08')
 await expect(page.getByRole('heading',{name:'测试产物 · 仅供流程验证'})).toBeVisible()
 await expect(page.getByText('未核验事实')).toBeVisible()
 const complete=page.getByRole('button',{name:'标记产物完成',exact:true})
 await expect(complete).toBeDisabled()
 const acknowledged=page.getByRole('checkbox',{name:/我已核对草稿和待核实事项/})
 const replaced=page.getByRole('checkbox',{name:/我已移除测试正文与占位内容/})
 await acknowledged.check();await replaced.check();await expect(complete).toBeEnabled()
 await page.getByLabel('本节点产物').fill('用户提供的真实想法')
 await expect(acknowledged).not.toBeChecked();await expect(replaced).not.toBeChecked();await expect(complete).toBeDisabled()
 await acknowledged.check();await replaced.check();await complete.click()
 expect(payload?.agentReview).toEqual({runId:'run_test_example',acknowledged:true,fixtureReplaced:true})
 await expect(page.locator('.editor-top .node-id')).toHaveText('N24')
 await page.locator('.node-item').filter({hasText:'N08'}).click()
 await expect(page.getByText('当前完成版本已记录人工确认；修改后需重新确认。')).toBeVisible()
 await page.setViewportSize({width:390,height:844})
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})

test('普通手写产物不要求专家审阅确认',async({page})=>{
 await page.route('**/api/v1/workspace',route=>route.abort())
 await page.goto('/projects/sample_focus?node=N08')
 await expect(page.locator('.agent-review')).toHaveCount(0)
 await page.getByLabel('本节点产物').fill('手工填写的内容')
 await expect(page.getByRole('button',{name:'标记产物完成',exact:true})).toBeEnabled()
 await page.getByRole('button',{name:'保存草稿',exact:true}).click()
})

test('浏览器本地模式确认后可完成并保留审阅状态',async({page})=>{
 const catalog=JSON.parse(fs.readFileSync(new URL('../src/data/catalog.json',import.meta.url),'utf8')) as Catalog
 const state=initialState(catalog),node=state.projects[0].nodes.N08
 node.status='DRAFT';node.draft='测试正文';node.agentDraftReview={runId:'run_local_fixture',fixture:true,fixtureBody:'测试正文',uncertainties:['来源待核实']}
 await page.addInitScript(value=>localStorage.setItem('creator-workbench-v1',JSON.stringify(value)),state)
 await page.route('**/api/v1/workspace',route=>route.abort())
 await page.goto('/projects/sample_focus?node=N08')
 const complete=page.getByRole('button',{name:'标记产物完成',exact:true})
 await page.getByLabel('本节点产物').fill('用户亲自提供的材料')
 await page.getByRole('checkbox',{name:/我已核对草稿和待核实事项/}).check()
 await page.getByRole('checkbox',{name:/我已移除测试正文与占位内容/}).check()
 await complete.click()
 await page.locator('.node-item').filter({hasText:'N08'}).click()
 await expect(page.getByText('当前完成版本已记录人工确认；修改后需重新确认。')).toBeVisible()
 const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('creator-workbench-v1')!))
 expect(saved.projects[0].nodes.N08.agentDraftReview.reviewedByHuman).toBe(true)
 expect(saved.projects[0].nodes.N08.agentDraftReview.localReviewedText).toBe('用户亲自提供的材料')
})
