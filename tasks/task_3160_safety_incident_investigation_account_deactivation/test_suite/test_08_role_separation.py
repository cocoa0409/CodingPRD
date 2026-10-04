"""Role separation: the operations each role holds exclusively, and the
operation-layer enforcement of the appeal team's independence."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_account,
    get_incident,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_incident_in_state,
    setup_policy,
    validate_error,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]


def test_withdrawal_belongs_to_the_operations_lead_alone(api):
    """PRD §4: "the authorized roles column below is exhaustive: a role that is not listed for
    an operation is refused with `ERR_UNAUTHORIZED`."
    PRD §3.2: "Withdrawal belongs to a `SafetyOperationsLead` and is available only while the
    incident's `decision_category` is still `PENDING` and its severity is `S1` or `S2`"

    Design: Corner/rbac/role_exclusivity_investigator_cannot_withdraw_and_lead_cannot_decide
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="cato.reyes")
    low = make_incident(account["id"], incident_category="PROPERTY_DAMAGE")
    set_clock("2026-10-01T00:00:00Z")

    res = api_client.withdraw_incident(low["id"], INVESTIGATOR)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert res.status_code == 403
    assert get_incident(low["id"])["incident_status"] == "OPEN", (
        "the refused withdrawal performs no transition"
    )

    allowed = get_success_data(api_client.withdraw_incident(low["id"], OPERATIONS_LEAD))
    assert allowed["incident_status"] == "WITHDRAWN", (
        "the operation succeeds for the role that holds it exclusively"
    )


def test_decision_belongs_to_the_investigator_alone(api):
    """PRD §4: "the authorized roles column below is exhaustive: a role that is not listed for
    an operation is refused with `ERR_UNAUTHORIZED`."
    PRD §3.4: "A `SafetyInvestigator` commits it once the incident sits at `PENDING_DECISION`"

    Design: Corner/rbac/role_exclusivity_investigator_cannot_withdraw_and_lead_cannot_decide
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="cato.reyes.lead")
    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    frozen = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))

    res = api_client.commit_decision(
        incident["id"],
        {
            "decision_category": "DEACTIVATED",
            "decision_basis": "S4 physical assault with a platform record and a law-enforcement contact on file.",
            "expected_incident_version": frozen["version"],
        },
        OPERATIONS_LEAD,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert res.status_code == 403

    assert get_incident(incident["id"])["incident_status"] == "PENDING_DECISION"
    assert get_account(account["id"])["status"] == "PENDING_DECISION"
    assert get_success_data(
        api_client.list_account_enforcement_actions(account["id"], OPERATIONS_LEAD)
    ) == [], "no enforcement action row exists after the refusal"


def test_appeal_reviewer_cannot_commit_a_decision(api):
    """PRD §2.1: "`SafetyInvestigator` and `SafetyAppealReviewer` therefore hold disjoint
    exclusive operations across the decision and appeal surfaces."
    PRD §4: "the authorized roles column below is exhaustive: a role that is not listed for an
    operation is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/role_appeal_reviewer_cannot_file_a_decision_on_any_incident
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="dario.nunes")
    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    frozen = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))

    res = api_client.commit_decision(
        incident["id"],
        {
            "decision_category": "RESTRICTED",
            "decision_basis": "Appeal reviewer attempting to commit the primary decision rather than review it.",
            "expected_incident_version": frozen["version"],
        },
        APPEAL_REVIEWER,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert res.status_code == 403

    after = get_incident(incident["id"])
    assert after["incident_status"] == "PENDING_DECISION"
    assert after.get("decision_maker_user_id") is None, (
        "the refused decision records no deciding operator"
    )


def test_appeal_against_an_undecided_incident_is_refused(api):
    """PRD §3.6: "The gate is a conjunction: the incident must sit at `DECIDED`, the region
    must hold exactly one appeal-eligible record for it, and the filing instant must be
    **strictly before** the linked enforcement action's `appeal_deadline_at`"
    PRD §3.6: "An account that has been deactivated through an incident whose
    `decision_category` is `DEACTIVATED` may appeal"

    Design: Corner/rbac/role_appeal_reviewer_cannot_file_a_decision_on_any_incident
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account = setup_account(account_type="DRIVER", handle="dario.nunes.early")
    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    assert get_incident(incident["id"])["incident_status"] == "PENDING_DECISION"

    res = api_client.file_appeal(incident["id"], APPEAL_REVIEWER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    assert get_incident(incident["id"])["incident_status"] == "PENDING_DECISION", (
        "the appeal gate is a state gate as well as an operation gate, and the two fail "
        "with different errors"
    )
    assert get_account(account["id"])["status"] == "PENDING_DECISION"