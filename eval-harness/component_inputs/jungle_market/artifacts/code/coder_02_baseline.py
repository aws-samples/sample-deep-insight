
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')

# duplicates before/after
df_raw = pd.read_csv('/app/data/jungle-market-sales.csv')
n_before = len(df_raw)
n_after = len(df)
track_calculation("dup_before", n_before, "원본 데이터 총 행 수(중복 제거 전)", "COUNT(rows) raw csv",
                   source_file="/app/data/jungle-market-sales.csv", importance="low")
track_calculation("dup_after", n_after, "중복 제거 후 총 행 수", "COUNT(rows) after drop_duplicates()",
                   source_file="./artifacts/cache/df_main.pkl", importance="low")

# Baseline metrics
total_sales = df['line_total'].sum()
n_orders = df['order_id'].nunique()
n_customers = df['customer_id'].nunique()
aov = df.groupby('order_id')['line_total'].sum().mean()
avg_qty = df['quantity'].mean()
total_gross = (df['unit_price'] * df['quantity']).sum()
total_discount = df['discount'].sum()
discount_rate = total_discount / total_gross

track_calculation("total_sales", total_sales, "전체 매출(line_total 합계)", "SUM(line_total)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["line_total"], importance="high")
track_calculation("n_orders", n_orders, "총 주문 수(고유 order_id)", "COUNT(DISTINCT order_id)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id"], importance="high")
track_calculation("n_customers", n_customers, "총 고객 수(고유 customer_id)", "COUNT(DISTINCT customer_id)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_id"], importance="high")
track_calculation("aov", aov, "평균 주문 금액(AOV)", "MEAN(SUM(line_total) GROUP BY order_id)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","line_total"], importance="high")
track_calculation("avg_qty", avg_qty, "라인 아이템 평균 구매 수량", "MEAN(quantity)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["quantity"], importance="medium")
track_calculation("discount_rate", discount_rate, "전체 할인율", "SUM(discount) / SUM(unit_price*quantity)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["discount","unit_price","quantity"], importance="high")

print(f"총매출: {total_sales:,.2f}")
print(f"주문수: {n_orders}, 고객수: {n_customers}")
print(f"AOV: {aov:,.2f}")
print(f"평균구매수량(라인): {avg_qty:.2f}")
print(f"총할인: {total_discount:,.2f}, 할인율: {discount_rate:.2%}")

# per-order lines (basket size)
lines_per_order = df.groupby('order_id').size()
avg_lines_per_order = lines_per_order.mean()
track_calculation("avg_lines_per_order", avg_lines_per_order, "주문당 평균 상품 종류 수(장바구니 크기)",
                   "MEAN(COUNT(rows) GROUP BY order_id)", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_id"], importance="medium")
print(f"주문당 평균 품목수: {avg_lines_per_order:.2f}")

# customer_type split
cust_type_orders = df.groupby('customer_type')['order_id'].nunique()
cust_type_sales = df.groupby('customer_type')['line_total'].sum()
new_order_share = cust_type_orders.get('New',0) / n_orders
returning_order_share = cust_type_orders.get('Returning',0) / n_orders
new_sales_share = cust_type_sales.get('New',0) / total_sales
returning_sales_share = cust_type_sales.get('Returning',0) / total_sales

track_calculation("new_order_share", new_order_share, "신규 고객 주문 비중", "COUNT(order_id WHERE customer_type='New')/COUNT(order_id)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_type","order_id"], importance="high")
track_calculation("returning_order_share", returning_order_share, "재구매 고객 주문 비중", "COUNT(order_id WHERE customer_type='Returning')/COUNT(order_id)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_type","order_id"], importance="high")
track_calculation("new_sales_share", new_sales_share, "신규 고객 매출 비중", "SUM(line_total WHERE customer_type='New')/SUM(line_total)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_type","line_total"], importance="high")
track_calculation("returning_sales_share", returning_sales_share, "재구매 고객 매출 비중", "SUM(line_total WHERE customer_type='Returning')/SUM(line_total)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_type","line_total"], importance="high")

print(f"신규 주문비중:{new_order_share:.2%}, 재구매 주문비중:{returning_order_share:.2%}")
print(f"신규 매출비중:{new_sales_share:.2%}, 재구매 매출비중:{returning_sales_share:.2%}")

# AOV by customer_type
aov_by_type = df.groupby(['customer_type','order_id'])['line_total'].sum().groupby('customer_type').mean()
track_calculation("aov_new", aov_by_type.get('New',0), "신규 고객 AOV", "MEAN(SUM(line_total) GROUP BY order_id) WHERE customer_type='New'",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_type","order_id","line_total"], importance="high")
track_calculation("aov_returning", aov_by_type.get('Returning',0), "재구매 고객 AOV", "MEAN(SUM(line_total) GROUP BY order_id) WHERE customer_type='Returning'",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_type","order_id","line_total"], importance="high")
print(aov_by_type)

save_calculation_metadata()

with open('./artifacts/all_results.txt', 'w', encoding='utf-8') as f:
    f.write(f"""# Jungle Market 매출 데이터 분석 결과

## 데이터 개요
- 분석 기간: {df['order_date'].min().date()} ~ {df['order_date'].max().date()} (2주간)
- 원본 행 수: {n_before:,}건 -> 완전 중복 {n_before-n_after}건 제거 -> 분석 대상 {n_after:,}건
- 총 주문 수: {n_orders:,}건, 총 고객 수: {n_customers:,}명, 상품 수: {df['product_id'].nunique()}개

## 베이스라인 지표
- 총 매출: ${total_sales:,.2f}
- 평균 주문 금액(AOV): ${aov:,.2f}
- 주문당 평균 품목 수: {avg_lines_per_order:.2f}개
- 전체 할인율: {discount_rate:.2%} (총 할인 ${total_discount:,.2f} / 정가 매출 ${total_gross:,.2f})

## 신규 vs 재구매 고객
- 신규 고객 주문 비중: {new_order_share:.2%}, 매출 비중: {new_sales_share:.2%}
- 재구매 고객 주문 비중: {returning_order_share:.2%}, 매출 비중: {returning_sales_share:.2%}
- 신규 고객 AOV: ${aov_by_type.get('New',0):,.2f}
- 재구매 고객 AOV: ${aov_by_type.get('Returning',0):,.2f}
""")
print("✅ Step2 완료")
