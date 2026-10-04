"""Authentication, authorization, role scoping, and the 404 error catalogue."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    build_user_headers,
    create_retailer,
    create_route,
    make_retailer_buyer_headers,
    validate_error,
    validate_error_is_one_of,
)
from test_helpers import TEST_USERS

NM = TEST_USERS["network_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]
QM = TEST_USERS["quality_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

FARM_PAYLOAD = {
    "name": "No Auth Farm",
    "region": "IA",
    "pasture_sqft": 21600,
    "barn_sqft": 180,
    "nest_box_count": 30,
    "declared_bird_count": 140,
}


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request that arrives without either header, or whose
    `X-User-Role` value is not one of these six role names, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.create_farm(FARM_PAYLOAD, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_unknown_role_header_returns_401(api):
    """PRD §2.1: "The system recognizes exactly six roles, spelled exactly as
    follows: `PlatformAdmin`, `NetworkManager`, `Auditor`, `QualityManager`,
    `PlantOperator`, and `RetailerBuyer`. A request that arrives without either
    header, or whose `X-User-Role` value is not one of these six role names, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unknown_role_header_returns_401
    """
    resp = api.create_farm(FARM_PAYLOAD, build_user_headers("test-super-1", "SuperUser"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_role_check_precedes_existence_returns_403(api):
    """PRD §2.11: "Authentication comes first: missing or malformed identity
    headers yield `ERR_UNAUTHENTICATED` before anything else is examined, and a
    role that is authenticated but not permitted on the endpoint yields
    `ERR_FORBIDDEN`."
    PRD §2.11: "Only then does the server resolve path and body references left
    to right, returning the appropriate 404."

    Design: Corner/validations/role_check_precedes_existence_returns_403
    """
    retailer = create_retailer()

    # RetailerBuyer is not among the roles permitted on GET /farms/{id}; the
    # authorization check fires before the farm-not-found check.
    resp = api.get_farm(NON_EXISTENT_UUID, make_retailer_buyer_headers(retailer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_rbac_exclusive_operation_denials_return_403(api):
    """PRD §2.1: "A request whose role is authenticated but not listed among the
    roles permitted on the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/rbac_exclusive_operation_denials_return_403
    """
    # QualityManager cannot recruit farms (NetworkManager-only endpoint).
    e1 = api.create_farm(FARM_PAYLOAD, QM)
    validate_error(e1, ApiErrorId.ERR_FORBIDDEN, 403)

    # PlantOperator cannot grade lots (QualityManager-only); 403 precedes 404.
    e2 = api.grade_lot(NON_EXISTENT_UUID, {"quality_score": 90}, PO)
    validate_error(e2, ApiErrorId.ERR_FORBIDDEN, 403)

    # NetworkManager cannot verify corrective actions (Auditor-only).
    e3 = api.verify_corrective_action(NON_EXISTENT_UUID, {"decision": "VERIFY_CLOSED"}, NM)
    validate_error(e3, ApiErrorId.ERR_FORBIDDEN, 403)

    # Auditor cannot create commitments (NetworkManager-only).
    e4 = api.create_commitment(
        {
            "retailer_id": NON_EXISTENT_UUID,
            "farm_id": NON_EXISTENT_UUID,
            "week_start": "2026-09-07",
            "committed_dozens": 10,
        },
        AUDITOR,
    )
    validate_error(e4, ApiErrorId.ERR_FORBIDDEN, 403)


def test_not_found_sweep_parent_resources(api):
    """PRD §2.6: "The request is rejected immediately with the `404` error that
    corresponds to the first identifier that does not resolve —
    `ERR_FARM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CA_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_CARTON_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND`"

    Design: Corner/errors/not_found_sweep_parent_resources
    """
    validate_error(api.get_farm(NON_EXISTENT_UUID, NM), ApiErrorId.ERR_FARM_NOT_FOUND, 404)
    validate_error(api.get_audit(NON_EXISTENT_UUID, NM), ApiErrorId.ERR_AUDIT_NOT_FOUND, 404)
    validate_error(api.get_lot(NON_EXISTENT_UUID, NM), ApiErrorId.ERR_LOT_NOT_FOUND, 404)
    validate_error(api.get_route(NON_EXISTENT_UUID, PO), ApiErrorId.ERR_ROUTE_NOT_FOUND, 404)
    validate_error(
        api.get_commitment(NON_EXISTENT_UUID, NM), ApiErrorId.ERR_COMMITMENT_NOT_FOUND, 404
    )
    validate_error(
        api.get_settlement_run(NON_EXISTENT_UUID, NM), ApiErrorId.ERR_SETTLEMENT_NOT_FOUND, 404
    )


def test_not_found_sweep_child_resources(api):
    """PRD §2.6: "The server resolves the first path identifier before it
    attempts the second: a farm is located before an audit or stop belonging to
    it, a route is located before the `stop_sequence` addressed within it, and a
    lot is located before any carton list beneath it."
    PRD §2.6: "The same existence discipline applies to body references: a
    commitment payload's `retailer_id` and `farm_id` must each resolve to an
    existing record before any business rule is evaluated."
    PRD §3.6: "an unknown code is `ERR_CARTON_NOT_FOUND`"

    Design: Corner/errors/not_found_sweep_child_resources
    """
    route = create_route(route_date="2026-09-08", capacity_cases=4)

    e_ca = api.submit_corrective_action(NON_EXISTENT_UUID, {"evidence_notes": "x"}, NM)
    validate_error(e_ca, ApiErrorId.ERR_CA_NOT_FOUND, 404)

    e_inc = api.resolve_incident(NON_EXISTENT_UUID, {"disposition": "NONE"}, NM)
    validate_error(e_inc, ApiErrorId.ERR_INCIDENT_NOT_FOUND, 404)

    e_ctn = api.get_carton("LOT-999999-C999", NM)
    validate_error(e_ctn, ApiErrorId.ERR_CARTON_NOT_FOUND, 404)

    e_stop = api.collect_stop(
        route["id"], 9,
        {"collected_cases": 1, "laid_start_date": "2026-09-06",
         "laid_end_date": "2026-09-07"},
        PO,
    )
    validate_error(e_stop, ApiErrorId.ERR_STOP_NOT_FOUND, 404)

    # Both body references are bogus; PRD does not pin which of the two is
    # resolved first, only that an unresolved reference yields its 404.
    e_body = api.create_commitment(
        {
            "retailer_id": NON_EXISTENT_UUID,
            "farm_id": NON_EXISTENT_UUID,
            "week_start": "2026-09-07",
            "committed_dozens": 10,
        },
        NM,
    )
    assert e_body.status_code == 404
    validate_error_is_one_of(
        e_body, [ApiErrorId.ERR_RETAILER_NOT_FOUND, ApiErrorId.ERR_FARM_NOT_FOUND]
    )
