<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useWorkbench} from '../stores/workbench'
const props=defineProps<{projectId:string;nodeId:string}>(),store=useWorkbench(),selected=ref<string[]>([])
const w=computed(()=>store.state.projects.find(p=>p.id===props.projectId)?.visualWorkbench),placements=computed(()=>w.value?.placements.filter(p=>p.active&&p.purpose==='TIMELINE'&&w.value?.needs.find(n=>n.id===p.needId)?.productionNodeId)??[])
const used=computed(()=>w.value?.uses.find(u=>u.nodeId===props.nodeId)?.placementIds??[]),stale=computed(()=>used.value.some(id=>!placements.value.some(p=>p.id===id)))
watch([()=>props.nodeId,()=>props.projectId,()=>used.value.join('|')],()=>{selected.value=used.value.filter(id=>placements.value.some(p=>p.id===id))},{immediate:true})
async function save(){await store.command({type:'USE_VISUAL_PLAN',payload:{projectId:props.projectId,nodeId:props.nodeId,placementIds:selected.value}},'已记录本步骤实际使用的画面；核对后单独完成剪辑产物')}
</script>
<template><section class="visual-handoff"><h3>制作画面交接</h3><p>勾选本次剪辑实际使用的画面。之后这些采用变化时，本步骤及其实际下游需复查。</p><p v-if="stale" role="status">之前使用的画面已被替换或撤销，请重新选择。</p><label v-for="p in placements" :key="p.id" class="checkbox-label"><input v-model="selected" type="checkbox" :value="p.id">{{w?.needs.find(n=>n.id===p.needId)?.title}} · {{p.trackId}} · {{(p.targetStartMs??0)/1000}}–{{(p.targetEndMs??0)/1000}} 秒</label><p v-if="!placements.length">主体内容或辅助画面尚未提供成片采用。</p><button class="btn" :disabled="store.saving||!selected.length" @click="save">使用所选画面</button><RouterLink :to="{path:'/candidates',query:{projectId}}" class="text-link">查看制作素材</RouterLink></section></template>
<style scoped>.visual-handoff{padding:20px 0;border-top:1px solid var(--line);margin-top:20px}.visual-handoff h3{font-size:16px}.visual-handoff p{font-size:13px;color:#555d6c;line-height:1.7}.visual-handoff label{font-size:13px;margin:12px 0}.visual-handoff .text-link{margin-left:15px}</style>
