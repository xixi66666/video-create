import {test,expect} from '@playwright/test'
import {api,useIsolatedBackend} from './support/isolated-backend'
useIsolatedBackend()
test('后端模式下创建、节点保存与刷新恢复',async({page,request})=>{
 const health=await request.get(api+'/api/v1/health');expect(health.ok()).toBe(true)
 await page.goto('/');await expect(page.locator('.workspace-note')).toContainText('本机服务已连接')
 await page.getByRole('button',{name:'新建作品',exact:true}).click();await page.getByLabel('作品名称').fill('后端联调验收作品');await page.getByRole('button',{name:'创建作品',exact:true}).click();await expect(page.getByRole('heading',{name:'后端联调验收作品',exact:true})).toBeVisible()
 await page.getByLabel('本节点产物').fill('真实服务持久化验收：只使用本机测试数据。');await page.getByRole('button',{name:'标记产物完成',exact:true}).click();await expect(page).toHaveURL(/node=N03/);await page.locator('.node-item').filter({hasText:'N02'}).click();await expect(page.locator('.editor-top')).toContainText('已完成');await page.reload();await expect(page.getByLabel('本节点产物')).toHaveValue('真实服务持久化验收：只使用本机测试数据。')
 const workspace=(await(await request.get(api+'/api/v1/workspace')).json()).data;expect(workspace.projects.find((p:any)=>p.title==='后端联调验收作品').nodes.N02.output).toContain('真实服务持久化验收')
})
test('素材原件上传、校验与回读',async({request})=>{
 const content=Buffer.from('creator-workbench file roundtrip verification')
 const response=await request.post(api+'/api/v1/files',{multipart:{file:{name:'verification.txt',mimeType:'text/plain',buffer:content}}});expect(response.ok()).toBe(true);const body=await response.json();expect(body.data.sha256).toMatch(/^[a-f0-9]{64}$/);expect(body.data.size).toBe(content.length)
 const file=await request.get(api+body.data.fileRef);expect(await file.body()).toEqual(content);expect((await request.get(api+'/api/v1/files/not-a-real-file')).status()).toBe(404)
})
test('服务端拒绝把认证信息放入模型参数',async({request})=>{
 const state=(await(await request.get(api+'/api/v1/workspace')).json()).data
 const response=await request.post(api+'/api/v1/commands',{data:{type:'SAVE_MODEL',expectedVersion:state.version,payload:{model:{id:'credential-guard-test',name:'test',provider:'test',remoteModelId:'test',protocol:'CUSTOM_HTTP',baseUrl:'https://provider.example.invalid',credentialRef:'CREATOR_TEST_KEY',capabilities:['TEXT_REASONING'],parameters:{apiKey:'EXAMPLE_ONLY'},enabled:false,verified:false}}}})
 expect(response.status()).toBe(400);expect((await response.json()).message).toContain('不能保存密钥')
 const after=(await(await request.get(api+'/api/v1/workspace')).json()).data;expect(after.version).toBe(state.version)
})
