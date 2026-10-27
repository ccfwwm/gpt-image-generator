---
name: gpt-image-generator
display_name: GPT 图片生成器
display_name_en: GPT Image Generator
description: Advanced AI image generation and editor built on GPT Image 2.5 — every model (gpt-image-2, gpt-image-2.5, gpt-image-2.5-sunburst, gpt-image-2.5-flare) costs a flat ¥0.04 per image, with switchable quality and size. Use it for text-to-image, image-to-image, photo editing, e-commerce product shots, ad creatives, product detail pages, social seeding visuals, and popup-based API key setup.
description_zh: 基于 GPT Image 2.5 的进阶版 AI 图片生成与编辑器，全部模型（gpt-image-2、gpt-image-2.5、gpt-image-2.5-sunburst、gpt-image-2.5-flare）统一 ¥0.04/张，画质与尺寸可自由切换。当用户需要文生图、图生图、图片编辑、电商图、广告图、详情页、带货图、种草图，或用弹窗配置图像 API 密钥时使用此 Skill。
description_en: An advanced AI image generation and editor built on GPT Image 2.5 — every model (gpt-image-2, gpt-image-2.5, gpt-image-2.5-sunburst, gpt-image-2.5-flare) costs a flat ¥0.04 per image, with switchable quality and size. Use it for text-to-image, image-to-image, photo editing, e-commerce product shots, ad creatives, product detail pages, social seeding visuals, and popup-based API key setup.
examples_zh:
  - "用 gpt-image-2.5 生成一张极简蓝绿色科技感海报背景，右侧留白给文案，保存到当前项目。"
  - "把这张随手拍的商品图改成白底电商主图，突出材质与光影，出 3:2 横版。"
  - "帮我配好图片 API 密钥：直接弹窗给我填，顺便把注册和建密钥的四步截图给我看。"
examples_en:
  - "Use gpt-image-2.5 to generate a minimalist blue-green tech poster background with empty space on the right for copy, and save it in the project."
  - "Turn this casual product snapshot into a white-background e-commerce hero shot with visible texture and light, in 3:2 landscape."
  - "Set up my image API key with the local popup and walk me through the four setup screenshots."
version: 2.4.1
author: 程迅科技
category: 内容创作
---

# GPT Image Generator

基于 GPT Image 2.5 的进阶版图片生成与编辑器，直连 `https://image.aicodeme.xyz`，无需自建中转。

**价格：全部模型统一 ¥0.04/张**（`image-低价分组`，额度填 `0` 不限），画质与尺寸不额外计价。

模型：`gpt-image-2`、`gpt-image-2.5`、`gpt-image-2.5-sunburst`、`gpt-image-2.5-flare`；画质支持 `low` / `medium` / `high` / `xhigh` / `max`，尺寸可从 1024 方图到 3840 长边自选。

能力：文生图、图生图、图片编辑（最多 16 张参考图）、电商主图 / 广告图 / 详情页长图 / 带货种草图，密钥通过本地掩码弹窗安全保存，并可在对话里切换模型、画质与尺寸。当用户需要上述任一能力时使用此 Skill。

## Configure the API key — open the popup yourself

The helper's masked window is the only accepted way to collect the secret, and **the assistant opens it — never hand the user a terminal command to type**.

1. Say what is about to happen ("我给你弹一个窗口"), then run `python scripts/aiimagesee_image.py configure-key`.
   It shows a light macOS-style masked window titled `配置 API 密钥 · GPT 图片生成器` — gradient header with the `¥0.04 / 张 · image-低价分组 · 所有模型同价` badge, a model-chip row (`gpt-image-2`, `gpt-image-2.5`, `gpt-image-2.5-sunburst` highlighted as default, `gpt-image-2.5-flare`), a numbered three-step card, prominent register / profile buttons, a paste button inside the field, and a blue primary button. It blocks until the user saves or cancels, then prints `dialog_result:` and `api_key: SET|MISSING`.
2. The call blocks while the user types, so give it room: pass a long timeout (for example 600000 ms) or run it with `run_in_background: true` and check `config` afterwards. Never kill it while the user is typing.
3. The user pastes the key, clicks `安全保存`, and it is written to the OS credential store (Windows DPAPI; macOS Keychain; Linux Secret Service or KWallet). Plaintext never touches chat, prompts, argv, env files, logs, or skill files.
4. `python scripts/aiimagesee_image.py clear-key` deletes the saved key after confirmation. `configure-key --terminal` uses hidden terminal input (needs a real TTY); `--detach` hands off to a separate process and returns immediately.

Do not ask the user to paste the key into chat. If the desktop has no Tk-capable Python, the helper reports it with a native message box instead of silently swallowing input — then suggest installing official Python with tcl/tk, or `--terminal` in a local shell.

## 首次上手：注册 → 建密钥 → 复制（四步截图）

When the user has no key yet, open the signup page in the browser panel (<https://image.aicodeme.xyz/signup/>) and walk them through @references/setup-guide.md. The four screenshots sit next to it in `references/`; `Read` them when the user asks to see a step.

1. **注册** — 邮箱 + 密码（≥8 位）+ 邮箱验证码 → 「注册并登录」。`references/setup-01-signup.jpg`
2. **个人中心** — 顶部「个人中心」，可看到余额与「开发者密钥」区域；充值/兑换码也在这里。`references/setup-02-profile.png`
3. **创建密钥** — 名称随意（如 `wb生图`）、额度填 `0`（不限）、价格方案选 **`image-低价分组`（全部模型 ¥0.04/张）**。价格方案与密钥绑定，之后不能按请求单独改。`references/setup-03-create-key.png`
4. **复制密钥** — 列表里点「复制」，粘贴进上面第 4 步弹出的本地窗口，点「安全保存」。`references/setup-04-copy-key.png`

## Choose a model through conversation

Supported model IDs:

| 模型 | 说明 | 价格 |
| --- | --- | --- |
| `gpt-image-2` | 基础款 | ¥0.04/张 |
| `gpt-image-2.5` | 2.5 系列标准款 | ¥0.04/张 |
| `gpt-image-2.5-sunburst` | **默认** | ¥0.04/张 |
| `gpt-image-2.5-flare` | 2.5 系列另一分支 | ¥0.04/张 |

Run `python scripts/aiimagesee_image.py models` to see what the current key's group actually exposes, and present that list when the user asks what is available. When the user asks to switch, save their exact ID with `python scripts/aiimagesee_image.py model set MODEL_ID` — the ID is passed through unchanged, so availability is decided by the service. A per-image `--model MODEL_ID` overrides the saved default.

## Generate or edit

Default quality is `high`, including with the default 2.5 model. Pass the user's requested quality unchanged; `xhigh` and `max` are supported values for 2.5 models. Do not silently lower or map quality. The upstream model and key's group determine whether a requested model/quality combination is accepted.

For generation, use `python scripts/aiimagesee_image.py generate --prompt "..." --out PATH`. For editing (图生图 / 改图), add one or more `--image PATH` options and use the `edit` command; up to 16 references, 20 MB each.

Size defaults to `1536x1024`; `1024x1024`, `1536x1024` and `1024x1536` cover square, landscape and portrait, and 详情页长图 can go taller within a 3:1 ratio. Long edge stays at or below 3840 px and every side must be divisible by 16.

Ask for or infer practical image settings only when the request needs them. Save results in the user's project or requested output folder and report the path. Do not use the built-in image generator unless the user requests it or this API is unavailable.

## Runtime 与依赖

- Python 3.10+，弹窗需要 `tkinter`（官方 Python 安装包自带 tcl/tk）；找不到时脚本会自动探测本机带 Tk 的解释器并记到 `gui_python`。
- 网络请求优先用系统 `curl`，没有则回退 Python 标准库；仅编辑模式在无 curl 时才需要 `requests`。
- 凭证不随包分发：密钥由用户在弹窗里自行输入，Windows 走 DPAPI、macOS/Linux 走系统钥匙串。

Use the local Python 3 launcher. Prefer an interpreter that can import `tkinter` for the popup — the helper detects one automatically and remembers it as `gui_python`. Read @references/api-shape.md for request fields, response handling, platform credential storage, and troubleshooting details.
