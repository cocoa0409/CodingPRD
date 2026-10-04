"""Compliance monitoring: window derivation, period contiguity and start
gates, finding validation, the period cap, breach escalation, the cure path,
and the final close-out cascade.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    MONITORING_PERIOD_ENDS,
    api_client,
    certify_disbursement,
    create_finding_payload,
    deposit_funds,
    file_finding,
    get_allocation_line,
    get_investigation,
    get_settlement,
    open_monitoring_period,
    release_disbursement,
    request_disbursement,
    run_compliant_period,
    set_clock,
    setup_all_periods_compliant_world,
    setup_executed_world,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
MONITOR = TEST_USERS["compliance_monitor_headers"]


def _same_instant(actual: str, expected: str) -> bool:
    return datetime.fromisoformat(actual.replace("Z", "+00:00")) == (
        datetime.fromisoformat(expected.replace("Z", "+00:00"))
    )


def test_monitoring_window_derived_from_executed_at():
    """PRD section 3.7: "Each period carries a 1-based `period_index` ... and
    a half-open window from `window_start` (inclusive) to `window_end`
    (exclusive), each exactly 180 days long: the first period's `window_start`
    is the settlement's `executed_at`, and each later period's `window_start`
    is exactly the previous period's `window_end`."
    PRD section 3.7: "A new period opens in `OPEN` status."

    Design: Corner/calculations/monitoring_window_derived_from_executed_at
    """
    world = setup_executed_world()
    period = open_monitoring_period(world["settlement"]["id"])
    assert period["period_index"] == 1
    assert _same_instant(period["window_start"], CLOCK_DEFAULT), (
        "period 1 window_start is the settlement's executed_at"
    )
    assert _same_instant(period["window_end"], "2027-02-28T00:00:00Z"), (
        "window_end is window_start plus exactly 180 days"
    )
    assert period["status"] == "OPEN"
    assert period["findings"] == []


def test_monitoring_period_contiguity_and_start_enforced():
    """PRD section 3.7: "Opening the next period while its predecessor is
    still `OPEN`, or any arrangement that would gap or overlap the previous
    window, is rejected with `ERR_PERIOD_NOT_CONTIGUOUS` (HTTP 409), and
    opening a period before its `window_start` has been reached is rejected
    with `ERR_PERIOD_NOT_STARTED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/monitoring_period_contiguity_and_start_enforced
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    period = open_monitoring_period(stl_id)
    resp_overlap = api_client.create_monitoring_period(stl_id, CHAIR)
    validate_error(resp_overlap, ApiErrorId.ERR_PERIOD_NOT_CONTIGUOUS)
    # Close period 1 by covering every injunctive term; the clock is still
    # 2026-09-01, far before period 2's window_start of 2027-02-28.
    for term_index in range(3):
        period = file_finding(period["id"], term_index, "COMPLIANT")
    assert period["status"] == "CLOSED_COMPLIANT"
    resp_early = api_client.create_monitoring_period(stl_id, CHAIR)
    validate_error(resp_early, ApiErrorId.ERR_PERIOD_NOT_STARTED)


def test_invalid_term_index_rejected():
    """PRD section 3.7: "A filing names a `term_index` that must index into
    the settlement's `injunctive_terms` array — an out-of-range index is
    rejected with `ERR_INVALID_TERM_INDEX` (HTTP 422)."
    PRD section 3.7: "At most one finding may exist per injunctive term per
    period: a second filing for the same `term_index` in the same period is
    rejected with `ERR_DUPLICATE_FINDING` (HTTP 409)."

    Design: Corner/errors/invalid_term_index_rejected
    """
    world = setup_executed_world()
    period = open_monitoring_period(world["settlement"]["id"])
    file_finding(period["id"], 0, "COMPLIANT")
    resp_range = api_client.file_finding(
        period["id"], create_finding_payload(5, "BREACH"), MONITOR,
    )
    validate_error(resp_range, ApiErrorId.ERR_INVALID_TERM_INDEX)
    resp_dupe = api_client.file_finding(
        period["id"], create_finding_payload(0, "BREACH"), MONITOR,
    )
    validate_error(resp_dupe, ApiErrorId.ERR_DUPLICATE_FINDING)


def test_finding_on_closed_period_returns_invalid_state():
    """PRD section 3.7: "A period closes itself the moment every injunctive
    term has a finding, stamping `closed_at` and counting its `breach_count`."
    PRD section 2.8: "the target resource's own state machine must admit the
    trigger (`ERR_INVALID_STATE`, ...)."

    Design: Corner/state_machines/finding_on_closed_period_returns_invalid_state
    """
    world = setup_executed_world()
    period = open_monitoring_period(world["settlement"]["id"])
    for term_index in range(3):
        period = file_finding(period["id"], term_index, "COMPLIANT")
    assert period["status"] == "CLOSED_COMPLIANT"
    resp = api_client.file_finding(
        period["id"], create_finding_payload(0, "BREACH"), MONITOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_period_limit_reached():
    """PRD section 3.7: "Each period carries a 1-based `period_index` that may
    not exceed 6 — opening a seventh is rejected with
    `ERR_PERIOD_LIMIT_REACHED` (HTTP 422)."

    Design: Corner/errors/period_limit_reached
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    for period_index in range(1, 7):
        run_compliant_period(world, period_index)
    # Move the clock to period 7's window_start so the temporal gates pass
    # and only the period cap can fire.
    set_clock(MONITORING_PERIOD_ENDS[5])
    resp = api_client.create_monitoring_period(stl_id, CHAIR)
    validate_error(resp, ApiErrorId.ERR_PERIOD_LIMIT_REACHED)
    periods, meta = validate_paginated(
        api_client.list_settlement_monitoring_periods(stl_id, CHAIR)
    )
    assert meta["total_count"] == 6
    assert all(p["status"] == "CLOSED_COMPLIANT" for p in periods)


def test_breach_finding_cascade_holds_certified_disbursement():
    """PRD section 3.7: "If `breach_count` is at least 2, the period closes
    `CLOSED_BREACH` and escalates: the settlement's `compliance_hold` is set
    true, and every `CERTIFIED` disbursement on the settlement's lines moves
    to `HELD`, freezing money in place until the defendant cures."
    PRD section 3.7: "A period closes itself the moment every injunctive term
    has a finding."

    Design: Difficulty/transitive_cascade/breach_finding_cascade_holds_certified_disbursement
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    ny_line = {l["state_code"]: l for l in world["lines"]}["NY"]
    deposit_funds(stl_id, 10000000)
    disb = request_disbursement(
        ny_line, world["offices"]["NY"], False,
        amount_cents=5000000, use_code="PROGRAM",
    )
    disb = certify_disbursement(disb["id"], world["offices"]["NY"])
    assert disb["status"] == "CERTIFIED"
    period = open_monitoring_period(stl_id)
    file_finding(period["id"], 0, "BREACH", note="marketing violation")
    file_finding(period["id"], 1, "BREACH", note="audit skipped")
    # The third finding completes term coverage and auto-closes the period.
    period = file_finding(period["id"], 2, "COMPLIANT")
    assert period["status"] == "CLOSED_BREACH"
    assert period["breach_count"] == 2
    settlement = get_settlement(stl_id)
    assert settlement["compliance_hold"] is True
    disbs, _ = validate_paginated(
        api_client.list_allocation_line_disbursements(ny_line["id"], CHAIR)
    )
    assert disbs[0]["id"] == disb["id"]
    assert disbs[0]["status"] == "HELD", (
        "the escalated close freezes the previously CERTIFIED disbursement"
    )


def test_cure_cascade_restores_held_disbursements():
    """PRD section 3.7: "If `breach_count` is exactly zero, the period closes
    `CLOSED_COMPLIANT`, and when the settlement's hold had been raised by an
    earlier breach, the close cures it: `compliance_hold` returns to false and
    every `HELD` disbursement returns to `CERTIFIED`."
    PRD section 3.5: "A `FundAdministrator` releases a disbursement only from
    `CERTIFIED` (else `ERR_INVALID_STATE`), only while the settlement's
    `compliance_hold` is false (else `ERR_COMPLIANCE_HOLD_ACTIVE`)."

    Design: Corner/complexity_layers/cure_cascade_restores_held_disbursements
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    ny_line = {l["state_code"]: l for l in world["lines"]}["NY"]
    deposit_funds(stl_id, 10000000)
    disb = request_disbursement(
        ny_line, world["offices"]["NY"], False,
        amount_cents=5000000, use_code="PROGRAM",
    )
    certify_disbursement(disb["id"], world["offices"]["NY"])
    period1 = open_monitoring_period(stl_id)
    file_finding(period1["id"], 0, "BREACH")
    file_finding(period1["id"], 1, "BREACH")
    file_finding(period1["id"], 2, "COMPLIANT")
    assert get_settlement(stl_id)["compliance_hold"] is True
    period2 = run_compliant_period(world, 2)
    assert period2["status"] == "CLOSED_COMPLIANT"
    assert period2["breach_count"] == 0
    settlement = get_settlement(stl_id)
    assert settlement["compliance_hold"] is False, "the clean close cures the hold"
    disbs, _ = validate_paginated(
        api_client.list_allocation_line_disbursements(ny_line["id"], CHAIR)
    )
    assert disbs[0]["status"] == "CERTIFIED", (
        "the cure cascade returns HELD disbursements to CERTIFIED"
    )
    released = release_disbursement(disb["id"])
    assert released["status"] == "RELEASED"
    line = get_allocation_line(ny_line["id"])
    assert line["disbursed_cents"] == 5000000


def test_release_cascades_line_disbursed_to_fund_disbursed_to_closeout():
    """PRD section 3.5: "the settlement's fund moves to `DISBURSING` on the
    first release (from either `FUNDED` or `PARTIALLY_FUNDED`), and on to
    `DISBURSED` the moment every allocation line of the settlement has reached
    a terminal status, `DISBURSED` or `REVERTED`."
    PRD section 3.7: "When the period whose `period_index` is 6 closes with
    `breach_count` zero while the settlement's `fund_status` is `DISBURSED`,
    the settlement's `term_status` moves `EXECUTED` → `CLOSED_OUT`, and that
    close-out cascades upward: the investigation's phase moves `MONITORING` →
    `CLOSED` automatically, ending the matter."

    Design: Difficulty/transitive_cascade/release_cascades_line_disbursed_to_fund_disbursed_to_closeout
    """
    world = setup_all_periods_compliant_world(period_count=5)
    stl_id = world["settlement"]["id"]
    # Hops 1-3 already landed inside the fixture: every line released in full
    # (DISBURSED) and the fund fully disbursed once all lines were terminal.
    assert world["settlement"]["fund_status"] == "DISBURSED"
    for line in world["lines"]:
        assert line["status"] == "DISBURSED"
        assert line["disbursed_cents"] == line["gross_share_cents"]
    assert world["investigation"]["phase"] == "MONITORING"
    # Trigger: the final finding of the sixth period.
    period6 = run_compliant_period(world, 6)
    assert period6["status"] == "CLOSED_COMPLIANT"
    assert period6["breach_count"] == 0
    settlement = get_settlement(stl_id)
    assert settlement["term_status"] == "CLOSED_OUT"
    assert settlement["fund_status"] == "DISBURSED"
    assert get_investigation(world["investigation"]["id"])["phase"] == "CLOSED"
