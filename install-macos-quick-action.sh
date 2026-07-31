#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
APP_DIR="$HOME/Library/Application Support/chmtool"
SERVICE_DIR="$HOME/Library/Services/解包 CHM 为 HTML.workflow"
SOURCE_SERVICE="$SCRIPT_DIR/macos/解包 CHM 为 HTML.workflow"

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 -- "错误：该安装器只能在 macOS 上运行"
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/chmtool.py" || ! -d "$SOURCE_SERVICE" ]]; then
  print -u2 -- "错误：安装文件不完整，请在项目根目录中运行此脚本"
  exit 1
fi

mkdir -p "$APP_DIR" "$HOME/Library/Services"
install -m 755 "$SCRIPT_DIR/chmtool.py" "$APP_DIR/chmtool.py"
install -m 755 "$SCRIPT_DIR/macos/quick-action.sh" "$APP_DIR/quick-action.sh"

if [[ -e "$SERVICE_DIR" ]]; then
  rm -rf "$SERVICE_DIR"
fi
/usr/bin/ditto "$SOURCE_SERVICE" "$SERVICE_DIR"

# Refresh the Services database. Finder will discover the action immediately
# in most cases; logging out is not required.
/System/Library/CoreServices/pbs -flush >/dev/null 2>&1 || true

print -r -- "安装完成：$SERVICE_DIR"
print -r -- "现在可以在 Finder 中选中 CHM 文件，右键 → 快速操作 → 解包 CHM 为 HTML。"
print -r -- "如果菜单没有立即出现，请重新打开 Finder 窗口，或到 系统设置 → 隐私与安全性 → 扩展 → Finder 中启用。"
