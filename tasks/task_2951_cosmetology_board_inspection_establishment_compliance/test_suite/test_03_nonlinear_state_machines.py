"""Non-linear state machines: a second independent dimension, and a true cycle.

PRD 3.6 gives one row two orthogonal state dimensions - an inspection's
``status`` walk and its ``hazard_state`` walk advance without touching each
other.  PRD 3.8 gives the citation a genuine cycle,
CONTESTED -> HEARING_SCHEDULED -> AMENDED -> CONTESTED, bounded not by a status
precondition but by a round cap.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    INSPECTOR_HEADERS,
    INSPECTOR_USER_ID,
    SECOND_HEARING_OFFICER_HEADERS,
    SECOND_HEARING_OFFICER_USER_ID,
    ApiErrorId,
    assert_cents,
    assert_fine_breakdown,
    assert_instants_equal,
    assert_points,
    contest_citation,
    create_establishment,
    create_violation_code,
    decide_hearing,
    hazard_declaration_payload,
    hearing_payload,
    issue_citation,
    record_finding,
    refresh_citation,
    refresh_establishment,
    schedule_hearing,
    setup_finalized_inspection,
    setup_inspection_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)


# --- Inspection: the hazard dimension advances independently of status --------
def _aqua_nails_in_progress_with_an_imminent_hazard_finding(api):
    """A COMPLAINT_DRIVEN visit open on site with one IMMINENT_HAZARD finding."""
    hazard_code = create_violation_code(
        api,
        severity="IMMINENT_HAZARD",
        base_points=5.0,
        fine_cents_base=50000,
        category="FACILITY",
        code="FAC-400",
    )
    establishment = create_establishment(
        api, station_capacity=6, establishment_type="NAIL_SALON", county_code="NCC",
        legal_name="Aqua Nails",
    )
    assert establishment["license_status"] == "PENDING_INSPECTION"
    assert establishment["compliance_posture"] == "CLEAR"
    inspection = setup_inspection_in_progress(
        api, establishment["id"], inspection_type="COMPLAINT_DRIVEN"
    )
    finding = record_finding(
        api,
        inspection["id"],
        hazard_code["id"],
        observed_count=1,
        corrected_on_site=False,
    )
    return {
        "establishment": establishment,
        "inspection": inspection,
        "finding": finding,
    }


def _declare_hazard(api, inspection_id, finding_id):
    return validate_success(
        api.declare_hazard(
            inspection_id,
            hazard_declaration_payload(
                finding_id, narrative="energised conductor within splash zone"
            ),
            INSPECTOR_HEADERS,
        )
    )


def test_hazard_declaration_moves_only_the_hazard_dimension(api):
    """PRD 3.6: ``hazard_state`` "evolves entirely separately from status:
    declaring a hazard never changes status, and the inspection continues through
    submission and finalization exactly as it would otherwise", while the
    establishment's licence "moves immediately to CLOSED_IMMINENT_HAZARD ... and
    its compliance_posture is recomputed to FROZEN" - PRD 3.6 again: "Closure does
    not wait for finalize".  No demerits are posted yet, because PRD 3.7 hop two
    is what assesses them.

    Design: Difficulty/non_linear_state_machine/inspection_hazard_dimension_advances_independently_of_status
    """
    built = _aqua_nails_in_progress_with_an_imminent_hazard_finding(api)

    declared = _declare_hazard(api, built["inspection"]["id"], built["finding"]["id"])
    assert declared["hazard_state"] == "HAZARD_DECLARED"
    assert declared["status"] == "IN_PROGRESS"
    assert declared["submitted_at"] is None
    assert declared["finalized_at"] is None

    finding = validate_success(
        api.get_violation_finding(built["finding"]["id"], BOARD_ADMIN_HEADERS)
    )
    assert finding["declared_hazard"] is True

    establishment = refresh_establishment(api, built["establishment"]["id"])
    assert establishment["license_status"] == "CLOSED_IMMINENT_HAZARD"
    assert establishment["compliance_posture"] == "FROZEN"
    assert_points(establishment["demerit_balance"], 0.00, "demerit_balance")


def test_status_walk_leaves_hazard_state_untouched_and_both_bands_closed(api):
    """PRD 3.6: "because hazard_state is HAZARD_DECLARED from then on, both the
    provisional and the final outcome bands of that inspection resolve to
    IMMEDIATE_CLOSURE regardless of the arithmetic score", and PRD 3.5's band
    order puts IMMEDIATE_CLOSURE first.  The score itself is
    5.0 * 8.0 * 1 * 1.0 * (1 - 0.00) = 40.00 in both variants, because PRD 3.5
    grants no on-site credit to an IMMINENT_HAZARD finding.  The status dimension
    walks IN_PROGRESS -> PENDING_REVIEW -> FINALIZED with ``hazard_state`` pinned.

    Design: Difficulty/non_linear_state_machine/inspection_hazard_dimension_advances_independently_of_status
    """
    built = _aqua_nails_in_progress_with_an_imminent_hazard_finding(api)
    inspection_id = built["inspection"]["id"]
    _declare_hazard(api, inspection_id, built["finding"]["id"])

    submitted = validate_success(api.submit_inspection(inspection_id, INSPECTOR_HEADERS))
    assert submitted["status"] == "PENDING_REVIEW"
    assert submitted["hazard_state"] == "HAZARD_DECLARED"
    assert_points(
        submitted["provisional_adjusted_score"], 40.00, "provisional_adjusted_score"
    )
    assert submitted["provisional_outcome"] == "IMMEDIATE_CLOSURE"

    finalized = validate_success(
        api.finalize_inspection(inspection_id, BOARD_ADMIN_HEADERS)
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["hazard_state"] == "HAZARD_DECLARED"
    assert_points(finalized["final_adjusted_score"], 40.00, "final_adjusted_score")
    assert finalized["final_outcome"] == "IMMEDIATE_CLOSURE"

    establishment = refresh_establishment(api, built["establishment"]["id"])
    assert_points(establishment["demerit_balance"], 40.00, "demerit_balance")
    assert establishment["license_status"] == "CLOSED_IMMINENT_HAZARD"
    assert establishment["compliance_posture"] == "FROZEN"


# --- Citation: the amendment cycle, bounded by the hearing round cap ----------
def _glow_salon_issued_citation(api):
    """A 56160-cent ESTABLISHMENT citation off a FAILING inspection.

    Base 30000 + 12000 = 42000, tier 1.00 on a 0.00 snapshot, subject factor
    1.00, surcharge 400 * (55.00 - 30.00) = 10000, so PRD 3.7 assesses 52000 with
    an 8 percent fee of 4160.  The conducting inspector is ``INSPECTOR_USER_ID``,
    which every adjudicator below must differ from (PRD 2.10).
    """
    foot_spa_code = create_violation_code(
        api, severity="CRITICAL", base_points=4.0, fine_cents_base=30000,
        category="FOOT_SPA", code="FSP-300",
    )
    implement_code = create_violation_code(
        api, severity="MAJOR", base_points=6.0, fine_cents_base=12000,
        category="IMPLEMENT_HANDLING", code="IMP-200",
    )
    establishment = create_establishment(
        api, station_capacity=4, establishment_type="SALON", county_code="NCA",
        legal_name="Glow Salon",
    )
    finalized = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[
            {"violation_code_id": foot_spa_code["id"], "observed_count": 2},
            {"violation_code_id": implement_code["id"], "observed_count": 1},
        ],
        inspector_user_id=INSPECTOR_USER_ID,
    )
    citation = issue_citation(api, finalized["inspection"]["id"])
    assert_cents(citation["total_due_cents"], 56160, "total_due_cents")
    assert citation["hearing_round_count"] == 0
    return {
        "establishment": establishment,
        "inspection": finalized["inspection"],
        "citation": citation,
    }


def _run_amendment_lap(
    api, citation_id, officer_user_id, officer_headers, amended_fine_cents, scheduled_at
):
    """One full lap: contest, schedule, then decide AMENDED."""
    contested = contest_citation(api, citation_id)
    assert contested["status"] == "CONTESTED"
    hearing = schedule_hearing(
        api, citation_id, officer_user_id, scheduled_at=scheduled_at
    )
    decided = decide_hearing(
        api,
        hearing["id"],
        decision="AMENDED",
        amended_fine_cents=amended_fine_cents,
        headers=officer_headers,
    )
    return {"hearing": hearing, "decided_hearing": decided}


def test_amended_decision_returns_the_citation_to_a_state_it_already_occupied(api):
    """PRD 3.8: an AMENDED decision re-derives the fee from the new assessed fine
    and "its contest_deadline_at is re-based to the hearing's decided_at advanced
    by 20 days, which is what reopens the contest right for a second round", and a
    citation may be contested from AMENDED - "AMENDED -> CONTESTED which is the arc
    that closes the adjudication cycle".  20000 cents re-keys the fee to the 5
    percent band, giving 1000 and 21000 due, and the citation walks
    CONTESTED -> HEARING_SCHEDULED -> AMENDED -> CONTESTED.

    Design: Difficulty/non_linear_state_machine/citation_amendment_cycle_loops_back_to_contested_until_rounds_exhausted
    """
    built = _glow_salon_issued_citation(api)
    citation_id = built["citation"]["id"]

    contested = contest_citation(api, citation_id)
    assert contested["status"] == "CONTESTED"

    hearing = schedule_hearing(
        api, citation_id, HEARING_OFFICER_USER_ID, scheduled_at="2026-08-20T14:00:00.000Z"
    )
    assert hearing["round_index"] == 1
    assert hearing["status"] == "SCHEDULED"
    scheduled_citation = refresh_citation(api, citation_id)
    assert scheduled_citation["status"] == "HEARING_SCHEDULED"
    assert scheduled_citation["hearing_round_count"] == 1

    decided = decide_hearing(
        api,
        hearing["id"],
        decision="AMENDED",
        amended_fine_cents=20000,
        headers=HEARING_OFFICER_HEADERS,
    )
    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "AMENDED"

    amended = refresh_citation(api, citation_id)
    assert amended["status"] == "AMENDED"
    assert_fine_breakdown(
        amended,
        assessed_fine_cents=20000,
        administrative_fee_cents=1000,
        total_due_cents=21000,
        outstanding_fine_cents=21000,
    )
    assert_instants_equal(
        amended["contest_deadline_at"],
        "2026-08-21T00:00:00.000Z",
        "contest_deadline_at re-based to decided_at + 20 days",
    )

    # The cycle closes: the citation re-enters a state it has already occupied.
    recontested = contest_citation(api, citation_id)
    assert recontested["status"] == "CONTESTED"
    assert recontested["hearing_round_count"] == 1


def test_third_hearing_request_is_refused_by_the_round_cap_not_by_a_status_gate(api):
    """PRD 3.8: "The citation's hearing_round_count must be strictly below the cap
    of two rounds; a citation that has already had both is refused with
    ERR_HEARING_ROUNDS_EXHAUSTED", and "Contesting is deliberately not gated on
    hearing_round_count, so a citation amended in the second round may still be
    contested and the round cap surfaces later, at scheduling time".  Two laps
    re-derive the fine 56160 -> 21000 -> 10500, the third contest still succeeds,
    and only the third scheduling attempt is rejected.

    Design: Difficulty/non_linear_state_machine/citation_amendment_cycle_loops_back_to_contested_until_rounds_exhausted
    """
    built = _glow_salon_issued_citation(api)
    citation_id = built["citation"]["id"]

    first = _run_amendment_lap(
        api,
        citation_id,
        HEARING_OFFICER_USER_ID,
        HEARING_OFFICER_HEADERS,
        amended_fine_cents=20000,
        scheduled_at="2026-08-20T14:00:00.000Z",
    )
    assert first["hearing"]["round_index"] == 1
    assert_cents(refresh_citation(api, citation_id)["total_due_cents"], 21000, "lap one")

    second = _run_amendment_lap(
        api,
        citation_id,
        SECOND_HEARING_OFFICER_USER_ID,
        SECOND_HEARING_OFFICER_HEADERS,
        amended_fine_cents=10000,
        scheduled_at="2026-08-25T14:00:00.000Z",
    )
    assert second["hearing"]["round_index"] == 2

    amended = refresh_citation(api, citation_id)
    assert amended["status"] == "AMENDED"
    assert amended["hearing_round_count"] == 2
    assert_fine_breakdown(
        amended,
        assessed_fine_cents=10000,
        administrative_fee_cents=500,
        total_due_cents=10500,
        outstanding_fine_cents=10500,
    )

    # The contest right survives the second amendment; the cap bites later.
    recontested = contest_citation(api, citation_id)
    assert recontested["status"] == "CONTESTED"

    validate_error(
        api.schedule_hearing(
            citation_id,
            hearing_payload(
                HEARING_OFFICER_USER_ID, scheduled_at="2026-08-28T14:00:00.000Z"
            ),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_HEARING_ROUNDS_EXHAUSTED,
    )

    rows, meta = validate_paginated(
        api.list_citation_hearings(citation_id, BOARD_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2
    assert [row["round_index"] for row in rows] == [1, 2]
    assert refresh_citation(api, citation_id)["hearing_round_count"] == 2
