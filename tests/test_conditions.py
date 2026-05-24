"""Tests for the condition expression evaluator (CAP-005)."""

import pytest

from capacium.conditions import ConditionEvaluator, ConditionResult


# ------------------------------------------------------------------
# Shared context fixture
# ------------------------------------------------------------------

@pytest.fixture
def ctx():
    return {
        "runtime": {"python": "3.11", "node": "20.0"},
        "os": "linux",
        "env": {"OPENAI_API_KEY": "set", "HOME": "/home/user"},
        "trust_state": "verified",
        "kind": "skill",
    }


@pytest.fixture
def evaluator(ctx):
    return ConditionEvaluator(ctx)


# ------------------------------------------------------------------
# Simple equality
# ------------------------------------------------------------------

class TestEquality:
    def test_os_equals(self, evaluator):
        r = evaluator.evaluate("os == linux")
        assert r.passed is True

    def test_os_not_equals(self, evaluator):
        r = evaluator.evaluate("os == windows")
        assert r.passed is False

    def test_kind_equals(self, evaluator):
        r = evaluator.evaluate("kind == skill")
        assert r.passed is True

    def test_inequality(self, evaluator):
        r = evaluator.evaluate("os != windows")
        assert r.passed is True

    def test_inequality_false(self, evaluator):
        r = evaluator.evaluate("os != linux")
        assert r.passed is False


# ------------------------------------------------------------------
# Version comparison
# ------------------------------------------------------------------

class TestVersionComparison:
    def test_python_gte_match(self, evaluator):
        r = evaluator.evaluate("runtime.python >= 3.10")
        assert r.passed is True

    def test_python_gte_exact(self, evaluator):
        r = evaluator.evaluate("runtime.python >= 3.11")
        assert r.passed is True

    def test_python_gte_fail(self, evaluator):
        r = evaluator.evaluate("runtime.python >= 3.12")
        assert r.passed is False

    def test_python_lt(self, evaluator):
        r = evaluator.evaluate("runtime.python < 4.0")
        assert r.passed is True

    def test_python_gt(self, evaluator):
        r = evaluator.evaluate("runtime.python > 3.10")
        assert r.passed is True

    def test_node_lte(self, evaluator):
        r = evaluator.evaluate("runtime.node <= 20.0")
        assert r.passed is True

    def test_node_lte_fail(self, evaluator):
        r = evaluator.evaluate("runtime.node <= 18.0")
        assert r.passed is False


# ------------------------------------------------------------------
# Existence checks
# ------------------------------------------------------------------

class TestExistence:
    def test_exists_present(self, evaluator):
        r = evaluator.evaluate("env.OPENAI_API_KEY exists")
        assert r.passed is True

    def test_exists_missing(self, evaluator):
        r = evaluator.evaluate("env.SECRET exists")
        assert r.passed is False
        assert "not found" in r.reason

    def test_not_exists_present(self, evaluator):
        r = evaluator.evaluate("env.OPENAI_API_KEY not-exists")
        assert r.passed is False

    def test_not_exists_missing(self, evaluator):
        r = evaluator.evaluate("env.SECRET not-exists")
        assert r.passed is True


# ------------------------------------------------------------------
# Trust state ordering
# ------------------------------------------------------------------

class TestTrustState:
    def test_trust_gte_verified(self, evaluator):
        r = evaluator.evaluate("trust_state >= verified")
        assert r.passed is True

    def test_trust_gte_signed(self, evaluator):
        r = evaluator.evaluate("trust_state >= signed")
        assert r.passed is False

    def test_trust_gt_audited(self, evaluator):
        r = evaluator.evaluate("trust_state > audited")
        assert r.passed is True

    def test_trust_eq(self, evaluator):
        r = evaluator.evaluate("trust_state == verified")
        assert r.passed is True


# ------------------------------------------------------------------
# AND connector
# ------------------------------------------------------------------

class TestAND:
    def test_both_true(self, evaluator):
        r = evaluator.evaluate("os == linux AND runtime.python >= 3.10")
        assert r.passed is True

    def test_first_false(self, evaluator):
        r = evaluator.evaluate("os == windows AND runtime.python >= 3.10")
        assert r.passed is False

    def test_second_false(self, evaluator):
        r = evaluator.evaluate("os == linux AND runtime.python >= 4.0")
        assert r.passed is False

    def test_both_false(self, evaluator):
        r = evaluator.evaluate("os == windows AND runtime.python >= 4.0")
        assert r.passed is False


# ------------------------------------------------------------------
# OR connector
# ------------------------------------------------------------------

class TestOR:
    def test_both_true(self, evaluator):
        r = evaluator.evaluate("kind == skill OR kind == mcp-server")
        assert r.passed is True

    def test_first_true(self, evaluator):
        r = evaluator.evaluate("kind == skill OR kind == tool")
        assert r.passed is True

    def test_second_true(self, evaluator):
        r = evaluator.evaluate("kind == tool OR kind == skill")
        assert r.passed is True

    def test_both_false(self, evaluator):
        r = evaluator.evaluate("kind == tool OR kind == mcp-server")
        assert r.passed is False


# ------------------------------------------------------------------
# Multiple connectors
# ------------------------------------------------------------------

class TestMultipleConnectors:
    def test_three_and(self, evaluator):
        r = evaluator.evaluate("os == linux AND kind == skill AND runtime.python >= 3.10")
        assert r.passed is True

    def test_and_or_mixed(self, evaluator):
        # Left-to-right: (os==linux AND kind==tool) => False, OR kind==skill => True
        r = evaluator.evaluate("os == linux AND kind == tool OR kind == skill")
        assert r.passed is True


# ------------------------------------------------------------------
# Nested path resolution
# ------------------------------------------------------------------

class TestPathResolution:
    def test_nested_path(self, evaluator):
        r = evaluator.evaluate("runtime.python >= 3.0")
        assert r.passed is True

    def test_deeply_nested(self):
        ev = ConditionEvaluator({"a": {"b": {"c": "hello"}}})
        r = ev.evaluate("a.b.c == hello")
        assert r.passed is True

    def test_missing_intermediate(self, evaluator):
        r = evaluator.evaluate("runtime.ruby >= 3.0")
        assert r.passed is False
        assert "not found" in r.reason

    def test_top_level_missing(self, evaluator):
        r = evaluator.evaluate("arch == x86_64")
        assert r.passed is False
        assert "not found" in r.reason


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_expression(self, evaluator):
        r = evaluator.evaluate("")
        assert r.passed is False
        assert "empty expression" in r.reason

    def test_whitespace_only(self, evaluator):
        r = evaluator.evaluate("   ")
        assert r.passed is False
        assert "empty expression" in r.reason

    def test_invalid_operator(self, evaluator):
        r = evaluator.evaluate("os ~= linux")
        assert r.passed is False
        assert "invalid expression syntax" in r.reason

    def test_missing_value_for_comparison(self, evaluator):
        r = evaluator.evaluate("os ==")
        assert r.passed is False

    def test_no_context(self):
        ev = ConditionEvaluator()
        r = ev.evaluate("os == linux")
        assert r.passed is False
        assert "not found" in r.reason

    def test_empty_context(self):
        ev = ConditionEvaluator({})
        r = ev.evaluate("env.KEY exists")
        assert r.passed is False


# ------------------------------------------------------------------
# evaluate_all
# ------------------------------------------------------------------

class TestEvaluateAll:
    def test_all_pass(self, evaluator):
        results = evaluator.evaluate_all([
            "os == linux",
            "kind == skill",
            "runtime.python >= 3.10",
        ])
        assert all(r.passed for r in results)
        assert len(results) == 3

    def test_one_fails(self, evaluator):
        results = evaluator.evaluate_all([
            "os == linux",
            "kind == tool",
        ])
        assert results[0].passed is True
        assert results[1].passed is False

    def test_empty_list(self, evaluator):
        results = evaluator.evaluate_all([])
        assert results == []


# ------------------------------------------------------------------
# ConditionResult dataclass
# ------------------------------------------------------------------

class TestConditionResult:
    def test_defaults(self):
        r = ConditionResult(passed=True, expression="os == linux")
        assert r.passed is True
        assert r.expression == "os == linux"
        assert r.reason == ""

    def test_with_reason(self):
        r = ConditionResult(passed=False, expression="x == y", reason="mismatch")
        assert r.reason == "mismatch"


# ------------------------------------------------------------------
# Value with hyphens / special chars in comparison
# ------------------------------------------------------------------

class TestSpecialValues:
    def test_kind_mcp_server(self):
        ev = ConditionEvaluator({"kind": "mcp-server"})
        r = ev.evaluate("kind == mcp-server")
        assert r.passed is True

    def test_path_with_underscores(self):
        ev = ConditionEvaluator({"trust_state": "audited"})
        r = ev.evaluate("trust_state == audited")
        assert r.passed is True
