"""Router 路由模式：按意图分发查询到对应处理器。

两层意图分类策略：

1. 第一层：关键词快速匹配（零成本，不调 LLM）；
2. 第二层：LLM 分类兜底（处理模糊意图）。

三种意图及对应处理器：

- ``github_search``：调用 GitHub Search API 搜索仓库；
- ``knowledge_query``：检索本地知识库 ``knowledge/articles/*.json``；
- ``general_chat``：直接调用 LLM 回答。

统一入口::

    from patterns.router import route

    reply = route("github 搜索 rag 推理框架")
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from workflows.model_client import (
    calculate_cost,
    chat_with_retry,
    create_provider,
)

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/search/repositories"
ARTICLES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"
TRACE_FILE = Path(__file__).resolve().parent.parent / "logs" / "router_trace.jsonl"
LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "router.log"
SEARCH_PER_PAGE = 5

INTENT_GITHUB = "github_search"
INTENT_KNOWLEDGE = "knowledge_query"
INTENT_GENERAL = "general_chat"

# 关键词快速匹配规则：命中任一即判定意图，按顺序优先 github -> knowledge。
GITHUB_KEYWORDS = ("github", "repo")
KNOWLEDGE_KEYWORDS = (
    "知识库", "本地库", "知识库里", "笔记里", "笔记中", "收录", "库里的",
)

# 剥离前缀，提取真正的搜索关键词。
GITHUB_PREFIXES = (
    "github 搜索", "github搜索", "github 上搜索", "github上搜索",
    "在 github 上搜索", "在github上搜索", "搜索 github", "搜下 github",
    "搜下github", "搜一下 github", "搜一下github", "github 找", "github找",
    "在 github 上找", "在github上找", "github 查找", "github查找",
    "查 github", "查github", "github 上", "github上",
)
KNOWLEDGE_PREFIXES = (
    "知识库里", "知识库中", "知识库", "本地库里", "本地库",
    "笔记里", "笔记中", "搜一下", "搜一搜", "搜下", "查一下",
    "查查", "查下", "看下库", "收录",
)

_provider = None


def _get_provider():
    """懒加载全局 LLM Provider 单例。"""
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


def _llm_call(
    prompt: str, system: str | None = None, temperature: float = 0.7
) -> tuple[str, float]:
    """调用 LLM 并返回 (内容, 本次成本 USD)，复用 model_client 的用量追踪。"""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = chat_with_retry(
        _get_provider(), messages, temperature=temperature
    )
    return response.content, calculate_cost(
        response.model, response.usage.prompt_tokens, response.usage.completion_tokens
    )


def _strip_prefixes(query: str, prefixes: tuple[str, ...]) -> str:
    """从查询头部剥离已知前缀，得到真正的搜索关键词。

    只剥离一次（取首个命中），并清理残留的标点与空白。
    """
    term = query.strip()
    lowered = term.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix.lower()):
            term = term[len(prefix):].strip()
            break
    return term.lstrip(" .，,。？！!;；:：\"'“”《》<>【】").strip()


def _keyword_route(query: str) -> tuple[str | None, str | None]:
    """第一层：关键词快速匹配，返回 (意图名, 命中的关键词)，未命中返回 (None, None)。

    只处理有明确信号的查询：含 github/repo 判 GitHub 搜索，
    含知识库/笔记/收录等判本地检索。其余（含「搜/查/找/看」开头的歧义查询）
    一律交给 LLM 分类兜底，避免启发式误判。
    """
    lowered = query.lower()
    for keyword in GITHUB_KEYWORDS:
        if keyword in lowered:
            return INTENT_GITHUB, keyword
    for keyword in KNOWLEDGE_KEYWORDS:
        if keyword in lowered:
            return INTENT_KNOWLEDGE, keyword
    return None, None


def _llm_route(query: str) -> tuple[str, str | None, str | None, float, str | None]:
    """第二层：LLM 兜底分类，返回 (最终意图, LLM原始意图, 错误信息, 成本 USD, GitHub搜索词)。

    github_search 意图时，LLM 在同一次调用中额外输出英文搜索关键词；
    LLM 输出不合法时最终意图回退 general_chat，error 记录原因。
    """
    system = (
        "你是查询意图分类器。输出格式严格如下：\n"
        "github_search 意图：github_search|英文搜索关键词"
        "（关键词用英文，空格分隔，不得包含中文）\n"
        "knowledge_query 意图：直接输出 knowledge_query\n"
        "general_chat 意图：直接输出 general_chat\n"
        "只输出上述格式，不要输出其它内容。"
    )
    prompt = f"判断下面问题的意图并按要求输出：\n{query}\n\n"
    try:
        reply, cost = _llm_call(prompt, system=system, temperature=0.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 分类失败，回退 general_chat: %s", exc)
        return INTENT_GENERAL, None, str(exc), 0.0, None
    raw = reply.strip()
    intent, _, term = raw.partition("|")
    intent = intent.strip().lower()
    term = (term.strip() or None) if intent == INTENT_GITHUB else None
    return (intent if intent in HANDLERS else INTENT_GENERAL), raw, None, cost, term


def _handle_github_search(query: str, search_term: str | None = None) -> str:
    """GitHub 仓库搜索：调用 GitHub Search API。

    LLM 路由提供的 ``search_term``（英文关键词）优先使用；
    否则从查询剥离前缀提取。query 参数用 urllib.parse.quote 编码。
    """
    if search_term:
        term = search_term
    else:
        term = _strip_prefixes(query, GITHUB_PREFIXES)
        if term.lower().startswith("github"):
            rest = term[6:].strip()
            term = rest.lstrip(" .，,。？！!").strip()
    if not term:
        return (
            "请输入要搜索的 GitHub 关键词，例如：github 搜索 RAG 推理框架。",
            {"type": "github", "count": 0, "llm_cost": 0.0, "llm_calls": 0},
        )

    encoded = urllib.parse.quote(term, safe="")
    url = f"{GITHUB_API}?q={encoded}&sort=stars&order=desc&per_page={SEARCH_PER_PAGE}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-knowledge-base-router",
    }
    try:
        data, via_direct = _fetch_github(url, headers)
    except Exception as exc:  # noqa: BLE001
        return (
            f"GitHub 搜索失败: {exc}",
            {"type": "github", "count": 0, "llm_cost": 0.0, "llm_calls": 0},
        )

    items = data.get("items") or []
    if not items:
        return (
            f"GitHub 上未找到与「{term}」相关的仓库。",
            {"type": "github", "count": 0, "llm_cost": 0.0, "llm_calls": 0},
        )

    lines = [f"GitHub 搜索「{term}」结果（按 stars 排序）:"]
    for i, item in enumerate(items[:SEARCH_PER_PAGE], 1):
        full_name = item.get("full_name") or item.get("name", "?")
        stars = item.get("stargazers_count", 0)
        language = item.get("language") or "N/A"
        description = _truncate(
            (item.get("description") or "").strip() or "暂无描述", 100
        )
        lines.append(
            f"{i}. {full_name} | stars: {stars} | {language} | {description}\n"
            f"   {item.get('html_url', '')}"
        )
    return "\n".join(lines), {
        "type": "github",
        "count": len(items),
        "llm_cost": 0.0,
        "llm_calls": 0,
        "via_direct": via_direct,
    }


def _truncate(text: str, limit: int = 100) -> str:
    """截断过长文本，避免超长描述刷屏。"""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _fetch_github(url: str, headers: dict) -> tuple[dict, bool]:
    """请求 GitHub Search API，返回 (数据, 是否走直连)。

    先按环境配置经代理请求；连接级失败（TLS/超时）时回退直连，
    直连的瞬时失败最多重试 2 次（0.5s/1s 退避）。HTTP 错误
    （如 403 限流）直接抛出，不切换通道。

    注意：每次尝试必须新建 Request，复用同一个 Request 时
    ProxyHandler 会缓存 proxy_host 导致直连仍走代理。
    """
    direct_opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp), False
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as exc:
        logger.warning("GitHub 搜索经代理连接失败，回退直连: %s", exc)

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with direct_opener.open(req, timeout=15) as resp:
                return json.load(resp), True
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise last_error  # type: ignore[misc]


INDEX_FILE = ARTICLES_DIR / "index.json"


def _load_articles() -> list[dict]:
    """加载 knowledge/articles/index.json 中的文章索引。"""
    if not INDEX_FILE.is_file():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def rebuild_index() -> None:
    """扫描 knowledge/articles/ 下的文章 JSON，重新生成 index.json。"""
    if not ARTICLES_DIR.is_dir():
        return
    records = []
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        if path.name in ("index.json",) or path.name.startswith("test-"):
            continue
        try:
            a = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        records.append(
            {
                "id": a.get("id"),
                "title": a.get("title"),
                "source_type": a.get("source_type"),
                "category": a.get("category"),
                "tags": a.get("tags") or [],
                "score": a.get("metadata", {}).get("score"),
                "summary": a.get("summary"),
            }
        )
    records.sort(key=lambda r: r["score"] or 0, reverse=True)
    INDEX_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("rebuild index: %d records -> %s", len(records), INDEX_FILE)


def _article_text(article: dict) -> str:
    """拼接文章可检索文本：标题 + 摘要 + 标签。"""
    tags = article.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return " ".join(
        [str(article.get("title", "")), str(article.get("summary", ""))]
        + [str(t) for t in tags]
    ).lower()


def _build_kb_context() -> str:
    """拼接知识库全部文章的可读文本，供 LLM 兜底直读。"""
    articles = _load_articles()
    if not articles:
        return ""
    lines = []
    for i, article in enumerate(articles, 1):
        tags = "、".join(str(t) for t in (article.get("tags") or []))
        title = article.get("title", "?")
        category = article.get("category", "")
        summary = (article.get("summary") or "").strip()
        lines.append(f"{i}. [{category}] {title} (tags: {tags})\n   {summary}")
    return "\n".join(lines)


def _llm_knowledge_answer(query: str) -> tuple[str, float]:
    """关键词检索无果时的 LLM 兜底：直读知识库全文后回答，返回 (内容, 成本 USD)。"""
    context = _build_kb_context()
    if not context:
        return f"知识库中未找到与「{query}」相关的内容。", 0.0
    system = (
        "你是本地 AI 知识库的检索助手。下面给出知识库已收录的全部文章"
        "（编号、分类、标签、摘要）。请严格基于这些内容回答用户问题，"
        "只引用知识库中确实存在的信息，不要编造。若知识库中没有相关内容，"
        "直接说明未收录。回答使用中文，控制篇幅。"
    )
    prompt = f"知识库内容如下：\n{context}\n\n用户问题：{query}"
    try:
        return _llm_call(prompt, system=system)
    except Exception as exc:  # noqa: BLE001
        return f"知识库中未找到与「{query}」相关的内容（LLM 兜底失败: {exc}）。", 0.0


def _handle_knowledge_query(query: str) -> str:
    """本地知识库检索：关键词匹配标题/摘要/标签，按 score 排序。

    关键词检索无结果时，回退到 LLM 直读知识库全文回答。
    """
    keyword = _strip_prefixes(query, KNOWLEDGE_PREFIXES)
    if not keyword:
        return (
            "请输入要检索的知识库关键词，例如：知识库里有没有关于 agent 的文章。",
            {
                "type": "knowledge",
                "matched": 0,
                "llm_fallback": False,
                "llm_cost": 0.0,
                "llm_calls": 0,
            },
        )
    lowered = keyword.lower()

    matches = []
    for article in _load_articles():
        if lowered in _article_text(article):
            matches.append(article)
    matches.sort(
        key=lambda a: a.get("score") or 0, reverse=True
    )
    matches = matches[:SEARCH_PER_PAGE]

    if not matches:
        answer, cost = _llm_knowledge_answer(query)
        return answer, {
            "type": "knowledge",
            "matched": 0,
            "llm_fallback": True,
            "llm_cost": cost,
            "llm_calls": 1 if cost > 0 else 0,
        }

    lines = [f"知识库检索「{keyword}」找到 {len(matches)} 条:"]
    for i, article in enumerate(matches[:SEARCH_PER_PAGE], 1):
        title = article.get("title", "?")
        category = article.get("category", "")
        score = article.get("score")
        summary = article.get("summary", "") or "暂无摘要"
        score_part = f" | score: {score}" if score is not None else ""
        lines.append(
            f"{i}. {title} | {category}{score_part}\n   {summary}"
        )
    return "\n".join(lines), {
        "type": "knowledge",
        "matched": len(matches),
        "llm_fallback": False,
        "llm_cost": 0.0,
        "llm_calls": 0,
    }


def _handle_general_chat(query: str) -> str:
    """直接调用 LLM 回答。"""
    try:
        content, cost = _llm_call(query)
    except Exception as exc:  # noqa: BLE001
        return f"调用 LLM 失败: {exc}", {
            "type": "general", "llm_cost": 0.0, "llm_calls": 0,
        }
    return content, {"type": "general", "llm_cost": cost, "llm_calls": 1}


HANDLERS = {
    INTENT_GITHUB: _handle_github_search,
    INTENT_KNOWLEDGE: _handle_knowledge_query,
    INTENT_GENERAL: _handle_general_chat,
}


def _append_trace(entry: dict) -> None:
    """追加一行调用记录到 logs/router_trace.jsonl，写入失败仅告警不阻断。"""
    try:
        TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("trace 写入失败: %s", TRACE_FILE)


def _trace_stats() -> None:
    """汇总 router_trace.jsonl，输出关键词设计相关的统计信号。"""
    if not TRACE_FILE.is_file():
        print(f"暂无 trace 记录: {TRACE_FILE}")
        return
    entries = []
    for line in TRACE_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not entries:
        print("trace 记录为空。")
        return

    n = len(entries)
    kw_hit = [e for e in entries if e.get("keyword_hit")]
    llm_used = [e for e in entries if e.get("llm_intent")]
    llm_err = [e for e in entries if e.get("llm_error")]
    kw_empty = [e for e in entries if e.get("keyword_hit") and e.get("outcome", {}).get("matched") == 0]
    gh_empty = [e for e in entries if e.get("outcome", {}).get("type") == "github" and e.get("outcome", {}).get("count") == 0]

    from collections import Counter

    kw_counter = Counter(e.get("hit_keyword") for e in kw_hit)
    intent_counter = Counter(e.get("final_intent") for e in entries)
    top_queries = Counter(e.get("query") for e in llm_used).most_common(10)

    print(f"总调用: {n}")
    print(f"关键词命中: {len(kw_hit)} ({len(kw_hit) / n:.0%})")
    print(f"LLM 兜底路由: {len(llm_used)} ({len(llm_used) / n:.0%}) | 其中失败 {len(llm_err)}")
    print(f"关键词命中但知识库 0 条(疑误路由): {len(kw_empty)}")
    print(f"github 搜索 0 条: {len(gh_empty)}")
    print("\n命中关键词分布:")
    for k, c in kw_counter.most_common():
        print(f"  {c:>3}  {k}")
    print("\n最终意图分布:")
    for k, c in intent_counter.most_common():
        print(f"  {c:>3}  {k}")
    if top_queries:
        print("\n触发 LLM 兜底最多的查询:")
        for q, c in top_queries:
            print(f"  {c:>3}  {q}")


@dataclass
class RouteResult:
    """一次路由调用的结构化结果。

    Attributes:
        text: 最终回复文本。
        query: 原始查询。
        intent: 最终意图名。
        keyword_hit: 第一层关键词是否命中。
        hit_keyword: 命中的关键词（未命中为 None）。
        llm_intent: LLM 兜底分类返回的原始意图（未走 LLM 为 None）。
        llm_error: LLM 兜底分类的错误信息（无错误为 None）。
        outcome: 处理器结果元信息（如 knowledge 命中条数）。
        llm_cost: 本次调用累计 LLM 成本（USD）。
        llm_calls: 本次调用完成的 LLM 调用次数。
    """

    text: str
    query: str
    intent: str
    keyword_hit: bool
    hit_keyword: str | None
    llm_intent: str | None
    llm_error: str | None
    outcome: dict | None
    llm_cost: float = 0.0
    llm_calls: int = 0


def route_with_meta(query: str) -> RouteResult:
    """统一入口（带元信息）：关键词匹配优先，未命中则 LLM 分类兜底，再分发给处理器。

    与 :func:`route` 行为一致，额外返回路由过程与 LLM 成本的元信息，
    并写入 logs/router_trace.jsonl 轨迹记录。
    """
    query = (query or "").strip()
    if not query:
        return RouteResult("请输入查询内容。", query, "", False, None, None, None, None)

    kw_intent, hit_keyword = _keyword_route(query)
    llm_cost, llm_calls = 0.0, 0
    github_term = None
    if kw_intent:
        intent = kw_intent
        llm_intent, llm_error = None, None
    else:
        intent, llm_intent, llm_error, cost, github_term = _llm_route(query)
        llm_cost += cost
        llm_calls += 1 if cost > 0 else 0

    logger.info("route: intent=%s query=%s", intent, query)
    if intent == INTENT_GITHUB and github_term:
        reply = _handle_github_search(query, github_term)
    else:
        reply = HANDLERS[intent](query)
    text, outcome = reply if isinstance(reply, tuple) else (reply, None)
    outcome = outcome or {}
    llm_cost += outcome.get("llm_cost", 0.0) or 0.0
    llm_calls += outcome.get("llm_calls", 0) or 0

    _append_trace(
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "query": query,
            "keyword_hit": kw_intent is not None,
            "hit_keyword": hit_keyword,
            "keyword_intent": kw_intent,
            "llm_intent": llm_intent,
            "llm_error": llm_error,
            "final_intent": intent,
            "outcome": outcome,
            "llm_cost": llm_cost,
            "llm_calls": llm_calls,
        }
    )
    return RouteResult(
        text=text,
        query=query,
        intent=intent,
        keyword_hit=kw_intent is not None,
        hit_keyword=hit_keyword,
        llm_intent=llm_intent,
        llm_error=llm_error,
        outcome=outcome,
        llm_cost=llm_cost,
        llm_calls=llm_calls,
    )


def route(query: str) -> str:
    """统一入口（纯文本版）：等价于 :func:`route_with_meta` 的 ``text``。

    Args:
        query: 用户原始查询。

    Returns:
        处理结果文本。
    """
    return route_with_meta(query).text


def _format_cli_result(result: RouteResult) -> str:
    """将路由结果格式化为规范化的命令行输出。"""
    route_desc = {
        INTENT_GITHUB: "GitHub 仓库搜索",
        INTENT_KNOWLEDGE: "本地知识库检索",
        INTENT_GENERAL: "通用对话",
    }.get(result.intent, result.intent)
    lines = [
        f"[输入] {result.query}",
        f"[路由] {route_desc} ({result.intent})",
    ]
    if result.keyword_hit:
        lines.append(f"[关键词] 命中「{result.hit_keyword}」→ {result.intent}")
    elif result.llm_intent:
        lines.append(
            f"[关键词] 未命中，LLM 兜底分类 → {result.intent}"
            f"（LLM 原始意图: {result.llm_intent}）"
        )
    else:
        lines.append(f"[关键词] 未命中，LLM 兜底分类 → {result.intent}（LLM 调用失败）")
    if result.llm_error:
        lines.append(f"[LLM] 分类失败: {result.llm_error}")
    if result.llm_calls > 0:
        lines.append(
            f"[LLM] 调用 {result.llm_calls} 次，约 ${result.llm_cost:.6f}"
        )
    if result.outcome and result.outcome.get("via_direct"):
        lines.append("[GitHub] 已改用直连（原代理连接失败）")
    lines.append(f"[回答]\n{result.text}")
    return "\n".join(lines)


def _setup_logging() -> None:
    """INFO 及以上日志写入 logs/router.log，不在控制台输出。"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
    )


def main() -> None:
    """测试入口：支持命令行传入单条查询，否则跑内置样例。"""
    import sys

    _setup_logging()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--rebuild-index":
            rebuild_index()
            return
        if sys.argv[1] == "--trace-stats":
            _trace_stats()
            return
        queries = [" ".join(sys.argv[1:])]
    else:
        queries = [
            "github 搜索 rag 推理框架",
            "搜一下 star 高的 LLM 训练框架",
            "知识库里有没有关于 agent 的文章",
            "查一下库里最近收录的推理优化技术",
            "你好，请用一句话介绍大语言模型 picture",
        ]
    for q in queries:
        print(_format_cli_result(route_with_meta(q)) + "\n")


if __name__ == "__main__":
    main()