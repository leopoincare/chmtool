#!/bin/zsh

set -euo pipefail

SERVICE_DIR="$HOME/Library/Services/解包 CHM 为 HTML.workflow"
APP_DIR="$HOME/Library/Application Support/chmtool"

rm -rf "$SERVICE_DIR" "$APP_DIR"
/System/Library/CoreServices/pbs -flush >/dev/null 2>&1 || true

print -r -- "已卸载“解包 CHM 为 HTML”Finder 快速操作。"
