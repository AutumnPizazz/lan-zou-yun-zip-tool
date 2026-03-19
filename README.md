# 蓝奏云分片助手

面向普通用户的 Windows 图形化工具，用于把大文件或文件夹处理成适合上传到蓝奏云的一组小文件，并在下载后通过同一个 GUI 完成校验、合并和解密。

## 项目简介

当前项目只提供一个统一 GUI 程序：

- `lan_zou_zip_tool_gui.exe`：进入首页后可选择“分片”或“还原”

整个流程围绕“零命令行知识用户”设计，不要求终端操作。

## 功能特性

- 单一 GUI，首页切换分片与还原
- 支持文件与文件夹
- 文件夹自动打包为 ZIP 后再加密
- 使用 AES-256-GCM 加密
- 使用 PBKDF2-HMAC-SHA256 从用户密码派生密钥
- 默认按 49 MB 分片，便于上传
- 分片文件使用随机文件名，并统一使用 `.txt` 扩展名
- 生成 `manifest.txt` 记录分片顺序、大小与 SHA256 校验信息
- 还原时自动校验完整性
- 还原完成后，文件夹场景可选自动解压
- 程序同目录生成 `lan_zou_zip_tool_gui.json`，记住常用路径和分片大小等非敏感设置

## 工作流程

### 发送方

1. 运行 `lan_zou_zip_tool_gui.exe`
2. 在首页点击“开始分片”
3. 选择文件或文件夹
4. 选择输出目录
5. 输入并确认密码（可留空）
6. 点击“开始处理”
7. 生成输出目录后，将整个目录上传到蓝奏云

输出目录通常包含：

- 若干随机命名的 `.txt` 分片文件
- `manifest.txt`
- `lan_zou_zip_tool_gui.exe`

### 接收方

1. 下载完整输出目录
2. 确保分片文件、`manifest.txt` 和 `lan_zou_zip_tool_gui.exe` 位于同一目录
3. 运行 `lan_zou_zip_tool_gui.exe`
4. 在首页点击“开始还原”
5. 如设置了密码则输入正确密码；未设置密码时可直接还原
6. 选择保存位置
7. 若原始内容是文件夹，可选择自动解压

## 安全说明

- 程序不会在清单或配置文件中保存明文密码
- 加密密钥由用户输入密码经过 PBKDF2 派生生成
- 清单中仅保存还原所需的非敏感参数，例如 salt、迭代次数、分片信息和校验值
- 分片在还原前会校验 SHA256，以尽早发现文件损坏或缺失
- 允许留空密码；留空时仍会封装处理，但不再具备实际保密性

说明：

- 如果原始输入是文件夹，还原后先得到 ZIP，再可选自动解压
- 如果原始输入是普通文件，还原后直接得到原文件，不会强行按 ZIP 处理
- 为提高蓝奏云兼容性，所有分片统一使用 `.txt` 扩展名

## 项目结构

```text
lan_zou_yun/
├─ .github/
│  └─ workflows/
│     └─ release.yml
├─ src/
│  └─ lan_zou_yun/
│     ├─ app_state.py
│     ├─ gui_common.py
│     ├─ main_gui.py
│     ├─ split_gui.py
│     ├─ restore_gui.py
│     └─ __init__.py
├─ lan_zou_zip_tool_gui.spec
├─ pyproject.toml
└─ README.md
```

## 开发环境

- Windows
- Python 3.14
- Poetry
- PyInstaller

## 安装依赖

```powershell
poetry install
```

## 运行源码

```powershell
poetry run python .\src\lan_zou_yun\main_gui.py
```

## 打包为 EXE

```powershell
poetry run pyinstaller lan_zou_zip_tool_gui.spec --clean
```

生成结果位于 `dist\` 目录。

## 自动发布

推送形如 `v0.1.0` 的标签后，GitHub Actions 会：

- 校验 Git 标签版本与 `pyproject.toml` 一致
- 构建 `lan_zou_zip_tool_gui.exe`
- 发布 `lan_zou_zip_tool_gui-v0.1.0.exe` 到 GitHub Release

## 注意事项

- 输出目录会尝试复制 `lan_zou_zip_tool_gui.exe`，因此正式发布时建议先打包统一 GUI
- 还原时必须保证所有分片完整存在，且与 `manifest.txt` 匹配
- 配置文件仅保存非敏感界面状态，不保存密码
- 这是一个桌面端工具项目，不包含蓝奏云账号登录、自动上传或自动下载功能

## 开源说明

欢迎提交 Issue 与 Pull Request，用于改进：

- 界面体验
- 错误提示
- 打包流程
- 文档和示例
- Windows 兼容性
