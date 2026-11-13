import policy from '../data/model-parameter-policy.json' with {type:'json'}

const allowed=new Set(policy.allowedTopLevelKeys)
const sensitiveKey=new RegExp(policy.sensitiveKeyPattern,'i')
const sensitiveValue=new RegExp(policy.sensitiveValuePattern,'i')

/** 配置参数只允许推理选项；凭据必须通过环境变量引用。规则由 specs 同步到两端。 */
export function validateModelParameters(value:unknown):void {
 assertNoCredentials(value)
 if(Object.keys(value as object).some(key=>!allowed.has(key)))throw new Error('参数包含尚未支持的选项，请只使用已支持的推理参数')
}
/** 视频生成参数存档可包含供应商选项，但始终拒绝凭据。 */
export function assertNoCredentials(value:unknown):void {
 if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('参数必须为 JSON 对象')
 const scan=(item:unknown):boolean=>{
  if(typeof item==='string')return sensitiveValue.test(item)
  if(Array.isArray(item))return item.some(scan)
  if(item&&typeof item==='object')return Object.entries(item).some(([key,child])=>sensitiveKey.test(key)||scan(child))
  return false
 }
 if(scan(value))throw new Error('参数中不能保存密钥、密码或认证头，请使用环境变量引用')
}
