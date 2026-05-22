#!/usr/bin/env python3
"""Convert Turtle analysis report MD → styled HTML dashboard via DeepSeek API.

Unlike report_html.py (template-based, mechanical), this script sends the
full report to DeepSeek with a carefully crafted design prompt, producing
context-aware HTML that adapts colors, layout, and emphasis to the stock's
specific story (buy / hold / avoid).

Usage:
    python3 scripts/report_html_llm.py \\
        --input output/601919_中远海控/中远海控_601919_分析报告.md \\
        --output output/601919_中远海控/中远海控_601919_分析报告.html

Requirements:
    pip install openai
    .env file with DEEPSEEK_API_KEY=sk-xxx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from config import _load_env_file


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get_deepseek_key() -> str:
    """Get DeepSeek API key from environment."""
    _load_env_file()
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not set.\n"
            "Add it to your .env file: DEEPSEEK_API_KEY=sk-xxx\n"
            "Get a key at: https://platform.deepseek.com/"
        )
    return key


def _call_deepseek(md_text: str, api_key: str, stock_name: str = "") -> str:
    """Send markdown report to DeepSeek, get back styled HTML."""
    try:
        import openai
    except ImportError:
        print("Error: 'openai' package required. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    name_hint = f" for {stock_name}" if stock_name else ""

    system_prompt = f"""You are an expert financial report designer. Your task is to convert a Chinese-language stock analysis report from Markdown to a polished, standalone HTML dashboard{name_hint}.

Design rules:
1. Use a dark gradient hero header (#1c3a5c to #2c5f8a) showing stock code, name, price, and market cap.
2. Place a colored verdict banner below the header. Color based on position recommendation:
   - "标准仓位" or "标准" → green left border
   - "观察" or "等待" or "30%" position → amber left border
   - "不建仓" or "排除" → red left border
3. Build KPI cards in a 4-column grid. Each card has a colored left accent bar:
   - Green: positive metrics (R > II, high ROE, low valuation multiples)
   - Amber: warning metrics (marginal, history near high)
   - Red: failing metrics (R < II, negative margin)
   - Blue: informational (net cash, dividend yield)
4. Financial table: highlight the peak year row, merge a trend column.
5. Valuation section: include a horizontal price-bar showing 10-year low → high → current position with percentage.
6. Penetration return section: show R, GG, II in a 3-card row with a sensitivity table below.
7. Use a two-column responsive layout for advantages vs risks.
8. Value trap checklist: use pass/fail chips (green checkmark / amber warning).
9. Stop-loss conditions: critical items in red, warnings in amber.
10. Pure inline CSS in <style> block. No external dependencies. Max-width 960px. Light background #fafaf7.
11. Font: system UI sans-serif. Monospace for numbers (JetBrains Mono or system-mono).
12. Rounded corners (8-12px). Subtle hover effects on tables. Clean flat design.
13. Footer with disclaimer.
14. Output ONLY the complete HTML. No markdown wrappers, no explanation text.

Color palette:
  green: #1a7a5a, green-bg: #e6f4ee
  amber: #a06c1a, amber-bg: #faf0d8
  red: #c0392b, red-bg: #fceaea
  blue: #2563a0, blue-bg: #e8f0fa
  bg: #fafaf7, bg2: #f0efe9, text: #1c1c1a, text2: #5c5c58, text3: #8a8a84"""

    user_prompt = f"""Convert this Markdown report to the HTML dashboard format described:

{md_text}"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=16000,
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("DeepSeek returned empty response")

    # Strip markdown code fences if present
    content = content.strip()
    if content.startswith("```html"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert Turtle analysis report (MD) to styled HTML via DeepSeek API",
    )
    parser.add_argument("--input", required=True, help="Path to analysis report .md file")
    parser.add_argument("--output", required=True, help="Output .html file path")
    parser.add_argument("--api-key", default=None, help="DeepSeek API key (default: from DEEPSEEK_API_KEY env)")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt only, do not call API")
    args = parser.parse_args()

    # Resolve paths
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = Path.cwd() / input_path
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    # Read input
    md_text = input_path.read_text(encoding="utf-8")

    # Extract stock name for hint
    import re
    name_match = re.search(r'公司名称\s*\|\s*(.+?)\s*\|', md_text)
    stock_name = name_match.group(1).strip() if name_match else ""

    # Get API key
    api_key = args.api_key or _get_deepseek_key()

    if args.dry_run:
        print(f"Would send {len(md_text):,} chars to DeepSeek")
        print(f"Stock: {stock_name}")
        print(f"Output: {output_path}")
        return

    # Call API
    print(f"Sending {len(md_text):,} chars to DeepSeek API ...")
    html = _call_deepseek(md_text, api_key, stock_name)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML report: {output_path}")
    print(f"  Size: {output_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
