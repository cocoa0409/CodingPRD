"""Composite setup helpers for the same-day catalog fulfillment API.

Every helper builds its precondition from scratch through PRD-declared endpoints,
because the harness restarts the server (and therefore empties the database) before
every individual test. Helpers use the lenient ``get_success_data`` validator so a
broken precondition reports "Setup failed" rather than a misleading assertion error.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    MONDAY_AFTER_CUTOFF_UTC,
    MONDAY_EARLY_UTC,
    TEST_DEFAULTS,
)
from .factories import (
    create_account_payload,
    create_attribute_payload,
    create_cross_reference_payload,
    create_distribution_center_payload,
    create_item_payload,
    create_order_payload,
    create_return_payload,
    create_square_footage_request_payload,
    create_stock_payload,
    create_supplier_payload,
    order_line_payload,
    return_line_payload,
    square_footage_line_payload,
)
from .test_users import (
    CURATOR_USER_ID,
    DC_MANAGER_USER_ID,
    PICKER_USER_ID,
    TEST_USERS,
    make_customer_account_headers,
)

BASE_URL = None  # the framework reads API_BASE_URL itself

ADMIN = TEST_USERS["platform_admin_headers"]
CURATOR = TEST_USERS["catalog_curator_headers"]
PICKER = TEST_USERS["warehouse_picker_headers"]
DCM = TEST_USERS["dc_manager_headers"]
DC_MANAGER = DCM


class SetupFailed(AssertionError):
    """Raised when a precondition call did not return a success status."""


def _ok(response):
    """Data payload of a successful setup call, or a clear SetupFailed error."""
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - surfaced to the test
        raise SetupFailed(str(exc)) from exc


def _as_list(data) -> List[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise SetupFailed(f"Expected a list payload, got {type(data).__name__}")


# =============================================================================
# Tier 1 — clock, centers, accounts
# =============================================================================

def setup_clock(api=None, utc: str = MONDAY_EARLY_UTC) -> dict:
    """Set the logical clock. Returns the ClockTick."""
    client = api or api_client
    return _ok(client.set_current_utc({"current_utc": utc}, ADMIN))


def setup_center(api=None, code: str = "BOS", region: str = "NORTHEAST",
                 local_zone: str = "America/New_York", local_cutoff_time: str = "06:00:00",
                 utc_offset_minutes: int = -240, inbound_capacity_units: int = 900,
                 transit_seconds: int = 86400) -> dict:
    """Create one distribution center and return its record."""
    client = api or api_client
    payload = create_distribution_center_payload(
        code=code, region=region, local_zone=local_zone,
        local_cutoff_time=local_cutoff_time, utc_offset_minutes=utc_offset_minutes,
        inbound_capacity_units=inbound_capacity_units, transit_seconds=transit_seconds,
    )
    return _ok(client.create_distribution_center(payload, ADMIN))


def setup_account(api=None, account_name: str = TEST_DEFAULTS["ACCOUNT_NAME"],
                  delivery_zone: str = TEST_DEFAULTS["DELIVERY_ZONE"],
                  home_region: str = TEST_DEFAULTS["HOME_REGION"]) -> dict:
    """Create one customer account and return its record."""
    client = api or api_client
    payload = create_account_payload(account_name=account_name, delivery_zone=delivery_zone,
                                     home_region=home_region)
    return _ok(client.create_account(payload, ADMIN))


def account_headers(account: dict) -> dict:
    """Ownership-gated headers for the account's own id."""
    return make_customer_account_headers(account["id"])


def setup_center_and_account(api=None, utc: str = MONDAY_EARLY_UTC,
                             **dc_overrides) -> dict:
    """Clock + one center + one account — the common base for most scenarios."""
    client = api or api_client
    setup_clock(client, utc)
    dc = setup_center(client, **dc_overrides)
    acct = setup_account(client)
    return {"clock": utc, "dc": dc, "acct": acct, "acct_headers": account_headers(acct)}


# =============================================================================
# Tier 2 — catalog build-out
# =============================================================================

ITEM_SPEC_DEFAULTS = {
    # No default sku: setup_curated_items falls back to f"{sku_prefix}-{1000+index}"
    # so each item in a batch gets a distinct sku. A truthy default here would
    # defeat that fallback and make every item collide on the same sku.
    "sku": None,
    "price": 1000,
    "bundle": 8,
    "long_tail": False,
    "weight": 0.10,
    "material": "steel",
    "revision": 1,
    "attr_name": "Grade",
    "attr_value": "8.8",
}

STOCK_SPEC_DEFAULTS = {
    "on_hand": 20,
    "demand": 2,
    "inbound": 2,
}


def setup_curated_items(api=None, specs: Optional[List[dict]] = None,
                        account: Optional[dict] = None, dc: Optional[dict] = None,
                        with_stock: bool = True, sku_prefix: str = "SKU") -> dict:
    """Create N items (each with one attribute row), approve them in one batch,
    and optionally record a stock row per item at ``dc``.

    Returns ``{"items": [...], "review": {...}, "stock_rows": [...]}``.
    """
    client = api or api_client
    specs = specs or [dict(ITEM_SPEC_DEFAULTS)]
    items: List[dict] = []
    for index, raw in enumerate(specs, start=1):
        spec = dict(ITEM_SPEC_DEFAULTS)
        spec.update(raw)
        payload = create_item_payload(
            sku=spec.get("sku") or f"{sku_prefix}-{1000 + index}",
            description=f"Catalog item {index}",
            material_spec=spec["material"],
            long_tail=spec["long_tail"],
            unit_price_cents=spec["price"],
            unit_weight_kg=spec["weight"],
            curation_bundle_size=spec["bundle"],
            curated_dimension_json={
                "nominal_length_mm": 10 + index,
                "nominal_width_mm": 10 + index,
                "nominal_height_mm": 10 + index,
                "drawing_revision": spec["revision"],
            },
        )
        item = _ok(client.create_item(payload, CURATOR))
        _ok(client.create_item_attribute(
            item["id"],
            create_attribute_payload(attribute_name=spec["attr_name"],
                                     attribute_value=spec["attr_value"]),
            CURATOR,
        ))
        items.append(item)

    review = None
    if items:
        review = _ok(client.create_curation_review(
            {"item_ids": [item["id"] for item in items]}, CURATOR))

    stock_rows: List[dict] = []
    if with_stock and dc is not None and account is not None:
        for index, (item, raw) in enumerate(zip(items, specs), start=1):
            spec = dict(STOCK_SPEC_DEFAULTS)
            spec.update(raw)
            row = _ok(client.create_stock(
                create_stock_payload(item_id=item["id"], dc_id=dc["id"],
                                     account_id=account["id"],
                                     on_hand_units=spec["on_hand"],
                                     daily_demand_units=spec["demand"],
                                     inbound_daily_units=spec["inbound"]),
                DCM,
            ))
            stock_rows.append(row)

    for item in items:
        # Re-read so every derived field reflects the approval that just ran.
        pass
    fresh = [_ok(client.get_item(item["id"], CURATOR)) for item in items]
    return {"items": fresh, "review": review, "stock_rows": stock_rows}


def setup_supplier(api=None, home_dc: Optional[dict] = None,
                   returns_items: bool = False,
                   **overrides) -> dict:
    """Create one supplier tied to ``home_dc``."""
    client = api or api_client
    payload = create_supplier_payload(home_dc_id=home_dc["id"], **overrides)
    return _ok(client.create_supplier(payload, ADMIN))


def setup_availability_report(api=None, supplier: Optional[dict] = None,
                              item: Optional[dict] = None,
                              reported_available_units: int = 60) -> dict:
    """File one availability report; returns the selected supplier."""
    client = api or api_client
    return _ok(client.create_availability_report(
        supplier["id"],
        {"item_id": item["id"], "reported_available_units": reported_available_units},
        ADMIN,
    ))


# =============================================================================
# Tier 3 — order lifecycle
# =============================================================================

def create_released_order(api=None, account: Optional[dict] = None,
                          lines: Optional[List[dict]] = None,
                          promised_delivery_by: Optional[str] = None) -> dict:
    """Create an order and release it. Returns the released order."""
    client = api or api_client
    headers = account_headers(account)
    payload = create_order_payload(account_id=account["id"], lines=lines)
    if promised_delivery_by is not None:
        payload["promised_delivery_by"] = promised_delivery_by
    order = _ok(client.create_order(payload, headers))
    return _ok(client.release_order(order["id"], headers))


def allocate_order(api=None, account: Optional[dict] = None,
                   order: Optional[dict] = None, expected_version: Optional[int] = None) -> dict:
    """Run the allocation selector against an already-released order."""
    client = api or api_client
    version = order["version"] if expected_version is None else expected_version
    return _ok(client.allocate_order(order["id"], {"expected_order_version": version},
                                     account_headers(account)))


def list_lines(api=None, account: Optional[dict] = None, order: Optional[dict] = None) -> List[dict]:
    """Order lines in creation order."""
    client = api or api_client
    return _as_list(_ok(client.list_order_lines(order["id"], account_headers(account),
                                                {"limit": 100, "offset": 0})))


def pick_and_complete(api=None, order: Optional[dict] = None, line: Optional[dict] = None,
                      requested_units: Optional[int] = None,
                      actual_units: Optional[int] = None) -> dict:
    """Start and complete one pick. Returns the resulting PickTask."""
    client = api or api_client
    requested = line["quantity"] if requested_units is None else requested_units
    actual = requested if actual_units is None else actual_units
    task = _ok(client.pick_line(order["id"], line["id"], {"requested_units": requested}, PICKER))
    return _ok(client.complete_pick(order["id"], line["id"], {"actual_units": actual}, PICKER))


def open_pick(api=None, order: Optional[dict] = None, line: Optional[dict] = None,
              requested_units: Optional[int] = None) -> dict:
    """Start a pick without completing it."""
    client = api or api_client
    requested = line["quantity"] if requested_units is None else requested_units
    return _ok(client.pick_line(order["id"], line["id"], {"requested_units": requested}, PICKER))


def confirm_cutoff(api=None, order: Optional[dict] = None, account: Optional[dict] = None,
                   service_level: str = "GROUND",
                   promised_delivery_by: Optional[str] = None) -> dict:
    """Certify the shipment cutoff, re-reading the order for its current version."""
    client = api or api_client
    current = _ok(client.get_order(order["id"], account_headers(account)))
    return _ok(client.confirm_cutoff(
        order["id"],
        {"expected_order_version": current["version"], "service_level": service_level},
        DCM,
    ))


def get_shipment_for_order(api=None, order: Optional[dict] = None,
                           account: Optional[dict] = None) -> dict:
    """The single shipment attached to an order."""
    client = api or api_client
    rows = _as_list(_ok(client.list_shipments(account_headers(account),
                                              {"order_id": order["id"], "limit": 10, "offset": 0})))
    if not rows:
        raise SetupFailed(f"No shipment exists for order {order['id']}")
    return rows[0]


# =============================================================================
# The main workhorse: build an order and walk it to a target state
# =============================================================================

def setup_order_scenario(api=None, lines_spec: Optional[List[dict]] = None,
                         target: str = "ALLOCATED", utc: str = MONDAY_EARLY_UTC,
                         center_overrides: Optional[dict] = None,
                         account_overrides: Optional[dict] = None,
                         extra_centers: Optional[List[dict]] = None,
                         promised_delivery_by: Optional[str] = None,
                         picks: Optional[List[Optional[int]]] = None,
                         service_level: str = "GROUND",
                         sku_prefix: str = "SKU") -> Dict[str, object]:
    """Create a center, an account, the curated items with stock, then an order
    walked forward to ``target``.

    ``lines_spec`` entries accept ``price``, ``qty``, ``bundle``, ``long_tail``,
    ``weight``, ``on_hand``, ``demand``, ``inbound`` and ``sku``.

    ``target`` is one of ``DRAFT``, ``RELEASED``, ``ALLOCATED``, ``PICKED``,
    ``SHIPPED``.

    ``picks`` carries the actual picked units per line when ``target`` is ``PICKED``
    or ``SHIPPED``; ``None`` means a full pick.
    """
    client = api or api_client
    setup_clock(client, utc)
    dc = setup_center(client, **(center_overrides or {}))
    centers = [dc]
    for overrides in (extra_centers or []):
        centers.append(setup_center(client, **overrides))
    acct = setup_account(client, **(account_overrides or {}))
    headers = account_headers(acct)

    specs = lines_spec or [{"price": 12000, "qty": 1}]
    catalog = setup_curated_items(client, specs=specs, account=acct, dc=dc,
                                  sku_prefix=sku_prefix)

    lines_payload = [
        order_line_payload(item["id"], spec.get("qty", 1))
        for item, spec in zip(catalog["items"], specs)
    ]
    order_payload = create_order_payload(account_id=acct["id"], lines=lines_payload)
    if promised_delivery_by is not None:
        order_payload["promised_delivery_by"] = promised_delivery_by
    order = _ok(client.create_order(order_payload, headers))
    lines = list_lines(client, acct, order)

    result: Dict[str, object] = {
        "clock": utc,
        "dc": dc,
        "centers": centers,
        "acct": acct,
        "acct_headers": headers,
        "items": catalog["items"],
        "review": catalog["review"],
        "stock_rows": catalog["stock_rows"],
        "order": order,
        "lines": lines,
        "shipment": None,
        "tasks": [],
    }

    if target == "DRAFT":
        return result

    order = _ok(client.release_order(order["id"], headers))
    result["order"] = order
    if target == "RELEASED":
        return result

    order = _ok(client.allocate_order(order["id"],
                                      {"expected_order_version": order["version"]}, headers))
    result["order"] = order
    lines = list_lines(client, acct, order)
    result["lines"] = lines
    if target == "ALLOCATED":
        return result

    tasks = []
    for index, line in enumerate(lines):
        actual = line["quantity"] if not picks else picks[index]
        tasks.append(pick_and_complete(client, order, line,
                                       requested_units=line["quantity"],
                                       actual_units=actual))
    result["tasks"] = tasks
    order = _ok(client.get_order(order["id"], headers))
    result["order"] = order
    lines = list_lines(client, acct, order)
    result["lines"] = lines
    if target == "PICKED":
        return result

    shipment = _ok(client.confirm_cutoff(
        order["id"],
        {"expected_order_version": order["version"], "service_level": service_level},
        DCM,
    ))
    result["shipment"] = shipment
    result["order"] = _ok(client.get_order(order["id"], headers))
    result["lines"] = list_lines(client, acct, result["order"])
    return result


# =============================================================================
# Tier 4 — threshold / accumulation targeting
# =============================================================================

def setup_pick_shortage_with_claim(api=None, line_units: int = 3, actual_units: int = 1,
                                   price: int = 3000, long_tail: bool = False,
                                   on_hand: Optional[int] = None, utc: str = MONDAY_EARLY_UTC,
                                   sku: str = "SKU-SHORT") -> Dict[str, object]:
    """Allocated order whose pick comes up short, opening a damage claim."""
    client = api or api_client
    stock = line_units if on_hand is None else on_hand
    scenario = setup_order_scenario(
        client,
        lines_spec=[{"price": price, "qty": line_units, "long_tail": long_tail,
                     "on_hand": stock, "sku": sku}],
        target="PICKED",
        utc=utc,
        picks=[actual_units],
    )
    claims = _as_list(_ok(client.list_damage_claims(
        DCM, {"order_id": scenario["order"]["id"], "limit": 10, "offset": 0})))
    if not claims:
        raise SetupFailed("Expected a damage claim after the short pick")
    scenario["claim"] = claims[0]
    scenario["tasks"] = [
        _ok(client.get_pick_task(task["id"], PICKER)) for task in scenario["tasks"]
    ]
    return scenario


def setup_allocated_order_with_two_stock_rows(api=None, on_hand_a: int = 12,
                                              on_hand_b: int = 5, qty: int = 4,
                                              price: int = 6500,
                                              utc: str = MONDAY_EARLY_UTC) -> Dict[str, object]:
    """Allocated order whose single item is held on two stock rows at one center."""
    client = api or api_client
    scenario = setup_order_scenario(
        client,
        lines_spec=[{"price": price, "qty": qty, "on_hand": on_hand_a}],
        target="ALLOCATED", utc=utc, sku_prefix="SKU-LEDGER",
    )
    second = _ok(client.create_stock(
        create_stock_payload(item_id=scenario["items"][0]["id"], dc_id=scenario["dc"]["id"],
                             account_id=scenario["acct"]["id"], on_hand_units=on_hand_b,
                             daily_demand_units=1, inbound_daily_units=1),
        DCM,
    ))
    scenario["stock_rows"] = list(scenario["stock_rows"]) + [second]
    return scenario


def setup_tier_boundary_order_count(api=None, line_count: int = 4,
                                    price: int = 12000,
                                    utc: str = MONDAY_EARLY_UTC) -> Dict[str, object]:
    """A released order carrying ``line_count`` equally priced single-unit lines."""
    client = api or api_client
    specs = [{"price": price, "qty": 1, "bundle": 8, "sku": f"BL-{2000 + index}"}
             for index in range(line_count)]
    return setup_order_scenario(client, lines_spec=specs, target="RELEASED", utc=utc,
                                sku_prefix="BL")


def setup_five_line_fee_order(api=None, prices: Optional[List[int]] = None,
                              quantities: Optional[List[int]] = None,
                              utc: str = MONDAY_EARLY_UTC,
                              sku_prefix: str = "SKU-5L") -> Dict[str, object]:
    """Released five-line order used by the handling-fee translations."""
    prices = prices or [12000, 24000, 36000, 48000, 60000]
    quantities = quantities or [1, 2, 3, 4, 5]
    specs = [
        {"price": price, "qty": qty, "bundle": 8, "on_hand": 10, "demand": 3, "inbound": 3}
        for price, qty in zip(prices, quantities)
    ]
    return setup_order_scenario(api, lines_spec=specs, target="RELEASED", utc=utc,
                                sku_prefix=sku_prefix)


# =============================================================================
# Tier 5 — returns, posture cascades and the consignment flow
# =============================================================================

def setup_shipped_order(api=None, qty: int = 5, price: int = 2000, long_tail: bool = False,
                        on_hand: int = 10, utc: str = MONDAY_AFTER_CUTOFF_UTC,
                        unit_weight_kg: float = 0.10, sku: str = "SKU-SHIP") -> Dict[str, object]:
    """Order picked in full and cut off, so the shipment is CUTOFF_CONFIRMED."""
    client = api or api_client
    return setup_order_scenario(
        client,
        lines_spec=[{"price": price, "qty": qty, "long_tail": long_tail,
                     "on_hand": on_hand, "weight": unit_weight_kg, "sku": sku}],
        target="SHIPPED", utc=utc, sku_prefix=sku,
    )


def create_and_approve_return(api=None, scenario: Optional[dict] = None,
                              requested_units: Optional[int] = None,
                              as_manager: bool = False) -> dict:
    """Create one return authorization for the scenario's first line and approve it."""
    client = api or api_client
    line = scenario["lines"][0]
    units = line["quantity"] if requested_units is None else requested_units
    headers = DCM if as_manager else account_headers(scenario["acct"])
    ret = _ok(client.create_return(
        create_return_payload(scenario["order"]["id"],
                              [return_line_payload(line["id"], units)]), headers))
    return _ok(client.approve_return(ret["id"], DCM))


def receive_return(api=None, ret: Optional[dict] = None, line: Optional[dict] = None,
                   part_number: str = "PART-001") -> dict:
    """Receive an approved return with the traceability map populated."""
    client = api or api_client
    return _ok(client.receive_return(
        ret["id"], {"removed_manufacturer_part_numbers": {line["id"]: part_number}}, DCM))


def setup_square_footage_quote(api=None, requested_feet: Optional[List[int]] = None,
                               utc: str = MONDAY_EARLY_UTC,
                               account_overrides: Optional[dict] = None) -> dict:
    """Quote a cut-pipe consignment. Returns the request and the account."""
    client = api or api_client
    setup_clock(client, utc)
    acct = setup_account(client, **(account_overrides or {}))
    lengths = requested_feet or [40, 60, 50]
    lines = [square_footage_line_payload(ordinal, feet)
             for ordinal, feet in enumerate(lengths, start=1)]
    request = _ok(client.create_square_footage_request(
        create_square_footage_request_payload(acct["id"], lines), account_headers(acct)))
    return {"acct": acct, "acct_headers": account_headers(acct), "request": request}


def setup_draft_order(api=None, lines_spec=None, utc: str = MONDAY_EARLY_UTC, **kwargs):
    """Order created but never released."""
    return setup_order_scenario(api, lines_spec=lines_spec, target="DRAFT", utc=utc, **kwargs)


def setup_released_order(api=None, lines_spec=None, utc: str = MONDAY_EARLY_UTC, **kwargs):
    """Order created and released, still AWAITING_RELEASE."""
    return setup_order_scenario(api, lines_spec=lines_spec, target="RELEASED", utc=utc, **kwargs)


def setup_allocated_order(api=None, lines_spec=None, utc: str = MONDAY_EARLY_UTC, **kwargs):
    """Order released and allocated to its center."""
    return setup_order_scenario(api, lines_spec=lines_spec, target="ALLOCATED", utc=utc, **kwargs)


def setup_picked_order(api=None, lines_spec=None, picks=None, utc: str = MONDAY_EARLY_UTC,
                       **kwargs):
    """Order walked through picking; ``picks`` gives the actual units per line."""
    return setup_order_scenario(api, lines_spec=lines_spec, target="PICKED", picks=picks,
                                utc=utc, **kwargs)


def setup_items_only(api=None, specs=None, utc: str = MONDAY_EARLY_UTC, sku_prefix: str = "SKU"):
    """Clock plus curated items with no stock rows — for read-path corners."""
    client = api or api_client
    setup_clock(client, utc)
    return setup_curated_items(client, specs=specs, account=None, dc=None, with_stock=False,
                               sku_prefix=sku_prefix)


def add_stock_row(api=None, item: Optional[dict] = None, dc: Optional[dict] = None,
                  account: Optional[dict] = None, on_hand: int = 10,
                  demand: int = 2, inbound: int = 2) -> dict:
    """Record one extra stock row for an item at a center."""
    client = api or api_client
    return _ok(client.create_stock(
        create_stock_payload(item_id=item["id"], dc_id=dc["id"], account_id=account["id"],
                             on_hand_units=on_hand, daily_demand_units=demand,
                             inbound_daily_units=inbound), DCM))


def setup_possitive_availability_centers(api=None, utc: str = MONDAY_AFTER_CUTOFF_UTC
                                         ) -> Dict[str, object]:
    """Two same-region centers, both past their cutoff, holding one shared item."""
    client = api or api_client
    setup_clock(client, utc)
    bos = setup_center(client, code="BOS", region="SOUTHEAST",
                       local_zone="America/New_York", utc_offset_minutes=-240,
                       transit_seconds=86400)
    dal = setup_center(client, code="DAL", region="SOUTHEAST",
                       local_zone="America/Chicago", utc_offset_minutes=-300,
                       transit_seconds=172800)
    acct = setup_account(client, home_region="SOUTHEAST")
    catalog = setup_curated_items(
        client,
        specs=[{"price": 2000, "bundle": 10, "sku": "AV-1001", "on_hand": 12}],
        account=acct, dc=bos, sku_prefix="AV",
    )
    item = catalog["items"][0]
    dal_row = _ok(client.create_stock(
        create_stock_payload(item_id=item["id"], dc_id=dal["id"], account_id=acct["id"],
                             on_hand_units=4, daily_demand_units=1, inbound_daily_units=1), DCM))
    return {"clock": utc, "bos": bos, "dal": dal, "acct": acct,
            "acct_headers": account_headers(acct), "item": item,
            "bos_stock": catalog["stock_rows"][0], "dal_stock": dal_row}