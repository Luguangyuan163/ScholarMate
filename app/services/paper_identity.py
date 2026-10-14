"""论文标识归一化：DOI、arXiv ID、标题指纹。

跨来源去重依赖同一套归一规则：只有把各来源写法不同的标识收敛成同一个值，
才能判断两条记录是不是同一篇论文。
"""

from __future__ import annotations

import hashlib
import re

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
DOI_PREFIX_PATTERN = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
ARXIV_ID_PATTERN = re.compile(
    r"(\d{4}\.\d{4,5})(v\d+)?"          # 新式：2401.12345v2
    r"|([a-z-]+(?:\.[A-Za-z]{2})?/\d{7})"  # 旧式：math.GT/0309136
)


def normalize_doi(raw: str | None) -> str:
    """去掉 DOI 前缀、统一小写；不是 DOI 形态时返回空串。"""
    if not raw:
        return ""
    value = DOI_PREFIX_PATTERN.sub("", str(raw).strip()).strip().lower()
    return value if DOI_PATTERN.match(value) else ""


def normalize_arxiv_id(raw: str | None) -> str:
    """从 URL 或带版本号的写法里取出主版本 arXiv ID；不是 arXiv 形态时返回空串。"""
    if not raw:
        return ""
    match = ARXIV_ID_PATTERN.search(str(raw).strip())
    if match is None:
        return ""
    return match.group(1) or match.group(3) or ""


def normalize_title(title: str | None) -> str:
    """标题归一：小写、去标点、压缩空白。中文标题保留原字符。"""
    if not title:
        return ""
    lowered = str(title).lower()
    stripped = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def title_fingerprint(
    title: str | None,
    authors: list[str] | None = None,
    year: int | None = None,
) -> str:
    """标题指纹：归一化标题 + 首作者 + 年份的 SHA1，用于缺少 DOI 时去重。"""
    first_author = normalize_title(authors[0]) if authors else ""
    payload = f"{normalize_title(title)}|{first_author}|{year if year is not None else ''}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
