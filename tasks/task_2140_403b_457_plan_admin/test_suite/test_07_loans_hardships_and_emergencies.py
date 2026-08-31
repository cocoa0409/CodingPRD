"""Loans, 403(b) hardships and 457(b) unforeseeable emergencies."""

from test_helpers import (
    ApiErrorId,
    approve_request,
    begin_review,
    create_active_plan,
    decide_request,
    fulfill_request,
    make_officer_headers,
    make_participant_headers,
    make_sponsor_headers,
    make_vendor_headers,
    move_plan,
    open_contract,
    register_employer,
    register_participant,
    register_vendor,
    report_balance,
    set_clock,
    setup_active_agreement,
    setup_plan_env,
    setup_request_under_review,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
)

RELIEF = {
    "insurance_reimbursement_available_cents": 500_000,
    "liquidatable_assets_cents": 300_000,
    "deferral_cessation_relief_cents": 200_000,
}


def _two_standard_env():
    """One sponsor running both a 403(b) and a 457(b) plan, one provider holding a
    current agreement with each, and one participant with a fully vested 5,000,000-cent
    contract under each plan."""
    set_clock()
    employer = register_employer()
    vendor = register_vendor()
    plan_403b = create_active_plan(employer["id"], plan_name="Riverbend 403(b)")
    plan_457b = create_active_plan(
        employer["id"], plan_name="Riverbend 457(b)", plan_type="PLAN_457B"
    )
    setup_active_agreement(plan_403b["id"], vendor["id"], employer["id"])
    setup_active_agreement(plan_457b["id"], vendor["id"], employer["id"])
    participant = register_participant(employer["id"])
    account_403b = open_contract(
        participant["id"], plan_403b["id"], vendor["id"], employer["id"],
        contract_number="NLA-0403", accumulated_benefit_cents=5_000_000,
    )
    account_457b = open_contract(
        participant["id"], plan_457b["id"], vendor["id"], employer["id"],
        contract_number="NLA-0457", accumulated_benefit_cents=5_000_000,
    )
    return {
        "employer_id": employer["id"], "vendor_id": vendor["id"],
        "plan_403b_id": plan_403b["id"], "plan_457b_id": plan_457b["id"],
        "participant_id": participant["id"],
        "account_403b_id": account_403b["id"], "account_457b_id": account_457b["id"],
    }


def test_hardship_ceiling_grosses_up_for_taxes_without_netting_relief(api):
    """PRD §3.8: "For a `HARDSHIP`, the 403(b) safe-harbour rule allows the need to be
    grossed up for the taxes and penalties reasonably anticipated on the distribution,
    and it does *not* net off other resources: the participant's written representation
    governs and there is no obligation to take a plan loan first. The base is therefore
    `stated_need_cents` plus `estimated_taxes_cents`, and available relief is ignored
    entirely."
    PRD §3.8: "Approval then writes `max_approvable_cents` from the applicable ceiling,
    sets `approved_amount_cents` equal to `requested_amount_cents`, and records
    `decided_by_user_id`."

    Design: Difficulty/dual_variant_calc/distribution_max_hardship_grossup_versus_unforeseeable_emergency_net
    """
    env = _two_standard_env()
    request = submit_request(
        env["participant_id"], env["plan_403b_id"], env["account_403b_id"], "HARDSHIP",
        requested_amount_cents=2_600_000, stated_need_cents=2_000_000,
        estimated_taxes_cents=600_000, safe_harbor_reason="MEDICAL_EXPENSES", **RELIEF,
    )
    begin_review(request["id"], "co-1")

    approved = validate_success(
        api.decide_participant_request(
            request["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
        )
    )

    assert approved["state"] == "APPROVED"
    assert approved["max_approvable_cents"] == 2_600_000, (
        "the hardship base ignores the 1000000 cents of available relief"
    )
    assert approved["approved_amount_cents"] == 2_600_000
    assert approved["decided_by_user_id"] == "co-2"


def test_unforeseeable_emergency_ceiling_nets_off_available_relief(api):
    """PRD §3.8: "Otherwise the base is `stated_need_cents` reduced by the relief total,
    floored at zero, and then increased by `estimated_taxes_cents`."
    PRD §3.8: "Under either standard the ceiling is the lesser of that base and the
    vested balance of the single named contract; no other contract of the participant
    participates. A `requested_amount_cents` above that ceiling is refused with
    `ERR_DISTRIBUTION_EXCEEDS_NEED`."
    PRD §3.8: "For identical `stated_need_cents`, `estimated_taxes_cents` and relief
    inputs, the emergency standard therefore yields a ceiling smaller than the hardship
    standard by exactly the relief total."

    Design: Difficulty/dual_variant_calc/distribution_max_hardship_grossup_versus_unforeseeable_emergency_net
    """
    env = _two_standard_env()
    request = submit_request(
        env["participant_id"], env["plan_457b_id"], env["account_457b_id"],
        "UNFORESEEABLE_EMERGENCY", requested_amount_cents=2_600_000,
        stated_need_cents=2_000_000, estimated_taxes_cents=600_000,
        emergency_reason="EXTRAORDINARY_MEDICAL", **RELIEF,
    )
    begin_review(request["id"], "co-1")

    response = api.decide_participant_request(
        request["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
    )

    validate_error(response, ApiErrorId.ERR_DISTRIBUTION_EXCEEDS_NEED.value)
    unchanged = validate_success(
        api.get_participant_request(request["id"], make_officer_headers())
    )
    assert unchanged["state"] == "UNDER_REVIEW"
    assert unchanged["approved_amount_cents"] is None


def _emergency_under_review_env():
    """A governmental 457(b) emergency request for 2,600,000 cents already UNDER_REVIEW
    with 1,000,000 cents of asserted relief."""
    return setup_request_under_review(
        "UNFORESEEABLE_EMERGENCY", plan_type="PLAN_457B",
        request_overrides={
            "requested_amount_cents": 2_600_000, "stated_need_cents": 2_000_000,
            "estimated_taxes_cents": 600_000, "emergency_reason": "EXTRAORDINARY_MEDICAL",
            **RELIEF,
        },
    )


def test_returned_for_info_resubmission_clears_the_reviewer(api):
    """PRD §3.8: "Resubmission increases `resubmission_count` by one, resets
    `reviewed_by_user_id` to null so that review must be opened afresh, and records
    `submitted_by_user_id` from the acting `X-User-ID`."
    PRD §3.8: "`RETURN_FOR_INFO` moves it `UNDER_REVIEW → RETURNED_FOR_INFO`."
    PRD §3.8: "`BEGIN_REVIEW` moves the request `SUBMITTED → UNDER_REVIEW` and records
    `reviewed_by_user_id` from the acting `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/participant_request_returned_for_info_revision_cycle
    """
    env = _emergency_under_review_env()

    returned = decide_request(
        env["request_id"], "RETURN_FOR_INFO", "co-1",
        note="substantiate that insurance and liquidation relief are genuinely unavailable",
    )
    assert returned["state"] == "RETURNED_FOR_INFO"

    resubmitted = validate_success(
        api.resubmit_participant_request(
            env["request_id"],
            {
                "insurance_reimbursement_available_cents": 0,
                "liquidatable_assets_cents": 0,
                "deferral_cessation_relief_cents": 0,
            },
            make_participant_headers(env["participant_id"]),
        )
    )

    assert resubmitted["state"] == "SUBMITTED", "a state the row already occupied at creation"
    assert resubmitted["resubmission_count"] == 1
    assert resubmitted["reviewed_by_user_id"] is None

    reopened = begin_review(env["request_id"], "co-1")
    assert reopened["state"] == "UNDER_REVIEW"
    assert reopened["reviewed_by_user_id"] == "co-1"


def test_revised_relief_figures_raise_the_ceiling_on_the_second_pass(api):
    """PRD §3.8: "the resubmission may revise `requested_amount_cents`,
    `stated_need_cents`, `estimated_taxes_cents`,
    `insurance_reimbursement_available_cents`, `liquidatable_assets_cents` and
    `deferral_cessation_relief_cents`, and any field supplied overwrites the stored value
    while omitted fields are left alone."
    PRD §3.8: "Otherwise the base is `stated_need_cents` reduced by the relief total,
    floored at zero, and then increased by `estimated_taxes_cents`."
    PRD §3.8: "Approval then writes `max_approvable_cents` from the applicable ceiling,
    sets `approved_amount_cents` equal to `requested_amount_cents`, and records
    `decided_by_user_id`."

    Design: Difficulty/non_linear_state_machine/participant_request_returned_for_info_revision_cycle
    """
    env = _emergency_under_review_env()
    decide_request(env["request_id"], "RETURN_FOR_INFO", "co-1")
    validate_success(
        api.resubmit_participant_request(
            env["request_id"],
            {
                "insurance_reimbursement_available_cents": 0,
                "liquidatable_assets_cents": 0,
                "deferral_cessation_relief_cents": 0,
            },
            make_participant_headers(env["participant_id"]),
        )
    )
    begin_review(env["request_id"], "co-1")

    approved = validate_success(
        api.decide_participant_request(
            env["request_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
        )
    )

    assert approved["state"] == "APPROVED"
    assert approved["max_approvable_cents"] == 2_600_000
    assert approved["approved_amount_cents"] == 2_600_000
    assert approved["decided_by_user_id"] == "co-2"


def _loan_ready_env(request_amount=3_300_000):
    """Two providers with current, loan-sharing agreements; contract A fully vested at
    5,000,000 cents and contract B at 3,000,000 cents / 80% carrying an existing loan."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    setup_active_agreement(env["plan_id"], env["vendor_ids"][0], env["employer_id"])
    setup_active_agreement(env["plan_id"], env["vendor_ids"][1], env["employer_id"])
    participant = register_participant(env["employer_id"])
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=3_000_000,
        vested_percentage_bps=8000,
    )
    report_balance(
        account_two["id"], env["vendor_ids"][1], as_of_date="2026-07-31",
        accumulated_benefit_cents=3_000_000, outstanding_loan_balance_cents=400_000,
        highest_outstanding_loan_12mo_cents=900_000,
    )
    request = submit_request(
        participant["id"], env["plan_id"], account_one["id"], "LOAN",
        requested_amount_cents=request_amount, loan_term_months=60,
    )
    begin_review(request["id"], "co-1")
    approve_request(request["id"], "co-2")
    env.update(
        participant_id=participant["id"], account_one_id=account_one["id"],
        account_two_id=account_two["id"], request_id=request["id"],
    )
    return env


def test_loan_disbursement_moves_contract_and_participant_loan_figures(api):
    """PRD §3.8: "A `LOAN` moves `APPROVED → DISBURSED`. The named contract's
    `outstanding_loan_balance_cents` increases by `approved_amount_cents`, and its
    `highest_outstanding_loan_12mo_cents` becomes the greater of its previous value and
    the new outstanding balance. Those contract-level changes force the participant's
    `total_outstanding_loan_balance_cents` and `highest_outstanding_loan_12mo_cents` to be
    recomputed, and the recomputed aggregates in turn drive the loan maximum toward zero;
    once the maximum reaches zero while the outstanding balance is positive,
    `loan_eligibility_flag` moves `AVAILABLE → SUSPENDED` and every subsequent loan
    request from that participant is blocked at filing."

    Design: Difficulty/transitive_cascade/loan_disbursement_capacity_suspension_chain
    """
    env = _loan_ready_env()

    disbursed = fulfill_request(env["request_id"], env["employer_id"], "2026-08-01")

    assert disbursed["state"] == "DISBURSED"
    assert disbursed["max_approvable_cents"] == 3_300_000
    assert disbursed["approved_amount_cents"] == 3_300_000
    account = validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )
    assert account["outstanding_loan_balance_cents"] == 3_300_000
    assert account["highest_outstanding_loan_12mo_cents"] == 3_300_000
    assert account["accumulated_benefit_cents"] == 5_000_000, (
        "a loan does not reduce the accumulated benefit"
    )
    participant = validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )
    assert participant["total_outstanding_loan_balance_cents"] == 3_700_000
    assert participant["highest_outstanding_loan_12mo_cents"] == 4_200_000


def test_exhausted_loan_capacity_suspends_further_loan_requests(api):
    """PRD §3.8: "The statutory ceiling, `cap_statutory_cents`, is an absolute cap of
    50,000 dollars reduced by `highest_outstanding_12mo_cents`. The vested ceiling,
    `cap_vested_cents`, starts as the greater of half the vested total and a floor of
    10,000 dollars — the half is taken as fifty percent of `vested_total_cents` with the
    result floored to a whole cent — and from that greater figure `outstanding_total_cents`
    is subtracted; the result is then capped so that it never exceeds `vested_total_cents`
    less `outstanding_total_cents`, because a loan can never reach beyond the vested money
    actually remaining. `maximum_loan_cents` is the smaller of the two ceilings, floored
    at zero."
    PRD §3.8: "Loan filings are additionally screened against the participant's
    `loan_eligibility_flag`, which must read `AVAILABLE` and otherwise yields
    `ERR_LOAN_ELIGIBILITY_SUSPENDED`, and against the loan ceiling below."

    Design: Difficulty/transitive_cascade/loan_disbursement_capacity_suspension_chain
    """
    env = _loan_ready_env()
    fulfill_request(env["request_id"], env["employer_id"], "2026-08-01")

    capacity = validate_success(
        api.get_loan_capacity(
            env["participant_id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert capacity["vested_total_cents"] == 7_400_000
    assert capacity["cap_statutory_cents"] == 800_000
    assert capacity["cap_vested_cents"] == 0
    assert capacity["maximum_loan_cents"] == 0
    assert capacity["loan_eligibility_flag"] == "SUSPENDED"
    assert validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )["loan_eligibility_flag"] == "SUSPENDED"

    blocked = api.create_participant_request(
        {
            "participant_id": env["participant_id"], "plan_id": env["plan_id"],
            "vendor_account_id": env["account_one_id"], "request_type": "LOAN",
            "requested_amount_cents": 100_000, "loan_term_months": 24,
        },
        make_participant_headers(env["participant_id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_LOAN_ELIGIBILITY_SUSPENDED.value)


def _stale_perimeter_env():
    """Provider one's feed is current; provider two's feed is 92 days old. The loan is
    drawn from provider one's contract."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    setup_active_agreement(env["plan_id"], env["vendor_ids"][0], env["employer_id"], "2026-07-31")
    env["stale_agreement"] = setup_active_agreement(
        env["plan_id"], env["vendor_ids"][1], env["employer_id"], "2026-05-01"
    )
    participant = register_participant(env["employer_id"])
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=3_000_000,
        vested_percentage_bps=8000,
    )
    request = submit_request(
        participant["id"], env["plan_id"], account_one["id"], "LOAN",
        requested_amount_cents=1_000_000, loan_term_months=60,
    )
    begin_review(request["id"], "co-1")
    env.update(
        participant_id=participant["id"], account_one_id=account_one["id"],
        account_two_id=account_two["id"], request_id=request["id"],
    )
    return env


def test_loan_approval_blocked_by_a_stale_agreement_on_another_contract(api):
    """PRD §3.8: "For a `LOAN`, every open contract of the participant in the plan's
    aggregation set must be covered by an agreement that is `ACTIVE`, has
    `shares_loan_data` true and is not stale."
    PRD §3.8: "An agreement that is missing, `PENDING`, `SUSPENDED` or `TERMINATED`, or
    that does not share the needed data class, yields `ERR_ISA_NOT_ACTIVE`; an agreement
    that clears that test but whose `data_stale` is true yields `ERR_ISA_DATA_STALE`."

    Design: Difficulty/cross_entity_state_dependency/loan_approval_gated_by_every_contract_information_sharing_agreement
    """
    env = _stale_perimeter_env()
    assert validate_success(
        api.get_agreement(env["stale_agreement"]["id"], make_officer_headers())
    )["data_stale"] is True

    response = api.decide_participant_request(
        env["request_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
    )

    validate_error(response, ApiErrorId.ERR_ISA_DATA_STALE.value)
    unchanged = validate_success(
        api.get_participant_request(env["request_id"], make_officer_headers())
    )
    assert unchanged["state"] == "UNDER_REVIEW"
    assert unchanged["approved_amount_cents"] is None


def test_loan_approval_succeeds_once_every_agreement_is_current(api):
    """PRD §3.2: "The server stores it, recomputes `data_stale` against the 45-day window
    of §2.9, and — when the agreement was `SUSPENDED` — returns it to `ACTIVE` in the same
    operation, incrementing `version` by one."
    PRD §3.8: "Approval then writes `max_approvable_cents` from the applicable ceiling,
    sets `approved_amount_cents` equal to `requested_amount_cents`, and records
    `decided_by_user_id`."
    PRD §3.8: "The aggregation set for a loan is narrower than the set used for deferral
    limits: it is every contract of the participant whose `status` is `OPEN` held under a
    plan with **both** the same `employer_id` **and** the same `plan_type` as the plan the
    loan is requested from."

    Design: Difficulty/cross_entity_state_dependency/loan_approval_gated_by_every_contract_information_sharing_agreement
    """
    env = _stale_perimeter_env()
    validate_error(
        api.decide_participant_request(
            env["request_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
        ),
        ApiErrorId.ERR_ISA_DATA_STALE.value,
    )

    refreshed = validate_success(
        api.post_data_feed(
            env["stale_agreement"]["id"], {"data_current_through_date": "2026-07-31"},
            make_vendor_headers(env["vendor_ids"][1]),
        )
    )
    assert refreshed["data_stale"] is False

    approved = validate_success(
        api.decide_participant_request(
            env["request_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
        )
    )
    assert approved["state"] == "APPROVED"
    assert approved["max_approvable_cents"] == 3_700_000
    assert approved["approved_amount_cents"] == 1_000_000


def _zero_balance_env():
    """One contract carrying nothing at all, under a current, loan-sharing agreement."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    setup_active_agreement(env["plan_id"], env["vendor_id"], env["employer_id"])
    participant = register_participant(
        env["employer_id"], full_name="Zero Balance", date_of_birth="1985-04-04",
        hire_date="2024-01-01", includible_compensation_cents=4_000_000, years_of_service=2,
    )
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-Z001", accumulated_benefit_cents=0,
    )
    env.update(participant_id=participant["id"], account_id=account["id"])
    return env


def test_loan_capacity_collapses_to_zero_with_no_vested_balance(api):
    """PRD §3.8: "Observe the consequence for an empty aggregation set: every sum is zero,
    the vested ceiling collapses to the smaller of ten thousand dollars less nothing and
    nothing less nothing — that is, zero — and the maximum is zero."
    PRD §3.8: "`loan_eligibility_flag` is derived and moves between `AVAILABLE` and
    `SUSPENDED`. It reads `SUSPENDED` exactly when the participant's
    `total_outstanding_loan_balance_cents` is greater than zero *and* the computed loan
    maximum evaluates to zero in every plan-type bucket the participant holds an open
    contract in; otherwise it reads `AVAILABLE`."

    Design: Difficulty/boundary_precision_check/zero_vested_balance_empty_loan_aggregation_set
    """
    env = _zero_balance_env()

    capacity = validate_success(
        api.get_loan_capacity(
            env["participant_id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )

    assert capacity["vested_total_cents"] == 0
    assert capacity["outstanding_total_cents"] == 0
    assert capacity["highest_outstanding_12mo_cents"] == 0
    assert capacity["cap_statutory_cents"] == 5_000_000
    assert capacity["cap_vested_cents"] == 0
    assert capacity["maximum_loan_cents"] == 0
    assert capacity["loan_eligibility_flag"] == "AVAILABLE", (
        "a participant who has never borrowed is never SUSPENDED"
    )
    assert validate_success(
        api.get_vendor_account(env["account_id"], make_officer_headers())
    )["vested_balance_cents"] == 0


def test_loan_request_without_vested_balance_is_refused(api):
    """PRD §3.8: "A participant who has never borrowed is therefore never `SUSPENDED`,
    however small their vested balance — that case surfaces instead as
    `ERR_NO_VESTED_BALANCE`, which is raised whenever a loan is requested against an
    aggregation set whose vested total is not greater than zero, both at filing and again
    at approval."
    PRD §2.6: "Note the consequence at rungs 39 through 41 versus rung 15: a participant
    who has never borrowed and holds no vested balance is caught by
    `ERR_NO_VESTED_BALANCE`, not by `ERR_LOAN_ELIGIBILITY_SUSPENDED`, because loan
    eligibility is only ever suspended for a participant whose outstanding borrowing is
    positive."

    Design: Difficulty/boundary_precision_check/zero_vested_balance_empty_loan_aggregation_set
    """
    env = _zero_balance_env()

    response = api.create_participant_request(
        {
            "participant_id": env["participant_id"], "plan_id": env["plan_id"],
            "vendor_account_id": env["account_id"], "request_type": "LOAN",
            "requested_amount_cents": 100_000, "loan_term_months": 24,
        },
        make_participant_headers(env["participant_id"]),
    )

    validate_error(response, ApiErrorId.ERR_NO_VESTED_BALANCE.value)
    rows, _meta = validate_paginated(
        api.list_participant_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert rows == []


def _frozen_loan_env():
    """A FROZEN 403(b) plan whose single participant holds one fully vested contract of
    100,000 cents, so the loan maximum is 100,000 cents."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    setup_active_agreement(env["plan_id"], env["vendor_id"], env["employer_id"])
    participant = register_participant(env["employer_id"])
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=100_000,
    )
    move_plan(env["plan_id"], env["employer_id"], "FROZEN")
    env.update(participant_id=participant["id"], account_id=account["id"])
    return env


def test_plan_frozen_beats_the_loan_ceiling(api):
    """PRD §3.1: "While a plan is `FROZEN`, no contribution election may be created
    against it and no submitted election of that plan may be approved or rejected, no
    remittance batch may be created against it, and no participant request whose
    `request_type` is `LOAN` may be created against it — each of those attempts is refused
    with `ERR_PLAN_FROZEN`."
    PRD §2.6: "The ladder is evaluated strictly in ascending order and the first rung that
    fails decides the response."
    PRD §2.6 rung 11: "The governing plan is not `FROZEN` for the operations a freeze
    suspends — otherwise `ERR_PLAN_FROZEN` (HTTP 409). This rung guards election
    submission, election decision, remittance batch creation, and the creation of a
    participant request whose `request_type` is `LOAN`."

    Design: Difficulty/priority_pair_validation_conflict/plan_frozen_state_beats_loan_limit_fiscal
    """
    env = _frozen_loan_env()

    response = api.create_participant_request(
        {
            "participant_id": env["participant_id"], "plan_id": env["plan_id"],
            "vendor_account_id": env["account_id"], "request_type": "LOAN",
            "requested_amount_cents": 500_000, "loan_term_months": 60,
        },
        make_participant_headers(env["participant_id"]),
    )

    validate_error(response, ApiErrorId.ERR_PLAN_FROZEN.value)
    rows, _meta = validate_paginated(
        api.list_participant_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert rows == [], "the refused filing created nothing"


def test_loan_ceiling_surfaces_once_the_plan_is_active_again(api):
    """PRD §3.8: "A loan whose `requested_amount_cents` exceeds the computed maximum is
    refused with `ERR_LOAN_LIMIT_EXCEEDED`, again both at filing and at approval."
    PRD §3.1: "an unfreeze moves it `FROZEN → ACTIVE` and requires the plan to be
    `FROZEN`"
    PRD §3.8: "`maximum_loan_cents` is the smaller of the two ceilings, floored at zero."

    Design: Difficulty/priority_pair_validation_conflict/plan_frozen_state_beats_loan_limit_fiscal
    """
    env = _frozen_loan_env()
    validate_error(
        api.create_participant_request(
            {
                "participant_id": env["participant_id"], "plan_id": env["plan_id"],
                "vendor_account_id": env["account_id"], "request_type": "LOAN",
                "requested_amount_cents": 500_000, "loan_term_months": 60,
            },
            make_participant_headers(env["participant_id"]),
        ),
        ApiErrorId.ERR_PLAN_FROZEN.value,
    )

    move_plan(env["plan_id"], env["employer_id"], "ACTIVE")
    response = api.create_participant_request(
        {
            "participant_id": env["participant_id"], "plan_id": env["plan_id"],
            "vendor_account_id": env["account_id"], "request_type": "LOAN",
            "requested_amount_cents": 500_000, "loan_term_months": 60,
        },
        make_participant_headers(env["participant_id"]),
    )

    validate_error(response, ApiErrorId.ERR_LOAN_LIMIT_EXCEEDED.value)
    capacity = validate_success(
        api.get_loan_capacity(
            env["participant_id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert capacity["maximum_loan_cents"] == 100_000
    rows, _meta = validate_paginated(
        api.list_participant_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert rows == []


def test_hardship_fulfilment_pays_and_reduces_the_accumulated_benefit(api):
    """PRD §3.8: "A `HARDSHIP` or an `UNFORESEEABLE_EMERGENCY` moves `APPROVED → PAID`
    instead, and takes an entirely different set of effects. The named contract's
    `accumulated_benefit_cents` is reduced by `approved_amount_cents` and its
    `vested_balance_cents` is recomputed from the new benefit; the participant's
    `total_accumulated_benefit_cents` and `total_vested_balance_cents` are recomputed. The
    contract's `outstanding_loan_balance_cents` is deliberately *not* touched — a
    distribution is not a loan, and nothing about paying one changes what the participant
    owes."
    PRD §3.8: "A sponsor admin fulfils an approved request by supplying a
    `fulfillment_date`, which must not be after the current logical clock date and is
    stored on the request."

    Design: Corner/state_machines/hardship_fulfillment_branch_lands_on_paid_and_reduces_accumulated_benefit
    """
    env = setup_request_under_review(
        "HARDSHIP",
        request_overrides={
            "requested_amount_cents": 100_000, "stated_need_cents": 100_000,
            "safe_harbor_reason": "MEDICAL_EXPENSES",
        },
    )
    approve_request(env["request_id"], "co-2")

    fulfilled = fulfill_request(env["request_id"], env["employer_id"], "2026-08-01")

    assert fulfilled["state"] == "PAID", "a hardship never lands on DISBURSED"
    assert fulfilled["max_approvable_cents"] == 100_000
    assert fulfilled["approved_amount_cents"] == 100_000
    account = validate_success(
        api.get_vendor_account(env["account_id"], make_officer_headers())
    )
    assert account["accumulated_benefit_cents"] == 4_900_000
    assert account["vested_balance_cents"] == 4_900_000
    assert account["outstanding_loan_balance_cents"] == 0
    participant = validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )
    assert participant["total_accumulated_benefit_cents"] == 4_900_000
    assert participant["total_vested_balance_cents"] == 4_900_000
    assert participant["loan_eligibility_flag"] == "AVAILABLE"


def test_approving_a_request_before_review_is_rejected(api):
    """PRD §3.8: "`APPROVE` and `DENY` both move the request out of `UNDER_REVIEW` and
    both require that the deciding officer's `X-User-ID` differs from the stored
    `reviewed_by_user_id`; the same officer may not both open review and decide."
    PRD §2.6 rung 9: "The addressed row's current state is a declared origin state for
    the requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/participant_request_approve_without_begin_review_is_rejected
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    setup_active_agreement(env["plan_id"], env["vendor_id"], env["employer_id"])
    participant = register_participant(env["employer_id"])
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        accumulated_benefit_cents=5_000_000,
    )
    request = submit_request(
        participant["id"], env["plan_id"], account["id"], "HARDSHIP",
        requested_amount_cents=100_000, stated_need_cents=100_000,
        safe_harbor_reason="MEDICAL_EXPENSES",
    )

    response = api.decide_participant_request(
        request["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    unchanged = validate_success(
        api.get_participant_request(request["id"], make_officer_headers())
    )
    assert unchanged["state"] == "SUBMITTED"
    assert unchanged["approved_amount_cents"] is None
    assert unchanged["reviewed_by_user_id"] is None


def test_reviewing_officer_cannot_also_decide_the_request(api):
    """PRD §2.6 rung 7: "Segregation of duties — otherwise `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403). This rung guards exactly two operations: the compliance decision on a
    participant request, where `X-User-ID` must differ from the stored
    `reviewed_by_user_id` whenever the decision is an approval or a denial; and the
    compliance decision on a contribution election, where `X-User-ID` must differ from the
    `determined_by_user_id` of the latest non-superseded eligibility determination for
    that election's plan-and-participant pair."
    PRD §3.8: "`APPROVE` and `DENY` both move the request out of `UNDER_REVIEW` and both
    require that the deciding officer's `X-User-ID` differs from the stored
    `reviewed_by_user_id`; the same officer may not both open review and decide."

    Design: Corner/validations/same_officer_cannot_open_review_and_approve_participant_request
    """
    env = setup_request_under_review(
        "HARDSHIP",
        request_overrides={
            "requested_amount_cents": 100_000, "stated_need_cents": 100_000,
            "safe_harbor_reason": "MEDICAL_EXPENSES",
        },
        reviewing_officer="co-1",
    )

    refused = api.decide_participant_request(
        env["request_id"], {"decision": "APPROVE"}, make_officer_headers("co-1")
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    blocked = validate_success(
        api.get_participant_request(env["request_id"], make_officer_headers())
    )
    assert blocked["state"] == "UNDER_REVIEW"
    assert blocked["decided_by_user_id"] is None

    approved = validate_success(
        api.decide_participant_request(
            env["request_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
        )
    )
    assert approved["state"] == "APPROVED"
    assert approved["decided_by_user_id"] == "co-2"


def test_distribution_standard_violations_are_rejected(api):
    """PRD §3.8: "A `HARDSHIP` may be requested only on a `PLAN_403B` plan whose
    `permits_hardship` is true; an `UNFORESEEABLE_EMERGENCY` only on a `PLAN_457B` plan
    whose `permits_unforeseeable_emergency` is true; a `LOAN` only on a plan whose
    `permits_loans` is true. Anything else — a hardship on a 457(b), an unforeseeable
    emergency on a 403(b), or a type the plan document simply does not offer — is refused
    with `ERR_DISTRIBUTION_TYPE_NOT_PERMITTED`."
    PRD §3.8: "A hardship must additionally name a deemed-immediate-and-heavy safe-harbour
    event, so a `safe_harbor_reason` of `NONE` is refused with
    `ERR_HARDSHIP_NOT_SAFE_HARBOR`"
    PRD §3.8: "but `COLLEGE_TUITION` and `PURCHASE_OF_HOME` are expressly *not*
    unforeseeable emergencies, and neither is `NONE`; citing any of those three is refused
    with `ERR_UE_STANDARD_NOT_MET`."

    Design: Corner/validations/hardship_and_emergency_standard_violations_are_rejected
    """
    env = _two_standard_env()
    headers = make_participant_headers(env["participant_id"])

    hardship_on_457b = api.create_participant_request(
        {
            "participant_id": env["participant_id"], "plan_id": env["plan_457b_id"],
            "vendor_account_id": env["account_457b_id"], "request_type": "HARDSHIP",
            "requested_amount_cents": 100_000, "stated_need_cents": 100_000,
            "safe_harbor_reason": "MEDICAL_EXPENSES",
        },
        headers,
    )
    validate_error(hardship_on_457b, ApiErrorId.ERR_DISTRIBUTION_TYPE_NOT_PERMITTED.value)

    hardship_without_reason = api.create_participant_request(
        {
            "participant_id": env["participant_id"], "plan_id": env["plan_403b_id"],
            "vendor_account_id": env["account_403b_id"], "request_type": "HARDSHIP",
            "requested_amount_cents": 100_000, "stated_need_cents": 100_000,
        },
        headers,
    )
    validate_error(hardship_without_reason, ApiErrorId.ERR_HARDSHIP_NOT_SAFE_HARBOR.value)

    home_purchase_emergency = api.create_participant_request(
        {
            "participant_id": env["participant_id"], "plan_id": env["plan_457b_id"],
            "vendor_account_id": env["account_457b_id"],
            "request_type": "UNFORESEEABLE_EMERGENCY", "requested_amount_cents": 100_000,
            "stated_need_cents": 100_000, "emergency_reason": "PURCHASE_OF_HOME",
        },
        headers,
    )
    validate_error(home_purchase_emergency, ApiErrorId.ERR_UE_STANDARD_NOT_MET.value)

    rows, _meta = validate_paginated(
        api.list_participant_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert rows == []


def test_emergency_with_sufficient_relief_is_refused_at_approval(api):
    """PRD §3.8: "Total relief is `insurance_reimbursement_available_cents` plus
    `liquidatable_assets_cents` plus `deferral_cessation_relief_cents`; if that total is
    greater than or equal to `stated_need_cents` the request is refused with
    `ERR_UE_RELIEF_AVAILABLE`, so relief exactly equal to the stated need already defeats
    the request."

    Design: Corner/validations/unforeseeable_emergency_with_sufficient_relief_is_rejected_at_approval
    """
    env = setup_request_under_review(
        "UNFORESEEABLE_EMERGENCY", plan_type="PLAN_457B",
        request_overrides={
            "requested_amount_cents": 100_000, "stated_need_cents": 2_000_000,
            "emergency_reason": "EXTRAORDINARY_MEDICAL",
            "insurance_reimbursement_available_cents": 1_000_000,
            "liquidatable_assets_cents": 700_000,
            "deferral_cessation_relief_cents": 300_000,
        },
    )

    response = api.decide_participant_request(
        env["request_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
    )

    validate_error(response, ApiErrorId.ERR_UE_RELIEF_AVAILABLE.value)
    unchanged = validate_success(
        api.get_participant_request(env["request_id"], make_officer_headers())
    )
    assert unchanged["state"] == "UNDER_REVIEW"
    assert unchanged["max_approvable_cents"] is None
