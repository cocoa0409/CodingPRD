"""Cross-entity gates: solicitation approval vs branch state; goodwill completion."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    setup_practicing_advisor_with_solicitation,
    setup_retiring_advisor_with_transfer, create_validated_advisor,
    make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_principal_headers"]


def test_approval_blocked_while_branch_suspended_then_succeeds():
    """PRD §3.8: "Then the cross-entity gates: the requesting advisor must be
    `VALIDATED` or `PRACTICING`; the advisor's branch must have
    `operating_status` `OPEN` — which is why suspended branches freeze pending
    solicitations even though the requests stay `SUBMITTED`; and the shelf
    entry for the `product_code` must currently be `APPROVED` (a retirement
    between submission and approval turns the request unapprovable, again
    surfacing `ERR_PRODUCT_NOT_ON_SHELF`)."

    Design: Difficulty/cross_entity_state_dependency/solicitation_approval_gated_by_branch_operating_status
    """
    branch, advisor, entry, request = setup_practicing_advisor_with_solicitation()

    validate_success(api_client.suspend_branch(branch["id"], ADMIN))
    validate_error(
        api_client.approve_solicitation(request["id"], COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE,
    )

    validate_success(api_client.reinstate_branch(branch["id"], ADMIN))
    approved = validate_success(
        api_client.approve_solicitation(request["id"], COMPLIANCE)
    )
    assert approved["status"] == "APPROVED"


def test_approval_blocked_by_advisor_status_after_termination():
    """PRD §3.8: "Then the cross-entity gates: the requesting advisor must be
    `VALIDATED` or `PRACTICING`; the advisor's branch must have
    `operating_status` `OPEN` — which is why suspended branches freeze pending
    solicitations even though the requests stay `SUBMITTED`; and the shelf
    entry for the `product_code` must currently be `APPROVED` (a retirement
    between submission and approval turns the request unapprovable, again
    surfacing `ERR_PRODUCT_NOT_ON_SHELF`)."

    Design: Difficulty/cross_entity_state_dependency/solicitation_approval_gated_by_branch_operating_status
    """
    branch, advisor, entry, request = setup_practicing_advisor_with_solicitation()

    # Terminating the advisor withdraws the SUBMITTED request; approval of the
    # withdrawn request is a state error.
    validate_success(api_client.terminate_advisor(advisor["id"], ADMIN))
    validate_error(
        api_client.approve_solicitation(request["id"], COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_complete_with_qualified_successor_runs_succession_cascade():
    """PRD §3.7: "Completion is the home office's final act on an `ACCEPTED`
    transfer, and it requires the retiring advisor to be `RETIRING` and the
    successor to be `VALIDATED` or `PRACTICING`."
    PRD §3.7: "Completion cascades across four records: the retiring advisor
    moves `RETIRING → RETIRED` with `branch_id` cleared; the successor's
    `branch_id` is set to the transfer's branch and the successor's
    `predecessor_advisor_id` is set to the retiring advisor — this is the only
    path that populates that field, and it stays null for non-succession
    advisors; the branch's staffing moves to `ADVISOR_ASSIGNED` or
    `FULLY_STAFFED` depending on administrator presence; and the escrow
    deposit is applied to the sale, leaving escrow so the transfer's escrow
    balance returns to zero."

    Design: Difficulty/cross_entity_state_dependency/goodwill_complete_gated_by_advisor_statuses
    """
    from test_helpers import create_goodwill_transfer_payload

    # Build a retiring advisor on a branch with trailing revenue, then create
    # the transfer naming a VALIDATED successor.
    transfer, retiring, _candidate, branch = setup_retiring_advisor_with_transfer()
    # The first transfer occupies the branch; cancel it so the corrected
    # transfer can be created cleanly.
    validate_success(api_client.cancel_transfer(transfer["id"], ADMIN))

    successor = create_validated_advisor(
        email="succ-qualified@example.com",
        start_date="2020-01-01T00:00:00Z",
        seed_posted_at="2020-01-02T00:00:00Z",
        eval_window_end="2020-04-01T00:00:00Z",
    )
    transfer = validate_success(api_client.create_goodwill_transfer(
        create_goodwill_transfer_payload(
            branch["id"], retiring["id"], successor["id"],
            valuation_mode="INTERNAL_SUCCESSION", escrow_deposit_cents=200000,
        ),
        ADMIN,
    ), expected_status=201)

    validate_success(
        api_client.accept_transfer(transfer["id"], make_advisor_headers(successor["id"]))
    )
    completed = validate_success(api_client.complete_transfer(transfer["id"], ADMIN))
    assert completed["status"] == "COMPLETED"

    retiring_after = get_success_data(api_client.get_advisor(retiring["id"], ADMIN))
    assert retiring_after["status"] == "RETIRED"
    assert retiring_after["branch_id"] is None

    successor_after = get_success_data(api_client.get_advisor(successor["id"], ADMIN))
    assert successor_after["branch_id"] == branch["id"]
    assert successor_after["predecessor_advisor_id"] == retiring["id"]


def test_complete_requires_retiring_advisor_in_retiring_state():
    """PRD §3.7: "Completion is the home office's final act on an `ACCEPTED`
    transfer, and it requires the retiring advisor to be `RETIRING` and the
    successor to be `VALIDATED` or `PRACTICING`."
    PRD §3.7: "Retirement is revocable: while no goodwill transfer on the
    advisor's branch stands in `ACCEPTED` or `COMPLETED` status, the advisor
    may rescind, returning `RETIRING → PRACTICING` and restoring the branch to
    `ADVISOR_ASSIGNED` or `FULLY_STAFFED` depending on administrator
    presence."

    Design: Difficulty/cross_entity_state_dependency/goodwill_complete_gated_by_advisor_statuses
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer()

    # While the transfer is still OFFERED, rescission is permitted and moves
    # the advisor back to PRACTICING.
    rescinded = validate_success(
        api_client.rescind_retirement(
            retiring["id"], make_advisor_headers(retiring["id"])
        )
    )
    assert rescinded["status"] == "PRACTICING"

    # Successor accepts (escrow 200000 >= 10% of 1800000).
    validate_success(
        api_client.accept_transfer(transfer["id"], make_advisor_headers(successor["id"]))
    )

    # The retiring advisor is now PRACTICING, not RETIRING: complete rejected.
    validate_error(
        api_client.complete_transfer(transfer["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
    )

    transfer_after = get_success_data(
        api_client.get_goodwill_transfer(transfer["id"], ADMIN)
    )
    assert transfer_after["status"] == "ACCEPTED"
