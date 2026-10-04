"""Corner tests: state_machines section — initial states, undefined
transitions, terminal lockdowns, remediation/re-submission loops, and the
clock-driven screening auto-transition."""
import pytest

from test_helpers import (
    AUDITOR_ISSUER_ID,
    ApiErrorId,
    create_athlete,
    create_certification_cycle,
    create_funding_agreement,
    create_governing_body,
    decertify_body,
    file_complaint,
    get_success_data,
    issue_findings,
    make_auditor_headers,
    move_cycle_to_remediation,
    open_cycle,
    parse_iso,
    read_athlete,
    read_funding_agreement,
    read_governing_body,
    reject_result,
    resubmit_result,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    substantiate_complaint,
    submit_result,
    terminate_agreement,
    validate_error,
    validate_success,
    verify_result,
)


def test_complaint_initial_state_filed(api, committee_admin_headers):
    """PRD §3.2: "The complaint starts `FILED` and moves through `TRIAGED` and
    `INVESTIGATING` to a terminal resolution of `SUBSTANTIATED` or
    `DISMISSED`, all driven by `CertificationAuditor` operators."
    PRD §3.2: "Triage records the acting auditor as `triaged_by_user_id`;
    resolution — either direction — records the resolving auditor as
    `resolved_by_user_id` and stamps `resolved_at` with the logical clock."
    PRD §2.4: "`version` (integer):** starts at 1 on creation and increments
    by exactly 1 on every mutation, including mutations caused by system
    cascades rather than direct client writes."

    Design: Corner/state_machines/complaint_initial_state_filed
    """
    body = create_governing_body(
        api=api,
        name="US Judo",
        sport_code="JUDO",
        funding_budget_cents=3_000_000,
        sport_science_pool_hours=40,
    )
    resp = api.create_complaint(
        body["id"],
        {
            "category": "FINANCIAL",
            "severity": "MINOR",
            "description": "Late expense reimbursements",
        },
        committee_admin_headers,
    )
    complaint = validate_success(resp, 201)
    assert complaint["status"] == "FILED"
    assert complaint["version"] == 1
    assert complaint["triaged_by_user_id"] is None
    assert complaint["resolved_by_user_id"] is None
    assert complaint["resolved_at"] is None


def test_complaint_resolve_from_filed_rejected(api, committee_admin_headers):
    """PRD §3.2: "The complaint starts `FILED` and moves through `TRIAGED` and
    `INVESTIGATING` to a terminal resolution of `SUBSTANTIATED` or
    `DISMISSED`, all driven by `CertificationAuditor` operators."
    PRD §2.6: "4. **State legality.** The requested transition must be defined
    from the resource's current state, or the request is rejected with
    `ERR_INVALID_STATE` (409); a resource already in a terminal state rejects
    every transition with `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/complaint_resolve_from_filed_rejected
    """
    body = create_governing_body(
        api=api,
        name="US Judo",
        sport_code="JUDO",
        funding_budget_cents=3_000_000,
        sport_science_pool_hours=40,
    )
    complaint = file_complaint(
        body["id"],
        api=api,
        category="SELECTION",
        severity="MAJOR",
        description="Selection criteria changed mid-cycle",
    )
    # FILED -> SUBSTANTIATED skips TRIAGED and INVESTIGATING: undefined.
    resp = api.transition_complaint(
        complaint["id"],
        {"to_state": "SUBSTANTIATED"},
        make_auditor_headers(AUDITOR_ISSUER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    listed = get_success_data(api.list_complaints(body["id"], committee_admin_headers))
    after = next(c for c in listed if c["id"] == complaint["id"])
    assert after["status"] == "FILED", "rejected transition must not move the complaint"
    assert after["triaged_by_user_id"] is None
    assert after["resolved_at"] is None


def test_decertified_body_terminal_lockdown(api, committee_admin_headers):
    """PRD §3.2: "`DECERTIFIED` is terminal — no transition leaves it — and a
    decertified body blocks downstream operations everywhere the rules require
    a non-decertified body."
    PRD §2.6: "4. **State legality.** The requested transition must be defined
    from the resource's current state, or the request is rejected with
    `ERR_INVALID_STATE` (409); a resource already in a terminal state rejects
    every transition with `ERR_ALREADY_TERMINAL` (409)."
    PRD §3.2: "Decertification is available only from `PROBATION` or
    `INTERIM_MANAGED`, and only with evidence: the body must have a
    `CLOSED_FAILED` cycle or a `SUBSTANTIATED` `CRITICAL` complaint resolved
    or closed within the trailing 365 days."

    Design: Corner/state_machines/decertified_body_terminal_lockdown
    """
    body = setup_certified_body(
        api=api,
        name="US Canoe",
        sport_code="CANO",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    # SUBSTANTIATED CRITICAL complaint cascades CERTIFIED -> INTERIM_MANAGED
    # and doubles as the decertification evidence.
    substantiate_complaint(
        body["id"],
        severity="CRITICAL",
        category="GOVERNANCE",
        api=api,
        description="Board falsified election results",
    )
    decertify_body(body["id"], api=api)

    resp = api.transition_governing_body(
        body["id"], {"to_state": "PROBATION"}, committee_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    after = read_governing_body(body["id"], api=api)
    assert after["status"] == "DECERTIFIED"


def test_cycle_remediation_reissue_loop(api):
    """PRD §3.1: "The remediation path moves `FINDINGS_ISSUED` to
    `REMEDIATION`; findings may then be re-issued — `REMEDIATION` back to
    `FINDINGS_ISSUED` — with fresh component scores, recomputing
    `provisional_score` and refreshing `issued_by_user_id` to the re-issuing
    auditor."
    PRD §3.1: "The provisional score is a weighted blend of the three
    components: 0.40 times the governance component, plus 0.35 times the
    athlete-representation component, plus 0.25 times the financial component,
    rounded half up to two decimal places."

    Design: Corner/state_machines/cycle_remediation_reissue_loop
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    cycle = create_certification_cycle(body["id"], api=api)
    open_cycle(cycle["id"], api=api)
    first = issue_findings(cycle["id"], 80, 70, 60, api=api)
    # 0.40*80 + 0.35*70 + 0.25*60 = 32.0 + 24.5 + 15.0 = 71.5
    assert first["status"] == "FINDINGS_ISSUED"
    assert first["provisional_score"] == pytest.approx(71.5, abs=1e-9)

    move_cycle_to_remediation(cycle["id"], api=api)

    reissued = issue_findings(cycle["id"], 82, 74, 66, api=api)
    assert reissued["status"] == "FINDINGS_ISSUED", (
        "the REMEDIATION -> FINDINGS_ISSUED revision loop is a defined transition"
    )
    # 0.40*82 + 0.35*74 + 0.25*66 = 32.8 + 25.9 + 16.5 = 75.2
    assert reissued["provisional_score"] == pytest.approx(75.2, abs=1e-9), (
        "re-issue recomputes provisional_score from the fresh components"
    )


def test_result_resubmission_loop(api):
    """PRD §3.4: "Rejection moves the result to `REJECTED`, from which the
    owning athlete — and only the owning athlete, matched by `X-User-ID` — may
    resubmit it to `SUBMITTED` for another review."
    PRD §3.4: "The placing ladder pays 40 points for 1st, 32 for 2nd, 26 for
    3rd, 20 for 4th, 16 for 5th, 12 for 6th, 8 for 7th, and 4 for 8th. The
    grade multiplier is 1.5 for an `A`-graded event, 1.25 for a `B`, and 1.0
    for a `C`. The `base_points` of a result are the placing points multiplied
    by the grade multiplier — a 2nd place at an `A` event banks 48 points, a
    1st at a `C` event banks 40."

    Design: Corner/state_machines/result_resubmission_loop
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = create_athlete(
        body["id"], api=api, full_name="Re Sub", date_of_birth="2000-01-01"
    )
    result = submit_result(
        athlete["id"],
        api=api,
        event_name="Spring Open",
        event_grade="B",
        placing=3,
        event_date="2026-10-01T00:00:00Z",
    )
    reject_result(result["id"], api=api)

    resubmitted = resubmit_result(result["id"], athlete["id"], api=api)
    assert resubmitted["status"] == "SUBMITTED", (
        "REJECTED is not terminal: the owning athlete resubmits to SUBMITTED"
    )

    verified = verify_result(result["id"], api=api)
    assert verified["status"] == "VERIFIED"
    # PLACING_POINTS[3] = 26, EVENT_MULTIPLIER B = 1.25 -> 32.5
    assert verified["base_points"] == pytest.approx(32.5, abs=1e-9)


def test_funding_terminated_lockdown(api, committee_admin_headers):
    """PRD §3.5: "Termination — from `OFFERED`, `ACTIVE`, or `SUSPENDED`, by a
    `CommitteeAdmin` or by the athlete-retirement cascade — removes the
    stipend from the committed total when the prior status was `ACTIVE`,
    lapses enrolled insurance, zeroes `science_hours_allocated`, and reruns
    the waterfall. `TERMINATED` is terminal."
    PRD §2.6: "4. **State legality.** The requested transition must be defined
    from the resource's current state, or the request is rejected with
    `ERR_INVALID_STATE` (409); a resource already in a terminal state rejects
    every transition with `ERR_ALREADY_TERMINAL` (409)."
    PRD §3.5: "The agreement begins with `status` of `OFFERED` — the lifecycle
    runs `OFFERED` to `ACTIVE`, may drop to `SUSPENDED` and return, and ends
    at the terminal `TERMINATED` — and with `insurance_status` of `INS_NONE`,
    the head of a parallel insurance dimension running `INS_NONE` to
    `INS_ENROLLED`, possibly lapsing to `INS_LAPSED` and re-enrolling."

    Design: Corner/state_machines/funding_terminated_lockdown
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = create_athlete(
        body["id"], api=api, full_name="Term Test", date_of_birth="2000-01-01"
    )
    # No verified results -> tier NONE; termination from OFFERED is allowed.
    agreement = create_funding_agreement(
        athlete["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    terminate_agreement(agreement["id"], api=api)

    resp = api.transition_funding_agreement(
        agreement["id"], {"to_state": "ACTIVE"}, committee_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    after = read_funding_agreement(agreement["id"], api=api)
    assert after["status"] == "TERMINATED"
    assert after["insurance_status"] == "INS_NONE"


def test_screening_auto_expiry_on_clock(api, committee_admin_headers):
    """PRD §3.3: "A `SafeSportOfficer` clears screening from
    `SCREENING_PENDING`, `SCREENING_FLAGGED`, or `SCREENING_EXPIRED` — never
    while the athlete is `RETIRED` — moving the athlete to `SCREENING_CLEARED`
    and setting `screening_expires_at` to the current logical clock plus 730
    days. When the logical clock moves strictly later than
    `screening_expires_at`, screening flips from `SCREENING_CLEARED` to
    `SCREENING_EXPIRED` automatically, both on clock set and on read."
    PRD §2.5: "An Athlete whose `screening_status` is `SCREENING_CLEARED`
    flips to `SCREENING_EXPIRED` once the current logical clock is strictly
    later than `screening_expires_at`."

    Design: Corner/state_machines/screening_auto_expiry_on_clock
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    # Cleared at the startup clock 2026-09-01T00:00:00Z, so the clearance
    # expires at 2028-08-31T00:00:00Z (plus 730 days).
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Exp Test", date_of_birth="2000-01-01"
    )
    assert athlete["eligibility_status"] == "ELIGIBLE"
    assert athlete["screening_status"] == "SCREENING_CLEARED"
    assert parse_iso(athlete["screening_expires_at"]) == parse_iso(
        "2028-08-31T00:00:00Z"
    )

    # 2028-09-01 is strictly later than the 2028-08-31 expiry instant.
    set_logical_clock("2028-09-01T00:00:00Z", api=api)
    after = read_athlete(athlete["id"], api=api)
    assert after["screening_status"] == "SCREENING_EXPIRED", (
        "screening flips automatically once the clock passes screening_expires_at"
    )
    assert after["eligibility_status"] == "ELIGIBLE", (
        "the auto-transition touches only the screening dimension"
    )
