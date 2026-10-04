"""Error catalog sweep: every resource-specific 404 fires on its own
endpoint with a well-formed but unknown identifier (PRD §2.9 step 3, §5)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_dealer,
    make_dealer_headers,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def test_not_found_sweep_returns_resource_specific_404(api):
    """PRD §2.9 step 3: "resource existence — URL path identifiers are
    resolved left to right, and body foreign keys (`end_user_id`,
    `volume_agreement_id`, `configuration_id`, `installation_phase_id`,
    `project_order_id`) resolve as well, with a missing identifier yielding
    the referenced resource's not-found error: `ERR_DEALER_NOT_FOUND`,
    `ERR_END_USER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_PRODUCT_FAMILY_NOT_FOUND`, `ERR_CONFIGURATION_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
    `ERR_PUNCH_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`".

    Design: Corner/errors/errors_not_found_sweep_returns_404
    """
    dealer = create_dealer(api)
    dealer_h = make_dealer_headers(dealer["id"])

    resp = api.update_dealer(
        NON_EXISTENT_UUID, {"service_capability_level": 5}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DEALER_NOT_FOUND)

    resp = api.create_volume_agreement(
        {
            "end_user_id": NON_EXISTENT_UUID,
            "effective_start": "2026-01-01",
            "effective_end": "2027-12-31",
            "tier1_discount_pct": 0.10,
            "tier2_discount_pct": 0.15,
            "tier3_discount_pct": 0.20,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_END_USER_NOT_FOUND)

    resp = api.get_volume_agreement(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)

    resp = api.update_product_family(
        NON_EXISTENT_UUID,
        {"lifecycle_status": "SUNSETTING", "last_order_date": "2026-12-31"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_FAMILY_NOT_FOUND)

    resp = api.start_install(NON_EXISTENT_UUID, dealer_h)
    validate_error(resp, ApiErrorId.ERR_PHASE_NOT_FOUND)

    resp = api.cancel_install_window(NON_EXISTENT_UUID, dealer_h)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_FOUND)

    resp = api.resolve_punch_ticket(
        NON_EXISTENT_UUID, {"resolution_note": "x"}, dealer_h
    )
    validate_error(resp, ApiErrorId.ERR_PUNCH_NOT_FOUND)

    resp = api.review_warranty_claim(
        NON_EXISTENT_UUID, {"decision": "APPROVE"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)
