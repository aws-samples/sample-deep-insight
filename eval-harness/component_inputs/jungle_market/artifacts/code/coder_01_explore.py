
import pandas as pd
import numpy as np
import os

df = pd.read_csv('/app/data/jungle-market-sales.csv')
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(df.dtypes.to_string())
print(df.head(3).to_string())

n_dup = int(df.duplicated().sum())
print(f"Exact duplicate rows: {n_dup}")

# order_id has multiple rows per order (line items) -> no identifier makes a full-row dup suspicious
# check if dup rows look like true re-scans (same order_id+product_id+everything)
if n_dup > 0:
    dup_rows = df[df.duplicated(keep=False)]
    print(dup_rows.head(10).to_string())

print("\nMissing values per column:")
print(df.isna().sum().to_string())

print("\norder_date range:", df['order_date'].min(), "-", df['order_date'].max())
print("unique customers:", df['customer_id'].nunique())
print("unique orders:", df['order_id'].nunique())
print("unique products:", df['product_id'].nunique())
print("customer_type values:", df['customer_type'].unique())
print("channel values:", df['channel'].unique())
print("city values:", df['city'].unique())
print("country values:", df['country'].unique())
print("category values:", df['category'].unique())
print("promo_code values:", df['promo_code'].unique())
print("gender values:", df['gender'].unique())
print("age_group values:", df['age_group'].unique())

print("\nunit_price stats:\n", df['unit_price'].describe().to_string())
print("\nquantity stats:\n", df['quantity'].describe().to_string())
print("\ndiscount stats:\n", df['discount'].describe().to_string())
print("\nline_total stats:\n", df['line_total'].describe().to_string())

# verify line_total formula
calc_total = df['unit_price'] * df['quantity'] - df['discount']
diff = (calc_total - df['line_total']).abs()
print("\nmax diff line_total vs calc:", diff.max())

os.makedirs('./artifacts/cache', exist_ok=True)

# Handle duplicates: since order_id + product can repeat legitimately? let's check real dup definition
if n_dup > 0:
    df_clean = df.drop_duplicates()
    print(f"\nDropped {n_dup} exact duplicate rows -> {len(df_clean)} rows remain")
else:
    df_clean = df.copy()
    print("\nNo exact duplicate rows found; keeping all rows")

df_clean['order_date'] = pd.to_datetime(df_clean['order_date'])
df_clean.to_pickle('./artifacts/cache/df_main.pkl')
print(f"📦 Cached: df_main.pkl, shape={df_clean.shape}")
print(df_clean.dtypes.to_string())
