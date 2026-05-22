#!/bin/bash
# Turtle Framework 腾讯云一键部署脚本
# 用法: bash deploy.sh
# 需要先配置 .env 中的 TUSHARE_TOKEN

set -e

echo "=== 龟龟投资策略 v2.0 部署脚本 ==="

# 1. 安装系统依赖
apt update
apt install -y python3 python3-pip git curl

# 2. 克隆（如果已存在则跳过）
if [ ! -d /root/turtle-framework ]; then
    echo "请将 Turtle-Framework 文件夹上传到 /root/turtle-framework"
    exit 1
fi

cd /root/turtle-framework

# 3. 安装 Python 依赖
pip3 install -r requirements.txt
echo "依赖安装完成"

# 4. 检查 .env
if [ ! -f .env ]; then
    cp .env.sample .env
    echo "⚠️  请编辑 .env 填入 TUSHARE_TOKEN"
    echo "   然后运行: python3 scripts/tushare_collector.py --code 600519.SH --dry-run"
    exit 0
fi

# 5. 验证连接
echo "=== 验证 Tushare 连接 ==="
python3 scripts/tushare_collector.py --code 600519.SH --dry-run || true

echo ""
echo "=== 部署完成 ==="
echo ""
echo "下一步:"
echo "  1. 首次运行: python3 scripts/screener_core.py --tier2-limit 50 --csv output/screener_results.csv"
echo "  2. 批量处理: python3 scripts/batch_pipeline.py --screener-csv output/screener_results.csv --top 50"
echo "  3. Hermes System Prompt 已放在 prompts/hermes_turtle_system_prompt.md"
echo "  4. 已有数据在 output/ 目录下，可直接使用"
