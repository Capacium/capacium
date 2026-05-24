from capacium.manifest import Manifest, parse_cap_id, format_cap_id


class TestManifest:
    def test_detect_from_directory_yaml(self, sample_capability_dir):
        manifest = Manifest.detect_from_directory(sample_capability_dir)
        assert manifest.name == "test-cap"
        assert manifest.version == "1.0.0"
        assert manifest.kind == "skill"
        assert manifest.author == "Test Author"

    def test_detect_from_directory_bundle(self, sample_bundle_dir):
        manifest = Manifest.detect_from_directory(sample_bundle_dir)
        assert manifest.name == "test-bundle"
        assert manifest.version == "2.0.0"
        assert manifest.kind == "bundle"
        assert len(manifest.capabilities) == 1
        assert manifest.capabilities[0]["name"] == "sub-cap"

    def test_detect_from_directory_json(self, tmp_path):
        cap_dir = tmp_path / "json-cap"
        cap_dir.mkdir()
        (cap_dir / "capability.json").write_text('{"kind": "tool", "name": "json-cap", "version": "3.0.0"}')
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.name == "json-cap"
        assert manifest.kind == "tool"
        assert manifest.version == "3.0.0"

    def test_detect_from_directory_legacy_skillpkg(self, tmp_path):
        cap_dir = tmp_path / "legacy-cap"
        cap_dir.mkdir()
        (cap_dir / ".skillpkg.json").write_text('{"name": "legacy-cap", "version": "0.5.0"}')
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.name == "legacy-cap"
        assert manifest.version == "0.5.0"

    def test_detect_from_directory_fallback(self, tmp_path):
        cap_dir = tmp_path / "fallback-cap"
        cap_dir.mkdir()
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.name == "fallback-cap"
        assert manifest.owner == "unknown"

    def test_id_property(self):
        m = Manifest(owner="alice", name="my-cap", version="1.0.0")
        assert m.id == "alice/my-cap"

    def test_id_global_fallback(self):
        m = Manifest(name="no-owner", version="1.0.0")
        assert m.id == "global/no-owner"

    def test_save_and_load_yaml(self, tmp_path):
        m = Manifest(kind="bundle", name="bundle-test", version="0.1.0", author="Tester",
                      dependencies={"dep-a": "^1.0"}, capabilities=[{"name": "sub", "source": "./sub"}])
        path = tmp_path / "capability.yaml"
        m.save(path)
        loaded = Manifest.load(path)
        assert loaded.name == "bundle-test"
        assert loaded.kind == "bundle"
        assert loaded.dependencies == {"dep-a": "^1.0"}
        assert loaded.capabilities == [{"name": "sub", "source": "./sub"}]

    def test_save_and_load_json(self, tmp_path):
        m = Manifest(kind="tool", name="tool-test", version="0.2.0")
        path = tmp_path / "capability.json"
        m.save(path)
        loaded = Manifest.load(path)
        assert loaded.name == "tool-test"
        assert loaded.kind == "tool"


class TestParseCapId:
    def test_with_owner(self):
        assert parse_cap_id("alice/my-cap") == ("alice", "my-cap")

    def test_without_owner(self):
        assert parse_cap_id("my-cap") == ("global", "my-cap")


class TestTriggers:
    def test_triggers_from_dict(self):
        data = {
            "name": "trigger-cap",
            "version": "1.0.0",
            "kind": "skill",
            "triggers": [
                {"event": "file-changed", "pattern": "*.py", "action": "run-linter"},
            ],
        }
        m = Manifest.from_dict(data)
        assert len(m.triggers) == 1
        assert m.triggers[0]["event"] == "file-changed"
        assert m.triggers[0]["action"] == "run-linter"

    def test_triggers_valid(self):
        m = Manifest(
            name="t",
            triggers=[
                {"event": "schedule", "action": "daily-check"},
                {"event": "on-install", "action": "setup"},
            ],
        )
        assert m.validate() == []

    def test_triggers_missing_event(self):
        m = Manifest(name="t", triggers=[{"action": "run"}])
        errors = m.validate()
        assert any("missing required 'event'" in e for e in errors)

    def test_triggers_missing_action(self):
        m = Manifest(name="t", triggers=[{"event": "manual"}])
        errors = m.validate()
        assert any("missing required 'action'" in e for e in errors)

    def test_triggers_invalid_event(self):
        m = Manifest(name="t", triggers=[{"event": "invalid-event", "action": "run"}])
        errors = m.validate()
        assert any("invalid event 'invalid-event'" in e for e in errors)

    def test_triggers_all_valid_events(self):
        valid_events = ["file-changed", "schedule", "webhook", "manual", "on-install", "on-update"]
        for event in valid_events:
            m = Manifest(name="t", triggers=[{"event": event, "action": "do-stuff"}])
            assert m.validate() == [], f"Event '{event}' should be valid"

    def test_triggers_empty_list_is_valid(self):
        m = Manifest(name="t", triggers=[])
        assert m.validate() == []

    def test_triggers_roundtrip_yaml(self, tmp_path):
        m = Manifest(
            name="trigger-rt",
            version="1.0.0",
            triggers=[{"event": "webhook", "action": "notify", "pattern": "/api/*"}],
        )
        path = tmp_path / "capability.yaml"
        m.save(path)
        loaded = Manifest.load(path)
        assert loaded.triggers == m.triggers


class TestFormatCapId:
    def test_format(self):
        assert format_cap_id("alice", "my-cap") == "alice/my-cap"
