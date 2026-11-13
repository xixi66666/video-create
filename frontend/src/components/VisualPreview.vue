<script setup lang="ts">
import {ref,watch} from 'vue'
const props=defineProps<{src:string;kind:'IMAGE'|'VIDEO';label:string;startMs?:number;endMs?:number}>()
const emit=defineEmits<{metadata:[durationMs:number]}>(),video=ref<HTMLVideoElement>(),failed=ref(false)
watch(()=>props.src,()=>{failed.value=false})
function metadata(){const v=video.value;if(!v)return;if(Number.isFinite(v.duration)&&v.duration>0)emit('metadata',Math.round(v.duration*1000));if(props.startMs!==undefined)v.currentTime=props.startMs/1000}
function play(){const v=video.value;if(v&&props.startMs!==undefined&&(v.currentTime<props.startMs/1000||(props.endMs!==undefined&&v.currentTime>=props.endMs/1000)))v.currentTime=props.startMs/1000}
function position(){const v=video.value;if(v&&props.endMs!==undefined&&v.currentTime>=props.endMs/1000){v.pause();v.currentTime=props.endMs/1000}}
</script>
<template><div class="visual-preview"><p v-if="failed||!src">{{failed?'暂时无法预览，可下载原件核对':'正在读取素材…'}}</p><img v-else-if="kind==='IMAGE'" :src="src" :alt="label" loading="lazy" @error="failed=true"><video v-else ref="video" :src="src" controls playsinline preload="metadata" :aria-label="label" @error="failed=true" @loadedmetadata="metadata" @play="play" @timeupdate="position"/></div></template>
<style scoped>.visual-preview{display:grid;place-items:center;background:#20242c;aspect-ratio:16/9;overflow:hidden;color:#f4f5f8;border-radius:8px}.visual-preview img,.visual-preview video{display:block;width:100%;height:100%;max-height:360px;object-fit:contain}.visual-preview p{padding:15px;text-align:center;font-size:13px;color:inherit}</style>
