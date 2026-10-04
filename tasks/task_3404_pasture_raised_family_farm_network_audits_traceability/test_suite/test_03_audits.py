"""Audit scheduling gap, completion window, expiry sweep, and error precedence."""
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_audit,
    create_farm,
    make_auditor_headers,
    schedule_audit,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

NM = TEST_USERS["network_manager_headers"]


def test_audit_minimum_gap_rejects_tighter_than_thirty_days(api):
    """PRD §3.2: "the new `scheduled_for` must be at least 30 days away from
    every non-`CANCELLED` audit of the same farm, in either direction; a tighter
    gap is rejected with `ERR_AUDIT_TOO_SOON` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/audit_minimum_gap_buffer_semantics
    """
    farm = create_farm(name="Gap Test Farm")
    farm_id = farm["id"]
    schedule_audit(farm_id, "INITIAL", "2026-09-03T00:00:00Z")

    # 2026-10-01 is 28 days after 2026-09-03 — inside the 30-day buffer.
    resp = api.schedule_audit(
        farm_id,
        {"audit_type": "FOR_CAUSE", "scheduled_for": "2026-10-01T00:00:00Z"},
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_TOO_SOON, 422)


def test_audit_minimum_gap_accepts_exactly_thirty_days(api):
    """PRD §3.2: "the new `scheduled_for` must be at least 30 days away from
    every non-`CANCELLED` audit of the same farm, in either direction; a tighter
    gap is rejected with `ERR_AUDIT_TOO_SOON` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/audit_minimum_gap_buffer_semantics
    """
    farm = create_farm(name="Gap Test Farm")
    farm_id = farm["id"]
    schedule_audit(farm_id, "INITIAL", "2026-09-03T00:00:00Z")

    # 2026-10-03 is exactly 30 days after 2026-09-03 — at-least semantics accept it.
    resp = api.schedule_audit(
        farm_id,
        {"audit_type": "FOR_CAUSE", "scheduled_for": "2026-10-03T00:00:00Z"},
        NM,
    )
    audit = validate_success(resp, 201)
    assert audit["status"] == "SCHEDULED"


def test_audit_complete_too_early_returns_window_missed(api):
    """PRD §3.2: "An audit has a completion window: it may be completed no
    earlier than 3 days before `scheduled_for` and no later than 7 days after
    it."
    PRD §3.2: "attempting completion before the early edge is rejected with
    `ERR_AUDIT_WINDOW_MISSED` (HTTP 422)"

    Design: Corner/state_machines/audit_complete_too_early_returns_window_missed
    """
    farm = create_farm(name="Early Bird Farm")
    farm_id = farm["id"]
    audit = schedule_audit(farm_id, "INITIAL", "2026-09-10T00:00:00Z")
    set_clock("2026-09-05T00:00:00Z")

    resp = api.complete_audit(audit["id"], {"outcome": "PASSED"},
                              make_auditor_headers("auditor-a"))
    validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_MISSED, 422)

    reread = validate_success(api.get_audit(audit["id"], NM), 200)
    assert reread["status"] == "SCHEDULED", "a rejected completion leaves the audit SCHEDULED"


def test_audit_expires_when_window_passes(api):
    """PRD §3.2: "When the clock sweep of §2.5 finds a `SCHEDULED` audit whose
    late edge has passed — the logical instant is strictly later than
    `scheduled_for` plus 7 days — the audit flips to `EXPIRED` without any
    auditor involvement."

    Design: Corner/state_machines/audit_expires_when_window_passes
    """
    farm = create_farm(name="Expiry Farm")
    farm_id = farm["id"]
    audit = schedule_audit(farm_id, "INITIAL", "2026-09-03T00:00:00Z")

    # At exactly scheduled_for + 7 days the audit is still SCHEDULED (strictly-greater).
    set_clock("2026-09-10T00:00:00Z")
    at_edge = validate_success(api.get_audit(audit["id"], NM), 200)
    assert at_edge["status"] == "SCHEDULED", (
        f"at exactly scheduled_for + 7 days the audit must still be SCHEDULED, "
        f"got {at_edge['status']}"
    )

    # Strictly past the late edge: EXPIRED.
    set_clock("2026-09-11T00:00:01Z")
    expired = validate_success(api.get_audit(audit["id"], NM), 200)
    assert expired["status"] == "EXPIRED"


def _setup_completed_annual_audit():
    """Farm with INITIAL passed 2026-09-03 and ANNUAL passed 2026-10-03; the
    clock is then advanced to 2026-11-01, outside the ANNUAL audit's window."""
    farm = create_farm(name="Oakhurst Pastures")
    farm_id = farm["id"]
    a1 = schedule_audit(farm_id, "INITIAL", "2026-09-03T00:00:00Z")
    set_clock("2026-09-03T09:00:00Z")
    complete_audit(a1["id"], "PASSED")
    a2 = schedule_audit(farm_id, "ANNUAL", "2026-10-03T00:00:00Z")
    set_clock("2026-10-03T09:00:00Z")
    complete_audit(a2["id"], "PASSED")
    set_clock("2026-11-01T00:00:00Z")
    return farm_id, a2["id"]


def test_audit_complete_state_error_beats_window_error(api):
    """PRD §2.11: "With a well-formed body in hand, state legality is checked:
    the target must be in a legal from-state for the requested transition"
    PRD §2.11: "Business rules then run in this sequence: certification gates
    first (`ERR_CERTIFICATION_REQUIRED`, `ERR_CERTIFICATION_NOT_CURRENT`), then
    covering-contract and forecast existence (`ERR_CONTRACT_REQUIRED`,
    `ERR_FORECAST_REQUIRED`), then temporal rules (`ERR_AUDIT_TOO_SOON`,
    `ERR_AUDIT_WINDOW_MISSED`, `ERR_STOP_DATE_CONFLICT`)"
    PRD §3.2: "Completion of an audit that is not currently `SCHEDULED` —
    already completed, `EXPIRED`, or `CANCELLED` — is rejected with
    `ERR_AUDIT_NOT_SCHEDULED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/audit_complete_state_error_beats_window_error
    """
    _, a2_id = _setup_completed_annual_audit()

    # The audit is already PASSED (state violation) AND the clock is outside
    # its completion window (temporal violation); the state error must win.
    resp = api.complete_audit(a2_id, {"outcome": "PASSED"},
                              make_auditor_headers("auditor-a"))
    validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_SCHEDULED, 409)


def test_audit_complete_rejection_leaves_audit_untouched(api):
    """PRD §3.2: "Completion of an audit that is not currently `SCHEDULED` —
    already completed, `EXPIRED`, or `CANCELLED` — is rejected with
    `ERR_AUDIT_NOT_SCHEDULED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/audit_complete_state_error_beats_window_error
    """
    _, a2_id = _setup_completed_annual_audit()

    resp = api.complete_audit(a2_id, {"outcome": "PASSED"},
                              make_auditor_headers("auditor-a"))
    validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_SCHEDULED, 409)

    reread = validate_success(api.get_audit(a2_id, NM), 200)
    assert reread["status"] == "PASSED", "the rejected second completion writes nothing"
