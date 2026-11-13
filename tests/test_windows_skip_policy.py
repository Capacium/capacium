"""WTS-001 — Windows skip policy enforcement.

Every skipif on win32 in the test tree must carry a reason that mentions
Windows. A skip without a reason or with a reason that does not mention
Windows is a policy violation.
"""

import ast
from pathlib import Path

import pytest


def _collect_win32_skips(root: Path):
    """Walk test files and collect every win32 skipif with its reason."""
    results = []
    for py_file in sorted(root.rglob("test_*.py")):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # pytest.mark.skipif(condition, reason=...)
            if not isinstance(node, ast.Call):
                continue
            # Direct skipif call
            is_skipif = False
            if isinstance(node.func, ast.Attribute) and node.func.attr == "skipif":
                is_skipif = True
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "mark"
                and node.func.attr == "skipif"
            ):
                is_skipif = True
            if not is_skipif:
                continue
            if not node.args:
                continue
            first_arg = ast.dump(node.args[0])
            if "win32" not in first_arg:
                continue
            # Extract the reason keyword
            reason = None
            for kw in node.keywords:
                if kw.arg == "reason":
                    if isinstance(kw.value, ast.Constant):
                        reason = kw.value.value
                    elif isinstance(kw.value, ast.JoinedStr):
                        reason = ast.literal_eval(kw.value)
                    break
            results.append((str(py_file), node.lineno, reason))
    return results


class TestWindowsSkipPolicy:
    """Every win32 skipif must have a reason that mentions Windows."""

    _REPO_ROOT = Path(__file__).resolve().parent.parent

    def test_no_win32_skipif_without_windows_reason(self):
        """All win32 skipif markers in the test tree must mention Windows."""
        violations = []
        for filepath, lineno, reason in _collect_win32_skips(self._REPO_ROOT / "tests"):
            if reason is None or reason == "":
                violations.append(f"{filepath}:{lineno}: skipif on win32 has no reason")
            elif "windows" not in reason.lower():
                violations.append(
                    f"{filepath}:{lineno}: skipif on win32 reason "
                    f"does not mention Windows: {reason!r}"
                )
        if violations:
            pytest.fail(
                f"{len(violations)} win32 skipif policy violation(s):\n"
                + "\n".join(violations)
            )

    def test_violating_fixture_is_red(self, tmp_path):
        """A fixture with a win32 skipif lacking a Windows reason is detected."""
        fixture = tmp_path / "test_fixture_violation.py"
        fixture.write_text("""import pytest
class TestViolation:
    @pytest.mark.skipif(sys.platform == "win32", reason="not applicable")
    def test_no_windows_mention(self):
        pass
""")
        violations = []
        for filepath, lineno, reason in _collect_win32_skips(tmp_path):
            if reason is None or reason == "":
                violations.append(f"{filepath}:{lineno}: no reason")
            elif "windows" not in reason.lower():
                violations.append(
                    f"{filepath}:{lineno}: reason does not mention Windows: {reason!r}"
                )
        assert len(violations) == 1
        assert "no_windows_mention" in str(violations[0]) or "not applicable" in str(violations[0])

    def test_violating_fixture_no_reason_is_red(self, tmp_path):
        """A fixture with a win32 skipif lacking any reason is detected."""
        fixture = tmp_path / "test_fixture_violation.py"
        fixture.write_text("""import pytest
class TestViolation:
    @pytest.mark.skipif(sys.platform == "win32")
    def test_no_reason(self):
        pass
""")
        violations = []
        for filepath, lineno, reason in _collect_win32_skips(tmp_path):
            if reason is None or reason == "":
                violations.append(f"{filepath}:{lineno}: no reason")
            elif "windows" not in reason.lower():
                violations.append(
                    f"{filepath}:{lineno}: reason does not mention Windows: {reason!r}"
                )
        assert len(violations) == 1
        assert "no_reason" in str(violations[0]) or "no reason" in str(violations[0]).lower()
