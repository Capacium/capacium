"""STAB-008 (V12): cap submit response parsing.

The Exchange /v2/submit endpoint is queue-based: it returns 202 with
{job_id, github_url, canonical_hint, status} and the result must be polled
via GET /v2/submit/{job_id}. The old CLI expected a synchronous schema
(canonical_name/kind/trust_state) and printed 'unknown' for everything
(lum1104 case, 2026-06-11).
"""


from capacium.commands.submit import submit_repository


# Recorded real-world shapes (lum1104/understand-anything, 2026-06-11):
QUEUE_ACCEPT_RESPONSE = {
    "job_id": "5a1d6c9e-1111-2222-3333-444455556666",
    "github_url": "https://github.com/Lum1104/Understand-Anything",
    "canonical_hint": "Lum1104/Understand-Anything",
    "status": "pending",
}

JOB_COMPLETED = {
    "github_url": "https://github.com/Lum1104/Understand-Anything",
    "status": "completed",
    "created_at": "2026-06-11T14:02:11.000000",
    "canonical_name": "lum1104/understand-anything",
    "error": None,
}

LISTING_DETAIL = {
    "canonical_name": "lum1104/understand-anything",
    "kind": "skill",
    "trust_state": "pending_review",
    "license": "MIT",
}


class FakeClient:
    def __init__(self, submit_response, job_states=None, detail=None,
                 detail_error=None):
        self._submit_response = submit_response
        self._job_states = list(job_states or [])
        self._detail = detail
        self._detail_error = detail_error
        self.submit_calls = []
        self.status_calls = []

    def submit(self, github_url, registry_url=None):
        self.submit_calls.append(github_url)
        return self._submit_response

    def submit_status(self, job_id, registry_url=None):
        self.status_calls.append(job_id)
        if self._job_states:
            return self._job_states.pop(0)
        return {"status": "processing"}

    def get_detail(self, name, registry_url=None):
        if self._detail_error:
            raise self._detail_error
        return self._detail or {}


class TestQueueResponse:
    def test_lum1104_recorded_response_shows_real_values(self, capsys):
        client = FakeClient(
            QUEUE_ACCEPT_RESPONSE,
            job_states=[{"status": "processing"}, JOB_COMPLETED],
            detail=LISTING_DETAIL,
        )
        ok = submit_repository(
            "https://github.com/Lum1104/Understand-Anything",
            client=client, poll_interval=0,
        )
        out = capsys.readouterr().out
        assert ok is True
        assert "lum1104/understand-anything" in out
        assert "skill" in out
        assert "pending_review" in out
        assert "https://capacium.xyz/listings/lum1104/understand-anything" in out
        assert "unknown" not in out

    def test_failed_job_shows_error(self, capsys):
        client = FakeClient(
            QUEUE_ACCEPT_RESPONSE,
            job_states=[{
                "status": "failed",
                "error": "No capability.yaml or SKILL.md with YAML frontmatter found",
            }],
        )
        ok = submit_repository("https://github.com/x/y", client=client,
                               poll_interval=0)
        out = capsys.readouterr().out
        assert ok is False
        assert "No capability.yaml" in out

    def test_timeout_reports_job_id_for_later(self, capsys):
        client = FakeClient(QUEUE_ACCEPT_RESPONSE, job_states=[])
        ok = submit_repository("https://github.com/x/y", client=client,
                               poll_interval=0, wait_timeout=0.01)
        out = capsys.readouterr().out
        assert ok is False
        assert QUEUE_ACCEPT_RESPONSE["job_id"] in out

    def test_detail_lookup_failure_degrades_gracefully(self, capsys):
        client = FakeClient(
            QUEUE_ACCEPT_RESPONSE,
            job_states=[JOB_COMPLETED],
            detail_error=RuntimeError("listing endpoint down"),
        )
        ok = submit_repository("https://github.com/x/y", client=client,
                               poll_interval=0)
        out = capsys.readouterr().out
        assert ok is True
        assert "lum1104/understand-anything" in out


class TestLegacyAndDriftSchemas:
    def test_legacy_sync_schema_still_parses(self, capsys):
        client = FakeClient({
            "canonical_name": "acme/old-cap",
            "kind": "tool",
            "trust_state": "verified",
        })
        ok = submit_repository("https://github.com/acme/old-cap", client=client)
        out = capsys.readouterr().out
        assert ok is True
        assert "acme/old-cap" in out
        assert "tool" in out
        assert "verified" in out

    def test_unknown_schema_shows_raw_response_with_warning(self, capsys):
        drifted = {"result": {"something": "entirely-different"}, "v": 3}
        client = FakeClient(drifted)
        ok = submit_repository("https://github.com/x/y", client=client)
        out = capsys.readouterr().out
        assert ok is False
        assert "Warning" in out or "warning" in out
        assert "entirely-different" in out  # raw response visible
        assert "unknown" not in out.replace("unknown response schema", "")


class TestUnconfirmedOutcomesReportFailure:
    """A listing that was never confirmed is not a published listing.

    Three paths previously returned True exactly when the client does not
    know what happened: a non-dict response, a dict without a job_id, and a
    poll still processing at the deadline. Each must report a failure instead
    so that `cap submit` never exits 0 for an unconfirmed listing.
    """

    def test_non_dict_response_is_failure(self, capsys):
        client = FakeClient(["literal", "string", "not", "a", "dict"])
        ok = submit_repository("https://github.com/x/y", client=client)
        out = capsys.readouterr().out
        assert ok is False, "unrecognised (non-dict) response must not count as success"
        assert "Warning" in out or "warning" in out  # diagnostics preserved

    def test_missing_job_id_is_failure(self, capsys):
        client = FakeClient({"no_job_id": "here", "status": "pending"})
        ok = submit_repository("https://github.com/x/y", client=client)
        assert ok is False, "response without job_id is unconfirmed and must fail"

    def test_still_processing_at_deadline_is_failure(self, capsys):
        client = FakeClient(QUEUE_ACCEPT_RESPONSE, job_states=[])
        ok = submit_repository("https://github.com/x/y", client=client,
                               poll_interval=0, wait_timeout=0.01)
        out = capsys.readouterr().out
        assert ok is False, "submission still queued at deadline is not a success"
        assert QUEUE_ACCEPT_RESPONSE["job_id"] in out  # still tells how to check later


class TestSubmitUrlEndToEnd:
    """Drive the real RegistryClient the way submit.py does — bare
    RegistryClient(), configured registry URL — and assert the request goes to
    <base>/v2/submit exactly once, with no doubled /v2, covering both config
    keys the code reads."""

    def _run_submit_via_real_client(self, config_text, monkeypatch, capsys):
        import json as _json
        from pathlib import Path as _P
        from unittest.mock import patch

        cdir = _P.home() / ".capacium"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "config.yaml").write_text(config_text)

        captured_urls = []

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            body = _json.dumps(QUEUE_ACCEPT_RESPONSE).encode("utf-8")

            class Resp:
                status = 202
                @staticmethod
                def read():
                    return body
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    pass

            return Resp()

        from capacium.commands.submit import submit_repository
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok = submit_repository("https://github.com/x/y",
                                   poll_interval=0.001, wait_timeout=0.01)
        return ok, captured_urls

    def test_registry_key_routes_to_base_v2_submit_once(self, monkeypatch, capsys):
        ok, urls = self._run_submit_via_real_client(
            "registry: https://api.capacium.xyz\n", monkeypatch, capsys)
        assert ok is False  # queued, never polled to completion -> failure
        submit_urls = [u for u in urls if u == "https://api.capacium.xyz/v2/submit"]
        assert len(submit_urls) == 1, f"expected exactly one submit POST, got {urls}"
        assert urls[0] == "https://api.capacium.xyz/v2/submit", urls[0]

    def test_registry_url_key_routes_to_base_v2_submit_once(self, monkeypatch, capsys):
        ok, urls = self._run_submit_via_real_client(
            "registry_url: https://api.capacium.xyz\n", monkeypatch, capsys)
        submit_urls = [u for u in urls if u == "https://api.capacium.xyz/v2/submit"]
        assert len(submit_urls) == 1, f"expected exactly one submit POST, got {urls}"
        assert urls[0] == "https://api.capacium.xyz/v2/submit", urls[0]

    def test_base_ending_in_v2_does_not_double(self, monkeypatch, capsys):
        ok, urls = self._run_submit_via_real_client(
            "registry: https://api.capacium.xyz/v2\n", monkeypatch, capsys)
        assert urls[0] == "https://api.capacium.xyz/v2/submit", urls[0]
        assert "/v2/v2/" not in urls[0], f"doubled segment: {urls[0]}"
