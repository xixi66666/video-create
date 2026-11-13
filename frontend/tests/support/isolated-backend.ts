import {test,expect} from '@playwright/test'

export const api=process.env.PLAYWRIGHT_API_URL??''
export const instance=process.env.PLAYWRIGHT_TEST_INSTANCE_ID??''
export const isolated=process.env.PLAYWRIGHT_EXTERNAL_SERVER==='1'&&!!instance
const dailyPorts=['5178','8088','8090']

/**
 * 每个后端/Agent 测试文件必须自己调用此函数。
 * 不要在被 import 的共享模块顶层注册 skip/beforeAll；Playwright 的模块缓存会让
 * 它只对部分文件生效，普通 e2e 可能误连日常工作区。
 */
export function useIsolatedBackend(){
 test.beforeEach(()=>{
  test.skip(!isolated,'联合测试请运行 npm run test:e2e:backend，脚本会创建独立服务与临时数据目录')
 })
 test.beforeAll(async({request,baseURL})=>{
  if(!isolated)return
  for(const address of [api,baseURL]){
   if(!address)throw new Error('缺少隔离服务地址')
   const url=new URL(address)
   if(url.hostname!=='127.0.0.1'||dailyPorts.includes(url.port))throw new Error('联合测试禁止连接日常服务端口')
   const response=await request.get(address+'/api/v1/health')
   expect(response.ok()).toBe(true)
   expect(response.headers()['x-workbench-test-instance']).toBe(instance)
  }
 })
}
