import {defineConfig} from '@playwright/test'
const baseURL=process.env.PLAYWRIGHT_BASE_URL??'http://127.0.0.1:15178'
// 只有隔离脚本同时提供实例标记和外部服务开关时，后端/Agent 用例才允许运行。
export const isolated=process.env.PLAYWRIGHT_EXTERNAL_SERVER==='1'&&!!process.env.PLAYWRIGHT_TEST_INSTANCE_ID
const backendSpecs=['**/agents.spec.ts','**/backend.spec.ts','**/visual-backend.spec.ts']
export default defineConfig({
 testDir:'./tests',testMatch:'*.spec.ts',testIgnore:isolated?[]:backendSpecs,workers:1,retries:0,reporter:'list',timeout:30000,
 use:{baseURL,channel:'msedge',headless:true,viewport:{width:1440,height:1040},screenshot:'only-on-failure'},
 webServer:process.env.PLAYWRIGHT_EXTERNAL_SERVER==='1'?undefined:{command:'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 15178 --strictPort',url:baseURL,reuseExistingServer:false},
 outputDir:'test-results'
})
