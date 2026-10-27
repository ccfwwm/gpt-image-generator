# 密钥获取四步（附截图）

> **价格：四个模型统一 ¥0.04/张**（`image-低价分组`，额度填 `0` 不限），换画质、换尺寸都不加价。

站点：`https://image.aicodeme.xyz`　注册页：`https://image.aicodeme.xyz/signup/`　个人中心：`https://image.aicodeme.xyz/profile/`

> 说明：以下截图仅作步骤指引，图片里的账号、余额、密钥均为示例，不含真实密钥。助手可以 `Read` 这些图片，再按图给用户讲步骤。

## 第 1 步 · 注册账号

打开 <https://image.aicodeme.xyz/signup/>，填邮箱与密码（至少 8 位），点「发送」获取邮箱验证码，填入后点「注册并登录」。

![注册页面](references/setup-01-signup.jpg)

## 第 2 步 · 进入个人中心

登录后点顶部导航的「个人中心」（也可直接访问 <https://image.aicodeme.xyz/profile/>）。这里能看到账户余额与「开发者密钥」区域，右上角「去充值」用于充值或兑换码入账。

![个人中心](references/setup-02-profile.png)

## 第 3 步 · 创建开发者密钥

在「开发者密钥」区域点右上角「创建密钥」，在弹窗里：

- 名称：随便起，例如 `wb生图`
- 额度：填 `0` 表示不限
- 价格方案：选 **`image-低价分组`** —— 四个模型统一 **¥0.04/张**，画质/尺寸不额外加价
- 点「创建密钥」

![创建密钥](references/setup-03-create-key.png)

> 价格方案在创建时与密钥绑定，之后无法对单次请求单独指定；想换方案只能新建密钥。

## 第 4 步 · 复制密钥

创建成功后在密钥列表里点「复制」，随后把密钥粘贴到 WorkBuddy 弹出的本地保存窗口（`configure-key`），点「安全保存」。

![复制密钥](references/setup-04-copy-key.png)

## 安全约定

- 密钥只在弹窗/系统凭据库里流转：Windows 用 DPAPI 加密，macOS/Linux 用 Keychain / Secret Service / KWallet。
- 不要粘贴到聊天、提示词、命令行参数、`.env`、日志或任何文件里；截图分享前也要把 `sk-...` 遮掉。
- 换密钥或做本地清理时用 `configure-key` 重设，或用 `clear-key` 删除（会二次确认，且不回显）。
