from pathlib import Path
from capacium.commands.publish import publish_capability


class TestPublish:
    def test_publish_stub_output(self, capsys, sample_capability_dir):
        result = publish_capability(sample_capability_dir)
        captured = capsys.readouterr()
        assert result is True
        assert "PUBLISH NOT IMPLEMENTED" in captured.out
        assert "test-cap" in captured.out
        assert "1.0.0" in captured.out

    def test_publish_nonexistent_path(self, tmp_path):
        bad_dir = tmp_path / "does-not-exist"
        result = publish_capability(bad_dir)
        assert result is False

    def test_publish_stub_with_extra_fields(self, tmp_path):
        cap_dir = tmp_path / "advanced-cap"
        cap_dir.mkdir(parents=True)
        (cap_dir / "capability.yaml").write_text("""\
kind: tool
name: advanced-cap
version: 2.1.0
description: Advanced test capability
owner: test-owner
frameworks:
  - opencode
dependencies:
  requests: ^2.28.0
""")

        result = publish_capability(cap_dir)
        assert result is True
