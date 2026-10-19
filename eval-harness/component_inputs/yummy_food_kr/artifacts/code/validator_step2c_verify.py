import pandas as pd, pickle, json, numpy as np

with open('./artifacts/cache/priority_calcs.pkl', 'rb') as f:
    priority_calcs = pickle.load(f)

df = pd.read_pickle('./artifacts/cache/df_raw.pkl')
df_media = pd.read_pickle('./artifacts/cache/df_media.pkl')
df_cross = pd.read_pickle('./artifacts/cache/df_cross.pkl')

MEDIA = ['쿠빵','네이바','아마존','컬삼']
CATS = ['신선식품','건강식품','간편식']
PRODS = {'프리미엄과일':'신선식품','오메가3':'건강식품','즉석밥세트':'간편식','샐러드키트':'신선식품','프로틴바':'건강식품','냉동만두':'간편식'}

total_cost = df['광고비용'].sum()
total_rev = df['매출액'].sum()
overall_ctr = df['클릭수'].sum() / df['노출수'].sum() * 100
overall_cvr = df['전환수'].sum() / df['클릭수'].sum() * 100
overall_roas = df['매출액'].sum() / df['광고비용'].sum()
overall_cpc = df['광고비용'].sum() / df['클릭수'].sum()
overall_cpa = df['광고비용'].sum() / df['전환수'].sum()

verified = {}

def check(cid, actual, expected, tol=0.02):
    try:
        match = abs(float(actual) - float(expected)) <= max(tol, abs(float(expected))*0.005)
    except (TypeError, ValueError):
        match = str(actual) == str(expected)
    verified[cid] = {'match': bool(match), 'expected': expected, 'actual': actual}

for c in priority_calcs:
    cid = c['id']
    val = c['value']
    if cid == 'total_cost': check(cid, total_cost, val)
    elif cid == 'total_rev': check(cid, total_rev, val)
    elif cid == 'overall_ctr': check(cid, round(overall_ctr,2), val)
    elif cid == 'overall_cvr': check(cid, round(overall_cvr,2), val)
    elif cid == 'overall_roas': check(cid, round(overall_roas,2), val)
    elif cid == 'overall_cpc': check(cid, round(overall_cpc,1), val)
    elif cid == 'overall_cpa': check(cid, round(overall_cpa,1), val)
    elif cid.startswith('media_'):
        parts = cid.split('_')
        media = parts[1]
        metric = '_'.join(parts[2:])
        sub = df[df['매체']==media]
        if metric == 'roas':
            actual = round(sub['매출액'].sum()/sub['광고비용'].sum(), 2)
        elif metric == 'ctr':
            actual = round(sub['클릭수'].sum()/sub['노출수'].sum()*100, 2)
        elif metric == 'cvr':
            actual = round(sub['전환수'].sum()/sub['클릭수'].sum()*100, 2)
        elif metric == 'cost_share':
            actual = round(sub['광고비용'].sum()/total_cost*100, 2)
        elif metric == 'rev_share':
            actual = round(sub['매출액'].sum()/total_rev*100, 2)
        elif metric == 'cpa':
            actual = round(sub['광고비용'].sum()/sub['전환수'].sum(), 1)
        else:
            actual = None
        check(cid, actual, val)
    elif cid.startswith('cat_'):
        parts = cid.split('_')
        cat = parts[1]
        metric = '_'.join(parts[2:])
        sub = df[df['카테고리']==cat]
        if metric == 'roas':
            actual = round(sub['매출액'].sum()/sub['광고비용'].sum(), 2)
        elif metric == 'ctr':
            actual = round(sub['클릭수'].sum()/sub['노출수'].sum()*100, 2)
        elif metric == 'cvr':
            actual = round(sub['전환수'].sum()/sub['클릭수'].sum()*100, 2)
        elif metric == 'cost_share':
            actual = round(sub['광고비용'].sum()/total_cost*100, 2)
        else:
            actual = None
        check(cid, actual, val)
    elif cid.startswith('prod_'):
        parts = cid.split('_')
        prod = parts[1]
        metric = '_'.join(parts[2:])
        sub = df[df['상품명']==prod]
        if metric == 'roas':
            actual = round(sub['매출액'].sum()/sub['광고비용'].sum(), 2)
        elif metric == 'ctr':
            actual = round(sub['클릭수'].sum()/sub['노출수'].sum()*100, 2)
        elif metric == 'cvr':
            actual = round(sub['전환수'].sum()/sub['클릭수'].sum()*100, 2)
        elif metric == 'cost':
            actual = sub['광고비용'].sum()
        else:
            actual = None
        check(cid, actual, val)
    elif cid.startswith('cross_') and cid.endswith('_roas'):
        parts = cid.split('_')
        media = parts[1]
        cat = parts[2]
        sub = df[(df['매체']==media)&(df['카테고리']==cat)]
        actual = round(sub['매출액'].sum()/sub['광고비용'].sum(), 2)
        check(cid, actual, val)
    elif cid == 'below_avg_media_cost':
        media_roas = df.groupby('매체').apply(lambda g: g['매출액'].sum()/g['광고비용'].sum())
        below = media_roas[media_roas < overall_roas].index.tolist()
        actual = df[df['매체'].isin(below)]['광고비용'].sum()
        verified[cid] = {'match': abs(actual-val) <= max(0.02, abs(val)*0.005), 'expected': actual, 'actual': val, 'note': f'below_avg media={below}'}
    elif cid == 'below_avg_media_cost_share':
        media_roas = df.groupby('매체').apply(lambda g: g['매출액'].sum()/g['광고비용'].sum())
        below = media_roas[media_roas < overall_roas].index.tolist()
        actual = round(df[df['매체'].isin(below)]['광고비용'].sum()/total_cost*100, 2)
        check(cid, actual, val)
    elif cid == 'naver_rev_gap':
        sub = df[df['매체']=='네이바']
        actual = round(sub['광고비용'].sum()*overall_roas - sub['매출액'].sum(), 1)
        check(cid, actual, val, tol=50000)
    elif cid == 'corr_ctr_cvr':
        actual = round(df['CTR'].corr(df['전환율']), 3)
        check(cid, actual, val, tol=0.005)
    elif cid == 'corr_cost_roas':
        actual = round(df['광고비용'].corr(df['ROAS']), 3)
        check(cid, actual, val, tol=0.005)
    elif cid == 'corr_ctr_roas':
        actual = round(df['CTR'].corr(df['ROAS']), 3)
        check(cid, actual, val, tol=0.005)
    elif cid == 'corr_cvr_roas':
        actual = round(df['전환율'].corr(df['ROAS']), 3)
        check(cid, actual, val, tol=0.005)
    elif cid == 'naver_ctr_vs_cvr_gap':
        sub = df[df['매체']=='네이바']
        ctr = sub['클릭수'].sum()/sub['노출수'].sum()*100
        cvr = sub['전환수'].sum()/sub['클릭수'].sum()*100
        actual = round(ctr - cvr, 2)
        check(cid, actual, val)
    elif cid == 'daily_roas_max':
        daily = df.groupby('날짜').apply(lambda g: g['매출액'].sum()/g['광고비용'].sum())
        actual = round(daily.max(), 2)
        check(cid, actual, val)
    elif cid == 'daily_roas_min':
        daily = df.groupby('날짜').apply(lambda g: g['매출액'].sum()/g['광고비용'].sum())
        actual = round(daily.min(), 2)
        check(cid, actual, val)
    elif cid in ('weekend_roas','weekday_roas'):
        d2 = df.copy()
        d2['날짜dt'] = pd.to_datetime(d2['날짜'])
        d2['dow'] = d2['날짜dt'].dt.dayofweek  # 5,6 = sat sun
        if cid == 'weekend_roas':
            sub = d2[d2['dow']>=5]
        else:
            sub = d2[d2['dow']<5]
        actual = round(sub['매출액'].sum()/sub['광고비용'].sum(), 2)
        check(cid, actual, val)
    elif cid == 'strategy1_naver_cut_amount':
        sub = df[df['매체']=='네이바']
        actual = round(sub['광고비용'].sum()*0.30, 1)
        check(cid, actual, val, tol=1)
    elif cid == 'strategy1_net_rev_gain':
        sub_n = df[df['매체']=='네이바']
        sub_k = df[df['매체']=='쿠빵']
        roas_n = sub_n['매출액'].sum()/sub_n['광고비용'].sum()
        roas_k = sub_k['매출액'].sum()/sub_k['광고비용'].sum()
        cut = sub_n['광고비용'].sum()*0.30
        actual = round(cut*roas_k - cut*roas_n, 1)
        check(cid, actual, val, tol=1000)
    elif cid == 'strategy2_amazon_health_roas':
        sub = df[(df['매체']=='아마존')&(df['카테고리']=='건강식품')]
        actual = round(sub['매출액'].sum()/sub['광고비용'].sum(), 2)
        check(cid, actual, val)
    elif cid == 'strategy2_increase_amount':
        sub = df[(df['매체']=='아마존')&(df['카테고리']=='건강식품')]
        actual = round(sub['광고비용'].sum()*0.5, 1)
        check(cid, actual, val, tol=1)
    elif cid == 'strategy2_conservative_roas':
        sub = df[(df['매체']=='아마존')&(df['카테고리']=='건강식품')]
        roas = sub['매출액'].sum()/sub['광고비용'].sum()
        actual = round(roas*0.7, 2)
        check(cid, actual, val)
    elif cid == 'strategy2_expected_rev':
        sub = df[(df['매체']=='아마존')&(df['카테고리']=='건강식품')]
        roas = sub['매출액'].sum()/sub['광고비용'].sum()
        increase = sub['광고비용'].sum()*0.5
        actual = round(increase*roas*0.7, 1)
        check(cid, actual, val, tol=1000)
    elif cid == 'strategy3_naver_cvr':
        sub = df[df['매체']=='네이바']
        actual = round(sub['전환수'].sum()/sub['클릭수'].sum()*100, 2)
        check(cid, actual, val)
    elif cid == 'strategy3_target_cvr':
        sub_n = df[df['매체']=='네이바']
        sub_k = df[df['매체']=='쿠빵']
        cvr_n = sub_n['전환수'].sum()/sub_n['클릭수'].sum()*100
        cvr_k = sub_k['전환수'].sum()/sub_k['클릭수'].sum()*100
        actual = round(cvr_n + (cvr_k-cvr_n)*0.2, 2)
        check(cid, actual, val)
    elif cid == 'strategy3_naver_aov':
        sub = df[df['매체']=='네이바']
        actual = round(sub['매출액'].sum()/sub['전환수'].sum(), 1)
        check(cid, actual, val, tol=5)
    elif cid == 'strategy3_additional_conv':
        sub_n = df[df['매체']=='네이바']
        sub_k = df[df['매체']=='쿠빵']
        cvr_n = sub_n['전환수'].sum()/sub_n['클릭수'].sum()*100
        cvr_k = sub_k['전환수'].sum()/sub_k['클릭수'].sum()*100
        target_cvr = cvr_n + (cvr_k-cvr_n)*0.2
        actual = round(sub_n['클릭수'].sum()*(target_cvr-cvr_n)/100, 1)
        check(cid, actual, val, tol=10)
    elif cid == 'strategy3_additional_rev':
        sub_n = df[df['매체']=='네이바']
        sub_k = df[df['매체']=='쿠빵']
        cvr_n = sub_n['전환수'].sum()/sub_n['클릭수'].sum()*100
        cvr_k = sub_k['전환수'].sum()/sub_k['클릭수'].sum()*100
        target_cvr = cvr_n + (cvr_k-cvr_n)*0.2
        add_conv = sub_n['클릭수'].sum()*(target_cvr-cvr_n)/100
        aov = sub_n['매출액'].sum()/sub_n['전환수'].sum()
        actual = round(add_conv*aov, 1)
        check(cid, actual, val, tol=500000)
    elif cid == 'strategy3_rev_increase_pct':
        sub_n = df[df['매체']=='네이바']
        sub_k = df[df['매체']=='쿠빵']
        cvr_n = sub_n['전환수'].sum()/sub_n['클릭수'].sum()*100
        cvr_k = sub_k['전환수'].sum()/sub_k['클릭수'].sum()*100
        target_cvr = cvr_n + (cvr_k-cvr_n)*0.2
        add_conv = sub_n['클릭수'].sum()*(target_cvr-cvr_n)/100
        aov = sub_n['매출액'].sum()/sub_n['전환수'].sum()
        add_rev = add_conv*aov
        actual = round(add_rev/sub_n['매출액'].sum()*100, 1)
        check(cid, actual, val, tol=1)
    else:
        verified[cid] = {'match': None, 'expected': 'NOT_IMPLEMENTED', 'actual': val, 'note': 'no_verifier'}

match_count = sum(1 for v in verified.values() if v.get('match') is True)
no_match = sum(1 for v in verified.values() if v.get('match') is False)
no_impl = sum(1 for v in verified.values() if v.get('match') is None)
print(f"Verified matches: {match_count}, mismatches: {no_match}, not_implemented: {no_impl}, total: {len(verified)}")

mismatches = [(cid, v) for cid, v in verified.items() if v.get('match') is False]
print(f"\nMismatches ({len(mismatches)}):")
for cid, v in mismatches:
    print(f"  {cid}: expected(coder)={v['actual']} vs recalculated={v['expected']}")

not_impl = [cid for cid, v in verified.items() if v.get('match') is None]
print(f"\nNot implemented ({len(not_impl)}): {not_impl}")

with open('./artifacts/cache/verified.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("Cached verified.pkl")
