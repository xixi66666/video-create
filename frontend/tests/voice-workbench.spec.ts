import {test, expect} from '@playwright/test'
import {isolated} from '../playwright.config'

test.skip(!isolated, '配音选角需要隔离的后端工作区')

test('角色库可试听样本并为作品保存选角', async ({page}) => {
  await page.route('**/api/v1/speech/voice', async route => {
    const body=route.request().postDataJSON()
    const data=body.action==='list'
      ? {mimoConfigured:false,roles:[{id:'narrator_one',name:'古诗旁白',version:'1.0.0',selected:1,clips:[{start:10,end:22}],samples:[{file:'春江花月夜.wav'}]}]}
      : {audioBase64:'UklGRg=='}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data})})
  })
  await page.goto('/voice')
  await expect(page.getByRole('heading',{name:'配音工作台'})).toBeVisible()
  await expect(page.getByText('古诗旁白').first()).toBeVisible()
  await page.getByRole('button',{name:'春江花月夜.wav'}).click()
  await expect(page.locator('audio')).toBeVisible()
  const project=page.locator('section').filter({has:page.getByRole('heading',{name:'为作品选角'})}).locator('select')
  await project.selectOption({index:1})
  await page.getByRole('button',{name:'保存选角'}).click()
  await expect(page.getByText('选角已保存到作品')).toBeVisible()
  await page.reload()
  await project.selectOption({index:1})
  await expect(page.getByText('旁白 · 古诗旁白')).toBeVisible()
})

test('重命名后角色和作品选角显示新名称，刷新后保留', async ({page}) => {
  let name='古诗旁白'
  await page.route('**/api/v1/speech/voice', async route => {
    const body=route.request().postDataJSON()
    if(body.action==='rename') name=body.name
    const data=body.action==='list'
      ? {mimoConfigured:false,roles:[{id:'narrator_one',name,version:'1.0.0',selected:1,clips:[],samples:[]}]}
      : {id:'narrator_one',name}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data})})
  })
  await page.goto('/voice')
  const project=page.locator('section').filter({has:page.getByRole('heading',{name:'为作品选角'})}).locator('select')
  await project.selectOption({index:1})
  await page.getByRole('button',{name:'保存选角'}).click()
  await page.getByRole('button',{name:'修改名称'}).click()
  await page.getByLabel('角色名称',{exact:true}).fill('月夜朗诵')
  await page.getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.getByRole('heading',{name:'月夜朗诵'})).toBeVisible()
  await expect(page.getByText('旁白 · 月夜朗诵')).toBeVisible()
  await page.reload()
  await project.selectOption({index:1})
  await expect(page.getByRole('heading',{name:'月夜朗诵'})).toBeVisible()
  await expect(page.getByText('旁白 · 月夜朗诵')).toBeVisible()
})

test('作品配音检查说话人绑定并展示生成的音轨', async ({page}) => {
  let submitted: any = null
  await page.route('**/api/v1/speech/voice', async route => {
    const body=route.request().postDataJSON()
    let data: any = {}
    if(body.action==='list') data={mimoConfigured:true,roles:[{id:'narrator_one',name:'古诗旁白',version:'1.0.0',selected:1,clips:[],samples:[]}]}
    if(body.action==='dub_start') { submitted=body; data={id:'abc',role:'',status:'queued',message:'等待处理'} }
    if(body.action==='job') data={id:'abc',role:'',status:'done',message:'配音已生成'}
    if(body.action==='dub_list') data={runs:submitted?[{id:'abc',status:'done',message:'配音已生成',completed:1,audio:'combined.wav',lines:submitted.lines}]:[]}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data})})
  })
  await page.goto('/voice')
  const casting=page.locator('section').filter({has:page.getByRole('heading',{name:'为作品选角'})})
  await casting.locator('select').selectOption({index:1})
  await page.getByRole('button',{name:'保存选角'}).click()
  const script=page.getByLabel('每行一句，格式为“说话人：台词”')
  await script.fill('旁白：天亮了。\n小明：出发吧。')
  await expect(page.getByText('尚未选角：小明。请先在上方为这些说话人保存选角。')).toBeVisible()
  await expect(page.getByRole('button',{name:'生成作品配音'})).toBeDisabled()
  await script.fill('旁白：天亮了。')
  await page.getByRole('button',{name:'生成作品配音'}).click()
  await expect(page.getByRole('button',{name:'试听完整音轨'})).toBeVisible()
  expect(submitted.lines).toEqual([{speaker:'旁白',text:'天亮了。'}])
  expect(submitted.cast[0].roleId).toBe('narrator_one')
})


test('工作区不可用时不能回退本地保存', async ({page}) => {
  await page.route('**/api/v1/workspace', route => route.fulfill({status:503,body:'{}'}))
  await page.goto('/voice')
  await expect(page.getByRole('heading',{name:'连接作品数据库'})).toBeVisible()
  await expect(page.getByText('无法连接远端作品数据库，请检查后端和网络后重试').first()).toBeVisible()
  await expect(page.getByRole('heading',{name:'配音工作台'})).toHaveCount(0)
})
