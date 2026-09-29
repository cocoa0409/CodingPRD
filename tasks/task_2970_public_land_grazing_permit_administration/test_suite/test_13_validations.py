"""Rejection probes: which of several simultaneously broken rules answers first, which code names
which entity, and what the register looks like once the refusal has been issued."""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_pct,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_use_report,
    add_use_record,
    approve_nonuse,
    authored_decision,
    bill_trespass_incident,
    create_allotment,
    create_aoi,
    create_base_property,
    create_pasture,
    create_permit,
    create_permittee,
    create_project,
    create_trespass_incident,
    finalized_assessment,
    get_allotment,
    get_aoi,
    get_assessment,
    get_bill,
    get_decision,
    get_pasture,
    get_permit,
    get_permittee,
    get_project,
    get_trespass_incident,
    get_use_record,
    issue_aoi,
    issue_permit,
    list_bills,
    pay_bill,
    remanded_assessment,
    report_actual_use,
    void_aoi,
)


def _permit_count(permittee_id):
    _items, meta = validate_paginated(api_client.list_permits(
        make_officer_headers(), params={"permittee_id": permittee_id}))
    return meta["total_count"]


def _use_record_count(aoi_id):
    _items, meta = validate_paginated(api_client.list_use_records(
        make_officer_headers(), params={"aoi_id": aoi_id}))
    return meta["total_count"]


def _applicant(name, email, carrying_capacity_aums):
    permittee = create_permittee(name=name, contact_email=email)
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         carrying_capacity_aums=carrying_capacity_aums)
    return permittee, base_property


def test_the_missing_livestock_kind_answers_before_the_inverted_term_dates():
    """One body breaks two rules at once — no livestock_kind and a term that ends four years before
    it starts — and the shape check at priority 1 is what answers, so the client sees ERR_VALIDATION
    rather than ERR_INVALID_DATE_RANGE. Supplying the kind and retrying the identical dates then
    surfaces the next check down, exactly as the normative ordering promises, and neither rejection
    leaves a permit behind.

    PRD 2.6: "When a single request violates more than one rule, exactly one error is returned, and
    which one is fully determined."
    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."
    PRD 2.6: "This ordering is normative — a client that fixes the reported problem and retries will
    then see the next-highest violated check, and never the reverse."
    PRD 2.6: "A permit's `term_start_date` must be strictly before its `term_end_date`; an operating
    instruction's `season_start_date` must be on or before its `season_end_date`; a use record's
    `planned_entry_date` must be strictly before its `planned_exit_date` and, when actual use is
    reported, its `actual_entry_date` must be strictly before its `actual_exit_date`, because a
    grazing window is half-open and a zero-length window is never valid; and a closure order's
    `effective_start_date` must be on or before its `effective_end_date`."
    PRD 3.3: "An application is filed by an `AuthorizedOfficer` naming the `allotment_id` the
    preference attaches to, the `permittee_id` who will hold it, the `base_property_id` that
    qualifies it, the `requested_aums` of preference sought (at least 1), the `term_start_date` and
    `term_end_date` bounding the term, and the `livestock_kind`, which is `CATTLE`, `SHEEP` or
    `HORSES`."

    Design: Corner/validations/corner_missing_required_field_outranks_bad_date_range
    """
    allotment = create_allotment(admin_unit_code="QB-138", total_permitted_aums=380, acres=11000,
                                 required_pasture_rotation_count=1)
    permittee, base_property = _applicant("Priority Ladder Ranch", "ladder@example.com", 200)

    inverted = f.permit_payload(allotment["id"], permittee["id"], base_property["id"],
                                requested_aums=100, term_start_date="2030-12-31",
                                term_end_date="2026-01-01")
    without_kind = dict(inverted)
    del without_kind["livestock_kind"]

    validate_error(api_client.create_permit(without_kind, make_officer_headers()),
                   ApiErrorId.ERR_VALIDATION, 400)
    validate_error(api_client.create_permit(inverted, make_officer_headers()),
                   ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

    assert _permit_count(permittee["id"]) == 0, "neither rejected call created a row"


def test_each_unresolvable_identifier_answers_with_its_own_not_found_code():
    """Eleven path reads and two body foreign keys all miss, and not one of them collapses into a
    generic not-found: every refusal is a 404 naming the entity that could not be resolved, and the
    two write probes leave the register untouched.

    PRD 2.6: "Each entity has its own not-found code: an allotment yields
    `ERR_ALLOTMENT_NOT_FOUND`, a pasture `ERR_PASTURE_NOT_FOUND`, a permittee
    `ERR_PERMITTEE_NOT_FOUND`, a base property `ERR_BASE_PROPERTY_NOT_FOUND`, a grazing permit
    `ERR_PERMIT_NOT_FOUND`, an annual operating instruction `ERR_AOI_NOT_FOUND`, a pasture use record
    `ERR_USE_RECORD_NOT_FOUND`, a grazing bill `ERR_BILL_NOT_FOUND`, a rangeland health assessment
    `ERR_ASSESSMENT_NOT_FOUND`, a permit decision `ERR_DECISION_NOT_FOUND`, an appeal case
    `ERR_APPEAL_NOT_FOUND`, a closure order `ERR_CLOSURE_ORDER_NOT_FOUND`, a trespass incident
    `ERR_TRESPASS_NOT_FOUND` and a range improvement project `ERR_PROJECT_NOT_FOUND`."
    PRD 2.6: "All fourteen carry HTTP 404."
    PRD 2.6: "Foreign keys sent in a request **body** are resolved with the same fourteen-code
    mapping, in the order in which the fields are listed for that operation in §4's request
    description and in §3's narrative."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left to
    right as described at the top of this subsection."

    Design: Corner/validations/corner_unknown_ids_return_their_own_not_found_code
    """
    allotment = create_allotment(admin_unit_code="QB-139", total_permitted_aums=360, acres=10500,
                                 required_pasture_rotation_count=1)
    permittee, base_property = _applicant("Not Found Probe Ranch", "notfound@example.com", 200)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")

    unknown = NON_EXISTENT_UUID
    reader = make_specialist_headers()
    path_probes = [
        (api_client.get_permittee(unknown, reader), ApiErrorId.ERR_PERMITTEE_NOT_FOUND),
        (api_client.get_permit(unknown, reader), ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (api_client.get_aoi(unknown, reader), ApiErrorId.ERR_AOI_NOT_FOUND),
        (api_client.get_use_record(unknown, reader), ApiErrorId.ERR_USE_RECORD_NOT_FOUND),
        (api_client.get_bill(unknown, reader), ApiErrorId.ERR_BILL_NOT_FOUND),
        (api_client.get_assessment(unknown, reader), ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (api_client.get_decision(unknown, reader), ApiErrorId.ERR_DECISION_NOT_FOUND),
        (api_client.get_appeal(unknown, reader), ApiErrorId.ERR_APPEAL_NOT_FOUND),
        (api_client.get_closure_order(unknown, reader), ApiErrorId.ERR_CLOSURE_ORDER_NOT_FOUND),
        (api_client.get_trespass_incident(unknown, reader), ApiErrorId.ERR_TRESPASS_NOT_FOUND),
        (api_client.get_project(unknown, reader), ApiErrorId.ERR_PROJECT_NOT_FOUND),
    ]
    for response, expected in path_probes:
        validate_error(response, expected, 404)

    validate_error(api_client.create_permit(
        f.permit_payload(allotment["id"], permittee["id"], unknown, requested_aums=100),
        make_officer_headers()), ApiErrorId.ERR_BASE_PROPERTY_NOT_FOUND, 404)
    validate_error(api_client.create_use_record(
        aoi["id"], f.use_record_payload(unknown, planned_head_count=60,
                                        planned_entry_date="2026-05-01",
                                        planned_exit_date="2026-06-01"),
        make_specialist_headers()), ApiErrorId.ERR_PASTURE_NOT_FOUND, 404)

    assert _permit_count(permittee["id"]) == 1, "the rejected application created nothing"
    assert _use_record_count(aoi["id"]) == 0


def test_the_three_state_refusals_each_name_their_own_subject():
    """Re-issuing an issued permit, re-reporting a reported leg and paying a paid bill are all 409s
    at the same priority, and each answers with the code of the entity whose transition was
    illegal — never one shared conflict code. None of the three refusals writes anything: the leg
    keeps its 60 head and 62.00 AUMs and the settled bill keeps its 17,200 cents.

    PRD 2.6: "**Transition legality** — HTTP 409 with the entity-specific state code."
    PRD 2.6: "A grazing permit yields `ERR_PERMIT_STATE_INVALID`, an operating instruction
    `ERR_AOI_STATE_INVALID`, a use record `ERR_USE_RECORD_STATE_INVALID`, a bill
    `ERR_BILL_STATE_INVALID`, an assessment `ERR_ASSESSMENT_STATE_INVALID`, a decision
    `ERR_DECISION_STATE_INVALID`, an appeal `ERR_APPEAL_STATE_INVALID`, a closure order
    `ERR_CLOSURE_ORDER_STATE_INVALID`, a trespass incident `ERR_TRESPASS_STATE_INVALID` and a project
    `ERR_PROJECT_STATE_INVALID`."
    PRD 3.5: "The owning instruction must be in `aoi_status` `ISSUED`; the leg must still be in
    `record_status` `SCHEDULED`, since reporting against a record already in `ACTUAL_REPORTED` or
    `ACCEPTED` is `ERR_USE_RECORD_STATE_INVALID`; `actual_exit_date` must be strictly after
    `actual_entry_date`; and the reported window must sit inside the instruction's declared season, so
    `actual_entry_date` must be on or after `season_start_date` and `actual_exit_date` on or before
    `season_end_date`, failing which the answer is `ERR_SEASON_OF_USE_VIOLATION`."
    PRD 3.6: "The target bill must be in `bill_status` `ISSUED` or `DELINQUENT`; paying one already
    `PAID` or `VOIDED` is `ERR_BILL_STATE_INVALID`."
    PRD 3.3: "Issuance is the transition `PENDING_REVIEW → ISSUED`, performed by an
    `AuthorizedOfficer` with no request body at all: the `permitted_aums` stored at application time
    is the figure that governs, and it is not re-read from the request."

    Design: Corner/validations/corner_state_invalid_codes_name_the_subject_entity
    """
    allotment = create_allotment(admin_unit_code="QB-140", total_permitted_aums=520, acres=14500,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="State Code Pasture",
                             pasture_aum_capacity=300, sequence_order=1)
    permittee, base_property = _applicant("State Code Ranch", "statecode@example.com", 200)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    leg = add_use_record(aoi["id"], pasture["id"], planned_head_count=60, livestock_kind="CATTLE",
                         planned_entry_date="2026-05-01", planned_exit_date="2026-06-01")
    issue_aoi(aoi["id"])
    reported = report_actual_use(leg["id"], actual_entry_date="2026-05-01",
                                actual_exit_date="2026-06-01", actual_head_count=60)
    assert reported["record_status"] == "ACTUAL_REPORTED"
    bill = [b for b in list_bills(aoi_id=aoi["id"], bill_type="PRELIMINARY_USE")
            if b["bill_status"] != "VOIDED"][0]
    assert pay_bill(bill["id"], 17200)["bill_status"] == "PAID"

    validate_error(api_client.issue_permit(permit["id"], make_officer_headers()),
                   ApiErrorId.ERR_PERMIT_STATE_INVALID, 409)
    validate_error(api_client.report_actual_use(
        leg["id"], f.report_actual_use_payload(actual_entry_date="2026-05-02",
                                               actual_exit_date="2026-06-01",
                                               actual_head_count=55),
        make_specialist_headers()), ApiErrorId.ERR_USE_RECORD_STATE_INVALID, 409)
    validate_error(api_client.record_payment(
        bill["id"], f.payment_payload(1), make_permittee_headers(permittee["id"])),
        ApiErrorId.ERR_BILL_STATE_INVALID, 409)

    assert get_permit(permit["id"])["permit_status"] == "ISSUED"
    unchanged = get_use_record(leg["id"])
    assert unchanged["actual_head_count"] == 60
    assert_aums(unchanged["actual_aums"], 62.00)
    settled = get_bill(bill["id"])
    assert settled["amount_paid_cents"] == 17200
    assert get_permittee(permittee["id"])["outstanding_balance_cents"] == 0


def test_signing_a_draft_decision_reports_the_wrong_state_and_not_the_missing_rationale():
    """The decision is DRAFT and its EA-level signature also lacks the required rationale, so two
    gates are broken at once; the transition-legality check at priority 8 outranks the environmental
    review gate at priority 11, so the answer is ERR_DECISION_STATE_INVALID and never
    ERR_ENVIRONMENTAL_REVIEW_INCOMPLETE. The refusal writes nothing at all.

    PRD 2.6: "**Transition legality** — HTTP 409 with the entity-specific state code."
    PRD 2.6: "**Environmental review gate** — `ERR_ENVIRONMENTAL_REVIEW_INCOMPLETE`, HTTP 409, on
    decision signature only."
    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."
    PRD 3.8: "The decision must be in `decision_status` `PROPOSED`, else
    `ERR_DECISION_STATE_INVALID`."
    PRD 3.8: "The new decision lands in `decision_status` `DRAFT` with `nepa_status` `PENDING`,
    `nepa_findings_summary` null, `pre_decision_adjustment_pct` null, `deciding_officer_id` null and
    `effective_date` null unless supplied, and its `authoring_officer_id` is stamped with the
    authoring specialist's `X-User-ID`."

    Design: Corner/validations/corner_finalize_from_draft_returns_decision_state_invalid_not_nepa
    """
    allotment = create_allotment(admin_unit_code="QB-141", total_permitted_aums=500, acres=14200,
                                 required_pasture_rotation_count=1)
    # PRD 3.8 requires a STOCKING_ADJUSTMENT decision to name a finalized assessment.
    assessment = finalized_assessment(allotment["id"], assessment_year=2026)
    decision = authored_decision(
        allotment["id"], decision_type="STOCKING_ADJUSTMENT", nepa_level="EA",
        assessment_id=assessment["id"], adjustment_pct=0.1, effective_date="2026-09-15")
    assert decision["decision_status"] == "DRAFT"
    assert decision["nepa_status"] == "PENDING"

    validate_error(api_client.finalize_decision(decision["id"], {}, make_officer_headers()),
                   ApiErrorId.ERR_DECISION_STATE_INVALID, 409)

    unchanged = get_decision(decision["id"])
    assert unchanged["decision_status"] == "DRAFT"
    assert unchanged["nepa_status"] == "PENDING"
    assert unchanged["deciding_officer_id"] is None
    assert_pct(get_allotment(allotment["id"])["stocking_adjustment_pct"], 0.0)


def test_re_billing_a_billed_incident_and_allocating_an_unapproved_project_are_both_refused():
    """The two enforcement instruments refuse on their own state and answer with their own code: a
    second bill against an already-BILLED incident is ERR_TRESPASS_STATE_INVALID and does not
    increment the permittee's counter a second time, and allocating a project that was never approved
    is ERR_PROJECT_STATE_INVALID with the pot still unfixed at 0 and no bill raised.

    PRD 3.11: "The incident must be in `incident_status` `DETECTED`, else
    `ERR_TRESPASS_STATE_INVALID`, and its `permittee_id` must be non-null — an incident whose owner is
    still undetermined cannot be billed, and attempting it is `ERR_TRESPASS_STATE_INVALID`."
    PRD 3.2: "the trespass counter is itself derived: it is the number of trespass incidents
    attributed to this permittee whose `incident_status` is `BILLED` or `RESOLVED`."
    PRD 2.6: "**Cost-share preconditions** — `ERR_PROJECT_STATE_INVALID`, HTTP 409, on cost-share
    allocation."
    PRD 3.12: "The project lands in `project_status` `PROPOSED` with `permittee_share_cents` and
    `allocated_share_cents` both 0."
    PRD 3.12: "Allocation distributes that pot across the operators and is likewise an
    `AuthorizedOfficer`'s act, requiring `project_status` `APPROVED` on pain of
    `ERR_PROJECT_STATE_INVALID`."

    Design: Corner/validations/corner_trespass_rebill_and_unapproved_allocation_rejected
    """
    allotment = create_allotment(admin_unit_code="QB-142", total_permitted_aums=480, acres=13800,
                                 required_pasture_rotation_count=1)
    permittee = create_permittee(name="Enforcement State Ranch", contact_email="enforce@example.com")
    incident = create_trespass_incident(
        allotment["id"], permittee["id"], detected_at="2026-07-15T08:00:00Z", head_count=31,
        livestock_kind="CATTLE", unauthorized_days=20, willfulness="NON_WILLFUL")
    assert bill_trespass_incident(incident["id"])["incident_status"] == "BILLED"
    project = create_project(allotment["id"], project_type="FENCE", total_cost_cents=120000,
                             agency_share_pct=0.5, permittee_share_pct=0.5,
                             maintenance_responsibility="PERMITTEE")
    assert project["project_status"] == "PROPOSED"

    validate_error(api_client.bill_trespass_incident(incident["id"], make_officer_headers()),
                   ApiErrorId.ERR_TRESPASS_STATE_INVALID, 409)
    validate_error(api_client.allocate_cost_share(project["id"], make_officer_headers()),
                   ApiErrorId.ERR_PROJECT_STATE_INVALID, 409)

    assert get_trespass_incident(incident["id"])["incident_status"] == "BILLED"
    assert get_permittee(permittee["id"])["billed_trespass_incident_count"] == 1, "not 2"
    assert len(list_bills(trespass_incident_id=incident["id"])) == 1

    stalled = get_project(project["id"])
    assert stalled["project_status"] == "PROPOSED"
    assert stalled["permittee_share_cents"] == 0
    assert stalled["allocated_share_cents"] == 0
    assert list_bills(project_id=project["id"]) == []


def test_a_not_meeting_determination_blocks_issuance_while_the_range_is_still_open():
    """Scores of 30 across the board finalize at 30.00 and stamp the allotment NOT_MEETING, and that
    alone refuses the issuance: the allotment is still OPEN with all 480 AUMs unspoken for, so
    neither posture nor capacity can be what answers, and the application is left in PENDING_REVIEW.

    PRD 2.6: "**Rangeland standards gate** — `ERR_HEALTH_STANDARDS_NOT_MET`, HTTP 409, on permit
    issuance, permit renewal and permit transfer."
    PRD 2.6: "A permit may not be issued, renewed or transferred onto an allotment whose
    `health_determination` is `NOT_MEETING` unless a permit decision of `decision_type`
    `STOCKING_ADJUSTMENT` on that allotment has already reached `decision_status` `EFFECTIVE`."
    PRD 3.7: "The `determination` follows by band: `MEETING` when `composite_score` is at least 70,
    `MEETING_WITH_PROBLEMS` when `composite_score` is at least 50 but less than 70, and `NOT_MEETING`
    in every remaining case, that is when it is below 50."
    PRD 3.7: "Under `INDICATOR_ASSESSMENT`, take 0.10 for each standard code listed in
    `standards_not_met`, add a further 0.10 when `causal_factor_is_livestock` is true, cap the result
    at 0.50, and round half-up to 4 decimal places; `observed_utilization_pct` is ignored entirely."
    PRD 3.7: "A `CONCUR` outcome moves `FIELD_REVIEW → FINALIZED`, computes `composite_score` and
    `determination`, computes `recommended_reduction_pct`, writes the resulting `determination` onto
    the allotment's `health_determination`, and bumps the allotment's `version`."

    Design: Corner/validations/corner_permit_issue_blocked_by_not_meeting_health
    """
    allotment = create_allotment(admin_unit_code="QB-143", total_permitted_aums=480, acres=13500,
                                 required_pasture_rotation_count=1)
    permittee, base_property = _applicant("Health Gate Ranch", "healthgate@example.com", 200)
    permit = create_permit(allotment["id"], permittee["id"], base_property["id"],
                          requested_aums=100)

    assessment = finalized_assessment(
        allotment["id"], assessment_year=2026, upland_score=30, riparian_score=30,
        water_quality_score=30, standards_not_met=["UPLAND_HEALTH", "RIPARIAN_FUNCTION"],
        causal_factor_is_livestock=True)
    assert assessment["composite_score"] == 30.00
    assert assessment["determination"] == "NOT_MEETING"
    assert_pct(assessment["recommended_reduction_pct"], 0.3000)  # 0.1 x 2 standards + 0.1 adder

    posture = get_allotment(allotment["id"])
    assert posture["health_determination"] == "NOT_MEETING"
    assert posture["allotment_status"] == "OPEN", "the gate is health, not posture"
    assert posture["open_aums"] == 480

    validate_error(api_client.issue_permit(permit["id"], make_officer_headers()),
                   ApiErrorId.ERR_HEALTH_STANDARDS_NOT_MET, 409)

    assert get_permit(permit["id"])["permit_status"] == "PENDING_REVIEW"
    assert get_allotment(allotment["id"])["allocated_aums"] == 0


def test_a_neighbours_base_property_is_not_owned_rather_than_not_found_or_too_small():
    """The property resolves perfectly and is more than large enough at 500 qualified AUMs, so
    neither the 404 family nor the preference-qualification gate can be what refuses: it belongs to
    another operator, which is a 422 ERR_BASE_PROPERTY_NOT_OWNED, and the applicant is left with no
    permit at all.

    PRD 2.6: "**Base-property ownership** — `ERR_BASE_PROPERTY_NOT_OWNED`, HTTP 422, on permit
    application, permit renewal and permit transfer."
    PRD 2.6: "The `base_property_id` carried by the request must belong to the permittee who will
    hold the resulting permit."
    PRD 3.3: "At this stage the named base property must belong to the named permittee, on pain of
    `ERR_BASE_PROPERTY_NOT_OWNED`, and `requested_aums` must fit within that property's
    `qualified_aums`, on pain of `ERR_INSUFFICIENT_QUALIFIED_AUMS`."
    PRD 3.2: "The property's `qualified_aums` is its `carrying_capacity_aums` multiplied by that
    factor, floored to a whole AUM."

    Design: Corner/validations/corner_base_property_must_belong_to_the_applicant
    """
    allotment = create_allotment(admin_unit_code="QB-144", total_permitted_aums=470, acres=13200,
                                 required_pasture_rotation_count=1)
    applicant = create_permittee(name="Ownership Applicant Ranch",
                                 contact_email="ownapplicant@example.com")
    neighbour, neighbours_property = _applicant("Ownership Neighbour Ranch",
                                                "ownneighbour@example.com", 500)
    assert neighbours_property["qualified_aums"] == 500, "priority 16 would have passed"

    validate_error(api_client.create_permit(
        f.permit_payload(allotment["id"], applicant["id"], neighbours_property["id"],
                         requested_aums=100), make_officer_headers()),
        ApiErrorId.ERR_BASE_PROPERTY_NOT_OWNED, 422)

    assert _permit_count(applicant["id"]) == 0
    assert _permit_count(neighbour["id"]) == 0, "nor did the property's owner acquire one"


def test_a_pasture_on_another_allotment_is_refused_before_capacity_is_ever_consulted():
    """The pasture exists and has 300 AUMs of room, but it hangs off a different allotment than the
    instruction's permit, so the locality rule answers with a 422 ERR_PASTURE_NOT_IN_ALLOTMENT rather
    than a 404 or a capacity complaint. No leg is stored, both pastures still read 0 scheduled AUMs,
    and the identical call against the instruction's own allotment is accepted at 62.00.

    PRD 2.6: "**Pasture locality** — `ERR_PASTURE_NOT_IN_ALLOTMENT`, HTTP 422, on use-record
    scheduling."
    PRD 2.6: "The `pasture_id` must name a pasture whose `allotment_id` equals the allotment of the
    instruction's permit."
    PRD 3.1: "Its `scheduled_aums` is the sum of `planned_aums` over every use record naming that
    pasture whose owning operating instruction has a `grazing_year` equal to the allotment's
    `current_grazing_year` and an `aoi_status` of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`; the
    figure is carried to 2 decimal places and starts at 0."
    PRD 3.4: "Round the result half-up to 2 decimal places, exactly once."

    Design: Corner/validations/corner_use_record_pasture_must_belong_to_the_allotment
    """
    home = create_allotment(admin_unit_code="QB-145", total_permitted_aums=460, acres=13100,
                            required_pasture_rotation_count=1)
    home_pasture = create_pasture(home["id"], name="Home Pasture", pasture_aum_capacity=300,
                                  sequence_order=1)
    neighbour = create_allotment(admin_unit_code="QB-146", total_permitted_aums=450, acres=13000,
                                 required_pasture_rotation_count=1)
    neighbour_pasture = create_pasture(neighbour["id"], name="Neighbour Pasture",
                                       pasture_aum_capacity=300, sequence_order=1)
    permittee, base_property = _applicant("Cross Pasture Ranch", "crosspasture@example.com", 200)
    permit = issue_permit(create_permit(home["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")

    foreign_leg = f.use_record_payload(neighbour_pasture["id"], planned_head_count=60,
                                       planned_entry_date="2026-05-01",
                                       planned_exit_date="2026-06-01")
    validate_error(api_client.create_use_record(aoi["id"], foreign_leg, make_specialist_headers()),
                   ApiErrorId.ERR_PASTURE_NOT_IN_ALLOTMENT, 422)

    assert _use_record_count(aoi["id"]) == 0
    assert_aums(get_pasture(neighbour_pasture["id"])["scheduled_aums"], 0)
    assert_aums(get_pasture(home_pasture["id"])["scheduled_aums"], 0)

    # Control: the only thing wrong with the call was which allotment the pasture sits on.
    accepted = get_success_data(api_client.create_use_record(
        aoi["id"], f.use_record_payload(home_pasture["id"], planned_head_count=60,
                                        planned_entry_date="2026-05-01",
                                        planned_exit_date="2026-06-01"),
        make_specialist_headers()), 201)
    assert_aums(accepted["planned_aums"], 62.00)


def test_a_renewal_may_start_on_the_predecessors_last_day_but_never_before_it():
    """A successor term opening two years inside the predecessor's own term is refused with a 422
    ERR_PREDECESSOR_PERMIT_INVALID, and the refusal expires nothing and creates nothing. Moving the
    start to the predecessor's last day exactly is accepted, so the comparison is on-or-after rather
    than strictly-after.

    PRD 2.6: "**Preference chain** — `ERR_PREDECESSOR_PERMIT_INVALID`, HTTP 422, on permit renewal
    and permit transfer."
    PRD 2.6: "The predecessor permit named by the path must be in `permit_status` `ISSUED`, must not
    already have a successor (no other permit may carry the same `predecessor_permit_id`), and on
    renewal the new `term_start_date` must fall on or after the predecessor's `term_end_date`."
    PRD 3.3: "The predecessor must be in `permit_status` `ISSUED`, must not already have a successor,
    and the new `term_start_date` must fall on or after the predecessor's `term_end_date`, all three
    failures reporting `ERR_PREDECESSOR_PERMIT_INVALID`."
    PRD 3.3: "On success the predecessor moves to `permit_status` `EXPIRED`, and a successor permit is
    created carrying `predecessor_permit_id` pointing at the predecessor, `permit_status` `ISSUED`,
    `account_status` `CURRENT`, the same `permittee_id`, `allotment_id`, `base_property_id`,
    `permitted_aums` and `livestock_kind` as the predecessor, and the supplied term dates."

    Design: Corner/validations/corner_renewal_term_must_not_start_before_predecessor_ends
    """
    allotment = create_allotment(admin_unit_code="QB-147", total_permitted_aums=1000, acres=29000,
                                 required_pasture_rotation_count=1)
    permittee, base_property = _applicant("Renewal Order Ranch", "renewalorder@example.com", 300)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=150, term_start_date="2026-01-01",
                                       term_end_date="2030-12-31")["id"])

    validate_error(api_client.renew_permit(
        permit["id"], f.renew_payload(base_property["id"], requested_aums=150,
                                      term_start_date="2029-01-01",
                                      term_end_date="2033-12-31"), make_officer_headers()),
        ApiErrorId.ERR_PREDECESSOR_PERMIT_INVALID, 422)

    assert get_permit(permit["id"])["permit_status"] == "ISSUED", "the predecessor was not expired"
    _items, meta = validate_paginated(api_client.list_permits(
        make_officer_headers(), params={"predecessor_permit_id": permit["id"]}))
    assert meta["total_count"] == 0, "no successor row was created"

    # Control: the same renewal starting on the predecessor's own last day is accepted.
    successor = get_success_data(api_client.renew_permit(
        permit["id"], f.renew_payload(base_property["id"], requested_aums=150,
                                      term_start_date="2030-12-31",
                                      term_end_date="2033-12-31"), make_officer_headers()), 201)
    assert successor["predecessor_permit_id"] == permit["id"]
    assert successor["consecutive_nonuse_years"] == 0
    assert get_permit(permit["id"])["permit_status"] == "EXPIRED"


def test_preference_is_capped_by_qualified_aums_and_not_by_carrying_capacity():
    """A livestock property carrying 200 AUMs qualifies only 150 of them, and it is the qualified
    figure the application is measured against: 200 requested AUMs are refused with a 422
    ERR_INSUFFICIENT_QUALIFIED_AUMS, while 150 on the very same property is accepted and then survives
    the identical re-check at issuance.

    PRD 2.6: "**Preference qualification** — `ERR_INSUFFICIENT_QUALIFIED_AUMS`, HTTP 422, on permit
    application, permit issuance, permit renewal and permit transfer."
    PRD 2.6: "The `requested_aums` must not exceed the `qualified_aums` of the named base property; a
    permittee with no base property of the required kind cannot hold preference at all."
    PRD 2.6: "The same comparison is re-run at issuance against the stored `permitted_aums`, which is
    why the issuance transition has an error mapping even though a conforming application can never
    fail it."
    PRD 3.2: "Controlled livestock qualifies at three-quarters strength: the factor for a `LIVESTOCK`
    property is 0.75."
    PRD 3.2: "`qualified_aums` is the ceiling on how much preference the property can support on a
    permit, and it is what priority 16 compares `requested_aums` against."

    Design: Corner/validations/corner_application_requires_enough_qualified_aums
    """
    allotment = create_allotment(admin_unit_code="QB-148", total_permitted_aums=440, acres=12800,
                                 required_pasture_rotation_count=1)
    permittee = create_permittee(name="Qualification Cap Ranch", contact_email="qualcap@example.com")
    livestock = create_base_property(
        permittee["id"], base_property_type="LIVESTOCK", carrying_capacity_aums=200,
        legal_description="200 head under a five-year private lease",
        controlled_since_date="1996-06-06")
    assert livestock["qualified_aums"] == 150  # floor(200 x 0.75)
    assert livestock["carrying_capacity_aums"] == 200

    validate_error(api_client.create_permit(
        f.permit_payload(allotment["id"], permittee["id"], livestock["id"], requested_aums=200),
        make_officer_headers()), ApiErrorId.ERR_INSUFFICIENT_QUALIFIED_AUMS, 422)
    assert _permit_count(permittee["id"]) == 0

    # Control: at exactly the qualified figure the application stands, and so does the re-check.
    accepted = create_permit(allotment["id"], permittee["id"], livestock["id"], requested_aums=150)
    assert accepted["permit_status"] == "PENDING_REVIEW"
    assert accepted["permitted_aums"] == 150
    assert issue_permit(accepted["id"])["permit_status"] == "ISSUED", "150 <= 150 holds"


def test_the_permit_year_slot_is_held_by_the_live_instruction_only():
    """A second instruction for the same permit and the same 2026 is refused with a 409
    ERR_DUPLICATE_AOI_FOR_YEAR even though the incumbent has never been issued; voiding the incumbent
    releases the slot and the identical create then succeeds, leaving two rows for the year of which
    only one is live.

    PRD 2.6: "**One instruction per permit-year** — `ERR_DUPLICATE_AOI_FOR_YEAR`, HTTP 409, on
    operating-instruction creation."
    PRD 2.6: "At most one instruction per permit and `grazing_year` may exist in an `aoi_status` other
    than `VOIDED`; voiding an instruction frees the slot so that a replacement may be created for the
    same year."
    PRD 3.4: "Voiding a `DRAFT` instruction simply marks it `VOIDED`: it held no allocation, so the
    allotment's `allocated_aums` and `open_aums` are recomputed and come back unchanged."
    PRD 3.4: "Because a voided instruction frees its permit-year slot, a replacement instruction may
    then be drafted for the same `grazing_year`."

    Design: Corner/validations/corner_duplicate_aoi_for_year_rejected_until_the_first_is_voided
    """
    allotment = create_allotment(admin_unit_code="QB-149", total_permitted_aums=430, acres=12700,
                                 required_pasture_rotation_count=1)
    permittee, base_property = _applicant("Duplicate AOI Ranch", "dupaoi@example.com", 200)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    incumbent = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                           season_start_date="2026-01-01", season_end_date="2026-12-31")

    replacement_payload = f.aoi_payload(permit["id"], grazing_year=2026, authorized_aums=80,
                                        season_start_date="2026-03-01",
                                        season_end_date="2026-10-31")
    validate_error(api_client.create_aoi(replacement_payload, make_specialist_headers()),
                   ApiErrorId.ERR_DUPLICATE_AOI_FOR_YEAR, 409)

    assert void_aoi(incumbent["id"],
                    void_reason="Replaced by a revised set of instructions.")["aoi_status"] == "VOIDED"

    replacement = get_success_data(api_client.create_aoi(replacement_payload,
                                                        make_specialist_headers()), 201)
    assert replacement["aoi_status"] == "DRAFT"
    assert replacement["authorized_aums"] == 80
    assert replacement["authorized_aums_at_issue"] == 80

    _items, meta = validate_paginated(api_client.list_aois(
        make_officer_headers(), params={"permit_id": permit["id"], "grazing_year": 2026}))
    assert meta["total_count"] == 2, "the voided row stays on the register beside the live one"
    assert get_allotment(allotment["id"])["allocated_aums"] == 0, "neither was ever issued"


def test_the_allotment_year_slot_for_an_assessment_is_held_from_the_draft_onward():
    """A second 2026 assessment is refused with a 409 ERR_DUPLICATE_ASSESSMENT_FOR_YEAR while the
    incumbent is still merely DRAFT, so the rule bites long before anything is finalized; the same
    call for 2025 is accepted, and with nothing finalized the allotment is still NOT_ASSESSED.

    PRD 2.6: "**One assessment per allotment-year** — `ERR_DUPLICATE_ASSESSMENT_FOR_YEAR`, HTTP 409,
    on assessment creation and on assessment review."
    PRD 2.6: "At most one assessment per allotment and `assessment_year` may reach `FINALIZED`, and at
    most one may sit in `DRAFT` or `FIELD_REVIEW` at a time."
    PRD 3.7: "At most one assessment per allotment and `assessment_year` may ever reach `FINALIZED`,
    and at most one may sit in `DRAFT` or `FIELD_REVIEW` at a time, either violation being
    `ERR_DUPLICATE_ASSESSMENT_FOR_YEAR`."
    PRD 3.1: "Its `allotment_status` is `OPEN`, its `health_determination` is `NOT_ASSESSED`, its
    `stocking_adjustment_pct` is 0, and its capacity ledger reads `effective_capacity_aums` equal to
    `total_permitted_aums`, `allocated_aums` of 0 and `open_aums` equal to `total_permitted_aums`."

    Design: Corner/validations/corner_duplicate_assessment_for_year_rejected
    """
    allotment = create_allotment(admin_unit_code="QB-150", total_permitted_aums=420, acres=12600,
                                 required_pasture_rotation_count=1)
    incumbent = get_success_data(api_client.create_assessment(
        f.assessment_payload(allotment["id"], assessment_year=2026, standards_not_met=[],
                             causal_factor_is_livestock=False), make_specialist_headers()), 201)
    assert incumbent["assessment_status"] == "DRAFT"

    validate_error(api_client.create_assessment(
        f.assessment_payload(allotment["id"], assessment_year=2026,
                             monitoring_method="UTILIZATION_MAPPING", upland_score=75,
                             riparian_score=75, water_quality_score=75,
                             observed_utilization_pct=60), make_specialist_headers()),
        ApiErrorId.ERR_DUPLICATE_ASSESSMENT_FOR_YEAR, 409)

    earlier_year = get_success_data(api_client.create_assessment(
        f.assessment_payload(allotment["id"], assessment_year=2025,
                             monitoring_method="UTILIZATION_MAPPING", upland_score=75,
                             riparian_score=75, water_quality_score=75,
                             observed_utilization_pct=60), make_specialist_headers()), 201)
    assert earlier_year["assessment_year"] == 2025
    assert earlier_year["assessment_status"] == "DRAFT"

    _items, meta = validate_paginated(api_client.list_assessments(
        make_officer_headers(), params={"allotment_id": allotment["id"]}))
    assert meta["total_count"] == 2
    assert get_allotment(allotment["id"])["health_determination"] == "NOT_ASSESSED"


def test_the_rotation_sequence_refuses_both_a_duplicate_position_and_a_gap():
    """Both failure modes of the one rule answer with the same 409 ERR_PASTURE_SEQUENCE_CONFLICT: a
    second pasture at position 1 collides, and a pasture at position 3 has nothing at position 2 to
    follow. Filling 2 and then 3 in order is accepted, so the rule is density from 1 rather than a
    ceiling on the sequence.

    PRD 2.6: "**Rotation sequence integrity** — `ERR_PASTURE_SEQUENCE_CONFLICT`, HTTP 409, on pasture
    creation."
    PRD 2.6: "`sequence_order` is unique within its allotment and the sequence must be dense from 1:
    creating position N requires that position N−1 already exists on that allotment."
    PRD 3.1: "The `sequence_order` fixes the pasture's position in the required rotation sequence: it
    must be at least 1, must be unique within the allotment, and the sequence must be dense from 1, so
    creating position 4 on an allotment that has only positions 1, 2 and 3 succeeds while creating
    position 5 on that same allotment is `ERR_PASTURE_SEQUENCE_CONFLICT`."
    PRD 3.1: "Pastures are listed either beneath their allotment in rotation order or across the whole
    inventory, narrowed by `allotment_id` or by `rest_required`."

    Design: Corner/validations/corner_pasture_sequence_must_be_unique_and_dense
    """
    allotment = create_allotment(admin_unit_code="QB-151", total_permitted_aums=410, acres=12500,
                                 required_pasture_rotation_count=1)
    first = create_pasture(allotment["id"], name="Sequence One", pasture_aum_capacity=200,
                           sequence_order=1)

    validate_error(api_client.create_pasture(
        allotment["id"], f.pasture_payload(name="Sequence One Again", pasture_aum_capacity=200,
                                           sequence_order=1), make_officer_headers()),
        ApiErrorId.ERR_PASTURE_SEQUENCE_CONFLICT, 409)
    validate_error(api_client.create_pasture(
        allotment["id"], f.pasture_payload(name="Sequence Three Too Early",
                                           pasture_aum_capacity=200, sequence_order=3),
        make_officer_headers()), ApiErrorId.ERR_PASTURE_SEQUENCE_CONFLICT, 409)

    second = create_pasture(allotment["id"], name="Sequence Two", pasture_aum_capacity=200,
                            sequence_order=2)
    third = create_pasture(allotment["id"], name="Sequence Three", pasture_aum_capacity=200,
                           sequence_order=3)
    assert second["sequence_order"] == 2
    assert third["sequence_order"] == 3

    items, meta = validate_paginated(api_client.list_allotment_pastures(
        allotment["id"], make_officer_headers()))
    assert meta["total_count"] == 3
    assert [p["id"] for p in items] == [first["id"], second["id"], third["id"]], "rotation order"


def test_both_clauses_of_the_rotation_rule_answer_with_the_same_code():
    """The default rotation count of 2 is what an allotment carries when the officer never supplies
    one, and both of priority 20's clauses fail into the same 422 ERR_ROTATION_REQUIREMENT_NOT_MET: one
    instruction schedules a single pasture, the other schedules two but includes the rested one.
    Neither refusal allocates anything, and adding a second unrested leg makes the first issue call
    succeed.

    PRD 2.6: "**Rotation requirement** — `ERR_ROTATION_REQUIREMENT_NOT_MET`, HTTP 422, on
    operating-instruction issuance."
    PRD 2.6: "The instruction's `distinct_pasture_count` must be at least the allotment's
    `required_pasture_rotation_count`, and every pasture of that allotment whose `rest_required` is
    true must be absent from the instruction's use records."
    PRD 3.1: "The officer may also supply `required_pasture_rotation_count`, the minimum number of
    distinct pastures an operating instruction must schedule before it may be issued; when omitted it
    defaults to 2, and it must be at least 1."
    PRD 3.4: "Once the leg is stored, the instruction's `planned_aums_total` is recomputed as the sum
    of `planned_aums` over **all** of its use records regardless of `record_status`, its
    `distinct_pasture_count` as the number of distinct `pasture_id` values across all of those
    records, and the named pasture's `scheduled_aums` roll-up is refreshed."

    Design: Corner/validations/corner_aoi_issue_enforces_rotation_count_and_rested_pastures
    """
    default_count = f.allotment_payload(name="Rotation Rule Allotment", admin_unit_code="QB-152",
                                        acres=27000, total_permitted_aums=900)
    del default_count["required_pasture_rotation_count"]
    allotment = get_success_data(api_client.create_allotment(default_count,
                                                           make_officer_headers()), 201)
    assert allotment["required_pasture_rotation_count"] == 2, "the omitted field defaults to 2"

    first = create_pasture(allotment["id"], name="Rotation Pasture One", pasture_aum_capacity=300,
                           sequence_order=1, rest_required=False)
    second = create_pasture(allotment["id"], name="Rotation Pasture Two", pasture_aum_capacity=300,
                            sequence_order=2, rest_required=False)
    rested = create_pasture(allotment["id"], name="Rotation Pasture Three Rested",
                            pasture_aum_capacity=300, sequence_order=3, rest_required=True)

    permittee_a, property_a = _applicant("Rotation Ranch A", "rotationa@example.com", 200)
    permit_a = issue_permit(create_permit(allotment["id"], permittee_a["id"], property_a["id"],
                                         requested_aums=100)["id"])
    permittee_b, property_b = _applicant("Rotation Ranch B", "rotationb@example.com", 200)
    permit_b = issue_permit(create_permit(allotment["id"], permittee_b["id"], property_b["id"],
                                         requested_aums=100)["id"])

    # Both instructions are drafted before either is issued, so no preliminary bill exists yet.
    too_few = create_aoi(permit_a["id"], grazing_year=2026, authorized_aums=150,
                         season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(too_few["id"], first["id"], planned_head_count=60, livestock_kind="CATTLE",
                   planned_entry_date="2026-05-01", planned_exit_date="2026-06-01")
    uses_rested = create_aoi(permit_b["id"], grazing_year=2026, authorized_aums=150,
                             season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(uses_rested["id"], first["id"], planned_head_count=60, livestock_kind="CATTLE",
                   planned_entry_date="2026-06-05", planned_exit_date="2026-07-05")
    add_use_record(uses_rested["id"], rested["id"], planned_head_count=60, livestock_kind="CATTLE",
                   planned_entry_date="2026-07-10", planned_exit_date="2026-08-09")
    assert get_aoi(uses_rested["id"])["distinct_pasture_count"] == 2, "the count clause is satisfied"

    validate_error(api_client.issue_aoi(too_few["id"], make_officer_headers()),
                   ApiErrorId.ERR_ROTATION_REQUIREMENT_NOT_MET, 422)
    validate_error(api_client.issue_aoi(uses_rested["id"], make_officer_headers()),
                   ApiErrorId.ERR_ROTATION_REQUIREMENT_NOT_MET, 422)

    assert get_aoi(too_few["id"])["aoi_status"] == "DRAFT"
    assert get_aoi(uses_rested["id"])["aoi_status"] == "DRAFT"
    refused = get_allotment(allotment["id"])
    assert refused["allocated_aums"] == 0
    assert refused["open_aums"] == 900

    # Control: a second unrested leg lifts distinct_pasture_count to the required 2.
    add_use_record(too_few["id"], second["id"], planned_head_count=60, livestock_kind="CATTLE",
                   planned_entry_date="2026-06-05", planned_exit_date="2026-07-05")
    issued = issue_aoi(too_few["id"])
    assert issued["aoi_status"] == "ISSUED"
    assert issued["distinct_pasture_count"] == 2
    assert_aums(issued["planned_aums_total"], 122.00)  # 62.00 + 60.00
    after = get_allotment(allotment["id"])
    assert after["allocated_aums"] == 150
    assert after["open_aums"] == 750


def test_the_remand_ceiling_bounds_the_field_review_loop_and_never_the_concurrence():
    """Two remands are spent legitimately; the third is refused with a 409
    ERR_ASSESSMENT_REMAND_LIMIT_EXCEEDED that neither increments the counter nor moves the row out of
    FIELD_REVIEW. From that same FIELD_REVIEW the reviewer may still concur, so the ceiling bounds only
    the rejection branch.

    PRD 2.6: "**Assessment remand ceiling** — `ERR_ASSESSMENT_REMAND_LIMIT_EXCEEDED`, HTTP 409, on
    assessment review."
    PRD 2.6: "A review that sends the assessment back to `DRAFT` may happen at most twice per
    assessment; the third such rejection is refused, and the reviewer must concur or the assessment
    must be abandoned."
    PRD 3.7: "A `REMAND` outcome moves `FIELD_REVIEW → DRAFT`, increments the assessment's
    `remand_count` by 1, and does **nothing else at all** — no score is computed, no determination is
    written, and the allotment is not touched in any way."
    PRD 3.7: "A remand is permitted at most twice per assessment; a third remand is refused with
    `ERR_ASSESSMENT_REMAND_LIMIT_EXCEEDED`, leaving the reviewer to concur or the assessment to be
    abandoned."
    PRD 3.7: "A `CONCUR` outcome moves `FIELD_REVIEW → FINALIZED`, computes `composite_score` and
    `determination`, computes `recommended_reduction_pct`, writes the resulting `determination` onto
    the allotment's `health_determination`, and bumps the allotment's `version`."

    Design: Corner/validations/corner_third_assessment_remand_rejected
    """
    allotment = create_allotment(admin_unit_code="QB-153", total_permitted_aums=300, acres=9000,
                                 required_pasture_rotation_count=1)
    once = remanded_assessment(allotment["id"], assessment_year=2026)
    assert once["assessment_status"] == "DRAFT"
    assert once["remand_count"] == 1

    get_success_data(api_client.submit_assessment(once["id"], make_specialist_headers()))
    twice = get_success_data(api_client.review_assessment(
        once["id"], f.review_payload("REMAND",
                                     review_notes="Second remand: riparian photo points missing."),
        make_officer_headers()))
    assert twice["assessment_status"] == "DRAFT"
    assert twice["remand_count"] == 2
    resubmitted = get_success_data(api_client.submit_assessment(once["id"],
                                                              make_specialist_headers()))
    assert resubmitted["assessment_status"] == "FIELD_REVIEW"

    validate_error(api_client.review_assessment(
        once["id"], f.review_payload("REMAND", review_notes="Third remand attempt."),
        make_officer_headers()), ApiErrorId.ERR_ASSESSMENT_REMAND_LIMIT_EXCEEDED, 409)

    refused = get_assessment(once["id"])
    assert refused["assessment_status"] == "FIELD_REVIEW", "the refusal did not move the row"
    assert refused["remand_count"] == 2, "a refused remand does not count"
    assert refused["composite_score"] is None

    finalized = get_success_data(api_client.review_assessment(
        once["id"], f.review_payload("CONCUR", review_notes="Accepted after two remands."),
        make_officer_headers()))
    assert finalized["assessment_status"] == "FINALIZED"
    assert finalized["composite_score"] == pytest.approx(80.00, abs=0.005)
    assert finalized["determination"] == "MEETING"
    assert get_allotment(allotment["id"])["health_determination"] == "MEETING"


def test_one_unreported_leg_blocks_acceptance_of_the_whole_year():
    """Completeness is judged leg by leg: with one of two legs reported the acceptance is refused with
    a 409 ERR_ACTUAL_USE_INCOMPLETE and the instruction stays ISSUED. Reporting the outstanding leg
    makes the identical call carry the instruction through both hops to BILLED and move every leg to
    ACCEPTED.

    PRD 2.6: "**Use-report completeness** — `ERR_ACTUAL_USE_INCOMPLETE`, HTTP 409, on use-report
    acceptance."
    PRD 2.6: "The instruction must have at least one use record, and no record may still be in
    `record_status` `SCHEDULED`."
    PRD 3.5: "Before the first hop the instruction must have at least one use record and no record may
    still be in `record_status` `SCHEDULED`; otherwise the request is refused with
    `ERR_ACTUAL_USE_INCOMPLETE`."
    PRD 3.5: "The second hop moves every use record of the instruction from `ACTUAL_REPORTED` to
    `ACCEPTED`, computes the final charge by the final variant of §3.6, settles the difference against
    the preliminary bill, sets `aoi_status` to `BILLED`, and recomputes the permittee's
    `outstanding_balance_cents`."
    PRD 3.5: "The instruction's `actual_aums_total` is then recomputed as the sum of `actual_aums` over
    its records whose `record_status` is `ACTUAL_REPORTED` or `ACCEPTED`; records still `SCHEDULED`
    contribute nothing, and `actual_aums` is null until the leg is reported."

    Design: Corner/validations/corner_accept_use_report_requires_every_record_reported
    """
    allotment = create_allotment(admin_unit_code="QB-154", total_permitted_aums=900, acres=24000,
                                 required_pasture_rotation_count=1)
    first = create_pasture(allotment["id"], name="Completeness Pasture One",
                           pasture_aum_capacity=300, sequence_order=1)
    second = create_pasture(allotment["id"], name="Completeness Pasture Two",
                            pasture_aum_capacity=300, sequence_order=2)
    permittee, base_property = _applicant("Completeness Ranch", "complete@example.com", 200)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                     season_start_date="2026-05-01", season_end_date="2026-09-30")
    reported_leg = add_use_record(aoi["id"], first["id"], planned_head_count=30,
                                  livestock_kind="CATTLE", planned_entry_date="2026-05-01",
                                  planned_exit_date="2026-05-31")
    pending_leg = add_use_record(aoi["id"], second["id"], planned_head_count=30,
                                 livestock_kind="CATTLE", planned_entry_date="2026-06-01",
                                 planned_exit_date="2026-07-01")
    assert issue_aoi(aoi["id"])["aoi_status"] == "ISSUED"
    report_actual_use(reported_leg["id"], actual_entry_date="2026-05-02",
                      actual_exit_date="2026-06-01", actual_head_count=30)

    validate_error(api_client.accept_use_report(aoi["id"], make_officer_headers()),
                   ApiErrorId.ERR_ACTUAL_USE_INCOMPLETE, 409)

    assert get_aoi(aoi["id"])["aoi_status"] == "ISSUED"
    still_scheduled = get_use_record(pending_leg["id"])
    assert still_scheduled["record_status"] == "SCHEDULED"
    assert still_scheduled["actual_aums"] is None

    caught_up = report_actual_use(pending_leg["id"], actual_entry_date="2026-06-02",
                                  actual_exit_date="2026-07-02", actual_head_count=30)
    assert caught_up["record_status"] == "ACTUAL_REPORTED"
    assert_aums(caught_up["actual_aums"], 30.00)

    billed = accept_use_report(aoi["id"])
    assert billed["aoi_status"] == "BILLED"
    assert_aums(billed["actual_aums_total"], 60.00)
    assert get_use_record(reported_leg["id"])["record_status"] == "ACCEPTED"
    assert get_use_record(pending_leg["id"])["record_status"] == "ACCEPTED"


def test_the_season_code_guards_the_instruction_window_the_plan_and_the_report_alike():
    """One code answers on three different surfaces: an instruction season reaching outside the
    allotment's recurring 04-01 to 10-31 window, a planned leg reaching outside the instruction season,
    and an actual window reported outside it. The first of those also outranks the debt gate, and it is
    the season code the client sees even though the permittee owes 17,200 cents at that moment.

    PRD 2.6: "**Season of use** — `ERR_SEASON_OF_USE_VIOLATION`, HTTP 422, on operating-instruction
    creation, use-record scheduling and actual-use reporting."
    PRD 2.6: "A use record's planned window, treated as half-open from `planned_entry_date` up to but
    excluding `planned_exit_date`, must fall entirely inside the closed interval from its instruction's
    `season_start_date` to its `season_end_date`; that instruction season must itself fall inside the
    allotment's recurring `season_start`-to-`season_end` window resolved against the instruction's
    `grazing_year`; and an actual window reported outside the instruction season is the same
    violation."
    PRD 2.6: "**Debt gate** — `ERR_OUTSTANDING_BALANCE`, HTTP 402, on permit issuance, permit renewal,
    permit transfer and operating-instruction creation."
    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."
    PRD 3.5: "The owning instruction must be in `aoi_status` `ISSUED`; the leg must still be in
    `record_status` `SCHEDULED`, since reporting against a record already in `ACTUAL_REPORTED` or
    `ACCEPTED` is `ERR_USE_RECORD_STATE_INVALID`; `actual_exit_date` must be strictly after
    `actual_entry_date`; and the reported window must sit inside the instruction's declared season, so
    `actual_entry_date` must be on or after `season_start_date` and `actual_exit_date` on or before
    `season_end_date`, failing which the answer is `ERR_SEASON_OF_USE_VIOLATION`."

    Design: Corner/validations/corner_season_of_use_bounds_both_planned_and_actual
    """
    allotment = create_allotment(admin_unit_code="QB-155", total_permitted_aums=500, acres=15000,
                                 season_start="04-01", season_end="10-31",
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Season Pasture One", pasture_aum_capacity=300,
                             sequence_order=1)
    permittee, base_property = _applicant("Season Ranch", "season@example.com", 200)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                     season_start_date="2026-05-01", season_end_date="2026-09-30")
    leg = add_use_record(aoi["id"], pasture["id"], planned_head_count=30, livestock_kind="CATTLE",
                         planned_entry_date="2026-06-01", planned_exit_date="2026-07-01")

    # Surface one, while the instruction is still DRAFT: the plan reaches before 2026-05-01.
    validate_error(api_client.create_use_record(
        aoi["id"], f.use_record_payload(pasture["id"], planned_entry_date="2026-04-15",
                                        planned_exit_date="2026-05-20", planned_head_count=30,
                                        livestock_kind="CATTLE"), make_specialist_headers()),
        ApiErrorId.ERR_SEASON_OF_USE_VIOLATION, 422)
    assert _use_record_count(aoi["id"]) == 1

    assert issue_aoi(aoi["id"])["aoi_status"] == "ISSUED"
    assert get_permittee(permittee["id"])["outstanding_balance_cents"] == 17200

    # Surface two: the 2027 instruction season opens on 03-01, outside the allotment's own window.
    validate_error(api_client.create_aoi(
        f.aoi_payload(permit["id"], grazing_year=2027, authorized_aums=100,
                      season_start_date="2027-03-01", season_end_date="2027-09-30"),
        make_specialist_headers()), ApiErrorId.ERR_SEASON_OF_USE_VIOLATION, 422)

    # Surface three: a leg that was legal when scheduled is reported outside the season.
    validate_error(api_client.report_actual_use(
        leg["id"], f.report_actual_use_payload(actual_entry_date="2026-09-15",
                                               actual_exit_date="2026-10-15",
                                               actual_head_count=30),
        make_specialist_headers()), ApiErrorId.ERR_SEASON_OF_USE_VIOLATION, 422)
    refused = get_use_record(leg["id"])
    assert refused["record_status"] == "SCHEDULED"
    assert refused["actual_aums"] is None

    inside = report_actual_use(leg["id"], actual_entry_date="2026-06-02",
                               actual_exit_date="2026-07-02", actual_head_count=30)
    assert inside["record_status"] == "ACTUAL_REPORTED"
    assert_aums(inside["actual_aums"], 30.00)


def test_capacity_is_re_read_at_issuance_rather_than_frozen_at_draft():
    """Two 60-AUM drafts both pass the creation check on a 100-AUM allotment because a draft consumes
    nothing; the first issues and takes 60, and the second — unchanged since it was accepted — is then
    refused with a 422 ERR_ALLOTMENT_CAPACITY_EXCEEDED. Voiding the first restores the 60 and the very
    same issue call succeeds, so the comparison is against the live open_aums at each moment.

    PRD 2.6: "**Allotment capacity** — `ERR_ALLOTMENT_CAPACITY_EXCEEDED`, HTTP 422, on
    operating-instruction creation, operating-instruction issuance, permit issuance, permit renewal and
    permit transfer."
    PRD 2.6: "At instruction creation the requested `authorized_aums` must not exceed the allotment's
    `open_aums` at that moment, and the same comparison is re-run at issuance against the then-current
    `open_aums`, so a capacity that shrank between draft and issue makes the issue fail even though the
    draft was accepted."
    PRD 3.4: "Crucially, a `DRAFT` instruction consumes nothing: capacity was checked against
    `open_aums` but not taken, and the allotment's `allocated_aums` does not move until the instruction
    is issued."
    PRD 3.4: "Voiding an instruction that had been issued does more: `aoi_status` becomes `VOIDED`,
    every bill of that instruction in `bill_status` `ISSUED` or `DELINQUENT` moves to `VOIDED`, the
    allotment's `allocated_aums` decreases by exactly that instruction's `billable_aums` while
    `open_aums` increases by the same amount — restoring the compensation invariant of §2.9 to the
    cent-exact AUM figure it held before issuance — `scheduled_aums` is refreshed on every pasture the
    instruction's records name, and the permittee's `outstanding_balance_cents` and the permit's
    `account_status` are re-derived."
    PRD 2.9: "The compensation invariant: if an allotment's `allocated_aums` is A before an operating
    instruction is issued, then after issuance it is A plus that instruction's `billable_aums`, and
    after that same instruction is voided it is A again — exactly A, with no drift — while `open_aums`
    returns to `effective_capacity_aums` less A."

    Design: Corner/validations/corner_allotment_capacity_checked_at_draft_and_again_at_issue
    """
    allotment = create_allotment(admin_unit_code="QB-156", total_permitted_aums=100, acres=3000,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Capacity Race Pasture",
                             pasture_aum_capacity=300, sequence_order=1)

    def issued_permit_for(name, email):
        permittee, base_property = _applicant(name, email, 60)
        return permittee, issue_permit(create_permit(
            allotment["id"], permittee["id"], base_property["id"], requested_aums=60)["id"])

    _permittee_a, permit_a = issued_permit_for("Race Ranch A", "racea@example.com")
    _permittee_b, permit_b = issued_permit_for("Race Ranch B", "raceb@example.com")
    _permittee_c, permit_c = issued_permit_for("Race Ranch C", "racec@example.com")

    first = create_aoi(permit_a["id"], grazing_year=2026, authorized_aums=60,
                       season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(first["id"], pasture["id"], planned_head_count=30, livestock_kind="CATTLE",
                   planned_entry_date="2026-05-01", planned_exit_date="2026-05-31")
    second = create_aoi(permit_b["id"], grazing_year=2026, authorized_aums=60,
                        season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(second["id"], pasture["id"], planned_head_count=30, livestock_kind="CATTLE",
                   planned_entry_date="2026-06-01", planned_exit_date="2026-07-01")

    assert issue_aoi(first["id"])["aoi_status"] == "ISSUED"
    committed = get_allotment(allotment["id"])
    assert committed["effective_capacity_aums"] == 100
    assert committed["allocated_aums"] == 60
    assert committed["open_aums"] == 40

    validate_error(api_client.issue_aoi(second["id"], make_officer_headers()),
                   ApiErrorId.ERR_ALLOTMENT_CAPACITY_EXCEEDED, 422)
    assert get_aoi(second["id"])["aoi_status"] == "DRAFT"

    validate_error(api_client.create_aoi(
        f.aoi_payload(permit_c["id"], grazing_year=2026, authorized_aums=41,
                      season_start_date="2026-01-01", season_end_date="2026-12-31"),
        make_specialist_headers()), ApiErrorId.ERR_ALLOTMENT_CAPACITY_EXCEEDED, 422)

    exactly_open = get_success_data(api_client.create_aoi(
        f.aoi_payload(permit_c["id"], grazing_year=2026, authorized_aums=40,
                      season_start_date="2026-01-01", season_end_date="2026-12-31"),
        make_specialist_headers()), 201)
    assert exactly_open["authorized_aums"] == 40
    assert exactly_open["aoi_status"] == "DRAFT"
    assert get_allotment(allotment["id"])["open_aums"] == 40, "a third draft still takes nothing"

    assert void_aoi(first["id"],
                    void_reason="Superseded by revised operating plan.")["aoi_status"] == "VOIDED"
    released = get_allotment(allotment["id"])
    assert released["allocated_aums"] == 0
    assert released["open_aums"] == 100

    reissued = issue_aoi(second["id"])
    assert reissued["aoi_status"] == "ISSUED", "the identical call that failed above now stands"
    settled = get_allotment(allotment["id"])
    assert settled["allocated_aums"] == 60
    assert settled["open_aums"] == 40


def test_the_non_use_code_covers_the_amount_and_the_missing_closure_order_alike():
    """One 422 ERR_NONUSE_EXCEEDS_AUTHORIZED answers both clauses: 101 AUMs against an authorization of
    100, and a perfectly legal 100 AUMs for DROUGHT while no drought order is ACTIVE. A
    PERSONAL_CONVENIENCE approval of 40 needs no order at all and re-prices the year, voiding the
    17,200-cent preliminary bill in favour of a 10,320-cent revised bill that names it.

    PRD 2.6: "**Non-use bounds** — `ERR_NONUSE_EXCEEDS_AUTHORIZED`, HTTP 422, on non-use approval."
    PRD 2.6: "The requested `nonuse_aums` must be at least 1 and no greater than the instruction's
    current `authorized_aums`, and a `nonuse_reason` of `DROUGHT` or `WILDFIRE` is accepted only while a
    closure order of the matching `order_type` is `ACTIVE` on the allotment."
    PRD 3.5: "The requested `nonuse_aums` must be at least 1 and no greater than the instruction's
    current `authorized_aums`, and the two agency-directed reasons are conditional: `DROUGHT` is
    accepted only while a closure order of `order_type` `DROUGHT_REDUCTION` is `ACTIVE` on the
    allotment, and `WILDFIRE` only while an order of `order_type` `WILDFIRE_CLOSURE` is `ACTIVE` on
    it."
    PRD 3.5: "Every one of those failures is `ERR_NONUSE_EXCEEDS_AUTHORIZED`."
    PRD 3.5: "The instruction's `billable_aums` becomes its `authorized_aums` less the approved
    `nonuse_aums`, the allotment's ledger is recomputed so that the released AUMs reappear in
    `open_aums`, any still-unpaid preliminary bill for that instruction is superseded by a revised bill
    at the lower figure, the permit's `consecutive_nonuse_years` is recomputed, and the permittee's
    `outstanding_balance_cents` is brought back into line."
    PRD 3.6: "The **revised** variant, used when an emergency reduction, a stocking adjustment or a
    vacatur moves `authorized_aums` while a use bill is still unpaid, sets `billed_aums` to the
    recomputed `authorized_aums` less `nonuse_aums`, voids the superseded bill and records
    `superseded_bill_id` on the replacement, and likewise applies no minimum-charge floor."

    Design: Corner/validations/corner_nonuse_bounded_by_authorized_and_by_closure_type
    """
    allotment = create_allotment(admin_unit_code="QB-157", total_permitted_aums=200, acres=6000,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Nonuse Bounds Pasture",
                             pasture_aum_capacity=300, sequence_order=1)
    permittee, base_property = _applicant("Nonuse Bounds Ranch", "nonuse@example.com", 150)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(aoi["id"], pasture["id"], planned_head_count=30, livestock_kind="CATTLE",
                   planned_entry_date="2026-05-01", planned_exit_date="2026-05-31")
    issue_aoi(aoi["id"])

    preliminary = [b for b in list_bills(aoi_id=aoi["id"], bill_type="PRELIMINARY_USE")][0]
    assert preliminary["total_amount_cents"] == 17200  # 100 x 172, admin fee 0
    before = get_allotment(allotment["id"])
    assert before["allocated_aums"] == 100
    assert before["open_aums"] == 100

    validate_error(api_client.approve_nonuse(
        aoi["id"], f.nonuse_payload(101, "PERSONAL_CONVENIENCE"), make_officer_headers()),
        ApiErrorId.ERR_NONUSE_EXCEEDS_AUTHORIZED, 422)
    validate_error(api_client.approve_nonuse(
        aoi["id"], f.nonuse_payload(100, "DROUGHT"), make_officer_headers()),
        ApiErrorId.ERR_NONUSE_EXCEEDS_AUTHORIZED, 422)

    untouched = get_aoi(aoi["id"])
    assert untouched["nonuse_aums"] == 0
    assert untouched["nonuse_reason"] is None
    assert untouched["billable_aums"] == 100

    reduced = approve_nonuse(aoi["id"], 40, nonuse_reason="PERSONAL_CONVENIENCE")
    assert reduced["nonuse_aums"] == 40
    assert reduced["nonuse_reason"] == "PERSONAL_CONVENIENCE"
    assert reduced["billable_aums"] == 60

    after = get_allotment(allotment["id"])
    assert after["allocated_aums"] == 60
    assert after["open_aums"] == 140
    assert get_bill(preliminary["id"])["bill_status"] == "VOIDED"
    revised = [b for b in list_bills(aoi_id=aoi["id"], bill_type="REVISED_USE")]
    assert len(revised) == 1, "one replacement bill at the lower figure"
    assert revised[0]["total_amount_cents"] == 10320  # 60 x 172, admin fee 0
    assert revised[0]["superseded_bill_id"] == preliminary["id"]
    assert get_permittee(permittee["id"])["outstanding_balance_cents"] == 10320


def test_the_overpayment_ceiling_is_the_remaining_balance_and_not_the_bill_total():
    """A 12,201-cent payment on a 17,200-cent bill that has already received 5,000 is refused with a 422
    ERR_OVERPAYMENT and adds nothing, because the ceiling is what remains rather than the total. One
    cent less is accepted and settles the bill exactly, which is what makes the refused amount legal in
    every respect but the arithmetic.

    PRD 2.6: "**Overpayment** — `ERR_OVERPAYMENT`, HTTP 422, on payment recording."
    PRD 2.6: "The `amount_cents` must be at least 1 and must not exceed the bill's
    `total_amount_cents` less its `amount_paid_cents`; overpayment is refused outright rather than
    credited."
    PRD 3.6: "The `amount_cents` must be at least 1 and must not exceed the bill's
    `total_amount_cents` less its `amount_paid_cents`, because overpayment is refused rather than
    credited and yields `ERR_OVERPAYMENT`."
    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."
    PRD 3.5: "The instruction reaches `CLOSED` later and indirectly: when a payment brings every
    non-voided bill of that instruction to `bill_status` `PAID`, the instruction moves `BILLED →
    CLOSED`."

    Design: Corner/validations/corner_payment_cannot_exceed_the_remaining_balance
    """
    allotment = create_allotment(admin_unit_code="QB-158", total_permitted_aums=200, acres=6000,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Overpayment Pasture",
                             pasture_aum_capacity=300, sequence_order=1)
    permittee, base_property = _applicant("Overpayment Ranch", "overpay@example.com", 150)
    permit = issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                       requested_aums=100)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(aoi["id"], pasture["id"], planned_head_count=30, livestock_kind="CATTLE",
                   planned_entry_date="2026-05-01", planned_exit_date="2026-05-31")
    issue_aoi(aoi["id"])

    bill = [b for b in list_bills(aoi_id=aoi["id"], bill_type="PRELIMINARY_USE")][0]
    assert bill["total_amount_cents"] == 17200
    payer = make_permittee_headers(permittee["id"])
    partial = get_success_data(api_client.record_payment(
        bill["id"], f.payment_payload(5000), payer), 201)
    assert partial["amount_paid_cents"] == 5000
    assert partial["bill_status"] == "ISSUED"

    validate_error(api_client.record_payment(bill["id"], f.payment_payload(12201), payer),
                   ApiErrorId.ERR_OVERPAYMENT, 422)
    assert get_bill(bill["id"])["amount_paid_cents"] == 5000, "the refusal credited nothing"

    settled = get_success_data(api_client.record_payment(
        bill["id"], f.payment_payload(12200), payer), 201)
    assert settled["amount_paid_cents"] == 17200
    assert settled["bill_status"] == "PAID"
    assert get_permittee(permittee["id"])["outstanding_balance_cents"] == 0
    assert get_aoi(aoi["id"])["aoi_status"] == "ISSUED", "CLOSED is reachable only from BILLED"
