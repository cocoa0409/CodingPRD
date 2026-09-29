"""Transition probes: which hop each action performs, which side effects ride along with it, and
which calls a terminal or wrong-state record refuses."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_pct,
    make_adjudicator_headers,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_use_report,
    approve_project,
    create_allotment,
    create_closure_order,
    create_permittee,
    create_project,
    drafted_aoi_setup,
    filed_appeal,
    finalized_assessment,
    get_allotment,
    get_aoi,
    get_appeal,
    get_assessment,
    get_closure_order,
    get_decision,
    get_permit,
    get_permittee,
    get_project,
    get_use_record,
    issued_aoi_setup,
    lift_closure_order,
    list_bills,
    proposed_decision,
    signed_decision,
    void_aoi,
)
from test_helpers.test_users import JUDGE_1, OFFICER_1, SPECIALIST_1


def _draft_assessment(allotment_id, **overrides):
    """A DRAFT assessment authored by the specialist who will submit it."""
    return get_success_data(api_client.create_assessment(
        f.assessment_payload(allotment_id, **overrides),
        make_specialist_headers(SPECIALIST_1)), 201)


def _submit(assessment_id):
    return api_client.submit_assessment(assessment_id, make_specialist_headers(SPECIALIST_1))


def _review(assessment_id, review_outcome, review_notes):
    return api_client.review_assessment(
        assessment_id, f.review_payload(review_outcome, review_notes=review_notes),
        make_officer_headers(OFFICER_1))


def test_submitting_an_assessment_moves_it_to_field_review_and_scores_nothing():
    """The submit hop is pure: the assessment reaches FIELD_REVIEW with its author intact and its
    remand counter at 0, no composite score or determination is written, and the allotment's own
    health_determination is still NOT_ASSESSED.

    PRD 3.7: "Submitting for field review is the transition `DRAFT → FIELD_REVIEW`, and only the
    authoring specialist may perform it: the acting `X-User-ID` must equal `author_user_id`, and
    anyone else is `ERR_UNAUTHORIZED`."
    PRD 3.7: "The new row lands in `assessment_status` `DRAFT` with `remand_count` 0,
    `composite_score`, `determination` and `recommended_reduction_pct` all still unwritten —
    `recommended_reduction_pct` reading its default of 0 — and `author_user_id` set to the creating
    specialist's `X-User-ID`."
    PRD 3.7: "A `CONCUR` outcome moves `FIELD_REVIEW → FINALIZED`, computes `composite_score` and
    `determination`, computes `recommended_reduction_pct`, writes the resulting `determination` onto
    the allotment's `health_determination`, and bumps the allotment's `version`."

    Design: Corner/state_machines/corner_assessment_draft_to_field_review_on_submit
    """
    allotment = create_allotment(admin_unit_code="QB-116", total_permitted_aums=700,
                                 acres=20000, required_pasture_rotation_count=1)
    assessment = _draft_assessment(allotment["id"], assessment_year=2026,
                                   monitoring_method="INDICATOR_ASSESSMENT",
                                   upland_score=62, riparian_score=44, water_quality_score=51,
                                   standards_not_met=["UPLAND_HEALTH"],
                                   causal_factor_is_livestock=True)
    assert assessment["assessment_status"] == "DRAFT"

    submitted = get_success_data(_submit(assessment["id"]))

    assert submitted["assessment_status"] == "FIELD_REVIEW"
    assert submitted["author_user_id"] == SPECIALIST_1
    assert submitted["remand_count"] == 0
    assert submitted["composite_score"] is None
    assert submitted["determination"] is None
    assert submitted["recommended_reduction_pct"] == 0

    assert get_allotment(allotment["id"])["health_determination"] == "NOT_ASSESSED", (
        "only a CONCUR review writes the allotment")


def test_submitting_the_same_assessment_twice_is_refused_rather_than_ignored():
    """Submit is state-guarded, not idempotent: the second call on an assessment already in
    FIELD_REVIEW answers HTTP 409 ERR_ASSESSMENT_STATE_INVALID and leaves the row exactly where the
    first call put it.

    PRD 3.7: "Submitting an assessment that is not in `DRAFT` is `ERR_ASSESSMENT_STATE_INVALID`, and
    a `UTILIZATION_MAPPING` assessment whose `observed_utilization_pct` is still null cannot be
    submitted."
    PRD 2.6: "**Transition legality** — HTTP 409 with the entity-specific state code. The subject
    record must be in a state from which the requested transition is declared, and every same-entity
    precondition of that transition must hold."

    Design: Corner/state_machines/corner_assessment_submit_twice_rejected
    """
    allotment = create_allotment(admin_unit_code="QB-117", total_permitted_aums=650,
                                 acres=18000, required_pasture_rotation_count=1)
    assessment = _draft_assessment(allotment["id"], assessment_year=2026,
                                   monitoring_method="UTILIZATION_MAPPING",
                                   upland_score=70, riparian_score=70, water_quality_score=70,
                                   observed_utilization_pct=40, standards_not_met=[],
                                   causal_factor_is_livestock=False)
    first = get_success_data(_submit(assessment["id"]))
    assert first["assessment_status"] == "FIELD_REVIEW"

    validate_error(_submit(assessment["id"]), ApiErrorId.ERR_ASSESSMENT_STATE_INVALID, 409)

    unchanged = get_assessment(assessment["id"])
    assert unchanged["assessment_status"] == "FIELD_REVIEW"
    assert unchanged["remand_count"] == 0


def test_a_remand_review_moves_the_counter_and_nothing_else_at_all():
    """REMAND sends the assessment back to DRAFT and takes remand_count to 1 while writing no score,
    no determination and — crucially — nothing on the allotment, whose version does not move.

    PRD 3.7: "A `REMAND` outcome moves `FIELD_REVIEW → DRAFT`, increments the assessment's
    `remand_count` by 1, and does **nothing else at all** — no score is computed, no determination is
    written, and the allotment is not touched in any way."
    PRD 2.4: "Because `version` moves on side-effect mutations as well as direct ones, an allotment's
    `version` advances whenever its capacity ledger, posture or health determination is rewritten —
    when a closure order is issued or lifted, when a health assessment is finalized with a
    concurrence, when a decision document is authored against it, and when a decision is made
    effective or vacated."

    Design: Corner/state_machines/corner_assessment_remand_only_increments_counter
    """
    allotment = create_allotment(admin_unit_code="QB-118", total_permitted_aums=600,
                                 acres=17000, required_pasture_rotation_count=1)
    assessment = _draft_assessment(allotment["id"], assessment_year=2026,
                                   monitoring_method="INDICATOR_ASSESSMENT",
                                   upland_score=62, riparian_score=44, water_quality_score=51,
                                   standards_not_met=["UPLAND_HEALTH"],
                                   causal_factor_is_livestock=True)
    get_success_data(_submit(assessment["id"]))
    version_before = get_allotment(allotment["id"])["version"]

    remanded = get_success_data(_review(
        assessment["id"], "REMAND",
        "Riparian transects were not re-read after the July storm; resample reach two."))

    assert remanded["assessment_status"] == "DRAFT"
    assert remanded["remand_count"] == 1
    assert remanded["composite_score"] is None
    assert remanded["determination"] is None
    assert remanded["recommended_reduction_pct"] == 0

    after = get_allotment(allotment["id"])
    assert after["health_determination"] == "NOT_ASSESSED"
    assert after["version"] == version_before, "a REMAND performs no allotment write"


def test_a_concur_review_finalizes_scores_the_record_and_writes_the_allotment():
    """CONCUR is the opposite branch and carries the whole side-effect set in one hop: the
    assessment reaches FINALIZED with a composite of 52.95, the MEETING_WITH_PROBLEMS band is
    selected, the allotment's health_determination is overwritten from NOT_ASSESSED and its version
    moves by exactly 1 — while its stocking_adjustment_pct stays 0, because a finalized assessment
    recommends and never reduces.

    PRD 3.7: "A `CONCUR` outcome moves `FIELD_REVIEW → FINALIZED`, computes `composite_score` and
    `determination`, computes `recommended_reduction_pct`, writes the resulting `determination` onto
    the allotment's `health_determination`, and bumps the allotment's `version`."
    PRD 3.7: "Multiply `upland_score` by 0.40, `riparian_score` by 0.35 and `water_quality_score` by
    0.25, add the three products, and round the sum half-up to 2 decimal places; the result is
    `composite_score`."
    PRD 3.7: "The `determination` follows by band: `MEETING` when `composite_score` is at least 70,
    `MEETING_WITH_PROBLEMS` when `composite_score` is at least 50 but less than 70, and
    `NOT_MEETING` in every remaining case, that is when it is below 50."
    PRD 3.7: "The recommendation is advisory: it becomes binding only when an officer carries it
    into a stocking-adjustment decision, as §3.8 describes."

    Design: Corner/state_machines/corner_assessment_concur_finalizes_and_writes_allotment_determination
    """
    allotment = create_allotment(admin_unit_code="QB-119", total_permitted_aums=560,
                                 acres=16000, required_pasture_rotation_count=1)
    assessment = _draft_assessment(allotment["id"], assessment_year=2026,
                                   monitoring_method="INDICATOR_ASSESSMENT",
                                   upland_score=62, riparian_score=44, water_quality_score=51,
                                   standards_not_met=["UPLAND_HEALTH"],
                                   causal_factor_is_livestock=True)
    get_success_data(_submit(assessment["id"]))
    version_before = get_allotment(allotment["id"])["version"]

    finalized = get_success_data(_review(
        assessment["id"], "CONCUR", "Concur with the interdisciplinary team findings."))

    assert finalized["assessment_status"] == "FINALIZED"
    # 62 x 0.40 + 44 x 0.35 + 51 x 0.25 = 24.8 + 15.4 + 12.75
    assert finalized["composite_score"] == pytest.approx(52.95, abs=0.005)
    assert finalized["determination"] == "MEETING_WITH_PROBLEMS", "50 <= 52.95 < 70"
    assert finalized["remand_count"] == 0

    after = get_allotment(allotment["id"])
    assert after["health_determination"] == "MEETING_WITH_PROBLEMS"
    assert after["version"] == version_before + 1
    assert_pct(after["stocking_adjustment_pct"], 0.0)
    assert after["effective_capacity_aums"] == 560
    assert after["allotment_status"] == "OPEN"


def _stocking_decision_ground(admin_unit_code, total_permitted_aums, acres):
    """An allotment carrying the FINALIZED assessment a STOCKING_ADJUSTMENT decision must name.

    The assessment is scored 80/80/80 so its determination is MEETING; concurrence bumps the
    allotment version, so the caller reads the version after this returns, never before.
    """
    allotment = create_allotment(admin_unit_code=admin_unit_code,
                                 total_permitted_aums=total_permitted_aums, acres=acres,
                                 required_pasture_rotation_count=1)
    assessment = finalized_assessment(allotment["id"], assessment_year=2026)
    assert assessment["assessment_status"] == "FINALIZED"
    return allotment, assessment


def test_an_authored_decision_lands_in_draft_with_only_the_authors_own_fields_written():
    """Creation writes the client's inputs and the DRAFT/PENDING posture and nothing more: the
    specialist who posted it becomes authoring_officer_id, deciding_officer_id and
    pre_decision_adjustment_pct are still null, and although the allotment's version moves by
    exactly 1 its stocking_adjustment_pct is untouched — a DRAFT decision cascades nothing.

    PRD 3.8: "The new decision lands in `decision_status` `DRAFT` with `nepa_status` `PENDING`,
    `nepa_findings_summary` null, `pre_decision_adjustment_pct` null, `deciding_officer_id` null and
    `effective_date` null unless supplied, and its `authoring_officer_id` is stamped with the
    authoring specialist's `X-User-ID`."
    PRD 3.8: "Authorship itself bumps the allotment's `version`, which means two decisions authored
    back to back against the same allotment cannot both quote the same `expected_allotment_version`;
    the second author must re-read the allotment first."
    PRD 3.8: "A `STOCKING_ADJUSTMENT` decision is allotment-wide, so its `permit_id` may be null,
    but it requires a non-null `assessment_id` naming the finalized assessment that justifies it and
    a non-null `adjustment_pct` strictly greater than 0 and at most 0.9 carried to at most 4 decimal
    places."

    Design: Corner/state_machines/corner_permit_decision_initial_state_is_draft
    """
    allotment, assessment = _stocking_decision_ground("QB-120", 540, 15500)
    version_before = get_allotment(allotment["id"])["version"]

    decision = get_success_data(api_client.create_decision(
        f.decision_payload(allotment["id"], version_before,
                           decision_type="STOCKING_ADJUSTMENT", nepa_level="CX",
                           assessment_id=assessment["id"], adjustment_pct=0.2,
                           effective_date="2026-09-01"),
        make_specialist_headers(SPECIALIST_1)), 201)

    assert decision["decision_status"] == "DRAFT"
    assert decision["nepa_status"] == "PENDING"
    assert decision["nepa_findings_summary"] is None
    assert decision["authoring_officer_id"] == SPECIALIST_1
    assert decision["deciding_officer_id"] is None
    assert_pct(decision["adjustment_pct"], 0.2)
    assert decision["pre_decision_adjustment_pct"] is None

    after = get_allotment(allotment["id"])
    assert after["version"] == version_before + 1
    assert_pct(after["stocking_adjustment_pct"], 0.0)
    assert after["effective_capacity_aums"] == 540
    assert after["allotment_status"] == "OPEN"


def test_signing_an_ea_decision_needs_a_rationale_even_though_nepa_review_is_complete():
    """The environmental-review gate is not satisfied by nepa_status alone: an EA-level decision
    signed with no rationale is refused HTTP 409 ERR_ENVIRONMENTAL_REVIEW_INCOMPLETE and stays
    PROPOSED with no deciding officer, while the identical call carrying a 63-character rationale
    signs it into FINAL.

    PRD 2.6: "**Environmental review gate** — `ERR_ENVIRONMENTAL_REVIEW_INCOMPLETE`, HTTP 409, on
    decision signature only. Signing requires `nepa_status` to be `COMPLETE` and
    `nepa_findings_summary` to be non-empty; a decision whose `nepa_level` is `EA` or `EIS`
    additionally requires a `rationale` of at least 20 characters."
    PRD 3.8: "On success `decision_status` becomes `FINAL`, `deciding_officer_id` is stamped with
    the signing officer's `X-User-ID`, and the `rationale` is stored."
    PRD 3.8: "On success the `nepa_findings_summary` is stored, `nepa_status` becomes `COMPLETE`,
    and the decision moves `DRAFT → PROPOSED` in the same operation, so completing the review and
    proposing the decision are one act rather than two."

    Design: Corner/state_machines/corner_decision_finalize_without_rationale_on_ea_rejected
    """
    allotment, assessment = _stocking_decision_ground("QB-121", 520, 15000)
    decision = proposed_decision(
        allotment["id"], decision_type="STOCKING_ADJUSTMENT", nepa_level="EA",
        assessment_id=assessment["id"], adjustment_pct=0.15, effective_date="2026-09-01")
    assert decision["nepa_status"] == "COMPLETE"
    assert decision["decision_status"] == "PROPOSED"

    validate_error(
        api_client.finalize_decision(decision["id"], {}, make_officer_headers(OFFICER_1)),
        ApiErrorId.ERR_ENVIRONMENTAL_REVIEW_INCOMPLETE, 409)

    held = get_decision(decision["id"])
    assert held["decision_status"] == "PROPOSED"
    assert held["deciding_officer_id"] is None

    rationale = "Reduce stocking to restore upland trend on the burned north pasture."
    signed = get_success_data(api_client.finalize_decision(
        decision["id"], f.finalize_payload(rationale=rationale),
        make_officer_headers(OFFICER_1)))
    assert signed["decision_status"] == "FINAL"
    assert signed["deciding_officer_id"] == OFFICER_1


def test_a_voided_instruction_can_never_be_issued_and_raises_no_bill():
    """VOIDED is terminal for an instruction: issuing one is refused HTTP 409
    ERR_AOI_STATE_INVALID, the row stays VOIDED, no PRELIMINARY_USE bill is raised, and the
    allotment's ledger still shows the whole 500 AUMs open because a voided instruction reserves
    nothing.

    PRD 3.4: "Issuing the instruction is the transition `DRAFT → ISSUED`, reserved to an
    `AuthorizedOfficer` and taking no request body."
    PRD 2.6: "**Transition legality** — HTTP 409 with the entity-specific state code. The subject
    record must be in a state from which the requested transition is declared, and every same-entity
    precondition of that transition must hold."
    PRD 2.9: "Instructions in `DRAFT` or `VOIDED` contribute nothing, and instructions for any
    other grazing year contribute nothing; the window is exactly the allotment's
    `current_grazing_year`, inclusive of both ends of that calendar year."
    PRD 3.4: "When `billable_aums` is greater than zero, a preliminary bill of `bill_type`
    `PRELIMINARY_USE` is raised, computed by the preliminary variant of the use-bill arithmetic in
    §3.6, and the permittee's `outstanding_balance_cents` is recomputed to include it."

    Design: Corner/state_machines/corner_aoi_issue_from_voided_rejected
    """
    setup = drafted_aoi_setup(
        authorized_aums=100, planned_head_count=60, planned_entry_date="2026-05-01",
        planned_exit_date="2026-06-01", total_permitted_aums=500, pasture_aum_capacity=300,
        carrying_capacity_aums=200, requested_aums=200, term_end_date="2030-12-31",
        allotment_overrides={"admin_unit_code": "QB-122", "acres": 14000})
    voided = void_aoi(setup["aoi"]["id"],
                      void_reason="Permittee withdrew the grazing application for 2026.")
    assert voided["aoi_status"] == "VOIDED"

    validate_error(
        api_client.issue_aoi(setup["aoi"]["id"], make_officer_headers()),
        ApiErrorId.ERR_AOI_STATE_INVALID, 409)

    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "VOIDED"
    assert list_bills(aoi_id=setup["aoi"]["id"]) == [], "the refused issue raised no bill"

    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allocated_aums"] == 0
    assert allotment["open_aums"] == 500


def test_lifting_an_already_lifted_order_is_refused_and_does_not_re_run_the_cascade():
    """LIFTED is terminal: the second lift answers HTTP 409 ERR_CLOSURE_ORDER_STATE_INVALID, and
    the proof that no cascade ran a second time is the allotment version standing exactly where the
    first lift left it, with the posture already restored to OPEN at full capacity.

    PRD 3.10: "An `AuthorizedOfficer` lifts an order that is in `order_status` `ACTIVE`, optionally
    recording a fresh `justification`; lifting one already `LIFTED` or `EXPIRED` is
    `ERR_CLOSURE_ORDER_STATE_INVALID`."
    PRD 3.10: "The order moves `ACTIVE → LIFTED` and the identical five-hop cascade re-runs over the
    **remaining** sources, so a lift recomputes rather than subtracts: lifting a 0.40 drought order
    while a 0.30 effective stocking adjustment survives leaves the allotment at 0.30 and
    `RESTRICTED`, not at 0.0 and `OPEN`."
    PRD 2.4: "Because `version` moves on side-effect mutations as well as direct ones, an
    allotment's `version` advances whenever its capacity ledger, posture or health determination is
    rewritten — when a closure order is issued or lifted, when a health assessment is finalized with
    a concurrence, when a decision document is authored against it, and when a decision is made
    effective or vacated."

    Design: Corner/state_machines/corner_closure_order_lift_twice_rejected
    """
    allotment = create_allotment(admin_unit_code="QB-123", total_permitted_aums=800,
                                 acres=22000, required_pasture_rotation_count=1)
    order = create_closure_order(
        allotment["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.25,
        effective_start_date="2026-08-05", effective_end_date="2026-10-31",
        justification="Below-average spring precipitation across the unit.")
    assert order["order_status"] == "ACTIVE"

    lifted = lift_closure_order(order["id"])
    assert lifted["order_status"] == "LIFTED"
    version_after_first_lift = get_allotment(allotment["id"])["version"]

    validate_error(
        api_client.lift_closure_order(
            order["id"], f.lift_payload(justification="Duplicate lift submitted by the field office."),
            make_officer_headers()),
        ApiErrorId.ERR_CLOSURE_ORDER_STATE_INVALID, 409)

    assert get_closure_order(order["id"])["order_status"] == "LIFTED"
    after = get_allotment(allotment["id"])
    assert after["version"] == version_after_first_lift, "no second cascade ran"
    assert_pct(after["stocking_adjustment_pct"], 0.0)
    assert after["effective_capacity_aums"] == 800
    assert after["allotment_status"] == "OPEN"


def _stayed_decision_setup(admin_unit_code, total_permitted_aums, acres, permittee_name,
                           permittee_email, adjustment_pct):
    """A FINAL STOCKING_ADJUSTMENT decision frozen into STAYED by a permittee's appeal."""
    allotment, assessment = _stocking_decision_ground(admin_unit_code, total_permitted_aums, acres)
    permittee = create_permittee(name=permittee_name, contact_email=permittee_email)
    decision = signed_decision(
        allotment["id"], decision_type="STOCKING_ADJUSTMENT", nepa_level="CX",
        assessment_id=assessment["id"], adjustment_pct=adjustment_pct,
        effective_date="2026-09-01")
    assert decision["decision_status"] == "FINAL"
    appeal = filed_appeal(decision["id"], permittee["id"], stay_requested=True)
    assert appeal["appeal_status"] == "FILED"
    assert appeal["stay_granted"] is True
    assert get_decision(decision["id"])["decision_status"] == "STAYED"
    return {"allotment": allotment, "permittee": permittee, "decision": decision,
            "appeal": appeal}


def test_docketing_takes_the_case_up_stamps_the_adjudicator_and_leaves_the_stay_alone():
    """FILED → UNDER_REVIEW writes exactly one field of its own: adjudicator_id from the docketing
    adjudicator's X-User-ID. The stay granted at filing is not revisited, remand_count stays 0, and
    the appealed decision is still STAYED with the allotment untouched — docketing has no cascade.

    PRD 3.9: "Docketing is the `AppealsAdjudicator`'s act of taking the case up, and it moves
    `appeal_status` `FILED → UNDER_REVIEW` while stamping `adjudicator_id` with the docketing
    adjudicator's `X-User-ID`."
    PRD 3.9: "Docketing does **not** touch `stay_granted`: the stay was granted or refused at
    filing time and is not revisited here."
    PRD 3.9: "No allotment, permit, instruction or bill field is written by the stay; it is a pure
    hold."

    Design: Corner/state_machines/corner_appeal_docket_moves_filed_to_under_review
    """
    setup = _stayed_decision_setup("QB-124", 760, 21000, "Docket Probe Ranch",
                                   "docket@example.com", 0.3)

    docketed = get_success_data(api_client.docket_appeal(
        setup["appeal"]["id"], make_adjudicator_headers(JUDGE_1)))

    assert docketed["appeal_status"] == "UNDER_REVIEW"
    assert docketed["adjudicator_id"] == JUDGE_1
    assert docketed["stay_granted"] is True
    assert docketed["remand_count"] == 0

    assert get_decision(setup["decision"]["id"])["decision_status"] == "STAYED"
    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.0)
    assert allotment["effective_capacity_aums"] == 760


def test_an_appeal_cannot_be_decided_before_it_has_been_docketed():
    """Deciding is legal only from UNDER_REVIEW, so a REVERSE aimed at a merely FILED case answers
    HTTP 409 ERR_APPEAL_STATE_INVALID: the case keeps its null adjudicator and, crucially, the
    decision is still STAYED rather than VACATED — the reversal cannot skip the docket.

    PRD 3.9: "The case must be in `appeal_status` `UNDER_REVIEW`, else `ERR_APPEAL_STATE_INVALID`,
    and the acting `X-User-ID` must equal `adjudicator_id` — the adjudicator who docketed the case is
    the only one who may decide it, and anyone else is `ERR_UNAUTHORIZED`."
    PRD 3.9: "The new case lands in `appeal_status` `FILED` with `remand_count` 0 and
    `adjudicator_id` null."
    PRD 3.8: "Reversing an appeal against a decision that is merely `STAYED` moves it `STAYED →
    VACATED` and runs **no** cascade at all, because a stayed decision never applied its effects."

    Design: Corner/state_machines/corner_appeal_decide_before_docketing_rejected
    """
    setup = _stayed_decision_setup("QB-125", 740, 20500, "Skip Docket Ranch",
                                   "skipdocket@example.com", 0.2)

    validate_error(
        api_client.decide_appeal(
            setup["appeal"]["id"],
            f.appeal_decision_payload("REVERSE",
                                      decision_rationale="Attempted reversal without docketing."),
            make_adjudicator_headers(JUDGE_1)),
        ApiErrorId.ERR_APPEAL_STATE_INVALID, 409)

    unchanged = get_appeal(setup["appeal"]["id"])
    assert unchanged["appeal_status"] == "FILED"
    assert unchanged["adjudicator_id"] is None
    assert get_decision(setup["decision"]["id"])["decision_status"] == "STAYED"


def _final_bill_setup():
    """A 2026 instruction authorized at 100 AUMs whose single 60-head, 31-day leg has been reported
    and accepted, so a FINAL_USE bill of 10,664 cents stands and the preliminary 17,200-cent bill
    has been voided in its favour."""
    setup = issued_aoi_setup(
        authorized_aums=100, planned_head_count=60, planned_entry_date="2026-05-01",
        planned_exit_date="2026-06-01", total_permitted_aums=700, pasture_aum_capacity=300,
        carrying_capacity_aums=250, requested_aums=200, term_end_date="2030-12-31",
        allotment_overrides={"admin_unit_code": "QB-126", "acres": 19000})
    preliminary = setup["preliminary_bill"]
    assert preliminary["total_amount_cents"] == 17200  # 100 authorized AUMs x 172, admin fee 0
    get_success_data(api_client.report_actual_use(
        setup["use_record"]["id"],
        f.report_actual_use_payload(actual_entry_date="2026-05-01",
                                    actual_exit_date="2026-06-01", actual_head_count=60),
        make_permittee_headers(setup["permittee"]["id"])))
    accepted = accept_use_report(setup["aoi"]["id"])
    assert accepted["aoi_status"] == "BILLED"
    finals = [b for b in list_bills(aoi_id=setup["aoi"]["id"], bill_type="FINAL_USE")
              if b["bill_status"] != "VOIDED"]
    assert len(finals) == 1
    setup["final_bill"] = finals[0]
    return setup


def test_paying_the_final_bill_settles_the_debt_the_account_and_the_grazing_year_at_once():
    """One payment request runs three hops on entities the payer never named: the bill reaches PAID,
    the permittee's balance falls to 0 and back to IN_GOOD_STANDING, and because no non-voided bill
    of the instruction is left unpaid the instruction itself moves BILLED → CLOSED — while the
    permit's authorization axis never leaves ISSUED.

    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."
    PRD 3.6: "The permittee's `outstanding_balance_cents` and `permittee_status` are then
    recomputed, and four consequential effects follow in turn: when the paid bill was an
    `UNAUTHORIZED_USE` bill, its linked trespass incident moves `BILLED → RESOLVED`; when every
    non-voided bill of the linked operating instruction has reached `PAID`, that instruction moves
    `BILLED → CLOSED`; when the permittee is left with no bill in `bill_status` `DELINQUENT`, every
    permit of that permittee whose `permit_status` is `PENDING_REVIEW`, `ISSUED` or `SUSPENDED`
    moves `account_status` `DELINQUENT → CURRENT`; and a permit that was `SUSPENDED` with
    `suspension_reason` `NONPAYMENT` then moves `SUSPENDED → ISSUED` with its `suspension_reason`
    cleared to null."
    PRD 3.6: "When the preliminary bill's `amount_paid_cents` is exactly 0, that bill moves to
    `bill_status` `VOIDED` and a bill of `bill_type` `FINAL_USE` is issued for the final total with
    `superseded_bill_id` set to the voided bill's `id`."
    PRD 3.6: "Step three selects the tiered administrative fee **from `base_amount_cents`, never
    from the total**: `admin_fee_cents` is 0 when `base_amount_cents` is below 50,000 cents, 2,500
    cents when `base_amount_cents` is at least 50,000 and below 200,000 cents, and 6,000 cents when
    `base_amount_cents` is 200,000 cents or more."

    Design: Corner/state_machines/corner_bill_payment_cascades_to_permittee_permit_and_aoi
    """
    setup = _final_bill_setup()
    bill = setup["final_bill"]
    # billed_aums is max(62.00 actual, floor(100 / 4) = 25) = 62.00; 62 x 172 = 10,664 < 50,000
    assert bill["total_amount_cents"] == 10664
    assert bill["admin_fee_cents"] == 0
    assert bill["bill_status"] == "ISSUED"
    assert bill["superseded_bill_id"] == setup["preliminary_bill"]["id"]
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 10664

    paid = get_success_data(api_client.record_payment(
        bill["id"], f.payment_payload(10664),
        make_permittee_headers(setup["permittee"]["id"])), 201)

    assert paid["bill_status"] == "PAID"
    assert paid["amount_paid_cents"] == 10664

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["outstanding_balance_cents"] == 0
    assert permittee["permittee_status"] == "IN_GOOD_STANDING"

    permit = get_permit(setup["permit"]["id"])
    assert permit["account_status"] == "CURRENT"
    assert permit["permit_status"] == "ISSUED"

    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "CLOSED"
    record = get_use_record(setup["use_record"]["id"])
    assert record["record_status"] == "ACCEPTED"
    assert_aums(record["actual_aums"], 62.00)


def test_closing_the_allotment_terminates_its_approved_projects_without_being_asked_to():
    """The closure order names only the allotment, yet a FULL_CLOSURE takes the approved water
    development with it: the project moves APPROVED → TERMINATED with its 160,000-cent pot frozen
    and nothing allocated, and a cost-share allocation on the terminated project is then refused
    with ERR_PROJECT_STATE_INVALID.

    PRD 3.12: "When the allotment moves to `allotment_status` `CLOSED` — which happens when a
    `WILDFIRE_CLOSURE` or `FULL_CLOSURE` order takes effect — every project of that allotment still
    in `project_status` `APPROVED` moves to `project_status` `TERMINATED` as a side effect, with no
    bill raised and `allocated_share_cents` left at 0."
    PRD 3.12: "On success `project_status` becomes `APPROVED` and `permittee_share_cents` is set to
    `total_cost_cents` multiplied by `permittee_share_pct`, rounded half-up to a whole cent."
    PRD 3.10: "It is exactly 1.0 when any closure order on the allotment in `order_status` `ACTIVE`
    has `order_type` `WILDFIRE_CLOSURE` or `FULL_CLOSURE`."
    PRD 3.12: "Both `COST_ALLOCATED` and `TERMINATED` are terminal."

    Design: Corner/state_machines/corner_project_terminated_when_allotment_closes
    """
    allotment = create_allotment(admin_unit_code="QB-127", total_permitted_aums=680,
                                 acres=18500, required_pasture_rotation_count=1)
    project = create_project(allotment["id"], project_type="WATER_DEVELOPMENT",
                             total_cost_cents=400000, agency_share_pct=0.6,
                             permittee_share_pct=0.4,
                             maintenance_responsibility="PERMITTEE")
    assert project["project_status"] == "PROPOSED"
    approved = approve_project(project["id"])
    assert approved["project_status"] == "APPROVED"
    assert approved["permittee_share_cents"] == 160000  # 400,000 x 0.4
    assert approved["allocated_share_cents"] == 0

    order = create_closure_order(
        allotment["id"], order_type="FULL_CLOSURE", reduction_pct=1.0,
        effective_start_date="2026-08-10", effective_end_date="2026-12-31",
        justification="Allotment closed for the remainder of the year pending land health review.")
    assert order["order_status"] == "ACTIVE"
    assert_pct(order["reduction_pct"], 1.0)

    shut = get_allotment(allotment["id"])
    assert shut["allotment_status"] == "CLOSED"
    assert_pct(shut["stocking_adjustment_pct"], 1.0)
    assert shut["effective_capacity_aums"] == 0

    terminated = get_project(project["id"])
    assert terminated["project_status"] == "TERMINATED"
    assert terminated["permittee_share_cents"] == 160000
    assert terminated["allocated_share_cents"] == 0

    validate_error(
        api_client.allocate_cost_share(project["id"], make_officer_headers()),
        ApiErrorId.ERR_PROJECT_STATE_INVALID, 409)
    assert get_project(project["id"])["project_status"] == "TERMINATED"
