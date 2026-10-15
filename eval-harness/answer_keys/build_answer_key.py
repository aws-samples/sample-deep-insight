"""Build answer keys (ground-truth facts) for the eval datasets with pandas.

Each fact describes one quantity a report on the dataset may state, precisely
enough for the fact checker (factcheck.py) to find it in a report and to tell
a wrong statement from one about a different period or subset:

  id           stable name; scenarios.yaml `pass:` refers to it
  kind         value     a number (value, unit, rel_tol)
               ranking   an order of names, best first (order); "Singapore 1위"
                         is checked against the position of Singapore
               relation  a comparison (relation: above / below / equal)
  description  what the quantity is and how it was computed. Shown to the
               model while it reads the report, so it never holds the answer
  note         answer-side detail (its rank, how it compares), shown only
               when a statement is adjudicated against the answer
  scope        period and filter the value holds for. A statement about
               another period or subset is out of scope, not wrong
  unit         USD, KRW, count, percent, ratio, rank or relation

Values are for the whole file (all rows, the full period, no filters) unless
`scope` says otherwise. Numbers that depend on a report's own formulas
(opportunity scores, scenario uplifts) are not here: they have no dataset
answer, and the recompute and citation graders already check them.

Usage:
    python answer_keys/build_answer_key.py          # writes answer_keys/*.json
Review the generated values once by hand before trusting them.
Each key agrees with its answer sheet: jungle_market with eval-harness/ground_truth/jungle_market/ground_truth.json
(checked 2026-10-12), yummy_food_kr/_en and moon_market_kr/_en with eval-harness/ground_truth/<dataset>/<lang>/ground_truth.json
(checked 2026-10-14).
"""
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

FULL = {"period": "full period of the file", "filter": "none"}


def value(id_, v, description, unit, rel_tol=0.005, scope=None, note=""):
    return {"id": id_, "kind": "value", "description": description, "scope": scope or FULL,
            "unit": unit, "value": round(float(v), 6), "rel_tol": rel_tol, "note": note}


def ranking(id_, order, description, scope=None):
    return {"id": id_, "kind": "ranking", "description": description, "scope": scope or FULL,
            "unit": "rank", "order": [str(n) for n in order]}


def relation(id_, rel, description, scope=None, note=""):
    return {"id": id_, "kind": "relation", "description": description, "scope": scope or FULL,
            "unit": "relation", "relation": rel, "note": note}


def jungle_market():
    """Jungle Market: planted patterns a shallow analysis gets wrong.

    The answer sheet is eval-harness/ground_truth/jungle_market/ (Q1-Q18), kept
    out of the data directory because the web app lists and serves every file
    in it; these facts are recomputed from the CSV and must agree with it. Every value is after removing the 111 exact duplicate rows
    (Sydney, 2026-03-10) unless its scope says raw; the scope tells the fact checker that counting them
    twice is an error, not another subset.
    """
    csv = REPO / "deep-insight-web" / "sample_data" / "jungle-market" / "jungle-market-sales.csv"
    raw = pd.read_csv(csv)
    df = raw.drop_duplicates()
    # The duplicates are a loading error, not a subset a report may choose: a figure that
    # counts them twice is wrong in the same scope, never "about another subset".
    once = ("none; the file's exact duplicate rows are a loading error and count once: a figure that counts them twice is wrong, "
            "not another subset, even when the report says it kept them. Only a statement that presents the figure as the raw "
            "file's value in contrast to the deduplicated one (\"before removing duplicates, Sydney looks first\") is about the raw file")
    # The file holds no other dates: a report that gives the whole data other dates mislabels
    # it (a report did: "2025-01-01 ~ 01-14"), which must not turn every figure into "another period".
    whole = ("the whole file, 2026-03-02 to 2026-03-15; the file has no other dates, so a report that labels "
             "its whole data with other dates is mislabeling this same period, not describing another one")
    clean = {"period": whole, "filter": once}
    rawscope = {"period": whole, "filter": "the raw file as loaded"}
    orders = df.groupby("order_id").agg(net=("line_total", "sum"), lines=("line_total", "size"), city=("city", "first"), date=("order_date", "first"),
                                        hour=("order_hour", "first"), ctype=("customer_type", "first"),
                                        channel=("channel", "first"), age=("age_group", "first"), promo=("promo_code", "first"))
    orders["gross"] = (df["unit_price"] * df["quantity"]).groupby(df["order_id"]).sum()
    rev = df["line_total"].sum()
    f = [
        value("total_revenue", rev, "Total revenue: SUM(line_total), net of discounts", "USD", scope=clean),
        value("order_count", len(orders), "Number of orders: distinct order_id", "count", rel_tol=0, scope=clean),
        value("customer_count", df["customer_id"].nunique(), "Number of distinct customers", "count", rel_tol=0, scope=clean),
        value("avg_order_value", rev / len(orders), "Average order value (AOV): SUM(line_total) / distinct order_id", "USD", scope=clean),
        value("lines_per_order", len(df) / len(orders), "Average number of rows (product lines) per order", "ratio", rel_tol=0.01, scope=clean),
        value("duplicate_row_count", int(raw.duplicated().sum()), "Number of exact duplicate rows in the file", "count", rel_tol=0, scope=rawscope,
              note="all of them are Sydney rows on 2026-03-10 (15 orders loaded twice)"),
    ]

    # Q1: duplicates change the top city
    by_city = df.groupby("city")["line_total"].sum().sort_values(ascending=False)
    raw_city = raw.groupby("city")["line_total"].sum().sort_values(ascending=False)
    f += [
        ranking("city_revenue_ranking", by_city.index, "Cities ranked by revenue, highest first", scope=clean),
        value("top_city_revenue", by_city.iloc[0], f"Revenue of city {by_city.index[0]}", "USD", scope=clean, note="the top city after dedup"),
        value("sydney_revenue", by_city["Sydney"], "Revenue of city Sydney", "USD", scope=clean,
              note=f"{raw_city['Sydney']:.2f} with the duplicate rows, which makes Sydney (wrongly) the top city"),
    ]

    # Q11-Q17: city profiles
    def share(mask):
        return (df[mask].groupby("city")["line_total"].sum() / df.groupby("city")["line_total"].sum()).sort_values(ascending=False)
    cheese = df["product_name"].isin(["Brie", "Cheddar Cheese", "Parmesan Cheese"])
    for id_, s, what in [
        ("bakery_share", share(df["category"] == "Bakery"), "Bakery category"),
        ("cheese_share", share(cheese), "cheese products (Brie, Cheddar Cheese, Parmesan Cheese)"),
        ("ready_meals_share", share(df["category"] == "Ready Meals"), "Ready Meals category"),
        ("plant_based_share", share(df["category"] == "Plant-based"), "Plant-based category"),
    ]:
        f.append(value(f"top_city_{id_}_pct", s.iloc[0] * 100, f"Share of {s.index[0]}'s net revenue that comes from the {what}: SUM(line_total) of those rows in the city / SUM(line_total) of the city. "
                       f"Not the city's share of the category's revenue (\"{s.index[0]}에서 발생한 비중\", category revenue in the city / all category revenue), a different quantity", "percent", rel_tol=0.05, scope=clean,
                       note=f"{s.index[0]} has the highest share among the 8 cities; next {s.index[1]} {s.iloc[1] * 100:.1f}%"))
        f.append(ranking(f"city_{id_}_ranking", s.index, f"Cities ranked by the share of their own net revenue (line_total) that comes from the {what}, highest first", scope=clean))
    oc = orders.groupby("city")
    lines = oc["lines"].mean().sort_values()
    aov = oc["net"].mean().sort_values(ascending=False)
    app = (orders["channel"] == "App").groupby(orders["city"]).mean().sort_values(ascending=False)
    f += [
        ranking("city_lines_per_order_ranking", lines.index, "Cities ranked by average rows (product lines) per order, FEWEST first", scope=clean),
        value("fewest_lines_city_lines_per_order", lines.iloc[0], f"Average rows per order in {lines.index[0]}", "ratio", rel_tol=0.01, scope=clean, note="the fewest among cities"),
        ranking("city_aov_ranking", aov.index, "Cities ranked by AOV (net), highest first", scope=clean),
        value("top_city_aov", aov.iloc[0], f"AOV (net) of city {aov.index[0]}", "USD", scope=clean, note="the highest among cities"),
        ranking("city_app_share_ranking", app.index, "Cities ranked by the share of orders placed on the App channel, highest first", scope=clean),
        value("top_city_app_share_pct", app.iloc[0] * 100, f"Share of {app.index[0]}'s orders placed on the App channel", "percent", rel_tol=0.02, scope=clean),
    ]

    # Q18: weekday (each weekday occurs twice in the two weeks)
    wd = orders.groupby(pd.to_datetime(orders["date"]).dt.day_name()).size().sort_values(ascending=False)
    f.append(ranking("weekday_order_ranking", wd.index, "Weekdays ranked by number of orders, most first", scope=clean))

    # Q3-Q4: co-purchase at order level
    basket = df.groupby("order_id")["product_name"].apply(set)
    n = len(basket)

    def cnt(*items):
        return int(basket.apply(lambda s: all(i in s for i in items)).sum())
    def lift(a, b):
        return cnt(a, b) * n / (cnt(a) * cnt(b))
    f += [
        value("coffee_oat_milk_orders", cnt("Ground Coffee", "Oat Milk"), "Orders containing both Ground Coffee and Oat Milk", "count", rel_tol=0, scope=clean,
              note="the product pair bought together in the most orders"),
        value("spaghetti_pasta_sauce_orders", cnt("Spaghetti", "Pasta Sauce"), "Orders containing both Spaghetti and Pasta Sauce", "count", rel_tol=0, scope=clean,
              note="second most frequent pair"),
        value("spaghetti_pasta_sauce_lift", lift("Spaghetti", "Pasta Sauce"), "Lift of Spaghetti and Pasta Sauce at order level: P(A and B) / (P(A) P(B))", "ratio", rel_tol=0.01, scope=clean,
              note="Spaghetti + Pasta Sauce + Parmesan Cheese is the strongest bundle by lift"),
        value("pasta_bundle_parmesan_confidence_pct", cnt("Spaghetti", "Pasta Sauce", "Parmesan Cheese") / cnt("Spaghetti", "Pasta Sauce") * 100,
              "Share of orders with Spaghetti and Pasta Sauce that also contain Parmesan Cheese (confidence)", "percent", rel_tol=0.02, scope=clean),
    ]

    # Q5: SAVE10 Simpson's paradox on net AOV
    save, nopromo = orders[orders["promo"] == "SAVE10"], orders[orders["promo"].isna()]
    per_city = pd.DataFrame({"save": save.groupby("city")["net"].mean(), "none": nopromo.groupby("city")["net"].mean()})
    assert (per_city["save"] > per_city["none"]).all(), "SAVE10 net AOV is no longer higher in every city: rewrite this fact"
    f += [
        value("save10_net_aov_pooled", save["net"].mean(), "Net AOV (mean of each order's SUM(line_total)) of orders with promo_code SAVE10, all cities pooled; an order has at most one code", "USD", scope=clean),
        value("no_promo_net_aov_pooled", nopromo["net"].mean(), "Net AOV (mean of each order's SUM(line_total)) of orders with no promo_code on any of their rows, all cities pooled; an order whose Spaghetti row has PASTA30 is a PASTA30 order, not a no-promo one", "USD", scope=clean),
        relation("save10_vs_no_promo_aov_within_city", "above",
                 "Within each city, net AOV of SAVE10 orders compared with orders with no promo code", scope={**clean, "filter": clean["filter"] + "; per city"},
                 note="higher in all 8 cities, while the pooled SAVE10 AOV is lower (Simpson's paradox: SAVE10 is concentrated in low-AOV Tokyo and Seoul)"),
        value("save10_share_tokyo_pct", (orders[orders.city == "Tokyo"]["promo"] == "SAVE10").mean() * 100, "Share of Tokyo orders with SAVE10", "percent", rel_tol=0.02, scope=clean),
    ]

    # Q6: Berlin Oat Milk stockout on 2026-03-07/08
    stock = ["2026-03-07", "2026-03-08"]
    after = ["2026-03-14", "2026-03-15"]
    berlin = df[df.city == "Berlin"]
    bo = orders[orders.city == "Berlin"]
    coffee_orders = set(df[df.product_name == "Ground Coffee"]["order_id"])
    def coffee_rate(o):
        return o.index.isin(coffee_orders).mean() * 100
    weekend = {"period": "2026-03-07 and 2026-03-08 (Sat-Sun)", "filter": "Berlin"}
    f += [
        value("berlin_oat_milk_units_stockout", berlin[berlin.order_date.isin(stock) & (berlin.product_name == "Oat Milk")]["quantity"].sum(),
              "Oat Milk units sold in Berlin on 2026-03-07 and 2026-03-08", "count", rel_tol=0, scope=weekend, note="0: out of stock"),
        value("berlin_coffee_per_100_orders_stockout", coffee_rate(bo[bo.date.isin(stock)]), "Berlin orders containing Ground Coffee per 100 orders, on 2026-03-07/08",
              "ratio", rel_tol=0.01, scope=weekend),
        value("berlin_coffee_per_100_orders_next_weekend", coffee_rate(bo[bo.date.isin(after)]), "Berlin orders containing Ground Coffee per 100 orders, on 2026-03-14/15",
              "ratio", rel_tol=0.01, scope={"period": "2026-03-14 and 2026-03-15 (Sat-Sun)", "filter": "Berlin"}),
    ]

    # Q7: WELCOME10 threshold bunching (gross order value of new-customer orders)
    new = orders[orders.ctype == "New"]
    newscope = {**clean, "filter": clean["filter"] + "; New customers' orders"}
    f += [
        value("new_orders_gross_50_55", int(((new.gross >= 50) & (new.gross < 55)).sum()), "New-customer orders with gross order value (unit_price x quantity) in [$50, $55)",
              "count", rel_tol=0, scope=newscope, note=f"of {len(new)} new-customer orders; only {int(((new.gross >= 45) & (new.gross < 50)).sum())} in [$45, $50): WELCOME10 starts at $50 gross"),
        value("new_customer_order_count", len(new), "Orders from New customers", "count", rel_tol=0, scope=newscope),
    ]

    # Q8-Q9: PASTA30 halo and post-promo dip (units per day over all rows of a product)
    windows = {"before": ("2026-03-02", "2026-03-08"), "promo": ("2026-03-09", "2026-03-11"), "after": ("2026-03-12", "2026-03-14")}
    def per_day(product, w):
        a, b = windows[w]
        sel = df[(df.product_name == product) & (df.order_date >= a) & (df.order_date <= b)]
        return sel["quantity"].sum() / ((pd.Timestamp(b) - pd.Timestamp(a)).days + 1)
    pscope = {"period": "PASTA30 2026-03-09 to 03-11 vs the week before (03-02 to 03-08)", "filter": once + "; all rows of the product"}
    for prod, id_ in [("Spaghetti", "spaghetti"), ("Pasta Sauce", "pasta_sauce"), ("Parmesan Cheese", "parmesan")]:
        f.append(value(f"{id_}_promo_lift_x", per_day(prod, "promo") / per_day(prod, "before"), f"{prod} units per day during PASTA30 divided by units per day in the week before",
                       "ratio", rel_tol=0.02, scope=pscope, note="" if id_ == "spaghetti" else "not discounted itself: a halo from the Spaghetti promotion"))
    f.append(value("spaghetti_post_promo_x", per_day("Spaghetti", "after") / per_day("Spaghetti", "before"),
                   "Spaghetti units per day in the 3 days after PASTA30 (03-12 to 03-14) divided by units per day in the week before", "ratio", rel_tol=0.02,
                   scope={"period": "2026-03-12 to 03-14 vs 2026-03-02 to 03-08", "filter": pscope["filter"]}, note="below 1: pantry loading after the promotion"))

    # Q10: late-night orders have the highest AOV
    band = pd.cut(orders["hour"], [-1, 5, 11, 17, 21, 23], labels=["late", "morning", "afternoon", "evening", "late2"]).astype(str).replace("late2", "late")
    names = {"late": "Late night (22-05)", "morning": "Morning (06-11)", "afternoon": "Afternoon (12-17)", "evening": "Evening (18-21)"}
    baov = orders.groupby(band)["net"].mean().sort_values(ascending=False)
    late = orders[band == "late"]
    f += [
        ranking("hour_band_aov_ranking", [names[b] for b in baov.index], "Hour bands by order_hour (06-11, 12-17, 18-21, 22-05) ranked by net AOV, highest first", scope=clean),
        value("late_night_aov", baov["late"], "Net AOV of orders placed 22:00-05:59 (order_hour 22-23 or 0-5)", "USD", scope=clean, note="the highest hour band"),
        value("late_night_age55_share_pct", (late.age == "55+").mean() * 100, "Share of late-night (22-05) orders from customers aged 55+", "percent", rel_tol=0.03, scope=clean,
              note=f"vs {(orders.age == '55+').mean() * 100:.0f}% of all orders"),
    ]
    return {"dataset": "jungle_market", "csv": str(csv.relative_to(REPO)), "rows": len(raw), "facts": f}


# yummy_food en is the kr file with English column names and values (same numbers).
YUMMY_EN = {"날짜": "Date", "매체": "Media", "카테고리": "Category", "상품명": "Product", "노출수": "Impressions",
            "클릭수": "Clicks", "전환수": "Conversions", "광고비용": "Ad Cost", "매출액": "Revenue", "전환율": "CVR",
            "주요구매연령": "Main Age Group", "주요구매성별": "Main Gender",
            "쿠빵": "Kuppang", "네이바": "Neiba", "아마존": "Amazon", "컬삼": "Kulsam",
            "간편식": "Convenience Food", "건강식품": "Health Food", "신선식품": "Fresh Food",
            "즉석밥세트": "Instant Rice Set", "냉동만두": "Frozen Dumplings", "프로틴바": "Protein Bar", "오메가3": "Omega-3",
            "샐러드키트": "Salad Kit", "프리미엄과일": "Premium Fruit",
            "20대": "20s", "30대": "30s", "40대": "40s", "50대": "50s", "남성": "Male", "여성": "Female"}
# fact ids are the same in both editions
YUMMY_SLUG = {"쿠빵": "kuppang", "네이바": "neiba", "아마존": "amazon", "컬삼": "kulsam",
              "간편식": "convenience_food", "건강식품": "health_food", "신선식품": "fresh_food"}


def yummy_food(lang):
    """Yummy Food: daily ad performance of 6 products on 4 media, September 2025.

    One row per date x media x product, no duplicates or gaps, and every ratio
    column is exact for its row, so there is nothing to clean: the planted
    patterns are about aggregating ad metrics. A mean of the ROAS column ranks
    the media differently from SUM(매출액) / SUM(광고비용), the highest-CTR media
    has the lowest ROAS, and 쿠빵's spend doubles on 2025-09-16 at a much lower
    incremental return. The answer sheet is eval-harness/ground_truth/yummy_food/<lang>/
    (Q1-Q13), kept out of the data directory because that ships to the runtime;
    these facts must agree with it. The facts are computed on the Korean names
    and translated for the en edition.
    """
    csv = REPO / "managed-agentcore" / "data" / "yummy_food" / lang / "yummy-food-market.csv"
    df = pd.read_csv(csv)
    if lang == "en":
        back = {v: k for k, v in YUMMY_EN.items()}
        df = df.rename(columns=back).replace(back)
    # The file holds no other dates: a whole-file figure labeled with other dates is mislabeled, not another period.
    whole = ("the whole file, 2025-09-01 to 2025-09-30; the file has no other dates, so a report that labels "
             "its whole data with other dates is mislabeling this same period, not describing another one")
    full = {"period": whole, "filter": "none"}
    sums = ["노출수", "클릭수", "전환수", "광고비용", "매출액"]
    tot = df[sums].sum()
    media = df.groupby("매체")[sums].sum()
    media["roas"] = media["매출액"] / media["광고비용"]
    media["ctr"] = media["클릭수"] / media["노출수"] * 100
    media["cvr"] = media["전환수"] / media["클릭수"] * 100
    row_mean = df.groupby("매체")["ROAS"].mean().sort_values(ascending=False)
    roas = media["roas"].sort_values(ascending=False)
    assert row_mean.index[0] != roas.index[0], "the mean of the ROAS column no longer picks another top media: rewrite these facts"
    ratio_note = "aggregated from the summed counts; the mean of the row-level column is a different (wrong) quantity"
    f = [
        value("total_revenue", tot["매출액"], "Total revenue: SUM(매출액)", "KRW", scope=full),
        value("total_ad_spend", tot["광고비용"], "Total ad spend: SUM(광고비용)", "KRW", scope=full),
        value("overall_roas", tot["매출액"] / tot["광고비용"], "Overall ROAS: SUM(매출액) / SUM(광고비용); may be printed as a ratio or a percent", "ratio", rel_tol=0.01, scope=full),
        value("overall_ctr_pct", tot["클릭수"] / tot["노출수"] * 100, "Overall CTR: SUM(클릭수) / SUM(노출수)", "percent", rel_tol=0.01, scope=full, note=ratio_note),
        value("overall_cvr_pct", tot["전환수"] / tot["클릭수"] * 100, "Overall conversion rate: SUM(전환수) / SUM(클릭수)", "percent", rel_tol=0.01, scope=full, note=ratio_note),
        value("total_conversions", tot["전환수"], "Total conversions: SUM(전환수)", "count", scope=full),
        value("total_clicks", tot["클릭수"], "Total clicks: SUM(클릭수)", "count", scope=full),
        value("total_impressions", tot["노출수"], "Total impressions: SUM(노출수)", "count", scope=full),
        value("row_count", len(df), "Number of rows (records) in the file", "count", rel_tol=0, scope=full),
        value("revenue_per_conversion", tot["매출액"] / tot["전환수"], "Revenue per conversion: SUM(매출액) / SUM(전환수)", "KRW", scope=full),
    ]

    # Q6-Q7: media revenue
    rev = media["매출액"].sort_values(ascending=False)
    f.append(ranking("media_revenue_ranking", rev.index, "Media ranked by revenue (SUM(매출액)), highest first", scope=full))
    for m in rev.index:
        f.append(value(f"media_revenue_{m}", rev[m], f"Revenue of media {m}: SUM(매출액) of its rows", "KRW", scope=full,
                       note=f"rank {list(rev.index).index(m) + 1} by revenue"))

    # Q1-Q2: ROAS per media is SUM/SUM, not the mean of the ROAS column
    f.append(ranking("media_roas_ranking", roas.index, "Media ranked by ROAS = SUM(매출액) / SUM(광고비용) of the media's rows, highest first", scope=full))
    for m in roas.index:
        f.append(value(f"media_roas_{m}", roas[m], f"ROAS of media {m}: SUM(매출액) / SUM(광고비용) of its rows; may be printed as a ratio or a percent", "ratio", rel_tol=0.01, scope=full,
                       note=f"rank {list(roas.index).index(m) + 1} by ROAS; the mean of its ROAS column is {row_mean[m]:.2f}, a different (wrong) quantity"
                            + (f" that wrongly ranks {m} first" if m == row_mean.index[0] else "")))

    # Q3: the highest CTR has the lowest conversion rate and ROAS
    ctr, cvr = media["ctr"].sort_values(ascending=False), media["cvr"].sort_values(ascending=False)
    assert ctr.index[0] == cvr.index[-1] == roas.index[-1], "the highest-CTR media is no longer the least efficient: rewrite these facts"
    top = ctr.index[0]
    f += [
        ranking("media_ctr_ranking", ctr.index, "Media ranked by CTR = SUM(클릭수) / SUM(노출수), highest first", scope=full),
        ranking("media_cvr_ranking", cvr.index, "Media ranked by conversion rate = SUM(전환수) / SUM(클릭수), highest first", scope=full),
        value(f"media_ctr_pct_{top}", ctr[top], f"CTR of media {top}: SUM(클릭수) / SUM(노출수)", "percent", rel_tol=0.01, scope=full, note="the highest CTR among the media"),
        value(f"media_cvr_pct_{top}", cvr[top], f"Conversion rate of media {top}: SUM(전환수) / SUM(클릭수)", "percent", rel_tol=0.01, scope=full,
              note="the lowest conversion rate among the media, and its ROAS is the lowest too"),
    ]

    # Q4-Q5: 쿠빵's spend doubles from 2025-09-16 at a low incremental return
    c = df[df["매체"] == "쿠빵"]
    h1, h2 = c[c["날짜"] <= "2025-09-15"][sums].sum(), c[c["날짜"] >= "2025-09-16"][sums].sum()
    inc = (h2["매출액"] - h1["매출액"]) / (h2["광고비용"] - h1["광고비용"])
    assert inc < roas.drop("쿠빵").min()
    first = {"period": "2025-09-01 to 2025-09-15", "filter": "media 쿠빵"}
    second = {"period": "2025-09-16 to 2025-09-30", "filter": "media 쿠빵"}
    f += [
        value("kuppang_daily_spend_before", h1["광고비용"] / 15, "Average daily ad spend of 쿠빵 (all its products), 2025-09-01 to 09-15", "KRW", rel_tol=0.01, scope=first),
        value("kuppang_daily_spend_after", h2["광고비용"] / 15, "Average daily ad spend of 쿠빵 (all its products), 2025-09-16 to 09-30", "KRW", rel_tol=0.01, scope=second,
              note="about twice the first half; the other media kept the same daily spend"),
        value("kuppang_roas_before", h1["매출액"] / h1["광고비용"], "ROAS of 쿠빵, 2025-09-01 to 09-15: SUM(매출액) / SUM(광고비용)", "ratio", rel_tol=0.01, scope=first),
        value("kuppang_roas_after", h2["매출액"] / h2["광고비용"], "ROAS of 쿠빵, 2025-09-16 to 09-30: SUM(매출액) / SUM(광고비용)", "ratio", rel_tol=0.01, scope=second),
        value("kuppang_incremental_roas", inc, "Incremental ROAS of 쿠빵's extra spend: (revenue 09-16 to 09-30 - revenue 09-01 to 09-15) / (ad spend 09-16 to 09-30 - ad spend 09-01 to 09-15)",
              "ratio", rel_tol=0.02, scope={"period": "2025-09-16 to 09-30 vs 2025-09-01 to 09-15", "filter": "media 쿠빵"},
              note=f"below the full-month ROAS of every other media (lowest {roas.index[-1]} {roas.iloc[-1]:.2f})"),
    ]

    # Q8-Q11: media, category and product profiles
    fresh = (df[df["카테고리"] == "신선식품"].groupby("매체")["매출액"].sum() / media["매출액"]).sort_values(ascending=False) * 100
    cat = (df.groupby("카테고리")["매출액"].sum() / tot["매출액"]).sort_values(ascending=False) * 100
    prod = df.groupby("상품명")[sums].sum()
    rpc = (prod["매출액"] / prod["전환수"]).sort_values(ascending=False)
    proas = (prod["매출액"] / prod["광고비용"]).sort_values(ascending=False)
    f += [
        value("top_media_fresh_food_share_pct", fresh.iloc[0], f"Share of {fresh.index[0]}'s revenue that comes from the 신선식품 category: SUM(매출액) of its 신선식품 rows / SUM(매출액) of its rows. "
              f"Not {fresh.index[0]}'s share of all 신선식품 revenue, a different quantity", "percent", rel_tol=0.02, scope=full,
              note=f"the highest among the media; next {fresh.index[1]} {fresh.iloc[1]:.1f}%"),
        ranking("category_revenue_ranking", cat.index, "Categories ranked by revenue (SUM(매출액)), highest first", scope=full),
    ]
    for k in cat.index:
        f.append(value(f"category_revenue_share_pct_{k}", cat[k], f"Share of total revenue from category {k}: SUM(매출액) of its rows / SUM(매출액)", "percent", rel_tol=0.02, scope=full))
    f += [
        value("top_product_revenue_per_conversion", rpc.iloc[0], f"Revenue per conversion of product {rpc.index[0]}: SUM(매출액) / SUM(전환수) of its rows", "KRW", scope=full,
              note="the highest among the products"),
        value("top_product_roas", proas.iloc[0], f"ROAS of product {proas.index[0]}: SUM(매출액) / SUM(광고비용) of its rows", "ratio", rel_tol=0.01, scope=full,
              note=f"the highest among the products; next {proas.index[1]} {proas.iloc[1]:.2f}"),
    ]

    # Q12: weekday (spend is flat; the weekend converts better)
    daily = df.groupby("날짜")["매출액"].sum()
    dow = pd.to_datetime(daily.index).dayofweek
    by_day = daily.groupby(pd.to_datetime(daily.index).day_name()).mean().sort_values(ascending=False)
    f += [
        value("saturday_avg_daily_revenue", by_day["Saturday"], "Average daily revenue on Saturdays: SUM(매출액) per Saturday, averaged over the month's Saturdays", "KRW", rel_tol=0.01, scope=full,
              note=f"the highest weekday; next {by_day.index[1]}"),
        value("weekend_vs_weekday_daily_revenue_x", daily[dow >= 5].mean() / daily[dow < 5].mean(), "Average daily revenue on Saturdays and Sundays divided by that on Mondays to Fridays",
              "ratio", rel_tol=0.02, scope=full),
    ]
    for x in f:
        for k, v in YUMMY_SLUG.items():
            x["id"] = x["id"].replace(k, v)
        assert x["id"].isascii(), x["id"]
    if lang == "en":
        def tr(t):
            for k in sorted(YUMMY_EN, key=len, reverse=True):
                t = t.replace(k, YUMMY_EN[k])
            return t
        for x in f:
            for key in ("description", "note"):
                if key in x:
                    x[key] = tr(x[key])
            x["scope"] = {k: tr(v) for k, v in x["scope"].items()}
            if "order" in x:
                x["order"] = [tr(n) for n in x["order"]]
    return {"dataset": f"yummy_food_{lang}", "csv": str(csv.relative_to(REPO)), "rows": len(df), "facts": f}


# moon_market en is the kr file with English names (same numbers).
MOON_EN = {"간편식/밀키트/샐러드": "Ready Meal/Meal Kit/Salad", "과일/견과/쌀": "Fruit/Nuts/Rice", "채소": "Vegetables",
           "정육/가공육/달걀": "Meat/Processed Meat/Egg", "유제품": "Dairy", "커피/차": "Coffee/Tea", "베이커리": "Bakery", "건강식품": "Health Supplements",
           "샐러드키트": "Salad Kit", "김치찌개키트": "Kimchi Stew Kit", "우동키트": "Udon Kit", "사과": "Apple", "견과류믹스": "Mixed Nuts",
           "백미": "White Rice", "상추": "Lettuce", "브로콜리": "Broccoli", "양파": "Onion", "돼지고기": "Pork", "달걀": "Egg",
           "한우선물세트": "Hanwoo Beef Gift Set", "우유": "Milk", "그릭요거트": "Greek Yogurt", "체다치즈": "Cheddar Cheese",
           "드립커피": "Drip Coffee", "생강차": "Ginger Tea", "녹차": "Green Tea", "식빵": "White Bread", "베이글": "Bagel",
           "크로와상": "Croissant", "홍삼": "Red Ginseng", "오메가3": "Omega-3", "유산균": "Probiotics",
           "2개입": "2-pack", "10개입": "10-pack", "20개입": "20-pack", "4개입": "4-pack", "30개입": "30-pack", "1개": "1 pc",
           "60정": "60 tablets", "30정": "30 tablets",
           "송파구": "Songpa-gu", "강남구": "Gangnam-gu", "서초구": "Seocho-gu", "마포구": "Mapo-gu", "강서구": "Gangseo-gu",
           "노원구": "Nowon-gu", "영등포구": "Yeongdeungpo-gu", "광진구": "Gwangjin-gu", "성동구": "Seongdong-gu", "용산구": "Yongsan-gu",
           "서울": "Seoul", "20대": "20s", "30대": "30s", "40대": "40s", "50대": "50s", "60대": "60s"}


def moon_market(lang):
    """Moon Market: two weeks of single-product grocery orders in 10 Seoul districts, May 2025.

    One row = one order (no order id), each product with one fixed size and
    price, and WEEKEND20 (20% off every Saturday and Sunday order) the only
    code, so Amount has one reading. Planted: the 05-05 / 05-06 public holidays
    make Monday and Tuesday look busiest; 서초구's top AOV is 3 한우선물세트 gift
    orders; weekend AOV is lower only by the discount. The answer sheet is
    eval-harness/ground_truth/moon_market/<lang>/ (Q1-Q12), kept out of the data
    directories; these facts must agree with it.
    """
    csv = REPO / "managed-agentcore" / "data" / "moon_market" / lang / "moon-market-fresh-food-sales.csv"
    df = pd.read_csv(csv, dtype={"ship-postal-code": str}, keep_default_na=False)
    if lang == "en":
        back = {v: k for k, v in MOON_EN.items()}
        df = df.replace(back)
    whole = ("the whole file, 2025-05-01 to 2025-05-14; the file has no other dates, so a report that labels "
             "its whole data with other dates is mislabeling this same period, not describing another one")
    full = {"period": whole, "filter": "none"}
    hol = df["Date"].isin(["2025-05-05", "2025-05-06"])
    wkend = pd.to_datetime(df["Date"]).dt.weekday >= 5
    wkday = ~hol & ~wkend
    promo = df["promotion-ids"] == "WEEKEND20"
    assert (promo == wkend).all(), "WEEKEND20 is no longer exactly the weekend orders: rewrite these facts"
    gross = df["Amount"] / promo.map({True: 0.8, False: 1.0})
    rev = df["Amount"].sum()
    f = [
        value("total_revenue", rev, "Total revenue: SUM(Amount), after the WEEKEND20 discount", "KRW", scope=full),
        value("order_count", len(df), "Number of orders: rows in the file (one row is one order; there is no order id)", "count", rel_tol=0, scope=full),
        value("avg_order_value", rev / len(df), "Average order value (AOV, 객단가): SUM(Amount) / rows", "KRW", scope=full),
        value("total_units", df["Qty"].sum(), "Units sold: SUM(Qty)", "count", rel_tol=0, scope=full),
        value("units_per_order", df["Qty"].mean(), "Average Qty per order", "ratio", rel_tol=0.01, scope=full),
        value("product_count", df["Product"].nunique(), "Number of distinct products", "count", rel_tol=0, scope=full),
        value("category_count", df["Category"].nunique(), "Number of distinct categories", "count", rel_tol=0, scope=full),
        value("promo_order_share_pct", promo.mean() * 100, "Share of orders with a promotion code (promotion-ids not empty)", "percent", rel_tol=0.01, scope=full,
              note="every one is WEEKEND20, i.e. every Saturday and Sunday order"),
        value("promo_order_count", promo.sum(), "Orders with a promotion code", "count", rel_tol=0, scope=full),
    ]

    # Q7: categories
    cat = df.groupby("Category")["Amount"].sum().sort_values(ascending=False)
    f += [
        ranking("category_revenue_ranking", cat.index, "Categories ranked by revenue (SUM(Amount)), highest first", scope=full),
        value("top_category_revenue", cat.iloc[0], f"Revenue of category {cat.index[0]}", "KRW", scope=full, note="the top category by revenue"),
        value("top_category_share_pct", cat.iloc[0] / rev * 100, f"Share of total revenue from category {cat.index[0]}", "percent", rel_tol=0.02, scope=full),
        value("second_category_revenue", cat.iloc[1], f"Revenue of category {cat.index[1]}", "KRW", scope=full, note="rank 2 by revenue"),
    ]

    # Q8-Q9: districts and products
    orders = df.groupby("ship-city").size().sort_values(ascending=False)
    drev = df.groupby("ship-city")["Amount"].sum().sort_values(ascending=False)
    prod = df.groupby("Product").size().sort_values(ascending=False)
    f += [
        ranking("district_order_ranking", orders.index, "Districts (ship-city) ranked by number of orders, most first", scope=full),
        value("top_district_orders", orders.iloc[0], f"Orders from district {orders.index[0]}", "count", rel_tol=0, scope=full, note="the most orders among the districts"),
        ranking("district_revenue_ranking", drev.index, "Districts (ship-city) ranked by revenue, highest first", scope=full),
        value("top_district_revenue", drev.iloc[0], f"Revenue of district {drev.index[0]}", "KRW", scope=full, note="the top district by revenue"),
        value("top_product_orders", prod.iloc[0], f"Orders of product {prod.index[0]}", "count", rel_tol=0, scope=full, note=f"the most ordered product; next {prod.index[1]} {prod.iloc[1]}"),
    ]

    # Q3: 서초구's AOV is 3 gift orders
    aov = df.groupby("ship-city")["Amount"].mean().sort_values(ascending=False)
    gift = df[df["Product"] == "한우선물세트"]
    assert aov.index[0] == "서초구" and set(gift["ship-city"]) == {"서초구"}
    seocho = df[df["ship-city"] == "서초구"]
    wo = df.drop(gift.index).groupby("ship-city")["Amount"].mean().sort_values(ascending=False)
    f += [
        ranking("district_aov_ranking", aov.index, "Districts (ship-city) ranked by AOV (SUM(Amount) / orders), highest first", scope=full),
        value("seocho_aov", aov["서초구"], "AOV of district 서초구", "KRW", scope=full, note=f"the highest; next {aov.index[1]} {aov.iloc[1]:,.0f}"),
        value("gift_set_order_count", len(gift), "Orders of 한우선물세트", "count", rel_tol=0, scope=full, note="all from 서초구, on 2025-05-05 and 05-06, Qty 3 each"),
        value("seocho_gift_share_pct", gift["Amount"].sum() / seocho["Amount"].sum() * 100, "Share of 서초구's revenue from its 한우선물세트 orders", "percent", rel_tol=0.02, scope=full),
        value("seocho_aov_without_gift", wo["서초구"], "AOV of district 서초구 without its 한우선물세트 orders", "KRW", scope={"period": whole, "filter": "district 서초구, 한우선물세트 orders excluded"},
              note=f"rank {list(wo.index).index('서초구') + 1} of 10 districts on that basis"),
    ]

    # Q1-Q2: holidays
    daily = df.groupby("Date").size()
    per_day = lambda m: df[m].groupby("Date").size().mean()
    f += [
        value("holiday_0505_orders", daily["2025-05-05"], "Orders on 2025-05-05 (Mon, public holiday)", "count", rel_tol=0, scope={"period": "2025-05-05", "filter": "none"}),
        value("holiday_0506_orders", daily["2025-05-06"], "Orders on 2025-05-06 (Tue, substitute holiday)", "count", rel_tol=0, scope={"period": "2025-05-06", "filter": "none"},
              note="05-05 and 05-06 are the two busiest dates"),
        value("weekend_orders_per_day", per_day(wkend), "Average orders per Saturday or Sunday", "ratio", rel_tol=0.01, scope=full),
        value("weekday_orders_per_day", per_day(wkday), "Average orders per Monday-Friday date that is not a public holiday (05-05, 05-06 excluded)", "ratio", rel_tol=0.01,
              scope={"period": whole, "filter": "Monday-Friday dates except 2025-05-05 and 05-06"}),
    ]

    # Q4: weekend AOV is lower only by WEEKEND20
    wscope = {"period": whole, "filter": "Saturday and Sunday orders"}
    dscope = {"period": whole, "filter": "Monday-Friday orders except 2025-05-05 and 05-06"}
    f += [
        value("weekend_aov", df[wkend]["Amount"].mean(), "AOV of Saturday and Sunday orders (SUM(Amount) / orders, after the 20% WEEKEND20 discount)", "KRW", scope=wscope),
        value("weekday_aov", df[wkday]["Amount"].mean(), "AOV of Monday-Friday orders that are not on a public holiday (05-05, 05-06 excluded)", "KRW", scope=dscope),
        value("weekend_gross_aov", gross[wkend].mean(), "AOV of Saturday and Sunday orders before the WEEKEND20 discount (Amount / 0.8)", "KRW", scope=wscope,
              note="about the same as the weekday AOV: the lower weekend AOV is the discount"),
        value("weekend_units_per_order", df[wkend]["Qty"].mean(), "Average Qty per Saturday or Sunday order", "ratio", rel_tol=0.01, scope=wscope),
        value("weekday_units_per_order", df[wkday]["Qty"].mean(), "Average Qty per Monday-Friday order not on a public holiday", "ratio", rel_tol=0.01, scope=dscope),
    ]

    # Q10-Q12: segments
    ac = df.groupby(["Age Group", "Category"])["Amount"].sum().unstack(fill_value=0)
    share = ac.div(ac.sum(axis=1), axis=0) * 100
    for c, id_ in [("간편식/밀키트/샐러드", "ready_meal"), ("건강식품", "health")]:
        s_ = share[c].sort_values(ascending=False)
        f.append(value(f"top_age_{id_}_share_pct", s_.iloc[0], f"Share of age group {s_.index[0]}'s revenue that comes from the {c} category: SUM(Amount) of those orders / SUM(Amount) of the age group. "
                       f"Not the age group's share of the category's revenue, a different quantity", "percent", rel_tol=0.02, scope=full,
                       note=f"the highest among the age groups; next {s_.index[1]} {s_.iloc[1]:.1f}%"))
    f.append(value("female_revenue_share_pct", df[df["Gender"] == "F"]["Amount"].sum() / rev * 100, "Share of total revenue from female customers (Gender = F)", "percent", rel_tol=0.01, scope=full))

    slug = {"서초구": "seocho"}
    for x in f:
        for k, v in slug.items():
            x["id"] = x["id"].replace(k, v)
        assert x["id"].isascii(), x["id"]
    if lang == "en":
        def tr(t):
            t = t.replace("(AOV, 객단가)", "(AOV)")
            for k in sorted(MOON_EN, key=len, reverse=True):
                t = t.replace(k, MOON_EN[k])
            return t
        for x in f:
            for key in ("description", "note"):
                if key in x:
                    x[key] = tr(x[key])
            x["scope"] = {k: tr(v) for k, v in x["scope"].items()}
            if "order" in x:
                x["order"] = [tr(n) for n in x["order"]]
    return {"dataset": f"moon_market_{lang}", "csv": str(csv.relative_to(REPO)), "rows": len(df), "facts": f}


if __name__ == "__main__":
    for key in (jungle_market(), yummy_food("kr"), yummy_food("en"), moon_market("kr"), moon_market("en")):
        path = OUT / f"{key['dataset']}.json"
        path.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(key['facts'])} facts")
