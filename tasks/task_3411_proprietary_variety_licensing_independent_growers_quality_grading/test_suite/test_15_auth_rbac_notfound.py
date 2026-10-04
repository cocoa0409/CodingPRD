"""Authentication, role authorization, RBAC denials, and the not-found sweep."""
from test_helpers import (
    validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_variety_payload, create_plant_lot_payload, decide_agreement_payload,
    receive_lot_payload,
    set_clock, create_released_variety, create_grower, apply_for_agreement,
    setup_active_agreement, setup_lot_in_transit,
    make_grower_principal_headers, make_quality_grader_headers,
    get_agreement, get_harvest_lot,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SETTLEMENT = TEST_USERS["settlement_officer_headers"]
NURSERY = TEST_USERS["nursery_manager_headers"]

_NF = {  # non-existent but well-formed UUIDs per resource
    "variety": "00000000-0000-4000-8000-000000000001",
    "grower": "00000000-0000-4000-8000-000000000002",
    "agreement": "00000000-0000-4000-8000-000000000003",
    "plant_lot": "00000000-0000-4000-8000-000000000004",
    "planting": "00000000-0000-4000-8000-000000000005",
    "harvest_lot": "00000000-0000-4000-8000-000000000006",
    "window": "00000000-0000-4000-8000-000000000007",
    "pool": "00000000-0000-4000-8000-000000000008",
    "recall_order": "00000000-0000-4000-8000-000000000009",
}


def test_missing_auth_headers_unauthenticated(api):
    """PRD section 2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming their operational
    capacity. A request missing either header, or carrying a role the system
    does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    set_clock("2026-06-01T00:00:00Z")
    resp = api.create_variety(
        create_variety_payload(variety_code="BRB-STR-99", name="Mystery"), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_authz_role_gate_beats_existence(api):
    """PRD section 2.8: "the system evaluates the following tiers in order and
    reports the first failure encountered" — role authorization (tier 2,
    HTTP 403) precedes existence (tier 4, HTTP 404).
    PRD section 2.8: "a `GrowerPrincipal` attempting to ship a plant lot is
    denied here, because the propagation prohibition is enforced as a role
    boundary."

    Design: Corner/validations/authz_role_gate_beats_existence
    """
    set_clock("2026-06-01T00:00:00Z")
    resp = api.suspend_grower(_NF["grower"],
                              make_quality_grader_headers("qg-9"), {})
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)  # 403, never 404


def test_settlement_officer_cannot_decide_agreement(api):
    """PRD section 2.1: "`ComplianceOfficer` polices the network: it decides
    agreements, suspends and exits growers, and enforces recall orders."
    PRD section 2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/settlement_officer_cannot_decide_agreement
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower()
    agreement = apply_for_agreement(grower, variety)
    resp = api.decide_agreement(agreement["id"],
                                decide_agreement_payload("APPROVE"), SETTLEMENT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_agreement(agreement["id"])["status"] == "PENDING_REVIEW"


def test_grower_cannot_create_plant_lots(api):
    """PRD section 3.4: "No grower-role request can create plant material; a
    `GrowerPrincipal` attempting it is refused with `ERR_FORBIDDEN_ROLE`, which
    is the propagation prohibition made structural."

    Design: Corner/rbac/grower_cannot_create_plant_lots
    """
    set_clock("2026-06-01T00:00:00Z")
    variety, grower, agreement = setup_active_agreement()
    resp = api.create_plant_lot(
        create_plant_lot_payload(agreement["id"], variety["id"],
                                 quantity_plants=100,
                                 nursery_code="FIELD-PROPAGATED"),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    rows, meta = validate_paginated(api.list_plant_lots(
        COMPLIANCE, params={"agreement_id": agreement["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_grader_cannot_receive_lot(api):
    """PRD section 2.1: "`CoolingOperator` records lot receipt and pulp
    temperature at the cooling facility."
    PRD section 2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/grader_cannot_receive_lot
    """
    bundle = setup_lot_in_transit()
    set_clock("2026-10-06T12:30:00Z")
    resp = api.receive_harvest_lot(
        bundle["harvest_lot"]["id"], receive_lot_payload(),
        make_quality_grader_headers("qg-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_harvest_lot(bundle["harvest_lot"]["id"])["lot_status"] == "IN_TRANSIT"


def test_not_found_sweep_all_entities(api):
    """PRD section 2.8: "Every identifier named in the path and in the request
    body must resolve to an existing resource, validated left-to-right: a
    missing variety yields `ERR_VARIETY_NOT_FOUND`, a missing grower
    `ERR_GROWER_NOT_FOUND`, a missing agreement `ERR_AGREEMENT_NOT_FOUND`, a
    missing plant lot `ERR_PLANT_LOT_NOT_FOUND`, a missing planting
    `ERR_PLANTING_NOT_FOUND`, a missing harvest lot `ERR_HARVEST_LOT_NOT_FOUND`,
    and a missing harvest window, pool period, settlement statement, or recall
    order the generic `ERR_NOT_FOUND`."

    Design: Corner/errors/not_found_sweep_all_entities
    """
    set_clock("2026-06-01T00:00:00Z")
    specific = [
        (api.get_variety(_NF["variety"], COMPLIANCE),
         ApiErrorId.ERR_VARIETY_NOT_FOUND),
        (api.suspend_grower(_NF["grower"], COMPLIANCE, {}),
         ApiErrorId.ERR_GROWER_NOT_FOUND),
        (api.get_agreement(_NF["agreement"], COMPLIANCE),
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        (api.get_plant_lot(_NF["plant_lot"], COMPLIANCE),
         ApiErrorId.ERR_PLANT_LOT_NOT_FOUND),
        (api.get_planting(_NF["planting"], COMPLIANCE),
         ApiErrorId.ERR_PLANTING_NOT_FOUND),
        (api.get_harvest_lot(_NF["harvest_lot"], COMPLIANCE),
         ApiErrorId.ERR_HARVEST_LOT_NOT_FOUND),
    ]
    for resp, err_id in specific:
        validate_error(resp, err_id)
    generic = [
        api.get_harvest_window(_NF["window"], COMPLIANCE),
        api.get_pool_period(_NF["pool"], COMPLIANCE),
        api.get_settlement_statement(_NF["pool"], COMPLIANCE),
        api.enforce_recall_order(_NF["recall_order"], COMPLIANCE),
    ]
    for resp in generic:
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
