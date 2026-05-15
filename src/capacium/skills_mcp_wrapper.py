"""Capacium Skills MCP Wrapper — exposes installed skills as MCP tools on stdio.

Auto-discovers all skills installed under `--cap-home` and registers each as
an MCP tool with its name and description from SKILL.md / capability.yaml.

Usage:
    python3 -m capacium.skills_mcp_wrapper --cap-home ~/.capacium/packages

Or via cap skills-mcp (P1-003):
    cap skills-mcp start

The ClaudeDesktopAdapter.install_skill() registers this wrapper as the
'capacium-skills' mcpServers entry so Claude Desktop auto-starts it.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


# =============================================================================
# Skill discovery
# =============================================================================

def _discover_skills(cap_home: Path) -> List[Dict[str, Any]]:
    """Walk cap_home and return metadata for every installed skill.

    Expected layout:
        cap_home / <owner> / <skill_name> / capability.yaml
        cap_home / <owner> / <skill_name> / SKILL.md      (optional)
    """
    skills: List[Dict[str, Any]] = []
    if not cap_home.exists():
        return skills

    for owner_dir in sorted(cap_home.iterdir()):
        if not owner_dir.is_dir() or owner_dir.name.startswith("."):
            continue
        for skill_dir in sorted(owner_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            cap_yaml = skill_dir / "capability.yaml"
            if not cap_yaml.exists():
                continue

            data = _parse_yaml_simple(cap_yaml)
            description = data.get("description", "")

            skill_md_path = skill_dir / "SKILL.md"
            if not description and skill_md_path.exists():
                description = _extract_description_from_skill_md(skill_md_path)

            skills.append({
                "name": data.get("name", skill_dir.name),
                "owner": data.get("owner", owner_dir.name),
                "version": data.get("version", "0.0.0"),
                "kind": data.get("kind", "skill"),
                "description": description or f"Installed skill: {skill_dir.name}",
                "path": str(skill_dir),
                "skill_md": str(skill_md_path) if skill_md_path.exists() else None,
            })

    return skills


def _parse_yaml_simple(path: Path) -> Dict[str, str]:
    """Parse a YAML file using stdlib (yaml package optional)."""
    try:
        import yaml  # type: ignore
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:
        return {}

    # Fallback: regex-based single-level key: value extraction
    result: Dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            m = re.match(r'^([a-z_]+):\s*(.+)$', line)
            if m:
                result[m.group(1)] = m.group(2).strip().strip("'\"")
    except Exception:
        pass
    return result


def _extract_description_from_skill_md(path: Path) -> str:
    """Pull description from YAML frontmatter of SKILL.md."""
    try:
        content = path.read_text()
        if not content.startswith("---"):
            return ""
        end = content.find("---", 3)
        if end < 0:
            return ""
        for line in content[3:end].splitlines():
            m = re.match(r'^description:\s*(.+)$', line.strip())
            if m:
                return m.group(1).strip().strip("'\"")
    except Exception:
        pass
    return ""


# =============================================================================
# MCP tool schema helpers
# =============================================================================

def _tool_name(skill: Dict[str, Any]) -> str:
    """Convert skill name to a valid MCP tool identifier."""
    return "skill_" + re.sub(r"[^a-zA-Z0-9_]", "_", skill["name"])


def _build_tools_list(skills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the tools array for an MCP tools/list response."""
    tools: List[Dict[str, Any]] = [
        {
            "name": "list_skills",
            "description": (
                f"List all {len(skills)} Capacium skill(s) installed in this environment. "
                "Returns name, version, and description for each."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    for skill in skills:
        tools.append({
            "name": _tool_name(skill),
            "description": skill["description"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional query or usage context for this skill",
                    }
                },
            },
        })
    return tools


# =============================================================================
# Tool call handler
# =============================================================================

def _handle_call(
    skill_map: Dict[str, Dict[str, Any]],
    tool_name: str,
    arguments: Dict[str, Any],
) -> str:
    """Execute a tool call and return its text result."""
    if tool_name == "list_skills":
        if not skill_map:
            return "No skills installed in this environment."
        lines = [f"{len(skill_map)} Capacium skill(s) installed:\n"]
        for name, skill in sorted(skill_map.items()):
            lines.append(
                f"  • {skill['owner']}/{skill['name']} v{skill['version']}\n"
                f"    {skill['description']}"
            )
        return "\n".join(lines)

    skill = skill_map.get(tool_name)
    if not skill:
        return f"Unknown skill tool '{tool_name}'. Call 'list_skills' to see available tools."

    # Return SKILL.md content as the tool result
    if skill.get("skill_md"):
        try:
            return Path(skill["skill_md"]).read_text()
        except Exception:
            pass

    return (
        f"# {skill['owner']}/{skill['name']} v{skill['version']}\n\n"
        f"{skill['description']}"
    )


# =============================================================================
# MCP stdio server loop
# =============================================================================

def run_mcp_server(cap_home: Path) -> None:
    """Start the MCP server on stdin/stdout (JSON-RPC 2.0 over stdio)."""
    skills = _discover_skills(cap_home)
    tools = _build_tools_list(skills)
    skill_map = {_tool_name(s): s for s in skills}

    print(
        f"capacium-skills-mcp: {len(skills)} skill(s) in {cap_home}",
        file=sys.stderr,
        flush=True,
    )

    def _write(obj: Any) -> None:
        print(json.dumps(obj), flush=True)

    def _respond(msg_id: Any, result: Any) -> None:
        _write({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _error(msg_id: Any, code: int, message: str) -> None:
        _write({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method: str = msg.get("method", "")
        msg_id: Any = msg.get("id")
        params: Dict[str, Any] = msg.get("params") or {}

        # Notifications have no id — never respond to them
        is_notification = msg_id is None

        if method == "initialize":
            _respond(msg_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "capacium-skills", "version": "1.0.0"},
            })

        elif method == "notifications/initialized":
            pass  # Fire-and-forget notification

        elif method == "tools/list":
            _respond(msg_id, {"tools": tools})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}
            text = _handle_call(skill_map, tool_name, arguments)
            _respond(msg_id, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })

        elif method == "ping":
            _respond(msg_id, {})

        elif not is_notification:
            _error(msg_id, -32601, f"Method not found: {method}")


# =============================================================================
# Entry point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="capacium.skills_mcp_wrapper",
        description="Capacium skills MCP server — exposes installed skills as MCP tools",
    )
    parser.add_argument(
        "--cap-home",
        default=str(Path.home() / ".capacium" / "packages"),
        metavar="DIR",
        help="Capacium package cache directory (default: ~/.capacium/packages)",
    )
    args = parser.parse_args()
    run_mcp_server(Path(args.cap_home).expanduser())


if __name__ == "__main__":
    main()
