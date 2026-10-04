"""Authorization, ownership scope, natural-key conflicts, error precedence and
the parent-version pin."""
from test_helpers import (
    ApiErrorId,
    api_client,
    candidate_to_assessment_pending,
    contract_candidate,
    fetch_advisor,
    fetch_credits,
    get_success_data,
    make_financial_rep_headers,
    new_advisor,
    new_appointment,
    new_candidate,
    new_license,
    new_office,
    new_policy,
    any_headers,
    dd_headers,
    lc_headers,
    md_headers,
    ro_headers,
    set_clock,
    setup_contracted_rep,
    setup_joint_case,
    setup_validated_rep,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Role grants and ownership scope
# ---------------------------------------------------------------------------
def test_a_recruiting_officer_may_not_create_a_district_office():
    """PRD §2.1: "If the headers are well formed but the named role does not
    hold the requested operation in its exclusive-operation or shared-operation
    grant, the request is refused with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/recruiting_officer_cannot_create_a_district_office
    """
    set_clock()

    refused = api_client.create_district_office({
        "office_code": "DO-H01", "name": "Unauthorized District",
        "region_code": "MW", "state_code": "WI",
    }, ro_headers)
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    offices = validate_success(api_client.list_district_offices(any_headers))
    offices = offices if isinstance(offices, list) else offices.get("data", [])
    assert offices == []


def test_a_financial_rep_may_not_terminate_or_move_money():
    """PRD §2.1: "`ManagingDirector` sits at the top of the field hierarchy and
    controls contracts, validation, termination, and all money movement."
    PRD §2.1: "If the headers are well formed but the named role does not hold
    the requested operation in its exclusive-operation or shared-operation
    grant, the request is refused with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/financial_rep_cannot_terminate_an_advisor_or_pay_a_credit
    """
    set_clock()
    office = new_office()
    ctx = setup_validated_rep(office["id"], name="Nora RBAC", annual_premium_cents=510000,
                              required_production_cents=100000, create_policy=True,
                              activate_policy=True)
    advisor_id = ctx["advisor"]["id"]
    credit = fetch_credits(ctx["policy"]["id"], "PRIMARY")[0]
    assert credit["status"] == "ACCRUED"

    rep_ctx = make_financial_rep_headers(advisor_id)
    refused_term = api_client.terminate_advisor(advisor_id, rep_ctx)
    validate_error(refused_term, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    refused_pay = api_client.pay_commission_credit(credit["id"], rep_ctx)
    validate_error(refused_pay, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    advisor = fetch_advisor(advisor_id)
    assert advisor["contract_status"] != "TERMINATED"
    assert advisor["chargeback_balance_cents"] == 0
    assert get_success_data(api_client.get_commission_credit(credit["id"], any_headers))["status"] == "ACCRUED"


def test_only_the_lead_advisor_may_submit_their_own_joint_case():
    """PRD §3.6: "Submitting a joint case is a `FinancialRep` action, and it is
    scoped to the acting advisor: `X-User-ID` must equal the case's
    `lead_advisor_id`."

    Design: Corner/rbac/only_the_lead_advisor_may_submit_their_own_joint_case
    """
    set_clock()
    office = new_office()
    ctx = setup_joint_case(office["id"], split_pct_lead=0.6, annual_premium_cents=510000)
    case_id = ctx["case"]["id"]
    lead_id = ctx["lead"]["advisor"]["id"]
    support_id = ctx["support"]["advisor"]["id"]

    refused = api_client.submit_joint_work_case(case_id, make_financial_rep_headers(support_id))
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    still_open = get_success_data(api_client.get_joint_work_case(case_id, any_headers))
    assert still_open["status"] == "OPEN"

    submitted = validate_success(api_client.submit_joint_work_case(
        case_id, make_financial_rep_headers(lead_id)))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["support_advisor_id"] == support_id


# ---------------------------------------------------------------------------
# Natural-key conflicts
# ---------------------------------------------------------------------------
def test_a_policy_number_is_unique_across_the_whole_population():
    """PRD §3.6: "The `policy_number` is a natural key unique across all
    policies, so a reuse is refused with `ERR_DUPLICATE_NATURAL_KEY`."

    Design: Corner/errors/duplicate_policy_number_is_rejected_as_a_natural_key_conflict
    """
    set_clock()
    office = new_office()
    first = new_advisor(office["id"], name="Lars First", email="lars.one@agency.example")
    second = new_advisor(office["id"], name="Mona Second", email="mona.two@agency.example")

    existing = new_policy(first["id"], annual_premium_cents=510000, policy_number="NM-G001")

    refused = api_client.create_policy({
        "policy_number": "NM-G001",
        "writing_advisor_id": second["id"],
        "carrier_name": "Northwestern Mutual",
        "product_line": "LIFE",
        "annual_premium_cents": 510000,
        "issue_date": "2026-02-02T00:00:00Z",
        "is_advanced_commission": True,
    }, md_headers)
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_NATURAL_KEY.value)

    all_policies = validate_success(api_client.list_policies(any_headers))
    all_policies = all_policies if isinstance(all_policies, list) else all_policies.get("data", [])
    assert len(all_policies) == 1

    stored = get_success_data(api_client.get_policy(existing["id"], any_headers))
    assert stored["writing_advisor_id"] == first["id"]

    by_second = validate_success(api_client.list_policies(any_headers,
                                                          {"writing_advisor_id": second["id"]}))
    by_second = by_second if isinstance(by_second, list) else by_second.get("data", [])
    assert by_second == []


# ---------------------------------------------------------------------------
# Error precedence
# ---------------------------------------------------------------------------
def test_licence_compliance_error_precedes_and_demotes_the_advisor():
    """PRD §3.5: "When the licence has gone stale, the approval is refused with
    `ERR_LICENSE_NOT_ACTIVE`, and — as §3.4 notes — the advisor's contract is
    demoted from `ACTIVE_TRAINING` to `AT_RISK` in the same operation."
    PRD §2.10: "Because compliance is evaluated before posture, a request that is
    blocked both by an expired licence and by an at-risk posture reports the
    licence error and not the posture error."

    Design: Corner/validations/licence_compliance_error_precedence_on_appointment_approval
    """
    set_clock("2026-01-05T00:00:00Z")
    office = new_office()
    advisor = new_advisor(office["id"], name="Hugo Stale")
    license_row = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-4101",
                              effective_date="2026-01-01T00:00:00Z",
                              expires_at="2026-02-01T00:00:00Z")
    appointment = new_appointment(advisor["id"], license_row["id"], approve=False,
                                  requested_date="2026-01-05T00:00:00Z")

    candidate, assessment = candidate_to_assessment_pending(
        office["id"], name="Hugo Stale", assessment_version="V2",
        scheduled_date="2026-01-06T00:00:00Z")
    validate_success(api_client.score_assessment(
        assessment["id"], {"raw_score": 85, "competency_scores": {
            "MARKET_KNOWLEDGE": 8, "RELATIONSHIP": 8, "RESILIENCE": 7, "ETHICS": 9}}, ro_headers))
    validate_success(api_client.advance_to_interview(candidate["id"], ro_headers))
    candidate = validate_success(api_client.extend_offer(candidate["id"], dd_headers))
    candidate = validate_success(api_client.accept_offer(candidate["id"], ro_headers))
    contract_candidate(advisor["id"], candidate, mode="FLAT_MONTHLY",
                       start_date="2026-01-07T00:00:00Z")

    set_clock("2026-03-01T00:00:00Z")

    refused = api_client.approve_carrier_appointment(appointment["id"], lc_headers)
    validate_error(refused, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value)

    still_requested = get_success_data(api_client.get_carrier_appointment(appointment["id"], any_headers))
    assert still_requested["appointment_status"] == "REQUESTED"
    assert still_requested["appointment_date"] is None

    refreshed = fetch_advisor(advisor["id"])
    assert refreshed["insurance_license_status"] == "LAPSED"
    assert refreshed["contract_status"] == "AT_RISK"
    assert refreshed["validation_posture"] == "AT_RISK"
    assert refreshed["appointment_status"] != "APPROVED"


# ---------------------------------------------------------------------------
# Orphaned book and office containment
# ---------------------------------------------------------------------------
def test_only_in_force_policies_are_orphaned_by_termination():
    """PRD §3.8: "For every `Policy` whose `writing_advisor_id` is the
    terminated advisor and whose status is `ISSUED` or `ACTIVE`, the policy's
    `orphaned` flag is set to true" ... "A policy that was already `LAPSED`,
    `SURRENDERED`, or `TERMINATED` is not orphaned by this cascade."

    Design: Corner/endpoints/policies_can_be_filtered_to_the_orphaned_set
    """
    set_clock()
    office = new_office()
    ctx = setup_validated_rep(office["id"], name="Ida Orphan", annual_premium_cents=510000,
                              required_production_cents=100000, create_policy=True,
                              activate_policy=True)
    advisor_id = ctx["advisor"]["id"]

    active_policy = ctx["policy"]
    second = new_policy(advisor_id, annual_premium_cents=510000, policy_number="NM-E002")
    validate_success(api_client.activate_policy(second["id"], md_headers))
    validate_success(api_client.surrender_policy(second["id"], md_headers))

    validate_success(api_client.terminate_advisor(advisor_id, md_headers))

    kept = get_success_data(api_client.get_policy(active_policy["id"], any_headers))
    assert kept["orphaned"] is True
    assert kept["status"] == "ACTIVE"

    surrendered = get_success_data(api_client.get_policy(second["id"], any_headers))
    assert surrendered["orphaned"] is False
    assert surrendered["status"] == "SURRENDERED"

    by_writer = validate_success(api_client.list_policies(any_headers,
                                                          {"writing_advisor_id": advisor_id}))
    by_writer = by_writer if isinstance(by_writer, list) else by_writer.get("data", [])
    assert len(by_writer) == 2


def test_closing_an_office_with_live_advisors_is_refused():
    """PRD §2.11: "Closing is refused with `ERR_OFFICE_HAS_LIVE_ADVISORS`
    whenever any advisor with a `contract_status` of `ACTIVE_TRAINING`,
    `VALIDATING`, or `AT_RISK` is still assigned to the office."
    PRD §2.11: "A `ManagingDirector` may suspend an `ACTIVE` office, which sets
    its status to `SUSPENDED` and changes no advisor's `contract_status`" ...
    "may reactivate a `SUSPENDED` office back to `ACTIVE`."

    Design: Corner/endpoints/district_office_close_is_refused_while_live_advisors_remain
    """
    set_clock()
    office = new_office()
    ctx = setup_contracted_rep(office["id"], name="Jun Live", mode="FLAT_MONTHLY")
    assert get_success_data(api_client.get_advisor(ctx["advisor"]["id"], any_headers))[
        "contract_status"] == "ACTIVE_TRAINING"

    refused = api_client.close_district_office(office["id"], md_headers)
    validate_error(refused, ApiErrorId.ERR_OFFICE_HAS_LIVE_ADVISORS.value)

    unchanged = get_success_data(api_client.get_district_office(office["id"], any_headers))
    assert unchanged["status"] == "ACTIVE"

    suspended = validate_success(api_client.suspend_district_office(office["id"], md_headers))
    assert suspended["status"] == "SUSPENDED"

    reactivated = validate_success(api_client.reactivate_district_office(office["id"], md_headers))
    assert reactivated["status"] == "ACTIVE"

    advisors = validate_success(api_client.list_office_advisors(office["id"], any_headers))
    advisors = advisors if isinstance(advisors, list) else advisors.get("data", [])
    assert len(advisors) == 1
    assert advisors[0]["contract_status"] == "ACTIVE_TRAINING"


# ---------------------------------------------------------------------------
# Parent-version pin
# ---------------------------------------------------------------------------
def test_a_stale_candidate_version_blocks_contract_creation():
    """PRD §2.6: "When the candidate's version has advanced since the client
    last read it, the create is rejected with `ERR_STALE_VERSION` at status 412."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_candidate_version_blocks_contract_creation
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Quin OCC")

    candidate = new_candidate(office["id"], name="Quin OCC")
    candidate = validate_success(api_client.screen_candidate(candidate["id"], ro_headers))
    stale_version = get_success_data(api_client.get_candidate(candidate["id"], any_headers))["version"]

    assessment = validate_success(api_client.schedule_assessment(
        candidate["id"], {"assessment_version": "V2", "scheduled_date": "2026-09-02T00:00:00Z"},
        ro_headers))
    validate_success(api_client.score_assessment(
        assessment["id"], {"raw_score": 85, "competency_scores": {
            "MARKET_KNOWLEDGE": 8, "RELATIONSHIP": 8, "RESILIENCE": 7, "ETHICS": 9}}, ro_headers))
    validate_success(api_client.advance_to_interview(candidate["id"], ro_headers))
    validate_success(api_client.extend_offer(candidate["id"], dd_headers))
    accepted = validate_success(api_client.accept_offer(candidate["id"], ro_headers))
    fresh_version = accepted["version"]
    assert fresh_version != stale_version

    refused = api_client.create_employment_contract({
        "advisor_id": advisor["id"],
        "candidate_id": candidate["id"],
        "contract_type": "FULL_TIME",
        "start_date": "2026-09-03T00:00:00Z",
        "training_allowance_total_cents": 1200000,
        "training_allowance_mode": "FLAT_MONTHLY",
        "validation_requirement_cents": 300000,
        "expected_candidate_version": stale_version,
    }, md_headers)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value)

    assert get_success_data(api_client.get_candidate(candidate["id"], any_headers))[
        "stage"] == "OFFER_ACCEPTED"

    created = validate_success(api_client.create_employment_contract({
        "advisor_id": advisor["id"],
        "candidate_id": candidate["id"],
        "contract_type": "FULL_TIME",
        "start_date": "2026-09-03T00:00:00Z",
        "training_allowance_total_cents": 1200000,
        "training_allowance_mode": "FLAT_MONTHLY",
        "validation_requirement_cents": 300000,
        "expected_candidate_version": fresh_version,
    }, md_headers), 201)
    assert created["contract_status"] == "ACTIVE_TRAINING"

    assert get_success_data(api_client.get_candidate(candidate["id"], any_headers))[
        "stage"] == "CONTRACTED"
    assert fetch_advisor(advisor["id"])["contract_status"] == "ACTIVE_TRAINING"