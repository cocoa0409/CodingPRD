"""Client-contact compliance (intervals by status, the strictly-greater
overdue sweep, immediate clearing on log-contact) and the release checklist /
execution gates."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_PLUS_90D,
    CLOCK_DEFAULT_PLUS_91D,
    TEST_USERS,
    add_effective_authorization,
    add_evidence_item,
    add_lab_analysis,
    advance_case,
    advance_case_to,
    case_advance_payload,
    get_case,
    log_contact,
    record_result_on_ctx,
    run_contact_overdue_sweep,
    set_clock,
    setup_accepted_case,
    setup_case_in_litigation,
    setup_exonerated_case,
    validate_error,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]
DECIDER = TEST_USERS["managing_attorney_headers"]


def test_contact_overdue_strict_greater_boundary_and_sweep_report(api):
    """PRD section 3.7: "For each swept case the sweep computes the whole days
    between the clock and `last_contact_at` and sets the flag true exactly
    when that figure strictly exceeds the interval — a case precisely at its
    interval is not overdue."
    PRD section 3.7: "the sweep reports `swept_case_count`,
    `newly_overdue_count`, and the `newly_overdue_case_ids`."
    PRD section 3.7: "Each logged contact stamps `last_contact_at` from the
    logical clock, increments `contact_count`, and clears `contact_overdue`
    immediately, without waiting for any sweep."

    Design: Corner/calculations/contact_overdue_strict_greater_boundary_and_sweep_report
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "IA", "name": "Iowa"}
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["contact_interval_days"] == 90
    assert ctx["case"]["contact_overdue"] is False

    # Exactly 90 days after creation: at the interval, NOT overdue.
    set_clock(CLOCK_DEFAULT_PLUS_90D)
    report = run_contact_overdue_sweep()
    assert report["swept_case_count"] == 1
    assert report["newly_overdue_count"] == 0
    assert get_case(case_id)["contact_overdue"] is False

    # 91 days: strictly over the interval, so the flag flips.
    set_clock(CLOCK_DEFAULT_PLUS_91D)
    report = run_contact_overdue_sweep()
    assert report["newly_overdue_count"] == 1
    assert case_id in report["newly_overdue_case_ids"]
    assert get_case(case_id)["contact_overdue"] is True

    # A logged contact clears the flag immediately, no sweep needed.
    data = log_contact(case_id, channel="VIDEO", expectation_setting="CAUTIOUS",
                       summary="Status call")
    assert data["contact_overdue"] is False
    assert data["contact_count"] == 1
    assert data["last_expectation_setting"] == "CAUTIOUS"


def test_contact_interval_mapping_follows_case_status(api):
    """PRD section 3.7: "The interval a case may go silent depends on its
    status: 90 days in `OPEN` or `INVESTIGATION`, 60 days in `TESTING`, 30
    days in `LITIGATION`, and 14 days in `EXONERATED`; the stored
    `contact_interval_days` mirrors this map and is null on a `CLOSED` case."
    PRD section 3.6: "From `INVESTIGATION`, beginning testing ... moves the
    case to `TESTING`, tightening the contact interval to 60 days (any
    `contact_overdue` flag is recomputed only when the next sweep runs,
    §3.7)".

    Design: Corner/calculations/contact_interval_mapping_follows_case_status
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "NE", "name": "Nebraska"}
    )
    assert ctx["case"]["contact_interval_days"] == 90

    advance_case_to(ctx, "BEGIN_INVESTIGATION")
    assert ctx["case"]["contact_interval_days"] == 90

    add_evidence_item(ctx)
    add_effective_authorization(ctx)
    advance_case_to(ctx, "BEGIN_TESTING")
    assert ctx["case"]["contact_interval_days"] == 60

    add_lab_analysis(ctx)
    record_result_on_ctx(ctx)
    advance_case_to(ctx, "BEGIN_LITIGATION")
    assert ctx["case"]["contact_interval_days"] == 30

    # Advancing a case never itself flips the flag; only the sweep writes it.
    assert ctx["case"]["contact_overdue"] is False


def test_release_checklist_regression_cycles_ready_to_planning(api):
    """PRD section 3.7: "After each update the readiness re-derives: `READY`
    when all three flags are true, `PLANNING` otherwise — regressing from
    `READY` back to `PLANNING` by clearing a flag is legal."
    PRD section 3.7: "the payload's `housing_arranged`, `id_documents_ready`,
    and `transportation_arranged` keys map onto the case's
    `release_housing_ready`, `release_id_documents_ready`, and
    `release_transportation_ready` flags respectively, each key optional with
    an absent key leaving its flag unchanged".

    Design: Corner/state_machines/release_checklist_regression_cycles_ready_to_planning
    """
    ctx = setup_exonerated_case(
        jurisdiction_overrides={"state_code": "DE", "name": "Delaware"}
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["release_readiness"] == "PLANNING"

    ready = advance_case(
        case_id, "UPDATE_RELEASE_CHECKLIST",
        housing_arranged=True, id_documents_ready=True,
        transportation_arranged=True,
        scheduled_release_date="2026-12-01T09:00:00Z",
    )
    assert ready["release_readiness"] == "READY"
    assert ready["release_housing_ready"] is True
    assert ready["release_id_documents_ready"] is True
    assert ready["release_transportation_ready"] is True

    # Clearing one flag regresses readiness; absent keys leave flags unchanged.
    regressed = advance_case(
        case_id, "UPDATE_RELEASE_CHECKLIST", headers=DECIDER,
        housing_arranged=False,
    )
    assert regressed["release_readiness"] == "PLANNING"
    assert regressed["release_housing_ready"] is False
    assert regressed["release_id_documents_ready"] is True
    assert regressed["release_transportation_ready"] is True
    assert regressed["status"] == "EXONERATED"


def test_release_execute_gates_readiness_then_date(api):
    """PRD section 3.7: "It requires the case to be `EXONERATED`
    (`ERR_CASE_NOT_EXONERATED` otherwise), requires `release_readiness` to be
    exactly `READY` — else `ERR_RELEASE_NOT_READY` (HTTP 409) — and requires
    the logical clock to have reached the `scheduled_release_date`, else
    `ERR_RELEASE_DATE_NOT_REACHED` (HTTP 409)."

    Design: Corner/validations/release_execute_gates_readiness_then_date
    """
    ctx = setup_exonerated_case(
        jurisdiction_overrides={"state_code": "CT", "name": "Connecticut"}
    )
    case_id = ctx["case"]["id"]

    advance_case(
        case_id, "UPDATE_RELEASE_CHECKLIST",
        housing_arranged=True, scheduled_release_date="2026-12-01T09:00:00Z",
    )
    # Readiness gate first: the checklist is incomplete.
    resp = api.advance_case(case_id, case_advance_payload("EXECUTE_RELEASE"), ATTORNEY)
    validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_READY)

    advance_case(
        case_id, "UPDATE_RELEASE_CHECKLIST",
        id_documents_ready=True, transportation_arranged=True,
    )
    assert get_case(case_id)["release_readiness"] == "READY"

    # Temporal gate: one second before the scheduled release.
    set_clock("2026-12-01T08:59:59Z")
    resp = api.advance_case(case_id, case_advance_payload("EXECUTE_RELEASE"), ATTORNEY)
    validate_error(resp, ApiErrorId.ERR_RELEASE_DATE_NOT_REACHED)

    # Exactly at the scheduled instant: equality executes.
    set_clock("2026-12-01T09:00:00Z")
    data = validate_ok(
        api.advance_case(case_id, case_advance_payload("EXECUTE_RELEASE"), ATTORNEY)
    )
    assert data["release_readiness"] == "RELEASED"


def test_update_release_checklist_before_exoneration_rejected(api):
    """PRD section 3.7: "Attempting the update on a case not in `EXONERATED`
    is rejected with `ERR_CASE_NOT_EXONERATED` (HTTP 409); on an `EXONERATED`
    case whose readiness is no longer in the planning states, with
    `ERR_INVALID_STATE`."

    Design: Corner/validations/update_release_checklist_before_exoneration_rejected
    """
    ctx = setup_case_in_litigation(
        jurisdiction_overrides={"state_code": "ME", "name": "Maine"}
    )
    assert ctx["case"]["status"] == "LITIGATION"
    assert ctx["case"]["release_readiness"] == "NOT_APPLICABLE"

    resp = api.advance_case(
        ctx["case"]["id"],
        case_advance_payload("UPDATE_RELEASE_CHECKLIST", housing_arranged=True),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_EXONERATED)

    case = get_case(ctx["case"]["id"])
    assert case["release_housing_ready"] is False
    assert case["release_readiness"] == "NOT_APPLICABLE"
