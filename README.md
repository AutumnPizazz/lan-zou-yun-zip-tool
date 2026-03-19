# 蓝奏云分片助手

[English](#lanzou-split-assistant)

面向普通用户的 Windows 图形化分片与还原工具，用于将大文件或文件夹处理成适合上传到蓝奏云的一组小文件，并在下载后通过独立程序完成校验、合并和解密。

## 项目简介

“蓝奏云分片助手”包含两个独立 GUI 程序：

- `split_gui.exe`：选择文件或文件夹后，自动完成压缩、加密、分片和清单生成
- `restore_gui.exe`：自动读取清单、校验分片、合并文件并解密恢复原始内容

整个流程围绕“零命令行知识用户”设计，不要求终端操作。

## 功能特性

- 图形界面操作，无需命令行
- 支持文件与文件夹
- 文件夹自动打包为 ZIP 后再加密
- 使用 AES-256-GCM 加密
- 使用 PBKDF2-HMAC-SHA256 从用户密码派生密钥
- 默认按 49 MB 分片，便于上传
- 分片文件使用随机文件名，并统一使用 `.txt` 扩展名
- 生成 `manifest.txt` 记录分片顺序、大小与 SHA256 校验信息
- 还原时自动校验完整性
- 还原完成后，文件夹场景可选自动解压

## 工作流程

### 发送方

1. 运行 `split_gui.exe`
2. 选择一个文件或文件夹
3. 选择输出目录
4. 输入并确认密码
5. 点击“开始处理”
6. 生成输出目录后，将整个目录上传到蓝奏云

输出目录通常包含：

- 若干随机命名的 `.txt` 分片文件
- `manifest.txt`
- `restore_gui.exe`

### 接收方

1. 下载完整输出目录
2. 确保分片文件、`manifest.txt` 和 `restore_gui.exe` 位于同一目录
3. 运行 `restore_gui.exe`
4. 点击“开始还原”
5. 输入正确密码
6. 选择保存位置
7. 若原始内容是文件夹，可选择自动解压

## 安全说明

- 程序不会在清单中保存明文密码
- 加密密钥由用户输入密码经过 PBKDF2 派生生成
- 清单中仅保存还原所需的非敏感参数，例如 salt、迭代次数、分片信息和校验值
- 分片在还原前会校验 SHA256，以尽早发现文件损坏或缺失

说明：

- 如果原始输入是文件夹，还原后先得到 ZIP，再可选自动解压
- 如果原始输入是普通文件，还原后直接得到原文件，不会强行按 ZIP 处理
- 为提高蓝奏云兼容性，所有分片统一使用 `.txt` 扩展名

## 项目结构

```text
lan_zou_yun/
├─ src/
│  └─ lan_zou_yun/
│     ├─ split_gui.py
│     ├─ restore_gui.py
│     └─ __init__.py
├─ pyproject.toml
└─ README.md
```

## 开发环境

- Windows
- Python 3.13
- Poetry
- PyInstaller

## 安装依赖

```powershell
poetry install
```

## 运行源码

分片工具：

```powershell
poetry run python .\src\lan_zou_yun\split_gui.py
```

还原工具：

```powershell
poetry run python .\src\lan_zou_yun\restore_gui.py
```

## 打包为 EXE

分片工具：

```powershell
poetry run pyinstaller -F -w -n split_gui .\src\lan_zou_yun\split_gui.py
```

还原工具：

```powershell
poetry run pyinstaller -F -w -n restore_gui .\src\lan_zou_yun\restore_gui.py
```

生成结果位于 `dist\` 目录。

## 注意事项

- `split_gui.exe` 会尝试把 `restore_gui.exe` 复制到输出目录，因此正式发布时建议先打包两个程序
- 还原时必须保证所有分片完整存在，且与 `manifest.txt` 匹配
- 密码错误时无法恢复原始内容
- 这是一个桌面端工具项目，不包含蓝奏云账号登录、自动上传或自动下载功能

## 开源说明

欢迎提交 Issue 与 Pull Request，用于改进：

- 界面体验
- 错误提示
- 打包流程
- 文档和示例
- Windows 兼容性

---

# Lanzou Split Assistant

[中文](#蓝奏云分片助手)

A Windows GUI toolset for splitting, encrypting, restoring, and decrypting files for Lanzou Cloud style upload workflows. It is designed for non-technical users and hides all command-line operations behind a simple desktop interface.

## Overview

Lanzou Split Assistant includes two standalone GUI programs:

- `split_gui.exe`: compresses folders, encrypts content, splits output into smaller parts, and generates a manifest
- `restore_gui.exe`: verifies parts, rebuilds the encrypted payload, decrypts it, and restores the original content

The project focuses on ease of use, predictable behavior, and basic integrity verification.

## Features

- GUI-only workflow
- Supports both files and folders
- Automatically zips folders before encryption
- AES-256-GCM encryption
- PBKDF2-HMAC-SHA256 based key derivation
- Default part size of 49 MB
- Randomized part filenames with a fixed `.txt` extension for compatibility
- `manifest.txt` stores metadata, ordering, and SHA256 checksums
- Automatic integrity verification during restore
- Optional auto-extract when the original input was a folder

## How It Works

### Sender side

1. Run `split_gui.exe`
2. Select a file or folder
3. Select an output directory
4. Enter and confirm a password
5. Click the start button
6. Upload the generated output folder to Lanzou Cloud

The output folder usually contains:

- multiple randomly named `.txt` part files
- `manifest.txt`
- `restore_gui.exe`

### Receiver side

1. Download the full output folder
2. Keep all part files, `manifest.txt`, and `restore_gui.exe` in the same directory
3. Run `restore_gui.exe`
4. Click the restore button
5. Enter the correct password
6. Choose a save location
7. If the original content was a folder, optionally extract it automatically

## Security Notes

- Plaintext passwords are never stored in the manifest
- Encryption keys are derived from the user password using PBKDF2
- The manifest only stores non-secret restore parameters such as salt, iteration count, part metadata, and checksums
- SHA256 verification helps detect missing or corrupted parts before restore

Notes:

- If the original input is a folder, the restored result is a ZIP file first, with optional extraction
- If the original input is a regular file, the restored result is the original file directly
- All generated parts use the `.txt` extension for better Lanzou compatibility

## Project Structure

```text
lan_zou_yun/
├─ src/
│  └─ lan_zou_yun/
│     ├─ split_gui.py
│     ├─ restore_gui.py
│     └─ __init__.py
├─ pyproject.toml
└─ README.md
```

## Requirements

- Windows
- Python 3.13
- Poetry
- PyInstaller

## Install Dependencies

```powershell
poetry install
```

## Run From Source

Split tool:

```powershell
poetry run python .\src\lan_zou_yun\split_gui.py
```

Restore tool:

```powershell
poetry run python .\src\lan_zou_yun\restore_gui.py
```

## Build EXE Files

Split tool:

```powershell
poetry run pyinstaller -F -w -n split_gui .\src\lan_zou_yun\split_gui.py
```

Restore tool:

```powershell
poetry run pyinstaller -F -w -n restore_gui .\src\lan_zou_yun\restore_gui.py
```

The generated executables will be placed in the `dist\` directory.

## Notes

- `split_gui.exe` tries to copy `restore_gui.exe` into the output directory, so both programs should be built before release
- All part files must remain complete and match `manifest.txt`
- A wrong password prevents successful restore
- This project does not implement Lanzou account login, automatic upload, or automatic download

## Contributing

Issues and pull requests are welcome for:

- UI improvements
- better error handling
- packaging workflow improvements
- documentation and examples
- Windows compatibility fixes
