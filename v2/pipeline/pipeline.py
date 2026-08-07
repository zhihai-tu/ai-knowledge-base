"""四步知识库自动化流水线：采集 → 分析 → 整理 → 保存。

Step 1 采集（Collect）：从 GitHub Search API 和 RSS 源采集 AI 相关内容。
Step 2 分析（Analyze）：调用 LLM 对每条内容进行摘要 / 评分 / 标签分析。
Step 3 整理（Organize）：去重 + 格式标准化 + 校验。
Step 4 保存（Save）：将文章保存为独立 JSON 文件到 knowledge/articles/。

用法示例::

    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from model_client import create_provider, chat_with_retry, load_dotenv, LLMProvider

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

GITHUB_API = "https://api.github.com/search/repositories"
GITHUB_QUERY = "AI OR LLM OR agent"
RSS_SOURCES_YAML = PROJECT_ROOT / "pipeline" / "rss_sources.yaml"

VALID_SOURCES = {"github", "rss"}
DEFAULT_SOURCES = ["github", "rss"]
DEFAULT_LIMIT = 20
VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_CATEGORIES = {"llm", "agent", "rag", "inference", "training", "tool"}

ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+$")
ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.S)
TAG_RE = re.compile(r"<(\w+)[^>]*>(.*?)</\1>", re.S)
CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MIN_SUMMARY_LEN = 20


# ── Step 1: 采集 ──────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_seq(prefix: str, date_str: str) -> int:
    """返回该前缀 + 日期下已存在文件的最大序号 + 1，避免重跑覆盖。"""
    max_seq = 0
    pattern = re.compile(rf"^{prefix}-{date_str}-(\d{{3}})\.json$")
    if ARTICLES_DIR.exists():
        for f in ARTICLES_DIR.iterdir():
            m = pattern.match(f.name)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def _make_item(source_type: str, seq: int, title: str, source_url: str,
               description: str, metadata: dict[str, Any]) -> dict[str, Any]:
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = "github" if source_type == "github" else "rss"
    return {
        "id": f"{prefix}-{date_str}-{seq:03d}",
        "title": title.strip(),
        "source_url": source_url.strip(),
        "source_type": source_type,
        "summary": description.strip(),
        "tags": [],
        "category": None,
        "status": "draft",
        "collected_at": _now_iso(),
        "analyzed_at": None,
        "published_at": None,
        "distribution": {"telegram": False, "feishu": False},
        "metadata": metadata,
    }


def collect_github(limit: int) -> list[dict[str, Any]]:
    """通过 GitHub Search API 采集 AI 相关仓库。"""
    params = {"q": GITHUB_QUERY, "sort": "stars", "order": "desc", "per_page": limit}
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "ai-knowledge-base-pipeline"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(GITHUB_API, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    items: list[dict[str, Any]] = []
    seq = _next_seq("github", datetime.now(timezone.utc).strftime("%Y%m%d"))
    for repo in data.get("items", []):
        meta = {
            "stars": repo.get("stargazers_count"),
            "language": repo.get("language"),
            "author": (repo.get("owner") or {}).get("login"),
            "topics": repo.get("topics") or [],
            "score": None,
            "score_reason": None,
        }
        items.append(_make_item(
            source_type="github", seq=seq,
            title=repo.get("full_name") or repo.get("name") or "",
            source_url=repo.get("html_url") or "",
            description=repo.get("description") or "",
            metadata=meta,
        ))
        seq += 1
    logger.info("GitHub 采集完成: %d 条", len(items))
    return items


def _clean_text(value: str) -> str:
    """去除 CDATA 包装与 HTML 标签，压缩空白。"""
    text = CDATA_RE.sub(r"\1", value)
    text = HTML_TAG_RE.sub(" ", text)
    return " ".join(text.split())


def load_rss_sources() -> list[dict[str, Any]]:
    """从 rss_sources.yaml 加载已启用的 RSS 源。"""
    if not RSS_SOURCES_YAML.exists():
        logger.warning("RSS 配置文件不存在: %s", RSS_SOURCES_YAML)
        return []
    with RSS_SOURCES_YAML.open("r", encoding="utf-8") as f:
        sources = yaml.safe_load(f) or []
    enabled = [s for s in sources if s.get("enabled")]
    logger.info("RSS 源加载完成: %d 个已启用 / %d 个总计", len(enabled), len(sources))
    return enabled

def _fetch_single_rss(client: httpx.Client, url: str, source_name: str,
                       limit: int, seq: int) -> list[dict[str, Any]]:
    """采集单个 RSS 源，返回条目列表。支持 RSS 和 Atom 格式。"""
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    text = resp.text

    items: list[dict[str, Any]] = []
    # 尝试 RSS 格式 (<item>)，失败则尝试 Atom 格式 (<entry>)
    matches = ITEM_RE.findall(text)
    if not matches:
        matches = ENTRY_RE.findall(text)

    for match in matches:
        fields = {key: value.strip() for key, value in TAG_RE.findall(match)}
        title = _clean_text(fields.get("title", ""))
        # Atom 格式链接在 <link href="..."/> 中，正则无法匹配，尝试从 <id> 或 <link> 提取
        link = _clean_text(fields.get("link", ""))
        if not link:
            # 尝试从 <link> 属性中提取
            link_match = re.search(r'<link[^>]+href="([^"]+)"', match)
            if link_match:
                link = link_match.group(1)
        description = _clean_text(fields.get("description", "") or fields.get("content", ""))
        if not title or not link:
            continue
        items.append(_make_item(
            source_type="rss", seq=seq,
            title=title,
            source_url=link,
            description=description,
            metadata={"published": fields.get("pubDate") or fields.get("published"),
                      "source_name": source_name,
                      "highlights": [], "score": None, "score_reason": None},
        ))
        seq += 1
        if len(items) >= limit:
            break
    return items


def collect_rss(limit: int) -> list[dict[str, Any]]:
    """在已启用的 RSS 源间轮流均分采集，总量不超过 limit。"""
    sources = load_rss_sources()
    if not sources:
        logger.warning("无可用 RSS 源，跳过采集")
        return []

    n = len(sources)
    per_source, extra = divmod(limit, n)
    if per_source == 0:
        per_source, extra = 1, 0

    items: list[dict[str, Any]] = []
    seq = _next_seq("rss", datetime.now(timezone.utc).strftime("%Y%m%d"))
    with httpx.Client(timeout=30.0, transport=httpx.HTTPTransport(proxy=None)) as client:
        for idx, source in enumerate(sources):
            if len(items) >= limit:
                break
            if per_source == 1 and idx >= limit:
                break
            quota = per_source + (1 if idx < extra else 0)
            name = source.get("name", "unknown")
            url = source.get("url", "")
            try:
                logger.info("采集 RSS 源: %s（配额 %d）", name, quota)
                new_items = _fetch_single_rss(client, url, name, quota, seq)
                items.extend(new_items)
                seq += len(new_items)
                logger.info("  %s: 采集 %d 条", name, len(new_items))
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning("  %s: 采集失败 - %s", name, exc)
    logger.info("RSS 采集完成: %d 条（来自 %d 个源）", len(items), len(sources))
    return items


# ── Step 2: 分析 ──────────────────────────────────────────────────

ANALYZE_SYSTEM = (
    "你是 AI 技术情报分析员。只输出一个 JSON 对象，不要任何额外文字。"
    '字段: {"summary": "150-300字中文摘要", "tags": ["1-3个英文标签"], '
    '"category": "llm|agent|rag|inference|training|tool", '
    '"score": 1到10的整数, "score_reason": "一句话评分理由"}'
)


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出中稳健提取 JSON 对象（容忍 ``` 代码围栏等噪声）。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def analyze_item(provider: LLMProvider, item: dict[str, Any]) -> dict[str, Any]:
    """调用 LLM 生成摘要 / 标签 / 分类 / 评分，失败时返回未分析条目。"""
    user_prompt = (
        f"请分析以下 AI 相关内容并输出 JSON：\n\n"
        f"标题: {item.get('title')}\n"
        f"链接: {item.get('source_url')}\n"
        f"原始描述: {item.get('summary') or '（无）'}"
    )
    try:
        resp = chat_with_retry(
            provider,
            [{"role": "system", "content": ANALYZE_SYSTEM},
             {"role": "user", "content": user_prompt}],
            temperature=0.3,
        )
        analysis = _extract_json(resp.content)
    except Exception as exc:
        logger.warning("条目 %s 分析失败: %s", item.get("id"), exc)
        return item

    item["summary"] = str(analysis.get("summary") or item.get("summary") or "").strip()
    tags = analysis.get("tags") or []
    item["tags"] = [str(t) for t in tags if str(t).strip()]
    category = analysis.get("category")
    item["category"] = category if category in VALID_CATEGORIES else None
    score = analysis.get("score")
    if isinstance(score, (int, float)):
        item["metadata"]["score"] = max(1, min(10, int(score)))
    item["metadata"]["score_reason"] = str(analysis.get("score_reason") or "").strip()
    item["analyzed_at"] = _now_iso()
    item["status"] = "review"
    return item


# ── Step 3: 整理 ──────────────────────────────────────────────────

def organize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去重 + 格式标准化。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        url = item.get("source_url", "")
        if url in seen:
            logger.debug("去重丢弃: %s", url)
            continue
        seen.add(url)
        result.append(_normalize(item))
    logger.info("整理完成: %d 条（去重 %d 条）", len(result), len(items) - len(result))
    return result


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    item["title"] = " ".join(str(item.get("title", "")).split())
    item["summary"] = " ".join(str(item.get("summary", "")).split())
    item["tags"] = list(dict.fromkeys(str(t) for t in item.get("tags") or []))
    if item.get("status") not in VALID_STATUSES:
        item["status"] = "review"
    return item


def validate_item(item: dict[str, Any]) -> list[str]:
    """校验条目是否符合 hooks/validate_json.py 的规范，返回错误列表。"""
    errors: list[str] = []
    if not isinstance(item.get("id"), str) or not ID_PATTERN.match(item["id"]):
        errors.append(f"id 格式错误: {item.get('id')}")
    if not isinstance(item.get("title"), str) or not item["title"]:
        errors.append("title 缺失或为空")
    url = item.get("source_url")
    if not isinstance(url, str) or not URL_PATTERN.match(url):
        errors.append(f"source_url 格式无效: {url}")
    summary = item.get("summary")
    if not isinstance(summary, str) or len(summary) < MIN_SUMMARY_LEN:
        errors.append(f"summary 过短（当前 {len(summary or '')} 字，最少 {MIN_SUMMARY_LEN} 字）")
    tags = item.get("tags")
    if not isinstance(tags, list) or len(tags) < 1:
        errors.append("tags 至少需要 1 个")
    status = item.get("status")
    if status not in VALID_STATUSES:
        errors.append(f"status 无效值: {status}")
    score = item.get("metadata", {}).get("score")
    if score is not None and not (1 <= score <= 10):
        errors.append(f"score 超出 1-10 范围: {score}")
    return errors


# ── Step 4: 保存 ──────────────────────────────────────────────────

def save_raw(raw_dir: Path, items: list[dict[str, Any]], source_type: str) -> int:
    """将采集结果批量写入 knowledge/raw/，返回写入条数。"""
    raw_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = raw_dir / f"{source_type}-{date_str}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    logger.info("原始数据已保存: %s (%d 条)", path, len(items))
    return len(items)


def save_articles(items: list[dict[str, Any]], dry_run: bool) -> int:
    """将整理后的文章逐个保存为独立 JSON 文件到 knowledge/articles/。"""
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for item in items:
        errors = validate_item(item)
        if errors:
            logger.warning("条目 %s 未通过校验，跳过: %s", item.get("id"), "; ".join(errors))
            continue
        path = ARTICLES_DIR / f"{item['id']}.json"
        if dry_run:
            logger.info("[dry-run] 将写入 %s", path)
        else:
            with path.open("w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=2)
            logger.info("已保存文章: %s", path)
        saved += 1
    return saved


# ── 主流程 ────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="四步知识库自动化流水线：采集 → 分析 → 整理 → 保存")
    parser.add_argument(
        "--sources", type=str, default=",".join(DEFAULT_SOURCES),
        help=f"采集源，逗号分隔，可选: {', '.join(sorted(VALID_SOURCES))}"
             f"（默认: {','.join(DEFAULT_SOURCES)}）")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"每个采集源最多采集条数（默认: {DEFAULT_LIMIT}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="干跑模式：执行流水线但不写入任何文件")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    load_dotenv()
    env_level = os.getenv("LOG_LEVEL", "").strip().upper()
    if args.verbose:
        level = logging.DEBUG
    elif env_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        level = getattr(logging, env_level)
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    invalid = [s for s in sources if s not in VALID_SOURCES]
    if invalid:
        logger.error("不支持的采集源: %s（可选: %s）",
                     ", ".join(invalid), ", ".join(sorted(VALID_SOURCES)))
        sys.exit(1)

    # Step 1: 采集（每个源各采集 limit 条，RSS 内部子源累计不超 limit）
    collected: list[dict[str, Any]] = []
    for source in sources:
        try:
            if source == "github":
                collected.extend(collect_github(args.limit))
            else:
                collected.extend(collect_rss(args.limit))
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.error("采集源 %s 失败: %s", source, exc)
    if not collected:
        logger.error("未采集到任何条目，流水线中止。")
        sys.exit(1)

    if not args.dry_run:
        for source in sources:
            subset = [i for i in collected if i["source_type"] == source]
            if subset:
                save_raw(RAW_DIR, subset, source)

    # Step 2: 分析
    try:
        provider = create_provider()
        analyzed = [analyze_item(provider, item) for item in collected]
    except RuntimeError as exc:
        logger.warning("未配置 API Key，跳过分析步骤: %s", exc)
        analyzed = collected

    # Step 3: 整理
    organized = organize(analyzed)

    # Step 4: 保存
    saved = save_articles(organized, args.dry_run)

    logger.info("流水线完成: 采集 %d 条，分析 %d 条，整理 %d 条，保存 %d 条",
                len(collected), len(analyzed), len(organized), saved)


if __name__ == "__main__":
    main()
