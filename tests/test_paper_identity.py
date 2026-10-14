"""论文标识归一化：DOI / arXiv ID / 标题指纹。"""

from __future__ import annotations

from app.services.paper_identity import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_title,
    title_fingerprint,
)


def test_normalize_doi_strips_prefix_and_lowercases():
    assert normalize_doi("https://doi.org/10.1145/ABC.123") == "10.1145/abc.123"
    assert normalize_doi("DOI:10.1000/XYZ") == "10.1000/xyz"
    assert normalize_doi("10.1000/abc ") == "10.1000/abc"
    assert normalize_doi("") == ""
    assert normalize_doi(None) == ""


def test_normalize_arxiv_id_removes_url_and_version():
    assert normalize_arxiv_id("2401.12345v2") == "2401.12345"
    assert normalize_arxiv_id("http://arxiv.org/abs/2401.12345v1") == "2401.12345"
    assert normalize_arxiv_id("arXiv:2401.12345") == "2401.12345"
    assert normalize_arxiv_id("") == ""


def test_normalize_arxiv_id_rejects_non_arxiv_values():
    """DOI 或 OpenAlex ID 不能被当成 arXiv ID，否则会被错误归类。"""
    assert normalize_arxiv_id("10.1000/xyz") == ""
    assert normalize_arxiv_id("W2741809807") == ""
    assert normalize_arxiv_id("math.GT/0309136") == "math.GT/0309136"


def test_normalize_title_ignores_case_punctuation_and_spacing():
    first = normalize_title("Low-Rank Adaptation,  of Large Language Models!")
    second = normalize_title("low rank adaptation of large language models")
    assert first == second


def test_title_fingerprint_is_stable_and_author_year_sensitive():
    base = title_fingerprint("Low-Rank Adaptation", ["Hu, E."], 2021)
    same = title_fingerprint("low-rank adaptation.", ["Hu, E."], 2021)
    other_author = title_fingerprint("Low-Rank Adaptation", ["Zhang, L."], 2021)
    other_year = title_fingerprint("Low-Rank Adaptation", ["Hu, E."], 2022)

    assert base == same
    assert base != other_author
    assert base != other_year
    assert len(base) == 40
