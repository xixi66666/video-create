import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import net from 'node:net'
import crypto from 'node:crypto'
import {spawn,spawnSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {removeIsolatedTestDirectory} from './e2e-temp-cleanup.mjs'

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'creator-workbench-e2e-'))
const children=[],logs=[]
const instance=crypto.randomUUID()
fs.writeFileSync(path.join(temporary,'.creator-e2e-instance'),instance,{flag:'wx'})
const environment={...process.env,CREATOR_RUNTIME_TOKEN:crypto.randomBytes(32).toString('base64'),CREATOR_ENABLE_LIVE_MODELS:'false',CREATOR_APPROVED_AGENT_MODELS:'',CREATOR_RUNTIME_DATA:path.join(temporary,'runtime'),CREATOR_RESEARCH_ENABLED:'false',CREATOR_LOCAL_MEDIA_ENABLED:'false'}
// 隔离测试不调用付费服务，避免将父进程的真实凭据传播给测试进程。
delete environment.DEEPSEEK_API_KEY
delete environment.CREATOR_CREDENTIAL_HOST_GUARDS
function publicEnvironment(){const copy={...environment};delete copy.CREATOR_RUNTIME_TOKEN;return copy}
let closing=false
async function freePort(){return await new Promise((resolve,reject)=>{const server=net.createServer();server.on('error',reject);server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(error=>error?reject(error):resolve(port))})})}
function start(executable,args,cwd,name){
 const log=fs.openSync(path.join(temporary,name+'.log'),'a');logs.push(log)
 const child=spawn(executable,args,{cwd,env:name==='frontend'?publicEnvironment():environment,windowsHide:true,stdio:['ignore',log,log]})
 child.on('error',error=>{child.startError=error});children.push(child);return child
}
async function ready(url,child,check,headers={}){
 const until=Date.now()+90000
 while(Date.now()<until){
  if(child.startError)throw child.startError
  if(child.exitCode!==null)throw new Error('隔离服务退出，请查看 '+temporary)
  try{const response=await fetch(url,{headers,signal:AbortSignal.timeout(1500)});if(response.ok&&await check(response))return}catch{}
  await new Promise(resolve=>setTimeout(resolve,300))
 }
 throw new Error('隔离服务启动超时，请查看 '+temporary)
}
async function cleanup(){
 if(closing)return;closing=true
 for(const child of children.toReversed()){
  if(child.exitCode!==null||!child.pid)continue
  // 只终止本脚本创建且仍存活的进程树。
  if(process.platform==='win32')spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'})
  else child.kill('SIGTERM')
 }
 for(const log of logs)fs.closeSync(log)
}
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{void cleanup().then(()=>process.exit(130))})
try{
 const [webPort,apiPort,runtimePort]=await Promise.all([freePort(),freePort(),freePort()])
 const baseURL='http://127.0.0.1:'+webPort,api='http://127.0.0.1:'+apiPort,runtime='http://127.0.0.1:'+runtimePort
 const java=process.env.JAVA_HOME?path.join(process.env.JAVA_HOME,'bin',process.platform==='win32'?'java.exe':'java'):'java'
 const python=process.env.CREATOR_RUNTIME_PYTHON??path.join(root,'agent-runtime','.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python')
 const jar=path.join(root,'backend','target','creator-workbench-0.2.0.jar')
 if(!fs.existsSync(jar))throw new Error('请先在 backend 执行 mvn clean test package')
 if(!fs.existsSync(python))throw new Error('请先安装 Agent 运行环境，或设置 CREATOR_RUNTIME_PYTHON')
 Object.assign(environment,{VITE_API_TARGET:api,PLAYWRIGHT_BASE_URL:baseURL,PLAYWRIGHT_API_URL:api,PLAYWRIGHT_TEST_INSTANCE_ID:instance,PLAYWRIGHT_EXTERNAL_SERVER:'1'})
 const worker=start(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(runtimePort),'--no-access-log'],path.join(root,'agent-runtime'),'runtime')
 await ready(runtime+'/health',worker,response=>response.json().then(body=>body.liveModelsEnabled===false),{'X-Creator-Token':environment.CREATOR_RUNTIME_TOKEN})
 const backend=start(java,['-jar',jar,'--server.port='+apiPort,'--spring.datasource.url=jdbc:h2:mem:e2e_'+instance.replaceAll('-','')+';MODE=MySQL;DB_CLOSE_DELAY=-1','--workbench.files-dir='+path.join(temporary,'files'),'--workbench.allowed-origins='+baseURL,'--workbench.agent-runtime-url='+runtime,'--workbench.test-instance-id='+instance],path.join(root,'backend'),'backend')
 await ready(api+'/api/v1/health',backend,response=>response.headers.get('x-workbench-test-instance')===instance)
 const web=start(process.execPath,[path.join(root,'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',String(webPort),'--strictPort'],path.join(root,'frontend'),'frontend')
 await ready(baseURL+'/api/v1/health',web,response=>response.headers.get('x-workbench-test-instance')===instance)
 console.log('联合测试使用临时数据目录：'+temporary)
 const cli=path.join(root,'frontend/node_modules/@playwright/test/cli.js')
 const run=spawn(process.execPath,[cli,'test',...process.argv.slice(2)],{cwd:path.join(root,'frontend'),env:publicEnvironment(),windowsHide:true,stdio:'inherit'})
 children.push(run)
 const code=await new Promise((resolve,reject)=>{run.on('error',reject);run.on('exit',code=>resolve(code??1))})
 process.exitCode=code
 await cleanup()
 if(code===0){removeIsolatedTestDirectory(temporary,os.tmpdir(),instance);console.log('隔离测试通过，临时数据库和文件已清理。')}
 else console.error('测试未通过，隔离日志保留在：'+temporary)
}catch(error){process.exitCode=1;await cleanup();console.error(error.message+'；隔离日志目录：'+temporary)}
