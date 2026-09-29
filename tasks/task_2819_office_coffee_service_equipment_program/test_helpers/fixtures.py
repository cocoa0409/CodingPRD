"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints;
nothing is assumed to be seeded. Setup calls go through the lenient success
reader so a broken preamble reports as a setup failure rather than as an
obscure assertion error.

Money is passed as a JSON number of whole cents, catalog prices as a JSON
number of whole micro-dollars, and every instant as a full ISO 8601 UTC
instant.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as _f
from .api_client import api_client
from .constants import ANCHOR_MONDAY, PRODUCT_CATEGORIES, PRODUCT_PRICES_MICROS
from .test_users import (
    TEST_USERS,
    make_customer_contact_headers,
    make_route_technician_headers,
)

PA = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

def _product_spec(label: str) -> tuple:
    """One catalog entry: label, category, sku, unit price in micros, green flag.

    The label is the key callers use to reach the created product; two pantry
    labels deliberately share the PANTRY category so a single invoice can carry
    two pantry lines at different unit prices.
    """
    return (
        label,
        PRODUCT_CATEGORIES[label],
        f"SKU-{label}-001",
        PRODUCT_PRICES_MICROS[label],
        label == "COFFEE",
    )


# The canonical catalog, in creation order. Only COFFEE is green-linked.
CATALOG_SPEC = [
    _product_spec(label)
    for label in ("COFFEE", "CREAMER", "TEA", "WATER", "PANTRY")
]

# Six products: the canonical five plus a second, cheaper pantry item, so an
# invoice can carry two fractional-cent lines of the same category.
CATALOG_SPEC_WITH_TWO_PANTRY = CATALOG_SPEC + [_product_spec("PANTRY_CUP")]

# Narrow catalogs, used when a recipe needs an exact par-line count per site.
CATALOG_SPEC_COFFEE_ONLY = [_product_spec("COFFEE")]
CATALOG_SPEC_COFFEE_TEA = [_product_spec("COFFEE"), _product_spec("TEA")]
CATALOG_SPEC_COFFEE_CREAMER = [_product_spec("COFFEE"), _product_spec("CREAMER")]
CATALOG_SPEC_THREE_ALLIED = [
    _product_spec(label) for label in ("COFFEE", "CREAMER", "TEA", "PANTRY")
]


# --- Global capabilities -----------------------------------------------------


def set_clock(to_iso8601: str, headers: dict = PA) -> None:
    """Move the server's logical clock to an exact instant."""
    get_success_data(api_client.set_clock(_f.set_clock_payload(to_iso8601), headers))


def set_market_index(index_micros: int, headers: dict = PA) -> None:
    """Replace the green coffee market quote."""
    get_success_data(
        api_client.set_green_index(_f.set_green_index_payload(index_micros), headers)
    )


# --- Single-resource creators -----------------------------------------------


def create_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(_f.create_route_payload(**overrides), PA))


def create_model(**overrides) -> dict:
    return get_success_data(
        api_client.create_equipment_model(_f.create_equipment_model_payload(**overrides), PA)
    )


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product_item(_f.create_product_item_payload(**overrides), PA)
    )


def create_asset(model_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_equipment_asset(
            _f.create_equipment_asset_payload(model_id, **overrides), PA
        )
    )


def create_account(**overrides) -> dict:
    return get_success_data(api_client.create_account(_f.create_account_payload(**overrides), AM))


def create_site(account_id: str, route_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_site(_f.create_site_payload(account_id, route_id, **overrides), AM)
    )


def plan_site(site_id: str, brew_style: str = "DRIP") -> dict:
    return get_success_data(
        api_client.size_and_plan_site(site_id, _f.size_and_plan_payload(brew_style), AM)
    )


def read_site(site_id: str) -> dict:
    return get_success_data(api_client.get_site(site_id, AM))


def read_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, AM))


def read_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, PA))


def read_asset(asset_id: str) -> dict:
    return get_success_data(api_client.get_equipment_asset(asset_id, PA))


def read_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_placement(placement_id, AM))


def read_visit(visit_id: str) -> dict:
    return get_success_data(api_client.get_visit(visit_id, AM))


def read_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, PA))


def read_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, BS))


def read_adjustment(adjustment_id: str) -> dict:
    return get_success_data(api_client.get_price_adjustment(adjustment_id, BS))


def create_placement(site_id: str, asset_id: str, expected_site_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_placement(
            _f.create_placement_payload(site_id, asset_id, expected_site_version, **overrides),
            AM,
        )
    )


def place_asset_at_site(site: dict, asset_id: str, **overrides) -> dict:
    """Install a brewer using the site's current version as the expected version."""
    fresh = read_site(site["id"])
    return create_placement(fresh["id"], asset_id, fresh["version"], **overrides)


def schedule_visit(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_visit(_f.create_visit_payload(site_id, **overrides), AM)
    )


def append_line(visit_id: str, route_id: str, product_id: str, requested_units: int) -> dict:
    return get_success_data(
        api_client.append_visit_line(
            visit_id,
            _f.append_visit_line_payload(product_id, requested_units),
            make_route_technician_headers(route_id),
        )
    )


def complete_visit(visit_id: str, route_id: str, delivered_lines=None) -> dict:
    return get_success_data(
        api_client.complete_visit(
            visit_id,
            _f.complete_visit_payload(delivered_lines or []),
            make_route_technician_headers(route_id),
        )
    )


def void_visit(visit_id: str, void_reason: str = "Recorded against the wrong stop") -> dict:
    return get_success_data(
        api_client.void_visit(visit_id, _f.void_visit_payload(void_reason), PA)
    )


def evaluate_compliance(placement_id: str) -> dict:
    return get_success_data(api_client.evaluate_placement_compliance(placement_id, {}, BS))


def evaluate_posture(site_id: str, headers: dict = AM) -> dict:
    return get_success_data(api_client.evaluate_service_posture(site_id, {}, headers))


def recompute_attachment(account_id: str, headers: dict = BS) -> dict:
    return get_success_data(api_client.recompute_allied_attachment(account_id, {}, headers))


def cancel_account(account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_account(account_id, _f.cancel_account_payload(**overrides), AM)
    )


def retrieve_placement(placement_id: str, condition: str = "SERVICEABLE") -> dict:
    return get_success_data(
        api_client.retrieve_placement(placement_id, _f.retrieve_placement_payload(condition), AM)
    )


def create_work_order(asset_id: str, route_id: str, wo_type: str = "REPAIR") -> dict:
    return get_success_data(
        api_client.create_work_order(
            _f.create_work_order_payload(asset_id, wo_type),
            make_route_technician_headers(route_id),
        )
    )


def advance_work_order(
    work_order_id: str, route_id: str, to_status: str, **fields
) -> dict:
    return get_success_data(
        api_client.advance_work_order(
            work_order_id,
            _f.advance_work_order_payload(to_status, **fields),
            make_route_technician_headers(route_id),
        )
    )


def loaner_swap(
    work_order_id: str,
    route_id: str,
    loaner_asset_id: str,
    loaner_out_date: str,
    loaner_due_back_date: str,
) -> dict:
    return get_success_data(
        api_client.loaner_swap(
            work_order_id,
            _f.loaner_swap_payload(loaner_asset_id, loaner_out_date, loaner_due_back_date),
            make_route_technician_headers(route_id),
        )
    )


def loaner_return(work_order_id: str, route_id: str, returned_on: str) -> dict:
    return get_success_data(
        api_client.loaner_return(
            work_order_id,
            _f.loaner_return_payload(returned_on),
            make_route_technician_headers(route_id),
        )
    )


def assemble_invoice(
    account_id: str, period_start: str, period_end: str, expected_account_version: int, **overrides
) -> dict:
    return get_success_data(
        api_client.create_invoice(
            _f.create_invoice_payload(
                account_id, period_start, period_end, expected_account_version, **overrides
            ),
            BS,
        )
    )


def assemble_invoice_for(account_id: str, period_start: str, period_end: str, **overrides) -> dict:
    """Assemble a draft using the account's current version as the expected version."""
    account = read_account(account_id)
    return assemble_invoice(
        account_id, period_start, period_end, account["version"], **overrides
    )


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, {}, BS))


def credit_invoice(
    invoice_id: str, target_line_id: str, amount_cents: int, credit_reason: str = "Equipment returned"
) -> dict:
    return get_success_data(
        api_client.credit_invoice(
            invoice_id,
            _f.credit_invoice_payload(target_line_id, amount_cents, credit_reason),
            BS,
        )
    )


def propose_adjustment(account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_price_adjustment(
            _f.create_price_adjustment_payload(account_id, **overrides), BS
        )
    )


def respond_adjustment(adjustment_id: str, account_id: str, disposition: str, **fields) -> dict:
    return get_success_data(
        api_client.respond_price_adjustment(
            adjustment_id,
            _f.respond_payload(disposition, **fields),
            make_customer_contact_headers(account_id),
        )
    )


def revise_adjustment(adjustment_id: str, revised_adjustment_pct_bps: int) -> dict:
    return get_success_data(
        api_client.revise_price_adjustment(
            adjustment_id, _f.revise_payload(revised_adjustment_pct_bps), BS
        )
    )


def create_manual_par_line(site_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_par_level(_f.create_par_level_payload(site_id, product_id, **overrides), AM)
    )


def override_par_line(par_level_id: str, **fields) -> dict:
    return get_success_data(
        api_client.update_par_level(par_level_id, _f.update_par_level_payload(**fields), AM)
    )


# --- Listing readers ---------------------------------------------------------


def list_par_lines(site_id: str, **extra_params) -> list:
    params = {"site_id": site_id, "limit": 100}
    params.update(extra_params)
    return get_success_data(api_client.list_par_levels(AM, params=params))


def par_lines_by_label(site_id: str, products: dict) -> dict:
    """Map catalog label to that site's par line for the labelled product."""
    by_product = {row["product_id"]: row for row in list_par_lines(site_id)}
    return {
        label: by_product[product["id"]]
        for label, product in products.items()
        if product["id"] in by_product
    }


# Historical name kept so either spelling reaches the same reader.
par_lines_by_category = par_lines_by_label


def par_line_for(site_id: str, product_id: str) -> dict:
    rows = list_par_lines(site_id, product_id=product_id)
    assert rows, f"no par line for product {product_id} at site {site_id}"
    return rows[0]


def list_invoice_lines(invoice_id: str, **extra_params) -> list:
    params = {"invoice_id": invoice_id, "limit": 100}
    params.update(extra_params)
    return get_success_data(api_client.list_invoice_lines(BS, params=params))


def lines_by_type(invoice_id: str) -> dict:
    """Group an invoice's lines by line_type."""
    grouped = {}
    for row in list_invoice_lines(invoice_id):
        grouped.setdefault(row["line_type"], []).append(row)
    return grouped


# --- Tier 1 / Tier 2: catalog and planned site -------------------------------


def setup_catalog(
    clock: str = ANCHOR_MONDAY,
    service_day: str = "MON",
    capacity_minutes: int = 480,
    travel_buffer_minutes: int = 30,
    catalog_spec=None,
    model_overrides=None,
) -> dict:
    """Clock anchored, one route, one brewer model, the five-category catalog.

    Returns {"route", "model", "products"} where products maps catalog label to
    the created catalog product.
    """
    set_clock(clock)
    route = create_route(
        service_day=service_day,
        capacity_minutes=capacity_minutes,
        travel_buffer_minutes=travel_buffer_minutes,
    )
    model = create_model(**(model_overrides or {}))
    products = {}
    for label, category, sku, price_micros, green_linked in catalog_spec or CATALOG_SPEC:
        products[label] = create_product(
            sku=sku,
            category=category,
            base_unit_price_micros=price_micros,
            pack_units=1,
            green_coffee_linked=green_linked,
        )
    return {"route": route, "model": model, "products": products}


def setup_planned_site(
    clock: str = ANCHOR_MONDAY,
    account_overrides=None,
    site_overrides=None,
    brew_style: str = "DRIP",
    **catalog_kwargs,
) -> dict:
    """Catalog + account + one break-room site that has been planned.

    Returns {"route", "model", "products", "account", "site"}.
    """
    base = setup_catalog(clock=clock, **catalog_kwargs)
    account = create_account(**(account_overrides or {}))
    site = create_site(account["id"], base["route"]["id"], **(site_overrides or {}))
    site = plan_site(site["id"], brew_style)
    base["account"] = account
    base["site"] = site
    return base


def setup_second_site(base: dict, **site_overrides) -> dict:
    """Add a second planned break room to the same account and route."""
    overrides = {"site_name": "Second Floor Break Room"}
    overrides.update(site_overrides)
    site = create_site(base["account"]["id"], base["route"]["id"], **overrides)
    return plan_site(site["id"])


def setup_placed_site(
    clock: str = ANCHOR_MONDAY,
    terms_type: str = "LOAN",
    minimum_purchase_cents: int = 75000,
    min_term_months: int = 12,
    serial_number: str = "SN-0001",
    **planned_kwargs,
) -> dict:
    """Planned site with one PLACEMENT asset installed under the given terms.

    Returns {"route", "model", "products", "account", "site", "asset",
    "placement"}.
    """
    base = setup_planned_site(clock=clock, **planned_kwargs)
    asset = create_asset(base["model"]["id"], serial_number=serial_number)
    placement = place_asset_at_site(
        base["site"],
        asset["id"],
        terms_type=terms_type,
        minimum_purchase_cents=minimum_purchase_cents,
        min_term_months=min_term_months,
    )
    base["asset"] = asset
    base["placement"] = placement
    base["site"] = read_site(base["site"]["id"])
    base["account"] = read_account(base["account"]["id"])
    return base


# --- Tier 3: visit lifecycle shortcuts ---------------------------------------


def schedule_stop_with_lines(
    base: dict,
    requested: dict,
    site: dict = None,
    window_start: str = "2026-08-03T09:00:00Z",
    window_end: str = "2026-08-03T09:45:00Z",
    planned_minutes: int = 45,
) -> dict:
    """Schedule one stop and append one requested line per named category."""
    target = site or base["site"]
    visit = schedule_visit(
        target["id"],
        window_start=window_start,
        window_end=window_end,
        planned_minutes=planned_minutes,
    )
    for category, units in requested.items():
        visit = append_line(
            visit["id"], base["route"]["id"], base["products"][category]["id"], units
        )
    return visit


def complete_stop(
    base: dict,
    visit: dict,
    delivered: dict = None,
    complete_at: str = None,
) -> dict:
    """Move the clock to the reporting instant and report the stop."""
    if complete_at is None:
        complete_at = visit["window_start"]
    set_clock(complete_at)
    delivered_lines = [
        _f.delivered_line(base["products"][category]["id"], units)
        for category, units in (delivered or {}).items()
    ]
    return complete_visit(visit["id"], base["route"]["id"], delivered_lines)


def setup_completed_visit(
    requested: dict = None,
    delivered: dict = None,
    window_start: str = "2026-08-03T09:00:00Z",
    window_end: str = "2026-08-03T09:45:00Z",
    planned_minutes: int = 45,
    complete_at: str = None,
    base: dict = None,
    **placed_kwargs,
) -> dict:
    """Placed site with one COMPLETED stop carrying the given delivered units.

    Returns the placed-site dictionary with a "visit" key added.
    """
    base = base or setup_placed_site(**placed_kwargs)
    requested = requested if requested is not None else {"COFFEE": 20}
    delivered = delivered if delivered is not None else dict(requested)
    visit = schedule_stop_with_lines(
        base,
        requested,
        window_start=window_start,
        window_end=window_end,
        planned_minutes=planned_minutes,
    )
    base["visit"] = complete_stop(base, visit, delivered, complete_at)
    base["site"] = read_site(base["site"]["id"])
    return base


# --- Tier 4: accumulation and threshold targeting ----------------------------


def drive_site_to_two_stockouts(
    base: dict,
    site: dict = None,
    first_window_start: str = "2026-08-03T09:00:00Z",
    first_window_end: str = "2026-08-03T09:45:00Z",
    second_window_start: str = "2026-08-31T09:00:00Z",
    second_window_end: str = "2026-08-31T09:45:00Z",
    categories=("COFFEE", "TEA"),
) -> dict:
    """Take a planned site to exactly two stockout par lines.

    A first stop delivers a modest quantity of two products; a second stop four
    weeks later delivers nothing, so the modelled draw empties both shelves and
    each line ends with a zero shelf quantity and a positive cumulative
    delivery. Two stockouts weigh 40.0, which is the escalation threshold.

    Returns {"first_visit", "second_visit", "site"}.
    """
    target = site or base["site"]
    first = schedule_stop_with_lines(
        base,
        {categories[0]: 20, categories[1]: 10},
        site=target,
        window_start=first_window_start,
        window_end=first_window_end,
    )
    first = complete_stop(base, first, {categories[0]: 20, categories[1]: 10})

    second = schedule_stop_with_lines(
        base,
        {categories[0]: 1, categories[1]: 1},
        site=target,
        window_start=second_window_start,
        window_end=second_window_end,
    )
    second = complete_stop(base, second, {categories[0]: 0, categories[1]: 0})
    return {
        "first_visit": first,
        "second_visit": second,
        "site": read_site(target["id"]),
    }


def setup_account_at_risk(base: dict = None, **placed_kwargs) -> dict:
    """Two break rooms of one account, both driven to ESCALATED, carrying the
    account to AT_RISK.

    Returns the base dictionary with "site_two", "escalation_one" and
    "escalation_two" keys added and "account"/"site" re-read.
    """
    base = base or setup_placed_site(**placed_kwargs)
    site_two = setup_second_site(base)
    base["site_two"] = site_two
    base["escalation_one"] = drive_site_to_two_stockouts(base)
    base["escalation_two"] = drive_site_to_two_stockouts(
        base,
        site=site_two,
        first_window_start="2026-08-03T10:15:00Z",
        first_window_end="2026-08-03T11:00:00Z",
        second_window_start="2026-08-31T10:15:00Z",
        second_window_end="2026-08-31T11:00:00Z",
    )
    base["site"] = read_site(base["site"]["id"])
    base["account"] = read_account(base["account"]["id"])
    return base


def setup_six_model_catalog(clock: str = ANCHOR_MONDAY) -> dict:
    """A catalog whose brewer models force every tie-break of the sizing
    selector to be exercised: capacity ascending, then monthly rent ascending,
    then registration order.

    Returns {"route", "products", "models"} where models maps model_code to the
    created model.
    """
    set_clock(clock)
    route = create_route()
    specs = [
        ("TOO-SMALL", 20, 4000),
        ("TIE-EARLY", 30, 4500),
        ("TIE-LATE", 30, 4500),
        ("PRICIER-TIE", 30, 9000),
        ("BIGGER", 60, 1000),
        ("BIGGEST", 90, 500),
    ]
    models = {}
    for code, capacity, rent in specs:
        models[code] = create_model(
            model_code=code,
            cups_per_hour_capacity=capacity,
            monthly_rent_cents=rent,
            min_headcount=1,
            max_headcount=250,
        )
    products = {}
    for label, category, sku, price_micros, green_linked in CATALOG_SPEC:
        products[label] = create_product(
            sku=sku,
            category=category,
            base_unit_price_micros=price_micros,
            pack_units=1,
            green_coffee_linked=green_linked,
        )
    return {"route": route, "models": models, "products": products}


# --- Tier 4: maintenance work orders ----------------------------------------


def setup_work_order(
    base: dict = None,
    wo_type: str = "REPAIR",
    loaner_serial: str = "SN-LOANER-1",
    with_loaner_asset: bool = True,
    **placed_kwargs,
) -> dict:
    """Placed brewer with an OPEN work order against it, plus a spare LOANER
    asset in stock ready to be swapped in.

    Returns the placed-site dictionary with "work_order" and (when requested)
    "loaner_asset" keys added.
    """
    base = base or setup_placed_site(**placed_kwargs)
    base["work_order"] = create_work_order(
        base["asset"]["id"], base["route"]["id"], wo_type
    )
    if with_loaner_asset:
        base["loaner_asset"] = create_asset(
            base["model"]["id"], serial_number=loaner_serial, asset_role="LOANER"
        )
    return base


def setup_work_order_in_progress(**kwargs) -> dict:
    """Same as setup_work_order but already advanced OPEN to IN_PROGRESS."""
    base = setup_work_order(**kwargs)
    base["work_order"] = advance_work_order(
        base["work_order"]["id"], base["route"]["id"], "IN_PROGRESS"
    )
    return base


def setup_loaner_out(
    loaner_out_date: str = "2026-08-03T00:00:00Z",
    loaner_due_back_date: str = "2026-08-07T00:00:00Z",
    **kwargs,
) -> dict:
    """Work order IN_PROGRESS with its substitute brewer OUT."""
    base = setup_work_order_in_progress(**kwargs)
    base["work_order"] = loaner_swap(
        base["work_order"]["id"],
        base["route"]["id"],
        base["loaner_asset"]["id"],
        loaner_out_date,
        loaner_due_back_date,
    )
    return base


# --- Tier 5: invoices, credits and terminal states ---------------------------


def setup_draft_invoice(
    base: dict = None,
    requested: dict = None,
    delivered: dict = None,
    window_start: str = "2026-08-03T09:00:00Z",
    window_end: str = "2026-08-03T09:45:00Z",
    invoice_at: str = "2026-08-04T08:00:00Z",
    period_start: str = "2026-08-03T00:00:00Z",
    period_end: str = "2026-08-03T23:59:59Z",
    invoice_overrides=None,
    **placed_kwargs,
) -> dict:
    """A completed stop inside a closed period, then a DRAFT invoice over it.

    Returns the placed-site dictionary with "visit" and "invoice" keys added.
    """
    base = setup_completed_visit(
        requested=requested,
        delivered=delivered,
        window_start=window_start,
        window_end=window_end,
        base=base,
        **placed_kwargs,
    )
    set_clock(invoice_at)
    base["invoice"] = assemble_invoice_for(
        base["account"]["id"], period_start, period_end, **(invoice_overrides or {})
    )
    base["account"] = read_account(base["account"]["id"])
    return base


def setup_issued_invoice(**kwargs) -> dict:
    """Same as setup_draft_invoice, then issued onto the account receivable."""
    base = setup_draft_invoice(**kwargs)
    base["invoice"] = issue_invoice(base["invoice"]["id"])
    base["account"] = read_account(base["account"]["id"])
    return base


def setup_retrieval_scheduled(
    base: dict = None,
    retrieval_due_by: str = "2026-08-10T00:00:00Z",
    cancel_reason: str = "Customer consolidating vendors",
    **placed_kwargs,
) -> dict:
    """Cancel the program so the installed brewer moves to RETRIEVAL_SCHEDULED."""
    base = base or setup_placed_site(**placed_kwargs)
    base["account"] = cancel_account(
        base["account"]["id"],
        cancel_reason=cancel_reason,
        retrieval_due_by=retrieval_due_by,
    )
    base["placement"] = read_placement(base["placement"]["id"])
    base["site"] = read_site(base["site"]["id"])
    return base


def setup_unreturned_asset_invoice(
    invoice_at: str,
    period_start: str,
    period_end: str,
    retrieval_due_by: str = "2026-08-10T00:00:00Z",
    base: dict = None,
    **placed_kwargs,
) -> dict:
    """A placement past its retrieval deadline, billed as unreturned by a draft.

    Returns the placed-site dictionary with "invoice" added and "placement" and
    "asset" re-read after assembly.
    """
    base = setup_retrieval_scheduled(
        base=base, retrieval_due_by=retrieval_due_by, **placed_kwargs
    )
    set_clock(invoice_at)
    base["invoice"] = assemble_invoice_for(
        base["account"]["id"], period_start, period_end
    )
    base["placement"] = read_placement(base["placement"]["id"])
    base["asset"] = read_asset(base["asset"]["id"])
    base["account"] = read_account(base["account"]["id"])
    return base


def setup_shortfall_billed_placement(base: dict = None, **placed_kwargs) -> dict:
    """Evaluate a LOAN placement twice with no purchases at all, so its
    compliance dimension walks MEETING_MINIMUM to SHORTFALL_WARNED to
    SHORTFALL_BILLED and the fee accrues.
    """
    base = base or setup_placed_site(**placed_kwargs)
    evaluate_compliance(base["placement"]["id"])
    base["placement"] = evaluate_compliance(base["placement"]["id"])
    return base


# --- Tier 5: green coffee negotiation ----------------------------------------


def setup_proposed_adjustment(
    base: dict = None,
    index_micros: int = 2400000,
    effective_at: str = "2026-09-01T00:00:00Z",
    **placed_kwargs,
) -> dict:
    """Move the market quote, then propose an adjustment against the account.

    With the canonical baseline of 2000000 micro-dollars, an index of 2400000
    is a movement of 2000 basis points and a pass-through of 1200.

    Returns the base dictionary with an "adjustment" key added.
    """
    base = base or setup_placed_site(**placed_kwargs)
    set_market_index(index_micros)
    base["adjustment"] = propose_adjustment(
        base["account"]["id"], effective_at=effective_at
    )
    return base


def setup_disputed_adjustment(dispute_reason: str = "Movement overstated", **kwargs) -> dict:
    """Proposed adjustment that the customer has disputed."""
    base = setup_proposed_adjustment(**kwargs)
    base["adjustment"] = respond_adjustment(
        base["adjustment"]["id"],
        base["account"]["id"],
        "DISPUTE",
        dispute_reason=dispute_reason,
    )
    return base


def setup_accepted_adjustment(**kwargs) -> dict:
    """Proposed adjustment the customer has accepted, repricing the account."""
    base = setup_proposed_adjustment(**kwargs)
    base["adjustment"] = respond_adjustment(
        base["adjustment"]["id"], base["account"]["id"], "ACCEPT"
    )
    base["account"] = read_account(base["account"]["id"])
    return base


# --- Additional primitives ----------------------------------------------------


def update_site(site_id: str, **fields) -> dict:
    """Revise a break room's demand attributes without re-running planning."""
    return get_success_data(
        api_client.update_site(site_id, _f.update_site_payload(**fields), AM)
    )


def read_day_load(route_id: str, service_date: str, headers: dict = AM) -> dict:
    """Computed read of one UTC service date's technician minutes on a route."""
    return get_success_data(
        api_client.get_route_day_load(
            route_id, headers, params={"service_date": service_date}
        )
    )


def read_par_line(par_level_id: str) -> dict:
    return get_success_data(api_client.get_par_level(par_level_id, AM))


def read_invoice_line(line_id: str) -> dict:
    return get_success_data(api_client.get_invoice_line(line_id, BS))


def list_placements(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api_client.list_placements(AM, params=query))


def list_visits(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api_client.list_visits(AM, params=query))


def list_work_orders(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api_client.list_work_orders(PA, params=query))


def list_adjustments(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api_client.list_price_adjustments(BS, params=query))


def list_sites(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api_client.list_sites(AM, params=query))


def list_invoices(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api_client.list_invoices(BS, params=query))


def create_second_route(**overrides) -> dict:
    """A second replenishment route, so route-scoped rules can be contrasted."""
    payload = {"name": "Uptown Monday Route"}
    payload.update(overrides)
    return create_route(**payload)
