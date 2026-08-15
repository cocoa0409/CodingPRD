"""Authentication, authorization, ownership, and the not-found error catalog."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_approved_request,
    create_home_payload,
    file_service_request,
    setup_home,
    setup_issued_chargeback,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    assess_warrantable_payload,
    create_work_order_payload,
)
from test_helpers.test_users import TEST_USERS, make_homeowner_headers, make_trade_partner_headers

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_create_home_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.7: "Authentication: `X-User-ID` and `X-User-Role` are present and the
    role is declared, else `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/create_home_missing_auth_header_unauthenticated
    """
    resp = api.create_home(
        create_home_payload(
            NON_EXISTENT_UUID,
            lot_number="L-931",
            community_name="Cedar Ridge",
            sale_price_cents=40_000_000,
            closing_date="2026-06-01",
            warranty_program="STANDARD",
        ),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_assess_as_homeowner_forbidden(api):
    """PRD §2.1: "A request whose role is recognized but not listed among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the assess endpoint authorizes only WarrantyRep.

    Design: Corner/validations/assess_as_homeowner_forbidden
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    request = file_service_request(
        home["id"], homeowner["id"], item_category="HVAC", description="AC out"
    )
    # The caller IS the owning homeowner; the role gate still fires first.
    resp = api.assess_service_request(
        request["id"],
        assess_warrantable_payload(),
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_cross_role_exclusive_denials(api):
    """PRD §2.1: "A request whose role is recognized but not listed among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "Duties are segregated across the opaque roles: representatives run
    triage, dispatch, follow-up, chargeback issuance, and claim filing; the
    manager holds master data, dispute resolution, chargeback approval and
    resolution, the operations checkpoint, and the clock; finance posts reserve
    adjustments and applies chargeback cash; the external administrator decides
    structural claims. The roles that issue a chargeback, approve or resolve it,
    and apply its payments are three different roles."

    Design: Corner/rbac/cross_role_exclusive_denials
    """
    ctx = setup_issued_chargeback(estimated_cost_cents=110_000)

    e1 = api.follow_up_service_request(
        ctx["request"]["id"],
        {"satisfaction_score": 4},
        make_trade_partner_headers(ctx["partner"]["id"]),
    )
    validate_error(e1, ApiErrorId.ERR_FORBIDDEN)

    e2 = api.complete_work_order(
        ctx["work_order"]["id"], {"actual_cost_cents": 110_000}, MANAGER
    )
    validate_error(e2, ApiErrorId.ERR_FORBIDDEN)

    e3 = api.approve_chargeback(ctx["chargeback"]["id"], {}, FINANCE)
    validate_error(e3, ApiErrorId.ERR_FORBIDDEN)

    e4 = api.record_payment(ctx["chargeback"]["id"], {"amount_cents": 1_000}, REP)
    validate_error(e4, ApiErrorId.ERR_FORBIDDEN)

    work_order = validate_success(api.get_work_order(ctx["work_order"]["id"], REP), 200)
    chargeback = validate_success(api.get_chargeback(ctx["chargeback"]["id"], REP), 200)
    assert work_order["status"] == "SCHEDULED", "forbidden calls change no state"
    assert chargeback["status"] == "ISSUED"


def test_not_found_catalog_sweep(api):
    """PRD §2.7: "Identifier resolution: path and body identifiers resolve in a
    fixed left-to-right order — home, then service request, then work order, then
    trade partner, then chargeback, then warranty reserve, then administrator
    claim, and finally homeowner references (the `homeowner_id` on a home-creation
    payload, or the homeowner path id on a homeowner fetch). The first
    unresolvable identifier produces its own 404: `ERR_HOME_NOT_FOUND`,
    `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_TRADE_PARTNER_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND`,
    `ERR_RESERVE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or
    `ERR_HOMEOWNER_NOT_FOUND`."

    Design: Corner/errors/not_found_catalog_sweep
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    request = create_approved_request(
        home["id"], homeowner["id"], description="Leak"
    )

    checks = [
        (api.get_homeowner(NON_EXISTENT_UUID, MANAGER),
         ApiErrorId.ERR_HOMEOWNER_NOT_FOUND),
        (api.get_home(NON_EXISTENT_UUID, MANAGER),
         ApiErrorId.ERR_HOME_NOT_FOUND),
        (api.get_service_request(NON_EXISTENT_UUID, REP),
         ApiErrorId.ERR_SERVICE_REQUEST_NOT_FOUND),
        (api.get_work_order(NON_EXISTENT_UUID, REP),
         ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
        (api.get_chargeback(NON_EXISTENT_UUID, REP),
         ApiErrorId.ERR_CHARGEBACK_NOT_FOUND),
        (api.get_warranty_reserve(NON_EXISTENT_UUID, FINANCE),
         ApiErrorId.ERR_RESERVE_NOT_FOUND),
        (api.get_administrator_claim(NON_EXISTENT_UUID, REP),
         ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ]
    for resp, error_id in checks:
        validate_error(resp, error_id)

    # Body-position existence: the trade partner reference on dispatch.
    resp = api.create_work_order(
        create_work_order_payload(
            request["id"],
            NON_EXISTENT_UUID,
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T11:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        ),
        REP,
    )
    validate_error(resp, ApiErrorId.ERR_TRADE_PARTNER_NOT_FOUND)
