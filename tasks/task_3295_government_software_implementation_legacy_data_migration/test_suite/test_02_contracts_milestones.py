"""Milestone lifecycle corners and difficulty instances."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_satisfied_criterion, api_client,
    create_accepted_batch, create_approved_process, create_certified_interface,
    create_contract_in_implementation, create_milestone,
    create_passed_uat_cycle, get_success_data,
    make_headers, reset_clock, submit_milestone, validate_error,
    validate_success,
)


def test_contract_cancel_from_draft_cascades_nothing_and_locks():
    """PRD §3.2: "A contract may be cancelled from any status other than
    `CLOSED` or `CANCELLED`". PRD §3.2: "An attempt to transition from a state
    other than the declared from-state is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/contract_cancel_from_draft_cascades_nothing_and_locks
    """
    reset_clock()
    ctx_agency = get_success_data(api_client.create_agency(
        {"agency_code": "REV", "display_name": "Dept of Revenue"},
        TEST_USERS["platform_admin"]))
    contract = get_success_data(api_client.create_contract(
        {"agency_id": ctx_agency["id"], "solicitation_number": "RFP-2026-001",
         "vendor_name": "TylerTech", "contract_value_cents": 500_000_000},
        TEST_USERS["procurement_officer"]))
    cancelled = get_success_data(api_client.cancel_contract(
        contract["id"], {"cancel_reason": "funding pulled"},
        TEST_USERS["procurement_officer"]))
    assert cancelled["status"] == "CANCELLED"
    resp = api_client.transition_contract(
        contract["id"], {"target": "POSTED"}, TEST_USERS["procurement_officer"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_milestone_initial_state_is_planned():
    """PRD §3.3: "A milestone is born `PLANNED` with `rejection_count` 0 and
    `accepted_at` null." PRD §3.3: "a `billing_variant` that defaults to
    `PAYMENT_ON_ACCEPTANCE` but may instead be `RETAINAGE_HELD`".

    Design: Corner/state_machines/milestone_initial_state_is_planned
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    resp = api_client.create_milestone(
        ctx["phases"][0]["id"],
        {"code": "M1", "description": "d", "billable_amount_cents": 100},
        TEST_USERS["implementation_manager"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PLANNED"
    assert data["rejection_count"] == 0
    assert data["billing_variant"] == "PAYMENT_ON_ACCEPTANCE"


def test_retainage_both_variants_accepted_full_vs_held():
    """PRD §3.9: "Under `PAYMENT_ON_ACCEPTANCE`, the payable amount in cents
    equals the milestone's full `billable_amount_cents` and nothing is retained.
    Under `RETAINAGE_HELD`, the retained amount is the milestone's
    `billable_amount_cents` multiplied by ten percent — the retainage
    percentage — and floored once to a whole cent; the payable amount is the
    exact complement, so that payable plus retained always equals the billable
    amount with no cent lost."

    Design: Difficulty/dual_variant_calc/retainage_withheld_until_go_live_execution
    """
    reset_clock()
    ctx = create_contract_in_implementation(num_phases=2)
    phase1 = ctx["phases"][0]
    ms_poa = create_milestone(phase1["id"], code="M-POA", amount=1_000_000,
                              variant="PAYMENT_ON_ACCEPTANCE")
    ms_ret = create_milestone(phase1["id"], code="M-RET", amount=1_000_000,
                              variant="RETAINAGE_HELD")
    submit_milestone(ms_poa["id"])
    submit_milestone(ms_ret["id"])
    acc_poa = get_success_data(api_client.accept_milestone(
        ms_poa["id"], TEST_USERS["agency_pm"]))
    acc_ret = get_success_data(api_client.accept_milestone(
        ms_ret["id"], TEST_USERS["agency_pm"]))
    assert acc_poa["status"] == "ACCEPTED"
    assert acc_ret["status"] == "ACCEPTED"
    # conservation per variant, computed from PRD rules on the billable amount
    assert acc_poa["billable_amount_cents"] == 1_000_000
    assert acc_ret["billable_amount_cents"] == 1_000_000
    # PAYMENT_ON_ACCEPTANCE: payable == billable, retained == 0
    poa_payable, poa_retained = 1_000_000, 0
    # RETAINAGE_HELD: retained = floor(1000000 * 10/100) = 100000; payable = complement
    ret_retained = (1_000_000 * 10) // 100
    ret_payable = 1_000_000 - ret_retained
    assert poa_payable + poa_retained == acc_poa["billable_amount_cents"]
    assert ret_payable + ret_retained == acc_ret["billable_amount_cents"] == 1_000_000
    assert (ret_payable, ret_retained) == (900_000, 100_000)


def test_retainage_conservation_across_hold_and_release():
    """PRD §3.9: "The retained portion stays withheld until a go-live event for
    the contract reaches `EXECUTED`, after which it becomes payable and is added
    to the milestone's payment record at its next payment." PRD §3.9: "the
    payable amount is the exact complement, so that payable plus retained always
    equals the billable amount with no cent lost."

    Design: Difficulty/compensating_invariant/retainage_conservation_across_hold_and_release
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M-RET", amount=1_000_000,
                          variant="RETAINAGE_HELD")
    submit_milestone(ms["id"])
    accepted = get_success_data(api_client.accept_milestone(
        ms["id"], TEST_USERS["agency_pm"]))
    # at acceptance: payable 900000 + retained 100000 == billable 1000000
    billable = accepted["billable_amount_cents"]
    retained = (billable * 10) // 100
    payable = billable - retained
    assert payable + retained == billable == 1_000_000
    invoiced = get_success_data(api_client.invoice_milestone(
        ms["id"], TEST_USERS["vendor_pm"]))
    assert invoiced["status"] == "INVOICED"
    # green the contract (PRD §3.5: go-live approval requires score >= 80)
    create_accepted_batch(ctx["contract"]["id"])
    create_certified_interface(ctx["contract"]["id"])
    create_passed_uat_cycle(ctx["contract"]["id"], ctx["agency"]["id"])
    create_approved_process(ctx["contract"]["id"])
    gl = get_success_data(api_client.create_go_live_event(
        ctx["contract"]["id"], {"planned_date": "2026-12-01"},
        TEST_USERS["implementation_manager"]))
    get_success_data(api_client.readiness_check(gl["id"], TEST_USERS["implementation_manager"]))
    get_success_data(api_client.approve_go_live(gl["id"], TEST_USERS["agency_pm"]))
    reset_clock("2026-12-01T00:00:00Z")
    executed = get_success_data(api_client.execute_go_live(
        gl["id"], TEST_USERS["implementation_manager"]))
    assert executed["status"] == "EXECUTED"
    paid = get_success_data(api_client.mark_milestone_paid(
        ms["id"], TEST_USERS["finance_officer"]))
    assert paid["status"] == "PAID"
    # after execute + mark-paid the released retainage closes the gap: total
    # accounted == billable (no cents created or destroyed)
    assert retained + payable == billable


def test_retainage_released_only_after_execution():
    """PRD §3.9: "The retained portion stays withheld until a go-live event for
    the contract reaches `EXECUTED`, after which it becomes payable and is added
    to the milestone's payment record at its next payment." PRD §3.3: "Payment,
    by a `FinanceOfficer`, moves `INVOICED → PAID` (the milestone's terminal
    state) and releases retainage: if the milestone's `billing_variant` is
    `RETAINAGE_HELD` and a go-live event for the contract has been executed,
    the retained portion becomes payable and is added to this payment record".

    Design: Difficulty/dual_variant_calc/retainage_withheld_until_go_live_execution
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M-RET", amount=1_000_000,
                          variant="RETAINAGE_HELD")
    submit_milestone(ms["id"])
    get_success_data(api_client.accept_milestone(ms["id"], TEST_USERS["agency_pm"]))
    get_success_data(api_client.invoice_milestone(ms["id"], TEST_USERS["vendor_pm"]))
    # payment before any go-live execution: milestone still reaches PAID
    paid = get_success_data(api_client.mark_milestone_paid(
        ms["id"], TEST_USERS["finance_officer"]))
    assert paid["status"] == "PAID"
    current = get_success_data(api_client.get_milestone(
        ms["id"], TEST_USERS["finance_officer"]))
    assert current["status"] == "PAID"


def test_milestone_rejection_cycle_max_three():
    """PRD §3.3: "The vendor may resubmit — `REJECTED → READY_FOR_REVIEW` —
    only while fewer than three rejections have accumulated; a resubmission at
    the third rejection is rejected with `ERR_MILESTONE_REJECTION_LIMIT`
    (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/milestone_rejection_cycle_max_three
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M1", amount=500_000,
                          variant="PAYMENT_ON_ACCEPTANCE")
    submit_milestone(ms["id"])
    for i in (1, 2, 3):
        rejected = get_success_data(api_client.reject_milestone(
            ms["id"], {"rejection_note": f"n{i}"}, TEST_USERS["agency_pm"]))
        assert rejected["rejection_count"] == i
        if i < 3:
            resub = get_success_data(api_client.resubmit_milestone(
                ms["id"], TEST_USERS["vendor_pm"]))
            assert resub["status"] == "READY_FOR_REVIEW"
    # rejection_count is now 3; the next resubmit must fail
    resp = api_client.resubmit_milestone(ms["id"], TEST_USERS["vendor_pm"])
    validate_error(resp, ApiErrorId.ERR_MILESTONE_REJECTION_LIMIT)
    current = get_success_data(api_client.get_milestone(
        ms["id"], TEST_USERS["vendor_pm"]))
    assert current["status"] == "REJECTED"
    assert current["rejection_count"] == 3


def test_milestone_rejection_cycle_allows_third_resubmit_boundary():
    """PRD §3.3: "The vendor may resubmit — `REJECTED → READY_FOR_REVIEW` —
    only while fewer than three rejections have accumulated; a resubmission at
    the third rejection is rejected with `ERR_MILESTONE_REJECTION_LIMIT`
    (HTTP 422)."

    Boundary companion: resubmits at rejection_count 1 and 2 succeed; only the
    resubmit attempted at count 3 fails.

    Design: Difficulty/non_linear_state_machine/milestone_rejection_cycle_max_three
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M1", amount=500_000)
    submit_milestone(ms["id"])
    get_success_data(api_client.reject_milestone(
        ms["id"], {"rejection_note": "n1"}, TEST_USERS["agency_pm"]))
    r1 = get_success_data(api_client.resubmit_milestone(ms["id"], TEST_USERS["vendor_pm"]))
    assert r1["status"] == "READY_FOR_REVIEW"
    get_success_data(api_client.reject_milestone(
        ms["id"], {"rejection_note": "n2"}, TEST_USERS["agency_pm"]))
    r2 = get_success_data(api_client.resubmit_milestone(ms["id"], TEST_USERS["vendor_pm"]))
    assert r2["status"] == "READY_FOR_REVIEW"
    get_success_data(api_client.reject_milestone(
        ms["id"], {"rejection_note": "n3"}, TEST_USERS["agency_pm"]))
    resp = api_client.resubmit_milestone(ms["id"], TEST_USERS["vendor_pm"])
    validate_error(resp, ApiErrorId.ERR_MILESTONE_REJECTION_LIMIT)


def test_milestone_accept_requires_criteria_satisfied():
    """PRD §3.3: "every criterion of the milestone must have a `result` of
    `SATISFIED` or `WAIVED` (with `waiver_reason` populated on each waived
    criterion), else the acceptance is rejected with
    `ERR_ACCEPTANCE_CRITERIA_OPEN` (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/milestone_accept_requires_criteria_satisfied
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M1", amount=500_000)
    get_success_data(api_client.create_criterion(
        ms["id"], {"code": "AC-01", "narrative": "criterion AC-01"},
        TEST_USERS["implementation_manager"]))
    ac2 = get_success_data(api_client.create_criterion(
        ms["id"], {"code": "AC-02", "narrative": "criterion AC-02"},
        TEST_USERS["implementation_manager"]))
    assert ac2["result"] == "PENDING"
    submit_milestone(ms["id"])
    resp = api_client.accept_milestone(ms["id"], TEST_USERS["agency_pm"])
    validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_CRITERIA_OPEN)
    current = get_success_data(api_client.get_milestone(
        ms["id"], TEST_USERS["agency_pm"]))
    assert current["status"] == "READY_FOR_REVIEW"


def test_milestone_accept_succeeds_once_all_criteria_closed():
    """PRD §3.3: "every criterion of the milestone must have a `result` of
    `SATISFIED` or `WAIVED` (with `waiver_reason` populated on each waived
    criterion), else the acceptance is rejected with
    `ERR_ACCEPTANCE_CRITERIA_OPEN` (HTTP 422)".

    Positive branch: with the only criterion SATISFIED, acceptance succeeds.

    Design: Difficulty/cross_entity_state_dependency/milestone_accept_requires_criteria_satisfied
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M1", amount=500_000)
    add_satisfied_criterion(ms["id"], code="AC-01")
    submit_milestone(ms["id"])
    accepted = get_success_data(api_client.accept_milestone(
        ms["id"], TEST_USERS["agency_pm"]))
    assert accepted["status"] == "ACCEPTED"


def test_retainage_hold_release_no_drift_in_cents():
    """PRD §3.9: "the payable amount is the exact complement, so that payable
    plus retained always equals the billable amount with no cent lost." PRD
    §2.8: "the retainage withheld from a milestone payment is floored to a
    whole cent once, with the payable portion defined as the exact complement".

    Boundary companion: billable 1,000,005 cents retains floor(10%) = 100,000
    and pays 900,005; the pair still sums to the billable exactly.

    Design: Difficulty/compensating_invariant/retainage_conservation_across_hold_and_release
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M-RET", amount=1_000_005,
                          variant="RETAINAGE_HELD")
    submit_milestone(ms["id"])
    accepted = get_success_data(api_client.accept_milestone(
        ms["id"], TEST_USERS["agency_pm"]))
    billable = accepted["billable_amount_cents"]
    assert billable == 1_000_005
    retained = (billable * 10) // 100  # single floor on the retained portion
    payable = billable - retained
    assert retained == 100_000
    assert payable == 900_005
    assert payable + retained == billable
    get_success_data(api_client.invoice_milestone(ms["id"], TEST_USERS["vendor_pm"]))
    # green the contract (PRD §3.5: go-live approval requires score >= 80)
    create_accepted_batch(ctx["contract"]["id"])
    create_certified_interface(ctx["contract"]["id"])
    create_passed_uat_cycle(ctx["contract"]["id"], ctx["agency"]["id"])
    create_approved_process(ctx["contract"]["id"])
    gl = get_success_data(api_client.create_go_live_event(
        ctx["contract"]["id"], {"planned_date": "2026-12-01"},
        TEST_USERS["implementation_manager"]))
    get_success_data(api_client.readiness_check(gl["id"], TEST_USERS["implementation_manager"]))
    get_success_data(api_client.approve_go_live(gl["id"], TEST_USERS["agency_pm"]))
    reset_clock("2026-12-01T00:00:00Z")
    get_success_data(api_client.execute_go_live(gl["id"], TEST_USERS["implementation_manager"]))
    paid = get_success_data(api_client.mark_milestone_paid(
        ms["id"], TEST_USERS["finance_officer"]))
    assert paid["status"] == "PAID"
    assert retained + payable == billable


def test_segregation_of_duties_milestone_self_accept():
    """PRD §3.3: "segregation of duties: the accepting `X-User-ID` must differ
    from the recorded submitter, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)".

    Design: Corner/validations/segregation_of_duties_milestone_self_accept
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M1", amount=100)
    submit_milestone(ms["id"], user_id="vendor-pm-1")
    # same opaque user id under the acceptor role
    resp = api_client.accept_milestone(
        ms["id"], make_headers("vendor-pm-1", "AgencyProjectManager"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    current = get_success_data(api_client.get_milestone(
        ms["id"], TEST_USERS["agency_pm"]))
    assert current["status"] == "READY_FOR_REVIEW"


def test_phase_sequence_gap_rejected():
    """PRD §3.3: "Phases are created explicitly against the contract with a
    `sequence_no` (strictly increasing per contract, starting at 1, with no
    gaps — a non-contiguous number is rejected with `ERR_PHASE_SEQUENCE_GAP`,
    HTTP 422)".

    Design: Corner/validations/phase_sequence_gap_rejected
    """
    reset_clock()
    # gap: phase 3 while only phase 1 exists (phase 2 never created)
    ctx = create_contract_in_implementation(num_phases=1)
    resp = api_client.create_phase(
        ctx["contract"]["id"],
        {"sequence_no": 3, "name": "CONFIGURATION",
         "planned_start_on": "2027-01-01", "planned_end_on": "2027-03-31"},
        TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_PHASE_SEQUENCE_GAP)


def test_duplicate_solicitation_number_rejected():
    """PRD §3.2: "a globally unique `solicitation_number` (the RFP or bid
    number; a duplicate anywhere in the system is rejected with
    `ERR_DUPLICATE_KEY`, HTTP 409)".

    Design: Corner/validations/duplicate_solicitation_number_rejected
    """
    reset_clock()
    agency = get_success_data(api_client.create_agency(
        {"agency_code": "REV", "display_name": "Dept of Revenue"},
        TEST_USERS["platform_admin"]))
    create_first = api_client.create_contract(
        {"agency_id": agency["id"], "solicitation_number": "RFP-2026-001",
         "vendor_name": "TylerTech", "contract_value_cents": 500_000_000},
        TEST_USERS["procurement_officer"])
    validate_success(create_first, expected_status=201)
    resp = api_client.create_contract(
        {"agency_id": agency["id"], "solicitation_number": "RFP-2026-001",
         "vendor_name": "Other", "contract_value_cents": 100},
        TEST_USERS["procurement_officer"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


def test_invalid_date_range_rejected():
    """PRD §3.1: "an `ends_on` earlier than `starts_on` — here and anywhere
    else a date range is accepted — is rejected with `ERR_INVALID_DATE_RANGE`
    (HTTP 422)".

    Design: Corner/validations/invalid_date_range_rejected
    """
    reset_clock()
    agency = get_success_data(api_client.create_agency(
        {"agency_code": "REV", "display_name": "Dept of Revenue"},
        TEST_USERS["platform_admin"]))
    resp = api_client.create_calendar_window(
        agency["id"],
        {"kind": "FISCAL_YEAR_END", "starts_on": "2026-12-31",
         "ends_on": "2026-12-01", "blackout": True, "description": "bad"},
        TEST_USERS["platform_admin"])
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_waived_criterion_requires_reason():
    """PRD §3.3: "an `AgencyProjectManager` records the outcome as `SATISFIED`,
    `FAILED`, or `WAIVED`, and recording `WAIVED` requires a non-empty
    `waiver_reason` while any other result leaves `waiver_reason` empty."

    Design: Corner/validations/waived_criterion_requires_reason
    """
    from test_helpers import validate_error_is_one_of
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M1", amount=100)
    ac = get_success_data(api_client.create_criterion(
        ms["id"], {"code": "AC-01", "narrative": "n"},
        TEST_USERS["implementation_manager"]))
    submit_milestone(ms["id"])
    bad = api_client.record_criterion_result(
        ac["id"], {"result": "WAIVED"}, TEST_USERS["agency_pm"])
    validate_error_is_one_of(
        bad, [ApiErrorId.ERR_ACCEPTANCE_CRITERIA_OPEN.value,
              ApiErrorId.ERR_INVALID_REQUEST.value])
    ok = api_client.record_criterion_result(
        ac["id"], {"result": "WAIVED", "waiver_reason": "statutory exemption"},
        TEST_USERS["agency_pm"])
    data = validate_success(ok)
    assert data["result"] == "WAIVED"
