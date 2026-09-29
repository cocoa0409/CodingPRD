"""RBAC, ownership, duty separation, OCC guards and read-your-writes (PRD §2.1, §2.7-§2.9, §4)."""
from test_helpers import *  # noqa: F401,F403

# ─── Canonical program shape (PRD §3.1-§3.4) ─────────────────────────────────
# A per-person basis of 431757 cents against these two rungs pins the award side
# of the budget rollup at 1443174 cents: PLATINUM 921765 + GOLD 521409.

_PLATINUM = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250_000_000,
    "budget_per_qualifier_cents": 2_500_000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 150_000,
    "service_load_bp": 1275,
}

_GOLD = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150_000_000,
    "budget_per_qualifier_cents": 1_600_000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40_000,
    "service_load_bp": 800,
}

_DESTINATION = {
    "city": "Lisbon",
    "country_code": "PT",
    "per_person_cost_cents": 431_757,
    "risk_score": 35,
    "air_gateway_code": "LIS",
}

_DESTINATION_B = {
    "city": "Seville",
    "country_code": "ES",
    "per_person_cost_cents": 388_000,
    "risk_score": 28,
    "air_gateway_code": "SVQ",
}

# 12 rooms over 5 nights at 38500 cents is a contract value of 2310000 cents and
# a blocked ledger of 60 room-nights; the 2000 bp allowance puts the attrition
# floor at 48 (PRD §3.7).
_CONTRACT = {
    "supplier_name": "Estoril Palace",
    "supplier_kind": "HOTEL",
    "room_block_count": 12,
    "contracted_nights": 5,
    "stay_start_at": "2026-11-08T00:00:00Z",
    "nightly_rate_cents": 38_500,
    "attrition_allowance_bp": 2000,
    "force_majeure_clause": "STANDARD",
    "exposure_basis": "ATTRITION_BASIS",
}

_MILESTONES = [
    {"sequence": 1, "due_at": "2026-08-15T00:00:00Z", "amount_cents": 577_500, "refundable_bp": 10000},
    {"sequence": 2, "due_at": "2026-09-15T00:00:00Z", "amount_cents": 577_500, "refundable_bp": 5000},
    {"sequence": 3, "due_at": "2026-10-15T00:00:00Z", "amount_cents": 1_155_000, "refundable_bp": 0},
]

_QUALIFIER_A = {
    "employee_code": "S-1001",
    "full_name": "Ana Reyes",
    "baseline_metric": 180_000_000,
    "actual_metric": 260_000_000,
    "guest_count": 1,
}

_QUALIFIER_B = {
    "employee_code": "S-2001",
    "full_name": "Ben Ortiz",
    "baseline_metric": 120_000_000,
    "actual_metric": 155_000_000,
    "guest_count": 0,
}

# stay_start_at 2026-11-08 plus 5 contracted nights makes stay_end_at
# 2026-11-13, the exclusive upper bound of the stay window (PRD §3.4).
_SEAT = {
    "arrival_date": "2026-11-08T00:00:00Z",
    "departure_date": "2026-11-13T00:00:00Z",
    "rooms": 1,
}

_ACTIVITY = {
    "name": "Douro Valley Wine Tour",
    "start_at": "2026-11-10T10:00:00Z",
    "end_at": "2026-11-10T13:00:00Z",
    "capacity": 5,
    "risk_level": "LOW",
}

_PD = TEST_USERS["program_director_headers"]
_SM = TEST_USERS["sourcing_manager_headers"]
_CA = TEST_USERS["contract_approver_headers"]
_CA_ALT = TEST_USERS["contract_approver_alt_headers"]
_AN = TEST_USERS["sales_ops_analyst_headers"]
_TD = TEST_USERS["travel_desk_headers"]
_TAX = TEST_USERS["tax_officer_headers"]
_TAX_ALT = TEST_USERS["tax_officer_alt_headers"]
_NO_AUTH = {"Content-Type": "application/json"}


def _canonical_kwargs():
    """Program / ladder / destination / contract overrides shared by the fixtures."""
    return dict(
        program_overrides={"budget_total_cents": 5_000_000},
        tier_specs=[_PLATINUM, _GOLD],
        destination_overrides=_DESTINATION,
        contract_overrides=_CONTRACT,
    )


def _registration_open_pair(gross_up_policy="FULL_GROSS_UP"):
    """REGISTRATION_OPEN program with both winners adjudicated and NOTIFIED."""
    return setup_registration_open_program(
        qualifier_specs=[_QUALIFIER_A, _QUALIFIER_B],
        gross_up_policy=gross_up_policy,
        **_canonical_kwargs(),
    )


def _onsite_pair_with_activity():
    """ONSITE program: two CONFIRMED seats and one OPEN capacity-5 activity."""
    return setup_onsite_with_activity(
        activity_overrides=_ACTIVITY,
        qualifier_specs=[_QUALIFIER_A, _QUALIFIER_B],
        gross_up_policy="FULL_GROSS_UP",
        registration_overrides=_SEAT,
        **_canonical_kwargs(),
    )


def _reconciled_solo():
    """RECONCILED program whose single winner travelled with a 783500-cent base."""
    return setup_reconciled_program(
        qualifier_specs=[_QUALIFIER_A],
        gross_up_policy="FULL_GROSS_UP",
        registration_overrides=_SEAT,
        **_canonical_kwargs(),
    )


def _sourcing_pair(second_destination=False):
    """SOURCING program with both qualifiers adjudicated against a 0-cent basis.

    Both destinations are added while the program is still in DESIGN, so only the
    shortlisting the cascade needs is done at SOURCING.
    """
    program = create_program(budget_total_cents=5_000_000)
    program_id = program["id"]
    tiers = [create_award_tier(program_id, **spec) for spec in (_PLATINUM, _GOLD)]
    destination = create_destination(program_id, **_DESTINATION)
    base = {"tiers": tiers, "tier": tiers[0]}
    if second_destination:
        base["destination_b"] = create_destination(program_id, **_DESTINATION_B)
    inspect_destination(destination["id"], 82)
    shortlist_destination(destination["id"])
    base["destination"] = read_destination(destination["id"])
    advance_program(program_id, "SOURCING")
    qualifiers = []
    for spec in (_QUALIFIER_A, _QUALIFIER_B):
        qualifier = create_qualifier(program_id, **spec)
        review_qualifier(qualifier["id"])
        qualifiers.append(read_qualifier(qualifier["id"]))
    base["qualifiers"] = qualifiers
    base["program"] = read_program(program_id)
    return base


def test_program_director_alone_charters_the_program_and_its_tier_ladder():
    """ProgramDirector reaches program creation, tier append and the policy lock.

    PRD §2.1: "Exclusively responsible for creating programs, advancing them,
    recording the gross-up policy decision, notifying qualifiers, cancelling
    programs and creating award tiers."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    program = validate_success(
        api_client.create_program(create_program_payload(budget_total_cents=5_000_000), _PD), 201
    )
    assert_program(program)
    assert program["status"] == "DESIGN"

    tier = validate_success(
        api_client.create_award_tier(create_award_tier_payload(program["id"], **_PLATINUM), _PD), 201
    )
    assert_award_tier(tier)
    assert tier["tier_code"] == "PLATINUM"

    locked = validate_success(
        api_client.set_gross_up_policy(
            program["id"], gross_up_policy_payload("FULL_GROSS_UP"), _PD
        )
    )
    assert locked["gross_up_policy"] == "FULL_GROSS_UP"
    assert locked["gross_up_policy_locked"] is True


def test_program_director_alone_advances_notifies_and_cancels_the_program():
    """The lifecycle, notification and cancellation verbs answer to ProgramDirector.

    PRD §2.1: "Exclusively responsible for creating programs, advancing them,
    recording the gross-up policy decision, notifying qualifiers, cancelling
    programs and creating award tiers."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    base = setup_contracted_program(**_canonical_kwargs())
    program_id = base["program"]["id"]
    for spec in (_QUALIFIER_A, _QUALIFIER_B):
        qualifier = create_qualifier(program_id, **spec)
        review_qualifier(qualifier["id"])

    summary = validate_success(api_client.notify_qualifiers(program_id, _PD))
    assert summary["notified_count"] == 2
    assert summary["skipped_count"] == 0
    assert len(summary["notified_qualifier_ids"]) == 2

    validate_success(
        api_client.set_gross_up_policy(program_id, gross_up_policy_payload("NONE"), _PD)
    )
    advanced = validate_success(
        api_client.advance_program(program_id, advance_payload("REGISTRATION_OPEN"), _PD)
    )
    assert advanced["status"] == "REGISTRATION_OPEN"

    cancelled = validate_success(
        api_client.cancel_program(
            program_id, {"cancellation_reason": "client pulled the program"}, _PD
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "client pulled the program"


def test_sourcing_manager_alone_sources_papers_and_withdraws_the_supply_side():
    """SourcingManager reaches destinations, inspection, contracts, schedule and withdrawal.

    PRD §2.1: "sources and inspects destinations, opens supplier contracts, runs
    the proposing side of negotiation, builds the deposit schedule and withdraws
    contracts that die before execution. This role cannot execute a contract."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    program = create_program(budget_total_cents=5_000_000)
    create_award_tier(program["id"], **_PLATINUM)

    destination = validate_success(
        api_client.create_destination(
            create_destination_payload(program["id"], **_DESTINATION), _SM
        ),
        201,
    )
    assert destination["status"] == "CANDIDATE"

    inspected = validate_success(
        api_client.site_inspect_destination(destination["id"], {"inspection_score": 82}, _SM)
    )
    assert inspected["inspection_status"] == "INSPECTED"
    assert inspected["inspected_by_user_id"] == "sm-01"

    shortlisted = validate_success(api_client.shortlist_destination(destination["id"], _SM))
    assert shortlisted["status"] == "SHORTLISTED"

    advance_program(program["id"], "SOURCING")
    contract = validate_success(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(program["id"], destination["id"], **_CONTRACT), _SM
        ),
        201,
    )
    assert contract["status"] == "DRAFT"

    milestone = validate_success(
        api_client.create_deposit_milestone(
            create_deposit_milestone_payload(contract["id"]), _SM
        ),
        201,
    )
    assert milestone["status"] == "SCHEDULED"

    proposed = validate_success(
        api_client.negotiate_contract(
            contract["id"], negotiate_payload("PROPOSE", note="opening block and rate"), _SM
        )
    )
    assert proposed["status"] == "PROPOSED"
    assert proposed["round_count"] == 1
    assert proposed["last_proposed_by_user_id"] == "sm-01"

    withdrawn = validate_success(
        api_client.withdraw_contract(
            contract["id"], {"withdrawal_reason": "ground handling folded into the hotel deal"}, _SM
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert read_milestone(milestone["id"])["status"] == "CANCELLED"


def test_contract_approver_alone_counters_executes_and_pays():
    """ContractApprover reaches the counter round, execution and milestone payment.

    PRD §2.1: "counter-signs and executes supplier contracts and pays deposit
    milestones."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    base = setup_sourcing_program(
        program_overrides={"budget_total_cents": 5_000_000},
        tier_specs=[_PLATINUM, _GOLD],
        destination_overrides=_DESTINATION,
    )
    contract = create_contract(base["program"]["id"], base["destination"]["id"], **_CONTRACT)
    milestone = create_milestone(contract["id"])
    propose_contract(contract["id"], "sm-01")

    countered = validate_success(
        api_client.negotiate_contract(
            contract["id"], negotiate_payload("COUNTER", nightly_rate_cents=37_000), _CA
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["last_countered_by_user_id"] == "ca-01"

    propose_contract(contract["id"], "sm-01", nightly_rate_cents=38_500)
    executed = validate_success(api_client.execute_contract(contract["id"], _CA_ALT))
    assert executed["status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == "ca-02"

    paid = validate_success(api_client.pay_deposit_milestone(milestone["id"], _CA))
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None


def test_sales_ops_analyst_alone_loads_and_adjudicates_qualifiers():
    """SalesOpsAnalyst reaches qualifier intake and tier adjudication.

    PRD §2.1: "loads qualifying-period sales results and adjudicates qualifiers
    against the tier ladder. This role cannot set budgets or advance the program."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    base = setup_contracted_program(**_canonical_kwargs())
    program_id = base["program"]["id"]

    qualifier = validate_success(
        api_client.create_qualifier(create_qualifier_payload(program_id, **_QUALIFIER_A), _AN), 201
    )
    assert_qualifier(qualifier)
    assert qualifier["award_status"] == "PENDING_REVIEW"

    reviewed = validate_success(api_client.review_qualifier(qualifier["id"], _AN))
    assert reviewed["award_status"] == "QUALIFIED"
    assert reviewed["committed_cost_cents"] == 921_765

    as_director = validate_success(api_client.get_program_measurement(program_id, _PD))
    as_analyst = validate_success(api_client.get_program_measurement(program_id, _AN))
    assert as_analyst == as_director
    assert as_analyst["qualified_count"] == 1


def test_travel_desk_alone_runs_seats_air_and_the_onsite_agenda():
    """TravelDesk reaches enrolment, confirmation, air management and the agenda.

    PRD §2.1: "runs the hospitality desk: seat confirmation, all air travel
    management, publishing and closing the on-site activity agenda, and the
    operational side of enrolments, signups and cancellations."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    base = _registration_open_pair()
    program_id = base["program"]["id"]
    qualifier = base["qualifiers"][0]

    registration = validate_success(
        api_client.create_registration(
            create_registration_payload(qualifier["id"], program_version(program_id), **_SEAT), _TD
        ),
        201,
    )
    assert registration["attendance_status"] == "INVITED"
    respond_registration(registration["id"], qualifier["id"], "ACCEPT", waiver_signed=True)

    confirmed = validate_success(api_client.confirm_registration(registration["id"], _TD))
    assert confirmed["attendance_status"] == "CONFIRMED"
    assert confirmed["room_nights"] == 5

    requested = validate_success(
        api_client.air_registration(
            registration["id"],
            air_payload("REQUEST", cabin_class="BUSINESS", deviation_pre_days=0,
                        deviation_post_days=0, base_fare_cents=214_000),
            _TD,
        )
    )
    assert requested["air_status"] == "REQUESTED"
    ticketed = validate_success(
        api_client.air_registration(registration["id"], air_payload("TICKET"), _TD)
    )
    assert ticketed["air_status"] == "TICKETED"

    advance_program(program_id, "ONSITE")
    activity = validate_success(
        api_client.create_onsite_activity(
            create_onsite_activity_payload(program_id, **_ACTIVITY), _TD
        ),
        201,
    )
    assert activity["status"] == "OPEN"

    signup = validate_success(
        api_client.create_activity_signup(
            create_activity_signup_payload(activity["id"], registration["id"], activity["version"]),
            _TD,
        ),
        201,
    )
    assert signup["status"] == "BOOKED"
    assert validate_success(api_client.cancel_activity_signup(signup["id"], _TD))["status"] == "CANCELLED"
    assert validate_success(api_client.close_onsite_activity(activity["id"], _TD))["status"] == "CLOSED"


def test_participant_alone_answers_the_invitation_and_drives_its_own_award():
    """A Participant reaches the response verb and its own enrolment lifecycle.

    PRD §2.1: "a qualifying salesperson acting on their own award: answering the
    invitation, enrolling themselves or a guest, choosing activities, cancelling
    and submitting the post-trip survey."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    base = _registration_open_pair()
    program_id = base["program"]["id"]
    qualifier = base["qualifiers"][0]
    owner = make_participant_headers(qualifier["id"])

    registration = validate_success(
        api_client.create_registration(
            create_registration_payload(qualifier["id"], program_version(program_id), **_SEAT),
            owner,
        ),
        201,
    )
    accepted = validate_success(
        api_client.respond_registration(
            registration["id"], respond_payload("ACCEPT", waiver_signed=True), owner
        )
    )
    assert accepted["attendance_status"] == "ACCEPTED"
    assert accepted["waiver_on_file"] is True

    confirm_registration(registration["id"])
    advance_program(program_id, "ONSITE")
    activity = create_activity(program_id, **_ACTIVITY)

    signup = validate_success(
        api_client.create_activity_signup(
            create_activity_signup_payload(activity["id"], registration["id"], activity["version"]),
            owner,
        ),
        201,
    )
    assert signup["status"] == "BOOKED"

    surveyed = validate_success(
        api_client.survey_registration(registration["id"], {"satisfaction_score": 9}, owner)
    )
    assert surveyed["satisfaction_score"] == 9

    released = validate_success(api_client.cancel_activity_signup(signup["id"], owner))
    assert released["status"] == "CANCELLED"
    cancelled = validate_success(
        api_client.cancel_registration(
            registration["id"], {"cancellation_reason": "family emergency"}, owner
        )
    )
    assert cancelled["attendance_status"] == "CANCELLED"


def test_tax_compliance_officer_alone_drafts_files_and_voids_the_award_report():
    """TaxComplianceOfficer reaches drafting, filing and voiding.

    PRD §2.1: "owns taxable award reporting: drafting, filing and voiding reports."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    base = _reconciled_solo()
    qualifier = read_qualifier(base["qualifier"]["id"])
    assert qualifier["award_status"] == "TRAVELLED"

    report = validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(qualifier["id"], 2026), _TAX
        ),
        201,
    )
    assert_tax_award_report(report)
    assert report["status"] == "DRAFT"
    assert report["award_value_cents"] == 783_500

    filed = validate_success(api_client.file_tax_award_report(report["id"], _TAX))
    assert filed["status"] == "FILED"
    assert filed["filed_by_user_id"] == "tax-01"

    voided = validate_success(
        api_client.void_tax_award_report(
            report["id"], {"void_reason": "filed against the wrong tax year"}, _TAX_ALT
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_user_id"] == "tax-02"


def test_every_operator_role_may_drive_the_logical_clock_but_participant_may_not():
    """The clock verb is open to all six operator roles and closed to Participant.

    PRD §2.5: "All six operator roles — `ProgramDirector`, `SourcingManager`,
    `ContractApprover`, `SalesOpsAnalyst`, `TravelDesk` and
    `TaxComplianceOfficer` — may set the clock; `Participant` may not."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations_end_to_end
    """
    for offset, headers in enumerate((_PD, _SM, _CA, _AN, _TD, _TAX), start=2):
        instant = f"2026-09-0{offset}T00:00:00Z"
        body = validate_success(api_client.set_clock(clock_payload(instant), headers))
        assert_instant_equals(body["current_utc"], instant, "current_utc")

    refused = api_client.set_clock(
        clock_payload("2026-09-09T00:00:00Z"), TEST_USERS["participant_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    reset_logical_clock()


def _refusal_base():
    """REGISTRATION_OPEN program: executed contract, full deposit schedule,
    a rejected sibling destination, both winners NOTIFIED and one ACCEPTED seat."""
    base = _sourcing_pair(second_destination=True)
    program_id = base["program"]["id"]
    contract = create_contract(program_id, base["destination"]["id"], **_CONTRACT)
    base["milestones"] = [create_milestone(contract["id"], **spec) for spec in _MILESTONES]
    propose_contract(contract["id"], "sm-01")
    execute_contract(contract["id"], "ca-01")
    lock_gross_up_policy(program_id, "FULL_GROSS_UP")
    notify_qualifiers(program_id)
    advance_program(program_id, "REGISTRATION_OPEN")
    owner = base["qualifiers"][0]
    registration = create_registration(owner["id"], program_id=program_id, **_SEAT)
    respond_registration(registration["id"], owner["id"], "ACCEPT", waiver_signed=True)
    base["contract"] = read_contract(contract["id"])
    base["registration"] = read_registration(registration["id"])
    base["program"] = read_program(program_id)
    base["qualifiers"] = [read_qualifier(q["id"]) for q in base["qualifiers"]]
    return base


def test_program_scoped_verbs_refuse_every_role_but_the_director():
    """Program creation, advancement, policy, notification and cancellation are director-only.

    PRD §2.1: "If the role is valid but is not listed among the authorized roles
    for the endpoint being called (see the table in §4), the request is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    base = _refusal_base()
    program_id = base["program"]["id"]

    validate_error(
        api_client.create_program(create_program_payload(), _TD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_award_tier(
            create_award_tier_payload(program_id, tier_code="SILVER", tier_rank=3), _AN
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.advance_program(program_id, advance_payload("ONSITE"), _SM),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.notify_qualifiers(program_id, _TD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.set_gross_up_policy(program_id, gross_up_policy_payload("NONE"), _TAX),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.cancel_program(program_id, {"cancellation_reason": "budget pulled"}, _TD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )


def test_supply_side_verbs_refuse_the_roles_the_matrix_leaves_out():
    """Sourcing, negotiation, execution and payment each answer to one role only.

    PRD §2.1: "If the role is valid but is not listed among the authorized roles
    for the endpoint being called (see the table in §4), the request is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    base = _refusal_base()
    program_id = base["program"]["id"]
    contract_id = base["contract"]["id"]
    sibling_id = base["destination_b"]["id"]

    validate_error(
        api_client.create_destination(create_destination_payload(program_id, **_DESTINATION_B), _PD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.site_inspect_destination(sibling_id, {"inspection_score": 90}, _CA),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.shortlist_destination(sibling_id, _CA),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(program_id, sibling_id, **_CONTRACT), _CA
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_deposit_milestone(
            create_deposit_milestone_payload(contract_id, sequence=4, amount_cents=1), _CA
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.negotiate_contract(contract_id, negotiate_payload("PROPOSE"), _TAX),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.withdraw_contract(contract_id, {"withdrawal_reason": "too late"}, _CA),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.execute_contract(contract_id, _SM),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.pay_deposit_milestone(base["milestones"][0]["id"], _SM),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )


def test_people_side_verbs_refuse_the_roles_the_matrix_leaves_out():
    """Adjudication, confirmation, air, response and tax drafting are single-role verbs.

    PRD §2.1: "If the role is valid but is not listed among the authorized roles
    for the endpoint being called (see the table in §4), the request is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    base = _refusal_base()
    program_id = base["program"]["id"]
    owner = base["qualifiers"][0]
    owner_headers = make_participant_headers(owner["id"])
    registration_id = base["registration"]["id"]

    validate_error(
        api_client.create_qualifier(
            create_qualifier_payload(program_id, employee_code="S-3001"), _PD
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.review_qualifier(owner["id"], _PD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.confirm_registration(registration_id, owner_headers),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.air_registration(registration_id, air_payload("REQUEST"), owner_headers),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.respond_registration(registration_id, respond_payload("DECLINE"), _TD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_onsite_activity(
            create_onsite_activity_payload(program_id, **_ACTIVITY), _PD
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_tax_award_report(create_tax_award_report_payload(owner["id"]), _PD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )


def test_read_endpoints_refuse_the_roles_their_matrix_row_omits():
    """Narrow read rows refuse the roles they leave out, exactly like the write rows.

    PRD §2.8: "Role authorization — the supplied role appears in the called
    endpoint's authorized-role list. Applies to every endpoint. Violation:
    `ERR_ROLE_NOT_PERMITTED`, HTTP 403."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    base = _refusal_base()
    program_id = base["program"]["id"]
    contract_id = base["contract"]["id"]
    owner_headers = make_participant_headers(base["qualifiers"][0]["id"])

    validate_error(
        api_client.get_program_measurement(program_id, _TD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.list_programs(TEST_USERS["participant_headers"]),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.list_qualifiers(owner_headers),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.get_destination(base["destination"]["id"], _TAX),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.get_supplier_contract(contract_id, owner_headers),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.get_deposit_milestone(base["milestones"][0]["id"], _TD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.get_exposure_projection(contract_id, _AN),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.list_tax_award_reports(_AN),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )


def test_a_refused_role_leaves_every_row_byte_for_byte_unchanged():
    """A batch of role refusals mutates nothing: no state, no version, no timestamp.

    PRD §2.8: "When a single request would fail more than one check, the check
    with the lowest priority number below wins and its error is the one returned."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    base = _refusal_base()
    program_id = base["program"]["id"]
    contract_id = base["contract"]["id"]
    registration_id = base["registration"]["id"]
    milestone_id = base["milestones"][0]["id"]
    owner_headers = make_participant_headers(base["qualifiers"][0]["id"])

    program_before = read_program(program_id)
    contract_before = read_contract(contract_id)
    registration_before = read_registration(registration_id)
    milestone_before = read_milestone(milestone_id)
    _, meta_before = validate_paginated(
        api_client.list_registrations(_TD, {"program_id": program_id})
    )

    for response in (
        api_client.advance_program(program_id, advance_payload("ONSITE"), _SM),
        api_client.execute_contract(contract_id, _SM),
        api_client.pay_deposit_milestone(milestone_id, _SM),
        api_client.confirm_registration(registration_id, owner_headers),
        api_client.cancel_program(program_id, {"cancellation_reason": "not authorised"}, _TD),
        api_client.create_registration(
            create_registration_payload(base["qualifiers"][1]["id"], program_before["version"]), _AN
        ),
    ):
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    assert read_program(program_id) == program_before
    assert read_contract(contract_id) == contract_before
    assert read_registration(registration_id) == registration_before
    assert read_milestone(milestone_id) == milestone_before
    _, meta_after = validate_paginated(
        api_client.list_registrations(_TD, {"program_id": program_id})
    )
    assert meta_after["total_count"] == meta_before["total_count"]


def test_role_authorization_is_decided_before_any_existence_check():
    """A forbidden role aimed at a non-existent id still gets the 403, never the 404.

    PRD §2.8: "Path existence — every templated id in the URL resolves to an
    existing row, validated strictly left to right, so the leftmost unresolvable
    segment decides the error."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    validate_error(
        api_client.execute_contract(NON_EXISTENT_UUID, _SM),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.execute_contract(NON_EXISTENT_UUID, _CA),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND, 404,
    )

    validate_error(
        api_client.pay_deposit_milestone(NON_EXISTENT_UUID, _SM),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.pay_deposit_milestone(NON_EXISTENT_UUID, _CA),
        ApiErrorId.ERR_MILESTONE_NOT_FOUND, 404,
    )

    validate_error(
        api_client.respond_registration(NON_EXISTENT_UUID, respond_payload("ACCEPT"), _TD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_qualifier(create_qualifier_payload(NON_EXISTENT_UUID), _PD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_qualifier(create_qualifier_payload(NON_EXISTENT_UUID), _AN),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404,
    )


def test_role_authorization_is_decided_before_the_request_schema():
    """A malformed body from a forbidden role reports the role, not the schema.

    PRD §2.8: "Request schema — all required fields present, correct JSON types,
    enum values inside their declared sets and integers inside their declared
    ranges."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    program = create_program(budget_total_cents=5_000_000)
    broken = create_award_tier_payload(program["id"], **_PLATINUM)
    broken.pop("tier_rank")

    validate_error(
        api_client.create_award_tier(broken, _AN),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.create_award_tier(broken, _PD),
        ApiErrorId.ERR_INVALID_REQUEST, 400,
    )


def test_the_two_authentication_rungs_outrank_role_authorization_and_existence():
    """Absent, empty and unrecognised auth headers are answered before anything else.

    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request
    is examined."

    Design: Corner/rbac/role_matrix_refusals_are_returned_before_any_state_or_existence_check
    """
    program = create_program(budget_total_cents=5_000_000)

    validate_error(
        api_client.get_program(program["id"], _NO_AUTH),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401,
    )
    validate_error(
        api_client.get_program(program["id"], build_user_headers("", "ProgramDirector")),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401,
    )
    validate_error(
        api_client.get_program(program["id"], build_user_headers("pd-01", "")),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401,
    )
    # Priority 1 outranks priority 2: an empty id beats an unrecognised role.
    validate_error(
        api_client.get_program(program["id"], build_user_headers("", "Wizard")),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401,
    )
    # Priority 2 outranks priority 3 on a role the endpoint would refuse anyway.
    validate_error(
        api_client.create_program(create_program_payload(), build_user_headers("pd-01", "Wizard")),
        ApiErrorId.ERR_INVALID_ROLE, 401,
    )
    # ... and both outrank path existence.
    validate_error(
        api_client.get_program(NON_EXISTENT_UUID, _NO_AUTH),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401,
    )
    validate_error(
        api_client.get_program(NON_EXISTENT_UUID, build_user_headers("pd-01", "Wizard")),
        ApiErrorId.ERR_INVALID_ROLE, 401,
    )


def _two_invited_seats():
    """REGISTRATION_OPEN program where each of the two winners holds its own INVITED seat."""
    base = _registration_open_pair()
    program_id = base["program"]["id"]
    base["registrations"] = [
        create_registration(qualifier["id"], program_id=program_id, **_SEAT)
        for qualifier in base["qualifiers"]
    ]
    return base


def test_one_qualifier_cannot_answer_another_qualifiers_invitation():
    """The response verb is keyed to the acting Qualifier row, not to the role.

    PRD §2.1: "A `Participant` whose `X-User-ID` does not match the owning
    qualifier is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _two_invited_seats()
    ana, ben = base["qualifiers"]
    ana_seat, ben_seat = base["registrations"]
    assert ana["id"] != ben["id"]

    validate_error(
        api_client.respond_registration(
            ana_seat["id"], respond_payload("ACCEPT", waiver_signed=True),
            make_participant_headers(ben["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    assert read_registration(ana_seat["id"])["attendance_status"] == "INVITED"

    accepted = validate_success(
        api_client.respond_registration(
            ana_seat["id"], respond_payload("ACCEPT", waiver_signed=True),
            make_participant_headers(ana["id"]),
        )
    )
    assert accepted["attendance_status"] == "ACCEPTED"
    assert read_registration(ben_seat["id"])["attendance_status"] == "INVITED"


def test_a_participant_cannot_read_another_qualifiers_seat_or_award_row():
    """The two guarded single reads are owner-only for a Participant.

    PRD §2.1: "This check guards nine operations: creating a registration,
    responding to an invitation, cancelling a registration, submitting a survey,
    creating an activity signup, cancelling an activity signup, reading a single
    registration, reading a single qualifier, and reading a single activity signup."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _two_invited_seats()
    ana, ben = base["qualifiers"]
    ana_seat, ben_seat = base["registrations"]
    as_ana = make_participant_headers(ana["id"])
    as_ben = make_participant_headers(ben["id"])

    validate_error(
        api_client.get_registration(ana_seat["id"], as_ben),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    validate_error(
        api_client.get_qualifier(ana["id"], as_ben),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )

    assert validate_success(api_client.get_registration(ana_seat["id"], as_ana))["id"] == ana_seat["id"]
    assert validate_success(api_client.get_qualifier(ana["id"], as_ana))["id"] == ana["id"]
    assert validate_success(api_client.get_registration(ben_seat["id"], as_ben))["id"] == ben_seat["id"]
    assert validate_success(api_client.get_qualifier(ben["id"], as_ben))["id"] == ben["id"]


def test_a_participant_cannot_enrol_a_guest_against_another_qualifier():
    """Enrolment is owner-only and a refused enrolment mints no seat.

    PRD §2.8: "Participant ownership — when the role is `Participant`,
    `X-User-ID` equals the `id` of the `Qualifier` that owns the target resource."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _two_invited_seats()
    program_id = base["program"]["id"]
    ana, ben = base["qualifiers"]
    ana_seat = base["registrations"][0]

    payload = create_registration_payload(
        ana["id"], program_version(program_id), registration_kind="GUEST",
        guest_of_registration_id=ana_seat["id"], **_SEAT
    )
    validate_error(
        api_client.create_registration(payload, make_participant_headers(ben["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )

    _, meta = validate_paginated(
        api_client.list_registrations(_TD, {"qualifier_id": ana["id"]})
    )
    assert meta["total_count"] == 1


def test_existence_outranks_ownership_and_an_unknown_identity_owns_nothing():
    """A missing row answers 404 first; a live row answers 403 to a stranger.

    PRD §2.8: "Path existence — every templated id in the URL resolves to an
    existing row, validated strictly left to right, so the leftmost unresolvable
    segment decides the error."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _two_invited_seats()
    ana, ben = base["qualifiers"]
    ana_seat = base["registrations"][0]
    as_ben = make_participant_headers(ben["id"])

    validate_error(
        api_client.respond_registration(NON_EXISTENT_UUID, respond_payload("ACCEPT"), as_ben),
        ApiErrorId.ERR_REGISTRATION_NOT_FOUND, 404,
    )
    validate_error(
        api_client.get_registration(NON_EXISTENT_UUID, as_ben),
        ApiErrorId.ERR_REGISTRATION_NOT_FOUND, 404,
    )
    validate_error(
        api_client.get_qualifier(NON_EXISTENT_UUID, as_ben),
        ApiErrorId.ERR_QUALIFIER_NOT_FOUND, 404,
    )
    validate_error(
        api_client.get_registration(ana_seat["id"], make_participant_headers(NON_EXISTENT_UUID)),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    validate_error(
        api_client.respond_registration(
            ana_seat["id"], respond_payload("ACCEPT"), TEST_USERS["participant_headers"]
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    assert read_registration(ana_seat["id"])["attendance_status"] == "INVITED"


def test_the_ownership_gate_applies_only_to_the_participant_role():
    """Operator roles read any seat or award row without an ownership check.

    PRD §2.8: "Participant ownership — when the role is `Participant`,
    `X-User-ID` equals the `id` of the `Qualifier` that owns the target resource."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _two_invited_seats()
    ana = base["qualifiers"][0]
    ana_seat = base["registrations"][0]

    for headers in (_TD, _AN, _PD, _TAX):
        assert validate_success(api_client.get_registration(ana_seat["id"], headers))["id"] == ana_seat["id"]
    for headers in (_TD, _AN, _PD, _SM, _CA, _TAX):
        assert validate_success(api_client.get_qualifier(ana["id"], headers))["id"] == ana["id"]


def test_ownership_is_decided_before_the_target_seats_own_state():
    """A stranger gets 403 on an already-answered seat; the owner gets the state error.

    PRD §2.8: "When a single request would fail more than one check, the check
    with the lowest priority number below wins and its error is the one returned."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _two_invited_seats()
    ana, ben = base["qualifiers"]
    ben_seat = base["registrations"][1]
    as_ana = make_participant_headers(ana["id"])
    as_ben = make_participant_headers(ben["id"])

    accepted = validate_success(
        api_client.respond_registration(
            ben_seat["id"], respond_payload("ACCEPT", waiver_signed=True), as_ben
        )
    )
    assert accepted["attendance_status"] == "ACCEPTED"

    validate_error(
        api_client.respond_registration(ben_seat["id"], respond_payload("DECLINE"), as_ana),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    validate_error(
        api_client.respond_registration(ben_seat["id"], respond_payload("DECLINE"), as_ben),
        ApiErrorId.ERR_REGISTRATION_STATE_INVALID, 409,
    )


def test_registration_side_ownership_guards_cancellation_and_the_survey():
    """Cancelling a seat and scoring it are owner-only Participant operations.

    PRD §2.1: "A `Participant` whose `X-User-ID` does not match the owning
    qualifier is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _onsite_pair_with_activity()
    ana, ben = base["qualifiers"]
    ana_seat, ben_seat = base["registrations"]
    as_ana = make_participant_headers(ana["id"])
    as_ben = make_participant_headers(ben["id"])

    validate_error(
        api_client.survey_registration(ana_seat["id"], {"satisfaction_score": 8}, as_ben),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    validate_error(
        api_client.cancel_registration(
            ana_seat["id"], {"cancellation_reason": "not my seat"}, as_ben
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )

    surveyed = validate_success(
        api_client.survey_registration(ana_seat["id"], {"satisfaction_score": 8}, as_ana)
    )
    assert surveyed["satisfaction_score"] == 8
    cancelled = validate_success(
        api_client.cancel_registration(
            ana_seat["id"], {"cancellation_reason": "family emergency"}, as_ana
        )
    )
    assert cancelled["attendance_status"] == "CANCELLED"
    assert read_registration(ben_seat["id"])["attendance_status"] == "CONFIRMED"


def test_signup_side_ownership_guards_creation_reading_and_release():
    """A signup belongs to the seat's qualifier, so a stranger can neither book nor release it.

    PRD §2.1: "This check guards nine operations: creating a registration,
    responding to an invitation, cancelling a registration, submitting a survey,
    creating an activity signup, cancelling an activity signup, reading a single
    registration, reading a single qualifier, and reading a single activity signup."

    Design: Corner/rbac/participant_identity_is_entity_backed_so_one_qualifier_cannot_touch_another
    """
    base = _onsite_pair_with_activity()
    activity = base["activity"]
    ana, ben = base["qualifiers"]
    ana_seat = base["registrations"][0]
    as_ana = make_participant_headers(ana["id"])
    as_ben = make_participant_headers(ben["id"])

    signup = validate_success(
        api_client.create_activity_signup(
            create_activity_signup_payload(
                activity["id"], ana_seat["id"], activity_version(activity["id"])
            ),
            as_ana,
        ),
        201,
    )
    assert signup["status"] == "BOOKED"

    validate_error(
        api_client.create_activity_signup(
            create_activity_signup_payload(
                activity["id"], ana_seat["id"], activity_version(activity["id"])
            ),
            as_ben,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    validate_error(
        api_client.get_activity_signup(signup["id"], as_ben),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )
    validate_error(
        api_client.cancel_activity_signup(signup["id"], as_ben),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403,
    )

    assert validate_success(api_client.get_activity_signup(signup["id"], as_ana))["id"] == signup["id"]
    released = validate_success(api_client.cancel_activity_signup(signup["id"], as_ana))
    assert released["status"] == "CANCELLED"


def _negotiated_contract():
    """A PROPOSED contract after PROPOSE(sm-01), COUNTER(ca-01), PROPOSE(sm-01)."""
    base = _sourcing_pair()
    contract = create_contract(
        base["program"]["id"], base["destination"]["id"], **_CONTRACT
    )
    propose_contract(contract["id"], "sm-01")
    counter_contract(contract["id"], "ca-01", nightly_rate_cents=37_000)
    propose_contract(contract["id"], "sm-01", nightly_rate_cents=38_500)
    base["contract"] = read_contract(contract["id"])
    assert base["contract"]["status"] == "PROPOSED"
    assert base["contract"]["round_count"] == 3
    assert base["contract"]["last_proposed_by_user_id"] == "sm-01"
    assert base["contract"]["last_countered_by_user_id"] == "ca-01"
    return base


def test_the_counterparty_who_countered_cannot_execute_its_own_contract():
    """ca-01 countered this contract, so ca-01 is barred from executing it.

    PRD §2.9: "A `SupplierContract` may only be executed by a `ContractApprover`
    whose `X-User-ID` differs from both `last_proposed_by_user_id` and
    `last_countered_by_user_id` on that contract; if it matches either, the
    attempt fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/rbac/contract_execution_requires_a_user_id_that_neither_proposed_nor_countered
    """
    base = _negotiated_contract()
    contract_id = base["contract"]["id"]

    validate_error(
        api_client.execute_contract(contract_id, make_contract_approver_headers("ca-01")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422,
    )

    unchanged = read_contract(contract_id)
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["round_count"] == 3
    assert unchanged["executed_by_user_id"] is None
    assert unchanged["executed_at"] is None
    assert unchanged["room_nights_blocked"] == 0
    assert read_program(base["program"]["id"])["status"] == "SOURCING"
    assert read_destination(base["destination"]["id"])["status"] == "SHORTLISTED"


def test_the_identity_that_proposed_cannot_execute_even_wearing_the_approver_role():
    """The guard compares user ids, not roles: sm-01 under ContractApprover still fails.

    PRD §2.9: "A `SupplierContract` may only be executed by a `ContractApprover`
    whose `X-User-ID` differs from both `last_proposed_by_user_id` and
    `last_countered_by_user_id` on that contract; if it matches either, the
    attempt fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/rbac/contract_execution_requires_a_user_id_that_neither_proposed_nor_countered
    """
    base = _negotiated_contract()
    contract_id = base["contract"]["id"]

    validate_error(
        api_client.execute_contract(contract_id, make_contract_approver_headers("sm-01")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422,
    )
    assert read_contract(contract_id)["status"] == "PROPOSED"


def test_the_role_gate_outranks_the_duty_separation_gate():
    """A clean identity wearing the wrong role is refused for the role, not the duty.

    PRD §2.8: "Role authorization — the supplied role appears in the called
    endpoint's authorized-role list. Applies to every endpoint. Violation:
    `ERR_ROLE_NOT_PERMITTED`, HTTP 403."

    Design: Corner/rbac/contract_execution_requires_a_user_id_that_neither_proposed_nor_countered
    """
    base = _negotiated_contract()
    contract_id = base["contract"]["id"]

    validate_error(
        api_client.execute_contract(contract_id, make_sourcing_manager_headers("ca-02")),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    validate_error(
        api_client.execute_contract(contract_id, make_sourcing_manager_headers("sm-01")),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )
    assert read_contract(contract_id)["status"] == "PROPOSED"


def test_a_third_approver_executes_and_the_contract_then_refuses_a_second_execution():
    """ca-02 neither proposed nor countered, so its execution stands and cascades.

    PRD §2.9: "A `SupplierContract` may only be executed by a `ContractApprover`
    whose `X-User-ID` differs from both `last_proposed_by_user_id` and
    `last_countered_by_user_id` on that contract; if it matches either, the
    attempt fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/rbac/contract_execution_requires_a_user_id_that_neither_proposed_nor_countered
    """
    base = _negotiated_contract()
    contract_id = base["contract"]["id"]

    executed = validate_success(
        api_client.execute_contract(contract_id, make_contract_approver_headers("ca-02"))
    )
    assert executed["status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == "ca-02"
    assert_instant_equals(executed["executed_at"], LOGICAL_CLOCK_DEFAULT, "executed_at")
    assert executed["round_count"] == 3

    program = read_program(base["program"]["id"])
    assert program["status"] == "CONTRACTED"
    assert program["per_person_cost_basis_cents"] == 431_757
    assert program["committed_budget_cents"] == 1_443_174

    validate_error(
        api_client.execute_contract(contract_id, make_contract_approver_headers("ca-03")),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409,
    )
    assert read_contract(contract_id)["round_count"] == 3


def _filed_report():
    """A FILED FULL_GROSS_UP report on a travelled PLATINUM winner, filed by tax-01."""
    return setup_filed_tax_report(
        gross_up_policy="FULL_GROSS_UP",
        filer_user_id="tax-01",
        qualifier_specs=[_QUALIFIER_A],
        registration_overrides=_SEAT,
        **_canonical_kwargs(),
    )


def test_the_officer_who_filed_a_report_cannot_void_it():
    """Self-review is refused: the filer's own id cannot void the filing.

    PRD §2.9: "A `TaxAwardReport` may only be voided by a
    `TaxComplianceOfficer` whose `X-User-ID` differs from the report's
    `filed_by_user_id`; if it matches, the attempt fails with
    `ERR_TAX_VOID_SELF_REVIEW` (HTTP 422)."

    Design: Corner/rbac/a_filed_tax_report_can_only_be_voided_by_a_different_officer
    """
    base = _filed_report()
    report = base["report"]
    assert report["status"] == "FILED"
    assert report["filed_by_user_id"] == "tax-01"
    assert report["award_value_cents"] == 783_500
    assert report["reported_value_cents"] == 1_198_929
    assert_reported_value_identity(report)

    validate_error(
        api_client.void_tax_award_report(
            report["id"], {"void_reason": "duplicate filing"},
            make_tax_officer_headers("tax-01"),
        ),
        ApiErrorId.ERR_TAX_VOID_SELF_REVIEW, 422,
    )

    unchanged = read_tax_report(report["id"])
    assert unchanged["status"] == "FILED"
    assert unchanged["voided_by_user_id"] is None
    assert read_qualifier(base["qualifier"]["id"])["tax_status"] == "REPORTED"
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 1_198_929


def test_a_second_officer_voids_the_filing_and_the_reported_total_is_compensated():
    """tax-02 differs from the filer, so the void stands and reverses the total exactly.

    PRD §2.9: "A `TaxAwardReport` may only be voided by a
    `TaxComplianceOfficer` whose `X-User-ID` differs from the report's
    `filed_by_user_id`; if it matches, the attempt fails with
    `ERR_TAX_VOID_SELF_REVIEW` (HTTP 422)."

    Design: Corner/rbac/a_filed_tax_report_can_only_be_voided_by_a_different_officer
    """
    base = _filed_report()
    report = base["report"]

    validate_error(
        api_client.void_tax_award_report(report["id"], {"void_reason": "wrong year"}, _PD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403,
    )

    voided = validate_success(
        api_client.void_tax_award_report(
            report["id"], {"void_reason": "filed against the wrong tax year"},
            make_tax_officer_headers("tax-02"),
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_user_id"] == "tax-02"
    assert voided["filed_by_user_id"] == "tax-01"
    assert_instant_equals(voided["filed_at"], report["filed_at"], "filed_at")

    assert read_qualifier(base["qualifier"]["id"])["tax_status"] == "VOIDED"
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 0


def test_a_voided_report_is_terminal_and_leaves_the_award_unreported():
    """A void cannot be repeated, and the voided award blocks the move to CLOSED.

    PRD §2.9: "A `TaxAwardReport` may only be voided by a
    `TaxComplianceOfficer` whose `X-User-ID` differs from the report's
    `filed_by_user_id`; if it matches, the attempt fails with
    `ERR_TAX_VOID_SELF_REVIEW` (HTTP 422)."

    Design: Corner/rbac/a_filed_tax_report_can_only_be_voided_by_a_different_officer
    """
    base = _filed_report()
    report = base["report"]
    void_tax_report(report["id"], voider_user_id="tax-02")

    validate_error(
        api_client.void_tax_award_report(
            report["id"], {"void_reason": "voided again"},
            make_tax_officer_headers("tax-03"),
        ),
        ApiErrorId.ERR_TAX_REPORT_STATE_INVALID, 409,
    )

    qualifier = read_qualifier(base["qualifier"]["id"])
    assert qualifier["taxable_award_cents"] == 783_500
    assert qualifier["tax_status"] == "VOIDED"
    validate_error(
        api_client.advance_program(base["program"]["id"], advance_payload("CLOSED"), _PD),
        ApiErrorId.ERR_TAX_REPORTING_INCOMPLETE, 422,
    )


def test_a_stale_expected_program_version_is_rejected_and_mints_no_seat():
    """An enrolment carrying a version the program has already left is refused.

    PRD §2.7: "If that value does not equal the program's current `version`, the
    create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_program_version_on_registration_create_is_rejected
    """
    base = _registration_open_pair()
    program_id = base["program"]["id"]
    ana, ben = base["qualifiers"]

    stale = program_version(program_id)
    create_registration(ana["id"], program_id=program_id, expected_program_version=stale, **_SEAT)
    current = program_version(program_id)
    assert current == stale + 1

    validate_error(
        api_client.create_registration(
            create_registration_payload(ben["id"], stale, **_SEAT), _TD
        ),
        ApiErrorId.ERR_STALE_PROGRAM_VERSION, 412,
    )

    _, meta = validate_paginated(api_client.list_registrations(_TD, {"qualifier_id": ben["id"]}))
    assert meta["total_count"] == 0
    assert program_version(program_id) == current
    assert read_qualifier(ben["id"])["award_status"] == "NOTIFIED"


def test_the_program_version_guard_demands_equality_not_merely_freshness():
    """A version ahead of the program's own is just as stale as one behind it.

    PRD §2.7: "A request to `POST /registrations` must carry
    `expected_program_version` as a required, non-optional integer field holding
    the `version` of the target `Program` as the client last observed it."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_program_version_on_registration_create_is_rejected
    """
    base = _registration_open_pair()
    program_id = base["program"]["id"]
    ben = base["qualifiers"][1]
    current = program_version(program_id)

    for candidate in (current + 1, current + 5):
        validate_error(
            api_client.create_registration(
                create_registration_payload(ben["id"], candidate, **_SEAT), _TD
            ),
            ApiErrorId.ERR_STALE_PROGRAM_VERSION, 412,
        )
    assert program_version(program_id) == current


def test_the_request_schema_is_checked_before_the_program_version_guard():
    """A missing or non-integer guard field is a schema failure, not a stale version.

    PRD §2.8: "Request schema — all required fields present, correct JSON types,
    enum values inside their declared sets and integers inside their declared
    ranges."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_program_version_on_registration_create_is_rejected
    """
    base = _registration_open_pair()
    program_id = base["program"]["id"]
    ben = base["qualifiers"][1]
    stale = program_version(program_id) - 1

    omitted = create_registration_payload(ben["id"], stale, **_SEAT)
    omitted.pop("expected_program_version")
    validate_error(
        api_client.create_registration(omitted, _TD), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    as_text = create_registration_payload(ben["id"], stale, **_SEAT)
    as_text["expected_program_version"] = str(stale)
    validate_error(
        api_client.create_registration(as_text, _TD), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    _, meta = validate_paginated(api_client.list_registrations(_TD, {"qualifier_id": ben["id"]}))
    assert meta["total_count"] == 0


def test_each_accepted_enrolment_bumps_the_program_version_the_next_one_must_carry():
    """Every seat minted moves the comparand, so the guard must be re-read each time.

    PRD §3.6: "Creating a seat increments the **program's** `version` by 1 as well
    as minting the registration at `version` 1 — which is exactly why the next
    enrolment must carry a freshly read `expected_program_version`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_program_version_on_registration_create_is_rejected
    """
    base = _registration_open_pair()
    program_id = base["program"]["id"]
    ana, ben = base["qualifiers"]

    first_version = program_version(program_id)
    ana_seat = validate_success(
        api_client.create_registration(
            create_registration_payload(ana["id"], first_version, **_SEAT), _TD
        ),
        201,
    )
    assert ana_seat["attendance_status"] == "INVITED"
    assert_version_is(ana_seat, 1, "registration")

    second_version = program_version(program_id)
    assert second_version == first_version + 1
    ben_seat = validate_success(
        api_client.create_registration(
            create_registration_payload(ben["id"], second_version, **_SEAT), _TD
        ),
        201,
    )
    assert ben_seat["attendance_status"] == "INVITED"
    assert program_version(program_id) == second_version + 1

    guest = create_registration_payload(
        ana["id"], second_version, registration_kind="GUEST",
        guest_of_registration_id=ana_seat["id"], **_SEAT
    )
    validate_error(
        api_client.create_registration(guest, _TD),
        ApiErrorId.ERR_STALE_PROGRAM_VERSION, 412,
    )

    guest["expected_program_version"] = program_version(program_id)
    guest_seat = validate_success(api_client.create_registration(guest, _TD), 201)
    assert guest_seat["registration_kind"] == "GUEST"
    assert guest_seat["guest_of_registration_id"] == ana_seat["id"]


def test_a_stale_expected_activity_version_is_rejected_and_takes_no_slot():
    """A signup carrying a version the activity has already left is refused.

    PRD §2.7: "If that value does not equal the activity's current `version`, the
    signup is rejected with `ERR_STALE_ACTIVITY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_activity_version_on_signup_create_is_rejected
    """
    base = _onsite_pair_with_activity()
    activity_id = base["activity"]["id"]
    ana_seat, ben_seat = base["registrations"]

    stale = activity_version(activity_id)
    create_signup(activity_id, ana_seat["id"], stale)
    current = activity_version(activity_id)
    assert current == stale + 1

    validate_error(
        api_client.create_activity_signup(
            create_activity_signup_payload(activity_id, ben_seat["id"], stale), _TD
        ),
        ApiErrorId.ERR_STALE_ACTIVITY_VERSION, 412,
    )

    assert_signup_counters(read_activity(activity_id), 1, 0)
    _, meta = validate_paginated(
        api_client.list_activity_signups(_TD, {"registration_id": ben_seat["id"]})
    )
    assert meta["total_count"] == 0
    assert activity_version(activity_id) == current


def test_the_activity_version_guard_demands_equality_and_a_present_integer():
    """A version ahead of the activity's own is stale, and an absent guard is a schema error.

    PRD §2.7: "A request to `POST /activity-signups` must carry
    `expected_activity_version` as a required, non-optional integer field holding
    the `version` of the target `OnsiteActivity` as the client last observed it."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_activity_version_on_signup_create_is_rejected
    """
    base = _onsite_pair_with_activity()
    activity_id = base["activity"]["id"]
    ana_seat = base["registrations"][0]
    current = activity_version(activity_id)

    for candidate in (current + 1, current + 3):
        validate_error(
            api_client.create_activity_signup(
                create_activity_signup_payload(activity_id, ana_seat["id"], candidate), _TD
            ),
            ApiErrorId.ERR_STALE_ACTIVITY_VERSION, 412,
        )

    validate_error(
        api_client.create_activity_signup(
            {"activity_id": activity_id, "registration_id": ana_seat["id"]}, _TD
        ),
        ApiErrorId.ERR_INVALID_REQUEST, 400,
    )
    validate_error(
        api_client.create_activity_signup(
            {"activity_id": activity_id, "registration_id": ana_seat["id"],
             "expected_activity_version": str(current)},
            _TD,
        ),
        ApiErrorId.ERR_INVALID_REQUEST, 400,
    )
    assert_signup_counters(read_activity(activity_id), 0, 0)


def test_a_signup_carrying_the_live_activity_version_books_and_moves_the_comparand():
    """The freshly read version is accepted and the accepted signup moves it on.

    PRD §3.8: "Every accepted signup increments the parent activity's `version` by
    1, which is what makes the next client's `expected_activity_version` go stale."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_activity_version_on_signup_create_is_rejected
    """
    base = _onsite_pair_with_activity()
    activity_id = base["activity"]["id"]
    ana_seat, ben_seat = base["registrations"]

    first = activity_version(activity_id)
    ana_signup = validate_success(
        api_client.create_activity_signup(
            create_activity_signup_payload(activity_id, ana_seat["id"], first), _TD
        ),
        201,
    )
    assert ana_signup["status"] == "BOOKED"

    second = activity_version(activity_id)
    assert second == first + 1
    ben_signup = validate_success(
        api_client.create_activity_signup(
            create_activity_signup_payload(activity_id, ben_seat["id"], second), _TD
        ),
        201,
    )
    assert ben_signup["status"] == "BOOKED"
    assert_signup_counters(read_activity(activity_id), 2, 0)
    assert activity_version(activity_id) == second + 1


def test_releasing_a_slot_also_moves_the_comparand_a_waiting_client_holds():
    """A release bumps the activity version, so a pre-release read is stale even with free capacity.

    PRD §3.8: "Either release increments the parent activity's `version` by 1
    alongside the signup's own."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_activity_version_on_signup_create_is_rejected
    """
    base = _onsite_pair_with_activity()
    activity_id = base["activity"]["id"]
    ana_seat, ben_seat = base["registrations"]

    ana_signup = create_signup(activity_id, ana_seat["id"], activity_version(activity_id))
    observed = activity_version(activity_id)
    cancel_signup(ana_signup["id"])
    assert activity_version(activity_id) == observed + 1
    assert_signup_counters(read_activity(activity_id), 0, 0)

    validate_error(
        api_client.create_activity_signup(
            create_activity_signup_payload(activity_id, ben_seat["id"], observed), _TD
        ),
        ApiErrorId.ERR_STALE_ACTIVITY_VERSION, 412,
    )

    booked = validate_success(
        api_client.create_activity_signup(
            create_activity_signup_payload(
                activity_id, ben_seat["id"], activity_version(activity_id)
            ),
            _TD,
        ),
        201,
    )
    assert booked["status"] == "BOOKED"
    assert_signup_counters(read_activity(activity_id), 1, 0)


def _cascade_ready():
    """A PROPOSED contract with its full schedule, a sibling candidate destination
    and both winners adjudicated before any per-person basis exists."""
    reset_logical_clock()
    base = _sourcing_pair(second_destination=True)
    contract = create_contract(
        base["program"]["id"], base["destination"]["id"], **_CONTRACT
    )
    base["milestones"] = [create_milestone(contract["id"], **spec) for spec in _MILESTONES]
    propose_contract(contract["id"], "sm-01")
    base["contract"] = read_contract(contract["id"])
    return base


def test_the_whole_five_level_execution_cascade_is_visible_on_the_first_read():
    """Execution's five levels are all readable in the very next reads, with no lag.

    PRD §2.10: "Where §3 lists the steps of a cascade, they are applied in the
    listed order, and every step that matches its selection criteria is applied —
    a cascade never stops early because one of its steps found nothing to do."

    Design: Corner/consistency_model/the_five_level_execution_cascade_is_fully_readable_on_the_first_read_after_it
    """
    base = _cascade_ready()
    contract_id = base["contract"]["id"]
    ana, ben = base["qualifiers"]

    executed = validate_success(api_client.execute_contract(contract_id, _CA))
    assert executed["status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == "ca-01"
    assert_instant_equals(executed["executed_at"], LOGICAL_CLOCK_DEFAULT, "executed_at")
    assert executed["room_nights_blocked"] == 60
    assert executed["room_nights_confirmed"] == 0
    assert executed["room_nights_available"] == 60
    assert executed["attrition_posture"] == "AT_RISK"
    assert_room_nights_conserved(executed)

    program = read_program(base["program"]["id"])
    assert program["status"] == "CONTRACTED"
    assert program["per_person_cost_basis_cents"] == 431_757
    assert program["committed_budget_cents"] == 1_443_174
    assert program["budget_headroom_cents"] == 3_556_826
    assert program["budget_posture"] == "OK"
    assert program["cancellation_exposure_cents"] == 1_848_000
    assert program["qualified_count"] == 2
    assert_budget_conserved(program)

    assert read_destination(base["destination"]["id"])["status"] == "SELECTED"
    assert read_destination(base["destination_b"]["id"])["status"] == "REJECTED"
    assert read_qualifier(ana["id"])["committed_cost_cents"] == 921_765
    assert read_qualifier(ben["id"])["committed_cost_cents"] == 521_409


def test_the_schedule_and_the_exposure_projection_are_current_on_their_first_read():
    """Level five and the exposure recompute are readable immediately after execution.

    PRD §2.10: "Aggregates are **recomputed, never patched**. ... are all defined
    as functions of the current row set, and are re-derived from that row set
    whenever their inputs change rather than being incrementally adjusted."

    Design: Corner/consistency_model/the_five_level_execution_cascade_is_fully_readable_on_the_first_read_after_it
    """
    base = _cascade_ready()
    contract_id = base["contract"]["id"]
    execute_contract(contract_id, "ca-01")

    milestones, meta = validate_paginated(
        api_client.list_deposit_milestones(_CA, {"contract_id": contract_id})
    )
    assert meta["total_count"] == 3
    assert [m["sequence"] for m in milestones] == [1, 2, 3]
    for milestone in milestones:
        assert milestone["status"] == "SCHEDULED"
        assert milestone["requires_finance_review"] is False
        assert milestone["paid_at"] is None

    projection = validate_success(api_client.get_exposure_projection(contract_id, _CA))
    assert projection["contract_value_cents"] == 2_310_000
    assert projection["room_nights_blocked"] == 60
    assert projection["room_nights_confirmed"] == 0
    assert projection["attrition_floor_room_nights"] == 48
    assert projection["shortfall_room_nights"] == 48
    assert projection["attrition_basis_cents"] == 1_848_000
    assert projection["binding_basis"] == "ATTRITION_BASIS"
    assert projection["binding_exposure_cents"] == 1_848_000


def test_a_second_pass_of_reads_after_the_cascade_is_identical_to_the_first():
    """Nothing settles late: reading everything twice returns the same bodies.

    PRD §2.10: "Two quantities are **conserved at every step**. The program's
    `committed_budget_cents` plus its `budget_headroom_cents` always equals its
    `budget_total_cents`, even when the headroom is negative."

    Design: Corner/consistency_model/the_five_level_execution_cascade_is_fully_readable_on_the_first_read_after_it
    """
    base = _cascade_ready()
    contract_id = base["contract"]["id"]
    program_id = base["program"]["id"]
    execute_contract(contract_id, "ca-01")

    first = {
        "program": read_program(program_id),
        "contract": read_contract(contract_id),
        "selected": read_destination(base["destination"]["id"]),
        "rejected": read_destination(base["destination_b"]["id"]),
        "ana": read_qualifier(base["qualifiers"][0]["id"]),
        "ben": read_qualifier(base["qualifiers"][1]["id"]),
        "projection": read_exposure_projection(contract_id),
    }
    second = {
        "program": read_program(program_id),
        "contract": read_contract(contract_id),
        "selected": read_destination(base["destination"]["id"]),
        "rejected": read_destination(base["destination_b"]["id"]),
        "ana": read_qualifier(base["qualifiers"][0]["id"]),
        "ben": read_qualifier(base["qualifiers"][1]["id"]),
        "projection": read_exposure_projection(contract_id),
    }
    assert second == first
    assert_budget_conserved(first["program"])
    assert_room_nights_conserved(first["contract"])


def _accepted_seat():
    """REGISTRATION_OPEN program where the PLATINUM winner holds an ACCEPTED seat."""
    base = _registration_open_pair()
    ana = base["qualifiers"][0]
    seat = create_registration(ana["id"], program_id=base["program"]["id"], **_SEAT)
    respond_registration(seat["id"], ana["id"], "ACCEPT", waiver_signed=True)
    base["registration"] = read_registration(seat["id"])
    return base


def test_a_confirmation_is_fully_derived_on_the_first_read_of_every_touched_row():
    """The ledger, the qualifier promotion and the rollup are all current immediately.

    PRD §3.7: "A confirmed seat's other effects are cross-entity. `room_nights` is
    stamped on the seat, the room-night ledger is re-run on the executed hotel
    contract to refresh `room_nights_confirmed`, `room_nights_available` and
    `attrition_posture`, the budget rollup is re-run so the seat's `cost_cents`
    joins `committed_budget_cents`, and — for a `WINNER` seat only — the owning
    qualifier moves `NOTIFIED → REGISTERED` with its own `version` increment."

    Design: Corner/consistency_model/derived_rollups_and_list_reads_reflect_a_confirmation_with_no_lag
    """
    base = _accepted_seat()
    ana = base["qualifiers"][0]
    seat_id = base["registration"]["id"]

    confirmed = validate_success(api_client.confirm_registration(seat_id, _TD))
    assert confirmed["attendance_status"] == "CONFIRMED"
    assert confirmed["room_nights"] == 5
    assert confirmed["cost_cents"] == 0

    assert read_qualifier(ana["id"])["award_status"] == "REGISTERED"

    contract = read_contract(base["contract"]["id"])
    assert contract["room_nights_blocked"] == 60
    assert contract["room_nights_confirmed"] == 5
    assert contract["room_nights_available"] == 55
    assert contract["attrition_posture"] == "AT_RISK"
    assert_room_nights_conserved(contract)

    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1_443_174
    assert program["budget_headroom_cents"] == 3_556_826
    assert program["budget_posture"] == "OK"
    assert_budget_conserved(program)

    projection = read_exposure_projection(base["contract"]["id"])
    assert projection["attrition_floor_room_nights"] == 48
    assert projection["shortfall_room_nights"] == 43
    assert projection["attrition_basis_cents"] == 1_655_500


def test_filtered_list_reads_and_the_measurement_read_show_the_confirmation_at_once():
    """The first filtered list read after a confirmation already selects the new state.

    PRD §2.3: "Filters are combined with logical AND, and any filter that is
    omitted is not applied."

    Design: Corner/consistency_model/derived_rollups_and_list_reads_reflect_a_confirmation_with_no_lag
    """
    base = _accepted_seat()
    program_id = base["program"]["id"]
    ana = base["qualifiers"][0]
    confirm_registration(base["registration"]["id"])

    confirmed_seats, seat_meta = validate_paginated(
        api_client.list_registrations(
            _TD, {"program_id": program_id, "attendance_status": "CONFIRMED"}
        )
    )
    assert seat_meta["total_count"] == 1
    assert confirmed_seats[0]["id"] == base["registration"]["id"]
    assert confirmed_seats[0]["room_nights"] == 5

    registered, qualifier_meta = validate_paginated(
        api_client.list_qualifiers(_AN, {"program_id": program_id, "award_status": "REGISTERED"})
    )
    assert qualifier_meta["total_count"] == 1
    assert registered[0]["id"] == ana["id"]

    _, notified_meta = validate_paginated(
        api_client.list_qualifiers(_AN, {"program_id": program_id, "award_status": "NOTIFIED"})
    )
    assert notified_meta["total_count"] == 1

    measurement = validate_success(api_client.get_program_measurement(program_id, _PD))
    assert measurement["sales_lift_pct"] is None
    assert measurement["satisfaction_index"] is None
    assert measurement["survey_count"] == 0
    assert measurement["travelled_count"] == 0
    assert measurement["baseline_metric_total"] == 0
    assert measurement["actual_metric_total"] == 0
    assert measurement["committed_budget_cents"] == 1_443_174
    assert measurement["budget_headroom_cents"] == 3_556_826
    assert measurement["budget_posture"] == "OK"

    assert validate_success(api_client.get_program_measurement(program_id, _PD)) == measurement
    _, repeat_meta = validate_paginated(
        api_client.list_registrations(
            _TD, {"program_id": program_id, "attendance_status": "CONFIRMED"}
        )
    )
    assert repeat_meta["total_count"] == 1
