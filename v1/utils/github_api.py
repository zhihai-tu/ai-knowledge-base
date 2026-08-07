import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class RepositoryInfo:
    """Repository basic information from GitHub API."""

    full_name: str
    description: Optional[str]
    stars: int
    forks: int
    language: Optional[str]
    url: str


def get_repo_info(owner: str, repo: str, token: Optional[str] = None) -> RepositoryInfo:
    """Fetch basic information for a GitHub repository.

    Args:
        owner: Repository owner or organization name.
        repo: Repository name.
        token: Optional GitHub personal access token for authenticated requests.

    Returns:
        RepositoryInfo containing stars, forks, description, etc.

    Raises:
        httpx.HTTPStatusError: If GitHub API returns an error response.
        httpx.RequestError: If network request fails.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    data = response.json()
    logger.info("Fetched repo info: %s", data["full_name"])

    return RepositoryInfo(
        full_name=data["full_name"],
        description=data.get("description"),
        stars=data["stargazers_count"],
        forks=data["forks_count"],
        language=data.get("language"),
        url=data["html_url"],
    )
