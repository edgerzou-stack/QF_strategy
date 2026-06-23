import json
import sys
import os

def render_table(title, items, headers):
    res = f"## {title} (入选 {len(items)} 只)\n\n"
    if len(items) == 0:
        return res + "暂无符合条件的标的。\n\n"
    
    res += "| " + " | ".join(headers) + " |\n"
    res += "|" + "|".join(["---"] * len(headers)) + "|\n"
    for row in items:
        cells = []
        for h in headers:
            val = row.get(h)
            if val is None:
                cells.append("")
            elif isinstance(val, float):
                cells.append(f"{val:.2f}")
            else:
                cells.append(str(val))
        res += "| " + " | ".join(cells) + " |\n"
    return res + "\n\n"

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 generate_report.py <input_json> <output_md>")
        sys.exit(1)
        
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        sys.exit(1)
        
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    results = data.get("results", {})
    div_results = results.get("dividend", [])
    gro_results = results.get("growth", [])
    diff = data.get("diff", {})

    out = f"# A 股全市场双核心策略筛选结果\n\n"
    out += f"本次运行基于当前最新行情快照，自动同步计算出以下两大策略标的池。\n\n"

    # 1. 红利策略
    div_headers = [
        "股票代码", "股票简称", "PE", "PB", "估值公式值", "TTM股息率",
        "总市值(亿元)", "3年连续双增长", "3年平均净利率", "3年净利润CAGR", "3年经营现金流平均增速", "资产负债率"
    ]
    out += render_table("一、稳健红利策略 (Dividend Strategy)", div_results, div_headers)

    div_diff = diff.get("dividend", {})
    if div_diff.get("added") or div_diff.get("removed"):
        out += "> **红利策略调仓提示**：\n"
        if div_diff.get("added"):
            out += f"> 🟢 **新增入池**：{', '.join(div_diff['added'])}\n"
        if div_diff.get("removed"):
            out += f"> 🔴 **掉出观测**：{', '.join(div_diff['removed'])}\n"
        out += "\n\n"

    # 2. 成长策略
    gro_headers = [
        "股票代码", "股票简称", "所处行业", "PE", "PB", "TTM股息率",
        "总市值(亿元)", "3年连续双增长", "3年平均净资产收益率", "3年平均净利率", "3年净利润CAGR", "3年营收CAGR", "资产负债率"
    ]
    out += render_table("二、高增成长策略 (Growth Strategy)", gro_results, gro_headers)

    gro_diff = diff.get("growth", {})
    if gro_diff.get("added") or gro_diff.get("removed"):
        out += "> **成长策略调仓提示**：\n"
        if gro_diff.get("added"):
            out += f"> 🟢 **新增入池**：{', '.join(gro_diff['added'])}\n"
        if gro_diff.get("removed"):
            out += f"> 🔴 **掉出观测**：{', '.join(gro_diff['removed'])}\n"
        out += "\n\n"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(out)
        
if __name__ == "__main__":
    main()
