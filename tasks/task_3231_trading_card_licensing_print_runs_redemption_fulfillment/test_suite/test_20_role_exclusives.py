"""Role exclusives at the platform's most gated operations.

Four operations are refused to a role outside their exclusive set, and each
refusal must be the authorization row rather than a later state row.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    build_packed_out_line,
    build_ready_to_ship_allocation,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    make_licensor_approver_headers,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]
ANALYST = TEST_USERS["redemption_analyst_headers"]
DIST = TEST_USERS["distribution_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _set_under_review(api):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    assert submitted["status"] == "UNDER_REVIEW"
    return license_obj, line, submitted


def test_the_licensing_manager_cannot_approve_a_card_set(api):
    """PRD §2.1: "`ProductManager` owns product-line and card-set planning,
    artwork submission, and pack configuration".

    PRD §2.1: "A request whose declared role is not permitted to perform the
    requested operation is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/a_licensing_manager_cannot_approve_a_card_set
    """
    license_obj, line, card_set = _set_under_review(api)
    resp = api.approve_card_set(
        card_set["id"], {"expected_card_set_version": card_set["version"]}, LM
    )
    error_id = validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)["error_id"]
    assert error_id != ApiErrorId.ERR_INVALID_STATE, (
        "authorization precedes the state precondition"
    )


def test_the_refused_approval_leaves_the_set_under_review(api):
    """PRD §3.9: "Every mutating request passes through the same ordered
    validation cascade before its business effect is applied and before any
    side effect lands."

    Design: Corner/rbac/a_licensing_manager_cannot_approve_a_card_set
    """
    license_obj, line, card_set = _set_under_review(api)
    api.approve_card_set(
        card_set["id"], {"expected_card_set_version": card_set["version"]}, LM
    )
    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["status"] == "UNDER_REVIEW"
    assert read["rights_pinned_version"] == 0


def test_the_owning_role_reaches_the_same_operation(api):
    """PRD §2.1: "`ProductManager` owns product-line and card-set planning, artwork
    submission, and pack configuration".

    Design: Corner/rbac/a_licensing_manager_cannot_approve_a_card_set
    """
    license_obj, line, card_set = _set_under_review(api)
    approved = validate_success(
        api.approve_card_set(
            card_set["id"], {"expected_card_set_version": card_set["version"]}, PM
        )
    )
    assert approved["status"] == "APPROVED", "the operation exists for the owning role"


def test_a_product_manager_cannot_decide_artwork(api):
    """PRD §2.1: "The `LicensorApprover` decides the artwork."

    PRD §2.1: "The remaining roles partition the business exclusives".

    Design: Corner/rbac/a_product_manager_cannot_decide_an_artwork_approval
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    artwork = get_success_data(
        api.submit_artwork(
            card_set["id"],
            {
                "artwork_code": "ART-BASE-001",
                "approver_id": license_obj["id"],
                "submitted_on": "2026-08-25T00:00:00Z",
            },
            PM,
        )
    )
    resp = api.decide_artwork(
        artwork["id"],
        {"decision": "APPROVE", "decided_on": "2026-08-26T00:00:00Z"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    read = validate_success(api.get_artwork_approval(artwork["id"], PM))
    assert read["status"] == "SUBMITTED"


def test_the_licensor_identity_is_the_licence_that_holds_the_right(api):
    """PRD §2.1: "When `X-User-Role` is `LicensorApprover`, `X-User-ID` is the
    `id` of the acting `License`."

    Design: Corner/rbac/a_product_manager_cannot_decide_an_artwork_approval
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    artwork = get_success_data(
        api.submit_artwork(
            card_set["id"],
            {
                "artwork_code": "ART-BASE-001",
                "approver_id": license_obj["id"],
                "submitted_on": "2026-08-25T00:00:00Z",
            },
            PM,
        )
    )
    decided = validate_success(
        api.decide_artwork(
            artwork["id"],
            {"decision": "APPROVE", "decided_on": "2026-08-26T00:00:00Z"},
            make_licensor_approver_headers(license_obj["id"]),
        )
    )
    assert decided["status"] == "APPROVED", "the licensor reaches the operation with its own id"
    assert decided["approver_id"] == license_obj["id"], (
        "the licensor identity is entity-backed"
    )


def test_a_quality_analyst_cannot_settle_a_collector_notice(api):
    """PRD §2.1: "`RedemptionFulfilmentAnalyst` issues redemption cards, applies
    the substitution policy and serves collector notices".

    Design: Corner/rbac/a_quality_analyst_cannot_settle_a_redemption_substitution
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    redemption = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-3001",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 400000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    )
    get_success_data(api.set_clock("2029-01-01T00:00:00Z", ADMIN))
    validate_success(api.cancel_redemption(redemption["id"], ANALYST))
    notice = get_success_data(
        api.serve_notification(
            redemption["id"],
            {"notice_code": "SUBST-90", "opened_on": "2029-01-01T00:00:00Z"},
            ANALYST,
        )
    )
    resp = api.settle_notification(
        notice["id"],
        {"redemption_status": "CANCELLED", "compensation_value_equals_scratch": True},
        QA,
    )
    error_id = validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)["error_id"]
    assert error_id != ApiErrorId.ERR_INVALID_STATE, "the role check runs before the state check"
    read = validate_success(api.get_notification(notice["id"], ANALYST))
    assert read["status"] == "ISSUED"


def test_the_redemption_analyst_reaches_the_settlement(api):
    """PRD §3.6: "Settlement is the notice-level act that books the substitution
    credit".

    Design: Corner/rbac/a_quality_analyst_cannot_settle_a_redemption_substitution
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    redemption = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-3002",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 400000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    )
    # Cancellation needs the clock strictly past opened_on + deadline_days and
    # settlement needs it no later than that same instant, so the notice is
    # served one day past the 730-day high-tier deadline and settled at once.
    # SUBSTITUTION_DEADLINE_DAYS_HIGH is 730, so a 2026-09-01 issuance carries a
    # deadline of 2028-08-31 — cancelling exactly at it is past the window while
    # the notice is still inside it.
    # Cancellation requires the clock strictly past the consumer deadline while
    # settlement requires it no later, so the clock steps past and then back.
    redemption_deadline = "2028-08-31T00:00:00Z"
    get_success_data(api.set_clock("2028-09-02T00:00:00Z", ADMIN))
    validate_success(api.cancel_redemption(redemption["id"], ANALYST))
    get_success_data(api.set_clock(redemption_deadline, ADMIN))
    notice = get_success_data(
        api.serve_notification(
            redemption["id"],
            {"notice_code": "SUBST-90", "opened_on": "2026-09-01T00:00:00Z"},
            ANALYST,
        )
    )
    settled = validate_success(
        api.settle_notification(
            notice["id"],
            {"redemption_status": "CANCELLED", "compensation_value_equals_scratch": True},
            ANALYST,
        )
    )
    assert settled["status"] == "SETTLED"


def test_a_distribution_manager_cannot_recall_an_unshipped_allocation(api):
    """PRD §3.8: "It is available from `SHIPPED` and only then
    (`ERR_INVALID_STATE`)."

    PRD §2.1: "`DistributionManager` reserves, ships and recalls channel
    allocations".

    Design: Corner/rbac/a_distribution_manager_cannot_recall_an_allocation_that_has_not_shipped
    """
    scenario = build_ready_to_ship_allocation(api, mark_utf=False)
    resp = api.recall_allocation(scenario["allocation"]["id"], DIST)
    error_id = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)["error_id"]
    assert error_id != ApiErrorId.ERR_FORBIDDEN, (
        "the refusal is the state precondition, not the role"
    )
    after = validate_success(api.get_allocation(scenario["allocation"]["id"], DIST))
    assert after["status"] == "RESERVED"


def test_the_same_role_recalls_successfully_after_shipping(api):
    """PRD §3.8: "Marking an allocation unable-to-fill is a deliberate admission
    that the channel cannot take the stock it reserved."

    Design: Corner/rbac/a_distribution_manager_cannot_recall_an_allocation_that_has_not_shipped
    """
    scenario = build_ready_to_ship_allocation(api, ship=True)
    validate_success(api.recall_allocation(scenario["allocation"]["id"], DIST))
    after = validate_success(api.get_allocation(scenario["allocation"]["id"], DIST))
    assert after["status"] == "RECALLED", "the role was always permitted"


def test_a_line_with_fewer_printed_cases_caps_its_channels(api):
    """PRD §3.8: "The line's capacity is its `cases_printed` multiplied by its
    `sets_per_case`".

    Design: Corner/rbac/a_distribution_manager_cannot_recall_an_allocation_that_has_not_shipped
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"], cases_printed=20)
    validate_success(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 20,
                "effective_price_cents": 72000,
            },
            DIST,
        ),
        expected_status=201,
    )
    validate_error(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "MASS",
                "quantity_allocated": 1,
                "effective_price_cents": 50000,
            },
            DIST,
        ),
        ApiErrorId.ERR_ALLOCATION_EXCEEDS_PRINT_RUN,
    )