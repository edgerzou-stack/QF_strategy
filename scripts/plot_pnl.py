import json
import matplotlib.pyplot as plt
import os
import matplotlib
import numpy as np
matplotlib.use('Agg') # For headless environments
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC', 'Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def main():
    flow_dir = "/Users/zouzhengting/Workplace/a_share_factor_flow"
    input_file = os.path.join(flow_dir, "dual_screen.json")
    output_file = os.path.join(flow_dir, "reports/pnl_chart.png")
    
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    trade_history = data.get("trade_history", [])
    if not trade_history:
        print("No trade history available to plot.")
        return
        
    # Convert PnL to actual ratios, e.g. 0.05 for 5%
    pnl_ratios = [t.get("pnl", 0) for t in trade_history if "pnl" in t]
    
    if not pnl_ratios:
        print("No PnL data found.")
        return
        
    pnls = [p * 100 for p in pnl_ratios]
    
    wins_list = [p for p in pnls if p > 0]
    losses_list = [p for p in pnls if p < 0]
    ties_list = [p for p in pnls if p == 0]
    
    wins = len(wins_list)
    losses = len(losses_list)
    ties = len(ties_list)
    total = len(pnls)
    win_rate = (wins / total) * 100 if total > 0 else 0
    
    # Calculate Profit/Loss Ratio and Equal Weight Returns
    avg_win = np.mean(wins_list) if wins > 0 else 0
    avg_loss = np.mean(losses_list) if losses > 0 else 0
    pl_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else float('inf')
    
    # Assume 1 unit invested per trade
    # Net return sum
    net_return_sum = sum(pnls)
    # Average return per trade
    avg_return = np.mean(pnls)
    
    # Create a figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # 1. Pie chart for Win Rate
    labels = ['盈利 (Win)', '亏损 (Loss)', '平局 (Tie)']
    sizes = [wins, losses, ties]
    colors = ['#ff9999', '#66b3ff', '#99ff99']
    
    # Filter out 0 sizes
    labels_filtered = [l for l, s in zip(labels, sizes) if s > 0]
    sizes_filtered = [s for s in sizes if s > 0]
    colors_filtered = [c for c, s in zip(colors, sizes) if s > 0]
    
    ax1.pie(sizes_filtered, labels=labels_filtered, colors=colors_filtered, autopct='%1.1f%%', startangle=90, textprops={'fontsize': 12})
    ax1.set_title(f'历史交割胜率 (总计: {total} 笔)', fontsize=14, pad=20)
    
    # Add text box for metrics
    metrics_text = f"等权总累计净收益: {net_return_sum:+.2f}%"
    props = dict(boxstyle='round,pad=1', facecolor='ivory', alpha=0.8, edgecolor='silver')
    ax1.text(0.5, -0.10, metrics_text, transform=ax1.transAxes, fontsize=12,
            verticalalignment='top', horizontalalignment='center', bbox=props)
    
    # 2. Cumulative Return Line Chart (Equity Curve)
    # Sort trades by exit date
    valid_trades = [t for t in trade_history if "exit_date" in t and "pnl" in t]
    valid_trades.sort(key=lambda x: x["exit_date"])
    
    dates = []
    cum_returns = []
    current_cum = 0.0
    
    # Add initial point
    if valid_trades:
        # Just use the first trade's entry date or a day before the first exit
        dates.append(valid_trades[0].get("entry_date", "2026-05-01"))
        cum_returns.append(0.0)
        
    for t in valid_trades:
        current_cum += (t["pnl"] * 100)
        dates.append(t["exit_date"])
        cum_returns.append(current_cum)
        
    # Plot line chart
    ax2.plot(dates, cum_returns, marker='o', color='royalblue', linewidth=2, markersize=5)
    ax2.fill_between(dates, cum_returns, 0, where=(np.array(cum_returns) >= 0), color='green', alpha=0.1, interpolate=True)
    ax2.fill_between(dates, cum_returns, 0, where=(np.array(cum_returns) < 0), color='red', alpha=0.1, interpolate=True)
    ax2.axhline(0, color='gray', linestyle='dashed', linewidth=1)
    
    ax2.set_title('等权累计净收益曲线 (Equity Curve)', fontsize=14)
    ax2.set_xlabel('平仓日期', fontsize=12)
    ax2.set_ylabel('累计净收益率 (%)', fontsize=12)
    
    # If there are many dates, rotate x labels
    ax2.tick_params(axis='x', rotation=45)
    
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.25) # Make room for text box
    plt.savefig(output_file, dpi=300)
    print(f"Chart saved to {output_file}")
    
    # Also copy to artifacts directory
    import shutil
    artifact_dir = "/Users/zouzhengting/.gemini/antigravity/brain/cb368359-75c4-4195-b42f-77230af3485d"
    artifact_path = os.path.join(artifact_dir, "pnl_chart.png")
    shutil.copy2(output_file, artifact_path)
    print(f"Chart copied to {artifact_path}")

if __name__ == "__main__":
    main()
