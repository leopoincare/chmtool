#!/bin/zsh

# Finder Quick Action entry point. Automator passes selected files as arguments.
set -u

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

TOOL="${CHMTOOL_PATH:-$HOME/Library/Application Support/chmtool/chmtool.py}"
success_count=0
failure_count=0

notify() {
  if [[ "${CHMTOOL_NO_UI:-0}" == "1" ]]; then
    return
  fi
  /usr/bin/osascript \
    -e 'on run argv' \
    -e 'display notification (item 2 of argv) with title (item 1 of argv)' \
    -e 'end run' \
    "CHM 解包工具" "$1" >/dev/null 2>&1 || true
}

next_output_directory() {
  local input="$1"
  local base="${input:r}_html"
  local candidate="$base"
  local number=2
  while [[ -e "$candidate" ]]; do
    candidate="${base}_${number}"
    (( number += 1 ))
  done
  print -r -- "$candidate"
}

if (( $# == 0 )); then
  notify "没有收到文件，请在 Finder 中选中 CHM 文件后再运行。"
  print -u2 -- "错误：没有收到输入文件"
  exit 1
fi

if [[ ! -f "$TOOL" ]]; then
  notify "主程序不存在，请重新运行 install-macos-quick-action.sh。"
  print -u2 -- "错误：找不到主程序：$TOOL"
  exit 1
fi

for input in "$@"; do
  if [[ ! -f "$input" || "${input:e:l}" != "chm" ]]; then
    notify "已跳过非 CHM 文件：${input:t}"
    print -u2 -- "错误：不是 CHM 文件：$input"
    (( failure_count += 1 ))
    continue
  fi

  output="$(next_output_directory "$input")"
  result="$(/usr/bin/python3 "$TOOL" "$input" --output "$output" 2>&1)"
  exit_code=$?
  if (( exit_code != 0 )); then
    message="${${(f)result}[-1]:-未知错误}"
    notify "${input:t} 解包失败：${message[1,180]}"
    print -u2 -- "$result"
    (( failure_count += 1 ))
    continue
  fi

  index="$output/chmtool-index.html"
  if [[ ! -f "$index" ]]; then
    index="$output/index.html"
  fi
  if [[ ! -f "$index" ]]; then
    index="${(f)$(find "$output" -maxdepth 1 -name 'chmtool-index*.html' -print -quit)}"
  fi

  if [[ "${CHMTOOL_NO_UI:-0}" != "1" ]]; then
    if [[ -n "$index" && -f "$index" ]]; then
      /usr/bin/open "$index" >/dev/null 2>&1 || true
    else
      /usr/bin/open "$output" >/dev/null 2>&1 || true
    fi
  fi
  notify "${input:t} 已解包到 ${output:t}"
  print -r -- "$result"
  (( success_count += 1 ))
done

if (( failure_count > 0 )); then
  print -u2 -- "完成：成功 $success_count 个，失败或跳过 $failure_count 个"
  exit 1
fi

print -r -- "完成：成功 $success_count 个"
