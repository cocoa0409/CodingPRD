"""Validation-order pairs: state vs negotiation safety, role vs shelf checks."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    setup_retiring_advisor_with_transfer, create_open_branch,
    create_validated_advisor, create_site_approved_branch, create_advisor,
    create_shelf_entry_payload, create_solicitation_payload,
    make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_principal_headers"]


def test_state_error_wins_on_declined_transfer_counter():
    """PRD §2.5: "More generally, every request passes through the validation
    pipeline in a fixed order. Authentication comes first
    (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`),
    then existence resolution (`ERR_NOT_FOUND`), then state-transition
    legality (`ERR_INVALID_STATE`), then the domain's business-safety,
    business-constraint, temporal, referential, fiscal, and input-shape rules
    in the priority order narrated in §3, with `ERR_INVALID_REQUEST`
    (malformed payloads, invalid enums, out-of-range numbers) acting as the
    final backstop before the stale-version check and remaining temporal and
    staffing rules are evaluated. Where several rules could reject the same
    request, the one named earlier in this pipeline — and, within §3, the one
    narrated first for that operation — determines which error the caller
    sees."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_declined_transfer_counter
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer()

    # Successor counters (last offer by successor), retiring party declines.
    countered = validate_success(api_client.counter_offer(
        transfer["id"],
        {"expected_transfer_version": transfer["version"], "offer_price_cents": 1700000},
        make_advisor_headers(successor["id"]),
    ))
    validate_success(
        api_client.decline_transfer(transfer["id"], make_advisor_headers(retiring["id"]))
    )

    # The successor (who made the last offer, violating alternation too) tries
    # another counter on the terminal DECLINED transfer: state legality is
    # checked before the business-safety alternation rule.
    validate_error(
        api_client.counter_offer(
            transfer["id"],
            {
                "expected_transfer_version": countered["version"],
                "offer_price_cents": 1650000,
            },
            make_advisor_headers(successor["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    fresh = get_success_data(api_client.get_goodwill_transfer(transfer["id"], ADMIN))
    assert fresh["status"] == "DECLINED"
    assert fresh["negotiation_round"] == countered["negotiation_round"] == 1


def test_declined_transfer_rejects_counter_from_either_party():
    """PRD §2.5: "More generally, every request passes through the validation
    pipeline in a fixed order. Authentication comes first
    (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`),
    then existence resolution (`ERR_NOT_FOUND`), then state-transition
    legality (`ERR_INVALID_STATE`), then the domain's business-safety,
    business-constraint, temporal, referential, fiscal, and input-shape rules
    in the priority order narrated in §3, with `ERR_INVALID_REQUEST`
    (malformed payloads, invalid enums, out-of-range numbers) acting as the
    final backstop before the stale-version check and remaining temporal and
    staffing rules are evaluated. Where several rules could reject the same
    request, the one named earlier in this pipeline — and, within §3, the one
    narrated first for that operation — determines which error the caller
    sees."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_declined_transfer_counter
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer()
    validate_success(
        api_client.decline_transfer(transfer["id"], make_advisor_headers(successor["id"]))
    )

    # Retiring advisor (not the last offerer here, so no alternation violation)
    # still gets the state error on the terminal DECLINED transfer.
    validate_error(
        api_client.counter_offer(
            transfer["id"],
            {
                "expected_transfer_version": transfer["version"],
                "offer_price_cents": 1700000,
            },
            make_advisor_headers(retiring["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_solicitation_shelf_then_role_gate():
    """PRD §3.8: "Submission already enforces the shelf rule: the referenced
    code must resolve to an `APPROVED` shelf entry, or the submission is
    rejected with `ERR_PRODUCT_NOT_ON_SHELF`."
    PRD §2.5: "More generally, every request passes through the validation
    pipeline in a fixed order. Authentication comes first
    (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`),
    then existence resolution (`ERR_NOT_FOUND`), then state-transition
    legality (`ERR_INVALID_STATE`), then the domain's business-safety,
    business-constraint, temporal, referential, fiscal, and input-shape rules
    in the priority order narrated in §3, with `ERR_INVALID_REQUEST`
    (malformed payloads, invalid enums, out-of-range numbers) acting as the
    final backstop before the stale-version check and remaining temporal and
    staffing rules are evaluated."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_solicitation_approval
    """
    branch, territory, advisor, boa = create_open_branch()
    entry = get_success_data(api_client.create_shelf_entry(
        create_shelf_entry_payload(complexity_level="COMPLEX", asset_class="ANNUITY"),
        COMPLIANCE,
    ), expected_status=201)

    # While the entry is PROPOSED the shelf rule rejects submission.
    validate_error(
        api_client.create_solicitation_request(
            create_solicitation_payload(advisor["id"], entry["product_code"]),
            make_advisor_headers(advisor["id"]),
        ),
        ApiErrorId.ERR_PRODUCT_NOT_ON_SHELF,
    )

    # Once APPROVED the submission succeeds.
    validate_success(api_client.approve_shelf_entry(entry["id"], COMPLIANCE))
    request = validate_success(
        api_client.create_solicitation_request(
            create_solicitation_payload(advisor["id"], entry["product_code"]),
            make_advisor_headers(advisor["id"]),
        ),
        expected_status=201,
    )

    # Approval by the Advisor role is stopped by role authorization, which
    # precedes both the safety and referential checks.
    validate_error(
        api_client.approve_solicitation(
            request["id"], make_advisor_headers(advisor["id"])
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    fresh = get_success_data(
        api_client.list_advisor_solicitation_requests(
            advisor["id"], make_advisor_headers(advisor["id"])
        )
    )
    assert all(r["status"] == "SUBMITTED" for r in fresh)


def test_unapproved_shelf_entry_rejected_before_approval_step():
    """PRD §3.8: "Submission already enforces the shelf rule: the referenced
    code must resolve to an `APPROVED` shelf entry, or the submission is
    rejected with `ERR_PRODUCT_NOT_ON_SHELF`."
    PRD §2.5: "More generally, every request passes through the validation
    pipeline in a fixed order. Authentication comes first
    (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`),
    then existence resolution (`ERR_NOT_FOUND`), then state-transition
    legality (`ERR_INVALID_STATE`), then the domain's business-safety,
    business-constraint, temporal, referential, fiscal, and input-shape rules
    in the priority order narrated in §3, with `ERR_INVALID_REQUEST`
    (malformed payloads, invalid enums, out-of-range numbers) acting as the
    final backstop before the stale-version check and remaining temporal and
    staffing rules are evaluated."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_solicitation_approval
    """
    branch, territory, advisor, boa = create_open_branch()
    entry = get_success_data(api_client.create_shelf_entry(
        create_shelf_entry_payload(complexity_level="COMPLEX", asset_class="ANNUITY"),
        COMPLIANCE,
    ), expected_status=201)
    validate_success(api_client.approve_shelf_entry(entry["id"], COMPLIANCE))
    request = validate_success(
        api_client.create_solicitation_request(
            create_solicitation_payload(advisor["id"], entry["product_code"]),
            make_advisor_headers(advisor["id"]),
        ),
        expected_status=201,
    )

    # A fully authorized principal approves the request.
    approved = validate_success(
        api_client.approve_solicitation(request["id"], COMPLIANCE)
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_role"] == "CompliancePrincipal"
