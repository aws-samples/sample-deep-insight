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
jungle_market agrees with the dataset's own ground_truth.json (checked 2026-10-12).
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

    The dataset ships with its own answer sheet (ground_truth.json / .md next
    to the CSV, Q1-Q18); these facts are recomputed from the CSV and must
    agree with it. Every value is after removing the 111 exact duplicate rows
    (Sydney, 2026-03-10) unless its scope says raw; the scope tells the fact checker that counting them
    twice is an error, not another subset.
    """
    csv = REPO / "deep-insight-web" / "sample_data" / "jungle-market" / "jungle-market-sales.csv"
    raw = pd.read_csv(csv)
    df = raw.drop_duplicates()
    # The duplicates are a loading error, not a subset a report may choose: a figure that
    # counts them twice is wrong in the same scope, never "about another subset".
    once = "none; the file's exact duplicate rows are a loading error and count once (a figure that counts them twice is wrong, not another subset)"
    clean = {"period": "full period 2026-03-02 to 2026-03-15", "filter": once}
    rawscope = {"period": "full period 2026-03-02 to 2026-03-15", "filter": "the raw file as loaded"}
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


if __name__ == "__main__":
    for key in (jungle_market(),):
        path = OUT / f"{key['dataset']}.json"
        path.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(key['facts'])} facts")
