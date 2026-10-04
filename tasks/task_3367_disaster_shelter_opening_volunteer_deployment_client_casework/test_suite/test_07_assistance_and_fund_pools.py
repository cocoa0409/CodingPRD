"""Entitlement, duplication-of-benefits, donor fund pools and the assistance card lifecycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    create_client,
    create_pool,
    open_case,
    register_client,
    resolve_referral,
    setup_funded_casework_scenario,
    setup_open_shelter,
    validate_error,
    validate_paginated,
    validate_success,
    verify_case_eligibility,
)


def _entitlement_scenario():
    """Two households of five registered at one shelter, flagged differently."""
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    flagged = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=5)
    plain = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=5)
    register_client(bundle["shelter_id"], flagged["id"], manager,
                    functional_needs_flag=True)
    register_client(bundle["shelter_id"], plain["id"], manager,
                    functional_needs_flag=False)

    case_flagged = open_case(flagged["id"], bundle["operation_id"])
    case_plain = open_case(plain["id"], bundle["operation_id"])
    bundle.update({"case_flagged": case_flagged, "case_plain": case_plain})
    return bundle


def test_functional_needs_registration_selects_the_expedited_schedule(api):
    """PRD §3.7: "the expedited schedule is used when any shelter registration belonging to the
    case's client carries a `functional_needs_flag` of true, or when the case's own status is
    `REOPENED`."

    PRD §3.7: "The `expedited_schedule` variant returns 20,000 cents plus half of the base
    amount ... with the whole result capped at 150,000 cents."

    Design: Difficulty/dual_variant_calc/case_entitlement_base_vs_expedited
    """
    bundle = _entitlement_scenario()
    caseworker = bundle["caseworker_headers"]

    flagged = validate_success(
        api.get_client_case(bundle["case_flagged"]["id"], caseworker))
    assert flagged["entitlement_cents"] == 80000


def test_plain_registration_selects_the_base_schedule(api):
    """PRD §3.7: "the base amount: the household size multiplied by 30,000 cents per person,
    capped at 120,000 cents — so a household of four or more receives the same base as a
    household of exactly four. The `base_schedule` variant stops there and returns the base
    unchanged."

    Design: Difficulty/dual_variant_calc/case_entitlement_base_vs_expedited
    """
    bundle = _entitlement_scenario()
    caseworker = bundle["caseworker_headers"]

    plain = validate_success(api.get_client_case(bundle["case_plain"]["id"], caseworker))
    assert plain["entitlement_cents"] == 120000


def test_duplication_offset_sums_live_referrals_of_the_same_type(api):
    """PRD §3.7: "the offset is computed as the sum of `estimated_value_cents` over every
    referral of the same case whose `assistance_type` matches the request's and whose status is
    `SUBMITTED`, `ACCEPTED` or `COMPLETED`."

    PRD §3.7: "Second, the award is computed as the requested amount minus the offset, floored at
    zero."

    Design: Difficulty/combinatorial_formula/duplication_offset_pinned_evaluation_order
    """
    bundle = setup_funded_casework_scenario(
        requested_amount_cents=40000, assistance_type="HOUSING", eligibility_status="VERIFIED")
    caseworker = bundle["caseworker_headers"]
    finance = bundle["finance_headers"]

    accepted = api.create_referral(
        bundle["case_id"],
        {"agency_code": "LOCAL_HOUSING", "assistance_type": "HOUSING",
         "estimated_value_cents": 18000},
        caseworker)
    resolve_referral(validate_success(accepted, 201)["id"], "ACCEPT")
    validate_success(api.create_referral(
        bundle["case_id"],
        {"agency_code": "SALVATION_ARMY", "assistance_type": "HOUSING",
         "estimated_value_cents": 7000},
        caseworker), 201)

    validate_success(api.approve_assistance_request(bundle["request_id"], finance))
    approved = validate_success(
        api.approve_assistance_request(bundle["request_id"], finance))

    assert approved["duplication_offset_cents"] == 25000
    assert approved["approved_amount_cents"] == 15000
    assert approved["status"] == "APPROVED"


def test_award_below_the_minimum_is_refused_and_stays_eligibility_verified(api):
    """PRD §3.7: "if the computed award is greater than zero but less than 5,000 cents, the
    approval is refused with `ERR_ASSISTANCE_BELOW_MINIMUM` at HTTP status 409 and the request
    remains in `ELIGIBILITY_VERIFIED`, awaiting either a change in the offset or a different
    request."

    Design: Difficulty/combinatorial_formula/duplication_offset_pinned_evaluation_order
    """
    bundle = setup_funded_casework_scenario(
        requested_amount_cents=26000, assistance_type="HOUSING", eligibility_status="VERIFIED")
    caseworker = bundle["caseworker_headers"]
    finance = bundle["finance_headers"]

    accepted = api.create_referral(
        bundle["case_id"],
        {"agency_code": "LOCAL_HOUSING", "assistance_type": "HOUSING",
         "estimated_value_cents": 18000},
        caseworker)
    resolve_referral(validate_success(accepted, 201)["id"], "ACCEPT")
    validate_success(api.create_referral(
        bundle["case_id"],
        {"agency_code": "SALVATION_ARMY", "assistance_type": "HOUSING",
         "estimated_value_cents": 7000},
        caseworker), 201)

    verified = validate_success(
        api.approve_assistance_request(bundle["request_id"], finance))
    assert verified["duplication_offset_cents"] == 25000
    assert verified["approved_amount_cents"] == 1000

    resp = api.approve_assistance_request(bundle["request_id"], finance)
    validate_error(resp, ApiErrorId.ERR_ASSISTANCE_BELOW_MINIMUM)

    still = validate_success(
        api.get_assistance_request(bundle["request_id"], finance))
    assert still["status"] == "ELIGIBILITY_VERIFIED"


def test_award_equal_to_the_remaining_balance_is_approved(api):
    """PRD §2.8: "An approval whose `approved_amount_cents` exceeds the target pool's
    `remaining_cents` is refused with `ERR_INSUFFICIENT_FUNDS` at HTTP status 409."

    PRD §2.8: "Its `remaining_cents` is `total_received_cents` minus `committed_cents` minus
    `disbursed_cents`, so a promise consumes capacity exactly as a payment does."

    Design: Difficulty/boundary_precision_check/fund_pool_exact_balance_boundary
    """
    bundle = setup_open_shelter()
    client = create_client(bundle["region_id"])
    register_client(bundle["shelter_id"], client["id"], bundle["manager_headers"])
    case = verify_case_eligibility(open_case(client["id"], bundle["operation_id"])["id"])

    pool = create_pool(fund_code="DR-9101-FOOD", restriction_type="UNRESTRICTED",
                       region_id=bundle["region_id"], total_received_cents=50000)
    caseworker = bundle["caseworker_headers"]
    finance = bundle["finance_headers"]

    first = validate_success(api.create_assistance_request(
        case["id"], {"fund_pool_id": pool["id"], "assistance_type": "FOOD",
                     "requested_amount_cents": 40000}, caseworker), 201)
    validate_success(api.approve_assistance_request(first["id"], finance))
    validate_success(api.approve_assistance_request(first["id"], finance))

    balance = validate_success(api.get_fund_pool(pool["id"], finance))
    assert balance["remaining_cents"] == 10000

    second = validate_success(api.create_assistance_request(
        case["id"], {"fund_pool_id": pool["id"], "assistance_type": "FOOD",
                     "requested_amount_cents": 10000}, caseworker), 201)
    validate_success(api.approve_assistance_request(second["id"], finance))
    approved = validate_success(api.approve_assistance_request(second["id"], finance))
    assert approved["status"] == "APPROVED"
    assert approved["approved_amount_cents"] == 10000

    drained = validate_success(api.get_fund_pool(pool["id"], finance))
    assert drained["remaining_cents"] == 0


def test_award_against_a_drained_pool_is_refused(api):
    """PRD §2.8: "An approval whose `approved_amount_cents` exceeds the target pool's
    `remaining_cents` is refused with `ERR_INSUFFICIENT_FUNDS` at HTTP status 409."

    Design: Difficulty/boundary_precision_check/fund_pool_exact_balance_boundary
    """
    bundle = setup_open_shelter()
    client = create_client(bundle["region_id"])
    register_client(bundle["shelter_id"], client["id"], bundle["manager_headers"])
    case = verify_case_eligibility(open_case(client["id"], bundle["operation_id"])["id"])

    pool = create_pool(fund_code="DR-9101-FOOD", restriction_type="UNRESTRICTED",
                       region_id=bundle["region_id"], total_received_cents=50000)
    caseworker = bundle["caseworker_headers"]
    finance = bundle["finance_headers"]

    for amount in (40000, 10000):
        request = validate_success(api.create_assistance_request(
            case["id"], {"fund_pool_id": pool["id"], "assistance_type": "FOOD",
                         "requested_amount_cents": amount}, caseworker), 201)
        validate_success(api.approve_assistance_request(request["id"], finance))
        validate_success(api.approve_assistance_request(request["id"], finance))

    third = validate_success(api.create_assistance_request(
        case["id"], {"fund_pool_id": pool["id"], "assistance_type": "FOOD",
                     "requested_amount_cents": 5000}, caseworker), 201)
    validate_success(api.approve_assistance_request(third["id"], finance))

    resp = api.approve_assistance_request(third["id"], finance)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS)


def test_reversing_a_disbursement_restores_the_pool_balance_exactly(api):
    """PRD §2.8: "Reversing a disbursement must restore the pool balance exactly: the
    compensating ledger entry carries the same `amount_cents` as the original charge and the
    `entry_type` `REVERSAL`, so the pool's `remaining_cents` returns to precisely its pre-award
    value."

    Design: Difficulty/compensating_invariant/fund_pool_remaining_cents_conserved
    """
    bundle = setup_funded_casework_scenario(
        pool_overrides={"restriction_type": "DONOR_RESTRICTED_DISASTER",
                        "total_received_cents": 300000},
        requested_amount_cents=75000, assistance_type="HOUSING", approve_twice=True)
    finance = bundle["finance_headers"]

    before = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    # PRD §2.8: an APPROVED award is committed money, so it already consumes the
    # pool's capacity ("a promise consumes capacity exactly as a payment does").
    assert before["remaining_cents"] == 225000

    # PRD §3.7: the approving officer may not also issue the card.
    issuer = TEST_USERS["second_finance_officer_headers"]
    validate_success(api.issue_card(bundle["request_id"], issuer))
    validate_success(api.redeem_card(bundle["request_id"], finance))

    during = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    assert during["remaining_cents"] == 225000
    assert during["disbursed_cents"] == 75000

    reversed_request = validate_success(
        api.reverse_assistance(bundle["request_id"], finance))
    assert reversed_request["status"] == "REVERSED"

    after = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    assert after["remaining_cents"] == 300000, (
        "the reversal must restore the pre-award value with no drift")
    assert after["committed_cents"] == 0
    assert after["disbursed_cents"] == 0


def test_award_lifecycle_keeps_the_pool_balances_consistent(api):
    """PRD §2.8: "Its `committed_cents` is the sum of `approved_amount_cents` across the
    assistance requests drawn on it that are in `APPROVED` or `CARD_ISSUED` status — money
    promised but not yet handed over."

    PRD §2.8: "Its `disbursed_cents` is the same sum restricted to requests in `DISBURSED`
    status."

    Design: Difficulty/compensating_invariant/fund_pool_remaining_cents_conserved
    """
    bundle = setup_funded_casework_scenario(
        pool_overrides={"restriction_type": "DONOR_RESTRICTED_DISASTER",
                        "total_received_cents": 300000},
        requested_amount_cents=75000, assistance_type="HOUSING", approve_twice=True)
    finance = bundle["finance_headers"]

    approved = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    assert approved["committed_cents"] == 75000
    assert approved["disbursed_cents"] == 0
    assert approved["remaining_cents"] == 225000

    # PRD §3.7: the approving officer may not also issue the card.
    issuer = TEST_USERS["second_finance_officer_headers"]
    validate_success(api.issue_card(bundle["request_id"], issuer))
    issued = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    assert issued["committed_cents"] == 75000

    validate_success(api.redeem_card(bundle["request_id"], finance))
    disbursed = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    assert disbursed["disbursed_cents"] == 75000
    assert disbursed["committed_cents"] == 0


def test_reversal_restores_the_operation_restricted_fund_balance(api):
    """PRD §3.7: "the pool's `disbursed_cents` is recomputed, then the pool's `remaining_cents`
    is recomputed, then the parent operation's `restricted_fund_balance_cents` is recomputed."

    PRD §2.8: "A disaster relief operation's `restricted_fund_balance_cents` is the sum of
    `remaining_cents` over every pool whose `restriction_type` is not `UNRESTRICTED` and which
    appears on at least one cost ledger entry of that operation."

    Design: Difficulty/transitive_cascade/assistance_reversal_restores_restricted_fund_chain
    """
    bundle = setup_funded_casework_scenario(
        pool_overrides={"fund_code": "DR-9101-RESTRICTED",
                        "restriction_type": "DONOR_RESTRICTED_DISASTER",
                        "total_received_cents": 200000},
        requested_amount_cents=50000, assistance_type="HOUSING", approve_twice=True)
    finance = bundle["finance_headers"]
    coord = bundle["coordinator_headers"]

    op = validate_success(api.get_operation(bundle["operation_id"], coord))
    validate_success(api.create_cost_ledger_entry(
        bundle["operation_id"],
        {"expected_disaster_relief_operation_version": op["version"],
         "fund_pool_id": bundle["pool_id"], "cost_category": "LOGISTICS",
         "amount_cents": 1000, "entry_type": "CHARGE",
         "incurred_at": "2026-09-03T10:00:00Z"},
        finance), 201)

    # PRD §3.7: the approving officer may not also issue the card.
    issuer = TEST_USERS["second_finance_officer_headers"]
    validate_success(api.issue_card(bundle["request_id"], issuer))
    validate_success(api.redeem_card(bundle["request_id"], finance))

    pool = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    assert pool["remaining_cents"] == 150000
    assert pool["disbursed_cents"] == 50000

    validate_success(api.reverse_assistance(bundle["request_id"], finance))

    restored_pool = validate_success(api.get_fund_pool(bundle["pool_id"], finance))
    assert restored_pool["remaining_cents"] == 200000
    assert restored_pool["disbursed_cents"] == 0

    operation = validate_success(api.get_operation(bundle["operation_id"], finance))
    assert operation["restricted_fund_balance_cents"] == 200000


def test_reversal_appends_a_mirroring_compensating_ledger_entry(api):
    """PRD §3.7: "a compensating cost ledger entry with `entry_type` of `REVERSAL` and an
    `amount_cents` equal to the original award is appended."

    PRD §3.7: "appends a cost ledger entry with `cost_category` of `FINANCIAL_ASSISTANCE`,
    `entry_type` of `CHARGE` and an `amount_cents` equal to the award."

    Design: Difficulty/transitive_cascade/assistance_reversal_restores_restricted_fund_chain
    """
    bundle = setup_funded_casework_scenario(
        pool_overrides={"fund_code": "DR-9101-RESTRICTED",
                        "restriction_type": "DONOR_RESTRICTED_DISASTER",
                        "total_received_cents": 200000},
        requested_amount_cents=50000, assistance_type="HOUSING", approve_twice=True)
    finance = bundle["finance_headers"]
    # PRD §3.7: the approving officer may not also issue the card.
    issuer = TEST_USERS["second_finance_officer_headers"]

    validate_success(api.issue_card(bundle["request_id"], issuer))
    validate_success(api.redeem_card(bundle["request_id"], finance))
    validate_success(api.reverse_assistance(bundle["request_id"], finance))

    entries, _meta = validate_paginated(
        api.list_cost_ledger_entries(finance, params={"fund_pool_id": bundle["pool_id"]}))
    reversals = [e for e in entries if e["entry_type"] == "REVERSAL"]
    charges = [e for e in entries if e["entry_type"] == "CHARGE"]

    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == 50000
    assert any(c["cost_category"] == "FINANCIAL_ASSISTANCE" for c in charges)


def test_pool_restriction_incompatible_with_the_assistance_type(api):
    """PRD §2.8: "An approval whose pool `restriction_type` is incompatible with the request's
    `assistance_type`, or with the client's region, is refused with
    `ERR_POOL_RESTRICTION_MISMATCH` at HTTP status 409."

    Design: Corner/validations/assistance_pool_restriction_type_mismatch
    """
    bundle = setup_open_shelter()
    client = create_client(bundle["region_id"])
    register_client(bundle["shelter_id"], client["id"], bundle["manager_headers"])
    case = verify_case_eligibility(open_case(client["id"], bundle["operation_id"])["id"])

    blood_pool = create_pool(fund_code="DR-9101-BLOOD",
                             restriction_type="DONOR_RESTRICTED_BLOOD",
                             region_id=bundle["region_id"], total_received_cents=100000)
    general_pool = create_pool(fund_code="DR-9101-GEN", restriction_type="UNRESTRICTED",
                               region_id=bundle["region_id"], total_received_cents=100000)
    caseworker = bundle["caseworker_headers"]
    finance = bundle["finance_headers"]

    blood_request = validate_success(api.create_assistance_request(
        case["id"], {"fund_pool_id": blood_pool["id"], "assistance_type": "HOUSING",
                     "requested_amount_cents": 20000}, caseworker), 201)
    validate_success(api.approve_assistance_request(blood_request["id"], finance))
    validate_error(api.approve_assistance_request(blood_request["id"], finance),
                   ApiErrorId.ERR_POOL_RESTRICTION_MISMATCH)

    general_request = validate_success(api.create_assistance_request(
        case["id"], {"fund_pool_id": general_pool["id"], "assistance_type": "HOUSING",
                     "requested_amount_cents": 20000}, caseworker), 201)
    validate_success(api.approve_assistance_request(general_request["id"], finance))
    approved = validate_success(
        api.approve_assistance_request(general_request["id"], finance))
    assert approved["status"] == "APPROVED"


def test_local_pool_cannot_fund_a_client_from_another_region(api):
    """PRD §2.8: "An approval whose pool `restriction_type` is incompatible with the request's
    `assistance_type`, or with the client's region, is refused with
    `ERR_POOL_RESTRICTION_MISMATCH` at HTTP status 409."

    Design: Corner/validations/local_restricted_pool_cross_region_rejected
    """
    bundle = setup_open_shelter()
    from test_helpers import create_region
    other = create_region(code="NW", name="Northwest", state_codes=["WA", "OR"],
                          coordinator_user_id="rc_nw", volunteer_pool_target=25,
                          authorized_agency_codes=["FEMA"])

    local_client = create_client(bundle["region_id"], full_name="Ana Lopez")
    remote_client = create_client(other["id"], full_name="Nora Pike")
    register_client(bundle["shelter_id"], local_client["id"], bundle["manager_headers"])
    register_client(bundle["shelter_id"], remote_client["id"], bundle["manager_headers"])

    local_case = verify_case_eligibility(
        open_case(local_client["id"], bundle["operation_id"])["id"])
    remote_case = verify_case_eligibility(
        open_case(remote_client["id"], bundle["operation_id"])["id"])

    pool = create_pool(fund_code="NW-LOCAL", restriction_type="DONOR_RESTRICTED_LOCAL",
                       region_id=other["id"], total_received_cents=90000)
    caseworker = bundle["caseworker_headers"]
    finance = bundle["finance_headers"]

    local_request = validate_success(api.create_assistance_request(
        local_case["id"], {"fund_pool_id": pool["id"], "assistance_type": "UTILITY",
                           "requested_amount_cents": 15000}, caseworker), 201)
    validate_success(api.approve_assistance_request(local_request["id"], finance))
    validate_error(api.approve_assistance_request(local_request["id"], finance),
                   ApiErrorId.ERR_POOL_RESTRICTION_MISMATCH)

    remote_request = validate_success(api.create_assistance_request(
        remote_case["id"], {"fund_pool_id": pool["id"], "assistance_type": "UTILITY",
                            "requested_amount_cents": 15000}, caseworker), 201)
    validate_success(api.approve_assistance_request(remote_request["id"], finance))
    approved = validate_success(
        api.approve_assistance_request(remote_request["id"], finance))
    assert approved["status"] == "APPROVED"


def test_issuing_a_card_twice_is_refused(api):
    """PRD §3.7: "issuing one whose `card_status` is anything other than `NOT_ISSUED` is refused
    with `ERR_CARD_ALREADY_ISSUED` at HTTP status 409 — the check is on the card, not the request
    status, so a request cannot be issued twice."

    Design: Corner/errors/card_issue_twice_returns_already_issued
    """
    bundle = setup_funded_casework_scenario(
        requested_amount_cents=30000, approve_twice=True)
    finance = bundle["finance_headers"]
    issuer = TEST_USERS["second_finance_officer_headers"]

    first = validate_success(api.issue_card(bundle["request_id"], issuer))
    assert first["card_status"] == "ISSUED"
    masked = first["card_number_masked"]

    resp = api.issue_card(bundle["request_id"], issuer)
    validate_error(resp, ApiErrorId.ERR_CARD_ALREADY_ISSUED)

    still = validate_success(api.get_assistance_request(bundle["request_id"], finance))
    assert still["card_number_masked"] == masked


def test_the_approving_officer_may_not_issue_the_card(api):
    """PRD §3.7: "The acting `X-User-ID` must differ from the request's `approved_by_user_id`;
    the same operator attempting both halves is refused with `ERR_SOD_VIOLATION` at HTTP
    status 403."

    Design: Corner/errors/card_issue_segregation_of_duties
    """
    bundle = setup_funded_casework_scenario(
        requested_amount_cents=30000, approve_twice=True)
    finance = bundle["finance_headers"]
    second_finance = TEST_USERS["second_finance_officer_headers"]

    request = validate_success(
        api.get_assistance_request(bundle["request_id"], finance))
    assert request["approved_by_user_id"] == "fo_1"

    validate_error(api.issue_card(bundle["request_id"], finance),
                   ApiErrorId.ERR_SOD_VIOLATION)

    issued = validate_success(api.issue_card(bundle["request_id"], second_finance))
    assert issued["card_status"] == "ISSUED"
    assert issued["issued_by_user_id"] == "fo_2"


def test_restricted_shelter_shortens_the_redemption_window(api):
    """PRD §3.7: "If any shelter registration belonging to the case's client sits in a shelter
    operation whose posture is `RESTRICTED` at issuance time, the window is 45 days; otherwise
    it is 90 days."

    Design: Corner/calculations/redemption_window_shortens_under_restricted_posture
    """
    bundle = setup_funded_casework_scenario(
        requested_amount_cents=30000, approve_twice=True)
    coord = bundle["coordinator_headers"]
    finance = bundle["finance_headers"]

    validate_success(api.recall_deployment(bundle["deployment_id"], coord))
    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], coord))
    assert shelter["posture"] == "RESTRICTED"

    # PRD §3.7: the approving officer may not also issue the card.
    issuer = TEST_USERS["second_finance_officer_headers"]
    issued = validate_success(api.issue_card(bundle["request_id"], issuer))
    assert issued["card_status"] == "ISSUED"
    assert_instant_equals(issued["redemption_deadline_at"], "2026-10-18T00:00:00Z")
