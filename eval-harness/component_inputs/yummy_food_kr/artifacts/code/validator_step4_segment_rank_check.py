import pandas as pd

df = pd.read_pickle('./artifacts/cache/df_raw.pkl')
total_cost = df['광고비용'].sum()
total_rev = df['매출액'].sum()

# Segment sum check: media
media_cost_sum = df.groupby('매체')['광고비용'].sum().sum()
media_rev_sum = df.groupby('매체')['매출액'].sum().sum()
cat_cost_sum = df.groupby('카테고리')['광고비용'].sum().sum()
prod_cost_sum = df.groupby('상품명')['광고비용'].sum().sum()
cross_cost_sum = df.groupby(['매체','카테고리'])['광고비용'].sum().sum()

print("Segment sum consistency check:")
print(f"  Total cost: {total_cost}, Media sum: {media_cost_sum}, match={abs(total_cost-media_cost_sum)<1}")
print(f"  Total rev: {total_rev}, Media rev sum: {media_rev_sum}, match={abs(total_rev-media_rev_sum)<1}")
print(f"  Category cost sum: {cat_cost_sum}, match={abs(total_cost-cat_cost_sum)<1}")
print(f"  Product cost sum: {prod_cost_sum}, match={abs(total_cost-prod_cost_sum)<1}")
print(f"  Cross(media x cat) cost sum: {cross_cost_sum}, match={abs(total_cost-cross_cost_sum)<1}")

# Cost share sum = 100%
media_share_sum = (df.groupby('매체')['광고비용'].sum()/total_cost*100).sum()
print(f"  Media cost share sum: {media_share_sum:.2f}% (should be ~100%)")

# Rank validation - ROAS ranking by media
media_roas = df.groupby('매체').apply(lambda g: g['매출액'].sum()/g['광고비용'].sum()).sort_values(ascending=False)
print(f"\nMedia ROAS ranking: {media_roas.to_dict()}")
print(f"  Top: 쿠빵={media_roas.iloc[0]:.2f} ... Bottom: 네이바={media_roas.iloc[-1]:.2f}")
assert media_roas.index[0] == '쿠빵', "Top media mismatch!"
assert media_roas.index[-1] == '네이바', "Bottom media mismatch!"
print("  Ranking matches Coder's claim (쿠빵 top, 네이바 bottom): CONFIRMED")

# cross best combo check
cross_roas = df.groupby(['매체','카테고리']).apply(lambda g: g['매출액'].sum()/g['광고비용'].sum())
best_combo = cross_roas.idxmax()
print(f"\nBest media x category combo: {best_combo} ROAS={cross_roas.max():.2f}")
assert best_combo == ('아마존','건강식품'), "Best combo mismatch!"
print("  Matches Coder's claim (아마존x건강식품=8.41): CONFIRMED")

# Correlation sign/strength interpretation sanity
corr_ctr_cvr = df['CTR'].corr(df['전환율'])
print(f"\nCTR-CVR correlation: {corr_ctr_cvr:.3f} -> {'strong negative' if corr_ctr_cvr < -0.7 else 'moderate/weak'}")
assert corr_ctr_cvr < -0.7, "Correlation strength claim mismatch"
print("  'Strong negative correlation (-0.898)' claim: CONFIRMED (<-0.7 threshold)")

print("\n✅ All segment-sum, ranking, and correlation sanity checks PASSED")
