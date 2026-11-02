#!/bin/sh
cd "$(dirname "$0")" || exit 1
echo "启动后请在浏览器打开 http://127.0.0.1:8501"
echo "首次使用可选择 查看模拟案卷。按 Control-C 停止。"
sh run.sh
result=$?
if [ "$result" -ne 0 ]; then
  echo "启动未完成，请查看上方错误及 README.md 中的安装说明。"
  read -r answer
fi
exit "$result"
