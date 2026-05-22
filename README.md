# Turtle Investment Framework (龟龟投资策略 v2.0)

基于 Tushare Pro + DeepSeek API 的 A 股价值投资分析框架。

## 架构

```
用户微信 → Hermes Agent → 腾讯云服务器
                          ├── screener_core.py      - Tier1+2 选股器
                          ├── batch_pipeline.py     - 批量采集+估值+报告
                          ├── report_html.py        - MD→HTML 报告转换
                          ├── tushare_collector.py  - 单只数据采集 (17板块)
                          └── valuation_engine.py   - 确定性估值引擎
```

## 快速开始

### 1. 配置 Token

```bash
cp .env.sample .env
# 编辑 .env，填入你的 Tushare Token
# 注册: https://tushare.pro/register
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
# 或: pip install tushare pandas tqdm numpy scipy
```

### 3. 跑选股

```bash
python scripts/screener_core.py --tier2-limit 50 --csv output/screener_results.csv
```

### 4. 跑批量报告

```bash
python scripts/batch_pipeline.py --screener-csv output/screener_results.csv --top 50
```

### 5. 单只深度分析

```bash
# 如果 HTML 已有，直接打开 output/{code}_{name}/*.html
# 如果需要重新生成:
python scripts/report_html.py \
    --input output/000651_格力电器/格力电器_000651_分析报告.md \
    --output output/000651_格力电器/格力电器_000651_分析报告.html
```

## Hermes Agent 配置

将 `prompts/hermes_turtle_system_prompt.md` 设置为 Hermes 的 System Prompt。

配好企业微信机器人 Webhook，即可通过微信语音/文字执行：
- "跑策略" — 全量选股
- "看看票池" — 查看当前结果
- "分析 000651" — 生成某只股票完整分析

## 目录结构

```
├── scripts/                - Python 脚本
├── strategies/turtle/      - 龟龟策略 LLM Prompt
├── shared/qualitative/     - 定性分析模块
├── prompts/                - Hermes 和 LLM prompt
├── output/                 - 运行时输出（已有预跑数据）
└── tests/                  - 单元测试
```

## 已有数据 (2026-05-22)

21 只股票已完成数据采集 + 估值引擎计算，可直接使用查看：

| # | 代码 | 名称 | 评分 | R | FCF Yield |
|---|------|------|------|------|-----------|
| 1 | 000915.SZ | 华特达因 | 0.91 | 7.8% | 18.8% |
| 2 | 000651.SZ | 格力电器 | 0.78 | 5.4% | 8.4% |
| 3 | 600729.SH | 重百集团 | 0.74 | 6.3% | 11.5% |
| 4 | 600351.SH | 亚宝药业 | 0.70 | 6.9% | 10.8% |
| 5 | 601919.SH | 中远海控 | 0.64 | 2.3% | 4.8% |

## 免责声明

本框架仅供参考，不构成投资建议。投资者应自行核实数据并做出决策。
