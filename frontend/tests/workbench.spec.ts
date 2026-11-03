import {test,expect} from '@playwright/test'
import fs from 'node:fs'

test.beforeEach(async({page})=>{await page.route('**/api/v1/workspace',route=>route.abort());await page.goto('/');await expect(page.locator('.workspace-note')).toContainText('浏览器本地保存')})
test('桌面首页、全节点与真实创建保存刷新',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await expect(page.getByRole('heading',{name:'让好想法，成为下一条作品.'})).toBeVisible()
 fs.mkdirSync('ui-artifacts',{recursive:true});await page.screenshot({path:'ui-artifacts/dashboard-desktop.png',fullPage:true,animations:'disabled'})
 await page.getByRole('button',{name:'新建作品',exact:true}).click();await page.getByLabel('作品名称').fill('浏览器验收作品');await page.getByLabel('最初的想法').fill('检查 49 节点与持久化');await page.getByRole('button',{name:'创建作品',exact:true}).click()
 await expect(page.getByRole('heading',{name:'浏览器验收作品',exact:true})).toBeVisible();await expect(page.locator('.node-item')).toHaveCount(49)
 await page.getByLabel('本节点产物').fill('资源：每周有三小时，有麦克风和录屏环境。');await page.getByRole('button',{name:'标记产物完成',exact:true}).click();await expect(page).toHaveURL(/node=N03/);await expect(page.locator('.editor-top .node-id')).toHaveText('N03')
 await page.locator('.node-item').filter({hasText:'N02'}).click();await expect(page.locator('.editor-top')).toContainText('已完成');await page.reload();await expect(page.getByLabel('本节点产物')).toHaveValue('资源：每周有三小时，有麦克风和录屏环境。');await page.screenshot({path:'ui-artifacts/workspace-desktop.png',fullPage:true,animations:'disabled'});expect(errors).toEqual([])
})
test('模型配置、全局绑定与秘密引用校验',async({page})=>{
 await page.getByRole('link',{name:'模型中心',exact:true}).click();await page.getByRole('button',{name:'登记模型',exact:true}).click();await page.getByLabel('显示名称').fill('验收写作模型');await page.getByLabel('服务商',{exact:true}).fill('本地验收服务');await page.getByLabel('真实模型 ID').fill('test-writer');await page.getByLabel('服务地址').fill('https://provider.example.invalid/v1');await page.getByRole('button',{name:'保存模型',exact:true}).click()
 await expect(page.locator('.model-table')).toContainText('验收写作模型');await expect(page.locator('.model-table')).toContainText('待接入验证');await page.locator('.binding-grid label').filter({hasText:'LLM 语言与推理'}).locator('select').selectOption({label:'验收写作模型'});await page.reload();await expect(page.locator('.binding-grid label').filter({hasText:'LLM 语言与推理'}).locator('select')).toHaveValue(/model_/)
 await page.screenshot({path:'ui-artifacts/models-desktop.png',fullPage:true,animations:'disabled'})
})
test('灵感、未接入工具说明与手机布局',async({page})=>{
 await page.getByRole('textbox',{name:'记录灵感',exact:true}).fill('一条真实保存的验收灵感');await page.getByRole('button',{name:'保存灵感',exact:true}).click();await page.getByRole('link',{name:'灵感收件箱',exact:true}).click();await expect(page.locator('.idea-list')).toContainText('一条真实保存的验收灵感')
 await page.getByRole('link',{name:'工具与环境',exact:true}).click();await expect(page.locator('.tool-card')).toHaveCount(6);await expect(page.locator('.tool-card').first()).toContainText('未接入')
 await page.setViewportSize({width:390,height:844});await page.goto('/');await expect(page.getByRole('button',{name:'打开菜单'})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'ui-artifacts/dashboard-mobile.png',fullPage:true,animations:'disabled'})
})
