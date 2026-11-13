# 本地媒体只读探测

`inspect_local_media` 在管理员显式开启受控本地媒体工具时可用。它先按既有规则读取受控目录中的单个普通文件，计算 SHA-256，再将读取到的字节经标准输入交给本机 `ffprobe`，返回容器格式、时长、码率及音视频流的可用字段（包括分辨率、帧率、编码、采样率和声道）。JPEG、WebP、MP4、WebM 等格式是否能探测取决于安装的 FFmpeg 构建和具体文件；对于无法从标准输入读取的文件会返回错误。返回的帧率为 ffprobe 的有理数文本，缺失字段保持缺失，不推断数据。

调用时可选 `include_loudness: true`：由 `ffmpeg` 的 loudnorm 滤镜分析**第一条音轨、最多前 120 秒**，给出综合响度 LUFS、真峰值 dBTP 和响度范围 LU。该结果不是超过 120 秒的整段响度，极短、无声、无音轨或不支持的素材可能无法产生有限测量值。文件截断、音质、噪声、音画同步、画面一致性、文字可读性和内容正确性仍须另外检测或人工审查；元数据与上述信号测量不等于成片验收。不能播放、剪辑、渲染或发布。

## 配置

管理员使用可信来源安装同时包含 `ffprobe` 和 `ffmpeg` 的构建。可从 [FFmpeg 官方下载页面](https://ffmpeg.org/download.html) 选择其链接的 Windows 构建；校验发行方提供的哈希并遵守其许可。将其置于受控目录，在启动真实运行服务的进程环境中设置：

```powershell
$env:CREATOR_LOCAL_MEDIA_ENABLED = 'true'
$env:CREATOR_LOCAL_MEDIA_ROOT = 'D:\受控素材目录'
$env:CREATOR_FFPROBE_PATH = 'D:\受信任工具目录\ffprobe.exe'
$env:CREATOR_FFMPEG_PATH = 'D:\受信任工具目录\ffmpeg.exe'
```

后两项可省略，此时优先读取本项目 `agent-runtime/data/media-tools/` 内的可执行文件，其次从启动进程的 `PATH` 解析；显式路径不合法时不会回退。工具只会注册给允许使用本地素材的角色，且仅在 LIVE 和运行快照允许时可用；默认关闭，FIXTURE 不访问主机文件。配置并启动不会改变 `domainVerified`。

若没有 ffprobe，WAV 和 PNG 仍可读取原有的文件头，其余格式会明确提示缺少工具。测响度需要 ffmpeg；失败会返回错误，不会生成测量值。单文件限 64 MiB，仅允许受控目录中的平铺普通文件，拒绝路径、链接、重解析点及硬链接；检查文件句柄和读取期间的变化。子进程接收内存中的文件内容，通过 `pipe` 协议读取，禁止使用其他 FFmpeg 协议访问本地路径和网络；单次进程限时 30 秒，输出限 2 MiB，超出即停止。受控目录和 FFmpeg 可执行文件需由管理员管理，不能允许不可信用户改写。媒体解析器处理不可信文件仍有安全风险，生产环境应配合独立低权限进程、系统资源限制和及时更新 FFmpeg。

## 测试

```powershell
cd agent-runtime
.\.venv\Scripts\python.exe -m pytest tests/test_local_media_tools.py -q
```

若工具可用，测试会生成无版权的合成音视频并校验真实元数据和响度；否则该真实工具测试会跳过，并保留无工具降级和输入限制测试。
