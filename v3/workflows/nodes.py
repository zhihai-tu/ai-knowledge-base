"""LangGraph 工作流的 5 个节点函数。

流水线: collect → analyze → organize → review → save

每个节点是纯函数: 接收 :class:`workflows.state.KBState`，返回 dict
（部分状态更新，LangGraph 以覆盖方式合并回共享状态）。

审核重做循环: 审核不通过且 ``iteration < MAX_ITERATIONS`` 时，带反馈回到
organize 重做；``iteration >= FORCE_PASS_ITERATION`` 时强制通过，避免死循环。

用法示例::

    from workflows.nodes import collect_node, analyze_node

    updates = collect_node(state)
"""

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from patterns.router import rebuild_index
from workflows.model_client import (
    Usage,
    accumulate_usage,
    chat_with_retry,
    create_provider,
)
from workflows.state import KBState

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/search/repositories"
GITHUB_QUERY = "AI OR LLM OR agent"
COLLECT_LIMIT = 10
# 相邻两条 LLM 分析请求的间隔（秒）：平滑请求速率，规避服务端
# 突发速率限流（如商汤 SenseNova 对 glm-5.2 的 BurstRate 429）。
# 对限流更严的服务可调大该值。
ANALYZE_INTERVAL_SECONDS = 2.0

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

# 评分体系：analyze / review 均使用 1-10 分值，与现有 knowledge/articles
# 的 metadata.score 及 index.json 保持一致。
MIN_ACCEPT_SCORE = 6       # organize 过滤线：低于该分值的条目丢弃
PASS_REVIEW_SCORE = 7      # review 通过线：overall_score >= 该值才通过
FORCE_PASS_ITERATION = 2   # iteration >= 2 强制通过（配合 MAX_ITERATIONS=3）

VALID_CATEGORIES = {"llm", "agent", "rag", "inference", "training", "tool"}
ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+$")

ANALYZE_SYSTEM = (
    "你是 AI 技术情报分析员。针对给定的 GitHub AI 项目，只输出一个 JSON 对象：\n"
    '{"summary": "150-300字中文摘要，准确反映项目核心价值与亮点", '
    '"tags": ["1-3个英文标签"], '
    '"category": "llm|agent|rag|inference|training|tool", '
    '"score": 1到10之间的整数（项目价值，越高越好，如8）, '
    '"score_reason": "一句话评分理由"}'
    "只输出 JSON，不要任何额外文字。"
)

REVISE_SYSTEM = (
    "你是知识库整理员。根据审核反馈修正给定的知识条目 JSON 数组。\n"
    "要求：保留全部条目与每个条目的 id / source_url 不变，只修改内容"
    "（summary / tags / category / metadata.score 等），结构与字段名不变。\n"
    "只输出修正后的完整 JSON 数组，不要任何额外文字。"
)

REVIEW_SYSTEM = (
    "你是知识库质量审核员。请从以下四个维度评审给定的知识条目，每项 1-10 分：\n"
    "1. summary_quality 摘要质量：准确、清晰、完整（150-300字）；\n"
    "2. tag_accuracy 标签准确性：标签贴切、数量得当；\n"
    "3. category_reasonableness 分类合理性：分类属于 llm|agent|rag|"
    "inference|training|tool；\n"
    "4. consistency 一致性：条目字段自洽（评分与摘要相符等）。\n"
    "overall_score = 四个维度平均分。\n"
    "只输出一个 JSON 对象，不要任何额外文字：\n"
    '{"passed": true或false, "overall_score": 1到10之间的数, '
    '"feedback": "具体改进建议(中文)", '
    '"scores": {"summary_quality": 8, "tag_accuracy": 7, '
    '"category_reasonableness": 9, "consistency": 8}}'
)

_provider = None


def _get_provider():
    """懒加载全局 LLM Provider 单例。"""
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


def _llm_chat(system: str, user: str, temperature: float = 0.0) -> str:
    """调用 LLM 返回文本内容，复用 model_client 的用量追踪与重试。"""
    response = chat_with_retry(
        _get_provider(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return response.content


def _parse_json(text: str) -> tuple[object | None, str | None]:
    """解析模型输出的 JSON，容忍代码块标记与前后噪声，返回 (对象, 错误信息)。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if -1 < start < end:
        try:
            return json.loads(text[start : end + 1]), None
        except json.JSONDecodeError as exc:
            return None, str(exc)
    return None, "未找到 JSON 对象"


def _to_float(value, default: float | None = None) -> float | None:
    """把任意值稳健转换为 float，失败返回 default（bool 视为非法）。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


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


# ── collect_node: 调用 GitHub Search API 采集 ──────────────────────

def _fetch_github_search() -> dict:
    """请求 GitHub Search API，返回 JSON 数据。

    先按系统配置经代理请求；连接级失败（TLS/超时）时回退直连，
    直连的瞬时失败最多重试 2 次（0.5s/1s 退避）。每次尝试必须新建
    Request，避免 ProxyHandler 缓存 proxy_host 导致直连仍走代理。
    """
    query = urllib.parse.urlencode(
        {"q": GITHUB_QUERY, "sort": "stars", "order": "desc",
         "per_page": COLLECT_LIMIT}
    )
    url = f"{GITHUB_API}?{query}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-knowledge-base-workflow",
    }
    direct_opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as exc:
        logger.warning("GitHub 采集经代理连接失败，回退直连: %s", exc)

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with direct_opener.open(req, timeout=15) as resp:
                return json.load(resp)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise last_error  # type: ignore[misc]


def _collect_github() -> list[dict]:
    """把 GitHub Search API 返回的仓库整理为 sources 报告列表。"""
    data = _fetch_github_search()
    sources = []
    collected_at = _now_iso()
    for repo in data.get("items", []):
        owner = (repo.get("owner") or {}).get("login", "")
        full_name = repo.get("full_name") or repo.get("name") or ""
        sources.append(
            {
                "source_type": "github",
                "title": full_name,
                "source_url": repo.get("html_url")
                or f"https://github.com/{full_name}",
                "summary": (repo.get("description") or "").strip(),
                "collected_at": collected_at,
                "stars": repo.get("stargazers_count"),
                "language": repo.get("language"),
                "author": owner,
                "topics": repo.get("topics") or [],
            }
        )
    return sources


def collect_node(state: KBState) -> dict:
    """节点 1：调用 GitHub Search API 采集 AI 相关仓库，更新 sources。"""
    print(f"[CollectNode] 调用 GitHub Search API 采集「{GITHUB_QUERY}」相关仓库...")
    try:
        sources = _collect_github()
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub 采集失败: %s", exc)
        print(f"[CollectNode] 采集失败: {exc}")
        sources = []
    print(f"[CollectNode] 采集完成: {len(sources)} 条")
    for s in sources:
        stars = s.get("stars")
        suffix = f" (⭐{stars})" if stars else ""
        print(f"  └ {s.get('title')}{suffix}")
    return {"sources": sources}


# ── analyze_node: LLM 生成中文摘要 / 标签 / 评分 ───────────────────

def _analyze_one(source: dict) -> tuple[dict | None, Usage | None]:
    """对单条 source 调用 LLM 生成分析报告；失败时降级为 (None, usage)。

    返回 (分析报告 dict, 本次调用 Usage)；Usage 用于累计到 state 成本，
    解析失败但已消耗 tokens 时 usage 依然有效。
    """
    user = (
        "请分析以下 GitHub AI 项目并输出 JSON：\n\n"
        f"标题: {source.get('title')}\n"
        f"链接: {source.get('source_url')}\n"
        f"Stars: {source.get('stars')}\n"
        f"语言: {source.get('language')}\n"
        f"Topics: {', '.join(str(t) for t in (source.get('topics') or []))}\n"
        f"原始描述: {source.get('summary') or '（无）'}"
    )
    try:
        response = chat_with_retry(
            _get_provider(),
            [
                {"role": "system", "content": ANALYZE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("条目 %s 分析调用失败: %s", source.get("source_url"), exc)
        return None, None
    usage = response.usage
    raw = response.content

    parsed, err = _parse_json(raw)
    if not isinstance(parsed, dict):
        logger.warning("条目 %s 分析输出非法 JSON: %s",
                       source.get("source_url"), err or "非对象")
        return None, usage

    raw_score = parsed.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        score = 0
    else:
        score = max(1, min(10, int(raw_score)))
    category = parsed.get("category")
    return {
        "source_id": source.get("source_url"),
        "title": source.get("title", ""),
        "source_url": source.get("source_url", ""),
        "source_type": source.get("source_type", "github"),
        "collected_at": source.get("collected_at"),
        "stars": source.get("stars"),
        "language": source.get("language"),
        "author": source.get("author"),
        "topics": source.get("topics") or [],
        "summary": str(parsed.get("summary") or source.get("summary") or "").strip(),
        "tags": [str(t) for t in (parsed.get("tags") or []) if str(t).strip()],
        "category": category if category in VALID_CATEGORIES else None,
        "score": score,
        "score_reason": str(parsed.get("score_reason") or "").strip(),
        "analyzed_at": _now_iso(),
    }, usage


def analyze_node(state: KBState) -> dict:
    """节点 2：用 LLM 对每条 source 生成中文摘要、标签、评分，更新 analyses。

    逐条调用并实时打印进度（glm 等推理模型单次响应可能耗时数十秒，
    避免看起来像卡死）。相邻请求间隔 ANALYZE_INTERVAL_SECONDS 平滑速率。
    每次调用的 token 用量累计进 ``state.cost_tracker``。
    """
    sources = state.get("sources") or []
    cost_tracker = state.get("cost_tracker") or {}
    print(f"[AnalyzeNode] 对 {len(sources)} 条数据调用 LLM 分析...")
    analyses = []
    for i, source in enumerate(sources):
        if i > 0:
            time.sleep(ANALYZE_INTERVAL_SECONDS)
        title = source.get("title") or source.get("source_url")
        print(f"[AnalyzeNode] 分析 {i + 1}/{len(sources)}: {title} ...", flush=True)
        analysis, usage = _analyze_one(source)
        if usage is not None:
            cost_tracker = accumulate_usage(cost_tracker, usage, _get_provider())
        if analysis is None:
            print(f"  └ 失败（限流/解析错误），已跳过")
            continue
        analyses.append(analysis)
        print(f"  └ score={analysis['score']}", flush=True)
        logger.info("分析完成: %s score=%s", analysis["source_url"], analysis["score"])
    print(f"[AnalyzeNode] 分析完成: {len(analyses)}/{len(sources)} 条")
    return {"analyses": analyses, "cost_tracker": cost_tracker}


# ── organize_node: 过滤低分 + 去重 + 按反馈修正 ────────────────────

def _make_article(a: dict, seq: int) -> dict:
    """把一条分析报告格式化为完整知识条目（metadata.score 沿用 1-10 分值）。"""
    prefix = "github" if a.get("source_type") == "github" else "rss"
    return {
        "id": f"{prefix}-{_today_str()}-{seq:03d}",
        "title": a.get("title", ""),
        "source_url": a.get("source_url", ""),
        "source_type": a.get("source_type", "github"),
        "summary": a.get("summary", ""),
        "tags": a.get("tags") or [],
        "category": a.get("category"),
        "status": "review",
        "collected_at": a.get("collected_at"),
        "analyzed_at": a.get("analyzed_at"),
        "published_at": None,
        "distribution": {"telegram": False, "feishu": False},
        "metadata": {
            "stars": a.get("stars"),
            "language": a.get("language"),
            "author": a.get("author"),
            "topics": a.get("topics") or [],
            "score": a.get("score"),
            "score_reason": a.get("score_reason") or "",
        },
    }


def _load_existing_urls() -> set[str]:
    """返回 knowledge/articles/ 下已收录文章的 source_url 集合（跨批次去重用）。"""
    urls: set[str] = set()
    if not ARTICLES_DIR.is_dir():
        return urls
    for path in ARTICLES_DIR.glob("*.json"):
        if path.name in ("index.json",) or path.name.startswith("test-"):
            continue
        try:
            a = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        url = a.get("source_url")
        if isinstance(url, str) and url:
            urls.add(url)
    return urls


def _build_articles(analyses: list[dict]) -> list[dict]:
    """从分析报告构建文章列表：过滤低分（< MIN_ACCEPT_SCORE）+ 按 URL 去重。

    去重范围覆盖当前批次内 + 历史已收录（跨批次），避免热门仓库重复入库。
    """
    seen_urls: set[str] = _load_existing_urls()
    seq = _next_seq("github", _today_str())
    articles = []
    for a in analyses:
        score = _to_float(a.get("score"))
        if score is not None and score < MIN_ACCEPT_SCORE:
            logger.info("过滤低分条目: %s score=%s", a.get("source_url"), score)
            continue
        url = a.get("source_url")
        if not url or url in seen_urls:
            logger.info("按 URL 去重丢弃: %s", url)
            continue
        seen_urls.add(url)
        articles.append(_make_article(a, seq))
        seq += 1
    return articles


def _revise_articles(articles: list[dict], feedback: str) -> list[dict]:
    """根据审核反馈调用 LLM 定向修正文章列表。

    要求 LLM 保留全部条目与 id；按原列表顺序重建，未返回的条目沿用原内容。
    """
    user = (
        "以下是知识库待审核条目 JSON 数组：\n"
        f"{json.dumps(articles, ensure_ascii=False, indent=2)}\n\n"
        f"审核反馈：\n{feedback}\n\n"
        "请根据反馈逐条修正，输出修正后的完整 JSON 数组。"
    )
    try:
        raw = _llm_chat(REVISE_SYSTEM, user, temperature=0.3)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OrganizeNode 修正调用失败，保留原条目: %s", exc)
        return articles

    parsed, err = _parse_json(raw)
    revised = {}
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and item.get("id"):
                revised[item["id"]] = item
    if not revised:
        logger.warning("OrganizeNode 修正输出非法，保留原条目: %s",
                       err or "非数组或缺少 id")
        return articles

    result = []
    for a in articles:
        item = revised.get(a.get("id"))
        if item is None:
            result.append(a)
            continue
        merged = {**a, **item}
        merged["id"] = a["id"]
        merged["source_url"] = a["source_url"]
        result.append(merged)
    return result


def organize_node(state: KBState) -> dict:
    """节点 3：过滤低分、按 URL 去重；有审核反馈时调用 LLM 定向修正。

    首轮（iteration==0 或无反馈）从 analyses 整体重建 articles；
    重做轮（iteration>0 且 review_feedback 非空）对现有 articles 修正后整体写回。
    """
    iteration = state.get("iteration", 0)
    feedback = (state.get("review_feedback") or "").strip()
    current = state.get("articles") or []
    print(f"[OrganizeNode] iteration={iteration}")

    if iteration > 0 and feedback and current:
        print("[OrganizeNode] 根据审核反馈调用 LLM 定向修正...")
        articles = _revise_articles(current, feedback)
    else:
        existing = len(_load_existing_urls())
        print(f"[OrganizeNode] 过滤低分(<{MIN_ACCEPT_SCORE}) + 按 URL 去重"
              f"（含 {existing} 条历史已收录）...")
        articles = _build_articles(state.get("analyses") or [])
    print(f"[OrganizeNode] 整理完成: {len(articles)} 条")
    return {"articles": articles}


# ── review_node: LLM 四维度审核 ────────────────────────────────────

def _review_articles(articles: list[dict]) -> dict:
    """调用 LLM 做四维度审核，返回 {"passed", "overall_score", "feedback"}。

    passed 以 overall_score >= PASS_REVIEW_SCORE 为准，与 LLM 输出保持一致。
    """
    if not articles:
        return {"passed": True, "overall_score": 0.0, "feedback": "无条目待审核。"}
    user = (
        "请审核以下知识条目：\n"
        f"{json.dumps(articles, ensure_ascii=False, indent=2)}"
    )
    try:
        raw = _llm_chat(REVIEW_SYSTEM, user, temperature=0.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ReviewNode 审核调用失败: %s", exc)
        return {"passed": False, "overall_score": 0.0,
                "feedback": f"审核调用失败: {exc}"}

    parsed, err = _parse_json(raw)
    if not isinstance(parsed, dict):
        return {"passed": False, "overall_score": 0.0,
                "feedback": f"审核输出非法 JSON: {err or '非对象'}"}

    overall = _to_float(parsed.get("overall_score"), default=0.0)
    overall = max(1.0, min(10.0, overall))
    feedback = str(parsed.get("feedback") or "").strip() or "无反馈"
    return {"passed": overall >= PASS_REVIEW_SCORE, "overall_score": overall,
            "feedback": feedback}


def review_node(state: KBState) -> dict:
    """节点 4：LLM 四维度评分；iteration >= FORCE_PASS_ITERATION 时强制通过。

    未通过时 iteration 递增，供重做循环使用；通过或强制通过时保持当前值。
    """
    iteration = state.get("iteration", 0)
    articles = state.get("articles") or []
    print(f"[ReviewNode] 四维度审核（iteration={iteration}, {len(articles)} 条）...")

    if iteration >= FORCE_PASS_ITERATION:
        print("[ReviewNode] 已达最大审核轮次，强制通过。")
        return {
            "review_passed": True,
            "review_feedback": "已达最大审核轮次，强制通过。",
            "iteration": iteration,
        }

    result = _review_articles(articles)
    print(
        f"[ReviewNode] overall_score={result['overall_score']:.3f} "
        f"passed={result['passed']}"
    )
    return {
        "review_passed": result["passed"],
        "review_feedback": result["feedback"],
        "iteration": iteration if result["passed"] else iteration + 1,
    }


def review_node_test(state: KBState) -> dict:
    """临时测试版节点 4：模拟审核循环（验证后会删除）。

    前 2 次强制返回 review_passed: False；iteration >= 2（第 3 次）返回 True。
    每次给出不同 feedback，并打印当前 iteration 与 review_passed。
    """
    iteration = state.get("iteration", 0)
    if iteration < 2:
        passed = False
        feedback = ["摘要过于简短", "标签不够精准"][iteration]
    else:
        passed = True
        feedback = "整体质量合格，审核通过。"
    print(f"[ReviewNode] iteration={iteration}, review_passed={passed}")
    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration if passed else iteration + 1,
    }


# ── save_node: 写入 articles 目录并更新 index.json ─────────────────

def _validate_article(item: dict) -> list[str]:
    """保存前的基础校验（与 hooks/validate_json.py 规范一致）。"""
    errors: list[str] = []
    if not isinstance(item.get("id"), str) or not ID_PATTERN.match(item["id"]):
        errors.append(f"id 格式错误: {item.get('id')}")
    if not isinstance(item.get("title"), str) or not item["title"]:
        errors.append("title 缺失或为空")
    url = item.get("source_url")
    if not isinstance(url, str) or not URL_PATTERN.match(url):
        errors.append(f"source_url 格式无效: {url}")
    summary = item.get("summary")
    if not isinstance(summary, str) or len(summary) < 20:
        errors.append(f"summary 过短（当前 {len(summary or '')} 字，最少 20 字）")
    return errors


def _save_articles(articles: list[dict]) -> int:
    """把文章逐个写入 knowledge/articles/{id}.json，未通过校验的跳过。"""
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for item in articles:
        errors = _validate_article(item)
        if errors:
            logger.warning("条目 %s 未通过校验，跳过: %s",
                           item.get("id"), "; ".join(errors))
            continue
        path = ARTICLES_DIR / f"{item['id']}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        saved += 1
        logger.info("已保存文章: %s", path)
    return saved


def save_node(state: KBState) -> dict:
    """节点 5：将 articles 写入 knowledge/articles/，并重建 index.json 索引。"""
    articles = state.get("articles") or []
    print(f"[SaveNode] 写入 {len(articles)} 篇文章到 knowledge/articles/ ...")
    saved = _save_articles(articles)
    rebuild_index()
    print(f"[SaveNode] 已保存 {saved} 篇，并更新 index.json")
    return {}
