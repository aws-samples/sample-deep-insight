import pandas as pd, pickle, json, numpy as np

with open('./artifacts/cache/priority_calcs.pkl', 'rb') as f:
    priority_calcs = pickle.load(f)

# Load raw data
df_raw = pd.read_csv('/app/data/yummy-food-market.csv')
print(f"Raw columns: {list(df_raw.columns)}")
print(f"Raw shape: {df_raw.shape}")

# Load coder-generated artifacts (ground truth for their own derived calcs)
df_media = pd.read_csv('./artifacts/media_agg.csv')
print(f"media_agg columns: {list(df_media.columns)}")
df_cross = pd.read_csv('./artifacts/cross_media_category.csv')
print(f"cross_media_category columns: {list(df_cross.columns)}")

# cache for next step
import os
os.makedirs('./artifacts/cache', exist_ok=True)
df_raw.to_pickle('./artifacts/cache/df_raw.pkl')
df_media.to_pickle('./artifacts/cache/df_media.pkl')
df_cross.to_pickle('./artifacts/cache/df_cross.pkl')
print("Cached raw/media/cross dataframes")
