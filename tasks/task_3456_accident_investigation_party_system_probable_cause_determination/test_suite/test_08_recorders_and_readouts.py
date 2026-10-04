"""Recorder packages and lab-bench readout sessions: system-field discipline,
lazy completion from the logical clock, recorder-state gating, forward-only
windows, and half-open bench overlap semantics (PRD §3.6, §2.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_recorder,
    create_recorder_payload,
    find_session,
    get_recorder,
    readout_session_payload,
    schedule_readout_session,
    set_clock,
    setup_launched_investigation,
    validate_error,
    validate_success,
)

RECORDER_CUSTODIAN = TEST_USERS["recorder_custodian_headers"]


class TestRecorderRegistration:
    def test_recorder_create_with_extra_system_fields_is_ignored_input(self, api):
        """PRD §3.6: "the package opens `SECURED` with an empty
        `readout_sessions` array." PRD §2.5: "`version` (integer): a
        system-managed integer that increments by one on every mutation of the
        resource" — client-supplied system fields are not part of the declared
        input and cannot steer the stored record.

        Design: Corner/entities/recorder_create_with_extra_system_fields_is_ignored_input
        """
        ctx = setup_launched_investigation()
        resp = api.create_recorder(
            create_recorder_payload(
                ctx["investigation"]["id"],
                recorder_type="CVR",
                condition="DAMAGED",
                status="RELEASED",
                version=99,
            ),
            RECORDER_CUSTODIAN,
        )
        recorder = validate_success(resp, expected_status=201)
        assert recorder["status"] == "SECURED"
        assert recorder["version"] == 1
        assert recorder["readout_sessions"] == []


class TestLazyReadoutCompletion:
    def test_lazy_readout_completion_never_bumps_version(self, api):
        """PRD §2.4: "A readout session becomes `COMPLETE` once the logical
        clock reaches its `window_end_utc`. A recorder package becomes
        `READOUT_COMPLETE` once at least one session exists on it and every
        session's `window_end_utc` has been reached." PRD §2.5: "`version`
        (integer): a system-managed integer that increments by one on every
        mutation of the resource" — lazy evaluation on read is not a mutation.

        Design: Corner/state_machines/lazy_readout_completion_never_bumps_version
        """
        ctx = setup_launched_investigation()
        recorder = create_recorder(
            ctx["investigation"]["id"], recorder_type="FDR", condition="INTACT"
        )
        recorder = schedule_readout_session(
            recorder["id"],
            bench_id="bench-3",
            window_start_utc="2026-09-02T10:00:00Z",
            window_end_utc="2026-09-02T12:00:00Z",
        )
        version_after_session = recorder["version"]
        assert recorder["status"] == "IN_READOUT"
        assert find_session(recorder)["status"] == "SCHEDULED"

        set_clock("2026-09-02T12:00:00Z")
        reread = get_recorder(recorder["id"])
        assert find_session(reread)["status"] == "COMPLETE"
        assert reread["status"] == "READOUT_COMPLETE"
        assert reread["version"] == version_after_session

    def test_session_on_completed_recorder_returns_recorder_state_invalid(self, api):
        """PRD §3.6: "The recorder itself must be `SECURED` or already
        `IN_READOUT` (`ERR_RECORDER_STATE_INVALID`)." PRD §2.4: lazy state
        changes resolve "on the next read or write of the affected resource".

        Design: Corner/errors/session_on_completed_recorder_returns_recorder_state_invalid
        """
        ctx = setup_launched_investigation()
        recorder = create_recorder(
            ctx["investigation"]["id"], recorder_type="FDR", condition="INTACT"
        )
        schedule_readout_session(
            recorder["id"],
            bench_id="bench-4",
            window_start_utc="2026-09-02T10:00:00Z",
            window_end_utc="2026-09-02T12:00:00Z",
        )
        set_clock("2026-09-02T12:00:00Z")

        resp = api.create_readout_session(
            recorder["id"],
            readout_session_payload("bench-4", "2026-09-03T10:00:00Z", "2026-09-03T12:00:00Z"),
            RECORDER_CUSTODIAN,
        )
        validate_error(resp, ApiErrorId.ERR_RECORDER_STATE_INVALID)

        reread = get_recorder(recorder["id"])
        assert reread["status"] == "READOUT_COMPLETE"
        assert len(reread["readout_sessions"]) == 1

    def test_session_window_in_past_returns_window_error(self, api):
        """PRD §3.6: "the start must lie strictly after the current logical
        clock (`ERR_WINDOW_IN_PAST`)".

        Design: Corner/errors/session_window_in_past_returns_window_error
        """
        ctx = setup_launched_investigation()
        recorder = create_recorder(
            ctx["investigation"]["id"], recorder_type="OTHER", condition="INTACT"
        )

        # The chain pinned the logical clock at 2026-09-01T00:00:00Z; a session
        # starting 2026-08-31 does not lie strictly after it.
        resp = api.create_readout_session(
            recorder["id"],
            readout_session_payload("bench-9", "2026-08-31T10:00:00Z", "2026-08-31T12:00:00Z"),
            RECORDER_CUSTODIAN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)

        reread = get_recorder(recorder["id"])
        assert reread["readout_sessions"] == []
        assert reread["status"] == "SECURED"


class TestBenchWindowOverlap:
    def test_bench_sessions_allow_touching_but_not_overlap(self, api):
        """PRD §3.6: "on the same bench, the new half-open window — covering
        its start instant up to but not including its end — must not overlap
        any other `SCHEDULED` session on that bench, though two sessions that
        merely touch, one starting exactly when the other ends, are permitted
        (`ERR_BENCH_WINDOW_CONFLICT`)". PRD §3.6: "The first session scheduled
        on a package moves it from `SECURED` to `IN_READOUT`".

        Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap_bench_half_open_sessions
        """
        ctx = setup_launched_investigation()
        recorder = create_recorder(
            ctx["investigation"]["id"], recorder_type="FDR", condition="DAMAGED"
        )

        first = schedule_readout_session(
            recorder["id"], "bench-7", "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z"
        )
        assert first["status"] == "IN_READOUT"

        # Touching the first window's end is allowed under half-open semantics.
        second = schedule_readout_session(
            recorder["id"], "bench-7", "2026-09-02T12:00:00Z", "2026-09-02T14:00:00Z"
        )
        assert len(second["readout_sessions"]) == 2

        resp = api.create_readout_session(
            recorder["id"],
            readout_session_payload("bench-7", "2026-09-02T11:30:00Z", "2026-09-02T13:00:00Z"),
            RECORDER_CUSTODIAN,
        )
        validate_error(resp, ApiErrorId.ERR_BENCH_WINDOW_CONFLICT)

        assert len(get_recorder(recorder["id"])["readout_sessions"]) == 2

    def test_bench_conflict_is_scoped_per_bench_id(self, api):
        """PRD §3.6: "on the same bench, the new half-open window — covering
        its start instant up to but not including its end — must not overlap
        any other `SCHEDULED` session on that bench" — the resource under
        contention is the bench, so an overlapping window on a different bench
        is permitted.

        Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap_bench_half_open_sessions
        """
        ctx = setup_launched_investigation()
        recorder = create_recorder(
            ctx["investigation"]["id"], recorder_type="CVR", condition="INTACT"
        )

        schedule_readout_session(
            recorder["id"], "bench-7", "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z"
        )
        # Same instants would conflict on bench-7; a different bench is free.
        other_bench = schedule_readout_session(
            recorder["id"], "bench-8", "2026-09-02T11:30:00Z", "2026-09-02T13:00:00Z"
        )
        assert len(other_bench["readout_sessions"]) == 2

        resp = api.create_readout_session(
            recorder["id"],
            readout_session_payload("bench-7", "2026-09-02T11:00:00Z", "2026-09-02T11:30:00Z"),
            RECORDER_CUSTODIAN,
        )
        validate_error(resp, ApiErrorId.ERR_BENCH_WINDOW_CONFLICT)
