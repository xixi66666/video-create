<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useWorkbench } from '../stores/workbench'

const store = useWorkbench()
const input = ref('你好，欢迎使用 MiMo 语音合成。')
const voice = ref('苏打')
const projectId = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const audioUrl = ref('')
const generatedVoice = ref('')
let audioBlob: Blob | null = null

function clearAudio() {
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
  audioUrl.value = ''
  audioBlob = null
}
onBeforeUnmount(clearAudio)

async function generate() {
  if (loading.value || !input.value.trim()) return
  error.value = ''
  clearAudio()
  loading.value = true
  try {
    // 每次点击只提交一次请求；超时后由用户决定是否再次尝试。
    const response = await fetch('/api/v1/speech/mimo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: input.value.trim(), voice: voice.value }),
      signal: AbortSignal.timeout(120000),
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.message || '语音生成失败，请查看服务状态。')
    const encoded = result.data?.audioBase64
    if (typeof encoded !== 'string' || result.data?.format !== 'wav') throw new Error('供应商未返回有效的 WAV 音频。')
    const decoded = atob(encoded)
    const bytes = Uint8Array.from(decoded, char => char.charCodeAt(0))
    if (!bytes.length) throw new Error('供应商返回的音频为空。')
    audioBlob = new Blob([bytes], { type: 'audio/wav' })
    generatedVoice.value = voice.value
    audioUrl.value = URL.createObjectURL(audioBlob)
  } catch (e) {
    error.value = e instanceof DOMException && e.name === 'TimeoutError'
      ? '请求超时，供应商是否已处理未知；未自动重试，请核对后再试。'
      : e instanceof TypeError ? '连接中断，供应商是否已处理未知；未自动重试，请核对后再试。'
      : e instanceof Error ? e.message : '语音生成失败。'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!audioBlob || saving.value) return
  saving.value = true
  try {
    const file = new File([audioBlob], `MiMo-${generatedVoice.value}-${Date.now()}.wav`, { type: 'audio/wav' })
    await store.addAsset(file, projectId.value, `MiMo TTS 生成（${generatedVoice.value}）`)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="mimo-panel" aria-labelledby="mimo-title">
    <div>
      <h2 id="mimo-title">MiMo 语音试听</h2>
      <p>点击生成将调用真实 MiMo 语音服务。限时免费与实际计费以供应商当前规则为准；不会自动重试。</p>
    </div>
    <label>试听文本<textarea v-model="input" maxlength="500" rows="3" placeholder="输入要合成的短句" :disabled="loading"/></label>
    <div class="mimo-controls">
      <label>音色<select v-model="voice" :disabled="loading"><option v-for="name in ['苏打','冰糖','茉莉','白桦']" :key="name" :value="name">{{ name }}</option></select></label>
      <button class="btn primary" :disabled="loading || !input.trim()" @click="generate">{{ loading ? '正在生成…' : '生成语音' }}</button>
    </div>
    <p v-if="error" class="mimo-error" role="alert">{{ error }}</p>
    <div v-if="audioUrl" class="mimo-result">
      <audio :src="audioUrl" controls aria-label="试听生成的语音"/>
      <label>关联作品<select v-model="projectId"><option value="">不关联</option><option v-for="project in store.actualProjects" :key="project.id" :value="project.id">{{ project.title }}</option></select></label>
      <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存到素材库' }}</button>
    </div>
  </section>
</template>

<style scoped>
.mimo-panel{margin:28px 0;padding:22px;border:1px solid var(--border,#e7e7e7);border-radius:14px;background:var(--surface,#fff);display:grid;gap:14px}
.mimo-panel h2{margin:0 0 6px;font-size:19px}.mimo-panel p{margin:0;color:#626a76;font-size:13px;line-height:1.6}
.mimo-panel label{display:grid;gap:6px;font-size:13px;font-weight:600}.mimo-panel textarea,.mimo-panel select{padding:10px;border:1px solid #d6dbe1;border-radius:8px;background:#fff;font:inherit;color:inherit}.mimo-panel textarea{width:100%;resize:vertical}
.mimo-controls,.mimo-result{display:flex;align-items:end;gap:12px;flex-wrap:wrap}.mimo-result audio{max-width:100%}.mimo-panel .mimo-error{color:#b42318}
</style>
