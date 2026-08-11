#!/usr/bin/env python3
"""MCP Server for local knowledge base search.

Implements a JSON-RPC 2.0 over stdio MCP server that exposes tools to search
the articles in knowledge/articles/*.json.  Only the Python standard library
is used; each request is a single-line JSON object read from stdin, and each
response is a single-line JSON object written to stdout.

Supported methods:
  initialize         -> server capabilities
  tools/list         -> list available tools
  tools/call         -> invoke a tool by name and arguments
"""

import json
import sys
from pathlib import Path

ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"

PROTOCOL_VERSION = "2024-11-05"


def load_articles():
    """Load all JSON files under ARTICLES_DIR.

    Malformed or non-JSON (e.g. directories) entries are skipped so a single
    bad file never breaks the whole server.
    """
    articles = []
    if not ARTICLES_DIR.is_dir():
        return articles
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        if path.name.startswith("test-"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                articles.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue
    return articles


def _article_text(article):
    """Return the searchable text of an article (title + summary + tags)."""
    parts = [article.get("title", ""), article.get("summary", "")]
    tags = article.get("tags") or []
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    return " ".join(parts).lower()


def search_articles(keyword, limit=5):
    """Case-insensitive keyword search over title, summary and tags."""
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return {"results": [], "total": 0}
    matches = []
    for article in load_articles():
        if keyword in _article_text(article):
            matches.append(minify(article))
    matches.sort(key=lambda a: a.get("metadata", {}).get("score", 0), reverse=True)
    matches = matches[: int(limit)]
    return {"results": matches, "total": len(matches), "keyword": keyword}


def get_article(article_id):
    """Return the full article matching the given id."""
    if not article_id:
        return {"found": False, "article": None}
    for article in load_articles():
        if article.get("id") == article_id:
            return {"found": True, "article": article}
    return {"found": False, "article": None, "id": article_id}


def knowledge_stats():
    """Return article count, source distribution and top tags."""
    articles = load_articles()
    sources = {}
    tags = {}
    for article in articles:
        source = article.get("source_type") or article.get("source") or "unknown"
        sources[source] = sources.get(source, 0) + 1
        raw_tags = article.get("tags") or []
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                key = str(tag)
                tags[key] = tags.get(key, 0) + 1
    top_tags = sorted(tags.items(), key=lambda kv: kv[1], reverse=True)[:10]
    return {
        "total": len(articles),
        "sources": sources,
        "top_tags": [{"tag": tag, "count": count} for tag, count in top_tags],
    }


def minify(article):
    """Return a trimmed copy suitable for list results."""
    return {
        "id": article.get("id"),
        "title": article.get("title"),
        "source_type": article.get("source_type"),
        "summary": article.get("summary"),
        "tags": article.get("tags"),
        "category": article.get("category"),
        "score": article.get("metadata", {}).get("score"),
    }


TOOLS = [
    {
        "name": "search_articles",
        "description": "Search local knowledge base articles by keyword over title, summary and tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Search keyword"},
                "limit": {
                    "type": "integer",
                    "description": "Max results, default 5",
                    "default": 5,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "Get a full article by its id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "Article id, e.g. github-20260804-001"},
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "Return knowledge base stats: total count, source distribution and top tags.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_HANDLERS = {
    "search_articles": lambda args: search_articles(
        args.get("keyword"), args.get("limit", 5)
    ),
    "get_article": lambda args: get_article(args.get("article_id")),
    "knowledge_stats": lambda args: knowledge_stats(),
}

# Initialize state
_session_initialized = False


def make_result(raw):
    """Wrap a tool's return value into an MCP content result."""
    return {"content": [{"type": "text", "text": json.dumps(raw, ensure_ascii=False)}]}


def handle(request):
    """Route a JSON-RPC request and return the response dict."""
    if request.get("jsonrpc") != "2.0":
        return rpc_response(request, id=request.get("id"), error={
            "code": -32600, "message": "Invalid Request", "data": "missing jsonrpc=2.0"
        })

    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        global _session_initialized
        _session_initialized = True
        return rpc_response(request, result={
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {"name": "mcp_knowledge_server", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        # Notification: no id, no response expected.
        return None

    if method == "tools/list":
        if not _session_initialized:
            return rpc_response(request, error={"code": -32001, "message": "Server not initialized"})
        return rpc_response(request, result={"tools": TOOLS})

    if method == "tools/call":
        try:
            tool_name = params.get("name")
            if tool_name not in TOOL_HANDLERS:
                return rpc_response(request, error={
                    "code": -32602, "message": f"Unknown tool: {tool_name}",
                })
            args = params.get("arguments") or {}
            result = TOOL_HANDLERS[tool_name](args)
            return rpc_response(request, result=make_result(result))
        except Exception as exc:  # noqa: BLE001 - surface any tool error to client
            return rpc_response(request, error={
                "code": -32603, "message": "Tool error", "data": str(exc),
            })

    if method == "ping":
        return rpc_response(request, result={})

    return rpc_response(request, error={
        "code": -32601, "message": f"Method not found: {method}",
    })


def rpc_response(request, result=None, error=None):
    """Build a JSON-RPC 2.0 response object."""
    body = {"jsonrpc": "2.0", "id": request.get("id")}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    return body


def main():
    """Read JSON lines from stdin and write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue
        try:
            response = handle(request)
        except Exception as exc:  # noqa: BLE001
            response = rpc_response(request, error={
                "code": -32603, "message": str(exc),
            })
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()