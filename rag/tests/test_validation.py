"""Deterministic citation checks and entailment-verifier parsing tests."""

import json

import pytest

from trendee_rag.llm import LLMResponse
from trendee_rag.validation import Claim, extract_claims, validate_citations, verify_entailment

SOURCES = [
    {
        "text": "生成式引擎正在改变用户获取信息的入口，品牌需要让内容进入 AI 的回答。",
        "excerpt": "生成式引擎正在改变用户获取信息的入口...",
    },
    {
        "text": "LLM 原生 GEO 通过结构化知识把品牌信息写入模型可检索的语料。",
        "excerpt": "LLM 原生 GEO 通过结构化知识...",
    },
]

VALID_PARAGRAPH = "生成式引擎正在改变用户获取信息的入口，品牌需要让内容进入 AI 的回答。[1]"
UNCITED_PARAGRAPH = "品牌需要让内容进入 AI 的回答，因此必须重视生成式引擎带来的入口变化。"


class FakeVerifierLLM:
    model_id = "fake-verifier"

    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def complete(self, messages, temperature, max_tokens):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        return LLMResponse(self.text, "stop", self.model_id)


def test_extract_claims_skips_headings_and_short_text():
    markdown = f"# 标题\n\n短句。\n\n## 一、章节\n\n{VALID_PARAGRAPH}\n"
    claims = extract_claims(markdown)

    assert len(claims) == 1
    assert claims[0].id == "c001"
    assert claims[0].markers == [1]
    assert "[1]" not in claims[0].text


def test_short_paragraph_with_number_is_checked():
    markdown = "## 一、章节\n\n服务超过 500 家客户。\n"
    claims = extract_claims(markdown)
    result = validate_citations(markdown, SOURCES)

    assert len(claims) == 1
    assert not result.passed
    assert "MISSING_CITATION" in {issue.code for issue in result.issues}


def test_valid_citation_passes():
    result = validate_citations(f"## 一、章节\n\n{VALID_PARAGRAPH}\n", SOURCES)

    assert result.passed
    assert result.cited_sources == {1}
    assert result.support[1] >= 0.20


def test_invalid_marker_and_missing_citation_fail():
    markdown = (
        "## 一、章节\n\n"
        "生成式引擎正在改变用户获取信息的入口，品牌需要让内容进入 AI 的回答。[9]\n\n"
        f"{UNCITED_PARAGRAPH}\n"
    )
    result = validate_citations(markdown, SOURCES)

    assert not result.passed
    codes = {issue.code for issue in result.issues}
    assert "INVALID_MARKER" in codes
    assert "MISSING_CITATION" in codes


def test_table_row_without_citation_fails():
    markdown = (
        "## 一、章节\n\n"
        "| 指标 | 说明 |\n"
        "| --- | --- |\n"
        "| 品牌内容进入 AI 回答的入口 | 生成式引擎正在改变用户获取信息的入口，品牌需要让内容进入 AI 的回答 |\n"
    )
    result = validate_citations(markdown, SOURCES)

    assert not result.passed
    assert "MISSING_CITATION" in {issue.code for issue in result.issues}


def test_ordered_list_number_is_not_treated_as_a_fact():
    markdown = (
        "## 一、章节\n\n"
        "1. 生成式引擎正在改变用户获取信息的入口，品牌需要让内容进入 AI 的回答。[1]\n"
    )
    result = validate_citations(markdown, SOURCES)

    assert result.passed
    assert result.claims[0].text.startswith("生成式引擎")


def test_list_intro_before_bullets_is_checked():
    markdown = (
        "## 一、章节\n\n"
        "以下说明为什么品牌内容需要进入生成式引擎的回答范围。\n\n"
        "- 生成式引擎正在改变用户获取信息的入口，品牌需要让内容进入 AI 的回答。[1]\n"
    )
    result = validate_citations(markdown, SOURCES)

    assert len(result.claims) == 2
    assert not result.passed
    assert "MISSING_CITATION" in {issue.code for issue in result.issues}


def test_fabricated_number_and_negation_fail():
    source = [{"text": "Trendee 不是一家传统 SEO 公司，而是一家 GEO 服务商。", "excerpt": "..."}]
    markdown = (
        "## 一、章节\n\n"
        "Trendee 已经服务超过 500 家中国出海客户，并且是一家传统 SEO 公司。[1]\n"
    )
    result = validate_citations(markdown, source)

    assert not result.passed
    codes = {issue.code for issue in result.issues}
    assert "FABRICATED_NUMBER" in codes
    assert "NEGATION_MISMATCH" in codes


def test_b2b_digit_is_not_a_fabricated_number():
    source = [{"text": "在 B2B 场景中，该工厂在 30 天内实现询盘量增加 20%。", "excerpt": "..."}]
    markdown = "## 一、章节\n\n在 B2B 场景中，该工厂在 30 天内实现询盘量增加 20%。[1]\n"
    result = validate_citations(markdown, source)

    assert result.passed


def test_positive_and_negative_clauses_match_separate_source_bullets():
    source = [
        {
            "text": (
                "优化前是技术参数型说明，缺乏场景关联。\n"
                "优化后关联用户生活场景，明确用户人群。"
            ),
            "excerpt": "...",
        }
    ]
    markdown = (
        "## 一、章节\n\n"
        "优化前是技术参数型说明、缺乏场景关联；优化后关联用户生活场景、明确用户人群。[1]\n"
    )
    result = validate_citations(markdown, source)

    assert result.passed


def test_negated_clause_can_match_a_different_source_cell_than_the_best_overlap():
    source = [
        {
            "text": (
                "对比维度 LLM-原生 GEO 传统 GEO\n"
                "意图匹配 语义理解 关键词匹配\n"
                "语义结构化 深度语义标签 缺少支持\n"
                "推荐逻辑 AI 深层推理 短期迷惑RAG"
            ),
            "excerpt": "...",
        }
    ]
    markdown = (
        "## 一、章节\n\n"
        "传统 GEO 对应关键词匹配、缺少支持与短期迷惑 RAG。[1]\n"
    )
    result = validate_citations(markdown, source)

    assert result.passed


def test_positive_cell_is_not_matched_with_a_negative_cell_from_the_same_table_row():
    source = [
        {
            "text": "语义结构化 深度语义标签 缺少支持\n推荐逻辑 AI 深层推理 短期迷惑RAG",
            "excerpt": "...",
        }
    ]
    markdown = "## 一、章节\n\n资料将语义结构化表述为深度语义标签，并将推荐逻辑表述为 AI 深层推理。[1]\n"
    result = validate_citations(markdown, source)

    assert result.passed


def test_unrelated_negation_in_source_does_not_reject_positive_claim():
    source = [
        {
            "text": "传统外贸渠道流量持续减少，品牌在 AI 世界无法被看到。\n优化后 30 天内询盘量增加 20%。",
            "excerpt": "...",
        }
    ]
    markdown = "## 一、章节\n\n优化后 30 天内询盘量增加 20%。[1]\n"
    result = validate_citations(markdown, source)

    assert result.passed


def test_insufficient_evidence_disclaimer_is_not_a_negation_mismatch():
    source = [
        {
            "text": "按行业划分的成本、周期与投入产出数据，现有资料未提供，相关预算判断无法由现有资料得出。",
            "excerpt": "...",
        }
    ]
    markdown = (
        "## 一、章节\n\n按行业划分的成本、周期与投入产出数据，现有资料不足以支持，"
        "相关预算判断无法由现有资料得出。[1]\n"
    )
    result = validate_citations(markdown, source)

    assert result.passed


def test_insufficient_evidence_disclaimer_is_not_low_overlap():
    source = [
        {
            "text": "Trendee 的 LLM-原生 GEO 技术体系覆盖品牌价值蒸馏、问题预测与内容生成。",
            "excerpt": "...",
        }
    ]
    markdown = (
        "## 一、章节\n\n现有资料不足以支持按行业划分的适用场景；"
        "以下内容仅依据资料中的产品目标归纳。[1]\n"
    )
    result = validate_citations(markdown, source)

    assert result.passed


def test_difficulty_word_is_not_treated_as_negation():
    source = [
        {
            "text": "传统“孤岛”营销中，AI 难以形成连贯、权威的品牌认知。",
            "excerpt": "...",
        }
    ]
    markdown = (
        "## 一、章节\n\n"
        "传统“孤岛”营销中，这直接影响了 AI 对品牌形成连贯、权威认知的过程。[1]\n"
    )
    result = validate_citations(markdown, source)

    assert result.passed


def test_no_moq_is_not_mistaken_for_english_negation():
    source = [{"text": "合作后的核心优势是 NO-MOQ（无最小起订量），不压货、采购灵活。", "excerpt": "..."}]
    markdown = "## 一、章节\n\n合作后的核心优势是 NO-MOQ（无最小起订量），不压货、采购灵活。[1]\n"
    result = validate_citations(markdown, source)

    assert result.passed


def test_absence_word_matches_absence_word():
    source = [{"text": "优化前的表述是技术参数型说明，缺乏场景关联。", "excerpt": "..."}]
    markdown = "## 一、章节\n\n优化前的表述是技术参数型说明，缺乏场景关联。[1]\n"
    result = validate_citations(markdown, source)

    assert result.passed


def test_number_must_not_match_as_substring():
    source = [{"text": "样本服务覆盖 1500 家门店，相关内容仅用于测试。", "excerpt": "..."}]
    markdown = "## 一、章节\n\n样本服务覆盖 500 家门店，相关内容仅用于测试。[1]\n"
    result = validate_citations(markdown, source)

    assert not result.passed
    assert "FABRICATED_NUMBER" in {issue.code for issue in result.issues}

    exact_source = [{"text": "样本服务覆盖 500 家门店，相关内容仅用于测试。", "excerpt": "..."}]
    assert validate_citations(markdown, exact_source).passed


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        '{"claims": []}',
        '{"claims": [{"id": "c001", "verdict": "supported", "reason": "x"}, '
        '{"id": "c001", "verdict": "supported", "reason": "x"}]}',
        '{"claims": [{"id": "c999", "verdict": "supported", "reason": "x"}]}',
        '{"claims": [{"id": "c001", "verdict": "maybe", "reason": "x"}]}',
    ],
)
def test_verifier_fail_closed_on_malformed_output(output):
    result = verify_entailment(
        [Claim("c001", "品牌需要让内容进入 AI 的回答。", [1])],
        SOURCES,
        FakeVerifierLLM(output),
    )

    assert not result.passed
    assert result.malformed


@pytest.mark.parametrize("verdict", ["unsupported", "uncertain"])
def test_verifier_rejects_unsupported_and_uncertain(verdict):
    output = json.dumps({"claims": [{"id": "c001", "verdict": verdict, "reason": "x"}]})
    result = verify_entailment(
        [Claim("c001", "品牌需要让内容进入 AI 的回答。", [1])],
        SOURCES,
        FakeVerifierLLM(output),
    )

    assert not result.passed
    assert not result.malformed
    assert result.verdicts == {"c001": verdict}
    assert result.issues


def test_verifier_accepts_supported_json_with_fence():
    output = '```json\n{"claims": [{"id": "c001", "verdict": "supported", "reason": "来源原句"}]}\n```'
    llm = FakeVerifierLLM(output)
    result = verify_entailment(
        [Claim("c001", "品牌需要让内容进入 AI 的回答。", [1])],
        SOURCES,
        llm,
    )

    assert result.passed
    assert not result.malformed
    assert result.verdicts == {"c001": "supported"}
    assert llm.calls[0]["temperature"] == 0.0
    assert "<SOURCES>" not in llm.calls[0]["messages"][0]["content"]  # sources go in the user JSON
