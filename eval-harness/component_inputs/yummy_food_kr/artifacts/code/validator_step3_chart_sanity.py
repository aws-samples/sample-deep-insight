import pandas as pd, os

chart_data_files = {
    "chart1_media_cost_vs_roas": ("./artifacts/media_agg.csv", "ROAS"),
    "chart2_category_metrics": ("./artifacts/category_agg.csv", "ROAS"),
    "chart3_product_roas_ranking": ("./artifacts/product_agg.csv", "ROAS"),
    "chart4_cost_vs_roas_bubble": ("./artifacts/product_agg.csv", "광고비용"),
    "chart5_media_category_heatmap": ("./artifacts/cross_pivot_roas.csv", None),  # pivot, check all numeric cols
    "chart6_daily_roas_trend": ("./artifacts/daily_trend.csv", "ROAS"),
}

failures = []
for chart, (path, col) in chart_data_files.items():
    if not os.path.exists(path):
        failures.append(f"{chart}: source file missing — {path}")
        continue
    df = pd.read_csv(path)
    if col is None:
        numeric = df.select_dtypes(include='number')
        total = numeric.fillna(0).abs().sum().sum()
        if total == 0:
            failures.append(f"{chart}: all numeric values zero/NaN in {path}")
        else:
            print(f"{chart}: OK (pivot sum={total:.2f}, shape={df.shape})")
        continue
    if col not in df.columns:
        failures.append(f"{chart}: column '{col}' missing in {path}, cols={list(df.columns)}")
        continue
    s = df[col].fillna(0).abs().sum()
    if s == 0:
        failures.append(f"{chart}: all values in '{col}' are zero/NaN")
    else:
        print(f"{chart}: OK ({col} sum={s:.2f}, rows={len(df)})")

if failures:
    print("\nChart data sanity check FAILED:")
    for f in failures:
        print(f"  - {f}")
else:
    print(f"\nChart data sanity: {len(chart_data_files)}/{len(chart_data_files)} non-zero - ALL PASS")
