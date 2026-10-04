"""Run window overlap (half-open), the graphics changeover buffer, and the
safety-vs-temporal gate ordering (PRD §2.7, §3.4, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_run_env, setup_in_progress_run, create_run, create_incident,
    get_agreement_version, scheduler, manager, engineer, api_client,
)


def _run_body(env, start, end, qty=5000, graphics="G1"):
    return {"line_id": env["line"]["id"], "format_id": env["format"]["id"],
            "scheduled_qty": qty, "graphics_code": graphics,
            "window_start": start, "window_end": end,
            "expected_agreement_version": get_agreement_version(
                env["agreement"]["id"])}


class TestHalfOpenWindows:
    def test_line_run_windows_touching_is_allowed(self, api):
        """PRD §3.4: "windows are half-open, so a run whose `window_start`
        coincides exactly with another run's `window_end` touches without
        overlapping and is allowed".

        Design: Difficulty/resource_temporal_overlap/line_run_windows_half_open_touching_allowed
        """
        env = setup_run_env()
        create_run(env["agreement"]["id"], env["line"]["id"], env["format"]["id"],
                   window_start="2026-09-10T08:00:00Z",
                   window_end="2026-09-10T16:00:00Z")
        touching = validate_success(api.create_run(
            env["agreement"]["id"],
            _run_body(env, "2026-09-10T16:00:00Z", "2026-09-10T23:00:00Z"),
            scheduler()), 201)
        assert touching["status"] == "SCHEDULED"

    def test_line_run_windows_one_second_overlap_rejected(self, api):
        """PRD §3.4: "any true intersection is rejected with
        `ERR_LINE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/line_run_windows_half_open_touching_allowed
        """
        env = setup_run_env()
        create_run(env["agreement"]["id"], env["line"]["id"], env["format"]["id"],
                   window_start="2026-09-10T08:00:00Z",
                   window_end="2026-09-10T16:00:00Z")
        create_run(env["agreement"]["id"], env["line"]["id"], env["format"]["id"],
                   window_start="2026-09-10T16:00:00Z",
                   window_end="2026-09-10T23:00:00Z")
        resp = api.create_run(env["agreement"]["id"],
                              _run_body(env, "2026-09-10T15:59:59Z",
                                        "2026-09-10T23:00:00Z"), scheduler())
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_OVERLAP)
        rows, _ = validate_paginated(api.list_runs(
            manager(), params={"line_id": env["line"]["id"],
                               "status": "SCHEDULED"}))
        assert len(rows) == 2


class TestChangeoverBuffer:
    def test_changeover_buffer_violation_positive_trigger(self, api):
        """PRD §3.4: "when the previous run on the same line ... carried a
        different `graphics_code`, at least 240 minutes (four hours) must
        separate that run's `window_end` from the new run's `window_start`,
        otherwise the create is rejected with
        `ERR_CHANGEOVER_BUFFER_VIOLATION`."

        Design: Corner/errors/changeover_buffer_violation_positive_trigger
        """
        env = setup_run_env()
        create_run(env["agreement"]["id"], env["line"]["id"], env["format"]["id"],
                   graphics_code="SUMMER",
                   window_start="2026-09-10T08:00:00Z",
                   window_end="2026-09-10T16:00:00Z")
        # 239-minute gap with a graphics change: rejected.
        resp = api.create_run(env["agreement"]["id"],
                              _run_body(env, "2026-09-10T19:59:00Z",
                                        "2026-09-10T23:00:00Z",
                                        graphics="OKTOBERFEST"), scheduler())
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_BUFFER_VIOLATION)
        # Exactly 240 minutes: accepted.
        ok = validate_success(api.create_run(
            env["agreement"]["id"],
            _run_body(env, "2026-09-10T20:00:00Z", "2026-09-10T23:00:00Z",
                      graphics="OKTOBERFEST"), scheduler()), 201)
        assert ok["status"] == "SCHEDULED"


class TestSafetyBeatsTemporal:
    def _held_line_env(self, api):
        """R0 IN_PROGRESS then HELD via an escalated incident -> line HOLD."""
        env = setup_in_progress_run(
            run_overrides={"scheduled_qty": 100000, "graphics_code": "G1"})
        incident = create_incident(env["run"]["id"], severity="MAJOR",
                                   defect_class="COATING",
                                   note="coating holiday")
        validate_success(api.escalate_incident(incident["id"], engineer()))
        return env

    def test_create_on_held_line_safety_beats_changeover_buffer(self, api):
        """PRD §2.7: gate "7. **Safety gates** — a line in `QUALITY_HOLD` blocks
        run creation and run start (`ERR_LINE_QUALITY_HOLD`, HTTP 409)" precedes
        gate "8. **Temporal conflicts** — ... the graphics changeover buffer
        (`ERR_CHANGEOVER_BUFFER_VIOLATION`)".

        Design: Difficulty/priority_pair_validation_conflict/create_on_held_line_safety_beats_changeover_buffer
        """
        env = self._held_line_env(api)
        resp = api.create_run(
            env["agreement"]["id"],
            _run_body(env, "2026-09-10T18:00:00Z", "2026-09-10T23:00:00Z",
                      graphics="G2"), scheduler())
        err = validate_error(resp, ApiErrorId.ERR_LINE_QUALITY_HOLD, 409)
        assert err["error_id"] != ApiErrorId.ERR_CHANGEOVER_BUFFER_VIOLATION

    def test_create_on_held_line_persists_nothing(self, api):
        """PRD §3.9: "the run's line enters `QUALITY_HOLD`, which blocks new run
        creation and run starts on that line with `ERR_LINE_QUALITY_HOLD`".

        Design: Difficulty/priority_pair_validation_conflict/create_on_held_line_safety_beats_changeover_buffer
        """
        env = self._held_line_env(api)
        api.create_run(env["agreement"]["id"],
                       _run_body(env, "2026-09-10T18:00:00Z",
                                 "2026-09-10T23:00:00Z", graphics="G2"),
                       scheduler())
        rows, _ = validate_paginated(api.list_runs(
            manager(), params={"agreement_id": env["agreement"]["id"]}))
        assert len(rows) == 1, "only the original run exists"
