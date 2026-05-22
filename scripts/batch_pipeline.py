#!/usr/bin/env python3
"""Batch Pipeline — 选股结果 → 批量数据采集 + 估值 → 汇编报告.

Usage:
    python3 scripts/batch_pipeline.py \\
        --screener-csv output/screener_results.csv \\
        --top 50 \\
        --llm-top 5

What it does:
    1. 读取 screener_results.csv，取 composite_score 最高的 N 只
    2. 逐只运行 tushare_collector.py → data_pack_market.md
    3. 逐只运行 valuation_engine.py → valuation_computed.md
    4. 生成 batch_report.html（50只概览仪表盘）
    5. 输出 batch_llm_candidates.json（供 LLM 精研管线消费）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OUTPUT_DIR = PROJECT_ROOT / "output"
PYTHON = sys.executable  # 使用当前 venv 的 Python

# 估值指标中文标签
METRIC_LABELS = {
    "composite_score": ("综合评分", ""),
    "R": ("穿透回报率 R", "%"),
    "II": ("门槛 II", "%"),
    "R_vs_II": ("R vs II", "pct"),
    "fcf_yield": ("FCF 收益率", "%"),
    "ev_ebitda": ("EV/EBITDA", "x"),
    "cash_adj_pe": ("扣现 PE", "x"),
    "floor_premium": ("底线溢价", "%"),
    "roe_waa": ("ROE 5Y", "%"),
    "fcf_margin": ("FCF 利润率", "%"),
    "net_debt_ebitda": ("净负债/EBITDA", "x"),
    "goodwill_ratio": ("商誉/总资产", "%"),
}


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def run_tushare_collector(ts_code: str, output_path: Path, python_path: str = PYTHON) -> bool:
    """Run tushare_collector.py for a single stock."""
    cmd = [
        python_path,
        str(SCRIPTS_DIR / "tushare_collector.py"),
        "--code", ts_code,
        "--output", str(output_path),
    ]
    print(f"  [tushare] {ts_code} → {output_path.name} ...", end=" ", flush=True)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=120,
        )
        if result.returncode == 0 and output_path.exists():
            size = output_path.stat().st_size
            print(f"OK ({size:,} bytes)")
            return True
        else:
            print(f"FAILED (rc={result.returncode})")
            if result.stderr:
                print(f"    stderr: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def run_valuation_engine(code_only: str, output_dir: Path, python_path: str = PYTHON) -> bool:
    """Run valuation_engine.py for a single stock.

    valuation_engine expects code without market suffix (e.g., '600887' not '600887.SH').
    """
    cmd = [
        python_path,
        str(SCRIPTS_DIR / "valuation_engine.py"),
        "--code", code_only,
        "--output-dir", str(output_dir),
    ]
    print(f"  [valuation] {code_only} → {output_dir.name}/ ...", end=" ", flush=True)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=120,
        )
        # valuation_engine writes valuation_computed.md + valuation_sensitivities.csv
        expected = output_dir / "valuation_computed.md"
        if result.returncode == 0 and expected.exists():
            size = expected.stat().st_size
            print(f"OK ({size:,} bytes)")
            return True
        else:
            print(f"FAILED (rc={result.returncode})")
            if result.stderr:
                print(f"    stderr: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def _generate_html_report(md_path: Path, html_path: Path, python_path: str = PYTHON) -> bool:
    """Generate HTML from a markdown analysis report using report_html.py."""
    print(f"  [html] {md_path.name} → {html_path.name} ...", end=" ", flush=True)
    try:
        result = subprocess.run(
            [python_path, str(SCRIPTS_DIR / "report_html.py"),
             "--input", str(md_path), "--output", str(html_path)],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=30,
        )
        if result.returncode == 0 and html_path.exists():
            print(f"OK ({html_path.stat().st_size:,}b)")
            return True
        else:
            print(f"FAILED")
            if result.stderr:
                print(f"    {result.stderr[:150]}")
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def extract_code_only(ts_code: str) -> str:
    """Extract digits-only code from ts_code (e.g., '600887.SH' → '600887')."""
    return ts_code.split(".")[0]


def extract_metrics_from_valuation(output_dir: Path) -> dict:
    """Extract key metrics from valuation_computed.md."""
    vfile = output_dir / "valuation_computed.md"
    metrics = {}
    if not vfile.exists():
        return metrics

    text = vfile.read_text(encoding="utf-8")
    import re

    patterns = {
        "classification": r"公司分类[：:]\s*\*?\*?(.+?)\*?\*?",
        "fair_value": r"公允价值[：:]\s*(\d+\.?\d*)",
        "implied_growth": r"隐含增长率[：:]\s*(\d+\.?\d*)%",
        "wacc": r"WACC[：:]\s*(\d+\.?\d*)%",
        "margin_of_safety": r"安全边际[：:]\s*([+-]?\d+\.?\d*)%",
        "terminal_value_pct": r"终值占比[：:]\s*(\d+\.?\d*)%",
    }

    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().strip("*")
            try:
                metrics[key] = float(val)
            except ValueError:
                metrics[key] = val

    return metrics


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

_CSS = """
:root{--bg:#fafaf7;--bg2:#f0efe9;--bg3:#e8e7e0;--text:#1c1c1a;--text2:#5c5c58;--text3:#8a8a84;--border:rgba(0,0,0,.08);--accent:#1a1a18;--green:#1a7a5a;--green-bg:#e6f4ee;--red:#c0392b;--red-bg:#fceaea;--amber:#a06c1a;--amber-bg:#faf0d8;--blue:#2563a0;--blue-bg:#e8f0fa}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Noto Sans SC',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.7;font-size:14px}
.container{max-width:960px;margin:0 auto;padding:32px 24px 64px}
.header{border-bottom:2px solid var(--accent);padding-bottom:24px;margin-bottom:32px}
.header h1{font-size:24px;font-weight:500;margin-bottom:4px}
.header .meta{font-size:13px;color:var(--text3)}
.summary{background:var(--bg2);border-radius:12px;padding:20px 24px;margin-bottom:32px;font-size:13px;color:var(--text2);line-height:1.8}
.summary strong{color:var(--text)}
h2{font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:1.5px;color:var(--text3);margin:40px 0 16px;padding-bottom:8px;border-bottom:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:13px;margin:16px 0}
th{text-align:left;padding:8px 10px;font-weight:400;color:var(--text3);border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}
th:not(:first-child){text-align:right}
td{padding:8px 10px;border-bottom:1px solid var(--border)}
td:not(:first-child){text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px}
tr:hover{background:var(--bg2)}
tr.top5{background:var(--green-bg)}
tr.top5 td:first-child{font-weight:500}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:4px;font-weight:500}
.badge-green{background:var(--green-bg);color:var(--green)}
.badge-amber{background:var(--amber-bg);color:var(--amber)}
.badge-red{background:var(--red-bg);color:var(--red)}
.status-ok{color:var(--green)}
.status-fail{color:var(--red)}
.footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--border);font-size:12px;color:var(--text3);line-height:1.8}
.callout{padding:16px 20px;background:var(--bg2);border-radius:8px;margin:20px 0;font-size:13px;color:var(--text2);line-height:1.7}
.callout.llm-info{background:var(--blue-bg);border-left:4px solid var(--blue)}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
"""


def _to_num(v):
    """Safely convert to float, return None on failure."""
    if v is None or pd.isna(v):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_float(v):
    """Used in JSON serialization."""
    n = _to_num(v)
    return float(n) if n is not None else None


def _color_r_vs_ii(val):
    """Color code for R vs II."""
    v = _to_num(val)
    if v is None:
        return ("-", "")
    if v > 2.0:
        return (f"{v:+.1f}pct", "badge-green")
    elif v > 0:
        return (f"{v:+.1f}pct", "badge-amber")
    else:
        return (f"{v:+.1f}pct", "badge-red")


def _color_fcf_yield(val):
    v = _to_num(val)
    if v is None:
        return ("-", "")
    if v > 8:
        return (f"{v:.1f}%", "badge-green")
    elif v > 4:
        return (f"{v:.1f}%", "badge-amber")
    else:
        return (f"{v:.1f}%", "badge-red")


def _color_ev_ebitda(val):
    v = _to_num(val)
    if v is None:
        return ("-", "")
    if v < 10:
        return (f"{v:.1f}x", "badge-green")
    elif v < 20:
        return (f"{v:.1f}x", "badge-amber")
    else:
        return (f"{v:.1f}x", "badge-red")


def generate_html(df: pd.DataFrame, top5_codes: list, output_path: Path, meta: dict) -> None:
    """Generate combined batch HTML report."""
    df = df.copy()

    def _fmt(v, fmt_str=".1f"):
        if v is None or pd.isna(v):
            return "-"
        try:
            return f"{float(v):{fmt_str}}"
        except (ValueError, TypeError):
            return str(v)

    rows_html = []
    for i, (_, row) in enumerate(df.iterrows()):
        ts_code = row.get("ts_code", "")
        name = row.get("name", "")
        is_top5 = ts_code in top5_codes
        row_class = ' class="top5"' if is_top5 else ""

        r_vs_ii, r_badge = _color_r_vs_ii(row.get("R_vs_II"))
        fcf_y, fcf_b = _color_fcf_yield(row.get("fcf_yield"))
        ev_eb, ev_b = _color_ev_ebitda(row.get("ev_ebitda"))

        rows_html.append(f"""<tr{row_class}>
            <td>{i + 1}</td>
            <td>{ts_code}</td>
            <td>{name}</td>
            <td>{row.get('industry', '-')}</td>
            <td>{_fmt(row.get('composite_score'), '.2f')}</td>
            <td>{_fmt(row.get('R'), '.1f')}%</td>
            <td><span class="badge {r_badge}">{r_vs_ii}</span></td>
            <td><span class="badge {fcf_b}">{fcf_y}</span></td>
            <td><span class="badge {ev_b}">{ev_eb}</span></td>
            <td>{_fmt(row.get('floor_premium'), '.1f')}%</td>
            <td>{_fmt(row.get('roe_waa'), '.1f')}%</td>
        </tr>""")

    llm_html = ""
    if top5_codes:
        llm_items = []
        for code in top5_codes:
            match = df[df["ts_code"] == code]
            if not match.empty:
                r = match.iloc[0]
                llm_items.append(
                    f"<li>{r['ts_code']} {r['name']} — R={_fmt(r.get('R'),'.1f')}%, "
                    f"Score={_fmt(r.get('composite_score'),'.2f')}</li>"
                )
        if llm_items:
            llm_html = f"""<div class="callout llm-info">
                <strong>LLM 精研候选（Top {len(top5_codes)}）</strong>
                <ol style="margin:8px 0 0 18px; color:var(--text2); font-size:13px;">
                    {"".join(llm_items)}
                </ol>
                <p style="margin-top:8px;font-size:12px;color:var(--text3)">
                    数据已就绪（data_pack_market.md + valuation_computed.md），可直接走 /business-analysis → Agent B → Agent C 生成完整投资报告。
                </p>
            </div>"""

    html = f"""<style>{_CSS}</style>
<div class="container">
<div class="header">
    <h1>龟龟投资策略 · 批量选股报告</h1>
    <div class="meta">
        生成时间: {meta['generated_at']} | 
        选股日期: {meta['screener_date']} |
        数据源: Tushare Pro | 
        候选数: {meta['total_stocks']} 只 |
        LLM精研: Top {meta['llm_top']} 只
    </div>
</div>

<div class="summary">
    <strong>筛选摘要</strong>
    <table style="margin-top:12px">
        <tr><td>选股器路径</td><td>{meta['screener_csv']}</td></tr>
        <tr><td>筛选条件</td><td>上市 ≥5年 | 市值 ≥50亿 | PE &gt; 0（主通道）| PE=NaN（观察通道）</td></tr>
        <tr><td>评分维度</td><td>ROE (5Y) + FCF Yield + 穿透回报率 R + EV/EBITDA + 底线溢价</td></tr>
        <tr><td>成功采集</td><td>{meta['collect_ok']} / {meta['total_stocks']} 只</td></tr>
        <tr><td>成功估值</td><td>{meta['valu_ok']} / {meta['total_stocks']} 只</td></tr>
    </table>
</div>

{llm_html}

<h2>排名表</h2>
<div style="overflow-x:auto">
<table>
<thead>
<tr>
    <th>#</th><th>代码</th><th>名称</th><th>行业</th>
    <th>综合评分</th><th>R</th><th>R vs II</th><th>FCF Yield</th><th>EV/EBITDA</th>
    <th>底线溢价</th><th>ROE 5Y</th>
</tr>
</thead>
<tbody>
{"".join(rows_html)}
</tbody>
</table>
</div>

<div class="footer">
    <p>本报告由 AI 模型基于龟龟投资策略 v2 框架自动生成，仅供参考，不构成投资建议。</p>
    <p>数据来源: Tushare Pro (tushare_collector.py) + valuation_engine.py | 框架: 龟龟投资策略 v2.0</p>
</div>
</div>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="批处理管道: 选股结果 → 采集 → 估值 → 报告",
    )
    parser.add_argument(
        "--screener-csv", required=True,
        help="Path to screener_results.csv",
    )
    parser.add_argument(
        "--top", type=int, default=50,
        help="Number of top stocks to process (default: 50)",
    )
    parser.add_argument(
        "--llm-top", type=int, default=5,
        help="Number of top stocks to flag for LLM deep analysis (default: 5)",
    )
    parser.add_argument(
        "--skip-collect", action="store_true",
        help="Skip data collection (use existing data_pack_market.md)",
    )
    parser.add_argument(
        "--skip-valuation", action="store_true",
        help="Skip valuation engine (use existing valuation_computed.md)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output report path (default: output/batch_report.html)",
    )
    parser.add_argument(
        "--auto-html", action="store_true",
        help="Auto-generate HTML report for each stock that has an analysis .md file",
    )
    args = parser.parse_args()

    # Resolve paths
    csv_path = Path(args.screener_csv)
    if not csv_path.is_absolute():
        csv_path = PROJECT_ROOT / csv_path
    if not csv_path.exists():
        print(f"Error: Screener CSV not found: {csv_path}")
        sys.exit(1)

    # Read & sort
    df = pd.read_csv(csv_path)
    if "composite_score" not in df.columns:
        print("Error: CSV missing 'composite_score' column. Run screener first.")
        sys.exit(1)

    df = df.sort_values("composite_score", ascending=False)
    df = df.head(args.top)
    print(f"Loaded {len(df)} stocks from {csv_path}")

    # Process each stock
    collect_ok = 0
    valu_ok = 0

    for i, (_, row) in enumerate(df.iterrows()):
        ts_code = row["ts_code"]
        name = row.get("name", ts_code)
        code_only = extract_code_only(ts_code)
        label = f"{code_only}_{name}"

        print(f"\n[{i+1}/{len(df)}] {ts_code} {name}")

        stock_dir = OUTPUT_DIR / label
        stock_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Data collection
        dp_path = stock_dir / "data_pack_market.md"
        if args.skip_collect and dp_path.exists():
            print("  [tushare] SKIP (existing)")
            collect_ok += 1
        else:
            ok = run_tushare_collector(ts_code, dp_path)
            if ok:
                collect_ok += 1

        # Step 2: Valuation
        v_path = stock_dir / "valuation_computed.md"
        if args.skip_valuation and v_path.exists():
            print("  [valuation] SKIP (existing)")
            valu_ok += 1
        else:
            ok = run_valuation_engine(code_only, stock_dir)
            if ok:
                valu_ok += 1

        # Step 3: Auto-generate HTML if analysis report exists
        if args.auto_html:
            report_md = stock_dir / f"{name}_{code_only}_分析报告.md"
            if report_md.exists():
                report_html = stock_dir / f"{name}_{code_only}_分析报告.html"
                if not report_html.exists() or report_md.stat().st_mtime > report_html.stat().st_mtime:
                    _generate_html_report(report_md, report_html)

        # Brief pause to avoid API rate limits
        if i < len(df) - 1:
            time.sleep(0.5)

    # Generate HTML report
    output_path = Path(args.output) if args.output else OUTPUT_DIR / "batch_report.html"
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    top5_codes = df.head(args.llm_top)["ts_code"].tolist()

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "screener_date": datetime.fromtimestamp(csv_path.stat().st_mtime).strftime("%Y-%m-%d"),
        "screener_csv": str(csv_path),
        "total_stocks": len(df),
        "llm_top": args.llm_top,
        "collect_ok": collect_ok,
        "valu_ok": valu_ok,
    }

    generate_html(df, top5_codes, output_path, meta)
    print(f"\nHTML report: {output_path}")

    # Export LLM candidates JSON
    llm_json = OUTPUT_DIR / "batch_llm_candidates.json"
    candidates = []
    for _, row in df.head(args.llm_top).iterrows():
        ts_code = row["ts_code"]
        code_only = extract_code_only(ts_code)
        name = row.get("name", ts_code)
        stock_dir = OUTPUT_DIR / f"{code_only}_{name}"
        candidates.append({
            "ts_code": ts_code,
            "code_only": code_only,
            "name": name,
            "composite_score": float(row["composite_score"]),
            "R": _safe_float(row.get("R")),
            "R_vs_II": _safe_float(row.get("R_vs_II")),
            "fcf_yield": _safe_float(row.get("fcf_yield")),
            "data_pack": str(stock_dir / "data_pack_market.md"),
            "valuation": str(stock_dir / "valuation_computed.md"),
            "output_dir": str(stock_dir),
        })
    llm_json.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"LLM candidates: {llm_json}")

    # Summary
    print(f"\n=== 完成 ===")
    print(f"  采集: {collect_ok}/{len(df)}")
    print(f"  估值: {valu_ok}/{len(df)}")
    print(f"  报告: {output_path}")
    print(f"\n下一步（LLM精研 Top {args.llm_top}）:")
    for c in candidates:
        print(f"  /business-analysis {c['ts_code']}")


if __name__ == "__main__":
    main()
