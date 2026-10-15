"""Citation markers must never land inside a number, a range or a date (#141).

Runs the code the Reporter and Auditor prompts tell the agent to write verbatim:
each prompt is rendered with apply_prompt_template, the file content is pulled
out of its write_and_execute_tool call, and executed.

    python3 tests/test_citation_numbers.py
"""
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
VARIANTS = ("managed-agentcore", "self-hosted")

# (spelling, text, numbers parsed from it). Every number here is one end of a range.
RANGES = [(sep, f"{left}{sep}{right}", nums)
          for sep in ("~", "～", "〜", "-", "–", "—", " - ", " ~ ", " – ", " — ")
          for left, right, nums in (("10", "15%", ["10", "15"]),
                                    ("10%", "15%", ["10", "15"]),
                                    ("1,000건", "2,000건", ["1,000", "2,000"]))]
DATES = [("3/9~3/15", ["3", "9", "3", "15"]), ("14:30", ["14", "30"]), ("1:2", ["1", "2"])]


def _prompt(variant, prompt):
    path = ROOT / variant / "src/prompts/template.py"
    spec = importlib.util.spec_from_file_location(f"template_{variant.replace('-', '_')}", path)
    template = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(template)
    return template.apply_prompt_template(prompt, {"USER_REQUEST": "", "FULL_PLAN": ""})


def _tool_file(variant, prompt, file_path):
    """Content of the write_and_execute_tool call that writes `file_path`, as the
    agent writes it out: the text between the quotes, not a Python literal."""
    md = _prompt(variant, prompt)
    start = md.index(f'file_path="{file_path}"')
    return re.compile(r"content=('''|\"\"\")(.*?)\1", re.DOTALL).search(md, start).group(2)


def _stub_docx():
    for name in ("docx", "docx.shared", "docx.enum", "docx.enum.text", "docx.oxml", "docx.oxml.ns"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["docx"].Document = object
    for attr in ("Pt", "RGBColor", "Cm", "Inches"):
        setattr(sys.modules["docx.shared"], attr, object)
    sys.modules["docx.enum.text"].WD_ALIGN_PARAGRAPH = object
    sys.modules["docx.oxml.ns"].qn = str


def _reporter(variant):
    _stub_docx()
    ns = {}
    exec(_tool_file(variant, "reporter", "./artifacts/code/reporter_report_utils.py"), ns)
    return ns


def _auditor(variant):
    ns = {}
    exec(_tool_file(variant, "auditor", "./artifacts/code/audit_engine.py"), ns)
    return ns


class _Run:
    def __init__(self, text):
        self.text = text


class _Para:
    def __init__(self, text):
        self.runs = [_Run(text)]

    @property
    def text(self):
        return "".join(r.text for r in self.runs)


class _Doc:
    def __init__(self, *texts):
        self.paragraphs = [_Para(t) for t in texts]
        self.tables = []


CITATIONS = [
    ("[1]", 111065.13, "총매출"),
    ("[2]", 15, "할인율"),
    ("[3]", 1476, "주문 건수"),
    ("[4]", 8.1, "평균 배송 기간"),
    ("[5]", 1000, "최소 주문"),
    ("[6]", 2000, "최대 주문"),
    ("[7]", 1234567890.125, "누적 거래액"),
    ("[8]", 111065, "결제 금액"),
    ("[9]", 10, "할인율 하한"),
]


class _InArtifacts(unittest.TestCase):
    """Runs each test in a temp dir holding ./artifacts/citations.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.makedirs("artifacts")
        with open("artifacts/citations.json", "w", encoding="utf-8") as f:
            json.dump(self.citations(), f, ensure_ascii=False)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    @staticmethod
    def citations():
        return {"citations": [
            {"citation_id": cid, "calculation_id": f"calc_{cid[1:-1]}", "value": v,
             "description": d, "verification_status": "verified"}
            for cid, v, d in CITATIONS]}


class ReporterResolver(_InArtifacts):
    def resolve(self, variant, *texts):
        doc = _Doc(*texts)
        _reporter(variant)["resolve_body_citations"](doc)
        return [p.text for p in doc.paragraphs]

    def check(self, cases):
        for variant in VARIANTS:
            for (src, want), out in zip(cases.items(), self.resolve(variant, *cases)):
                with self.subTest(variant=variant, src=src):
                    self.assertEqual(out, want)

    def test_single_values(self):
        self.check({
            "총매출은 111,065.13달러, 전년보다": "총매출은 111,065.13달러[1], 전년보다",
            "총매출은 $111,065.13, 전년보다": "총매출은 $111,065.13[1], 전년보다",
            "결제 금액 111,065.78달러 (다른 값)": "결제 금액 111,065.78달러 (다른 값)",
            "주문 건수 1,476건 중": "주문 건수 1,476건[3] 중",
            "평균 배송 기간 8.1일": "평균 배송 기간 8.1일",
            "할인율은 15%였다": "할인율은 15%[2]였다",
            "주문 건수 1,476, 총매출 111,065.13": "주문 건수 1,476[3], 총매출 111,065.13[1]",
            "주문 건수 1,476건,결제 금액 111,065": "주문 건수 1,476건[3],결제 금액 111,065[8]",
            # / and : between a unit and a number join two values, not a range
            "주문 건수 1,476건/결제 금액 111,065원": "주문 건수 1,476건[3]/결제 금액 111,065원[8]",
            "할인율 1위:15%": "할인율 1위:15%[2]",
            # the decimals must round from the citation, also at large magnitudes
            "누적 거래액 1,234,567,890.13": "누적 거래액 1,234,567,890.13[7]",
            "누적 거래액 1,234,567,890.14": "누적 거래액 1,234,567,890.14",
        })

    def test_no_marker_inside_a_range_or_date(self):
        texts = [f"할인율 하한 최대 주문 최소 주문 {t} 할인율" for _, t, _ in RANGES]
        texts += [f"할인율 {t} 할인율" for t, _ in DATES]
        self.check({t: t for t in texts})


class AuditorClaims(_InArtifacts):
    @staticmethod
    def docx(*paras):
        body = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in paras)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
        path = os.path.join(os.getcwd(), "report.docx")
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return path

    def claims(self, variant, para):
        return [(c["value"], c["unit"], c["marker"], c["in_range"])
                for c in _auditor(variant)["extract_claims"](self.docx(para))]

    def findings(self, variant, *paras):
        ns = _auditor(variant)
        return ns["classify"](ns["extract_claims"](self.docx(*paras)), self.citations(), {"calculations": []})

    def test_ranges(self):
        for variant in VARIANTS:
            for sep, text, nums in RANGES:
                with self.subTest(variant=variant, text=text):
                    claims = self.claims(variant, text)
                    self.assertEqual([c[0] for c in claims], [float(n.replace(",", "")) for n in nums])
                    self.assertTrue(all(c[3] for c in claims), claims)
            for text, nums in DATES:
                with self.subTest(variant=variant, text=text):
                    self.assertEqual([(c[0], c[3]) for c in self.claims(variant, text)],
                                     [(float(n), True) for n in nums])

    def test_single_values(self):
        cases = {
            "총매출은 111,065.13달러, 전년보다": [(111065.13, "달러", None, False)],
            "1,476건": [(1476.0, "건", None, False)],
            "8.1일": [(8.1, "일", None, False)],
            "전년 대비 -5.2%p": [(-5.2, "%p", None, False)],
            "매출 100억 -5% 감소": [(100.0, "억", None, False), (-5.0, "%", None, False)],
            "1,476건/111,065원": [(1476.0, "건", None, False), (111065.0, "원", None, False)],
            # a number right after , or . is still a claim; the N of [N] is not
            "1,476건,2,000건[9]": [(1476.0, "건", None, False), (2000.0, "건", "9", False)],
            "끝.2,000건[6]": [(2000.0, "건", "6", False)],
        }
        for variant in VARIANTS:
            for para, want in cases.items():
                with self.subTest(variant=variant, para=para):
                    self.assertEqual(self.claims(variant, para), want)

    def test_classify(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                found = self.findings(
                    variant,
                    "범위 3,000건~4,000건 사이",      # range ends: no Type A
                    "1,000건-2,000건[6]",             # right end is 2,000, matches [6]: no Type B
                    "단일 값 5,000건",                # uncited single value: Type A
                    "합계 1,476건,9,999건[3]",         # 9,999 ≠ [3]: Type B
                )
                types_ = sorted((f["type"], f.get("body_value")) for f in found if f["type"] != "D")
                self.assertEqual(types_, [("A", 5000.0), ("B", 9999.0)])


class SameCodeEverywhere(unittest.TestCase):
    """The number block is shared verbatim by both prompts in both variants."""

    def test_reporter_and_auditor_agree(self):
        def block(variant, prompt):
            md = (ROOT / variant / "src/prompts" / f"{prompt}.md").read_text(encoding="utf-8")
            return re.search(r"^# Number claims, shared verbatim.*?^    return raw, .*?$", md,
                             re.DOTALL | re.MULTILINE).group(0)
        blocks = {block(v, p) for v in VARIANTS for p in ("reporter", "auditor")}
        self.assertEqual(len(blocks), 1)


if __name__ == "__main__":
    unittest.main()
