"""Capacium Registry category taxonomy and auto-classification.

Provides a 2-level category hierarchy, tag/keyword-based classification
for listings, GitHub topic extraction, and taxonomy seeding for the local
search index.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from src.capacium.index import Index

TAXONOMY: Dict[str, Dict[str, object]] = {
    "AI & Agents": {
        "description": "Agent capabilities, skills, tools, and prompt engineering",
        "children": {
            "Agent Skills": "Reusable agent skill configurations",
            "Agent Tools": "Tool integrations for AI agents",
            "Agent Workflows": "Multi-step agent coordination flows",
            "Prompt Templates": "Reusable prompt engineering templates",
        },
    },
    "MCP Infrastructure": {
        "description": "Model Context Protocol servers and infrastructure",
        "children": {
            "Browser MCPs": "Browser automation MCP servers",
            "Filesystem MCPs": "File system access MCPs",
            "Database MCPs": "Database connectivity MCPs",
            "API MCPs": "API integration MCPs",
            "Utility MCPs": "General purpose MCP servers",
        },
    },
    "Developer Tools": {
        "description": "Development environment tools, CLI, and workflows",
        "children": {
            "CLI Plugins": "Command-line interface plugins",
            "Git & Versioning": "Git hooks and version control tools",
            "CI/CD": "Continuous integration and deployment tools",
            "Testing": "Test frameworks and runners",
            "Linting & Formatting": "Code quality tools",
        },
    },
    "Data & Knowledge": {
        "description": "Data processing, search, and knowledge bases",
        "children": {
            "Vector Databases": "Vector embedding storage and search",
            "Knowledge Bases": "Structured knowledge management",
            "Data Processing": "ETL and data transformation",
        },
    },
    "Security & Trust": {
        "description": "Security scanning, fingerprinting, and signing",
        "children": {
            "Vulnerability Scanning": "Security vulnerability detection",
            "Secrets Management": "Credential and secret handling",
            "Compliance": "Regulatory compliance tools",
        },
    },
    "Communication": {
        "description": "Messaging, notifications, and collaboration",
        "children": {
            "Email": "Email integration tools",
            "Messaging": "Chat and messaging platforms",
            "Notifications": "Push notification services",
        },
    },
    "Content & Media": {
        "description": "Content management, media processing, and publishing",
        "children": {
            "CMS Integration": "Content management systems",
            "Media Processing": "Image, video, and audio processing",
            "Document Generation": "PDF and document creation",
        },
    },
    "Platform & Cloud": {
        "description": "Cloud platforms, infrastructure, and deployments",
        "children": {
            "Cloud Providers": "AWS, GCP, Azure integrations",
            "Container Orchestration": "Docker, Kubernetes tools",
            "Serverless": "Serverless function deployments",
        },
    },
    "Browser & Web": {
        "description": "Web scraping, browser automation, and HTTP",
        "children": {
            "Web Scraping": "Data extraction from websites",
            "HTTP Clients": "HTTP request tools and utilities",
            "Web Frameworks": "Web application frameworks",
        },
    },
    "Utilities": {
        "description": "General purpose utilities and helpers",
        "children": {
            "File Management": "File operations and management",
            "Text Processing": "Text manipulation and parsing",
            "Date & Time": "Date, time, and scheduling utilities",
        },
    },
}

_TAG_CATEGORY_MAP: Dict[str, str] = {
    "browser": "Browser & Web/Web Scraping",
    "playwright": "Browser & Web/Web Scraping",
    "puppeteer": "Browser & Web/Web Scraping",
    "selenium": "Browser & Web/Web Scraping",
    "chrome": "Browser & Web/Web Scraping",
    "firefox": "Browser & Web/Web Scraping",
    "database": "Data & Knowledge/Data Processing",
    "sql": "Data & Knowledge/Data Processing",
    "postgres": "Data & Knowledge/Data Processing",
    "mysql": "Data & Knowledge/Data Processing",
    "redis": "Data & Knowledge/Data Processing",
    "mongodb": "Data & Knowledge/Data Processing",
    "api": "MCP Infrastructure/API MCPs",
    "rest": "MCP Infrastructure/API MCPs",
    "graphql": "MCP Infrastructure/API MCPs",
    "http": "MCP Infrastructure/API MCPs",
    "filesystem": "MCP Infrastructure/Filesystem MCPs",
    "file": "MCP Infrastructure/Filesystem MCPs",
    "folder": "MCP Infrastructure/Filesystem MCPs",
    "directory": "MCP Infrastructure/Filesystem MCPs",
    "security": "Security & Trust/Vulnerability Scanning",
    "auth": "Security & Trust/Vulnerability Scanning",
    "oauth": "Security & Trust/Vulnerability Scanning",
    "sso": "Security & Trust/Vulnerability Scanning",
    "scan": "Security & Trust/Vulnerability Scanning",
}

_KIND_DEFAULTS: Dict[str, str] = {
    "mcp-server": "MCP Infrastructure/Utility MCPs",
    "skill": "AI & Agents/Agent Skills",
    "tool": "Developer Tools/CLI Plugins",
    "bundle": "AI & Agents/Agent Workflows",
}

_FALLBACK_CATEGORY = "Utilities/File Management"


def classify(listing: dict) -> list[str]:
    """Determine categories for a listing based on kind, tags, and existing data.

    Checks categories field first, then falls back to tag/keyword matching,
    then kind-based defaults, then a generic fallback.
    """
    existing = listing.get("categories")
    if existing and isinstance(existing, list) and len(existing) > 0:
        return existing

    tags = listing.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                continue
            match = _TAG_CATEGORY_MAP.get(tag.lower().strip())
            if match:
                return [match]

    kind = listing.get("kind")
    default = _KIND_DEFAULTS.get(kind, _FALLBACK_CATEGORY)
    return [default]


def classify_from_github_topics(topics: list[str]) -> list[str]:
    """Extract and normalize GitHub topics into de-duplicated tags."""
    normalized: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        if not isinstance(topic, str):
            continue
        cleaned = topic.lower().strip().replace(" ", "-")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized[:15]


def seed_taxonomy(index: Index) -> None:
    """Seed the taxonomy table with the standard 2-level category hierarchy."""
    for level1_name, level1_data in TAXONOMY.items():
        index.upsert_taxonomy(
            path=level1_name,
            level=1,
            name=level1_name,
            parent_path="",
            description=str(level1_data.get("description", "")),
        )
        children = level1_data.get("children", {})
        if isinstance(children, dict):
            for level2_name, level2_desc in children.items():
                path = f"{level1_name}/{level2_name}"
                index.upsert_taxonomy(
                    path=path,
                    level=2,
                    name=level2_name,
                    parent_path=level1_name,
                    description=str(level2_desc),
                )
    index.update_category_counts()


def get_category_tree(index: Index) -> dict:
    """Build a nested category tree with descriptions and counts."""
    raw = index.get_taxonomy()
    level1_nodes: dict[str, dict] = {}

    for entry in raw:
        level = entry.get("level")
        name = entry.get("name")
        desc = entry.get("description", "")
        if not name:
            continue

        if level == 1:
            path = entry.get("path", name)
            level1_count = index.count_by_category(parent_path=path)
            total = sum(level1_count.values()) if level1_count else 0
            level1_nodes[path] = {
                "description": desc,
                "count": total,
                "children": {},
            }
        elif level == 2:
            parent_path = entry.get("parent_path", "")
            if parent_path in level1_nodes:
                child_path = entry.get("path", "")
                child_counts = index.count_by_category(parent_path=parent_path)
                child_count = child_counts.get(child_path, 0)
                level1_nodes[parent_path]["children"][name] = {
                    "description": desc,
                    "count": child_count,
                }

    return level1_nodes
