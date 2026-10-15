"""Independent recomputation of calculation_metadata.json against the source CSV.

The Validator checks the Coder with code the agents wrote themselves; this
grader re-derives the values with pandas, outside the agent loop. Formulas are
free-form pseudo-SQL, so only the shapes agents actually write are parsed, and
everything else is counted as unsupported rather than guessed:

    AGG(col)                              SUM / AVG / MEAN / MEDIAN / MIN / MAX / COUNT
    COUNT(*), COUNT(DISTINCT col)
    SUM(a) / COUNT(*), SUM(a) / COUNT(DISTINCT b)
    AGG(col) GROUP BY key[+key2]          also "grouped by" and "by"; key may be `weekday`
    AGG(col) WHERE c1=v1 AND c2=v2        literal values filter; placeholders act like GROUP BY
    MAX(AGG(col) GROUP BY key)            min / max over the groups
    SUM(col)/TOTAL(col)*100 GROUP BY key  each group's share in percent
    … *100                                trailing multiplier

For grouped values, which group a calculation means is read from its
description ("2025-05-02 일별 매출", "월요일 총매출", "M_30대 평균"). When the
description names exactly one group, the value is checked against that group.
When it names none, the value only has to equal some group's value; those
looser checks are counted in `recompute_lenient`. If no group's value matches
either, the formula may mean something else ("weekdays" is not "per weekday"),
so it counts as `recompute_unverified`, never as wrong. A formula with no group
at all that misses is also tried on the subset its description names
("PASTA30 할인율": rows with promo_code PASTA30); a match there is lenient too.

A file with exact duplicate rows (jungle_market) is also recomputed with the
duplicates removed, since dropping them is the correct analysis; a value that
matches only that way counts in `recompute_dedup`.

Agents often clean the file once and compute from a cached copy
(df_clean.pkl). A calculation on such a derived file is recomputed from the raw
CSV (and its deduplicated copy) when its formula only names CSV columns. A
match counts (`recompute_derived`); a mismatch is not counted as wrong, since
the cleaning may have filtered rows the grader can't know about
(`recompute_derived_unmatched`).

The Validator marks each citation verified or needs_review with code the
agents wrote; for SUM-free formulas its example code compares a value with
itself. `validator_false_verified` counts cited calculations the Validator
called verified that this recomputation finds wrong, out of
`validator_verified_checked` verified ones it could recompute strictly.
"""
import re
from pathlib import Path

from .citations import load_calculations, load_citations

AGGS = {
    "SUM": lambda s: s.sum(), "AVG": lambda s: s.mean(), "MEAN": lambda s: s.mean(),
    "MEDIAN": lambda s: s.median(), "MIN": lambda s: s.min(), "MAX": lambda s: s.max(),
    "COUNT": lambda s: s.count(), "STD": lambda s: s.std(), "STDDEV": lambda s: s.std(),
}
WEEKDAY_KEYS = {"weekday", "dayofweek", "day_of_week", "요일", "dow"}
WEEKDAY_LABELS = [("월요일", "monday", "mon"), ("화요일", "tuesday", "tue"), ("수요일", "wednesday", "wed"),
                  ("목요일", "thursday", "thu"), ("금요일", "friday", "fri"), ("토요일", "saturday", "sat"),
                  ("일요일", "sunday", "sun")]
GENDER_ALIASES = {"M": ("남성", "남자", "male", "men"), "F": ("여성", "여자", "female", "women")}

AGG_RE = r"(SUM|AVG|MEAN|MEDIAN|MIN|MAX|COUNT)\(\s*(DISTINCT\s+)?([^()]*?)\s*\)"


def load_csv(path):
    import pandas as pd
    return pd.read_csv(path, encoding="utf-8-sig")


def _norm(name):
    return re.sub(r"[\s_\-`'\"]", "", str(name)).lower()


def _column(df, name):
    """Match a formula's column name to the CSV header, ignoring case, spaces, _ and -."""
    want = _norm(name)
    return next((c for c in df.columns if _norm(c) == want), None)


def _agg(df, func, distinct, col):
    col = col.strip()
    if func == "COUNT" and (col in ("*", "") or _norm(col) in ("rows", "row", "1", "orders", "transactions")):
        return float(len(df))
    real = _column(df, col)
    if real is None:
        return None
    if distinct:
        return float(df[real].nunique()) if func == "COUNT" else None
    return float(AGGS[func](df[real]))


def _key_series(df, key):
    """Series to group by for one key, plus whether it is a derived weekday."""
    if _norm(key) in WEEKDAY_KEYS:
        import pandas as pd
        date_col = (_column(df, "Date") or _column(df, "날짜")
                    or next((c for c in df.columns if "date" in _norm(c)), None))
        if date_col is None:
            return None
        dates = pd.to_datetime(df[date_col], format="%m/%d/%y", errors="coerce")
        if dates.isna().all():
            dates = pd.to_datetime(df[date_col], format="mixed", errors="coerce")
        return dates.dt.dayofweek.rename("weekday")
    real = _column(df, key)
    return None if real is None else df[real]


def _labels(key_name, value):
    """Strings that would name this group value in a description."""
    v = str(value)
    out = [v]
    if key_name == "weekday" and value == value:  # not NaN
        out = list(WEEKDAY_LABELS[int(value)])
    elif v in GENDER_ALIASES:
        out = [v, *GENDER_ALIASES[v]]
    elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", v):  # 5/1/25 → 2025-05-01, 5월 1일
        import pandas as pd
        d = pd.to_datetime(v, format="%m/%d/%y", errors="coerce")
        if d is not pd.NaT:
            out += [d.strftime("%Y-%m-%d"), f"{d.month}월 {d.day}일", f"{d.month}/{d.day}"]
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):  # 2026-03-02 → 3월 2일, 3/2
        y, m, d = (int(x) for x in v.split("-"))
        out += [f"{m}월 {d}일", f"{m}/{d}"]
    elif v == "nan":
        out = ["없음", "미적용", "no promotion", "no promo", "none"]
    return out


def _mentions(text, label):
    label = label.lower()
    if re.fullmatch(r"[a-z0-9]{1,3}", label):  # short codes like M, F, 30s need word edges
        return re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", text) is not None
    return label in text


def _grouped(df, keys, inner, description, outer=None, share=False):
    """Per-group values, then pick the group the description names (or all as candidates)."""
    series = [_key_series(df, k) for k in keys]
    if any(s is None for s in series):
        return None
    groups = df.groupby(series, dropna=False)
    total = inner(df) if share else None
    values = {}
    for gkey, part in groups:
        gkey = gkey if isinstance(gkey, tuple) else (gkey,)
        v = inner(part)
        if v is None:
            return None
        values[gkey] = v / total * 100 if share else v
    text = (description or "").lower()
    names = [s.name for s in series]
    if outer:
        # "50대 최선호 카테고리 매출" = max within 50대 (and, if named, that category): narrow to
        # groups whose key values the description names before taking the max / min.
        pool = values
        for j, n in enumerate(names):
            named_vals = {g[j] for g in pool if any(_mentions(text, lbl) for lbl in _labels(n, g[j]))}
            if named_vals and len(named_vals) < len({g[j] for g in pool}):
                pool = {g: v for g, v in pool.items() if g[j] in named_vals}
        return {"value": outer(list(pool.values())), "lenient": False}
    named = [g for g in values if all(any(_mentions(text, lbl) for lbl in _labels(n, part)) for n, part in zip(names, g))]
    if len(named) == 1:
        return {"value": values[named[0]], "lenient": False}
    candidates = named or list(values)
    return {"candidates": [values[g] for g in candidates], "lenient": True}


# --- general expression evaluator ----------------------------------------------------
#
# Arithmetic over aggregates, each optionally filtered or grouped:
#     SUM(Amount WHERE Category=='간편식') / SUM(Amount) * 100
#     SUM(Amount|category)/SUM(Amount)*100          SUM(Amount|cat) / SUM(Amount|all)
#     SUM(Amount) WHERE promotion-ids IS NULL        COUNT(rows WHERE Category==cat)
#     MEAN(Amount) GROUP BY Category                 STD(Amount)/MEAN(Amount)*100
# An unquoted value that isn't in the column (cat, X, d, '{}') is a placeholder:
# the aggregate is computed per value and the description picks which one.
# Names the agent derived itself (cat_sales, daily_sum, has_promo) aren't
# columns, so such formulas stay unsupported.

AGG_NAMES = "SUM|AVG|MEAN|MEDIAN|MIN|MAX|COUNT|STD|STDDEV|TOTAL"
CLAUSE_RE = re.compile(r"\s+(GROUP(?:ED)?\s+BY|BY|WHERE)\s+", re.I)


def _top_level_split(f, rx):
    """Split at the first match of rx that is outside parentheses."""
    depth = 0
    for i, ch in enumerate(f):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0:
            m = rx.match(f, i)
            if m:
                return f[:i], m.group(1).upper(), f[m.end():]
    return f, None, None


def _key_column(df, name):
    """Column for a key name: exact (normalized), weekday, or a unique prefix (cat → Category)."""
    if _norm(name) in WEEKDAY_KEYS:
        return "weekday"
    col = _column(df, name)
    if col:
        return col
    hits = [c for c in df.columns if _norm(c).startswith(_norm(name))] if len(_norm(name)) >= 3 else []
    return hits[0] if len(hits) == 1 else None


def _conditions(df, text):
    """[(col, op, literal)] filters and [col] placeholder keys, or None if unparseable."""
    filters, keys = [], []
    for part in re.split(r"\s+AND\s+", text.strip(), flags=re.I):
        part = part.strip()
        m = re.fullmatch(r"(.+?)\s+(IS\s+NOT\s+NULL|NOT\s+NULL|IS\s+NULL)", part, re.I)
        if m:
            col = _column(df, m.group(1))
            if col is None:
                return None
            filters.append((col, "null" if m.group(2).upper() == "IS NULL" else "notnull", None))
            continue
        m = re.fullmatch(r"(.+?)\s*(==|!=|=)\s*(.+)", part)
        if not m:
            return None
        col = _column(df, m.group(1))
        if col is None:
            return None
        raw = m.group(3).strip()
        quoted = re.fullmatch(r"(['\"])(.*)\1", raw)
        val = quoted.group(2) if quoted else raw
        values = set(df[col].astype(str))
        if val in values:
            filters.append((col, "!=" if m.group(2) == "!=" else "==", val))
        elif (quoted and val in ("{}", "")) or (not quoted and re.fullmatch(r"[A-Za-z_]\w{0,11}", val)):
            if m.group(2) == "!=":
                return None
            keys.append(col)
        else:
            return None
    return filters, keys


def _apply(df, filters):
    for col, op, val in filters:
        s = df[col]
        if op == "null":
            df = df[s.isna()]
        elif op == "notnull":
            df = df[s.notna()]
        elif op == "==":
            df = df[s.astype(str) == val]
        else:
            df = df[s.astype(str) != val]
    return df


def _parse_aggregate(df, func, inner):
    inner = inner.strip()
    agg = {"func": "SUM" if func == "TOTAL" else func, "total": func == "TOTAL", "filters": [], "keys": [], "distinct": False}
    m = re.fullmatch(r"(.+?)\s+WHERE\s+(.+)", inner, re.I)
    if m:
        c = _conditions(df, m.group(2))
        if c is None:
            return None
        agg["filters"], agg["keys"] = c
        inner = m.group(1).strip()
    if "|" in inner:
        inner, key = (x.strip() for x in inner.split("|", 1))
        if _norm(key) in ("all", "total", "전체"):
            agg["total"] = True
        else:
            col = _key_column(df, key)
            if col is None:
                return None
            agg["keys"].append(col)
    m = re.fullmatch(r"DISTINCT\s+(.+)", inner, re.I)
    if m:
        agg["distinct"], inner = True, m.group(1)
    agg["col"] = inner
    if not (agg["func"] == "COUNT" and (inner in ("*", "") or _norm(inner) in ("rows", "row", "1", "orders", "transactions"))):
        if _column(df, inner) is None:
            return None
    return agg


def _recompute_expr(formula, df, description):
    f = re.sub(r"\s+", " ", (formula or "").strip())
    if re.match(r"(MAX|MIN)\(.*GROUP", f, re.I):
        return None  # min / max over groups: handled by the fixed patterns
    body, kind, rest = _top_level_split(f, CLAUSE_RE)
    clause_keys, global_filters, global_keys = [], [], []
    while kind:
        nxt_body, nxt_kind, nxt_rest = _top_level_split(rest, CLAUSE_RE)
        text = nxt_body
        tail = re.search(r"\s*\*\s*100\s*$", text)
        if tail:  # "... grouped by Category *100"
            text, body = text[:tail.start()], body + " * 100"
        if kind == "WHERE":
            c = _conditions(df, text)
            if c is None:
                return None
            global_filters += c[0]
            global_keys += c[1]
        else:
            for k in _keys(text):
                col = _key_column(df, k)
                if col is None:
                    return None
                clause_keys.append(col)
        kind, rest = nxt_kind, nxt_rest

    aggs, out, i = [], [], 0
    for m in re.finditer(rf"\b({AGG_NAMES})\(", body, re.I):
        if m.start() < i:
            return None
        close = body.find(")", m.end())
        if close < 0 or "(" in body[m.end():close]:
            return None  # nested aggregates aren't supported
        a = _parse_aggregate(df, m.group(1).upper(), body[m.end():close])
        if a is None:
            return None
        out.append(body[i:m.start()] + f" a{len(aggs)} ")
        aggs.append(a)
        i = close + 1
    out.append(body[i:])
    expr = "".join(out)
    if not aggs or not re.fullmatch(r"[\sa0-9.+\-*/()]*", expr) or re.search(r"[a-z]", re.sub(r"\ba\d+\b", "", expr)):
        return None

    keys = list(dict.fromkeys(clause_keys + global_keys + [k for a in aggs for k in a["keys"]]))
    base = _apply(df, global_filters)

    def evaluate(part):
        env = {}
        for n, a in enumerate(aggs):
            grouped = bool(clause_keys or global_keys or a["keys"])
            src = df if a["total"] else (part if grouped else base)
            v = _agg(_apply(src, a["filters"]), a["func"], a["distinct"], a["col"])
            if v is None:
                return None
            env[f"a{n}"] = v
        try:
            return float(eval(expr, {"__builtins__": {}}, env))  # expr is digits, operators and a<n> only
        except ZeroDivisionError:
            return None

    if not keys:
        v = evaluate(base)
        return None if v is None else {"value": v, "lenient": False}
    series = [_key_series(base, k) if k == "weekday" else base[k] for k in keys]
    return _grouped(base, keys, evaluate, description) if all(s is not None for s in series) else None


def recompute(formula, df, description=""):
    """Recomputed value as {"value": x} or {"candidates": [...], "lenient": True}; None if unsupported."""
    try:
        r = _recompute_expr(formula, df, description)
    except Exception:
        r = None
    if r is not None:
        return r
    f = re.sub(r"\s+", " ", (formula or "").strip())
    scale = 1.0
    m = re.fullmatch(r"(.*?)\s*\*\s*100", f)
    if m and not re.search(r"/\s*TOTAL", f, re.I):
        f, scale = m.group(1).strip(), 100.0

    def scaled(r):
        if r is None:
            return None
        if "value" in r:
            return {**r, "value": r["value"] * scale}
        return {**r, "candidates": [c * scale for c in r["candidates"]]}

    # MAX(AGG(col) GROUP BY key) / MIN(...)
    m = re.fullmatch(rf"(MAX|MIN)\(\s*{AGG_RE}\s+(?:GROUP(?:ED)? BY)\s+([^()]+?)\s*\)", f, re.I)
    if m:
        outer, func, distinct, col, key = m.group(1).upper(), m.group(2).upper(), m.group(3), m.group(4), m.group(5)
        return scaled(_grouped(df, _keys(key), lambda d: _agg(d, func, distinct, col), description, max if outer == "MAX" else min))

    # SUM(col)/TOTAL(col)*100 GROUP BY key
    m = re.fullmatch(rf"SUM\(\s*([^()]+?)\s*\)\s*/\s*TOTAL\(\s*[^()]+?\s*\)\s*\*\s*100\s+(?:GROUP(?:ED)? BY)\s+(.+)", f, re.I)
    if m:
        col, key = m.group(1), m.group(2)
        return _grouped(df, _keys(key), lambda d: _agg(d, "SUM", None, col), description, share=True)

    # AGG(col) GROUP BY key / grouped by key
    m = re.fullmatch(rf"{AGG_RE}\s+(?:GROUP(?:ED)? BY)\s+(.+)", f, re.I)
    if m:
        func, distinct, col, key = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
        return scaled(_grouped(df, _keys(key), lambda d: _agg(d, func, distinct, col), description))

    # AGG(col) WHERE c1=v1 AND c2=v2
    m = re.fullmatch(rf"{AGG_RE}\s+WHERE\s+(.+)", f, re.I)
    if m:
        func, distinct, col, cond = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
        sub, placeholder_keys = df, []
        for part in re.split(r"\s+AND\s+", cond, flags=re.I):
            cm = re.fullmatch(r"\s*([^=]+?)\s*=\s*['\"]?(.+?)['\"]?\s*", part)
            if not cm:
                return None
            real = _column(df, cm.group(1))
            if real is None:
                return None
            val = cm.group(2)
            if val in set(df[real].astype(str)):
                sub = sub[sub[real].astype(str) == val]
            elif re.fullmatch(r"[a-z_]{1,3}", val):  # placeholder such as g / a
                placeholder_keys.append(real)
            else:
                return None
        inner = lambda d: _agg(d, func, distinct, col)
        if placeholder_keys:
            return scaled(_grouped(sub, placeholder_keys, inner, description))
        v = inner(sub)
        return None if v is None else scaled({"value": v, "lenient": False})

    # ratios of plain aggregates
    m = re.fullmatch(rf"SUM\(\s*([^()]+?)\s*\)\s*/\s*COUNT\(\s*(DISTINCT\s+)?([^()]*?)\s*\)", f, re.I)
    if m:
        num, den = _agg(df, "SUM", None, m.group(1)), _agg(df, "COUNT", m.group(2), m.group(3))
        return None if num is None or not den else scaled({"value": num / den, "lenient": False})

    m = re.fullmatch(AGG_RE, f, re.I)
    if m:
        v = _agg(df, m.group(1).upper(), m.group(2), m.group(3))
        return None if v is None else scaled({"value": v, "lenient": False})
    return None


def _keys(key_text):
    return [k for k in re.split(r"\s*[+,&]\s*|\s+and\s+", key_text.strip(), flags=re.I) if k]


def _named_subset(formula, df, description, stored):
    """The formula over the subset its description names ("PASTA30 할인율", "아마존×건강식품 ROAS"), when that matches.

    Agents often write the overall formula and put the group only in the
    description. Each column value the description names is tried alone, then
    every combination of named values from different columns (a 매체 × 카테고리
    cell); the matching value, if any, is returned.
    """
    import itertools
    import pandas as pd
    text = (description or "").lower()
    named = []  # (column, value) the description mentions
    for col in df.columns:
        values = df[col].unique()
        if len(values) > 50:
            continue
        named += [(col, v) for v in values if any(_mentions(text, lbl) for lbl in _labels(col, v))]
    for size in range(1, min(len({c for c, _ in named}), 3) + 1):
        for combo in itertools.combinations(named, size):
            if len({c for c, _ in combo}) < size:
                continue  # two values of one column never hold together
            mask = pd.Series(True, index=df.index)
            for col, v in combo:
                mask &= df[col].isna() if pd.isna(v) else df[col] == v
            try:
                r = recompute(formula, df[mask], description)
            except Exception:
                r = None
            if r is not None and "value" in r and same_value(stored, r["value"]):
                return r["value"]
    return None


def same_value(stored, expected):
    """Stored equals expected, or expected rounded to the precision the stored value was written with.

    19655.0 matches 19655.41 (stored as a whole number), 18.6 and 18.551663
    match 18.55166312549055 (rounded to 1 and 6 decimals), a float from another
    computation matches to ~1e-9, and 16,432,923 does not match 16,431,923.
    """
    if abs(stored - expected) <= max(abs(expected) * 1e-9, 1e-9):
        return True
    text = repr(float(stored))
    if "e" in text:
        return False
    decimals = 0 if text.endswith(".0") else len(text.split(".")[1])
    return abs(round(expected, decimals) - stored) <= max(abs(stored) * 1e-12, 1e-12)


def grade(artifacts_dir, csv_path):
    calcs = load_calculations(artifacts_dir)
    if calcs is None:
        return {"recompute_supported": 0, "details": ["calculation_metadata.json unusable"]}
    df = load_csv(csv_path)
    dedup = df.drop_duplicates() if df.duplicated().any() else None
    source_name = Path(csv_path).name
    details = []
    supported = ok = lenient = unverified = dedup_ok = derived = derived_unmatched = 0
    strict = {}  # calculation id → recomputed value matches, for strict checks on the raw file

    def matches(stored, r):
        return same_value(stored, r["value"]) if "value" in r else any(same_value(stored, v) for v in r["candidates"])

    for cid, c in calcs.items():
        # Calculations on a derived file (df_clean.pkl, an intermediate CSV) are
        # only recomputed when the formula names nothing but CSV columns, and only
        # a match counts: the derivation may have filtered rows.
        is_raw = Path(str(c.get("source_file", ""))).name == source_name
        try:
            r = recompute(c.get("formula"), df, c.get("description", ""))
        except Exception:
            r = None  # a formula we can't evaluate is unsupported, not wrong
        if r is None:
            continue
        try:
            stored = float(c.get("value"))
        except (TypeError, ValueError):
            if is_raw:
                supported += 1
                details.append(f"{cid}: non-numeric value {c.get('value')!r}")
            continue
        if dedup is not None and not matches(stored, r):
            try:
                rd = recompute(c.get("formula"), dedup, c.get("description", ""))
            except Exception:
                rd = None
            if rd is not None and matches(stored, rd):
                r, dedup_ok = rd, dedup_ok + 1
        if "value" in r and not matches(stored, r):
            for frame in (df, dedup) if dedup is not None else (df,):
                v = _named_subset(c.get("formula"), frame, c.get("description", ""), stored)
                if v is not None:
                    r = {"candidates": [v], "lenient": True}
                    break
        if not is_raw:
            if matches(stored, r):
                supported, ok, derived = supported + 1, ok + 1, derived + 1
                lenient += "candidates" in r
            else:
                derived_unmatched += 1
            continue
        if "value" in r:
            supported += 1
            strict[cid] = same_value(stored, r["value"])
            if strict[cid]:
                ok += 1
            else:
                details.append(f"{cid}: {c.get('formula')} [{c.get('description', '')[:40]}] stored {stored} but recomputed {r['value']}")
        elif any(same_value(stored, v) for v in r["candidates"]):
            supported += 1
            ok += 1
            lenient += 1
        else:
            # The description didn't say which group, and no group matches: the formula may mean
            # something else ("weekdays" vs per weekday), so this is unverified, not wrong.
            unverified += 1
    cites = load_citations(artifacts_dir) or {}
    verified = {c.get("calculation_id") for c in cites.values()
                if str(c.get("verification_status", "")).lower() == "verified"} & set(strict)
    false_verified = sorted(cid for cid in verified if not strict[cid])
    if false_verified:
        details.append(f"Validator marked verified but recomputed differently: {false_verified}")
    return {
        "recompute_supported": supported,
        "recompute_total": len(calcs),
        "recompute_lenient": lenient,
        "recompute_unverified": unverified,
        **({"recompute_dedup": dedup_ok} if dedup is not None else {}),
        "recompute_derived": derived,
        "recompute_derived_unmatched": derived_unmatched,
        "recompute_match_rate": ok / supported if supported else None,
        "validator_verified_checked": len(verified),
        "validator_false_verified": len(false_verified),
        "details": details,
    }
