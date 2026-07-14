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
        assert ok is True
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
        assert ok is True
        assert "Warning" in out or "warning" in out
        assert "entirely-different" in out  # raw response visible
        assert "unknown" not in out.replace("unknown response schema", "")
