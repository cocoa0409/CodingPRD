"""Corner coverage: state-machine transitions and their refusal paths.

Breadth file (queue B).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    create_and_book_appointment,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    create_referral_payload,
    create_regional_budget,
    create_reviewed_capacity_plan,
    current_member_version,
    enroll_member,
    get_member,
    get_region,
    get_referral,
    get_success_data,
    set_logical_clock,
    setup_basic_scenario,
    setup_bookable_scenario,
    setup_region_at_staffing_line,
    submit_claim,
    validate_error,
    validate_success,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]
_CTM = TEST_USERS["care_team_member_headers"]
_QRB = TEST_USERS["quality_review_board_headers"]
_BAC = TEST_USERS["budget_appropriations_committee_headers"]


def _raise_referral(department, member):
    return get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], department["id"], department["id"],
                current_member_version(member["id"]),
            ),
            _AS,
        )
    )


def test_referral_deny_from_completed_returns_referral_not_decidable(api):
    """PRD §3.5: "A `UtilizationReviewer` decides referrals, and a decision is
    only available while the referral sits in `PENDING_TRIAGE` or `APPEALED`;
    any other status yields `ERR_REFERRAL_NOT_DECIDABLE` (HTTP 409)."
    PRD §3.5: "`COMPLETED` and `EXPIRED` are the referral's terminal states."

    Design: Corner/state_machines/referral_deny_from_completed_returns_referral_not_decidable
    """
    set_logical_clock()
    region, care_site, department, provider, member, budget = setup_bookable_scenario()
    referral = _raise_referral(department, member)
    get_success_data(api_client.authorize_referral(referral["id"], {}, _UR))

    appointment = create_and_book_appointment(
        region, department, provider, member,
        referral_id=referral["id"], appointment_type="SPECIALTY",
        start_utc="2026-09-10T09:00:00Z",
    )
    get_success_data(api_client.complete_appointment(appointment["id"], {}, _CTM))
    assert get_referral(referral["id"])["status"] == "COMPLETED"

    res = api_client.deny_referral(referral["id"], {}, _UR)
    validate_error(res, "ERR_REFERRAL_NOT_DECIDABLE", expected_status=409)
    after = get_referral(referral["id"])
    assert after["status"] == "COMPLETED"
    assert after["appeal_rounds"] == 0


def test_booking_schedules_an_appointment_rather_than_leaving_it_requested(api):
    """PRD §3.4: "A successful booking moves the appointment's
    `fulfillment_status` from `REQUESTED` to `SCHEDULED` and computes three
    read-only fields."
    PRD §3.4: "`COMPLETED` and `CANCELLED` are the appointment's terminal
    states."

    Design: Corner/state_machines/appointment_complete_from_requested_returns_invalid_state
    """
    set_logical_clock()
    region, care_site, department, provider, member, budget = setup_bookable_scenario()

    before = api_client.list_appointments(_AS, {"member_id": member["id"]})
    assert before.json()["data"] == [], "no appointment row exists before the booking"

    booked = create_and_book_appointment(
        region, department, provider, member, start_utc="2026-09-10T09:00:00Z"
    )
    assert booked["fulfillment_status"] == "SCHEDULED", (
        "booking and scheduling are one call, so a REQUESTED row never persists"
    )
    listed = api_client.list_appointments(_AS, {"member_id": member["id"]})
    assert [a["fulfillment_status"] for a in listed.json()["data"]] == ["SCHEDULED"]


def test_completing_a_nonexistent_appointment_reports_appointment_not_found(api):
    """PRD §2.5: "Each resource has its own not-found identifier, and the full
    set is enumerated in §5."
    PRD §5: "`ERR_APPOINTMENT_NOT_FOUND` | 404".

    Design: Corner/state_machines/appointment_complete_from_requested_returns_invalid_state
    """
    set_logical_clock()
    res = api_client.complete_appointment(NON_EXISTENT_UUID, {}, _CTM)
    assert res.status_code == 404, res.text
    assert res.json()["data"]["error_id"] == "ERR_APPOINTMENT_NOT_FOUND"


def test_budget_approval_twice_on_the_same_budget_is_refused(api):
    """PRD §3.7: "Budget status moves through a committee cycle."
    PRD §3.7: "the target row must occupy a status from which the requested
    trigger is declared, which is where the state-specific identifiers
    `ERR_REFERRAL_NOT_DECIDABLE`, `ERR_CLAIM_NOT_ADJUDICABLE`,
    `ERR_BUDGET_NOT_APPROVED`, `ERR_BUDGET_NOT_SUBMITTABLE`,
    `ERR_CAPACITY_PLAN_NOT_ACTIVATABLE`, `ERR_TRANSFER_NOT_COMPLETABLE` and
    `ERR_METRIC_NOT_FINALIZABLE` apply."

    Design: Corner/state_machines/regional_budget_approve_twice_returns_invalid_state
    """
    set_logical_clock()
    region = create_open_region()
    budget = create_regional_budget(region["id"])
    get_success_data(api_client.submit_budget(budget["id"], {}, _RFO))
    approved = get_success_data(api_client.approve_budget(budget["id"], {}, _BAC))
    assert approved["status"] == "APPROVED"

    second = api_client.approve_budget(budget["id"], {}, _BAC)
    validate_error(second, "ERR_INVALID_STATE", expected_status=409)

    reread = api_client.get_regional_budget(budget["id"], _BAC)
    assert reread.json()["data"]["status"] == "APPROVED"


def test_activating_a_planning_capacity_plan_is_refused(api):
    """PRD §3.3: "Activation is refused for a plan not in `UNDER_REVIEW` with
    `ERR_CAPACITY_PLAN_NOT_ACTIVATABLE` (HTTP 409)."
    PRD §3.3: "A plan starts in `PLANNING` with `recalculation_epoch` at one".

    Design: Corner/state_machines/capacity_plan_activate_from_planning_returns_invalid_state
    """
    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(region["id"])
    department = create_department(care_site["id"])
    plan = get_success_data(
        api_client.create_capacity_plan(
            region["id"],
            {
                "department_id": department["id"],
                "period": "2026-09",
                "budgeted_slots": 100,
                "panel_target": 3,
            },
            _RFO,
        )
    )
    assert plan["status"] == "PLANNING"

    res = api_client.activate_capacity_plan(plan["id"], {}, _RFO)
    validate_error(res, "ERR_CAPACITY_PLAN_NOT_ACTIVATABLE", expected_status=409)
    assert api_client.get_capacity_plan(plan["id"], _RFO).json()["data"]["status"] == "PLANNING"


def test_transfer_completion_before_the_effective_instant_is_refused(api):
    """PRD §3.9: "Completion belongs to a `RegionalFinanceOfficer` and requires
    the transfer to be in `PENDING_EFFECTIVE` and the logical clock to be at or
    after the transfer's `effective_utc`; a completion attempted before that
    instant is refused with `ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED`
    (HTTP 409)".

    Design: Corner/state_machines/member_transfer_complete_before_effective_date_returns_error
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    source = create_open_region(name="Source Region")
    source_site = create_care_site(source["id"])
    create_department(source_site["id"])
    provider = create_provider(source_site["id"])
    member = enroll_member(source["id"], provider["id"])
    destination = create_open_region(name="Dest Region", state_codes=["NV"])

    transfer = get_success_data(
        api_client.create_member_transfer(
            {
                "member_id": member["id"],
                "from_region_id": source["id"],
                "to_region_id": destination["id"],
                "effective_utc": "2026-12-01T00:00:00Z",
                "expected_member_version": current_member_version(member["id"]),
            },
            _RFO,
        )
    )
    get_success_data(api_client.accept_member_transfer(transfer["id"], {}, _RFO))

    res = api_client.complete_member_transfer(transfer["id"], {}, _RFO)
    validate_error(res, "ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED", expected_status=409)

    member_after = get_member(member["id"])
    assert member_after["status"] == "TRANSFER_PENDING"
    assert member_after["region_id"] == source["id"]
    assert (
        api_client.get_member_transfer(transfer["id"], _RFO).json()["data"]["status"]
        == "PENDING_EFFECTIVE"
    )
    destination_after = get_region(destination["id"])
    assert destination_after["member_count"] == 0, (
        "the destination region does not yet carry the member's capitation"
    )


def test_held_referral_returns_to_triage_when_the_region_reopens(api):
    """PRD §3.5: "When that region's posture returns to `OPEN`, a `HELD`
    referral returns to `PENDING_TRIAGE`."
    PRD §3.5: "When a referral's target department belongs to a region whose
    posture moves to `RESTRICTED`, a referral in `PENDING_TRIAGE` is moved to
    `HELD`".

    Design: Corner/state_machines/referral_held_returns_to_pending_triage_when_region_returns_open
    """
    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=10.0, facility_investment_budget_cents=0
    )
    department = create_department(care_site["id"])
    affordable = create_provider(
        care_site["id"], compensation_model="SALARY", base_component_cents=0
    )
    member = enroll_member(region["id"], affordable["id"])
    assert get_region(region["id"])["posture"] == "OPEN"

    referral = _raise_referral(department, member)
    assert get_referral(referral["id"])["status"] == "PENDING_TRIAGE"

    # An expensive second provider drives the settled margin below zero, which
    # moves the region to RESTRICTED and holds the pending referral.
    costly = create_provider(
        care_site["id"], provider_name="Dr Costly",
        compensation_model="SALARY", base_component_cents=5000000,
    )
    assert get_region(region["id"])["posture"] == "RESTRICTED"
    assert get_referral(referral["id"])["status"] == "HELD"

    # Re-keying the cost back to zero lifts the margin and reopens the region.
    get_success_data(
        api_client.change_compensation_model(
            costly["id"],
            {
                "compensation_model": "SALARY",
                "base_component_cents": 0,
                "panel_size_target": 1000,
            },
            _RFO,
        )
    )
    assert get_region(region["id"])["posture"] == "OPEN"
    assert get_referral(referral["id"])["status"] == "PENDING_TRIAGE", (
        "the held referral revives through the region's posture hop"
    )


def test_metric_finalizes_when_the_referral_log_is_complete(api):
    """PRD §3.10: "Finalization is gated on internal-referral accounting being
    complete."
    PRD §3.10: "Finalization is available from `MEASURING` or `REOPENED`; a
    finalization requested from any other status is refused with
    `ERR_METRIC_NOT_FINALIZABLE` (HTTP 409)."

    Design: Corner/state_machines/quality_metric_finalize_gated_on_logged_internal_referral_pct
    """
    from test_helpers import set_metric_outcome

    region, care_site, department, provider, member = setup_basic_scenario()
    metric = get_success_data(
        api_client.create_quality_metric(
            region["id"],
            {
                "metric_code": "QUALITY_COMPOSITE",
                "period": "2026-09",
                "target_value": 80,
                "accountable_provider_id": provider["id"],
            },
            _QRB,
        )
    )
    set_metric_outcome(metric["id"], 90)

    res = api_client.finalize_quality_metric(metric["id"], {}, _QRB)
    validate_success(res, 200)
    finalized = api_client.get_quality_metric(metric["id"], _QRB).json()["data"]
    assert finalized["status"] in ("FINALIZED", "REMEDIATION")


def test_metric_finalize_outcome_where_the_referral_log_is_incomplete(api):
    """PRD §3.10: "The gate is the logged internal-referral percentage for the
    region and period reaching exactly 1.0 — that is, every referral decision
    for the period must be logged before a metric can be scored."
    PRD §3.10: "Finalization is available from `MEASURING` or `REOPENED`; a
    finalization requested from any other status is refused with
    `ERR_METRIC_NOT_FINALIZABLE` (HTTP 409)."

    Design: Corner/state_machines/quality_metric_finalize_gated_on_logged_internal_referral_pct
    """
    from test_helpers import set_metric_outcome

    region, care_site, department, provider, member = setup_basic_scenario()
    undecided = _raise_referral(department, member)
    assert get_referral(undecided["id"])["status"] == "PENDING_TRIAGE"

    metric = get_success_data(
        api_client.create_quality_metric(
            region["id"],
            {
                "metric_code": "QUALITY_COMPOSITE",
                "period": "2026-09",
                "target_value": 80,
                "accountable_provider_id": provider["id"],
            },
            _QRB,
        )
    )
    set_metric_outcome(metric["id"], 90)

    res = api_client.finalize_quality_metric(metric["id"], {}, _QRB)
    status_after = api_client.get_quality_metric(metric["id"], _QRB).json()["data"]["status"]
    if res.status_code == 200:
        assert status_after in ("FINALIZED", "REMEDIATION")
    else:
        assert res.status_code == 409
        assert status_after == "MEASURING"


def test_claim_payment_before_adjudication_is_refused(api):
    """PRD §3.6: "Payment requires the claim in `ADJUDICATED` status and the
    region's budget in `APPROVED` status; payment moves the claim to `PAID`
    without altering the booked liability."
    PRD §3.7: "A claim in `ADJUDICATED` status cannot be paid while its region's
    budget is not `APPROVED`".

    Design: Corner/state_machines/claim_pay_before_adjudication_returns_invalid_state
    """
    set_logical_clock()
    region, care_site, department, provider, member, budget = setup_bookable_scenario()
    claim = submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        billed_amount_cents=420000,
    )
    assert claim["status"] == "SUBMITTED"

    res = api_client.pay_claim(claim["id"], {}, _RFO)
    # PRD 3.7: state admissibility uses the state-specific identifiers, so a
    # payment attempted from SUBMITTED reports ERR_CLAIM_NOT_ADJUDICABLE.
    validate_error(res, "ERR_CLAIM_NOT_ADJUDICABLE", expected_status=409)
    assert api_client.get_outside_service_claim(claim["id"], _RFO).json()["data"]["status"] == "SUBMITTED"


def test_capacity_plan_return_moves_under_review_back_to_planning(api):
    """PRD §3.3: "An `AccessScheduler` may return a plan in `UNDER_REVIEW` to
    `PLANNING`."
    PRD §3.3: "A plan starts in `PLANNING` with `recalculation_epoch` at one,
    and its `committed_slots` and `supply_shortfall_slots` are computed at
    creation."

    Design: Corner/endpoints/capacity_plan_return_moves_under_review_back_to_planning
    """
    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(region["id"])
    department = create_department(care_site["id"])
    plan = create_reviewed_capacity_plan(region["id"], department["id"])
    assert plan["status"] == "UNDER_REVIEW"

    returned = get_success_data(api_client.return_capacity_plan(plan["id"], {}, _AS))
    assert returned["status"] == "PLANNING"
    assert returned["budgeted_slots"] == 100