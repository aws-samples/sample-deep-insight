
import pandas as pd
import os

df = pd.read_csv('/app/data/yummy-food-market.csv')
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(df.dtypes.to_string())
print(df.head(3).to_string())
print("\n결측치:")
print(df.isnull().sum().to_string())
print("\n매체 unique:", df['매체'].unique())
print("카테고리 unique:", df['카테고리'].unique())
print("상품명 unique:", df['상품명'].unique())
print("날짜 범위:", df['날짜'].min(), "~", df['날짜'].max())
print("날짜 unique count:", df['날짜'].nunique())

os.makedirs('./artifacts/cache', exist_ok=True)
df.to_pickle('./artifacts/cache/df_main.pkl')
print(f"📦 Cached: df_main.pkl")

# 상품-카테고리 매핑 체크
print("\n상품-카테고리 매핑:")
print(df.groupby('상품명')['카테고리'].unique())

# 0 분모 체크
print("\n노출수 0인 행:", (df['노출수']==0).sum())
print("클릭수 0인 행:", (df['클릭수']==0).sum())
print("광고비용 0인 행:", (df['광고비용']==0).sum())
