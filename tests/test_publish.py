"""Tests for cap publish command."""

import sys
import subprocess
from unittest import mock

from capacium.commands.publish import publish_capability
from capacium.registry_client import RegistryClientError


class TestPublish:
    def test_publish_rejects_nonexistent_tarball(self, tmp_path):
        bad_path = tmp_path / "does-not-exist.tar.gz"
        result = publish_capability(bad_path)
        assert result is False

    def test_publish_rejects_non_tarball(self, tmp_path):
        txt_file = tmp_path / "not-a-tarball.txt"
        txt_file.write_text("hello")
        result = publish_capability(txt_file)
        assert result is False

    def test_publish_tarball_without_manifest(self, tmp_path):
        import tarfile

        tarball = tmp_path / "empty.tar.gz"
        with tarfile.open(tarball, "w:gz"):
            pass
        result = publish_capability(tarball)
        assert result is False

    def test_publish_valid_tarball(self, tmp_path):
        import tarfile

        cap_yaml = tmp_path / "capability.yaml"
        cap_yaml.write_text("""\
kind: skill
name: test-cap
version: 1.0.0
description: A test skill
owner: test-owner
frameworks:
  - opencode
""")
        tarball = tmp_path / "test-owner-test-cap-1.0.0.tar.gz"
        with tarfile.open(tarball, "w:gz") as tar:
            tar.add(cap_yaml, arcname="capability.yaml")

        with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
            instance = mock_client.return_value
            instance.publish.return_value = {
                "canonical_name": "test-owner/test-cap",
                "kind": "skill",
                "trust_state": "discovered",
                "created": True,
            }
            result = publish_capability(tarball)
            assert result is True
            instance.publish.assert_called_once()

    def test_publish_conflict_409(self, tmp_path):
        import tarfile

        cap_yaml = tmp_path / "capability.yaml"
        cap_yaml.write_text("""\
kind: skill
name: test-cap
version: 1.0.0
owner: test-owner
""")
        tarball = tmp_path / "test-owner-test-cap-1.0.0.tar.gz"
        with tarfile.open(tarball, "w:gz") as tar:
            tar.add(cap_yaml, arcname="capability.yaml")

        with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
            instance = mock_client.return_value
            instance.publish.side_effect = RegistryClientError(
                "HTTP 409 from http://example.com/v2/publish: Capability already exists",
                status_code=409,
            )
            result = publish_capability(tarball)
            assert result is False

    def test_publish_unauthorized_401(self, tmp_path):
        import tarfile

        cap_yaml = tmp_path / "capability.yaml"
        cap_yaml.write_text("""\
kind: skill
name: test-cap
version: 1.0.0
owner: test-owner
""")
        tarball = tmp_path / "test-owner-test-cap-1.0.0.tar.gz"
        with tarfile.open(tarball, "w:gz") as tar:
            tar.add(cap_yaml, arcname="capability.yaml")

        with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
            instance = mock_client.return_value
            instance.publish.side_effect = RegistryClientError(
                "HTTP 401 from http://example.com/v2/publish: Unauthorized",
                status_code=401,
            )
            result = publish_capability(tarball)
            assert result is False

    def test_publish_package_path_is_required(self):
        result = subprocess.run(
            [sys.executable, "-m", "capacium.cli", "publish"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_publish_with_token_flag(self, tmp_path):
        import tarfile

        cap_yaml = tmp_path / "capability.yaml"
        cap_yaml.write_text("""\
kind: skill
name: test-cap
version: 1.0.0
owner: test-owner
""")
        tarball = tmp_path / "test-owner-test-cap-1.0.0.tar.gz"
        with tarfile.open(tarball, "w:gz") as tar:
            tar.add(cap_yaml, arcname="capability.yaml")

        with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
            instance = mock_client.return_value
            instance.publish.return_value = {
                "canonical_name": "test-owner/test-cap",
                "kind": "skill",
                "trust_state": "discovered",
                "created": True,
            }
            result = publish_capability(tarball, token="my-secret-token")
            assert result is True
            mock_client.assert_called_once_with(token="my-secret-token")
