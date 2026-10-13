"""Citation markers must never land inside a number, a range or a date (#141).

Runs the code the Reporter and Auditor prompts tell the agent to write verbatim:
each prompt is rendered the way template.py does, the file content is pulled
out of its write_and_execute_tool call, and executed.

    python3 tests/test_citation_numbers.py
"""
import ast
import json
import os
import re
import sys
import tempfile
import types
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VARIANTS = ("managed-agentcore", "self-hosted")


def _tool_file(variant, prompt, file_path):
    """Content of the write_and_execute_tool call that writes `file_path`."""
    md = (ROOT / variant / "src/prompts" / f"{prompt}.md").read_text(encoding="utf-8")
    md = md.format_map(defaultdict(str))
    start = md.index(f'file_path="{file_path}"')
    m = re.compile(r"content=('''|\"\"\")(.*?)\1", re.DOTALL).search(md, start)
    return ast.literal_eval(m.group(1) + m.group(2) + m.group(1))


def _stub_docx():
    for name in ("docx", "docx.shared", "docx.enum", "docx.enum.text", "docx.oxml", "docx.oxml.ns"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["docx"].Document = object
    for attr in ("Pt", "RGBColor", "Cm", "Inches"):
        setattr(sys.modules["docx.shared"], attr, object)
    sys.modules["docx.enum.text"].WD_ALIGN_PARAGRAPH = object
    sys.modules["docx.oxml.ns"].qn = str


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
    ("[5]", 2024, "기준 연도"),
    ("[6]", 3, "시작 월"),
]


class ReporterResolver(unittest.TestCase):
    def setUp(self):
        _stub_docx()
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.makedirs("artifacts")
        with open("artifacts/citations.json", "w", encoding="utf-8") as f:
            json.dump({"citations": [
                {"citation_id": cid, "value": v, "description": d, "verification_status": "verified"}
                for cid, v, d in CITATIONS]}, f, ensure_ascii=False)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def resolve(self, variant, *texts):
        ns = {}
        exec(_tool_file(variant, "reporter", "./artifacts/code/reporter_report_utils.py"), ns)
        doc = _Doc(*texts)
        ns["resolve_body_citations"](doc)
        return [p.text for p in doc.paragraphs]

    def test_markers(self):
        cases = {
            "총매출은 111,065.13달러, 전년보다": "총매출은 111,065.13달러[1], 전년보다",
            "총매출은 $111,065.13, 전년보다": "총매출은 $111,065.13[1], 전년보다",
            "총매출은 약 111,065달러 수준": "총매출은 약 111,065달러[1] 수준",
            "총매출 111,065.78달러 (다른 값)": "총매출 111,065.78달러 (다른 값)",
            "할인율 10~15% 적용": "할인율 10~15% 적용",
            "할인율 10% ~ 15% 적용": "할인율 10% ~ 15% 적용",
            "시작 월 3/9~3/15 행사": "시작 월 3/9~3/15 행사",
            "주문 건수 1,476건 중": "주문 건수 1,476건[3] 중",
            "평균 배송 기간 8.1일": "평균 배송 기간 8.1일",
            "할인율은 15%였다": "할인율은 15%[2]였다",
            "기준 연도 2024-2025 비교": "기준 연도 2024-2025 비교",
            "주문 건수 1,476, 총매출 111,065.13": "주문 건수 1,476[3], 총매출 111,065.13[1]",
        }
        for variant in VARIANTS:
            got = self.resolve(variant, *cases)
            for (src, want), out in zip(cases.items(), got):
                with self.subTest(variant=variant, src=src):
                    self.assertEqual(out, want)
                    self.assertNotRegex(out, r"\d\s?\[\d+\]\s?[.,~/]?\d")


class AuditorClaims(unittest.TestCase):
    def claims(self, variant, para):
        ns = {}
        exec(_tool_file(variant, "auditor", "./artifacts/code/audit_engine.py"), ns)
        return [(m.group(1), m.group(2) or "", ns["_RANGE_L"].search(para, 0, m.start(1)) is not None
                 or ns["_RANGE_R"].match(para, m.end(1)) is not None)
                for m in ns["_NUM_RE"].finditer(para)]

    def test_numbers(self):
        cases = {
            "총매출은 111,065.13달러, 전년보다": [("111,065.13", "달러", False)],
            "10~15% 할인": [("10", "", True), ("15", "%", True)],
            "3/9~3/15": [("3", "", True), ("9", "", True), ("3", "", True), ("15", "", True)],
            "1,476건": [("1,476", "건", False)],
            "8.1일": [("8.1", "일", False)],
            "전년 대비 -5.2%p": [("-5.2", "%p", False)],
        }
        for variant in VARIANTS:
            for para, want in cases.items():
                with self.subTest(variant=variant, para=para):
                    self.assertEqual(self.claims(variant, para), want)


class SameRegexEverywhere(unittest.TestCase):
    def test_reporter_and_auditor_agree(self):
        def pattern(variant, prompt, name):
            md = (ROOT / variant / "src/prompts" / f"{prompt}.md").read_text(encoding="utf-8")
            line = re.search(rf"^\s*{name} = (.*)$", md, re.MULTILINE).group(1)
            return line.replace("unit_re", "U").replace("_UNIT", "U").replace("(?:\\[(\\d+)\\])", "(\\[\\d+\\])")
        for r_name, a_name in (("unit_re", "_UNIT"), ("num_re", "_NUM_RE"),
                               ("range_l", "_RANGE_L"), ("range_r", "_RANGE_R")):
            got = {pattern(v, p, n) for v in VARIANTS for p, n in (("reporter", r_name), ("auditor", a_name))}
            self.assertEqual(len(got), 1, got)


if __name__ == "__main__":
    unittest.main()
