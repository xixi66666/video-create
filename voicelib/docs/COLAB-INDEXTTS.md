# 走 Colab 跑 IndexTTS-2.5

> 唯一一条"免费 + 真的是 IndexTTS-2.5"的路:GitHub Actions 拉起免费 Colab T4,
> 跑完把 wav 发成 Release。本文件是你需要做的全部前置。

## 0. 前置(缺一不可)

| 条件 | 为什么 |
|---|---|
| 能访问 Google | `gcloud` 授权要开浏览器登录,以及 Colab API |
| GitHub 账号 | 存放 fork、跑 Actions、接收 issue |
| 免费 Colab 额度 | 每次跑消耗一个 T4 会话 |

---

## 1. Fork 仓库

打开 <https://github.com/htlin222/index-tts-in-colab> → **Fork**(公开仓库即可)。

记下你的仓库路径,形如 `你的用户名/index-tts-in-colab`。

---

## 2. 装 gcloud 并生成凭据(最麻烦的一步)

<https://cloud.google.com/sdk/docs/install>

```bash
gcloud auth application-default login \
  --scopes=openid,https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/colaboratory
```

生成的 JSON 默认在:

```
Windows   %APPDATA%\gcloud\application_default_credentials.json
macOS/Linux  ~/.config/gcloud/application_default_credentials.json
```

### 存进 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret

| Name | Value |
|---|---|
| `COLAB_ADC_CREDENTIALS` | 上面那个 JSON 的**全部内容** |

命令行等价:

```powershell
gh secret set COLAB_ADC_CREDENTIALS --repo 你的用户名/index-tts-in-colab < $env:APPDATA\gcloud\application_default_credentials.json
```

> ⚠️ 这把凭据 scope 含 `cloud-platform`,范围不小。**别给这个仓库加协作者**,别接受来路不明的 PR。

---

## 3. 配 HF_TOKEN(强烈建议)

不配的话,模型下载可能卡 20 分钟以上(匿名请求被限速)。

1. <https://huggingface.co/settings/tokens> 建一个 **read** 权限 token
2. 存成 secret:`HF_TOKEN`

```powershell
gh secret set HF_TOKEN --repo 你的用户名/index-tts-in-colab
```

---

## 4. 换成你的角色参考音频

仓库里的 `assets/ref_voice.wav` 是作者自带的 7 秒样本。**必须换**,否则克隆出来是别人的声音。

```powershell
# 用我们声库里已经合格的片段(10–14 秒、44.1kHz、单声道、无混响)
Copy-Item D:\Code\video\voicelib\characters\<角色id>\refs\calm.wav `
          D:\Code\video\index-tts-in-colab\assets\ref_voice.wav -Force
```

然后 commit + push。之后**每次合成都会用这个音色**——这个仓库的设计是"一个仓库一个音色"。

> 想多角色?fork 多份,或者每次改文件。它的 v1 不支持按 issue 传参考音频。

---

## 5. 用起来

### 方式 A:命令行(推荐,一键)

```powershell
$env:GH_TOKEN = "ghp_xxx"     # 需要 repo 权限

D:\venvs\voicelib\Scripts\python.exe D:\Code\video\voicelib\console\colab_tts.py `
  --repo 你的用户名/index-tts-in-colab `
  --text "她握着刀，指节发白。\n别出声……它还在上面。" `
  --emotion 悲傷 --weight 0.8 --model 2.5 `
  --out D:\Code\video\out\line.wav
```

它会:建 issue → 轮询 → 下载 wav → 落盘。首次约 15–20 分钟,之后每句加几分钟。

**先看会提交什么(不真发):**

```powershell
... --dry-run
```

### 方式 B:网页手点

仓库 → Issues → New issue → 选「🎙️ 語音合成請求」→ 填表 → 提交。

---

## 情绪与参数

| 情绪 | 说明 |
|---|---|
| 自然 / 高興 / 憤怒 / 悲傷 / 低落 / 驚訝 | 6 个预设,写死在 `scripts/parse_issue.py` |
| 强度 0.1–1.0 | 默认 0.85;过高会让音色失真 |

**2.0 vs 2.5**:2.5 更快、支持语速控制,但会把中文往**标准普通话**拉;2.0 没有语言 token,保留参考音频原始腔调。
如果你的角色带口音,**先试 2.0**。

---

## 已知限制

| 限制 | 说明 |
|---|---|
| 一次只能跑一个 | Colab 免费账号限制;浏览器里开着 Colab 会占用导致失败 |
| 每次全新 VM | 6GB 模型重下,15 分钟打底,无缓存 |
| 一个仓库一个音色 | 参考音频写死在仓库里 |
| 每行 ≤200 字、总 ≤6000 字 | 超了直接失败,不静默截断 |
| 情绪整段统一 | 不支持每行不同情绪 |
| 输出是干声 | 没有混音,需自己接 `postprocess.yaml` |

---

## 故障排查

| 症状 | 原因 |
|---|---|
| `TooManyAssignmentsError` | 有别的 Colab 会话占着 T4,去 colab.research.google.com 断开 |
| workflow 显示绿但没产物 | 作者踩过:`colab exec` 不检查远端失败。看 step 日志里有没有 `FATAL:` |
| 模型下载卡住 | 没配 `HF_TOKEN` |
| `unrecognized emotion` | 情绪字样被改过,必须含「自然/高興/憤怒/悲傷/低落/驚訝」之一 |
| 声音不对 | 忘了换 `assets/ref_voice.wav` |

---

## 与 voicelib 的关系

这条路**绕开了本地部署**,但产出仍是干声。要进 `voicelib`:

1. 把 wav 存成 `characters/<id>/refs/calm.wav`(如果用作参考)
2. 或当作"已合成台词",进 manifest / 字幕轴(尚未实现)
3. 记得:采集来的音色仍受授权约束,只能 `draft`
