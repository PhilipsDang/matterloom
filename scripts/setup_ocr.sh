#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p work/bin work/swift-cache
swiftc -module-cache-path work/swift-cache scripts/vision_ocr.swift -o work/bin/vision-ocr
echo "扫描识别程序已编译；请用扫描样本验证识别结果。"
