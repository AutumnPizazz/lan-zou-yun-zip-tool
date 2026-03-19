# 蓝奏云分片助手

面向零命令行经验用户的图形化分片与还原工具。包含两个独立程序：

- `split_gui.exe`：分片/加密
- `restore_gui.exe`：还原/解密

## 使用步骤

### 分片端
1. 运行 `split_gui.exe`
2. 点击“选择文件/文件夹”
3. 输入并确认密码
4. 点击“开始处理”，等待完成
5. 将生成的输出文件夹整体上传到蓝奏云

### 还原端
1. 下载方把分片文件、`manifest.dat` 与 `restore_gui.exe` 放在同一目录
2. 运行 `restore_gui.exe`
3. 点击“开始还原”，输入密码
4. 选择保存位置，可选自动解压

## 打包说明（开发者）

建议使用 Poetry + PyInstaller：

1. `poetry install`
2. `poetry run pyinstaller -F -w -n split_gui src/lan_zou_yun/split_gui.py`
3. `poetry run pyinstaller -F -w -n restore_gui src/lan_zou_yun/restore_gui.py`

生成的 `dist/split_gui.exe` 与 `dist/restore_gui.exe` 即为最终程序。
