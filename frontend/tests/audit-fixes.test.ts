import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {applyCommand,initialState,type Catalog} from '../src/lib/domain.ts'

const catalog=JSON.parse(fs.readFileSync(new URL('../src/data/catalog.json',import.meta.url),'utf8')) as Catalog
const model={id:'audit-model',name:'测试模型',provider:'test',protocol:'CUSTOM_HTTP',baseUrl:'https://example.invalid',remoteModelId:'test',credentialRef:'CREATOR_TEST_KEY',capabilities:['TEXT_REASONING'],parameters:{},enabled:false,verified:false}
test('模型参数拒绝常见凭据键、嵌套凭据、秘密值及未知参数',()=>{
 for(const parameters of [{token:'EXAMPLE_ONLY'},{headers:'Bearer EXAMPLE_ONLY'},{auth:'EXAMPLE_ONLY'},{bearer:'EXAMPLE_ONLY'},{credential:'EXAMPLE_ONLY'},{'x-api-key':'EXAMPLE_ONLY'},{response_format:{headers:{Authorization:'EXAMPLE_ONLY'}}},{stop:['Bearer EXAMPLE_ONLY']},{stop:'sk-AUDIT_EXAMPLE_ONLY_0000'},{stop:'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ0ZXN0In0.EXAMPLE_ONLY_SIGNATURE'},{stop:'-----BEGIN PRIVATE KEY----- EXAMPLE_ONLY'},{custom_option:1}]){
  assert.throws(()=>applyCommand(initialState(catalog),{type:'SAVE_MODEL',payload:{model:{...model,parameters}}},catalog),/密钥|认证|参数/)
 }
})
test('模型参数保留常用推理参数与结构化格式',()=>{
 const parameters={temperature:0.6,top_p:0.9,maxOutputTokens:4096,stop:['END'],response_format:{type:'json_object'}}
 const next=applyCommand(initialState(catalog),{type:'SAVE_MODEL',payload:{model:{...model,parameters}}},catalog)
 assert.deepEqual(next.models[0].parameters,parameters)
})
