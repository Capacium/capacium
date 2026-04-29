import shutil
from typing import List, Optional
from ..registry import Registry
from ..models import Kind
from ..registry_client import RegistryClient, RegistryResult, RegistryDetail, RegistryClientError
from ..utils.config import get_registry_url


_TRUST_BADGES = {
    "verified": "\U0001f7e2",
    "audited": "\U0001f7e1",
    "signed": "\U0001f535",
    "untrusted": "\U0001f534",
}


def _badge(trust: str) -> str:
    return _TRUST_BADGES.get(trust.lower(), _TRUST_BADGES["untrusted"])


def _kind_label(kind_str: str) -> str:
    return kind_str if kind_str else "skill"


def _fmt_installs(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _format_result_card(r: RegistryResult, install_cmd: str, info_cmd: str) -> str:
    trust_label = r.trust.lower() if r.trust else "untrusted"
    badge = _badge(trust_label)
    kind = _kind_label(r.kind)
    frameworks = ", ".join(r.frameworks) if r.frameworks else "any"
    dep_str = ""
    if r.dependencies:
        dep_str = "  \u2502  Depends on: " + ", ".join(r.dependencies.keys())
    runtime_str = ""
    if r.runtimes:
        runtimes_list = [f"{k} {v}" for k, v in r.runtimes.items()]
        runtime_str = "  \u2502  Runtimes: " + ", ".join(runtimes_list)
    tags_str = ""
    if r.tags:
        tags_str = "  \u2502  Tags: " + ", ".join(r.tags)
    installs_label = _fmt_installs(r.installs) + " installs"

    lines = [
        f"{badge} {r.owner}/{r.name}   v{r.version}  {trust_label}",
        f"   {r.description or 'No description'}   {installs_label}",
        f"   Kind: {kind}  \u2502  Framework: {frameworks}",
    ]
    if dep_str:
        lines.append(dep_str)
    if runtime_str:
        lines.append(runtime_str)
    if tags_str:
        lines.append(tags_str)
    lines.append(f""
                 f"")
    lines.append(f"   $ {install_cmd}")
    lines.append(f"   $ {info_cmd}")
    return "\n".join(lines)


def search_capabilities(query: str, kind: Optional[str] = None, registry_url: Optional[str] = None,
                        category: Optional[str] = None, trust: Optional[str] = None,
                        min_trust: Optional[str] = None, tag: Optional[List[str]] = None,
                        mcp_client: Optional[str] = None, publisher: Optional[str] = None,
                        sort: Optional[str] = None, json_output: bool = False,
                        limit: int = 50, framework: Optional[str] = None):
    effective_url = registry_url or get_registry_url()

    client = RegistryClient()
    try:
        tag_value = tag[0] if tag else None
        results = client.search(
            query,
            kind=kind,
            registry_url=effective_url,
            framework=framework,
            trust=trust or min_trust,
            category=category,
            tag=tag_value,
            sort=sort or "relevance",
            limit=limit,
        )
    except RegistryClientError as e:
        print(f"\u26a0\ufe0f  Exchange not reachable ({e})")
        print("   Falling back to local registry...\n")
        _search_local(query, kind)
        return

    if not results:
        print(f"\U0001f50d Results for \"{query}\" \u2014 0 found")
        return

    print(f"\U0001f50d Results for \"{query}\" \u2014 {len(results)} found\n")
    for r in results:
        cap_id = f"{r.owner}/{r.name}"
        install_cmd = f"cap install {cap_id}"
        info_cmd = f"cap info {cap_id}"
        print(_format_result_card(r, install_cmd, info_cmd))
        print()


def cap_info(cap_spec: str, registry_url: Optional[str] = None):
    effective_url = registry_url or get_registry_url()
    client = RegistryClient()

    try:
        detail = client.get_detail(cap_spec, registry_url=effective_url)
    except RegistryClientError as e:
        print(f"\u26a0\ufe0f  Exchange not reachable ({e})")
        return

    if detail is None:
        print(f"Capability \"{cap_spec}\" not found.")
        return

    trust_label = detail.trust.lower() if detail.trust else "untrusted"
    badge = _badge(trust_label)
    kind = _kind_label(detail.kind)
    frameworks = ", ".join(detail.frameworks) if detail.frameworks else "any"

    sep = "\u2500" * 62
    print(f"\n{sep}")
    print(f"  {badge} {detail.owner}/{detail.name}")
    print(f"  {detail.description or 'No description'}")
    print(f"  Version: v{detail.version}")
    print(sep)
    print(f"  Trust State:  {trust_label.upper()}")
    if detail.trust_breakdown:
        print(f"  Trust Score:  {detail.trust_score}/100")
        for key, value in detail.trust_breakdown.items():
            print(f"    \u2022 {key}: {value}")
    print(f"  Installs:     {_fmt_installs(detail.installs)}")
    print(sep)

    if detail.versions:
        print(f"  Available versions: {', '.join(detail.versions[:10])}")
        if len(detail.versions) > 10:
            print(f"  ... and {len(detail.versions) - 10} more")

    if detail.dependencies:
        print(f"  Dependencies:")
        for dep_name, dep_version in detail.dependencies.items():
            print(f"    \u2022 {dep_name}: {dep_version}")

    if detail.runtimes:
        print(f"  Runtimes:")
        for r_name, r_version in detail.runtimes.items():
            print(f"    \u2022 {r_name}: {r_version}")

    if detail.tags:
        print(f"  Tags: {', '.join(detail.tags)}")

    if detail.categories:
        print(f"  Categories: {', '.join(detail.categories)}")

    print(f"  Kind:          {kind}")
    print(f"  Framework:     {frameworks}")
    if detail.repository:
        print(f"  Repository:    {detail.repository}")
    if detail.published_at:
        print(f"  Published:     {detail.published_at}")
    if detail.updated_at:
        print(f"  Updated:       {detail.updated_at}")
    print(sep)
    print(f"  Install: $ cap install {detail.owner}/{detail.name}")
    print(f"  Info:    $ cap info {detail.owner}/{detail.name}")
    print(f"{sep}\n")


def _search_local(query: str, kind: Optional[str] = None):
    registry = Registry()
    kind_enum = None
    if kind:
        try:
            kind_enum = Kind(kind)
        except ValueError:
            valid = ", ".join(k.value for k in Kind)
            print(f"Invalid kind: {kind}. Valid kinds: {valid}")
            return

    capabilities = registry.search_capabilities(query, kind=kind_enum)

    if not capabilities:
        print(f"No capabilities matching '{query}'.")
        return

    term_width = shutil.get_terminal_size((80, 20)).columns
    print(f"Found {len(capabilities)} capability(ies) matching '{query}':\n")
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        kind_str = cap.kind.value if cap.kind else "skill"
        print(f"  \u2022 [{kind_str}] {cap_id}@{cap.version}")
        print(f"    fingerprint: {cap.fingerprint[:12]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        print(f"    $ cap info {cap_id}")
        print()
