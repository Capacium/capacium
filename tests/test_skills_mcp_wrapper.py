from capacium.skills_mcp_wrapper import _discover_skills


def _write_capability(path, *, name, version, kind="skill"):
    path.mkdir(parents=True)
    (path / "capability.yaml").write_text(
        f"kind: {kind}\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"description: {name} {version}\n"
    )
    (path / "SKILL.md").write_text(f"# {name}\n")


def test_discover_skills_supports_versioned_package_layout(tmp_path):
    cap_home = tmp_path / "packages"
    _write_capability(
        cap_home / "LangeVC" / "skillweave-blueprint" / "1.1.0",
        name="skillweave-blueprint",
        version="1.1.0",
    )

    skills = _discover_skills(cap_home)

    assert [skill["name"] for skill in skills] == ["skillweave-blueprint"]
    assert skills[0]["version"] == "1.1.0"


def test_discover_skills_uses_latest_version_and_ignores_non_skills(tmp_path):
    cap_home = tmp_path / "packages"
    _write_capability(
        cap_home / "LangeVC" / "example" / "1.9.0",
        name="example",
        version="1.9.0",
    )
    _write_capability(
        cap_home / "LangeVC" / "example" / "1.10.0",
        name="example",
        version="1.10.0",
    )
    _write_capability(
        cap_home / "LangeVC" / "server" / "2.0.0",
        name="server",
        version="2.0.0",
        kind="mcp-server",
    )

    skills = _discover_skills(cap_home)

    assert len(skills) == 1
    assert skills[0]["name"] == "example"
    assert skills[0]["version"] == "1.10.0"
