"""Validations that refuse an operation against a specific structural condition (PRD 2.9-2.11, 3.1-3.6)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, setup_funded_program, build_qualified_household, create_qualification,
    approve_qualification, enroll_bridge_program, setup_referral, create_agent,
    go_live_departing, draft_backup_offer, issue_backup_offer, get_program,
    record_carrying_cost,
    TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]


def test_second_open_referral_for_the_same_scope_is_refused(api):
    """PRD section 3.1: "a program may not hold two simultaneously active referrals for the
    same side of the transaction — a second `OPEN` referral for a `role_scope` already
    covered on that program is refused with `ERR_DUPLICATE_ACTIVE_REFERRAL`."

    Design: Corner/validations/duplicate_active_referral_rejected
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "25 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    setup_referral(bp["id"], qualified=True, role_scope="DEPARTING_SIDE",
                   license_number="LIC-D1")
    second = create_agent(license_number="LIC-D2")
    validate_success(api.qualify_agent(second["id"], COORD), 200)

    res = api.create_referral(
        {"agent_id": second["id"], "bridge_program_id": bp["id"],
         "role_scope": "DEPARTING_SIDE"}, COORD)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_REFERRAL.value, expected_status=409)


def test_backup_offer_on_a_stale_appraisal_is_refused(api):
    """PRD section 3.3: "if more than `APPRAISAL_VALIDITY_DAYS` have passed between the
    property's `appraisal_date` and the logical clock, the funding is refused with
    `ERR_APPRAISAL_STALE`. The same staleness rule guards the guarantee described in §3.6."

    Design: Corner/validations/appraisal_stale_rejected_on_backup_offer
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "27 Def Way", "appraised_value_cents": 50_000_000,
                   "mortgage_payoff_cents": 20_000_000, "condition_grade": "B",
                   "appraisal_date": "2026-01-01T00:00:00Z"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    res = api.create_backup_offer(
        {"departing_property_id": sc["departing"]["id"], "bridge_program_id": bp["id"],
         "offer_price_cents": 44_000_000, "window_days": 30,
         "window_start": "2026-09-01T00:00:00Z"}, COORD)
    validate_error(res, ApiErrorId.ERR_APPRAISAL_STALE.value, expected_status=422)


def test_the_coordinator_that_issued_an_offer_cannot_exercise_it(api):
    """PRD section 2.1: "The `Coordinator` who issued a `BackupOffer` must not be the same
    `Coordinator` who exercises it, which is the only place in the system where two opaque
    operator identifiers are compared to each other. An exercise attempted by the issuing
    operator is rejected with `ERR_SOD_BACKUP_APPROVER` (HTTP 403)."

    Design: Corner/validations/same_issuer_cannot_exercise_backup_offer
    """
    reset_clock()
    sc = setup_funded_program(
        variant="OPTIMISTIC", income_cents=30_000_000,
        departing={"address": "29 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    go_live_departing(sc)
    offer = draft_backup_offer(sc, offer_price_cents=61_000_000, as_user_id="coord-sod-1")
    issued = issue_backup_offer(offer["id"], as_user_id="coord-sod-1")

    from test_helpers import build_user_headers
    res = api.exercise_backup_offer(
        offer["id"], {"expected_backup_offer_version": issued["version"]},
        build_user_headers("coord-sod-1", "Coordinator"))
    validate_error(res, ApiErrorId.ERR_SOD_BACKUP_APPROVER.value, expected_status=403)


def test_a_different_coordinator_may_exercise_the_offer(api):
    """PRD section 2.1: "The `Coordinator` who issued a `BackupOffer` must not be the same
    `Coordinator` who exercises it"

    PRD section 3.9: "Exercising the guarantee is the program acting on its own promise, and
    it is the one operation with a segregation-of-duties guard."

    Design: Corner/validations/same_issuer_cannot_exercise_backup_offer
    """
    reset_clock()
    sc = setup_funded_program(
        variant="OPTIMISTIC", income_cents=30_000_000,
        departing={"address": "29 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    go_live_departing(sc)
    offer = draft_backup_offer(sc, offer_price_cents=61_000_000, as_user_id="coord-sod-1")
    issued = issue_backup_offer(offer["id"], as_user_id="coord-sod-1")

    from test_helpers import build_user_headers
    exercised = validate_success(api.exercise_backup_offer(
        offer["id"], {"expected_backup_offer_version": issued["version"]},
        build_user_headers("coord-sod-2", "Coordinator")), 200)
    assert exercised["status"] == "EXERCISED"


def test_funding_is_refused_when_the_principal_breaches_the_loan_to_value_ceiling(api):
    """PRD section 3.3: "The interim loan principal may not exceed 7500 basis points of the
    new property's appraised value, measured as the principal multiplied by ten thousand and
    divided by the appraisal, all rounded down; a loan that would sit above that
    loan-to-value ceiling is refused with `ERR_LTV_EXCEEDS_LIMIT`."

    Design: Corner/validations/approval_ltv_exceeded_on_fund
    """
    reset_clock()
    # Homeowner equity is large and the income ceiling is set high enough that the clamp does
    # not bind, so the capacity itself breaches the ceiling.
    sc = build_qualified_household(
        income_cents=20_000_000,
        departing={"address": "31 Def Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 0, "condition_grade": "A"},
        new={"address": "32 Def Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="OPTIMISTIC", target_purchase_price_cents=40_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program = get_program(bp["id"])

    res = api.fund_bridge_program(
        bp["id"],
        {"expected_bridge_program_version": program["version"], "interest_rate_bps": 800},
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_LTV_EXCEEDS_LIMIT.value, expected_status=422)
    assert get_program(bp["id"])["advance_status"] == "PENDING", "the program was not funded"