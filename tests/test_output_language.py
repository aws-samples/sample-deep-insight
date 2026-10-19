"""OUTPUT_LANGUAGE: the language every agent writes in, set once from the request.

Run from the repo root: python -m unittest tests.test_output_language

The eval scenarios' queries (eval-harness/config/scenarios.yaml), wrapped the
way agentcore_runtime.py wraps a request, must come out as the language they
are written in, and the prompts that write files or the report must carry the
value in their header.
"""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITIONS = ("managed-agentcore", "self-hosted")
WRITERS = ("coder", "validator", "reporter", "auditor")


def load_template(edition):
    path = os.path.join(ROOT, edition, "src", "prompts", "template.py")
    spec = importlib.util.spec_from_file_location(f"template_{edition.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (query, language): the Korean and English requests of the eval scenarios
QUERIES = [
    ("jungle-market-sales.csv 는 분석 파일이고, column_definitions.json은 컬럼에 대한 설명입니다.\n"
     "데이터에서 비즈니스 성장 기회를 발굴해줘: 숨겨진 고객 패턴과 세그먼트를 발견하고, 수익 최적화 방안을 제시하며,\n"
     "다음 달 매출을 크게 늘릴 수 있는 실행 가능한 전략 3가지를 우선순위와 기대 효과를 포함해서 제안해줘.\n"
     "결과는 DOCX로 저장해줘.", "Korean"),
    ("jungle-market-sales.csv 는 분석 파일이고, column_definitions.json은 컬럼에 대한 설명입니다.\n"
     "총 매출액, 주문 건수, 평균 주문 금액을 계산하고 카테고리별 매출 비중도 함께 보여줘. 결과물을 DOCX로 만들어줘.", "Korean"),
    ("yummy-food-market.csv 는 분석 파일이고, column_definitions.json은 컬럼에 대한 설명입니다.\n"
     "매체별·카테고리별·상품별 광고 성과(CTR, 전환율, ROAS)를 분석해서 광고비가 어디서 효율적으로 쓰이고\n"
     "어디서 낭비되는지 찾아주고, 광고비 효율을 높일 수 있는 실행 가능한 전략 3가지를\n"
     "우선순위와 기대 효과를 포함해서 제안해줘. 결과는 DOCX로 저장해줘.", "Korean"),
    ("jungle-market-sales.csv is the data file and column_definitions.json describes the columns.\n"
     "Find business growth opportunities in the data: discover hidden customer patterns and segments,\n"
     "and propose 3 actionable strategies to significantly grow next month's revenue. Save the result as DOCX.", "English"),
    ("yummy-food-market.csv is the data file and column_definitions.json describes the columns.\n"
     "Analyze ad performance (CTR, conversion rate, ROAS) by media, category and product, find where\n"
     "ad spend is used efficiently and where it is wasted. Save the result as DOCX.", "English"),
]


class OutputLanguageTest(unittest.TestCase):
    def test_scenario_queries(self):
        for edition in EDITIONS:
            detect = load_template(edition).detect_output_language
            for query, expected in QUERIES:
                request = f"AgentCore Request: <user_request>{query}</user_request>"
                with self.subTest(edition=edition, query=query[:40]):
                    self.assertEqual(detect(request), expected)

    def test_names_in_latin_letters_dont_flip_the_language(self):
        detect = load_template(EDITIONS[0]).detect_output_language
        self.assertEqual(detect("jungle-market-sales.csv, column_definitions.json 로 CTR, ROAS 분석해줘"), "Korean")
        self.assertEqual(detect("Compare 쿠빵 and Neiba by ROAS"), "English")
        self.assertEqual(detect(""), "the language of USER_REQUEST")

    def test_writer_prompts_carry_it(self):
        for edition in EDITIONS:
            template = load_template(edition)
            for name in WRITERS:
                rendered = template.apply_prompt_template(name, {
                    "USER_REQUEST": "AgentCore Request: <user_request>Analyze ROAS by media.</user_request>",
                    "FULL_PLAN": "", "EXECUTION_ENVIRONMENT": ""})
                with self.subTest(edition=edition, prompt=name):
                    self.assertIn("OUTPUT_LANGUAGE: English\n", rendered.split("---")[1])
            reporter = template.apply_prompt_template("reporter", {
                "USER_REQUEST": "<user_request>매체별 ROAS 분석해줘</user_request>",
                "FULL_PLAN": "", "EXECUTION_ENVIRONMENT": ""})
            self.assertIn("if 'Korean' == 'Korean'", reporter)


if __name__ == "__main__":
    unittest.main()
