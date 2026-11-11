# 录入一个新角色

> 目标:15–30 分钟内把"一个人"变成库里可被项目引用的角色。
> 前置:编辑器已装 `redhat.vscode-yaml`(打开仓库时会提示安装),这样 YAML 有字段补全和红波浪线。

---

## 第 0 步:先填这张单子(别急着动文件)

| 项 | 填什么 | 示例 |
|---|---|---|
| character_id | 小写+下划线,3–32 位,**永不复用** | `lin_wan` |
| display_name | 中文名 | 林晚 |
| 性别 / 年龄 | 只能 male/female/neutral + 区间 | female / 18-22 |
| 音色标签 | 2–6 个短词,用于选角检索 | 清冷、偏低、微沙 |
| 戏路 | 一句话 | 侠女,内敛,压抑式爆发 |
| 音区 | 中低音区 / 中高音区 | 中低音区 |
| 声源类型 | 委托录制 / 自有录制 / 授权音色 / 设计音色 | 委托录制 |
| 授权到期日 | 加引号 | "2029-11-30" |
| 表演要点 | 这个角色怎么说话 | 情绪内收,激烈戏靠气息不靠音量 |

**character_id 定错是最贵的错误**——它是所有关联的键,改了等于换角色。

---

## 第 1 步:建目录

```powershell
cd D:\Code\video\voicelib
Copy-Item templates\character -Destination characters\<character_id> -Recurse
```

产物:
```
characters/<character_id>/
├── voice_card.yaml
└── presets.yaml
```

接着手动补两个空目录(模板里没有):

```powershell
New-Item -ItemType Directory characters\<character_id>\refs
New-Item -ItemType Directory characters\<character_id>\bench
Copy-Item characters\demo_qingleng_female\bench\lines.txt characters\<character_id>\bench\
```

---

## 第 2 步:填声卡

打开 `characters/<character_id>/voice_card.yaml`,把所有 `<>` 换掉。

编辑器的帮助:**光标停在任一字段上会显示说明;填错类型立刻出红波浪线**。

三个必须注意的点:

| 坑 | 后果 |
|---|---|
| `valid_until: 2029-11-30` 不加引号 | YAML 会解析成日期对象,schema 校验不过 |
| `rate_baseline` 填成供应商的 speed | 语义反了(库内 >1 更快),整集语速错 |
| `status` 直接填 `active` | active 表示可发布;参考音频没到位就是造假,先 `draft` |

---

## 第 3 步:填预设

打开 `presets.yaml`,至少留 `calm` / `intense` / `whisper` 三档。

| 规则 | 为什么 |
|---|---|
| `emo` 各键之和 ≤ 0.8 | 留余量给音色自带的情绪底色 |
| `pause_after` 每档不同 | 全同值会被判"机械停顿" |
| `rate` 只用库内语义 | 供应商的倒数转换由适配器负责,别在这里倒 |

---

## 第 4 步:放参考音频

| 项 | 要求 |
|---|---|
| 文件名 | `calm.wav` / `intense.wav` / `whisper.wav` |
| 时长 | **10–14 秒**(硬上限 15 秒) |
| 格式 | WAV 或 FLAC,**禁止 MP3** |
| 内容 | 该角色情绪最典型的一句,用**目标说话方式**录,不要念标准普通话 |
| 环境 | 安静、无 BGM、无混响、无降噪痕迹 |

详细要求见 `characters/<character_id>/refs/README.md`(可直接发给录音的人)。

录完自检:

```powershell
ffprobe -v error -show_entries stream=sample_rate,channels -show_entries format=duration -of default=nw=1 refs\calm.wav
```

时长不在 10–14 秒、或采样率低于 44100,重录。

---

## 第 5 步:登记两处(最容易漏)

**这两处是手工双写,必须都改**,否则调用时会报 `E2001 角色未登记`。

### 5.1 `registry.json`

在 `characters` 数组里追加一条:

```json
{
  "character_id": "lin_wan",
  "display_name": "林晚",
  "version": "0.1.0",
  "status": "draft",
  "gender": "female",
  "age_range": "18-22",
  "timbre_tags": ["清冷", "偏低", "微沙"],
  "archetype": "侠女",
  "path": "characters/lin_wan",
  "voice_card": "characters/lin_wan/voice_card.yaml",
  "presets": "characters/lin_wan/presets.yaml",
  "preset_keys": ["calm", "intense", "whisper"],
  "refs_complete": false,
  "providers": ["index_tts25"],
  "fallback_order": ["index_tts25"],
  "license_ref": "licenses/lin_wan.md",
  "license_valid_until": "2029-11-30",
  "checksum": null
}
```

> `refs_complete` 在三条音频都到位后才改 `true`。

### 5.2 `catalog.md`

在"可用角色"表里加一行:

```markdown
| `lin_wan` | 林晚 | 女 / 18-22 | 清冷、偏低、微沙 | 侠女 | calm / intense / whisper | 🟡 draft | 0.1.0 |
```

---

## 第 6 步:校验

```powershell
python D:\Code\video\.scratch\validate_module.py
```

看两件事:

1. `YAML: N 个` —— 你的新文件是否被解析(解析失败会列出来)
2. `规则覆盖 53/53` —— 索引是否仍然自洽

再单独校验声卡(可选,需装 `jsonschema`):

```powershell
python -c "import json,yaml,jsonschema; d=yaml.safe_load(open(r'characters/lin_wan/voice_card.yaml',encoding='utf-8')); s=json.load(open('schema/voice_card.schema.json',encoding='utf-8')); jsonschema.validate(d,s); print('OK')"
```

---

## 常见错误

| 报错 | 原因 | 修法 |
|---|---|---|
| `E2001 角色未登记` | 只建了目录,没改 `registry.json` | 补第 5.1 步 |
| schema: `valid_until is not of type string` | 日期没加引号 | 加引号 |
| schema: `age_range does not match` | 写成 `18~22` | 必须是 `18-22` |
| `E2003 参考音频缺失或时长不合规` | 超 15 秒或不是无损 | 重录;超 15 秒会被静默截断 |
| `E2002 授权缺失` | `license_ref` 指向的文件不存在 | 先签授权,再建角色 |
| 编辑器没有补全 | 缺 `redhat.vscode-yaml` | 装扩展,重开窗口 |

---

## 什么时候可以从 draft 转 active

三条同时满足:

- [ ] 3 条参考音频到位,`refs_complete: true`
- [ ] 授权文件已签,且写明**含 AI 合成/克隆/训练**
- [ ] 试听定档完成(`bench/lines.txt` 跑一遍,人工打分 ≥4)

在 `voice_card.yaml` 与 `registry.json` 两处把 `status` 改成 `active`,并把 `catalog.md` 的 🟡 改成 🟢。
