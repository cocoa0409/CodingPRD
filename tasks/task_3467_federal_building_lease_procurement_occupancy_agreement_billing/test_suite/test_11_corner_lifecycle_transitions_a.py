"""Corner coverage: lifecycle transitions — requirements, offers, leases,
occupancy agreements, and rent bills."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_agency, create_leased_building,
    create_offer_payload, create_requirement, generate_bill,
    get_success_data, make_agency_manager_headers, pay_bill, set_clock,
    setup_active_leased_oa, setup_active_owned_oa, setup_awarded_lease,
    submit_requirement, validate_error, validate_paginated, validate_success,
    walk_requirement_to_soliciting,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_requirement_return_resubmit_revision_cycle(api):
    """PRD §3.2: "A `GSALeasingOfficer` who finds the requirement deficient
    returns it, moving `SUBMITTED` to `NEEDS_REVISION`, and the agency
    resubmits from `NEEDS_REVISION` back to `SUBMITTED` — again scope-checked.
    This return-and-resubmit cycle may repeat without bound."
    PRD §3.2: "the base level is 1 when the total is below 15, 2 when it is at
    least 15 but below 30, 3 when at least 30 but below 45, 4 when at least 45
    but below 60, and 5 when it reaches 60."

    Design: Corner/state_machines/requirement_return_resubmit_revision_cycle
    """
    agency = create_agency()
    set_clock("2026-10-01T00:00:00Z")
    req = create_requirement(
        agency, title="Field Office", base_headcount=120,
        annual_growth_pct=0.01, target_occupancy_year=2030, sf_per_person=160,
        special_needs=[], region_code="R4", mission_points=10,
        population_points=8, size_points=6, criticality_points=6)
    submit_requirement(req, agency)

    returned = validate_success(api.return_requirement(req["id"], OFFICER), 200)
    assert returned["status"] == "NEEDS_REVISION"

    resubmitted = validate_success(api.resubmit_requirement(
        req["id"], make_agency_manager_headers(agency["id"])), 200)
    assert resubmitted["status"] == "SUBMITTED", "cycle closed"

    validated = validate_success(api.validate_requirement(req["id"], OFFICER), 200)
    assert validated["status"] == "VALIDATED"
    assert validated["required_security_level"] == 3, "30 points: 10+8+6+6, no SCIF"


def test_requirement_submit_from_validated_rejected(api):
    """PRD §3.2: "Submission moves the requirement from `DRAFT` to
    `SUBMITTED`"
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/requirement_submit_from_validated_rejected
    """
    agency = create_agency()
    set_clock("2026-10-01T00:00:00Z")
    req = create_requirement(
        agency, title="Field Office", base_headcount=120,
        annual_growth_pct=0.01, target_occupancy_year=2030, sf_per_person=160,
        special_needs=[], region_code="R4", mission_points=10,
        population_points=8, size_points=6, criticality_points=6)
    submit_requirement(req, agency)
    get_success_data(api.validate_requirement(req["id"], OFFICER))

    resp = api.submit_requirement(req["id"], make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(api.get_space_requirement(req["id"], OFFICER), 200)
    assert after["status"] == "VALIDATED"


def test_requirement_awarded_terminal_lockdown(api):
    """PRD §3.2: "When an offer is finally selected, the system itself moves
    the requirement from `SOLICITING` to `AWARDED` — a terminal state that
    hands the lifecycle off to the newly created lease."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/requirement_awarded_terminal_lockdown
    """
    bundle = setup_awarded_lease()
    req = bundle["req"]
    resp = api.return_requirement(req["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(api.get_space_requirement(req["id"], OFFICER), 200)
    assert after["status"] == "AWARDED", "the award stands"


def test_offer_select_before_evaluate_rejected(api):
    """PRD §3.3: "A new offer starts in `SUBMITTED`; a `GSALeasingOfficer`
    moves it to `UNDER_EVALUATION` when evaluation begins."
    PRD §3.3: "Awarding the lease — selecting an offer, moving it from
    `UNDER_EVALUATION` to `SELECTED` — is the most heavily gated operation in
    the system."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/offer_select_before_evaluate_rejected
    """
    agency = create_agency()
    building = create_leased_building()
    set_clock("2026-10-01T00:00:00Z")
    req = walk_requirement_to_soliciting(agency)
    offer = get_success_data(api.create_offer(
        req["id"], create_offer_payload(building["id"]), LESSOR))

    resp = api.select_offer(offer["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(api.get_offer(offer["id"], OFFICER), 200)
    assert after["status"] == "SUBMITTED"
    leases, _ = validate_paginated(api.list_leases(
        OFFICER, params={"requirement_id": req["id"]}))
    assert leases == []


def test_offer_withdraw_after_selection_rejected(api):
    """PRD §3.3: "A `LessorRep` may withdraw an offer that is still in
    `SUBMITTED` or still in `UNDER_EVALUATION`; either way the offer lands in
    `WITHDRAWN` with `rejection_reason` set to `WITHDRAWN_BY_LESSOR`."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/offer_withdraw_after_selection_rejected
    """
    bundle = setup_awarded_lease()
    resp = api.withdraw_offer(bundle["offer"]["id"], LESSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(api.get_offer(bundle["offer"]["id"], OFFICER), 200)
    assert after["status"] == "SELECTED"


def test_offer_withdraw_stamps_rejection_reason(api):
    """PRD §3.3: "A `LessorRep` may withdraw an offer that is still in
    `SUBMITTED` or still in `UNDER_EVALUATION`; either way the offer lands in
    `WITHDRAWN` with `rejection_reason` set to `WITHDRAWN_BY_LESSOR`."

    Design: Corner/state_machines/offer_withdraw_stamps_rejection_reason
    """
    agency = create_agency()
    building = create_leased_building()
    set_clock("2026-10-01T00:00:00Z")
    req = walk_requirement_to_soliciting(agency)
    offer = get_success_data(api.create_offer(
        req["id"], create_offer_payload(building["id"]), LESSOR))

    withdrawn = validate_success(api.withdraw_offer(offer["id"], LESSOR), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["rejection_reason"] == "WITHDRAWN_BY_LESSOR"


def test_lease_commence_window_edge_and_repeat_guard(api):
    """PRD §3.4: "The commencement date must fall on or after the award date
    and no later than twenty-four months after it; outside that window the
    request fails with `ERR_COMMENCEMENT_OUT_OF_WINDOW`."
    PRD §3.4: "Commencement pins the lease's `end_date`: the date
    `term_months` months after the commencement date, minus one day, using
    month arithmetic with the day preserved and clamped to the target month's
    end."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Awarded 2026-10-01: 2028-10-02 is beyond the 24-month window, 2028-10-01 is
    the inclusive boundary, and a second commence is an invalid transition.

    Design: Corner/state_machines/lease_commence_window_edge_and_repeat_guard
    """
    bundle = setup_awarded_lease()  # awarded at logical clock 2026-10-01
    lease = bundle["lease"]

    too_late = api.commence_lease(
        lease["id"], {"commencement_date": "2028-10-02",
                      "ti_buildout_cost_cents": 400000000,
                      "ti_amort_method": "ANNUITY"}, OFFICER)
    validate_error(too_late, ApiErrorId.ERR_COMMENCEMENT_OUT_OF_WINDOW)

    commenced = validate_success(api.commence_lease(
        lease["id"], {"commencement_date": "2028-10-01",
                      "ti_buildout_cost_cents": 400000000,
                      "ti_amort_method": "ANNUITY"}, OFFICER), 200)
    assert commenced["status"] == "COMMENCED", "boundary inclusive"
    assert commenced["end_date"] == "2038-09-30"

    repeat = api.commence_lease(
        lease["id"], {"commencement_date": "2028-10-01",
                      "ti_buildout_cost_cents": 400000000,
                      "ti_amort_method": "ANNUITY"}, OFFICER)
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_lease_expiring_sweep_at_exact_threshold(api):
    """PRD §2.4: "A lease in `COMMENCED` moves to `EXPIRING` once the current
    date reaches the date eighteen months before its `end_date` (month
    arithmetic, with the day clamped to the month end when the target month is
    shorter)."
    PRD §2.4: "The clock-setting response reports `current_utc` plus the ids of
    everything the sweep moved: `transitioned_lease_ids`,
    `transitioned_oa_ids`, and `transitioned_plan_ids`."

    end_date 2036-12-31 minus 18 months is 2035-06-30 (day clamped): at
    2035-06-29 the lease is still COMMENCED, at 2035-06-30 it is EXPIRING.

    Design: Corner/state_machines/lease_expiring_sweep_at_exact_threshold
    """
    bundle = setup_active_leased_oa(tax_year=None)
    lease = bundle["lease"]

    sweep1 = set_clock("2035-06-29T00:00:00Z")
    assert lease["id"] not in sweep1["transitioned_lease_ids"]
    mid = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert mid["status"] == "COMMENCED", "threshold not reached"

    sweep2 = set_clock("2035-06-30T00:00:00Z")
    assert lease["id"] in sweep2["transitioned_lease_ids"]
    end = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert end["status"] == "EXPIRING"


def test_oa_activate_twice_rejected(api):
    """PRD §3.5: "Activation — the tenant agency signing — moves `DRAFT` to
    `ACTIVE`"
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/oa_activate_twice_rejected
    """
    bundle = setup_active_owned_oa()
    oa, agency = bundle["oa"], bundle["agency"]
    resp = api.activate_oa(oa["id"], make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert after["status"] == "ACTIVE"


def test_bill_partial_payment_then_exact_payoff(api):
    """PRD §3.5: "a payment smaller than the remaining balance moves an
    `ISSUED` bill to `PARTIALLY_PAID` with `amount_paid_cents` increased by the
    amount; a payment exactly equal to the remaining balance moves an `ISSUED`
    bill straight to `PAID` with `amount_paid_cents` set to `total_cents`; and
    a payment exactly equal to the remaining balance on a `PARTIALLY_PAID` bill
    moves it to `PAID` the same way."
    PRD §3.5: "Every payment appends a record of `paid_at`, `amount_cents`, and
    `payer_user_id` to `payments`, and the agreement's receivable ledger is
    recomputed."

    Design: Corner/state_machines/bill_partial_payment_then_exact_payoff
    """
    bundle = setup_active_leased_oa()
    oa, agency = bundle["oa"], bundle["agency"]
    bill = generate_bill(oa, "2027-04")
    assert bill["total_cents"] == 24347894

    first = pay_bill(bill, agency, 1000000)
    assert first["status"] == "PARTIALLY_PAID"
    assert first["amount_paid_cents"] == 1000000

    second = pay_bill(bill, agency, 23347894)
    assert second["status"] == "PAID"
    assert second["amount_paid_cents"] == 24347894
    assert len(second["payments"]) == 2


def test_bill_overpayment_rejected(api):
    """PRD §3.5: "Payment is made by the `AgencyManager` of the bill's agency
    (scope-checked), supplying an `amount_cents` that must be greater than zero
    and no more than the bill's remaining balance — `total_cents` minus what
    has already been paid — or the payment fails with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/state_machines/bill_overpayment_rejected
    """
    bundle = setup_active_leased_oa()
    oa, agency = bundle["oa"], bundle["agency"]
    bill = generate_bill(oa, "2027-04")
    assert bill["total_cents"] == 24347894

    resp = api.pay_bill(bill["id"], {"amount_cents": 24347895},
                        make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

    bills, _ = validate_paginated(api.list_bills(oa["id"], ADMIN))
    assert bills[0]["amount_paid_cents"] == 0
    assert bills[0]["status"] == "ISSUED", "the rejection left no trace"
