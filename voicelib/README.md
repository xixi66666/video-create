# voicelib — 配音配置资产库

配音线的**唯一真相源**。项目不复制这里的任何东西,只引用 `character_id`。

> **本地操作台**:双击 `voicelib\console\start.cmd`(或 `.\start.ps1`)→ <http://127.0.0.1:8767>
> 默认「采集」页:贴视频链接 → 自动截人声 → 生成角色。另有「角色库」页做手工编辑。
> 已装好 yt-dlp + demucs + torch(在 `D:\venvs\voicelib`,因为 C 盘只剩 3.6 GB)。详见 [docs/HARVEST.md](docs/HARVEST.md)。

- 规范正文:[SPEC.md](SPEC.md) — **v0.2.1**
- **模块契约**:[module/CONTRACT.md](module/CONTRACT.md) · 集成点:[module/INTEGRATION.md](module/INTEGRATION.md) · 错误码:[module/errors.yaml](module/errors.yaml)
- **规则总表(机器可读)**:[rules.yaml](rules.yaml)
- **模板**:[templates/](templates/) · 交付单:[docs/DELIVERY-CHECKLIST.md](docs/DELIVERY-CHECKLIST.md)
- 外部实践吸收清单:[docs/EXTERNAL-PRACTICES.md](docs/EXTERNAL-PRACTICES.md)
- Windows 部署与冒烟测试:[docs/WINDOWS-INDEXTTS-SETUP.md](docs/WINDOWS-INDEXTTS-SETUP.md)
- **TTS API 接入(试听/克隆)**:[docs/TTS-API.md](docs/TTS-API.md)
- **走 Colab 跑 IndexTTS-2.5**:[docs/COLAB-INDEXTTS.md](docs/COLAB-INDEXTTS.md)
- 人读目录:[catalog.md](catalog.md)
- 机器索引:[registry.json](registry.json)

## 目录

```
voicelib/
├── SPEC.md                  # 七层规范(v0.2.1)
├── rules.yaml               # 53 条规则,机器可读
├── console/                 # 本地操作台
│   ├── start.cmd / start.ps1  # 启动(自动选 venv)
│   ├── server.py            # HTTP 服务 + 录入 API
│   ├── harvest.py           # 采集流水线:下载→分离→切段→打分
│   ├── synth.py             # TTS API 适配器(试听/克隆)
│   ├── colab_tts.py         # Colab IndexTTS-2.5 客户端(提交 issue → 取 wav)
│   ├── probe_tts.py         # 端点连通性判定器
│   └── static/              # index.html / app.css / app.js
├── module/                  # 作为流水线阶段的模块定义
│   ├── CONTRACT.md          # 接口契约:输入/输出/判定/幂等
│   ├── INTEGRATION.md       # 插在流水线哪一环,前后各是谁
│   ├── errors.yaml          # 53 条 → 错误码(53/53 覆盖)
│   └── examples/            # 请求样例(含负例)
├── docs/
│   ├── ADD-CHARACTER.md           # 录入新角色:6 步操作单
│   ├── HARVEST.md                 # 采集:链接 → 人声片段 → 角色
│   ├── TTS-API.md                 # 接入 TTS API:试听与克隆
│   ├── COLAB-INDEXTTS.md          # 走 Colab 免费 GPU 跑 IndexTTS-2.5
│   ├── DELIVERY-CHECKLIST.md      # 交付验收单(打印/签字)
│   ├── EXTERNAL-PRACTICES.md      # 外部实践吸收清单(采纳/改写/不采纳)
│   └── WINDOWS-INDEXTTS-SETUP.md  # Windows 原生部署 + 冒烟测试
├── templates/               # 复制即用的模板
│   ├── script-beats.yaml    # 可表演脚本(填充示例)
│   ├── project-voice.yaml   # 项目配音声明
│   ├── take-log.yaml        # 挑条留痕
│   └── character/           # 新角色空壳
│       ├── voice_card.yaml
│       └── presets.yaml
├── catalog.md               # 选角目录:人看这个
├── registry.json            # 资产索引:程序看这个
├── schema/                  # 校验契约
│   ├── beats.schema.json
│   ├── voice_card.schema.json
│   ├── presets.schema.json
│   └── manifest.schema.json
├── characters/<character_id>/
│   ├── voice_card.yaml      # 声卡:身份、音色、供应商映射、授权
│   ├── presets.yaml         # 预设:情绪 × 语速 × 停顿
│   ├── refs/                # 参考音频(干声)
│   └── bench/lines.txt      # 回归测试句
├── _shared/
│   ├── providers.yaml       # 供应商能力矩阵
│   ├── postprocess.yaml     # 统一混音链参数
│   ├── lexicon.tsv          # 读音词典
│   └── banned.yaml          # 禁用音源黑名单
└── licenses/                # 授权文件
```

## 一个项目怎么开始

```
1. 复制 templates/script-beats.yaml → 项目 script/S01.beats.yaml,按 §3 改写
2. 复制 templates/project-voice.yaml → 项目 voice.yaml,选角色、锁版本
3. 合成时按 templates/take-log.yaml 记账
4. 交付前复制 docs/DELIVERY-CHECKLIST.md → 项目 output/,逐项签字
```

**约束从哪来**:`rules.yaml` 是规则清单,`SPEC.md` 是规则的解释,`schema/` 是结构契约。三者冲突时,**以 `rules.yaml` 为准**。

## 新建一个角色(四步)

1. 复制 `characters/demo_qingleng_female/` 为新目录,目录名 = `character_id`(小写下划线)
2. 填 `voice_card.yaml`:身份、音色、`source`(含授权)、`providers`
3. 放 3 条参考干声到 `refs/`:清冷 / 激烈 / 低语,**10–14 秒**(硬上限 15 秒),无 BGM 无混响
4. 填 `presets.yaml` 至少 `calm` / `intense` / `whisper` 三档,然后在 `registry.json` 登记

> 参考音频质量占克隆效果的九成。宁可只录 3 条干净的,不要放 20 条带混响的。

## 在项目里用

```yaml
# 项目配音配置
voices:
  - character_id: demo_qingleng_female
    version: "0.1"
    preset: calm
```

## 状态约定

| 状态 | 含义 |
|---|---|
| `draft` | 结构未齐,允许缺参考音频;不得用于发布项目 |
| `active` | 通过全部校验,可用于发布 |
| `retired` | 停止使用,保留以防历史项目无法复现 |
