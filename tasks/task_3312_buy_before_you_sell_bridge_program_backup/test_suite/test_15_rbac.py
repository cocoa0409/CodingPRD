"""Role-based access: peer roles cannot perform each other's operations (PRD 2.1)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, setup_funded_program, go_live_departing, draft_backup_offer,
    create_agent, make_homeowner_headers, make_agent_headers, TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]


def test_homeowner_role_cannot_enrol_a_bridge_program(api):
    """PRD section 2.1: "A well-formed request whose role is not permitted on the target
    operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the operations available to a
    role are exactly those enumerated in §4."

    Design: Corner/rbac/homeowner_cannot_create_bridge_program
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "45 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])

    res = api.create_bridge_program(
        {"homeowner_id": sc["homeowner"]["id"], "qualification_id": q["id"],
         "new_property_id": sc["new"]["id"],
         "departing_property_id": sc["departing"]["id"],
         "projected_carry_months": 4},
        make_homeowner_headers(sc["homeowner"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_coordinator_role_may_enrol_the_same_bridge_program(api):
    """PRD section 4: "| POST | `/knock/bridge-programs` | Enrol an approved qualification
    into the bridge program | Coordinator |"

    PRD section 2.1: "The system recognises exactly five roles: `Coordinator`,
    `Underwriter`, `Homeowner`, `Agent`, and `ProgramAdmin`."

    Design: Corner/rbac/homeowner_cannot_create_bridge_program
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "45 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])

    res = api.create_bridge_program(
        {"homeowner_id": sc["homeowner"]["id"], "qualification_id": q["id"],
         "new_property_id": sc["new"]["id"],
         "departing_property_id": sc["departing"]["id"],
         "projected_carry_months": 4},
        COORD,
    )
    program = validate_success(res, 201)
    assert program["advance_status"] == "PENDING"


def test_agent_role_cannot_issue_a_backup_offer(api):
    """PRD section 2.1: "A well-formed request whose role is not permitted on the target
    operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the operations available to a
    role are exactly those enumerated in §4."

    PRD section 4: "| POST | `/knock/backup-offers/{id}/issue` | Issue the backup offer and
    start the exercise window | Coordinator |"

    Design: Corner/rbac/agent_cannot_issue_backup_offer
    """
    reset_clock()
    sc = setup_funded_program(
        variant="OPTIMISTIC", income_cents=30_000_000,
        departing={"address": "47 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    go_live_departing(sc)
    offer = draft_backup_offer(sc, offer_price_cents=61_000_000)
    agent = create_agent(license_number="LIC-RBAC")

    res = api.issue_backup_offer(offer["id"], make_agent_headers(agent["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    still = validate_success(api.get_backup_offer(offer["id"], COORD), 200)
    assert still["status"] == "DRAFT", "the unauthorized call changed nothing"