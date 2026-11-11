# 声音采集与 MiMo 朗诵

本文记录已跑通的链路：从视频或音频取得音轨，分离伴奏，试听并保存角色参考样本，再调用 MiMo 复刻生成新台词。脚本是独立命令行工具；配音工作台网页和自部署 IndexTTS 接入尚未完成。

## 用到的组件

| 组件 | 作用 | 本次使用 |
| --- | --- | --- |
| Python | 运行采集和合成脚本 | Windows x64，Python 3.11.9 |
| yt-dlp | 从支持的平台取得音视频链接中的音轨；本地文件无需下载 | 2026.10.26 |
| FFmpeg、FFprobe | 解码视频音轨、裁剪片段、转换成 WAV，并检查工具是否可用 | 8.1.1 |
| Demucs | 使用 `htdemucs` 的 `--two-stems=vocals` 分离人声和伴奏 | 4.1.0，首次运行需下载模型权重 |
| PyTorch | 为 Demucs 提供推理运行时 | 2.15.0，CPU |
| NumPy | 计算候选片段的帧能量、处理 PCM 和拼接音频 | 2.4.6 |
| MiMo API | 将参考 WAV 和文字发送给 `mimo-v2.5-tts-voiceclone`，返回 WAV | 小米云端接口，需自行配置密钥 |

Demucs 分离的是人声和伴奏，并不能识别或单独分离多位说话人；背景歌声也可能保留。候选排序只参考能量和静音位置，需人工试听确认人物、发音和残留 BGM。

## 安装

以下命令在仓库根目录、Windows PowerShell 执行。需要 Python 3.11、FFmpeg 和 FFprobe，并将 FFmpeg 的 `bin` 加入 PATH。检查命令：

```powershell
py -3.11 --version
ffmpeg -version
ffprobe -version
py -3.11 -m venv .venv-voice
.\.venv-voice\Scripts\python.exe -m pip install -r voicelib/requirements.txt
.\.venv-voice\Scripts\python.exe voicelib/voice.py doctor
```

模型权重和 Python 依赖需要联网下载。默认使用 CPU；有 NVIDIA CUDA 环境时，可以按 [PyTorch 官方安装指南](https://pytorch.org/get-started/locally/)安装与本机驱动兼容的 PyTorch，然后在提取命令中指定 `--device cuda`。当前清单以本机 CPU 验证版本为基准，其他系统和 GPU 环境需自行验证。

Linux/macOS 可用 `python3.11 -m venv .venv-voice` 创建环境，并把下面命令中的 Python 路径替换为 `.venv-voice/bin/python`。FFmpeg 安装方式由操作系统决定。

## 1. 从链接提取候选

角色 ID 为 3–32 位小写字母、数字或下划线，以字母开头。为避免覆盖，已有角色 ID 不能再次用于提取。

```powershell
.\.venv-voice\Scripts\python.exe voicelib/voice.py extract luoshen_demo 'https://www.bilibili.com/video/BV1uN4y1y7Fb/' --start 195 --seconds 40
```

这会从原视频第 195 秒起处理 40 秒。省略 `--start` 和 `--seconds` 可处理完整音轨，长音频使用 CPU 可能需要较长时间。亦可把链接替换为本地文件路径。已有清晰单人干声时，可加 `--clean` 跳过 Demucs。

脚本从音轨解码出 44.1 kHz 立体声 PCM，分离伴奏后，按帧能量、伴奏相对能量和停顿位置筛选最多三段 10–12 秒候选。结果写在 `.voice-data/luoshen_demo/`：

- `01-original.wav`、`01-vocals.wav` 等分别是原声和分离后的人声，时间范围一致。
- `manifest.json` 保存来源、候选在原音频中的秒数和参考 WAV 的 SHA-1 指纹。链接的查询参数不保存，平台媒体 ID 单独保存。
- 默认数据目录 `.voice-data/` 已被 Git 忽略。设置环境变量 `VOICELIB_HOME` 可以把整个角色库放到其他目录；换机器需自行复制该目录。

依次试听原声和人声，确认目标说话人、背景音与词句是否完整，然后选定编号：

```powershell
.\.venv-voice\Scripts\python.exe voicelib/voice.py select luoshen_demo 1 --name '洛神赋朗诵'
```

命令生成 `character.json`，记录角色 ID、名称、版本、候选文件和指纹。当前命令行版本支持首次定档及重复选择同一候选；要试用另一个样本，请新建一个采集角色目录。

## 2. MiMo 试音与朗诵

在当前 PowerShell 会话设置自己的 `MIMO_API_KEY`。使用前在本机交互输入，避免把密钥写到项目或命令历史：

```powershell
$env:MIMO_API_KEY = Read-Host 'MiMo API Key'
.\.venv-voice\Scripts\python.exe voicelib/voice.py speak luoshen_demo --text '夜色渐深，渡口最后一盏灯亮了。' --out '.voice-data/luoshen_demo/试听.wav'
```

每次新的合成会将选定参考音频和文字发送给小米，具体费用和账号权限以供应商为准。脚本验证音频指纹和返回 WAV。输出文件已存在时需换名，避免覆盖。

长文使用 UTF-8 文本文件，以**空行**分隔合成块，每块最多 40 个非空白字符，建议按句子自然停顿分段：

```text
春江潮水连海平，海上明月共潮生。
滟滟随波千万里，何处春江无月明？

江流宛转绕芳甸，月照花林皆似霰。
空里流霜不觉飞，汀上白沙看不见。
```

```powershell
.\.venv-voice\Scripts\python.exe voicelib/voice.py speak luoshen_demo --text-file '.\poem.txt' --style '平静舒展地朗诵，保持参考音色。' --out '.voice-data/luoshen_demo/朗诵.wav'
```

脚本顺序请求各段，修整段落首尾留白，段间加入 0.35 秒停顿，所有段成功后才写出合并 WAV。成功段缓存于角色目录 `takes/`，缓存键包含参考音频、文字、语气和模型；重跑同一任务可复用这些段落。失败请求不会自动重试，也不会用静音代替失败段。输出尚未经过配音规范中的混音和交付验收。

## 排查

- **找不到 FFmpeg**：重新打开终端，确认 `ffmpeg -version`、`ffprobe -version` 正常。
- **链接下载失败**：先在浏览器确认链接可访问；平台登录、地区或反爬限制会影响 yt-dlp。也可将合法取得的本地音视频路径作为输入。
- **Demucs 权重下载失败**：检查目标机器访问模型下载服务的网络。允许使用自己的代理或镜像配置，重试原命令。分离失败时不会把混音当成已分离人声入库。
- **候选为空、说话人不对或 BGM 残留**：更换 `--start` / `--seconds` 范围或素材，人工试听确认。能量排序不具备说话人识别能力。
- **MiMo 401/403 或 429**：检查密钥、模型权限、余额或限流；不会自动重试。

## 本次实际验证

素材为 B 站 `BV1uN4y1y7Fb`《洛神赋》朗诵。本机先用 yt-dlp 获取音轨，再用 FFmpeg 和 CPU 版 Demucs 分离并生成候选；选用原片 206.9–218.9 秒的 12 秒人声作为参考。MiMo 成功生成「夜色渐深，渡口最后一盏灯亮了」和分段版《春江花月夜》。合成前试听确认了角色效果。

## 资料

- [Demucs 项目与使用说明](https://github.com/adefossez/demucs)
- [yt-dlp 项目](https://github.com/yt-dlp/yt-dlp)
- [MiMo 语音合成接口](https://mimo.mi.com/docs/zh-CN/api/audio/tts-post)
- [项目配音规范](SPEC.md)
