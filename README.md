# chmtool

一个零 Python 第三方依赖的小脚本：调用系统中的 CHM 解包工具提取 `.chm` 内容，并生成带页面搜索和预览功能的 HTML 导航页。导航页会优先读取 CHM 的 `.hhc` 目录，保留原始中文标签和目录层级；没有目录信息时再使用 HTML 页面标题或文件名。桌面浏览时可拖动导航与内容之间的分隔条调整宽度，双击分隔条可恢复默认宽度。

## 环境要求

- Python 3.9+
- 以下任一 CHM 解包程序：
  - macOS / Linux：`extract_chmLib`（通常由 `chmlib` 提供）
  - macOS / Linux / Windows：`7zz`、`7z` 或 `7za`

macOS 可使用 Homebrew 安装：

```bash
brew install chmlib
```

Ubuntu / Debian：

```bash
sudo apt install libchm-bin
```

## 使用

```bash
python3 chmtool.py /path/to/manual.chm
```

默认会输出到 CHM 同目录下的 `manual_html/`，然后用浏览器打开：

```text
manual_html/index.html
```

如果 CHM 本身已经包含根目录 `index.html`，脚本不会覆盖它，而会把导航页命名为 `chmtool-index.html`。

常用选项：

```bash
# 指定输出目录
python3 chmtool.py manual.chm -o ./site

# 替换已有输出目录
python3 chmtool.py manual.chm -o ./site --overwrite

# 只解包，不生成导航页
python3 chmtool.py manual.chm --no-index

# 指定解包工具或自定义导航页名称
python3 chmtool.py manual.chm --extractor 7zz --index-name contents.html
```

查看全部参数：

```bash
python3 chmtool.py --help
```

## macOS Finder 右键快速操作

项目提供了一个 Finder 快速操作。安装后可以选中一个或多个 `.chm` 文件，右键直接解包并打开生成的 HTML 导航页。

安装：

```bash
./install-macos-quick-action.sh
```

安装完成后，在 Finder 中执行：

1. 选中 `.chm` 文件。
2. 右键选择 **快速操作**（或 **服务**）。
3. 点击 **解包 CHM 为 HTML**。

输出目录会创建在原 CHM 文件旁边，例如：

```text
manual.chm
manual_html/
```

快速操作会自动打开导航页，并通过系统通知显示处理结果。为避免误覆盖，如果 `manual_html` 已存在，会依次使用 `manual_html_2`、`manual_html_3` 等新目录。

如果右键菜单中没有出现该操作，可以到 **系统设置 → 隐私与安全性 → 扩展 → Finder** 中启用，或重新打开 Finder 窗口。

卸载：

```bash
./uninstall-macos-quick-action.sh
```

## 测试

```bash
python3 -m unittest -v
```

> CHM 内部本来就是 HTML、CSS、图片等网页资源，因此“转换为 HTML”的核心过程就是将这些资源安全地解包；额外生成的导航页用于快速浏览解包后的全部 HTML 页面。
