# Windows 原生部署 IndexTTS-2.5

> 决策日期 2026-11-10 · 对应 SPEC v0.2.1 §8
> 目标:一个能出声、能量时长、能批量跑的本地服务。**够用优先,不追求完美。**

## 0. 为什么可以不上 WSL / Docker

IndexTTS 在 Windows 上的唯一硬依赖是 `pynini`(文本归一化),但:

- 我们的 **SPEC L1-03 本来就要求把数字、单位写成汉字**
- 缺归一化时模型**仍能跑**,只是数字读得差([出处](https://pypi.org/project/indextts25-inference/0.1.1/))

也就是说:**归一化在脚本层已经做掉了,不是阻塞项。**

所以主方案是「Windows 原生 + 预归一化」,WSL2 只在原生装不上时兜底。

---

## 1. 前置检查

| 项 | 要求 | 检查 |
|---|---|---|
| GPU 显存 | ≥ 8 GB(峰值实测约 6 GB,fp16 约 4.3 GB) | `nvidia-smi` |
| 驱动 | ≥ 550(CUDA 12.x) | `nvidia-smi` 右上角 |
| 磁盘 | ≥ 20 GB(权重 ~6.5 GB + 环境 ~4.5 GB) | — |
| Python | 3.10 – 3.13 | `python --version` |

```powershell
nvidia-smi
python --version
```

> 显存 6 GB 是**峰值**,8 GB 卡能跑但别同时开别的 GPU 任务。

---

## 2. 装环境

独立 venv,不要污染全局。**路径用 ASCII**,避开空格与中文(SPEC §8.5)。

```powershell
mkdir D:\videotools\indextts -Force
cd D:\videotools\indextts
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

装 Torch(CUDA 版本按你的驱动选,cu128 适用于驱动 ≥ 550):

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

装推理库 + 服务依赖:

```powershell
pip install indextts25-inference fastapi uvicorn soundfile
```

> 用的是 `indextts25-inference`(纯 Python 轮子),**不是**上游仓库的 `uv sync` 路线——
> 后者绑了一堆 macOS 假设,sdpa 后端也不需要 `flash-attn`(Windows 上没有预编译轮子)。

---

## 3. 下权重(约 6.5 GB)

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
hf download IndexTeam/IndexTTS-2.5 --local-dir checkpoints --exclude "qwen0bemo4-merge/*"
```

**断点续传**:中断后重跑同一条命令即可。若镜像也慢,用 ModelScope:

```powershell
git clone https://www.modelscope.cn/models/IndexTeam/IndexTTS-2.5.git checkpoints
```

> `qwen0bemo4-merge/` 是自然语言情感模块,我们用不上(我们用 emotion 参数 + 预设表),省 1.2 GB。

---

## 4. 文本归一化:两条路

### 路线 A(主方案,零依赖):预归一化

在送进 TTS **之前**把数字、时间、单位改成汉字。这和 SPEC L1-03 是同一件事,不额外增加负担。

```python
import re
_DIGIT = {c: d for c, d in zip("0123456789", "零一二三四五六七八九")}

def normalize_zh(text: str) -> str:
    """把阿拉伯数字逐位转汉字。整段数字按位读,避免'十二'与'一二'混淆时再细化。"""
    return re.sub(r"\d", lambda m: _DIGIT[m.group()], text)
```

> 逐位替换是**保守策略**:「2026」读作「二零二六」,「第3集」读作「第三集」也成立。
> 需要「十五」这类读法时,再按场景加规则(日期、金额、序号各一套)。

### 路线 B(可选,有失败风险):conda 装 pynini

```powershell
conda install -c conda-forge pynini=2.1.5
pip install WeTextProcessing
```

⚠️ win-64 wheel 不保证存在。**装不上就走路线 A,不要卡在这里**——这是本方案唯一可能失败的点,而已有兜底。

---

## 5. 最小服务

`server.py`,放在 `D:\videotools\indextts\`:

```python
import os, uuid
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from indextts25 import IndexTTS25

MODEL_DIR = os.environ.get("INDEXTTS_MODEL_DIR", r"D:\videotools\indextts\checkpoints")
OUT_DIR = os.environ.get("INDEXTTS_OUT_DIR", r"D:\videotools\indextts\out")
os.makedirs(OUT_DIR, exist_ok=True)

tts = IndexTTS25(model_dir=MODEL_DIR, attn_backend="sdpa")
app = FastAPI()


class Req(BaseModel):
    text: str
    ref: str                 # 参考音频绝对路径,10-14 秒
    rate: float = 1.0        # 库内语义:>1 更快(SPEC §1.3)
    lang: str = "ZH"


@app.get("/health")
def health():
    return {"ok": True, "model": "IndexTTS-2.5", "backend": "sdpa"}


@app.post("/synthesize")
def synthesize(r: Req):
    out = os.path.join(OUT_DIR, uuid.uuid4().hex + ".wav")
    provider_speed = 1.0 / r.rate          # 供应商 <1 更快 → 必须取倒数
    tts.synthesize(r.text, voice=r.ref, out=out, speed=provider_speed, lang=r.lang)
    return {"path": out, "rate": r.rate, "provider_speed": provider_speed}


if __name__ == "__main__":
    # 单 worker:该模型非线程安全(SPEC L3-05)
    uvicorn.run(app, host="127.0.0.1", port=8766, workers=1)
```

启动:

```powershell
$env:INDEXTTS_MODEL_DIR = "D:\videotools\indextts\checkpoints"
python server.py
```

> **只监听 127.0.0.1、无鉴权**,不要暴露到公网。
> 首次启动要加载模型 + 建 CUDA 上下文,1–3 分钟属正常。

---

## 6. 冒烟测试(五项,必须全过)

准备一条 **10–14 秒、无 BGM 无混响**的中文干声。

| # | 测什么 | 怎么测 | 通过标准 |
|---|---|---|---|
| 1 | 能出声 | POST 一句短句 | 2 分钟内返回 wav |
| 2 | 音色像 | 同一句用参考音频克隆 | 能听出是同一个人 |
| 3 | 采样率 | `ffprobe` 输出 | **22050 Hz**,无损 |
| 4 | 中文正确 | 一句含数字 + 多音字 | 「第3集」读第三集;多音字不错 |
| 5 | 速度与稳定性 | 单句计时,同句跑 3 条 | 算出 RTF;3 条有明显差异(说明需要 3-take) |

```powershell
# 计时
Measure-Command { curl.exe -s -X POST http://127.0.0.1:8766/synthesize `
  -H "Content-Type: application/json" `
  -d '{\"text\":\"雨夜,她以妖刀斩尽恶影。\",\"ref\":\"D:\\\\voices\\\\ref.wav\",\"rate\":0.95}' }
```

```powershell
# 采样率
ffprobe -v error -show_entries stream=sample_rate,channels,codec_name -of default=nw=1 out.wav
```

### 记录模板

跑完把这张表填了,后面定阈值全靠它:

```
参考音频: ____ 秒, 来源: ____
单句字数: ____  耗时: ____ 秒  → RTF = 耗时 / 音频时长 ≈ ____
显存峰值: ____ GB
采样率: ____ Hz
读音问题: ____
3-take 差异: 明显 / 一般 / 几乎相同
```

---

## 7. 常见故障

| 症状 | 原因 | 处理 |
|---|---|---|
| `CUDA out of memory` | 显存不足或碎片 | 关掉其它 GPU 程序;设 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` |
| 中文数字读错 | 没做归一化 | 走路线 A,或装 pynini |
| 控制台中文乱码 | 编码不是 UTF-8 | `chcp 65001`、`$env:PYTHONUTF8=1` |
| 路径报错 | 含空格/中文/盘符冒号 | 移到 `D:\videotools\` 这类纯 ASCII 路径 |
| 首次调用超时 | 冷启动加载模型 | 先 `/health`,再预热一次 |
| 并发请求卡死 | 模型非线程安全 | 保持 `workers=1`,请求排队 |
| 装 `flash-attn` 失败 | Windows 无预编译轮子 | **不要装**,用 `sdpa` |

---

## 8. 与 SPEC 的对应

| 本手册操作 | 对应规则 |
|---|---|
| 独立 venv + ASCII 路径 | §8.5 路径与编码 |
| `speed = 1/rate` | §1.3 库内语义,适配器转换 |
| `workers=1` | L3-05 非线程安全必须串行 |
| 服务端点走环境变量 | L3-07 机器属性不进库 |
| 用完即关 | L3-08 服务按需启停 |
| 22400→48k 升采样 | L4-07 |
| 冒烟测试 5 项 | L0-05 / L2-06 / L3-01 |
