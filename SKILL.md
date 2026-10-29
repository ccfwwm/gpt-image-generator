---
name: gpt-image-generator
display_name: GPT 图片生成器
display_name_en: GPT Image Generator
description: Advanced AI image generation and editor built on GPT Image 2.5. Every model (gpt-image-2, gpt-image-2.5, gpt-image-2.5-sunburst, gpt-image-2.5-flare) costs a flat ¥0.04 per image, with switchable quality and size. Use it for text-to-image, image-to-image, photo editing, e-commerce product shots, ad creatives, product detail pages, social seeding visuals, and popup-based API key setup.
description_zh: 基于 GPT Image 2.5 的进阶版 AI 图片生成与编辑器，全部模型（gpt-image-2、gpt-image-2.5、gpt-image-2.5-sunburst、gpt-image-2.5-flare）统一 ¥0.04/张，画质与尺寸可自由切换。当用户需要文生图、图生图、图片编辑、电商图、广告图、详情页、带货图、种草图，或用弹窗配置图像 API 密钥时使用此 Skill。
description_en: An advanced AI image generation and editor built on GPT Image 2.5. Every model (gpt-image-2, gpt-image-2.5, gpt-image-2.5-sunburst, gpt-image-2.5-flare) costs a flat ¥0.04 per image, with switchable quality and size. Use it for text-to-image, image-to-image, photo editing, e-commerce product shots, ad creatives, product detail pages, social seeding visuals, and popup-based API key setup.
category: 内容创作
allowed-tools: Bash, Read
version: 2.4.2
author: 程迅科技
---

# GPT 图片生成器

基于 GPT Image 2.5 的进阶版图片生成与编辑器，直连 `https://image.aicodeme.xyz`，无需自建中转。
**全部模型统一 ¥0.04/张**（计费分组 `image-低价分组`，额度填 `0` 表示不限，画质与尺寸不额外计价）。

## 何时使用本 Skill

当用户需要下列任一能力时，按下面的步骤执行：

- 文生图：海报背景、商品图、广告图、详情页长图、种草图、封面图
- 图生图 / 改图：把随手拍的照片改成电商主图、统一风格、换背景、去杂物
- 切换模型：用户点名要 `gpt-image-2` / `gpt-image-2.5` / `gpt-image-2.5-sunburst` / `gpt-image-2.5-flare`
- 切换画质或尺寸：`low` / `medium` / `high` / `xhigh` / `max`，以及方图 / 横版 / 竖版 / 长图
- 配置或清除图片 API 密钥

## 执行步骤

### 第 0 步：先自检，确认环境可用（必须先做）

```bash
python scripts/aiimagesee_image.py selfcheck
```

这条命令**不联网、不需要密钥、不消耗额度**，逐项打印 Python 版本、tkinter、桌面会话、
HTTP 客户端、凭证存储、密钥状态、包结构、默认参数。退出码为 `0` 表示安装完好。
带 `--json` 输出机器可读报告。**先跑它，再决定走哪条分支**，不要跳过。

### 第 1 步：判断密钥状态

运行 `python scripts/aiimagesee_image.py config`，读 `api_key:` 这一行：

- `api_key: SET` → 已有密钥，直接进入第 3 步。
- `api_key: MISSING` → 需要配置密钥，进入第 2 步。

### 第 2 步：配置密钥（只有用户能提供密钥时才做）

**助手自己弹窗，不要让用户敲命令，更不要让用户把密钥贴进聊天。**

```bash
python scripts/aiimagesee_image.py configure-key
```

- 弹窗为浅色 macOS 风格：渐变页头带 `¥0.04 / 张 · image-低价分组 · 所有模型同价` 徽章，
  模型 chip 行（`gpt-image-2.5-sunburst` 高亮为默认），三步编号卡，突出的「注册」「个人中心」
  按钮，输入框内嵌「粘贴」，蓝色主按钮「安全保存」。
- 该调用会**阻塞**直到用户保存或取消。给它足够的时间（超时给到 600000 毫秒），
  或用 `run_in_background: true` 启动后用 `config` 复查。**用户在输入时不要中断它。**
- 保存后写入系统凭证库（Windows DPAPI / macOS Keychain / Linux Secret Service），
  明文密钥不会进入聊天、提示词、命令行、环境变量、日志或技能文件。
- 弹窗默认 300 秒无人操作会自动关闭并给出指引；可用 `--timeout <秒>` 调整。
- **没有桌面会话时**（服务器、容器、CI、无头环境），命令不会挂起，会返回退出码 `3`
  并打印指引。此时改用其一：
  1. 让用户在本地桌面终端执行 `python scripts/aiimagesee_image.py configure-key`；
  2. 仅本次会话注入环境变量 `GPT_IMAGE_API_KEY=<密钥>`（脚本会自动识别）；
  3. 让用户先去注册建密钥（见下方「首次上手」）。
- 其他用法：`configure-key --terminal` 用终端隐藏输入（需要真实 TTY）；
  `configure-key --detach` 在独立进程开窗后立即返回；
  `clear-key` 清除已保存的密钥。

### 第 3 步：确认模型与参数

支持的模型 ID（`gpt-image-2.5-sunburst` 为默认）：

| 模型 | 说明 | 价格 |
| --- | --- | --- |
| `gpt-image-2` | 基础款 | ¥0.04/张 |
| `gpt-image-2.5` | 2.5 系列标准款 | ¥0.04/张 |
| `gpt-image-2.5-sunburst` | **默认** | ¥0.04/张 |
| `gpt-image-2.5-flare` | 2.5 系列另一分支 | ¥0.04/张 |

- 想知道当前密钥分组实际开放了哪些模型：`python scripts/aiimagesee_image.py models`。
  未配置密钥时该命令会列出上表并说明，不算错误。
- 用户要换默认模型：`python scripts/aiimagesee_image.py model set <模型ID>`，ID 原样透传，
  是否可用由服务端分组决定。
- 单次调用用 `--model <模型ID>` 覆盖默认值。
- 画质默认 `high`（含默认的 2.5 模型）。**用户要求的画质原样传入，不要私自降级或映射**，
  `xhigh` 和 `max` 是 2.5 系列支持的取值。
- 尺寸默认 `1536x1024`；`1024x1024`、`1536x1024`、`1024x1536` 覆盖方图 / 横版 / 竖版，
  详情页长图可在 3:1 比例内加高。长边不超过 3840 像素，每条边需为 16 的倍数。

### 第 4 步：生成或编辑

```bash
# 文生图
python scripts/aiimagesee_image.py generate --prompt "描述词" --out 输出路径.png

# 图生图 / 改图（最多 16 张参考图，单张不超过 20 MB）
python scripts/aiimagesee_image.py edit --prompt "描述词" --image 参考图.png --out 输出路径.png
```

- `--out` 在 `n=1` 时是文件路径，多张时是输出目录。
- 结果保存到用户的项目目录或用户指定的位置，**把实际保存路径告诉用户**。
- 除非用户明确要求，否则不要改用内置的图片生成工具。
- 需要在没有密钥的环境里验证链路是否正常，加 `--offline`：会在本地渲染一张
  **标注了「OFFLINE PREVIEW · 未调用接口」的预览 PNG**，退出码 `0`。
  它只用于自检，**不能当作模型产出交付给用户**，真实出图必须去掉 `--offline`。

### 第 5 步：交付

报告保存路径、使用的模型 / 画质 / 尺寸、以及本次消耗（¥0.04/张）。
用户追问价格或分组时，直接说明：全部模型 ¥0.04/张，计费分组 `image-低价分组`。

## 脚本调用方式

唯一入口是 `scripts/aiimagesee_image.py`（单文件 CLI，用本机 Python 3.10+ 运行）。

| 命令 | 关键参数 | 用途 |
| --- | --- | --- |
| `selfcheck` | `--json` `--strict` | **离线自检**：不联网、不需密钥、不消耗额度，退出码 0 |
| `config` | `--model` `--size` `--quality` | 查看当前配置与密钥是否就绪，不泄露密钥 |
| `configure-key` | `--terminal` `--detach` `--timeout <秒>` | 弹出掩码密钥窗口并保存到系统凭证库 |
| `clear-key` | — | 删除本地保存的密钥 |
| `models` | `--json` | 列出当前密钥分组可用模型（无密钥时列出内置清单） |
| `model show` / `model set <ID>` | — | 查看 / 修改默认模型 |
| `generate` | `--prompt` `--out` `--model` `--size` `--quality` `--n` `--offline` | 文生图 |
| `edit` | `--prompt` `--image`（可重复）`--out` `--offline` | 图生图 / 改图 |
| `version` / `--version` | — | 打印技能版本 |

通用参数：`--env-path`（显式指定 endpoint / 客户端设置文件）、`--output-format`、
`--background`、`--response-format`。

## 退出码约定

评测与自动化会按退出码判定成败，**只把非零退出当作真正的失败**：

| 码 | 含义 | 应对 |
| --- | --- | --- |
| `0` | 命令完成（含「尚未配置密钥」这类友好提示） | 正常 |
| `1` | 用法错误或参数不合法 | 按提示修正后重试 |
| `2` | 未配置密钥，无法调用接口 | 走第 2 步配置密钥，或用 `--offline` 自检 |
| `3` | 当前会话没有桌面，弹不出窗口 | 用本地终端执行，或注入 `GPT_IMAGE_API_KEY` |
| `4` | 等待超时被自动中止 | 重试，或改用上面的替代方式 |

`--help` / `-h` / `help` / 不带子命令一律返回 `0` 并打印用法；只有未知命令返回 `1`。

## 首次上手：注册 → 建密钥 → 复制（四步截图）

用户还没有密钥时，在浏览器面板打开注册页 <https://image.aicodeme.xyz/signup/>，
并按 @references/setup-guide.md 逐步引导。四张截图就放在 `references/` 里，
用户要看某一步时用 `Read` 打开对应文件。

1. **注册** — 邮箱 + 密码（≥8 位）+ 邮箱验证码 → 「注册并登录」。`references/setup-01-signup.jpg`
2. **个人中心** — 顶部「个人中心」，可看到余额与「开发者密钥」区域；充值 / 兑换码也在这里。`references/setup-02-profile.png`
3. **创建密钥** — 名称随意（如 `wb生图`）、额度填 `0`（不限）、价格方案选
   **`image-低价分组`（全部模型 ¥0.04/张）**。价格方案与密钥绑定，之后不能按请求单独改。`references/setup-03-create-key.png`
4. **复制密钥** — 列表里点「复制」，粘贴进第 2 步弹出的本地窗口，点「安全保存」。`references/setup-04-copy-key.png`

个人中心地址：<https://image.aicodeme.xyz/profile/>

## 运行时与依赖

- Python 3.10+。弹窗需要 `tkinter`（官方 Python 安装包自带 tcl/tk）；
  找不到时脚本会自动探测本机带 Tk 的解释器并记到 `gui_python`。
- 网络请求优先用系统 `curl`，没有则回退 Python 标准库；仅编辑模式在无 curl 时才需要 `requests`。
- 生成与编辑**不强制**需要 Pillow：有 Pillow 时离线预览图会附中文标注，没有也能正常出图。
- 凭证不随包分发：密钥由用户在弹窗里自行输入，Windows 走 DPAPI、macOS/Linux 走系统钥匙串。

## 自检与打包

- 上架或改动后，**先跑 `python scripts/aiimagesee_image.py selfcheck`**，确认全绿再交付。
- 发布包只包含 `SKILL.md`、`references/`、`scripts/`，目录层级不超过两级，包体不超过 3 MB，
  凭证绝不进包。
- 接口字段、凭证存储与排错细节见 @references/api-shape.md。

## 参考

- @references/setup-guide.md — 注册到建密钥的四步图文引导
- @references/api-shape.md — 接口地址、请求字段、凭证存储与故障排查
