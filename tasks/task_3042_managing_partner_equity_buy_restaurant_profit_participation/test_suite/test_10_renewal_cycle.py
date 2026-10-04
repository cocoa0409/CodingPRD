"""Contract renewal cycle tests: repeated cyclic renewals extend the term,
and the expiry sweep must not fire between cycles."""
from test_helpers import (
    validate_success,
    setup_active_contract,
    set_clock,
    make_managing_partner_headers,
    TEST_USERS,
)

CONTROLLER = TEST_USERS["corporate_controller_headers"]


def test_renewal_cycle_extends_term_twice(api):
    """PRD §3.4: "Acceptance moves the contract back to `ACTIVE`, extends
    `term_end_date` by 2 years, and increments `renewed_count` by 1. This loop
    is cyclic and unbounded — renewal may be offered and accepted repeatedly,
    and `renewed_count` grows without limit."
    PRD §2.10: "An accepted renewal extends the contract term by 2 years."

    Design: Difficulty/non_linear_state_machine/contract_renewal_cycle_extends_term_repeatedly
    """
    setup = setup_active_contract(term_start_date="2027-01-01", term_end_date="2032-01-01")
    partner_headers = make_managing_partner_headers(setup["partner"]["id"])
    set_clock("2031-06-01T00:00:00Z")
    validate_success(api.offer_renewal(setup["contract"]["id"], CONTROLLER))
    validate_success(api.accept_renewal(setup["contract"]["id"], partner_headers))
    validate_success(api.offer_renewal(setup["contract"]["id"], CONTROLLER))
    accepted = validate_success(api.accept_renewal(setup["contract"]["id"], partner_headers))
    assert accepted["renewed_count"] == 2
    assert accepted["term_end_date"] == "2036-01-01"
    assert accepted["status"] == "ACTIVE"


def test_renewal_cycle_holds_past_original_term_end(api):
    """PRD §3.4: "Whether a contract is `ACTIVE` or `RENEWAL_OFFERED`, once the
    logical clock's date reaches the `term_end_date`, the sweep moves the
    contract to `EXPIRED` and returns the partner from `PLACED` to `CERTIFIED`,
    clearing their placement."
    PRD §3.4: "Acceptance moves the contract back to `ACTIVE`, extends
    `term_end_date` by 2 years, and increments `renewed_count` by 1."

    Design: Difficulty/non_linear_state_machine/contract_renewal_cycle_extends_term_repeatedly
    """
    setup = setup_active_contract(term_start_date="2027-01-01", term_end_date="2032-01-01")
    partner_headers = make_managing_partner_headers(setup["partner"]["id"])
    set_clock("2031-06-01T00:00:00Z")
    validate_success(api.offer_renewal(setup["contract"]["id"], CONTROLLER))
    validate_success(api.accept_renewal(setup["contract"]["id"], partner_headers))
    validate_success(api.offer_renewal(setup["contract"]["id"], CONTROLLER))
    validate_success(api.accept_renewal(setup["contract"]["id"], partner_headers))
    # Past the ORIGINAL term end (2032-01-01): the extended term keeps it alive.
    set_clock("2033-06-01T00:00:00Z")
    fetched = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    assert fetched["status"] == "ACTIVE"
    assert fetched["renewed_count"] == 2
    assert fetched["term_end_date"] == "2036-01-01"
