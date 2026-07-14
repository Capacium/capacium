"""UP-002: blocked-but-honest status for upstream-broken capabilities.

elementeer (@elementeer/shared missing on npm) and karldane (go.mod replace
pointing at the author's machine) can never work — they get per-adapter
status 'blocked' with the upstream reason, visible in cap list --details
and distinguished from 'broken' in doctor.
"""
import pytest

from capacium.commands.block_status import (
    block_capability,
    get_blocked_frameworks,
    unblock_capability,
)
from capacium.commands.doctor import _check_mcp_handshake
from capacium.commands.list_capabilities import list_capabilities
from capacium.models import Capability, Kind
from capacium.registry import Registry


@pytest.fixture
def upstream_broken_cap(tmp_home):
    pkg = tmp_home / ".capacium" / "packages" / "karldane" / "slack-mcp" / "1.0.0"
    pkg.mkdir(parents=True)
    (pkg / "capability.yaml").write_text(
        "kind: mcp-server\nname: slack-mcp\nversion: 1.0.0\ndescription: t\n"
        "mcp:\n  transport: stdio\n  command: /nonexistent/slack-mcp\n"
    )
    registry = Registry()
    cap = Capability(
        owner="karldane", name="slack-mcp", version="1.0.0",
        kind=Kind.MCP_SERVER, install_path=pkg, fingerprint="f" * 64,
        framework="claude-code", frameworks=["claude-code", "opencode"],
    )
    assert registry.add_capability(cap)
    return {"registry": registry, "cap": cap}


REASON = "go.mod replace points at the author's machine — never buildable"


class TestBlockLifecycle:
    def test_block_sets_status_on_all_adapters(self, tmp_home, upstream_broken_cap):
        assert block_capability(
            "karldane/slack-mcp", reason=REASON,
            issue="https://github.com/karldane/slack-mcp/issues/1",
        ) is True
        blocked = get_blocked_frameworks(
            upstream_broken_cap["registry"], upstream_broken_cap["cap"]
        )
        assert set(blocked) == {"claude-code", "opencode"}
        assert REASON in blocked["claude-code"]
        assert "issues/1" in blocked["claude-code"]

    def test_block_requires_reason(self, tmp_home, upstream_broken_cap):
        assert block_capability("karldane/slack-mcp", reason="") is False

    def test_unblock_clears(self, tmp_home, upstream_broken_cap):
        block_capability("karldane/slack-mcp", reason=REASON)
        assert unblock_capability("karldane/slack-mcp") is True
        assert get_blocked_frameworks(
            upstream_broken_cap["registry"], upstream_broken_cap["cap"]
        ) == {}
        assert unblock_capability("karldane/slack-mcp") is False


class TestVisibility:
    def test_list_details_shows_blocked_with_reason(
        self, tmp_home, upstream_broken_cap, capsys
    ):
        block_capability("karldane/slack-mcp", reason=REASON)
        capsys.readouterr()
        list_capabilities(details=True)
        out = capsys.readouterr().out
        assert "blocked" in out
        assert "never buildable" in out

    def test_doctor_distinguishes_blocked_from_broken(
        self, tmp_home, upstream_broken_cap, capsys
    ):
        """A blocked cap must not appear as a failed probe — and must not be
        probed at all (it cannot respond, that is the point)."""
        block_capability("karldane/slack-mcp", reason=REASON)
        name, passed, detail = _check_mcp_handshake()
        assert passed is True, f"blocked cap reported as broken: {detail}"
        assert "blocked (upstream)" in detail
        assert "slack-mcp" in detail

    def test_doctor_unblocked_broken_cap_still_fails(
        self, tmp_home, upstream_broken_cap
    ):
        name, passed, detail = _check_mcp_handshake()
        assert passed is False
        assert "slack-mcp" in detail
