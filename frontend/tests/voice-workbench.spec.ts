import {test, expect} from '@playwright/test'

test('角色库可试听样本并为作品保存选角', async ({page}) => {
  await page.route('**/api/v1/workspace', route => route.fulfill({status:503,body:'{}'}))
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
  await page.route('**/api/v1/workspace', route => route.fulfill({status:503,body:'{}'}))
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
