import fs from 'node:fs'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const entries={nodes:['nodes.json','nodes'],agents:['agents.json','agents'],capabilities:['capabilities.json','capabilities'],gates:['gates.json','gates'],templates:['workflow-templates.json','templates']}
const catalog={}
for(const[key,[file,field]]of Object.entries(entries))catalog[key]=JSON.parse(fs.readFileSync(path.join(root,'specs',file),'utf8'))[field]
if(catalog.nodes.length!==49)throw new Error('Expected 49 active node definitions')
for(const destination of ['frontend/src/data/catalog.json','backend/src/main/resources/catalog.json']){const output=path.join(root,destination);fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(catalog,null,2)+'\n')}
fs.mkdirSync(path.join(root,'frontend/public/guides'),{recursive:true})
fs.copyFileSync(path.join(root,'docs/08-external-integration.md'),path.join(root,'frontend/public/guides/external-integration.md'))
fs.copyFileSync(path.join(root,'docs/16-agent-implementation.md'),path.join(root,'frontend/public/guides/agent-implementation.md'))
fs.copyFileSync(path.join(root,'docs/20-multi-agent-runtime.md'),path.join(root,'frontend/public/guides/agent-runtime.md'))
fs.copyFileSync(path.join(root,'docs/22-comfyui-local-connector.md'),path.join(root,'frontend/public/guides/22-comfyui-local-connector.md'))
console.log('Catalog synchronized: 49 active nodes, 19 roles, 25 capabilities, 6 gates.')

for(const destination of ["frontend/src/data/model-parameter-policy.json","backend/src/main/resources/model-parameter-policy.json"]){fs.copyFileSync(path.join(root,"specs/model-parameter-policy.json"),path.join(root,destination))}
