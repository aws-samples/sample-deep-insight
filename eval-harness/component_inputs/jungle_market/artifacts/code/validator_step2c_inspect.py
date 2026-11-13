import pickle, json
with open('./artifacts/cache/priority_calcs.pkl', 'rb') as f:
    priority_calcs = pickle.load(f)
by_id = {c['id']: c for c in priority_calcs}
import pandas as pd
with open('./artifacts/cache/df_main.pkl', 'rb') as f:
    df = pickle.load(f)
print("categories:", sorted(df['category'].unique()))
print("promo_code unique:", df['promo_code'].unique()[:10])
print("customer_type unique:", df['customer_type'].unique())

# print remaining calc details for inspection
remaining_ids = ['aov','discount_rate','new_order_share','returning_order_share','new_sales_share',
 'returning_sales_share','aov_new','aov_returning','week1_sales','week2_sales','wow_growth',
 'daily_avg_sales','next_month_baseline','peak_dow','peak_hour','peak_hour_sales',
 'top20_product_share','top10pct_cust_sales_share','top20pct_cust_sales_share',
 'repeat_customers','repeat_rate','churn_risk_customers','churn_risk_rate','avg_repurchase_interval',
 'best_age_gender_aov_value','channel_aov_App','channel_aov_Web','aov_with_promo','aov_without_promo',
 'multi_item_order_share','corr_value_nitems','s1_target_customers']
for rid in remaining_ids:
    c = by_id.get(rid)
    if c:
        print(rid, '::', c['value'], '::', c['formula'], '::', c['source_file'], '::', c.get('source_columns'))
