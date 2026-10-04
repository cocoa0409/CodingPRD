"""Orders of refusal when a request violates more than one rule (PRD section 2.11)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, fund_program, record_carrying_cost, create_advance,
    approve_advance, disburse_advance, get_loan, setup_referral, create_agent,
    suspend_agent, make_homeowner_headers, complete_repairs, occupy_new_home,
    TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_repayment_on_an_undrawn_loan_is_refused_as_a_state_error(api):
    """PRD section 2.11: "State-appropriateness is judged before money: a resource that is
    not in a state from which the requested transition is declared is refused with
    `ERR_INVALID_STATE` before any economic check runs"

    PRD section 2.11: "a request that is both mistimed and over-budget is refused as
    mistimed, and an implementation that evaluates the economic checks first will surface
    the wrong error to the client."

    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_carrying_cost
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "19 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "20 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])
    # An unpaid carrying cost the fiscal check would also trip.
    record_carrying_cost(program["id"], "DEPARTING_TAX", 500_000,
                         due_date="2026-10-01T00:00:00Z")

    res = api.post_repayment(
        loan["id"],
        {"amount_cents": 1, "expected_interim_loan_version": loan["version"]},
        make_homeowner_headers(sc["homeowner"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    still = get_loan(loan["id"])
    assert still["status"] == "ORIGINATED", "no repayment path reaches an ORIGINATED loan"


def test_small_repayment_is_not_blocked_by_an_unpaid_carrying_cost(api):
    """PRD section 3.5: "A payment strictly smaller than the sum of the loan's
    `outstanding_principal_cents` and `accrued_interest_cents` reduces principal,
    recomputes interest and puts the loan in `REPAYING`."

    PRD section 3.5: "A final repayment may not be posted while the program's
    `outstanding_carrying_cost_cents` is anything but zero — the carrying costs must be
    cleared first"

    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_carrying_cost
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "19 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "20 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])
    record_carrying_cost(program["id"], "DEPARTING_TAX", 500_000,
                         due_date="2026-10-01T00:00:00Z")
    advance = disburse_advance(approve_advance(
        create_advance(program["id"], loan["id"], "DOWN_PAYMENT", 8_000_000)["id"])["id"])
    drawn = get_loan(loan["id"])
    assert drawn["status"] == "DRAWN"

    repaid = validate_success(api.post_repayment(
        loan["id"],
        {"amount_cents": 100_000, "expected_interim_loan_version": drawn["version"]},
        make_homeowner_headers(sc["homeowner"]["id"])), 200)
    assert repaid["status"] == "REPAYING", "a partial repayment is not a settlement attempt"
    assert advance["status"] == "DISBURSED"


def _stale_appraisal_scenario(api, grade: str = "C"):
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "21 Departing Way", "appraised_value_cents": 50_000_000,
                   "mortgage_payoff_cents": 20_000_000, "condition_grade": grade,
                   "appraisal_date": "2026-01-01T00:00:00Z"},
        new={"address": "22 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="OPTIMISTIC", target_purchase_price_cents=40_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program = validate_success(
        api.get_bridge_program(bp["id"], COORD), 200)
    return sc, program


def test_offer_below_the_price_floor_outranks_a_stale_appraisal(api):
    """PRD section 2.11: "Only after the state checks pass does the server evaluate the
    lender's credit floor, the loan-to-value ceiling, the regulatory price floor, the draw
    headroom, the repair ceiling, the carrying-cost settlement condition and the
    reconciliation rules of §3."

    PRD section 2.11: "Referenced resources are resolved next, in the left-to-right order
    of §2.6, so a 404 always outranks a 409 or a 422 on the same request."

    Design: Difficulty/priority_pair_validation_conflict/safety_over_constraint_appraisal
    """
    reset_clock()
    sc, program = _stale_appraisal_scenario(api, "C")
    # floor = max(50% * 0.88 * 0.955, 50% * 0.85); the regulatory floor binds on a C home.
    res = api.create_backup_offer(
        {"departing_property_id": sc["departing"]["id"], "bridge_program_id": program["id"],
         "offer_price_cents": 42_000_000, "window_days": 30,
         "window_start": "2026-09-01T00:00:00Z"}, COORD)
    validate_error(res, ApiErrorId.ERR_REGULATORY_PRICE_FLOOR.value, expected_status=422)


def test_price_basis_uses_the_discounted_floor_for_a_well_conditioned_home(api):
    """PRD section 3.6: "no modifier at all for a home graded `A`, 200 basis points for one
    graded `B`, 450 for one graded `C` and 600 for one graded `D`, again flooring."

    Design: Difficulty/priority_pair_validation_conflict/safety_over_constraint_appraisal
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "31 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 0, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="OPTIMISTIC", target_purchase_price_cents=40_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    offer = validate_success(api.create_backup_offer(
        {"departing_property_id": sc["departing"]["id"], "bridge_program_id": bp["id"],
         "offer_price_cents": 62_000_000, "window_days": 30,
         "window_start": "2026-09-01T00:00:00Z"}, COORD), 201)
    # 70% less 12% is 61600000, and a grade-A home carries no condition modifier, so the
    # discounted floor 61600000 exceeds the 8500-bps regulatory floor of 59500000.  The
    # offer is written above that floor, as the PRD requires.
    assert offer["price_basis_cents"] == 61_600_000
    assert offer["offer_price_cents"] == 62_000_000


def test_referral_against_a_suspended_agent_outranks_the_duplicate_scope_rule(api):
    """PRD section 2.11: "Authentication is settled first: a request without usable
    credentials is refused with `ERR_UNAUTHENTICATED`, and only a request that survives that
    check is examined for role permission and then for the segregation-of-duties rule that
    guards the exercise of a backup offer."

    PRD section 3.1: "First, the partner must be usable at that moment: an agent whose
    `qualification_status` is `SUSPENDED` cannot be the subject of a new referral, and the
    attempt is refused with `ERR_AGENT_NOT_QUALIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_over_fiscal_referral
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "23 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    # A good agent already holds the DEPARTING_SIDE scope on this program.
    setup_referral(bp["id"], qualified=True, role_scope="DEPARTING_SIDE",
                   license_number="LIC-GOOD")
    # A second agent is suspended and would also duplicate that scope.
    bad = create_agent(license_number="LIC-BAD")
    suspend_agent(bad["id"])

    res = api.create_referral(
        {"agent_id": bad["id"], "bridge_program_id": bp["id"],
         "role_scope": "DEPARTING_SIDE"}, COORD)
    validate_error(res, ApiErrorId.ERR_AGENT_NOT_QUALIFIED.value, expected_status=422)


def test_a_program_still_refuses_a_second_open_referral_for_the_same_side(api):
    """PRD section 3.8: "The pools are consumed per approval and do not carry across
    advances, so each approval starts from full pools."

    PRD section 3.1: "Second, a program may not hold two simultaneously active referrals
    for the same side of the transaction — a second `OPEN` referral for a `role_scope`
    already covered on that program is refused with `ERR_DUPLICATE_ACTIVE_REFERRAL`."

    Design: Difficulty/priority_pair_validation_conflict/referential_over_fiscal_referral
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "23 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    setup_referral(bp["id"], qualified=True, role_scope="DEPARTING_SIDE",
                   license_number="LIC-D1")
    second_agent = create_agent(license_number="LIC-D2")
    validate_success(api.qualify_agent(second_agent["id"], COORD), 200)

    res = api.create_referral(
        {"agent_id": second_agent["id"], "bridge_program_id": bp["id"],
         "role_scope": "DEPARTING_SIDE"}, COORD)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_REFERRAL.value, expected_status=409)