export interface ComfyTemplate {id:string;name:string;ready:boolean;message?:string}
export interface ComfyReadiness {online:boolean;enabled:boolean;message?:string;templates:ComfyTemplate[]}
export interface ComfyRun {id:string;projectId:string;nodeId:string;templateId:string;state:string;promptId?:string;createdAt:string;message?:string;fileRef?:string;sha256?:string;size?:number;adopted?:boolean}
export class ComfyApiError extends Error {constructor(message:string,readonly status:number){super(message)}}

export async function comfyApi<T>(path='',body?:object):Promise<T>{
 const response=await fetch('/api/v1/comfy-runs'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(12000)})
 const result=await response.json();if(!response.ok)throw new ComfyApiError(result.message??'ComfyUI 请求失败',response.status);return result.data
}
