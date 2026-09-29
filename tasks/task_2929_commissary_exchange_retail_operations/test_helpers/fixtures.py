"""Composite setup helpers.

Every test runs against a freshly started server with an empty database, so
every scenario is assembled here from scratch through the public API. Nothing in
this module asserts business behaviour: setup steps use the lenient success
reader so that a failed *setup* is reported as a setup problem rather than as a
misleading business assertion.

Two conventions run through the whole file:

* The two version-guarded writes -- creating a shelf allocation and granting a
  delegation -- re-read the parent record when the caller does not pass an
  explicit expected version, because a successful write of either kind advances
  that parent's version.
* Money arguments are integer cents and temporal arguments are full ISO 8601
  UTC instants.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import AUG_01, AUG_31
from .test_users import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_BOARD_OFFICER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    HEADERS_SYSTEM_OPERATOR,
    make_board_officer_headers,
    make_fund_controller_headers,
    make_patron_headers,
)

# ---------------------------------------------------------------------------
# Tier 1: single-call primitives
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Reposition the logical clock. Mutates no entity and runs no sweep."""
    return get_success_data(api.set_clock(factories.clock_payload(instant), HEADERS_SYSTEM_OPERATOR))


def create_store(
    api: ApiClient,
    name: str = "Fort Example Commissary",
    channel: str = "COMMISSARY",
    region: str = "CONUS",
    surcharge_rate_bp: Optional[int] = None,
    exchange_markup_bp: Optional[int] = None,
    shelf_block_capacity_facings: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register a store. A fresh store is fiscally empty and therefore FROZEN."""
    payload = factories.store_payload(
        name=name,
        channel=channel,
        region=region,
        surcharge_rate_bp=surcharge_rate_bp,
        exchange_markup_bp=exchange_markup_bp,
        shelf_block_capacity_facings=shelf_block_capacity_facings,
    )
    return get_success_data(api.create_store(payload, headers or HEADERS_FUND_CONTROLLER), 201)


def read_store(api: ApiClient, store_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a store, including its four derived fund figures and its posture."""
    return get_success_data(api.get_store(store_id, headers or HEADERS_FUND_CONTROLLER))


def store_version(api: ApiClient, store_id: str) -> int:
    """The store's current version, for the allocation stale-view guard."""
    return read_store(api, store_id)["version"]


def create_patron(
    api: ApiClient,
    full_name: str = "SGT A Example",
    id_card_class: str = "ACTIVE_DUTY",
    sponsor_patron_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Enrol a patron. A new patron is VALID on the card axis and CLEAR on watch."""
    payload = factories.patron_payload(
        full_name=full_name,
        id_card_class=id_card_class,
        sponsor_patron_id=sponsor_patron_id,
    )
    return get_success_data(api.create_patron(payload, headers or HEADERS_COMPLIANCE_OFFICER), 201)


def read_patron(api: ApiClient, patron_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a patron with both risk scores and both status dimensions."""
    return get_success_data(api.get_patron(patron_id, headers or HEADERS_COMPLIANCE_OFFICER))


def patron_version(api: ApiClient, patron_id: str) -> int:
    """The patron's current version, for the delegation stale-view guard."""
    return read_patron(api, patron_id)["version"]


def set_card_status(
    api: ApiClient,
    patron_id: str,
    action: str,
    reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Move the card axis by hand: SUSPEND, REINSTATE or REVOKE."""
    payload = factories.card_status_payload(action, reason)
    return get_success_data(
        api.set_card_status(patron_id, payload, headers or HEADERS_COMPLIANCE_OFFICER)
    )


def record_compliance_review(
    api: ApiClient,
    patron_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record a resale strike or clear the watch."""
    payload = factories.compliance_review_payload(decision)
    return get_success_data(
        api.compliance_review(patron_id, payload, headers or HEADERS_COMPLIANCE_OFFICER)
    )


def create_delegation(
    api: ApiClient,
    sponsor_patron_id: str,
    delegate_patron_id: str,
    valid_from: str = AUG_01,
    valid_to: str = AUG_31,
    per_sale_spend_cap_cents: int = 100000,
    expected_delegate_patron_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Grant authorized-shopper privileges, guarded by the delegate's version."""
    if expected_delegate_patron_version is None:
        expected_delegate_patron_version = patron_version(api, delegate_patron_id)
    payload = factories.delegation_payload(
        sponsor_patron_id=sponsor_patron_id,
        delegate_patron_id=delegate_patron_id,
        expected_delegate_patron_version=expected_delegate_patron_version,
        valid_from=valid_from,
        valid_to=valid_to,
        per_sale_spend_cap_cents=per_sale_spend_cap_cents,
    )
    return get_success_data(
        api.create_delegation(payload, headers or HEADERS_COMPLIANCE_OFFICER), 201
    )


def read_delegation(api: ApiClient, delegation_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one delegation."""
    return get_success_data(
        api.get_delegation(delegation_id, headers or HEADERS_COMPLIANCE_OFFICER)
    )


def revoke_delegation(
    api: ApiClient,
    delegation_id: str,
    reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Withdraw a grant; its open sales are flagged."""
    payload = factories.delegation_revoke_payload(reason)
    return get_success_data(
        api.revoke_delegation(delegation_id, payload, headers or HEADERS_COMPLIANCE_OFFICER)
    )


def create_product(
    api: ApiClient,
    sku: str,
    name: Optional[str] = None,
    category: str = "GROCERY_STAPLE",
    unit_cost_cents: int = 1000,
    unit_weight_grams: Optional[int] = None,
    quantity_limit_per_visit: Optional[int] = None,
    resale_restricted: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a worldwide item record."""
    payload = factories.product_payload(
        sku=sku,
        name=name,
        category=category,
        unit_cost_cents=unit_cost_cents,
        unit_weight_grams=unit_weight_grams,
        quantity_limit_per_visit=quantity_limit_per_visit,
        resale_restricted=resale_restricted,
    )
    return get_success_data(api.create_product(payload, headers or HEADERS_ASSORTMENT_PLANNER), 201)


def create_assortment(
    api: ApiClient,
    store_id: str,
    product_id: str,
    shelf_block: str = "A1",
    facings: int = 4,
    supply_mode: str = "WAREHOUSE",
    vendor_name: Optional[str] = None,
    promo_allowance_bp: Optional[int] = None,
    promo_window_start: Optional[str] = None,
    promo_window_end: Optional[str] = None,
    effective_from: str = AUG_01,
    effective_to: str = AUG_31,
    overseas_shipping_allowance_cents: Optional[int] = None,
    expected_store_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Allocate an item to a shelf block, guarded by the store's version."""
    if expected_store_version is None:
        expected_store_version = store_version(api, store_id)
    payload = factories.assortment_payload(
        store_id=store_id,
        product_id=product_id,
        expected_store_version=expected_store_version,
        shelf_block=shelf_block,
        facings=facings,
        supply_mode=supply_mode,
        vendor_name=vendor_name,
        promo_allowance_bp=promo_allowance_bp,
        promo_window_start=promo_window_start,
        promo_window_end=promo_window_end,
        effective_from=effective_from,
        effective_to=effective_to,
        overseas_shipping_allowance_cents=overseas_shipping_allowance_cents,
    )
    return get_success_data(
        api.create_assortment(payload, headers or HEADERS_ASSORTMENT_PLANNER), 201
    )


def retire_assortment(
    api: ApiClient,
    assortment_id: str,
    reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Retire an allocation, releasing its facings and cascading three hops."""
    payload = factories.assortment_retire_payload(reason)
    return get_success_data(
        api.retire_assortment(assortment_id, payload, headers or HEADERS_ASSORTMENT_PLANNER)
    )


def open_sale(
    api: ApiClient,
    store_id: str,
    patron_id: str,
    acting_delegation_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a visit; business_date is stamped from the logical clock."""
    payload = factories.sale_payload(store_id, patron_id, acting_delegation_id)
    return get_success_data(api.open_sale(payload, headers or HEADERS_STORE_CASHIER), 201)


def add_line(
    api: ApiClient,
    sale_id: str,
    product_id: str,
    quantity: int = 1,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Ring an item onto an open visit."""
    payload = factories.sale_line_payload(product_id, quantity)
    return get_success_data(
        api.add_sale_line(sale_id, payload, headers or HEADERS_STORE_CASHIER), 201
    )


def tender_sale(
    api: ApiClient,
    sale_id: str,
    collected_tax_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Tender a visit: settle the allowance, post the ledger, cascade the funds."""
    payload = factories.tender_payload(collected_tax_cents)
    return get_success_data(api.tender_sale(sale_id, payload, headers or HEADERS_STORE_CASHIER))


def void_sale(
    api: ApiClient,
    sale_id: str,
    voided_reason: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Void a visit; a tendered visit is reversed in the ledger."""
    payload = factories.void_payload(voided_reason)
    return get_success_data(api.void_sale(sale_id, payload, headers or HEADERS_COMPLIANCE_OFFICER))


def read_sale(api: ApiClient, sale_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a visit with every computed money field."""
    return get_success_data(api.get_sale(sale_id, headers or HEADERS_STORE_CASHIER))


def create_mwr_program(
    api: ApiClient,
    store_id: str,
    name: str = "Youth Sports",
    priority_rank: int = 1,
    funding_ceiling_cents: int = 100000,
    status: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register a dividend waterfall bucket."""
    payload = factories.mwr_program_payload(
        store_id=store_id,
        name=name,
        priority_rank=priority_rank,
        funding_ceiling_cents=funding_ceiling_cents,
        status=status,
    )
    return get_success_data(api.create_mwr_program(payload, headers or HEADERS_BOARD_OFFICER), 201)


def create_capital_project(
    api: ApiClient,
    store_id: str,
    title: str = "Deli Case Replacement",
    requested_amount_cents: int = 250000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draft a project; the contingency tier and obligation compute at creation."""
    payload = factories.capital_project_payload(
        store_id=store_id,
        title=title,
        requested_amount_cents=requested_amount_cents,
    )
    return get_success_data(
        api.create_capital_project(payload, headers or HEADERS_FUND_CONTROLLER), 201
    )


def submit_capital_project(
    api: ApiClient,
    project_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Submit a draft or returned project; the caller becomes submitted_by_user_id."""
    return get_success_data(
        api.submit_capital_project(project_id, None, headers or HEADERS_FUND_CONTROLLER)
    )


def decide_capital_project(
    api: ApiClient,
    project_id: str,
    decision: str,
    note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Render the board decision: APPROVE, RETURN or REJECT."""
    payload = factories.project_decision_payload(decision, note)
    return get_success_data(
        api.decide_capital_project(project_id, payload, headers or HEADERS_BOARD_OFFICER)
    )


def close_capital_project(
    api: ApiClient,
    project_id: str,
    outlay_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Close an approved project, releasing the whole obligation."""
    payload = factories.project_close_payload(outlay_cents)
    return get_success_data(
        api.close_capital_project(project_id, payload, headers or HEADERS_FUND_CONTROLLER)
    )


def close_period(
    api: ApiClient,
    store_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run the store's six-step period-close checkpoint."""
    return get_success_data(api.close_period(store_id, None, headers or HEADERS_FUND_CONTROLLER))


def create_special_order(
    api: ApiClient,
    store_id: str,
    patron_id: str,
    product_id: str,
    quantity: int = 1,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Place a special order; it starts SUBMITTED with every figure at 0."""
    payload = factories.special_order_payload(store_id, patron_id, product_id, quantity)
    return get_success_data(
        api.create_special_order(payload, headers or HEADERS_STORE_CASHIER), 201
    )


def route_special_order(
    api: ApiClient,
    order_id: str,
    route: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Fork the order onto a fill route."""
    payload = factories.route_payload(route)
    return get_success_data(
        api.route_special_order(order_id, payload, headers or HEADERS_STORE_CASHIER)
    )


def cancel_special_order(
    api: ApiClient,
    order_id: str,
    cancelled_reason: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Cancel a non-terminal order, releasing exactly its committed allowance."""
    payload = factories.cancel_payload(cancelled_reason)
    return get_success_data(
        api.cancel_special_order(order_id, payload, headers or HEADERS_STORE_CASHIER)
    )


def read_special_order(api: ApiClient, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one special order with its shipping computation."""
    return get_success_data(api.get_special_order(order_id, headers or HEADERS_STORE_CASHIER))


def read_ledger(
    api: ApiClient,
    store_id: str,
    fund: Optional[str] = None,
    entry_type: Optional[str] = None,
    limit: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """The store's append-only fund ledger in created_at ascending order."""
    params: Dict[str, Any] = {}
    if fund is not None:
        params["fund"] = fund
    if entry_type is not None:
        params["entry_type"] = entry_type
    if limit is not None:
        params["limit"] = limit
    response = api.list_fund_ledger(store_id, params or None, headers or HEADERS_FUND_CONTROLLER)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 2: shelf-ready scenes
# ---------------------------------------------------------------------------


def setup_store_with_product(
    api: ApiClient,
    store_name: str = "Fort Example Commissary",
    channel: str = "COMMISSARY",
    region: str = "CONUS",
    surcharge_rate_bp: Optional[int] = None,
    exchange_markup_bp: Optional[int] = None,
    shelf_block_capacity_facings: Optional[int] = None,
    sku: str = "SKU-EX-100",
    product_name: Optional[str] = None,
    category: str = "GROCERY_STAPLE",
    unit_cost_cents: int = 1000,
    unit_weight_grams: Optional[int] = None,
    quantity_limit_per_visit: Optional[int] = None,
    resale_restricted: Optional[bool] = None,
    shelf_block: str = "A1",
    facings: int = 4,
    supply_mode: str = "WAREHOUSE",
    vendor_name: Optional[str] = None,
    promo_allowance_bp: Optional[int] = None,
    promo_window_start: Optional[str] = None,
    promo_window_end: Optional[str] = None,
    effective_from: str = AUG_01,
    effective_to: str = AUG_31,
    overseas_shipping_allowance_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """A store, an item and a live allocation of that item onto a shelf block."""
    store = create_store(
        api,
        name=store_name,
        channel=channel,
        region=region,
        surcharge_rate_bp=surcharge_rate_bp,
        exchange_markup_bp=exchange_markup_bp,
        shelf_block_capacity_facings=shelf_block_capacity_facings,
    )
    product = create_product(
        api,
        sku=sku,
        name=product_name,
        category=category,
        unit_cost_cents=unit_cost_cents,
        unit_weight_grams=unit_weight_grams,
        quantity_limit_per_visit=quantity_limit_per_visit,
        resale_restricted=resale_restricted,
    )
    assortment = create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block=shelf_block,
        facings=facings,
        supply_mode=supply_mode,
        vendor_name=vendor_name,
        promo_allowance_bp=promo_allowance_bp,
        promo_window_start=promo_window_start,
        promo_window_end=promo_window_end,
        effective_from=effective_from,
        effective_to=effective_to,
        overseas_shipping_allowance_cents=overseas_shipping_allowance_cents,
        expected_store_version=store["version"],
    )
    return {"store": store, "product": product, "assortment": assortment}


def setup_visit(
    api: ApiClient,
    patron_name: str = "SGT A Example",
    id_card_class: str = "ACTIVE_DUTY",
    **scene_kwargs: Any,
) -> Dict[str, Any]:
    """A shelf-ready store plus an enrolled patron and an open visit."""
    scene = setup_store_with_product(api, **scene_kwargs)
    patron = create_patron(api, full_name=patron_name, id_card_class=id_card_class)
    sale = open_sale(api, scene["store"]["id"], patron["id"])
    scene["patron"] = patron
    scene["sale"] = sale
    return scene


def setup_tendered_visit(
    api: ApiClient,
    quantity: int = 1,
    patron_name: str = "SGT A Example",
    id_card_class: str = "ACTIVE_DUTY",
    **scene_kwargs: Any,
) -> Dict[str, Any]:
    """A visit with one line rung and then tendered, so the ledger has moved."""
    scene = setup_visit(
        api, patron_name=patron_name, id_card_class=id_card_class, **scene_kwargs
    )
    scene["line"] = add_line(api, scene["sale"]["id"], scene["product"]["id"], quantity)
    scene["sale"] = tender_sale(api, scene["sale"]["id"])
    return scene


def setup_delegated_visit(
    api: ApiClient,
    sponsor_card_class: str = "RETIREE",
    delegate_card_class: str = "ACTIVE_DUTY",
    valid_from: str = AUG_01,
    valid_to: str = AUG_31,
    per_sale_spend_cap_cents: int = 100000,
    open_the_visit: bool = True,
    **scene_kwargs: Any,
) -> Dict[str, Any]:
    """A sponsor, a delegate, a live grant and -- optionally -- a visit under it."""
    scene = setup_store_with_product(api, **scene_kwargs)
    sponsor = create_patron(api, full_name="MSG S Sponsor", id_card_class=sponsor_card_class)
    delegate = create_patron(api, full_name="SPC D Delegate", id_card_class=delegate_card_class)
    delegation = create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=valid_from,
        valid_to=valid_to,
        per_sale_spend_cap_cents=per_sale_spend_cap_cents,
        expected_delegate_patron_version=delegate["version"],
    )
    scene["sponsor"] = sponsor
    scene["delegate"] = delegate
    scene["delegation"] = delegation
    if open_the_visit:
        scene["sale"] = open_sale(
            api,
            scene["store"]["id"],
            sponsor["id"],
            acting_delegation_id=delegation["id"],
        )
    return scene


def setup_special_order(
    api: ApiClient,
    quantity: int = 1,
    route: Optional[str] = None,
    patron_name: str = "SGT A Example",
    id_card_class: str = "ACTIVE_DUTY",
    **scene_kwargs: Any,
) -> Dict[str, Any]:
    """A placed special order, optionally already routed onto a fill route."""
    scene = setup_store_with_product(api, **scene_kwargs)
    patron = create_patron(api, full_name=patron_name, id_card_class=id_card_class)
    order = create_special_order(
        api, scene["store"]["id"], patron["id"], scene["product"]["id"], quantity
    )
    if route is not None:
        order = route_special_order(api, order["id"], route)
    scene["patron"] = patron
    scene["order"] = order
    return scene


# ---------------------------------------------------------------------------
# Tier 3: fiscal scenes
# ---------------------------------------------------------------------------


def setup_funded_store(
    api: ApiClient,
    surcharge_target_hint_cents: int = 600000,
    store_name: str = "Fort Example Commissary",
    channel: str = "COMMISSARY",
    region: str = "CONUS",
    surcharge_rate_bp: int = 1000,
    unit_cost_cents: int = 100000,
    quantity: int = 60,
    sku: str = "SKU-FUND-100000",
    shelf_block: str = "F1",
    facings: int = 10,
) -> Dict[str, Any]:
    """A store whose surcharge fund has been filled by one large tendered visit.

    The only way money enters the surcharge fund is a tendered sale, so the
    scene rings a high-value basket at a store dialled to the maximum surcharge
    rate. ``surcharge_target_hint_cents`` documents the intent of the caller's
    chosen quantity; it is not sent anywhere.
    """
    scene = setup_store_with_product(
        api,
        store_name=store_name,
        channel=channel,
        region=region,
        surcharge_rate_bp=surcharge_rate_bp,
        sku=sku,
        unit_cost_cents=unit_cost_cents,
        shelf_block=shelf_block,
        facings=facings,
    )
    patron = create_patron(api, full_name="MSG L Funder", id_card_class="ACTIVE_DUTY")
    sale = open_sale(api, scene["store"]["id"], patron["id"])
    add_line(api, sale["id"], scene["product"]["id"], quantity)
    scene["patron"] = patron
    scene["sale"] = tender_sale(api, sale["id"])
    scene["store"] = read_store(api, scene["store"]["id"])
    scene["surcharge_target_hint_cents"] = surcharge_target_hint_cents
    return scene


def setup_approved_project(
    api: ApiClient,
    requested_amount_cents: int = 400000,
    submitter_user_id: str = "sfc-050",
    decider_user_id: str = "mwr-050",
    store_id: Optional[str] = None,
    title: str = "Freezer Compressor Overhaul",
    **funded_store_kwargs: Any,
) -> Dict[str, Any]:
    """A project taken all the way to APPROVED against a funded store.

    The submitting controller and the deciding officer are distinct identities,
    and the submitter is recorded so that a later close by that same identity can
    be shown to be refused.
    """
    scene: Dict[str, Any]
    if store_id is None:
        scene = setup_funded_store(api, **funded_store_kwargs)
        store_id = scene["store"]["id"]
    else:
        scene = {"store": read_store(api, store_id)}
    project = create_capital_project(
        api,
        store_id=store_id,
        title=title,
        requested_amount_cents=requested_amount_cents,
    )
    project = submit_capital_project(
        api, project["id"], make_fund_controller_headers(submitter_user_id)
    )
    project = decide_capital_project(
        api,
        project["id"],
        "APPROVE",
        headers=make_board_officer_headers(decider_user_id),
    )
    scene["project"] = project
    scene["submitter_user_id"] = submitter_user_id
    scene["decider_user_id"] = decider_user_id
    scene["store"] = read_store(api, store_id)
    return scene


def setup_restricted_watch_patron(
    api: ApiClient,
    sku: str = "SKU-RST-1000",
    unit_cost_cents: int = 1000,
    shelf_block: str = "Z1",
    facings: int = 6,
    separate_sales: int = 8,
    **scene_kwargs: Any,
) -> Dict[str, Any]:
    """A patron driven to RESTRICTED on the watch axis by controlled-item units.

    Each unit of a resale-restricted item is worth 12 points, so eight units
    spread over eight separate open visits carry the rolling score to 96, past
    the RESTRICTED threshold of 85.
    """
    scene = setup_store_with_product(
        api,
        sku=sku,
        unit_cost_cents=unit_cost_cents,
        resale_restricted=True,
        shelf_block=shelf_block,
        facings=facings,
        **scene_kwargs,
    )
    patron = create_patron(api, full_name="SFC R Watched", id_card_class="ACTIVE_DUTY")
    sales: List[Dict[str, Any]] = []
    for _ in range(separate_sales):
        sale = open_sale(api, scene["store"]["id"], patron["id"])
        add_line(api, sale["id"], scene["product"]["id"], 1)
        sales.append(sale)
    scene["patron"] = read_patron(api, patron["id"])
    scene["sales"] = sales
    return scene


def patron_headers_for(patron: Dict[str, Any]) -> Dict[str, str]:
    """Headers for a patron caller: the caller id is that patron's own record id."""
    return make_patron_headers(patron["id"])
