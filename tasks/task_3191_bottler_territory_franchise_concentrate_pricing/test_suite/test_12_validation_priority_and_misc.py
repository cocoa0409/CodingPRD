"""Validation priority, cross-entity state gates, envelope shape, filtered lists."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
    validate_paginated,
    get_success_data,
    set_clock_default,
    create_brand_owner,
    create_territory,
    create_draft_agreement,
    create_product_line,
    create_price_index,
    activate_agreement,
    seed_active_agreement,
    add_second_active_agreement,
    create_customer,
    create_equipment,
    place_equipment,
    create_service_window,
    create_cpo,
    create_dsd_order_payload,
    create_cpo_payload,
    ops_headers,
    make_bottler_ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]
FT = TEST_USERS["field_technician_headers"]


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / cpo_create_suspended_agreement_and_below_min_qty_state_wins
# ---------------------------------------------------------------------------

def test_cpo_create_on_suspended_agreement_below_min_qty_state_wins(api):
    """PRD §2.7: "The system applies validations in a fixed priority order on
    every request, and a request fails at the first failing check. The order
    is: (1) authentication of the headers; (2) role authorization for the
    endpoint; (3) existence of every path identifier and every foreign-key
    identifier in the body — validated left to right, path parameters first and
    then body fields in their declared order — with any miss rejected as
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404); (4) state checks confirming the target
    entity is in a state from which the requested transition is defined (this
    priority level covers `ERR_INVALID_STATE`, `ERR_AGREEMENT_NOT_ACTIVE`,
    `ERR_AGREEMENT_ALREADY_ACTIVE`, `ERR_CPO_ALREADY_FINALIZED`,
    `ERR_NCA_NOT_PUBLISHED`, `ERR_EQUIPMENT_NOT_IN_WAREHOUSE`,
    `ERR_CUSTOMER_DISPUTED`, `ERR_DSD_ORDER_NOT_DELIVERED`,
    `ERR_TRANSFER_CUSTOMERS_DISPUTED`, `ERR_LAUNCH_PRODUCT_INACTIVE`,
    `ERR_TERRITORY_HAS_ACTIVE_AGREEMENT`, and `ERR_ALREADY_TERMINAL`); ... (8)
    domain quantity rules (`ERR_MIN_ORDER_QUANTITY`, `ERR_ZERO_QUANTITY`,
    `ERR_INDEX_QUARTER_DUPLICATE`, `ERR_LINE_OBLIGATION_UNMET`); ...".

    Design: Difficulty/priority_pair_validation_conflict/cpo_create_suspended_agreement_and_below_min_qty_state_wins
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    r = api_client.suspend_agreement(ag_id, BOA)
    assert r.status_code == 200
    r = api_client.create_cpo(
        {
            "agreement_id": ag_id,
            "product_line_id": env["line"]["id"],
            "quantity_gallons": 500,  # also below the 1000 minimum
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": env["ag_v1"],
        },
        ops_headers(env),
    )
    body = r.json()
    assert r.status_code == 409, f"state check (priority 4) must win: {r.text}"
    assert body["data"]["error_id"] == ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value
    assert body["data"]["error_id"] != ApiErrorId.ERR_MIN_ORDER_QUANTITY.value


def test_cpo_create_on_active_agreement_below_min_qty_reports_quantity_error(api):
    """PRD §3.2: "The minimum order quantity is 1000 gallons; a
    `quantity_gallons` below that floor is rejected with
    `ERR_MIN_ORDER_QUANTITY` (HTTP 422)."
    PRD §2.7: "The system applies validations in a fixed priority order on
    every request, and a request fails at the first failing check."

    Design: Difficulty/priority_pair_validation_conflict/cpo_create_suspended_agreement_and_below_min_qty_state_wins
    """
    env = seed_active_agreement()
    r = api_client.create_cpo(
        {
            "agreement_id": env["agreement"]["id"],
            "product_line_id": env["line"]["id"],
            "quantity_gallons": 500,
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": env["ag_v1"],
        },
        ops_headers(env),
    )
    validate_error(r, ApiErrorId.ERR_MIN_ORDER_QUANTITY.value)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / service_window_overlap_and_budget_breach_temporal_wins
# ---------------------------------------------------------------------------

def _seed_placed_equipment_with_budget(budget):
    env = seed_active_agreement(service_budget_cents=budget)
    cust = create_customer(env)
    eq = create_equipment(env)
    place_equipment(env, eq["id"], cust["id"])
    return env, cust, eq


def test_service_window_overlap_and_budget_breach_temporal_wins(api):
    """PRD §2.7: "(5) business temporal rules such as overlapping NCA windows,
    overlapping service windows, overlapping equipment placements, and
    commitment-window closure; ... and (9) fiscal rules
    (`ERR_SERVICE_BUDGET_EXCEEDED`, `ERR_FUND_INSUFFICIENT_BALANCE`,
    `ERR_CLAWBACK_EXCEEDS_ACCRUAL`, `ERR_PRICE_DEVIATION_EXCEEDS_BAND`)."
    PRD §2.7: "The system applies validations in a fixed priority order on
    every request, and a request fails at the first failing check."

    Design: Difficulty/priority_pair_validation_conflict/service_window_overlap_and_budget_breach_temporal_wins
    """
    env, cust, eq = _seed_placed_equipment_with_budget(1000)
    create_service_window(
        eq["id"], technician_label="T-7",
        window_start="2026-10-01T09:00:00Z", window_end="2026-10-01T11:00:00Z",
        cost_cents=600,
    )  # spent 600, remaining 400
    r = api_client.create_service_window(
        eq["id"],
        {"technician_label": "T-7", "window_start": "2026-10-01T10:00:00Z",
         "window_end": "2026-10-01T12:00:00Z", "cost_cents": 500},
        FT,
    )
    body = r.json()
    assert r.status_code == 409, f"temporal check (priority 5) must win: {r.text}"
    assert body["data"]["error_id"] == ApiErrorId.ERR_SERVICE_WINDOW_OVERLAP.value
    assert body["data"]["error_id"] != ApiErrorId.ERR_SERVICE_BUDGET_EXCEEDED.value


def test_service_window_budget_breach_alone_reports_fiscal_error(api):
    """PRD §3.5: "Fiscally, the agreement's `service_spent_cents` plus the new
    window's `cost_cents` must not exceed the agreement's
    `service_budget_cents`; an overrun is rejected with
    `ERR_SERVICE_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/service_window_overlap_and_budget_breach_temporal_wins
    """
    env, cust, eq = _seed_placed_equipment_with_budget(1000)
    create_service_window(
        eq["id"], technician_label="T-7",
        window_start="2026-10-01T09:00:00Z", window_end="2026-10-01T11:00:00Z",
        cost_cents=600,
    )
    r = api_client.create_service_window(
        eq["id"],
        {"technician_label": "T-8", "window_start": "2026-10-02T09:00:00Z",
         "window_end": "2026-10-02T10:00:00Z", "cost_cents": 500},
        FT,
    )
    validate_error(r, ApiErrorId.ERR_SERVICE_BUDGET_EXCEEDED.value)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / cpo_requires_active_agreement
# ---------------------------------------------------------------------------

def test_cpo_create_on_draft_agreement_rejected(api):
    """PRD §2.7: "(4) state checks confirming the target entity is in a state
    from which the requested transition is defined (this priority level covers
    `ERR_INVALID_STATE`, `ERR_AGREEMENT_NOT_ACTIVE`, ...)".
    PRD §3.2: "A `BottlerOps` operator acting as a specific agreement places a
    **concentrate purchase order** by supplying the `agreement_id`, the
    `product_line_id` being ordered, a `quantity_gallons`, a `delivery_quarter`
    in `YYYY-Qn` form, and the OCC field `expected_agreement_version`
    (see §2.8)."

    Design: Difficulty/cross_entity_state_dependency/cpo_requires_active_agreement
    """
    set_clock_default()
    bo = create_brand_owner()
    create_price_index(bo["id"])
    line = create_product_line(bo["id"])
    ter = create_territory(bo["id"])
    ag = create_draft_agreement(ter["id"])  # left in DRAFT
    r = api_client.create_cpo(
        {
            "agreement_id": ag["id"],
            "product_line_id": line["id"],
            "quantity_gallons": 10000,
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": ag["version"],
        },
        make_bottler_ops_headers(ag["id"]),
    )
    validate_error(r, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
    assert r.status_code == 409
    data, meta = validate_paginated(
        api_client.list_cpos(PA, params={"agreement_id": ag["id"]})
    )
    assert meta["total_count"] == 0


def test_cpo_create_on_suspended_agreement_rejected(api):
    """PRD §2.7: "(4) state checks confirming the target entity is in a state
    from which the requested transition is defined (this priority level covers
    `ERR_INVALID_STATE`, `ERR_AGREEMENT_NOT_ACTIVE`, ...)".
    PRD §3.1: "The brand owner's staff may **suspend** an `ACTIVE` agreement,
    moving it to `SUSPENDED`, and later **reinstate** a `SUSPENDED` agreement
    back to `ACTIVE` — a cycle that may repeat."

    Design: Difficulty/cross_entity_state_dependency/cpo_requires_active_agreement
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    r = api_client.suspend_agreement(ag_id, BOA)
    assert r.status_code == 200
    ag_version = get_success_data(r)["version"]
    r = api_client.create_cpo(
        {
            "agreement_id": ag_id,
            "product_line_id": env["line"]["id"],
            "quantity_gallons": 10000,
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": ag_version,
        },
        ops_headers(env),
    )
    validate_error(r, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
    assert r.status_code == 409
    data, meta = validate_paginated(
        api_client.list_cpos(PA, params={"agreement_id": ag_id})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / bottler_agreement_suspend_reinstate_cycle_and_cpo_parallel_dims
# ---------------------------------------------------------------------------

def test_agreement_suspend_reinstate_cycle_returns_to_active(api):
    """PRD §3.1: "The brand owner's staff may **suspend** an `ACTIVE`
    agreement, moving it to `SUSPENDED`, and later **reinstate** a `SUSPENDED`
    agreement back to `ACTIVE` — a cycle that may repeat."
    PRD §3.1: "Every one of these transitions increments the agreement's
    `version` by 1 and refreshes `updated_at`."

    Design: Difficulty/non_linear_state_machine/bottler_agreement_suspend_reinstate_cycle_and_cpo_parallel_dims
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    r = api_client.suspend_agreement(ag_id, BOA)
    assert r.status_code == 200
    assert get_success_data(r)["status"] == "SUSPENDED"
    r = api_client.reinstate_agreement(ag_id, BOA)
    assert r.status_code == 200
    data = get_success_data(r)
    assert data["status"] == "ACTIVE"
    assert data["version"] == env["agreement"]["version"] + 2


def test_cpo_receive_leaves_pricing_dimension_untouched(api):
    """PRD §3.2: "Every purchase order carries two parallel status dimensions.
    `fulfillment_status` starts at `PLACED` and can move to `RECEIVED` (when
    the concentrate physically arrives) or to `CANCELLED`. `pricing_status`
    starts at `PROVISIONAL` and moves to `FINALIZED` exactly once. Receiving
    does not touch `pricing_status`; finalizing does not touch
    `fulfillment_status`."

    Design: Difficulty/non_linear_state_machine/bottler_agreement_suspend_reinstate_cycle_and_cpo_parallel_dims
    """
    env = seed_active_agreement()
    cpo = create_cpo(env, quantity_gallons=10000, delivery_quarter="2026-Q3")
    r = api_client.receive_cpo(cpo["id"], ops_headers(env))
    assert r.status_code == 200
    data = get_success_data(r)
    assert data["fulfillment_status"] == "RECEIVED"
    assert data["pricing_status"] == "PROVISIONAL", "receive must not touch pricing_status"


# ---------------------------------------------------------------------------
# Queue B: endpoints / filtered_lists_scope_children_to_parent
# ---------------------------------------------------------------------------

def test_filtered_lists_scope_children_to_parent(api):
    """PRD §4 endpoint table: "GET | `/bottler/customers` | List customers,
    optionally by agreement, NCA, or status | ...".
    PRD §4 endpoint table: "GET | `/bottler/concentrate-purchase-orders` | List
    CPOs, optionally by agreement or product line | ...".

    Design: Corner/endpoints/filtered_lists_scope_children_to_parent
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    create_cpo(env)
    add_second_active_agreement(env)
    data, meta = validate_paginated(
        api_client.list_customers(
            make_bottler_ops_headers(env["agreement"]["id"]),
            params={"agreement_id": env["agreement"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == cust["id"]
    data2, meta2 = validate_paginated(
        api_client.list_cpos(
            make_bottler_ops_headers(env["agreement2"]["id"]),
            params={"agreement_id": env["agreement2"]["id"]},
        )
    )
    assert meta2["total_count"] == 0
    assert data2 == []


# ---------------------------------------------------------------------------
# Queue B: endpoints / error_envelope_shape_on_not_found
# ---------------------------------------------------------------------------

def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with "`response_type`: "error"" and a data object
    whose keys are "error_id" and "message".
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    set_clock_default()
    r = api_client.get_territory(NON_EXISTENT_UUID, PA)
    body = r.json()
    assert r.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_RESOURCE_NOT_FOUND.value
    assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0
    assert "api_request_id" in body["meta"] and body["meta"]["api_request_id"]
    assert "api_request_timestamp" in body["meta"] and body["meta"]["api_request_timestamp"]


# ---------------------------------------------------------------------------
# Queue B: validations / duplicate_index_quarter_rejected
# ---------------------------------------------------------------------------

def test_duplicate_index_quarter_rejected(api):
    """PRD §3.1: "Quarterly commodity indices are recorded as **concentrate
    price index** rows, one per brand per quarter, each with a `quarter` label
    in `YYYY-Qn` form and an `index_value` at 2 decimal places strictly greater
    than zero. At most one index row may exist for a given brand and quarter; a
    second row for the same pair is rejected with `ERR_INDEX_QUARTER_DUPLICATE`
    (HTTP 409)."

    Design: Corner/validations/duplicate_index_quarter_rejected
    """
    set_clock_default()
    bo = create_brand_owner()
    create_price_index(bo["id"], quarter="2026-Q2", index_value=110.00)
    r = api_client.create_price_index(
        {"brand_owner_id": bo["id"], "quarter": "2026-Q2", "index_value": 115.00},
        BOA,
    )
    validate_error(r, ApiErrorId.ERR_INDEX_QUARTER_DUPLICATE.value)
    assert r.status_code == 409
