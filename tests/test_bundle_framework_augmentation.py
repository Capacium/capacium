"""Regression coverage for adding a framework to an installed bundle."""

from pathlib import Path


def _write_bundle(root: Path) -> Path:
    bundle_dir = root / "toolkit"
    skills_dir = bundle_dir / "skills"
    for name in ("toolkit-plan", "toolkit-review"):
        skill_dir = skills_dir / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "capability.yaml").write_text(
            f"""\
kind: skill
name: {name}
version: 1.0.0
description: {name} test skill
frameworks:
- opencode
"""
        )
        (skill_dir / "SKILL.md").write_text(f"# {name}\n")

    (bundle_dir / "capability.yaml").write_text(
        """\
kind: bundle
name: toolkit
version: 1.0.0
description: Toolkit test bundle
frameworks:
- opencode
- qwen
- cursor
capabilities:
- name: toolkit-plan
  source: ./skills/toolkit-plan
  version: 1.0.0
- name: toolkit-review
  source: ./skills/toolkit-review
  version: 1.0.0
"""
    )
    return bundle_dir


def test_installed_bundle_adds_new_project_framework_to_every_member(
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from capacium.commands.install import install_capability
    from capacium.registry import Registry

    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
    bundle_dir = _write_bundle(tmp_path)

    assert install_capability(
        "test/toolkit@1.0.0",
        source_dir=bundle_dir,
        no_lock=True,
        framework="opencode",
    )

    opencode_skills = tmp_home / ".opencode" / "skills"
    assert (opencode_skills / "toolkit-plan").is_symlink()
    assert (opencode_skills / "toolkit-review").is_symlink()

    registry = Registry()
    for name in ("toolkit-plan", "toolkit-review"):
        member = registry.get_capability(f"test/{name}", "1.0.0")
        assert member is not None
        assert member.frameworks == ["opencode"]
        assert "cursor" not in registry.get_adapter_statuses(
            f"test/{name}", "1.0.0"
        )

    assert install_capability(
        "test/toolkit",
        no_lock=True,
        offline=True,
        framework="qwen",
    )
    qwen_skills = tmp_home / ".qwen" / "skills"
    assert (qwen_skills / "toolkit-plan").is_symlink()
    assert (qwen_skills / "toolkit-review").is_symlink()
    assert not (qwen_skills / "toolkit").exists()
    for name in ("toolkit-plan", "toolkit-review"):
        member = registry.get_capability(f"test/{name}", "1.0.0")
        assert member is not None
        assert "qwen" in member.frameworks
        assert registry.get_adapter_statuses(f"test/{name}", "1.0.0")[
            "qwen"
        ].status == "installed"

    project_root = tmp_path / "cursor-project"
    assert install_capability(
        "test/toolkit",
        no_lock=True,
        offline=True,
        framework="cursor",
        project=str(project_root),
    )

    cursor_skills = project_root / ".cursor" / "skills"
    member_links = {
        path.name: path.resolve()
        for path in cursor_skills.iterdir()
        if path.is_symlink()
    }
    assert set(member_links) == {"toolkit-plan", "toolkit-review"}
    assert not (cursor_skills / "toolkit").exists()

    for name, target in member_links.items():
        member = registry.get_capability(f"test/{name}", "1.0.0")
        assert member is not None
        assert target == member.install_path.resolve()
        assert "cursor" in member.frameworks
        assert registry.get_adapter_statuses(f"test/{name}", "1.0.0")[
            "cursor"
        ].status == "installed"

    bundle = registry.get_capability("test/toolkit", "1.0.0")
    assert bundle is not None
    assert "cursor" in bundle.frameworks

    assert install_capability(
        "test/toolkit",
        no_lock=True,
        offline=True,
        framework="cursor",
        project=str(project_root),
    )
    repeated_links = {
        path.name: path.resolve()
        for path in cursor_skills.iterdir()
        if path.is_symlink()
    }
    assert repeated_links == member_links
    assert (opencode_skills / "toolkit-plan").is_symlink()
    assert (opencode_skills / "toolkit-review").is_symlink()
    assert (qwen_skills / "toolkit-plan").is_symlink()
    assert (qwen_skills / "toolkit-review").is_symlink()
