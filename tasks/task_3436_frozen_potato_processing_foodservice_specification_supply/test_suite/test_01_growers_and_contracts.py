"""Grower registry and crop-contract lifecycle: creation shape, computed
volume, pagination, not-found behavior, activation idempotency, the amendment
OCC gate, and the delivery-window overlap rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_crop_contract,
    assert_grower,
    create_amendment_payload,
    create_crop_contract_payload,
    create_grower_payload,
    deliver_lot,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_active_contract,
    make_contract,
    make_grower,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

GRM = TEST_USERS["grower_relations_manager_headers"]
ACCOUNT = TEST_USERS["account_manager_headers"]


def test_grower_create_returns_201_with_system_fields_and_version_1(api):
    """PRD §4: "Operations that create a new resource return `201 Created`;
    operations that modify an existing resource — state transitions, readings,
    delivery recording, allocation execution, and the logical-clock set —
    return `200 OK`."
    PRD §2.4: "`id` (string): a server-minted UUID with no type prefix,
    assigned at creation."
    PRD §2.4: "`version` (integer): a system-managed integer that increments
    by exactly one on every mutation of the resource, including mutations
    driven by system cascades, derived-field reconciliation, and automatic
    state transitions — not only client-initiated writes."

    Design: Corner/entities/grower_create_returns_201_with_system_fields_and_version_1
    """
    set_clock(api=api)
    resp = api.create_grower(create_grower_payload(), GRM)
    body = resp.json()
    data = validate_success(resp, 201)
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"
    assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", ""))
    assert_grower(data)
    assert data["grower_code"] == "GR-100"
    assert data["legal_name"] == "Columbia Basin Farms LLC"
    assert data["region"] == "COLUMBIA_BASIN"
    assert data["version"] == 1, f"fresh grower must carry version 1, got {data['version']}"
    assert is_valid_uuid(data["id"])


def test_crop_contracts_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
    maximum of 100. The `offset` parameter specifies how many items to skip
    and defaults to 0."
    PRD §2.3: "List responses carry four pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §3.1: "The contracts list can be filtered by `grower_id`, `status`,
    and `variety`."

    Design: Corner/entities/crop_contracts_list_paginates_with_total_count_and_has_more
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    # Three varieties -> identical windows may coexist (the overlap check is
    # scoped to grower+variety).
    for variety in ("RUSSET_BURBANK", "RANGER_RUSSET", "UMATILLA_RUSSET"):
        make_contract(grower["id"], api=api, variety=variety)

    page1 = api.list_crop_contracts(ACCOUNT, params={"grower_id": grower["id"], "limit": 2, "offset": 0})
    data1, meta1 = validate_paginated(page1)
    assert len(data1) == 2, f"page 1 must hold 2 rows, got {len(data1)}"
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2 = api.list_crop_contracts(ACCOUNT, params={"grower_id": grower["id"], "limit": 2, "offset": 2})
    data2, meta2 = validate_paginated(page2)
    assert len(data2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False

    default_page = api.list_crop_contracts(ACCOUNT, params={"grower_id": grower["id"]})
    data_default, meta_default = validate_paginated(default_page)
    assert len(data_default) == 3, "default page (limit 10) must return all 3 rows"

    filtered = api.list_crop_contracts(ACCOUNT, params={"grower_id": grower["id"], "variety": "RANGER_RUSSET"})
    data_f, meta_f = validate_paginated(filtered)
    assert len(data_f) == 1 and meta_f["total_count"] == 1
    assert data_f[0]["variety"] == "RANGER_RUSSET"


def test_growers_get_with_unknown_id_returns_grower_not_found(api):
    """PRD §2.10: "path identifiers are resolved first, left to right,
    followed by body foreign-key identifiers in the endpoint's declared input
    order; each must resolve to an existing entity or the request fails with
    the matching not-found error (`ERR_GROWER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    ...), all HTTP 404."

    Design: Corner/entities/growers_get_with_unknown_id_returns_grower_not_found
    """
    set_clock(api=api)
    resp = api.get_grower(UNKNOWN_UUID, ACCOUNT)
    body = resp.json()
    validate_error(resp, ApiErrorId.ERR_GROWER_NOT_FOUND)
    assert body["response_type"] == "error"
    assert body["data"].get("error_id") and body["data"].get("message"), (
        "error payload must carry both error_id and message"
    )


def test_contract_create_computes_contracted_volume_from_acres_times_yield(api):
    """PRD §3.1: "From these terms the system derives the read-only
    `contracted_volume_cwt`: the product of `contracted_acres` and
    `expected_yield_cwt_per_acre`, rounded half-up to one decimal place."

    Design: Corner/entities/contract_create_computes_contracted_volume_from_acres_times_yield
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    c1 = validate_success(
        api.create_crop_contract(create_crop_contract_payload(grower["id"]), GRM), 201
    )
    assert c1["contracted_volume_cwt"] == 40000.0, (
        f"100 acres x 400 cwt/acre must store 40000.0, got {c1['contracted_volume_cwt']}"
    )
    assert c1["status"] == "DRAFT" and c1["version"] == 1

    c2 = validate_success(
        api.create_crop_contract(
            create_crop_contract_payload(
                grower["id"], variety="RANGER_RUSSET",
                contracted_acres=45.5, expected_yield_cwt_per_acre=380.4,
                base_price_per_cwt_cents=2400,
                delivery_window_start="2026-10-15T00:00:00Z",
                delivery_window_end="2026-12-01T00:00:00Z",
            ),
            GRM,
        ),
        201,
    )
    assert c2["contracted_volume_cwt"] == 17308.2, (
        f"round_half_up(45.5 x 380.4, 1) must store 17308.2, got {c2['contracted_volume_cwt']}"
    )
    assert_crop_contract(c2)


def test_contract_create_with_unknown_grower_returns_grower_not_found(api):
    """PRD §2.10: "path identifiers are resolved first, left to right,
    followed by body foreign-key identifiers in the endpoint's declared input
    order; each must resolve to an existing entity or the request fails with
    the matching not-found error (`ERR_GROWER_NOT_FOUND`, ...), all HTTP 404."

    Design: Corner/entities/contract_create_with_unknown_grower_returns_grower_not_found
    """
    set_clock(api=api)
    resp = api.create_crop_contract(create_crop_contract_payload(UNKNOWN_UUID), GRM)
    validate_error(resp, ApiErrorId.ERR_GROWER_NOT_FOUND)
    data, meta = validate_paginated(api.list_crop_contracts(GRM))
    assert data == [], "no contract row may be persisted after a 404 rejection"


def test_contract_activate_twice_returns_contract_not_draft(api):
    """PRD §3.1: "Activation moves a contract from `DRAFT` to `ACTIVE`,
    requires the referenced grower to exist (`ERR_GROWER_NOT_FOUND`
    otherwise), and is rejected with `ERR_CONTRACT_NOT_DRAFT` when the
    contract is in any other state."

    Design: Corner/state_machines/contract_activate_twice_returns_contract_not_draft
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    contract = make_active_contract(grower["id"], api=api)
    assert contract["status"] == "ACTIVE" and contract["version"] == 2

    resp = api.activate_crop_contract(contract["id"], GRM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_DRAFT)

    reread = validate_success(api.get_crop_contract(contract["id"], GRM))
    assert reread["status"] == "ACTIVE"
    assert reread["version"] == 2, "the rejected second activate must not bump the version"


def test_existence_404_precedes_state_409_on_activate(api):
    """PRD §2.10: "When several checks could reject the same request, the
    server evaluates them in a fixed priority order and returns the first
    failure encountered."
    PRD §2.10: "5. **Existence** — path identifiers are resolved first, left
    to right ... all HTTP 404."
    PRD §2.10: "6. **State preconditions** — the target resource must be in
    the state its transition requires ... all HTTP 409."

    Design: Corner/validations/existence_404_precedes_state_409_on_activate
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    contract = make_active_contract(grower["id"], api=api)

    resp_unknown = api.activate_crop_contract(UNKNOWN_UUID, GRM)
    err_unknown = validate_error(resp_unknown, ApiErrorId.ERR_CONTRACT_NOT_FOUND)
    assert resp_unknown.status_code == 404

    resp_active = api.activate_crop_contract(contract["id"], GRM)
    err_active = validate_error(resp_active, ApiErrorId.ERR_CONTRACT_NOT_DRAFT)
    assert resp_active.status_code == 409

    assert err_unknown["error_id"] != err_active["error_id"]


def test_accept_amendment_with_stale_version_returns_412_then_succeeds(api):
    """PRD §2.9: "If that value does not equal the contract's current
    `version` at the moment of acceptance — because another writer has since
    advanced the contract, for example by a lot delivery flipping it to
    `FULFILLED` or a prior acceptance already applying — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
    applying terms against a contract state it never observed."
    PRD §3.1: "On acceptance the pending terms are applied to the contract,
    `pending_amendment` returns to null, and `contracted_volume_cwt` is
    recomputed from the amended acreage and yield."

    Design: Corner/cross_cutting_layers/accept_amendment_with_stale_version_returns_412_then_succeeds
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    contract = make_active_contract(grower["id"], api=api)
    pending = validate_success(
        api.propose_amendment(contract["id"], create_amendment_payload(), GRM)
    )
    assert pending["status"] == "AMENDMENT_PENDING"
    current_version = pending["version"]  # create 1 -> activate 2 -> propose 3
    assert current_version == 3

    stale = api.accept_amendment(
        contract["id"], {"expected_crop_contract_version": current_version - 1}, GRM
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412
    still_pending = validate_success(api.get_crop_contract(contract["id"], GRM))
    assert still_pending["status"] == "AMENDMENT_PENDING", "a stale accept must apply nothing"
    assert still_pending["base_price_per_cwt_cents"] == 2500

    accepted = validate_success(
        api.accept_amendment(
            contract["id"], {"expected_crop_contract_version": current_version}, GRM
        )
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["base_price_per_cwt_cents"] == 2700
    assert accepted["contracted_volume_cwt"] == 48000.0, (
        f"120 acres x 400 recomputes to 48000.0, got {accepted['contracted_volume_cwt']}"
    )
    assert accepted["version"] == 4
    assert accepted["pending_amendment"] is None
