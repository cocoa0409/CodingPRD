"""Role authorisation on the configuration surface and on the approval chain."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_unset,
    create_desk_policy_with_matrix,
    decide_step,
    get_success_data,
    latest_approval_request,
    pending_step_of_request,
    read_quote,
    read_step,
    setup_submitted_quote,
    step_decision_payload,
    validate_error,
    USER_IDS,
)


def test_a_sales_rep_cannot_activate_a_desk_policy_revision(
    api, base, rep_headers, admin_headers
):
    """PRD §2.1: "If both headers are present but `X-User-Role` is not one of the roles authorised
    for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.1: "A revision only becomes law when a `PlatformAdmin` activates it, driving `status`
    from `DRAFT` to `ACTIVE`."

    Design: Corner/rbac/sales_rep_cannot_activate_a_desk_policy
    """
    draft = create_desk_policy_with_matrix(
        api, activate=False, tiers=(), name="FY27 Rep Attempt"
    )["policy"]
    assert draft["status"] == "DRAFT"

    validate_error(
        api.activate_desk_policy(draft["id"], rep_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    unchanged = get_success_data(api.get_desk_policy(draft["id"], admin_headers))
    assert unchanged["status"] == "DRAFT"
    assert_unset(unchanged, "activated_at")

    still_live = get_success_data(api.get_desk_policy(base["policy"]["id"], admin_headers))
    assert still_live["status"] == "ACTIVE"


def test_legal_counsel_cannot_decide_a_discount_approval_step(
    api, base, rep_headers, legal_headers, analyst_headers
):
    """PRD §2.1: "If both headers are present but `X-User-Role` is not one of the roles authorised
    for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`LegalCounsel` reviews non-standard terms and owns the terms track of the approval
    fork."

    Design: Corner/rbac/legal_counsel_cannot_decide_an_approval_step
    """
    scenario = setup_submitted_quote(
        api, base, [("support", 10, 0.20)], 12, rep_headers,
        title="Northwind Legal Overreach", payment_terms_days=30,
    )
    assert scenario["quote"]["status"] == "PENDING_APPROVAL"
    assert scenario["quote"]["required_approval_level"] == 2

    step = scenario["step"]
    assert step["level"] == 1
    assert step["assigned_role"] == "DealDeskAnalyst"

    validate_error(
        api.decide_approval_step(
            step["id"],
            step_decision_payload("APPROVE", "Legal signing off on pricing"),
            legal_headers,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    untouched = read_step(api, step["id"], analyst_headers)
    assert untouched["decision"] == "PENDING"
    assert_unset(untouched, "acting_user_id")


def test_the_analyst_cannot_decide_the_director_level_step_it_created(
    api, base, rep_headers, analyst_headers, director_headers
):
    """PRD §2.10: "A user who neither holds the step's own `assigned_role` nor holds a matching
    grant is refused with `ERR_APPROVER_ROLE_MISMATCH` (HTTP 403)."
    PRD §2.10: "And the grant must match the step: its `tier_level` must equal the step's `level`
    and its `grantee_user_id` must equal the acting `X-User-ID`."

    Design: Corner/rbac/analyst_cannot_decide_a_director_level_step_without_a_delegation_grant
    """
    scenario = setup_submitted_quote(
        api, base, [("support", 10, 0.20)], 12, rep_headers,
        title="Northwind Chain Discipline", payment_terms_days=30,
    )
    assert scenario["quote"]["status"] == "PENDING_APPROVAL"
    assert scenario["quote"]["final_blended_discount_pct"] == pytest.approx(0.200000, abs=1e-9)

    first = decide_step(
        api, scenario["step"]["id"], "APPROVE", analyst_headers, "Desk review complete"
    )
    assert first["decision"] == "APPROVED"

    second = pending_step_of_request(api, scenario["request"]["id"], analyst_headers)
    assert second["level"] == 2
    assert second["assigned_role"] == "SalesDirector"

    validate_error(
        api.decide_approval_step(
            second["id"],
            step_decision_payload("APPROVE", "Analyst self-escalating"),
            analyst_headers,
        ),
        ApiErrorId.ERR_APPROVER_ROLE_MISMATCH,
        403,
    )

    cleared = decide_step(api, second["id"], "APPROVE", director_headers, "Director approves")
    assert cleared["decision"] == "APPROVED"
    assert cleared["acting_user_id"] == USER_IDS["director"]
    assert_unset(cleared, "delegation_grant_id")

    assert read_quote(api, scenario["quote"]["id"], rep_headers)["status"] == "APPROVED"
    assert latest_approval_request(api, scenario["quote"]["id"], rep_headers)["status"] == "APPROVED"
