<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import Icon from '../components/Icon.vue'

type Clip = {start:number;end:number}
type Voice = {id:string;name:string;version:string|null;selected:number|null;clips:Clip[];samples:{file:string}[]}
type Job = {id:string;role:string;status:'queued'|'running'|'done'|'failed';message:string}
type DubRun = {id:string;status:string;message:string;completed:number;audio?:string;lines:{speaker:string;text:string;audio?:string}[]}
const store = useWorkbench()
const route = useRoute()
const voices = ref<Voice[]>([])
const selectedId = ref('')
const loading = ref(true)
const error = ref('')
const job = ref<Job|null>(null)
const configured = ref(false)
const storage = ref<'local'|'mysql'>('local')
const source = ref('')
const file = ref<File|null>(null)
const roleId = ref('')
const roleName = ref('')
const renameId = ref('')
const renameName = ref('')
const renaming = ref(false)
const clean = ref(false)
const start = ref<number|null>(null)
const seconds = ref<number|null>(null)
const text = ref('夜色渐深，渡口最后一盏灯亮了。')
const style = ref('自然、舒展地朗读。')
const player = ref('')
const playerLabel = ref('')
const projectId = ref(typeof route.query.projectId === 'string' ? route.query.projectId : '')
const speaker = ref('旁白')
const dubScript = ref('')
const dubJob = ref<Job|null>(null)
const dubRuns = ref<DubRun[]>([])
const dubPlayer = ref('')
const dubPlayerLabel = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let dubTimer: ReturnType<typeof setTimeout> | undefined
let alive = true
const current = computed(() => voices.value.find(v => v.id === selectedId.value))
const project = computed(() => store.state.projects.find(p => p.id === projectId.value))
const busy = computed(() => job.value?.status === 'running' || job.value?.status === 'queued')
const dubBusy = computed(() => dubJob.value?.status === 'running' || dubJob.value?.status === 'queued')
const dialogue = computed(() => dubScript.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map(line => {
  const match = line.match(/^([^：:]{1,100})[：:]\s*(.+)$/)
  return {speaker:match ? match[1].trim() : '旁白', text:match ? match[2].trim() : line}
}))
const missingSpeakers = computed(() => [...new Set(dialogue.value.map(line => line.speaker))].filter(name => !project.value?.voiceCast?.some(v => v.speaker === name)))
const readyCount = computed(() => voices.value.filter(v => v.selected).length)

async function request(body: Record<string, unknown>) {
  const res = await fetch('/api/v1/speech/voice', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  const result = await res.json()
  if (!res.ok) throw new Error(result.message || '配音服务请求失败')
  return result.data
}
async function refresh() {
  try {
    const result = await request({action:'list'})
    voices.value = result.roles
    configured.value = result.mimoConfigured
    storage.value = result.storage === 'mysql' ? 'mysql' : 'local'
    if (!voices.value.some(v => v.id === selectedId.value)) selectedId.value = voices.value[0]?.id || ''
    error.value = ''
  } catch (e) { error.value = e instanceof Error ? e.message : '无法加载角色库' }
  finally { loading.value = false }
}
function beginRename(voice: Voice) {
  renameId.value = voice.id
  renameName.value = voice.name
  error.value = ''
}
async function saveRename() {
  const name = renameName.value.trim()
  if (!name || name.length > 100) { error.value = '角色名称须为 1–100 个字符'; return }
  renaming.value = true
  error.value = ''
  try {
    const result = await request({action:'rename',role:renameId.value,name})
    const role = voices.value.find(v => v.id === result.id)
    if (role) role.name = result.name
    if (selectedId.value === result.id) roleName.value = result.name
    renameId.value = ''
    store.toast('角色名称已更新')
  } catch (e) { error.value = e instanceof Error ? e.message : '修改名称失败' }
  finally { renaming.value = false }
}
async function poll(id:string) {
  try {
    job.value = await request({action:'job',id})
    if (job.value?.status === 'done') { selectedId.value = job.value.role; await refresh() }
    else if (job.value?.status === 'failed') error.value = job.value.message
    else if (alive) timer = setTimeout(() => poll(id), 1800)
  } catch (e) { job.value = null; error.value = e instanceof Error ? e.message : '任务状态不可用，请刷新后查看角色库' }
}
async function run(body:Record<string,unknown>) {
  error.value = ''
  try {
    job.value = await request(body)
    if (job.value) await poll(job.value.id)
  } catch (e) { error.value = e instanceof Error ? e.message : '任务启动失败' }
}
async function fileBase64(input:File):Promise<string> {
  return new Promise((resolve,reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.readAsDataURL(input)
  })
}
async function extract() {
  try {
    if (!roleId.value.match(/^[a-z][a-z0-9_]{2,31}$/)) throw new Error('角色 ID 需为 3–32 位小写字母、数字或下划线，且以字母开头')
    if (!file.value && !source.value.trim()) throw new Error('请输入链接或选择文件')
    if (file.value && file.value.size > 20*1024*1024) throw new Error('上传文件不能超过 20 MB')
    await run({action:'extract',role:roleId.value,source:source.value.trim(),fileBase64:file.value ? await fileBase64(file.value) : undefined,
      start:start.value === null || String(start.value) === '' ? undefined : Number(start.value), seconds:seconds.value === null || String(seconds.value) === '' ? undefined : Number(seconds.value), clean:clean.value})
  } catch (e) { error.value = e instanceof Error ? e.message : '素材读取失败' }
}
async function listen(kind:string,name:string|number,label:string) {
  if (!current.value) return
  try {
    const result = await request({action:'audio',role:current.value.id,kind,name})
    const bytes = Uint8Array.from(atob(result.audioBase64), c => c.charCodeAt(0))
    if (player.value) URL.revokeObjectURL(player.value)
    player.value = URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}))
    playerLabel.value = label
  } catch (e) { error.value = e instanceof Error ? e.message : '读取音频失败' }
}
async function cast() {
  const role = current.value
  if (!project.value || !role?.version || !speaker.value.trim()) { error.value = '请选择作品、角色并填写说话人'; return }
  const entry = {speaker:speaker.value.trim(),roleId:role.id,name:role.name,version:role.version}
  const cast = [...(project.value.voiceCast || []).filter(v => v.speaker !== entry.speaker),entry]
  await store.command({type:'SET_VOICE_CAST',payload:{projectId:project.value.id,cast}},'选角已保存到作品')
}
async function removeCast(name:string) {
  if (!project.value) return
  await store.command({type:'SET_VOICE_CAST',payload:{projectId:project.value.id,cast:(project.value.voiceCast||[]).filter(v=>v.speaker!==name)}},'选角已移除')
}
function loadProjectScript() {
  const node = project.value?.nodes.N23?.output || project.value?.nodes.N22?.output || ''
  let content = node
  try {
    const parsed = JSON.parse(node)
    if (typeof parsed.spokenScript === 'string') content = parsed.spokenScript
    else { error.value = '作品脚本是结构化数据，但没有可直接读取的 spokenScript，请手动粘贴台词。'; return }
  } catch { /* 普通文本脚本 */ }
  dubScript.value = content
}
async function refreshDubs() {
  if (!projectId.value) { dubRuns.value = []; return }
  try { const result = await request({action:'dub_list',projectId:projectId.value}); dubRuns.value = Array.isArray(result.runs) ? result.runs : [] }
  catch (e) { error.value = e instanceof Error ? e.message : '配音记录加载失败' }
}
async function pollDub(id:string) {
  try {
    dubJob.value = await request({action:'job',id})
    if (dubJob.value?.status === 'done' || dubJob.value?.status === 'failed') {
      if (dubJob.value.status === 'failed') error.value = dubJob.value.message
      await refreshDubs()
    } else if (alive) dubTimer = setTimeout(() => pollDub(id),1800)
  } catch (e) { error.value = e instanceof Error ? e.message : '配音任务状态不可用'; await refreshDubs() }
}
async function startDub() {
  if (!project.value || !dialogue.value.length || missingSpeakers.value.length) return
  error.value = ''
  try {
    dubJob.value = await request({action:'dub_start',projectId:project.value.id,lines:dialogue.value,cast:project.value.voiceCast || []})
    if (dubJob.value) await pollDub(dubJob.value.id)
  } catch (e) { error.value = e instanceof Error ? e.message : '配音任务启动失败' }
}
async function listenDub(run:DubRun, name:string, label:string) {
  try {
    const result = await request({action:'dub_audio',projectId:projectId.value,id:run.id,name})
    const bytes = Uint8Array.from(atob(result.audioBase64),c => c.charCodeAt(0))
    if (dubPlayer.value) URL.revokeObjectURL(dubPlayer.value)
    dubPlayer.value = URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}))
    dubPlayerLabel.value = label
  } catch (e) { error.value = e instanceof Error ? e.message : '音轨读取失败' }
}
watch(projectId, () => { dubScript.value = ''; dubJob.value = null; clearTimeout(dubTimer); void refreshDubs() })
function time(value:number) { return `${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}` }
onMounted(() => { void refresh(); void refreshDubs() })
onUnmounted(() => { alive=false; clearTimeout(timer); clearTimeout(dubTimer); if(player.value) URL.revokeObjectURL(player.value); if(dubPlayer.value) URL.revokeObjectURL(dubPlayer.value) })
</script>

<template>
  <div class="page-content voice-page">
    <header class="voice-heading">
      <div><p class="voice-kicker">声音资产 / 配音制作</p><h1>配音工作台</h1><p>收集喜欢的声音，为每一部作品找到合适的角色。</p></div>
      <div class="voice-count"><strong>{{ readyCount }}</strong><span>个可用角色<br><small>{{ storage === 'mysql' ? '保存在共享数据库' : '保存在本机角色库' }}</small></span></div>
    </header>
    <p v-if="error" class="voice-alert" role="alert">{{ error }} <button @click="error=''">关闭</button></p>
    <p v-if="job && (busy || job.status==='done')" class="voice-notice" role="status">{{ job.message }}<span v-if="busy"> · 处理较长素材可能需要几分钟</span></p>
    <div class="voice-layout">
      <aside class="voice-library">
        <div class="voice-section-head"><div><h2>我的声音角色</h2><p>选择角色查看参考音频</p></div><button class="voice-refresh" aria-label="刷新角色库" @click="refresh"><Icon name="RotateCcw" :size="16"/></button></div>
        <p v-if="loading" class="voice-empty">正在读取角色库…</p>
        <p v-else-if="!voices.length" class="voice-empty">还没有声音角色，使用右侧素材创建第一个角色。</p>
        <button v-for="v in voices" :key="v.id" :class="['voice-role', {active:selectedId===v.id}]" @click="selectedId=v.id;roleName=v.name">
          <span class="voice-role-mark"><Icon name="AudioLines" :size="20"/></span>
          <span class="voice-role-copy"><strong>{{ v.name }}</strong><small>{{ v.id }}</small></span>
          <span :class="['voice-role-state',{ready:v.selected}]">{{ v.selected ? '已定档' : '待选段' }}</span>
        </button>
      </aside>
      <div class="voice-main">
        <section v-if="current" class="voice-detail">
          <div class="voice-detail-head"><div><span class="voice-overline">当前声音</span>
            <template v-if="renameId===current.id">
              <form class="voice-rename" @submit.prevent="saveRename">
                <label class="voice-rename-label">角色名称<input v-model="renameName" maxlength="100" required :disabled="renaming" autofocus></label>
                <button class="btn primary" type="submit" :disabled="renaming">保存</button>
                <button class="btn" type="button" :disabled="renaming" @click="renameId=''">取消</button>
              </form>
            </template>
            <div v-else class="voice-title-row"><h2>{{ current.name }}</h2><button class="voice-link" type="button" @click="beginRename(current)">修改名称</button></div>
            <p>{{ current.id }} <span v-if="current.version">· 版本 {{ current.version }}</span></p></div><span class="voice-tag">{{ current.selected ? '可用于选角' : '选择参考片段' }}</span></div>
          <div class="voice-subhead"><h3>参考片段</h3><span>试听原声与分离人声</span></div>
          <div v-for="(clip,index) in current.clips" :key="index" class="voice-clip">
            <span class="voice-clip-time">{{ time(clip.start) }} – {{ time(clip.end) }}</span>
            <button class="voice-link" @click="listen('original',index+1,'原声')">听原声</button>
            <button class="voice-link" @click="listen('vocals',index+1,'分离人声')">听人声</button>
            <span v-if="current.selected===index+1" class="voice-selected">已选定</span>
            <button v-else-if="!current.selected" class="voice-link select" :disabled="busy || !roleName.trim()" @click="run({action:'select',role:current.id,number:index+1,name:roleName})">选为参考</button>
          </div>
          <label v-if="!current.selected" class="voice-label voice-name">角色名称<input v-model="roleName" placeholder="例如：温柔旁白"></label>
          <div v-if="current.samples.length" class="voice-samples"><h3>试听与作品</h3><button v-for="sample in current.samples" :key="sample.file" class="voice-sample" @click="listen('sample',sample.file,sample.file)"><Icon name="Play" :size="15"/><span>{{ sample.file }}</span></button></div>
          <div v-if="player" class="voice-player"><span>{{ playerLabel }}</span><audio :src="player" controls autoplay/></div>
        </section>
        <section class="voice-create">
          <div class="voice-section-head"><div><h2>添加声音角色</h2><p>粘贴音视频链接，或上传本地音频；系统会提取候选片段。</p></div><Icon name="Plus" :size="20"/></div>
          <div class="voice-form-grid">
            <label class="voice-label wide">视频或音频链接<input v-model="source" type="url" placeholder="粘贴视频、音频或开放声库链接" :disabled="!!file"></label>
            <label class="voice-label">角色 ID<input v-model="roleId" placeholder="例如 story_narrator"></label>
            <label class="voice-label">本地文件 <small>最大 20 MB</small><input type="file" accept="audio/*,video/*" @change="file=($event.target as HTMLInputElement).files?.[0] || null"></label>
            <label class="voice-label">起始时间（秒）<input v-model.number="start" type="number" min="0" placeholder="从头开始"></label>
            <label class="voice-label">处理时长（秒）<input v-model.number="seconds" type="number" min="10" placeholder="处理至结尾"></label>
          </div>
          <div class="voice-create-actions"><label class="voice-check"><input v-model="clean" type="checkbox">素材已是干声，跳过 BGM 分离</label><button class="btn primary" :disabled="busy" @click="extract"><Icon name="Sparkles" :size="16"/>提取声音</button></div>
        </section>
        <section class="voice-create">
          <div class="voice-section-head"><div><h2>用台词试听</h2><p>选择已定档的角色，调用 MiMo 生成语音。</p></div><span class="voice-tag">{{ configured ? 'MiMo 已配置' : 'MiMo 待配置' }}</span></div>
          <label class="voice-label">试听台词<textarea v-model="text" rows="3" placeholder="输入台词。长文请用空行分段，每段最多 40 个字符。"/></label>
          <label class="voice-label">语气与读法<input v-model="style" placeholder="例如：自然、平静地朗读"></label>
          <div class="voice-create-actions"><span class="voice-hint">生成时会发送参考音频和台词至 MiMo</span><button class="btn primary" :disabled="busy || !current?.selected || !text.trim()" @click="run({action:'speak',role:current?.id,text,style})"><Icon name="Play" :size="15"/>生成试听</button></div>
        </section>
        <section class="voice-create">
          <div class="voice-section-head"><div><h2>为作品选角</h2><p>将声音分配给作品中的旁白或角色。</p></div></div>
          <div class="voice-form-grid"><label class="voice-label">作品<select v-model="projectId"><option value="">选择作品</option><option v-for="p in store.state.projects" :key="p.id" :value="p.id">{{ p.title }}</option></select></label><label class="voice-label">说话人<input v-model="speaker" placeholder="例如：旁白"></label></div>
          <div class="voice-create-actions"><span class="voice-hint">{{ current?.selected ? '当前角色：'+current.name : '先选择已定档的声音角色' }}</span><button class="btn primary" :disabled="!project || !current?.selected || store.saving" @click="cast">保存选角</button></div>
          <div v-if="project?.voiceCast?.length" class="voice-cast-list"><div v-for="item in project.voiceCast" :key="item.speaker"><span><strong>{{ item.speaker }}</strong> · {{ voices.find(v => v.id === item.roleId)?.name ?? item.name }} <small>v{{ item.version }}</small></span><button class="voice-link" @click="removeCast(item.speaker)">移除</button></div></div>
        </section>
        <section class="voice-create" aria-labelledby="dub-heading">
          <div class="voice-section-head"><div><h2 id="dub-heading">作品自动配音</h2><p>按作品选角逐句生成配音，并保存完整音轨。</p></div></div>
          <p v-if="!project" class="voice-hint">请先在上方选择作品并为说话人保存选角。</p>
          <template v-else>
            <div class="voice-subhead"><h3>配音台词</h3><button type="button" class="voice-link" @click="loadProjectScript">读取作品脚本</button></div>
            <label class="voice-label">每行一句，格式为“说话人：台词”<textarea v-model="dubScript" rows="6" placeholder="旁白：夜色渐深。&#10;小明：我们出发吧。" :disabled="dubBusy"/></label>
            <p class="voice-hint">不写说话人时按“旁白”处理。请检查读取的文本；生成会调用 MiMo。</p>
            <p v-if="missingSpeakers.length" class="voice-alert" role="alert">尚未选角：{{ missingSpeakers.join('、') }}。请先在上方为这些说话人保存选角。</p>
            <div class="voice-create-actions"><span role="status" class="voice-hint">{{ dubJob?.message || `共 ${dialogue.length} 段台词` }}</span><button class="btn primary" :disabled="busy || dubBusy || !configured || !dialogue.length || !!missingSpeakers.length" @click="startDub">生成作品配音</button></div>
            <div v-if="dubRuns.length" class="voice-cast-list"><section v-for="run in dubRuns" :key="run.id"><div><span><strong>{{ run.status === 'done' ? '配音已生成' : run.status === 'failed' ? '生成失败' : run.status === 'interrupted' ? '任务已中断' : '处理中' }}</strong> · {{ run.completed }}/{{ run.lines.length }} 段 <small>{{ run.message }}</small></span><button v-if="run.audio" class="voice-link" @click="listenDub(run,run.audio,'完整配音')">试听完整音轨</button></div><details v-if="run.completed"><summary>查看已生成的台词</summary><div v-for="(line,index) in run.lines.filter(l=>l.audio)" :key="index"><span>{{ line.speaker }}：{{ line.text }}</span><button class="voice-link" @click="listenDub(run,line.audio!,`${line.speaker} 第 ${index+1} 段`)">试听</button></div></details></section></div>
            <div v-if="dubPlayer" class="voice-player"><span>{{ dubPlayerLabel }}</span><audio :src="dubPlayer" controls/><a :href="dubPlayer" download="作品配音.wav" class="voice-link">下载</a></div>
          </template>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.voice-page{max-width:1440px;margin:auto;padding-bottom:70px}.voice-heading{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:30px}.voice-heading h1{font-size:30px;letter-spacing:-.02em;margin:6px 0}.voice-heading p,.voice-section-head p{color:#667084;margin:0;line-height:1.6}.voice-heading .voice-kicker{color:#7164a7;font-size:12px;font-weight:700;letter-spacing:.08em}.voice-count{display:flex;align-items:center;gap:12px;color:#343b52;font-size:13px}.voice-count strong{font-size:32px;font-weight:600}.voice-count small{color:#798296}.voice-layout{display:grid;grid-template-columns:290px minmax(0,1fr);gap:24px;align-items:start}.voice-library,.voice-detail,.voice-create{background:white;border:1px solid #e4e7ef;border-radius:14px}.voice-library{padding:22px;position:sticky;top:20px}.voice-section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:20px}.voice-section-head h2{font-size:17px;margin:0 0 5px}.voice-section-head p{font-size:13px}.voice-refresh{border:0;background:transparent;color:#667084;cursor:pointer}.voice-role{border:1px solid transparent;width:100%;background:transparent;padding:12px 9px;display:flex;align-items:center;text-align:left;gap:10px;border-radius:10px;cursor:pointer}.voice-role:hover,.voice-role.active{background:#f5f3fb;border-color:#e6e1f3}.voice-role-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:10px;background:#e9e4f5;color:#605390;flex:none}.voice-role-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:3px}.voice-role-copy strong,.voice-role-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.voice-role-copy small,.voice-hint,.voice-empty{font-size:12px;color:#707a8d}.voice-role-state,.voice-tag{font-size:11px;color:#7769a0;background:#f1eef9;border-radius:20px;padding:4px 8px;white-space:nowrap}.voice-role-state.ready{color:#356b5a;background:#e9f5ef}.voice-main{display:grid;gap:20px;min-width:0}.voice-detail,.voice-create{padding:26px}.voice-detail-head{display:flex;justify-content:space-between;gap:16px;padding-bottom:21px;border-bottom:1px solid #edf0f5}.voice-detail-head h2{font-size:22px;margin:5px 0}.voice-detail-head p{margin:0;color:#7a8393;font-size:12px}.voice-overline{font-size:12px;color:#7769a0;font-weight:700}.voice-subhead{display:flex;justify-content:space-between;align-items:center;margin:20px 0 10px}.voice-subhead h3,.voice-samples h3{font-size:14px;margin:0}.voice-subhead span{font-size:12px;color:#7a8393}.voice-clip{display:flex;align-items:center;gap:18px;padding:12px 0;border-bottom:1px solid #f0f1f5}.voice-clip-time{font-variant-numeric:tabular-nums;font-size:13px;color:#454c5c;margin-right:auto}.voice-link{border:0;background:transparent;color:#5e518d;cursor:pointer;font-size:13px}.voice-link.select{font-weight:700}.voice-selected{font-size:12px;color:#38755f}.voice-samples{margin-top:22px}.voice-sample{display:inline-flex;align-items:center;gap:7px;margin:12px 8px 0 0;border:1px solid #e4e7ef;background:#fff;border-radius:8px;padding:8px 10px;color:#4b5264;cursor:pointer;max-width:100%}.voice-sample span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.voice-player{display:flex;align-items:center;gap:16px;margin-top:20px;background:#f6f7fb;border-radius:10px;padding:10px 14px;font-size:12px;color:#5c6578}.voice-player audio{width:100%;height:36px}.voice-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.voice-label{display:flex;flex-direction:column;gap:7px;font-size:13px;font-weight:600;color:#42495b;margin-bottom:14px}.voice-label.wide{grid-column:1/-1}.voice-label small{font-weight:400;color:#7a8393}.voice-label input,.voice-label textarea,.voice-label select{width:100%;border:1px solid #dce0ea;border-radius:8px;padding:10px 12px;background:#fff;color:#262d3d;font:inherit;font-weight:400}.voice-label textarea{resize:vertical}.voice-name{margin-top:18px}.voice-create-actions{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:10px}.voice-check{font-size:13px;color:#606a7d;display:flex;gap:8px;align-items:center}.voice-alert,.voice-notice{padding:12px 16px;border-radius:8px;margin-bottom:18px;font-size:13px}.voice-alert{background:#fff2f0;color:#9d3428}.voice-alert button{float:right;border:0;background:transparent;color:inherit;cursor:pointer}.voice-notice{background:#eef5f1;color:#36614c}.voice-cast-list{margin-top:18px;border-top:1px solid #edf0f5}.voice-cast-list div{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #edf0f5;font-size:13px}.voice-cast-list small{color:#838b9a}@media(max-width:850px){.voice-layout{grid-template-columns:1fr}.voice-library{position:static}.voice-heading{align-items:start}.voice-count{display:none}}@media(max-width:540px){.voice-detail,.voice-create{padding:18px}.voice-form-grid{grid-template-columns:1fr}.voice-label.wide{grid-column:auto}.voice-clip{gap:8px;flex-wrap:wrap}.voice-create-actions{align-items:stretch;flex-direction:column}.voice-player{align-items:stretch;flex-direction:column}}
.voice-detail-head > .voice-tag { align-self: flex-start; }
.voice-title-row { display:flex; align-items:center; gap:12px; }
.voice-rename { display:flex; align-items:end; flex-wrap:wrap; gap:8px; margin:8px 0; }
.voice-rename-label { display:flex; flex-direction:column; gap:5px; font-size:12px; color:#596376; }
.voice-rename-label input { width:min(280px, 100%); border:1px solid #dce0ea; border-radius:8px; padding:9px 12px; color:#262d3d; font:inherit; font-size:14px; }
</style>
