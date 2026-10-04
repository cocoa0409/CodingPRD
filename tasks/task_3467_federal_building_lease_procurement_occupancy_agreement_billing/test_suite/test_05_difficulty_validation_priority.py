"""Priority-pair conflicts: when two rules are violated, the lower priority
number produces the response (PRD §2.10)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_agency, create_leased_building,
    create_offer_payload, generate_bill, get_success_data,
    make_agency_manager_headers, pay_bill, set_clock, setup_active_leased_oa,
    validate_error, validate_paginated, validate_success,
    walk_requirement_to_soliciting,
)

OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_bill_pay_state_lockdown_beats_overpayment_fiscal(api):
    """PRD §2.10: "When a single request violates several rules, the violation
    with the lowest priority number produces the response; the checks are
    evaluated in this order:"
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."
    PRD §2.10: "12. Fiscal gates — `ERR_AMORTIZATION_WINDOW_TOO_SHORT` and
    `ERR_PAYMENT_EXCEEDS_BALANCE` (both 422)."

    A 1-cent payment against a fully PAID bill violates both the state rule
    (PAID is terminal) and the fiscal rule (1 > remaining balance 0); the
    priority-6 state error must win over the priority-12 fiscal error.

    Design: Difficulty/priority_pair_validation_conflict/bill_pay_state_lockdown_beats_overpayment_fiscal
    """
    bundle = setup_active_leased_oa()
    oa, agency = bundle["oa"], bundle["agency"]
    agency_h = make_agency_manager_headers(agency["id"])

    bill = generate_bill(oa, "2027-04")
    assert bill["total_cents"] == 24347894
    paid = pay_bill(bill, agency, 24347894)
    assert paid["status"] == "PAID"

    resp = api.pay_bill(bill["id"], {"amount_cents": 1}, agency_h)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert err["error_id"] == "ERR_INVALID_STATE_TRANSITION", (
        "state (priority 6) beats fiscal (priority 12): "
        "never ERR_PAYMENT_EXCEEDS_BALANCE here")

    bills, _ = validate_paginated(api.list_bills(oa["id"], TEST_USERS["gsa_admin_headers"]))
    assert bills[0]["status"] == "PAID"
    assert bills[0]["amount_paid_cents"] == 24347894


def test_offer_select_security_gate_beats_offer_expiry(api):
    """PRD §3.3: "Four preconditions hold, surfacing in validation-priority
    order (§2.10): the requirement must still be `SOLICITING`
    (`ERR_REQUIREMENT_NOT_SOLICITING`); the offered building's
    `security_capability` must be at least the requirement's
    `required_security_level` (`ERR_SECURITY_LEVEL_INSUFFICIENT`); the offer's
    `valid_until` must not be earlier than the current logical clock
    (`ERR_OFFER_EXPIRED`); and the offered building's `available_sf` must be at
    least the requirement's `required_usable_sf`
    (`ERR_BUILDING_CAPACITY_EXCEEDED`)."
    PRD §2.10: "8. Award safety: the offered building's security capability
    against the requirement's level — `ERR_SECURITY_LEVEL_INSUFFICIENT` (422)."
    PRD §2.10: "9. Temporal windows — `ERR_OFFER_EXPIRED`,
    `ERR_COMMENCEMENT_OUT_OF_WINDOW`, `ERR_BILL_MONTH_OUT_OF_TERM`,
    `ERR_OPTION_DEADLINE_PASSED` (all 422), and
    `ERR_ALTERATION_WINDOW_CONFLICT` (409)."

    The offered building's capability 3 is below the required level 4 AND the
    offer lapsed at 2026-09-15; the priority-8 safety error must win over the
    priority-9 temporal error.

    Design: Difficulty/priority_pair_validation_conflict/offer_select_security_gate_beats_offer_expiry
    """
    agency = create_agency()
    building = create_leased_building(building_name="Low-Posture Plaza",
                                      address="9 Side St",
                                      security_capability=3)
    set_clock("2026-10-01T00:00:00Z")
    req = walk_requirement_to_soliciting(agency)  # required_security_level 4

    offer = get_success_data(api.create_offer(
        req["id"], create_offer_payload(
            building["id"], valid_until="2026-09-15T00:00:00Z"), LESSOR))
    get_success_data(api.evaluate_offer(offer["id"], OFFICER))

    resp = api.select_offer(offer["id"], OFFICER)
    err = validate_error(resp, ApiErrorId.ERR_SECURITY_LEVEL_INSUFFICIENT)
    assert err["error_id"] == "ERR_SECURITY_LEVEL_INSUFFICIENT", (
        "safety (priority 8) beats temporal (priority 9): "
        "never ERR_OFFER_EXPIRED here")

    req_after = validate_success(api.get_space_requirement(req["id"], OFFICER), 200)
    assert req_after["status"] == "SOLICITING"
    leases, meta = validate_paginated(api.list_leases(
        OFFICER, params={"requirement_id": req["id"]}))
    assert leases == [], "no lease is created by the rejected selection"
