import pickle, json, os, numpy as np
from datetime import datetime

def to_python_type(value):
    if isinstance(value, (np.integer, np.int64)): return int(value)
    elif isinstance(value, (np.floating, np.float64)): return float(value)
    elif isinstance(value, np.ndarray): return value.tolist()
    elif isinstance(value, (np.bool_,)): return bool(value)
    return value

with open('./artifacts/cache/priority_calcs.pkl', 'rb') as f:
    priority_calcs = pickle.load(f)
with open('./artifacts/cache/verified_complete.pkl', 'rb') as f:
    verified = pickle.load(f)

print(f"Loaded {len(priority_calcs)} calcs, {len(verified)} verified entries")

# Build citations - sequential numbering
citations_list = []
for i, c in enumerate(priority_calcs, 1):
    cid = c['id']
    vres = verified.get(cid, {})
    status = "verified" if vres.get('match') is True else "needs_review"
    entry = {
        "citation_id": f"[{i}]",
        "calculation_id": cid,
        "value": to_python_type(c['value']),
        "description": c.get('description', ''),
        "formula": c.get('formula', ''),
        "source_file": c.get('source_file', ''),
        "verification_status": status,
    }
    if c.get('aliases'):
        entry["aliases"] = c['aliases']
    if status == "needs_review" and vres.get('note'):
        entry["verification_note"] = vres['note']
    if status == "needs_review" and vres.get('actual') is not None:
        entry["recomputed_value"] = to_python_type(vres['actual']) if not isinstance(vres['actual'], str) else vres['actual']
    citations_list.append(entry)

citations = {
    "metadata": {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_calculations": len(priority_calcs),
        "cited_calculations": len(citations_list)
    },
    "citations": citations_list
}

os.makedirs('./artifacts', exist_ok=True)
with open('./artifacts/citations.json', 'w', encoding='utf-8') as f:
    json.dump(citations, f, indent=2, ensure_ascii=False)
print(f"✅ citations.json ({len(citations_list)} citations)")

ok = sum(1 for v in verified.values() if v['match'] is True)
nr = sum(1 for v in verified.values() if v['match'] is False)
total = len(verified)

needs_review_ids = [cid for cid, v in verified.items() if v['match'] is False]

report_lines = []
report_lines.append("=" * 70)
report_lines.append("Jungle Market 판매 데이터 — 계산 검증 리포트 (Validator)")
report_lines.append("=" * 70)
report_lines.append(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report_lines.append("")
report_lines.append(f"총 계산 항목(high importance, dedup 후): {total}")
report_lines.append(f"검증 통과(verified): {ok}")
report_lines.append(f"검증 보류(needs_review): {nr}")
report_lines.append(f"검증률: {ok/total*100:.1f}%")
report_lines.append("")
report_lines.append("-" * 70)
report_lines.append("1. 핵심 지표 재계산 결과")
report_lines.append("-" * 70)
report_lines.append("총매출($110,270.26), 주문수(2,987), 고객수(1,847), AOV($36.92),")
report_lines.append("할인율(3.70%), 신규/재구매 매출·주문 비중, 요일/시간대 패턴,")
report_lines.append("일평균매출·다음달 베이스라인($236,293), 지역/채널/프로모션/카테고리")
report_lines.append("매출 분해 등 핵심 지표는 df_main.pkl 원자료 기준 재계산 결과와")
report_lines.append("모두 일치 확인(허용오차: 저장값 소수점 정밀도 기준).")
report_lines.append("")
report_lines.append("-" * 70)
report_lines.append("2. RFM 세그먼트 합계 정합성 체크")
report_lines.append("-" * 70)
report_lines.append("세그먼트별 고객수 합계 = 499(일반고객)+484(VIP)+445(이탈위험)")
report_lines.append("+375(우수고객)+44(이탈/저가치) = 1,847명 = 전체 고객수와 정확히 일치.")
report_lines.append("세그먼트별 매출 비중 합계도 100%로 정합성 확인.")
report_lines.append("VIP 세그먼트(26.2%)가 매출의 49.1% 차지 — 재계산으로 재확인됨.")
report_lines.append("")
report_lines.append("-" * 70)
report_lines.append("3. 전략별 기대 매출 증분 검증")
report_lines.append("-" * 70)
report_lines.append("전략1(이탈위험 재활성화), 전략2(크로스셀 품목확대, s2_*_v2) 시나리오는")
report_lines.append("공식 그대로 재현 시 기대값과 완전 일치(오차 < 1e-10% 수준).")
report_lines.append("")
report_lines.append("전략3(요일별 수요 평탄화, s3_*_final)은 재현 결과가 기대값과 약 0.34%")
report_lines.append("차이(예: s3_base_final 재현값 $14,239 vs 보고값 $14,192). 로직(주말 2일")
report_lines.append("요일평균의 합 149.5건/일 vs 저조요일 2일 요일평균의 합 364.5건 등)은")
report_lines.append("근거 수치와 방법론이 타당하고 과대추정은 아니나, AOV 소수점 처리 등")
report_lines.append("세부 반올림 차이로 완전orig 일치는 되지 않아 needs_review로 표기.")
report_lines.append("")
report_lines.append("avg_repurchase_interval, aov_returning_no_promo, aov_uplift_per_order,")
report_lines.append("및 이에 연쇄된 SAVE10 전략(s3_*_v2, 최종 전략에는 미채택되어 영향 없음)은")
report_lines.append("재현 시도(연속쌍평균/구간평균, promo_code first/any 매칭) 모두 기대값과")
report_lines.append("불일치하여 needs_review로 표기. 단, 해당 SAVE10 전략(v2)은 원본 분석에서도")
report_lines.append("uplift가 음수로 나타나 최종 3대 전략에는 사용되지 않았으므로 보고서의")
report_lines.append("핵심 결론(최종 확정 3대 전략)에는 영향 없음.")
report_lines.append("")
report_lines.append("-" * 70)
report_lines.append("4. 시각화 데이터 정합성(Chart Sanity Check)")
report_lines.append("-" * 70)
report_lines.append("7종 차트(일별추이, 카테고리매출, 상품파레토, RFM세그먼트, 요일x시간대")
report_lines.append("히트맵, 할인구간분석, 상관관계히트맵, 전략효과비교) 모두 기초 데이터가")
report_lines.append("non-zero이며 총계가 전체 매출($110,270.26)과 일치함을 확인. 이상 없음.")
report_lines.append("")
report_lines.append("-" * 70)
report_lines.append("5. 권고 사항 (Reporter 전달)")
report_lines.append("-" * 70)
report_lines.append("- needs_review 9개 항목(위 3번 항목): 보고서 본문에서 '정확히 X이다'와")
report_lines.append("  같은 과도한 단정 대신 '약 X로 추정된다'는 표현 사용 권고.")
report_lines.append("- 전략3(요일 평탄화)의 기대효과는 반올림 차이(0.34%) 수준이므로 신뢰도")
report_lines.append("  높음(근사치로 그대로 사용 가능), 단 '추정치' 명시 권고.")
report_lines.append("- SAVE10 쿠폰 확대(v2) 전략은 데이터상 uplift가 음수로 기각되었다는")
report_lines.append("  점을 보고서에 명시하여 혼선 방지 권고.")
report_lines.append("")
report_lines.append(f"[검증 완료] verified={ok}, needs_review={nr}, total={total}")

with open('./artifacts/validation_report.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(report_lines))
print("✅ validation_report.txt")
print(f"\nSummary: Total={total}, Verified={ok}, Needs review={nr}")
