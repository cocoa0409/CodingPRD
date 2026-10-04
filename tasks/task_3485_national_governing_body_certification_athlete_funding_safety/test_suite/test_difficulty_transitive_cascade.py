"""Difficulty tests: transitive_cascade — multi-hop cascades where each link
is caused by the previous link's mutation (abuse substantiation depth-4 and
decertification depth-3).
"""
import pytest

from test_helpers import (
    activate_agreement,
    add_verified_result,
    adjudicate_abuse_report,
    create_funding_agreement,
    enroll_insurance,
    file_abuse_report,
    file_appeal,
    file_complaint,
    forward_abuse_report,
    investigate_complaint,
    make_athlete_headers,
    make_ngb_admin_headers,
    read_athlete,
    read_funding_agreement,
    read_governing_body,
    read_procedure,
    read_roster,
    resolve_complaint,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_nominated_roster,
    triage_complaint,
    validate_paginated,
    validate_success,
)


def test_abuse_substantiation_cascade_depth4(api, committee_admin_headers):
    """PRD athlete section: "A substantiated adjudication fires the four-link
    abuse cascade in a single operation: the subject athlete's screening moves
    to `SCREENING_FLAGGED` and, when currently `ELIGIBLE`, eligibility moves
    to `SUSPENDED`; the athlete's `ACTIVE` funding agreements move to
    `SUSPENDED`; any enrolled insurance on those agreements lapses from
    `INS_ENROLLED` to `INS_LAPSED`; and the athlete's non-terminal roster
    slots are removed with `slot_status` becoming `REMOVED`, triggering
    alternate promotion under the roster slot rules of §3.6."
    PRD funding section: "Suspension subtracts exactly the agreement's
    `monthly_stipend_cents` from the body's `committed_monthly_stipend_cents`
    — an exact reversal, never an approximation".
    PRD selection section: "the highest-ranked `ALTERNATE` slot still
    `NOMINATED` becomes a `PRIMARY` slot with `slot_status` of `PROMOTED` and
    its `rank` reassigned".

    Design: Difficulty/transitive_cascade/abuse_substantiation_cascade_depth4
    """
    body = setup_certified_body(
        api=api,
        name="US Boxing",
        sport_code="BOXI",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete_a = setup_eligible_athlete(
        body["id"], api=api, full_name="A Prime", date_of_birth="1998-01-01"
    )
    add_verified_result(
        athlete_a["id"], event_grade="A", placing=1,
        event_date="2026-08-01T00:00:00Z", event_name="August Cup", api=api,
    )
    athlete_b = setup_eligible_athlete(
        body["id"], api=api, full_name="B Alt", date_of_birth="1999-02-02"
    )
    add_verified_result(
        athlete_b["id"], event_grade="C", placing=2,
        event_date="2026-06-01T00:00:00Z", event_name="June Meet", api=api,
    )

    # Selection chain first, while the startup clock still satisfies the
    # 90-day publish lead: roster NOMINATED at 2026-12-20 with A PRIMARY and
    # B ALTERNATE (composites 0.7*92+0.3*60 = 82.4 and 0.7*80+0.3*32 = 65.6).
    _proc, roster = setup_nominated_roster(
        body["id"],
        {athlete_a["id"]: 92, athlete_b["id"]: 80},
        api=api,
        quota_slots=1,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )
    slots_by_athlete = {s["athlete_id"]: s for s in roster["slots"]}
    assert slots_by_athlete[athlete_a["id"]]["slot_type"] == "PRIMARY"
    assert slots_by_athlete[athlete_a["id"]]["composite_score"] == pytest.approx(
        82.4, abs=1e-9
    )
    assert slots_by_athlete[athlete_b["id"]]["slot_type"] == "ALTERNATE"
    assert slots_by_athlete[athlete_b["id"]]["composite_score"] == pytest.approx(
        65.6, abs=1e-9
    )

    # Funding chain at the same 2026-12-20 clock: A's 2026-08-01 result is
    # 141 days old (full weight) -> 60.00 trailing points -> TIER_B 200000.
    agreement = create_funding_agreement(
        athlete_a["id"],
        api=api,
        coverage_start="2026-12-20T00:00:00Z",
        coverage_end="2027-06-20T00:00:00Z",
        points_method="TRAILING_365",
    )
    assert agreement["trailing_points"] == pytest.approx(60.0, abs=1e-9)
    assert agreement["tier"] == "TIER_B"
    agreement = activate_agreement(agreement["id"], api=api)
    # Enroll insurance at exactly activated_at + 30 days (inclusive boundary);
    # the result is 171 days old then, still inside the full-weight window.
    set_logical_clock("2027-01-19T00:00:00Z", api=api)
    enrolled = enroll_insurance(agreement["id"], api=api)
    assert enrolled["insurance_status"] == "INS_ENROLLED"

    # Trigger: abuse report forwarded to the independent body, then
    # adjudicated substantiated.
    report = file_abuse_report(
        athlete_a["id"],
        api=api,
        headers=make_ngb_admin_headers(body["id"]),
        reporter_role="NGB_STAFF",
        allegation="Physical abuse during training camp",
    )
    forward_abuse_report(report["id"], api=api)
    decided = adjudicate_abuse_report(
        report["id"], "ADJUDICATED_SUBSTANTIATED", api=api
    )
    assert decided["status"] == "ADJUDICATED_SUBSTANTIATED"

    # Link 1: athlete screening flagged and eligibility suspended.
    athlete_a_after = read_athlete(athlete_a["id"], api=api)
    assert athlete_a_after["eligibility_status"] == "SUSPENDED"
    assert athlete_a_after["screening_status"] == "SCREENING_FLAGGED"

    # Link 2: agreement SUSPENDED with its 200000 stipend debited exactly.
    agreement_after = read_funding_agreement(agreement["id"], api=api)
    assert agreement_after["status"] == "SUSPENDED"
    body_after = read_governing_body(body["id"], api=api)
    assert body_after["committed_monthly_stipend_cents"] == 0, (
        "the single 200000 stipend must be debited exactly, "
        f"got {body_after['committed_monthly_stipend_cents']!r}"
    )

    # Link 3: enrolled insurance lapses.
    assert agreement_after["insurance_status"] == "INS_LAPSED", (
        f"INS_ENROLLED must lapse on suspension, got {agreement_after['insurance_status']!r}"
    )

    # Link 4: A's roster slot REMOVED and B promoted to PRIMARY/PROMOTED.
    roster_after = read_roster(roster["id"], api=api)
    after_by_athlete = {s["athlete_id"]: s for s in roster_after["slots"]}
    assert after_by_athlete[athlete_a["id"]]["slot_status"] == "REMOVED"
    promoted = after_by_athlete[athlete_b["id"]]
    assert promoted["slot_type"] == "PRIMARY"
    assert promoted["slot_status"] == "PROMOTED"


def test_decertification_cascade_procedure_roster_appeals(
    api, committee_admin_headers
):
    """PRD complaints/decertification section: "The decertification cascade
    then resolves every dependent concern of the body in one operation: every
    non-terminal SelectionProcedure of the body moves to `SUPERSEDED`; every
    `ACTIVE` or `SUSPENDED` FundingAgreement of the body's athletes moves to
    `SUSPENDED`, halting stipends; and every `ACTIVE` CommercialDeal of the
    body's athletes moves to `TERMINATED`."
    PRD complaints/decertification section: "The procedure-supersede hop
    carries its own cascade: every non-terminal Roster of a superseded
    procedure moves to `CANCELLED`, and every `FILED` or `HEARING` Appeal of
    a cancelled roster moves to `WITHDRAWN`."
    PRD complaints/decertification section: "When a `CRITICAL` complaint is
    resolved `SUBSTANTIATED` while the body is `CERTIFIED` or `PROBATION`, the
    body cascades to `INTERIM_MANAGED`".
    PRD complaints/decertification section: "Decertification is available
    only from `PROBATION` or `INTERIM_MANAGED`, and only with evidence: the
    body must have a `CLOSED_FAILED` cycle or a `SUBSTANTIATED` `CRITICAL`
    complaint resolved or closed within the trailing 365 days."

    Design: Difficulty/transitive_cascade/decertification_cascade_procedure_roster_appeals
    """
    body = setup_certified_body(
        api=api,
        name="US Canoe",
        sport_code="CANO",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Kai Paddle", date_of_birth="1998-01-01"
    )
    proc, roster = setup_nominated_roster(
        body["id"],
        {athlete["id"]: 90},
        api=api,
        quota_slots=1,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )
    assert roster["status"] == "NOMINATED"

    # An open (FILED) appeal sits on the roster when the cascade fires.
    appeal = file_appeal(
        roster["id"], athlete["id"], api=api, grounds="ELIGIBILITY"
    )
    assert appeal["status"] == "FILED"

    # A CRITICAL complaint substantiated at 2026-12-21 cascades the CERTIFIED
    # body to INTERIM_MANAGED (decertification evidence within the window).
    set_logical_clock("2026-12-21T00:00:00Z", api=api)
    complaint = file_complaint(
        body["id"],
        api=api,
        headers=make_athlete_headers(athlete["id"]),
        category="GOVERNANCE",
        severity="CRITICAL",
        description="Board falsified election results",
    )
    triage_complaint(complaint["id"], api=api)
    investigate_complaint(complaint["id"], api=api)
    resolve_complaint(complaint["id"], "SUBSTANTIATED", api=api)
    body_mid = read_governing_body(body["id"], api=api)
    assert body_mid["status"] == "INTERIM_MANAGED", (
        "CRITICAL substantiation must cascade CERTIFIED -> INTERIM_MANAGED, "
        f"got {body_mid['status']!r}"
    )

    # Trigger: committee decertifies the INTERIM_MANAGED body.
    resp = api.transition_governing_body(
        body["id"], {"to_state": "DECERTIFIED"}, committee_admin_headers
    )
    body_end = validate_success(resp)
    assert body_end["status"] == "DECERTIFIED"

    # Link 1: the non-terminal (LOCKED) procedure is superseded.
    proc_after = read_procedure(body["id"], proc["id"], api=api)
    assert proc_after["proc_status"] == "SUPERSEDED", (
        f"procedure must be SUPERSEDED by the decertification cascade, "
        f"got {proc_after['proc_status']!r}"
    )

    # Link 2: the procedure supersede cancels the non-terminal roster.
    roster_after = read_roster(roster["id"], api=api)
    assert roster_after["status"] == "CANCELLED", (
        f"roster must be CANCELLED via the supersede hop, got {roster_after['status']!r}"
    )

    # Link 3: the roster cancellation withdraws the open appeal.
    appeals, meta = validate_paginated(
        api.list_roster_appeals(roster["id"], committee_admin_headers)
    )
    assert meta["total_count"] == 1
    assert appeals[0]["id"] == appeal["id"]
    assert appeals[0]["status"] == "WITHDRAWN", (
        f"the open appeal must be WITHDRAWN by the roster cancellation, "
        f"got {appeals[0]['status']!r}"
    )
