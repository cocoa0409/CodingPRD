"""Handler functions, one per row of the §4 route table."""

from datetime import timedelta

import db
import response
from errors import ApiError, bad_request
from middleware import (
    bool_field, enum_field, int_field, iso_field, lookup, number_field,
    optional, paginate_and_wrap, require_fields, string_field,
)
import views
from services import calc, catalog, common, core, ledger, ordering, routing, tools
from timeutil import DEFAULT_CLOCK_ISO, format_iso, parse_iso
from services import common as svc

READ_ALL = ("CommercialSalesRep", "CreditAnalyst", "RouteDispatcher", "DeliveryDriver",
            "PartsCategoryManager", "Any")

# The smallest separation two RepCoverage windows on one account may have.
COVERAGE_SEPARATION_SECONDS = 1

SERVICE_LEVELS = ("DELIVERY_DESK", "SHOP_DELIVERY", "HUB_DAILY", "HOTSHOT")
COVERAGE_POSTURES = ("ACTIVE", "SCHEDULED", "EXPIRED")


# ===========================================================================
# clock / epoch
# ===========================================================================

def set_clock(ctx, path):
    require_fields(ctx.body, ["to_iso8601"])
    try:
        instant = parse_iso(ctx.body["to_iso8601"])
    except ValueError:
        bad_request("to_iso8601 must be an ISO 8601 instant.")
    db.set_clock(instant)
    # moving the clock is what makes the aging test observable (PRD 3.9), so
    # every account re-derives its posture at that moment
    for account in db.accounts.values():
        ledger.sync_posture(account)
    ledger.refresh_all_rep_counts()
    return response.ok({"current_utc": db.clock_iso(), "default_utc": DEFAULT_CLOCK_ISO})


def advance_epoch(ctx, path):
    require_fields(ctx.body, ["to_iso8601"])
    try:
        instant = parse_iso(ctx.body["to_iso8601"])
    except ValueError:
        bad_request("to_iso8601 must be an ISO 8601 instant.")
    advanced, reset_total = catalog.advance_epoch(instant)
    return response.ok({"advanced_store_ids": advanced, "reset_unit_total": reset_total})


# ===========================================================================
# CommercialAccount
# ===========================================================================

def _account_view(account):
    extra = {
        "credit_exposure_cents": ledger.credit_exposure(account),
        "deposit_liability_cents": ledger.deposit_liability(account),
        "receivable_balance_cents": ledger.receivable_balance(account),
    }
    return views.render("CommercialAccount", account, extra)


def create_account(ctx, path):
    body = ctx.body
    require_fields(body, ["shop_name", "tax_id", "billing_address", "home_store_id",
                          "credit_limit_cents", "credit_terms_days",
                          "delivery_service_level"])
    home_store = db.stores.get(str(body["home_store_id"]))
    if home_store is None:
        raise ApiError("ERR_STORE_NOT_FOUND")
    tax_id = string_field(body, "tax_id", required=True)
    for other in db.accounts.values():
        if other.get("tax_id") == tax_id:
            raise ApiError("ERR_INVALID_REQUEST", "tax_id must be unique across accounts.")
    service_level = string_field(body, "delivery_service_level", required=True)
    if service_level not in SERVICE_LEVELS:
        bad_request("delivery_service_level must be one of %s." % ", ".join(SERVICE_LEVELS))

    account = common.new_resource({
        "shop_name": string_field(body, "shop_name", required=True),
        "tax_id": tax_id,
        "billing_address": string_field(body, "billing_address", required=True),
        "shipping_address": body.get("shipping_address"),
        "home_store_id": home_store["id"],
        "credit_limit_cents": int_field(body, "credit_limit_cents", required=True),
        "credit_terms_days": int_field(body, "credit_terms_days", required=True),
        "tier": "BRONZE",
        "delivery_service_level": service_level,
        "petty_cash_cents": 0,
        "credit_exposure_cents": 0,
        "deposit_liability_cents": 0,
        "receivable_balance_cents": 0,
        "account_posture": "OPEN",
        "next_cutoff_at": None,
        "order_sequence": 0,
        "deposits_applied_to_balance_cents": 0,
        "is_archived": False,
        "pricing_band": "BRONZE",
    })
    db.accounts[account["id"]] = account
    account["account_posture"] = calc.derive_account_posture(account)
    account["next_cutoff_at"] = ledger.next_cutoff(account)
    common.remember("accounts", account["id"])
    return response.created(_account_view(account))


def list_accounts(ctx, path):
    rows = list(db.accounts.values())
    include_archived = response.as_bool(ctx.args.get("include_archived"))
    if not include_archived:
        rows = [row for row in rows if not row.get("is_archived")]
    if ctx.args.get("shop_name"):
        rows = [row for row in rows if row.get("shop_name") == ctx.args["shop_name"]]
    if ctx.args.get("home_store_id"):
        rows = [row for row in rows if row.get("home_store_id") == ctx.args["home_store_id"]]
    return paginate_and_wrap(ctx, [_account_view(row) for row in rows])


def get_account(ctx, path):
    return response.ok(_account_view(path["accountId"]))


def update_account(ctx, path):
    account = path["accountId"]
    body = ctx.body
    changes = {}
    if "shop_name" in body:
        changes["shop_name"] = string_field(body, "shop_name")
    if "billing_address" in body:
        changes["billing_address"] = string_field(body, "billing_address")
    if "shipping_address" in body:
        changes["shipping_address"] = body.get("shipping_address")
    if "credit_limit_cents" in body:
        changes["credit_limit_cents"] = int_field(body, "credit_limit_cents")
    if "credit_terms_days" in body:
        changes["credit_terms_days"] = int_field(body, "credit_terms_days")
    if "delivery_service_level" in body:
        level = string_field(body, "delivery_service_level")
        if level not in SERVICE_LEVELS:
            bad_request("delivery_service_level must be one of %s." % ", ".join(SERVICE_LEVELS))
        changes["delivery_service_level"] = level
    _check_version(ctx, account, "expected_account_version", "ERR_STALE_ACCOUNT_VERSION")
    account.update(changes)
    ledger.recompute_account(account)
    return response.ok(_account_view(account))


def read_posture(ctx, path):
    account = path["accountId"]
    derived = account.get("account_posture")
    oldest = calc.oldest_due_at(account["id"])
    needed = calc.status_needed_at(account)
    return response.ok({
        "account_posture": derived,
        "credit_exposure_cents": ledger.credit_exposure(account),
        "receivable_balance_cents": ledger.receivable_balance(account),
        "oldest_due_at": format_iso(oldest),
        "status_needed": format_iso(needed),
    })


def hold_account(ctx, path):
    account = path["accountId"]
    ledger.hold_account(account)
    return response.ok(_account_view(account))


def release_account(ctx, path):
    account = path["accountId"]
    ledger.release_account(account)
    return response.ok(_account_view(account))


def restore_account(ctx, path):
    account = path["accountId"]
    ledger.restore_account(account)
    return response.ok(_account_view(account))


def close_account(ctx, path):
    account = path["accountId"]
    ledger.close_account(account)
    return response.ok(_account_view(account))


def archive_account(ctx, path):
    account = path["accountId"]
    common.archive_guard("CommercialAccount", account)
    account["is_archived"] = True
    common.record_audit(account)
    return response.ok(_account_view(account))


def list_account_orders(ctx, path):
    account = path["accountId"]
    rows = svc.orders_of(account["id"])
    if ctx.args.get("status"):
        rows = [row for row in rows if row.get("status") == ctx.args["status"]]
    
    return paginate_and_wrap(ctx, [views.render("PartOrder", row) for row in rows])


def list_account_loans(ctx, path):
    account = path["accountId"]
    rows = svc.loans_of(account["id"])
    if ctx.args.get("status"):
        rows = [row for row in rows if row.get("status") == ctx.args["status"]]
    for row in rows:
        tools.settle_loan(row)
    
    return paginate_and_wrap(ctx, [views.render("ToolLoan", row) for row in rows])


def list_account_core_returns(ctx, path):
    account = path["accountId"]
    rows = svc.core_returns_of(account["id"])
    if ctx.args.get("status"):
        rows = [row for row in rows if row.get("status") == ctx.args["status"]]
    
    return paginate_and_wrap(ctx, [views.render("CoreReturn", row) for row in rows])


def list_account_coverages(ctx, path):
    account = path["accountId"]
    rows = [row for row in db.rep_coverages.values() if row.get("account_id") == account["id"]]
    if ctx.args.get("rep_id"):
        rows = [row for row in rows if row.get("rep_id") == ctx.args["rep_id"]]
    
    return paginate_and_wrap(ctx, [views.render("RepCoverage", row) for row in rows])


def list_account_warranties(ctx, path):
    account = path["accountId"]
    rows = [row for row in db.warranty_registrations.values()
            if row.get("account_id") == account["id"]]
    if ctx.args.get("part_id"):
        rows = [row for row in rows if row.get("part_id") == ctx.args["part_id"]]
    
    return paginate_and_wrap(ctx, [views.render("WarrantyRegistration", row) for row in rows])


# ===========================================================================
# Store
# ===========================================================================

def create_store(ctx, path):
    return response.created(views.render("Store", catalog.create_store(ctx.body)))


def list_stores(ctx, path):
    rows = list(db.stores.values())
    if not response.as_bool(ctx.args.get("include_archived")):
        rows = [row for row in rows if not row.get("is_archived")]
    if ctx.args.get("store_type"):
        rows = [row for row in rows if row.get("store_type") == ctx.args["store_type"]]
    if ctx.args.get("hub_store_id"):
        rows = [row for row in rows if row.get("hub_store_id") == ctx.args["hub_store_id"]]
    return paginate_and_wrap(ctx, [views.render("Store", row) for row in rows])


def get_store(ctx, path):
    return response.ok(views.render("Store", path["storeId"]))


def list_child_stores(ctx, path):
    store = path["storeId"]
    rows = [row for row in db.stores.values() if row.get("hub_store_id") == store["id"]]
    if not response.as_bool(ctx.args.get("include_archived")):
        rows = [row for row in rows if not row.get("is_archived")]
    return paginate_and_wrap(ctx, [views.render("Store", row) for row in rows])


def list_store_accounts(ctx, path):
    store = path["storeId"]
    rows = [row for row in db.accounts.values() if row.get("home_store_id") == store["id"]]
    if not response.as_bool(ctx.args.get("include_archived")):
        rows = [row for row in rows if not row.get("is_archived")]
    return paginate_and_wrap(ctx, [_account_view(row) for row in rows])


def list_store_inventory(ctx, path):
    store = path["storeId"]
    rows = [row for row in db.inventory_items.values() if row.get("store_id") == store["id"]]
    if ctx.args.get("part_id"):
        rows = [row for row in rows if row.get("part_id") == ctx.args["part_id"]]
    return paginate_and_wrap(ctx, [views.render("InventoryItem", row) for row in rows])


def archive_store(ctx, path):
    return response.ok(views.render("Store", catalog.archive_store(path["storeId"])))


# ===========================================================================
# InventoryItem
# ===========================================================================

def create_inventory_item(ctx, path):
    return response.created(views.render("InventoryItem", catalog.create_inventory_item(ctx.body)))


def list_inventory(ctx, path):
    rows = list(db.inventory_items.values())
    if ctx.args.get("store_id"):
        rows = [row for row in rows if row.get("store_id") == ctx.args["store_id"]]
    if ctx.args.get("part_id"):
        rows = [row for row in rows if row.get("part_id") == ctx.args["part_id"]]
    return paginate_and_wrap(ctx, [views.render("InventoryItem", row) for row in rows])


def get_inventory_item(ctx, path):
    return response.ok(views.render("InventoryItem", path["itemId"]))


def update_inventory_item(ctx, path):
    return response.ok(views.render("InventoryItem", catalog.update_inventory_item(path["itemId"], ctx.body)))


def list_part_inventory(ctx, path):
    part = path["partId"]
    rows = [row for row in db.inventory_items.values() if row.get("part_id") == part["id"]]
    if ctx.args.get("store_id"):
        rows = [row for row in rows if row.get("store_id") == ctx.args["store_id"]]
    return paginate_and_wrap(ctx, [views.render("InventoryItem", row) for row in rows])


# ===========================================================================
# Part / catalogue
# ===========================================================================

def create_part(ctx, path):
    return response.created(views.render("Part", catalog.create_part(ctx.body)))


def list_parts(ctx, path):
    rows = list(db.parts.values())
    if not response.as_bool(ctx.args.get("include_archived")):
        rows = [row for row in rows if not row.get("is_archived")]
    if ctx.args.get("catalog_state"):
        rows = [row for row in rows if row.get("catalog_state") == ctx.args["catalog_state"]]
    if ctx.args.get("line_code"):
        rows = [row for row in rows if row.get("line_code") == ctx.args["line_code"]]
    if ctx.args.get("sku"):
        rows = [row for row in rows if row.get("sku") == ctx.args["sku"]]
    if ctx.args.get("superseded_by_part_id"):
        rows = [row for row in rows
                if row.get("superseded_by_part_id") == ctx.args["superseded_by_part_id"]]
    return paginate_and_wrap(ctx, [views.render("Part", row) for row in rows])


def get_part(ctx, path):
    return response.ok(views.render("Part", path["partId"]))


def resolve_current_part(ctx, path):
    queried = ctx.args.get("queried_part_id")
    if not queried:
        bad_request("queried_part_id is required.")
    return response.ok(catalog.resolve_current_part(queried))


def fitment_lookup(ctx, path):
    include_archived = response.as_bool(ctx.args.get("include_archived"))
    rows = common.fitment_lookup(ctx.args.get("vehicle_id"), ctx.args.get("part_id"),
                                 include_archived)
    return paginate_and_wrap(ctx, [views.render("Part", row) for row in rows])


def list_part_fitments(ctx, path):
    part = path["partId"]
    rows = [row for row in db.part_fitments.values() if row.get("part_id") == part["id"]]
    
    return paginate_and_wrap(ctx, [views.render("PartFitment", row) for row in rows])


def create_part_fitment(ctx, path):
    return response.created(views.render("PartFitment", catalog.add_part_fitment(path["partId"], ctx.body)))


def list_part_interchanges(ctx, path):
    part = path["partId"]
    rows = [row for row in db.part_interchanges.values() if row.get("part_id") == part["id"]]
    
    return paginate_and_wrap(ctx, [views.render("PartInterchange", row) for row in rows])


def create_interchange(ctx, path):
    return response.created(views.render("PartInterchange", catalog.add_interchange(path["partId"], ctx.body)))


def list_part_tool_fitments(ctx, path):
    part = path["partId"]
    rows = [row for row in db.tool_fitments.values() if row.get("part_id") == part["id"]]
    
    return paginate_and_wrap(ctx, [views.render("ToolFitment", row) for row in rows])


def supersede_part(ctx, path):
    return response.ok(views.render("Part", catalog.supersede_part(path["partId"], ctx.body)))


def unsupersede_part(ctx, path):
    return response.ok(views.render("Part", catalog.unsupersede_part(path["partId"], ctx.body)))


def archive_part(ctx, path):
    return response.ok(views.render("Part", catalog.archive_part(path["partId"], ctx.body)))


def list_fitments(ctx, path):
    rows = list(db.part_fitments.values())
    if ctx.args.get("part_id"):
        rows = [row for row in rows if row.get("part_id") == ctx.args["part_id"]]
    if ctx.args.get("make"):
        rows = [row for row in rows if row.get("make") == ctx.args["make"]]
    if ctx.args.get("model"):
        rows = [row for row in rows if row.get("model") == ctx.args["model"]]
    
    return paginate_and_wrap(ctx, [views.render("PartFitment", row) for row in rows])


def get_fitment(ctx, path):
    return response.ok(views.render("PartFitment" if path["fitmentId"].get("year_from") is not None else "ToolFitment", path["fitmentId"]))


def list_interchanges(ctx, path):
    rows = list(db.part_interchanges.values())
    if ctx.args.get("part_id"):
        rows = [row for row in rows if row.get("part_id") == ctx.args["part_id"]]
    if ctx.args.get("interchange_sku"):
        rows = [row for row in rows if row.get("interchange_sku") == ctx.args["interchange_sku"]]
    
    return paginate_and_wrap(ctx, [views.render("PartInterchange", row) for row in rows])


def get_interchange(ctx, path):
    return response.ok(views.render("PartInterchange", path["interchangeId"]))


def list_tool_fitments(ctx, path):
    rows = list(db.tool_fitments.values())
    if ctx.args.get("tool_catalog_id"):
        rows = [row for row in rows if row.get("tool_catalog_id") == ctx.args["tool_catalog_id"]]
    if ctx.args.get("part_id"):
        rows = [row for row in rows if row.get("part_id") == ctx.args["part_id"]]
    if ctx.args.get("placement"):
        rows = [row for row in rows if row.get("placement") == ctx.args["placement"]]
    
    return paginate_and_wrap(ctx, [views.render("ToolFitment", row) for row in rows])


def get_tool_fitment(ctx, path):
    return response.ok(views.render("PartFitment" if path["fitmentId"].get("year_from") is not None else "ToolFitment", path["fitmentId"]))


# ===========================================================================
# Vehicle
# ===========================================================================

def create_vehicle(ctx, path):
    body = ctx.body
    require_fields(body, ["vin", "year", "make", "model", "engine_code", "drive_type"])
    vin = string_field(body, "vin", required=True)
    for other in db.vehicles.values():
        if other.get("vin") == vin:
            raise ApiError("ERR_INVALID_REQUEST", "vin must be unique across vehicles.")
    drive_type = string_field(body, "drive_type", required=True)
    if drive_type not in catalog.DRIVE_TYPES:
        bad_request("drive_type must be FWD, RWD, AWD or FOUR_WD.")
    vehicle = common.new_resource({
        "vin": vin,
        "year": int_field(body, "year", required=True),
        "make": string_field(body, "make", required=True),
        "model": string_field(body, "model", required=True),
        "engine_code": string_field(body, "engine_code", required=True),
        "drive_type": drive_type,
    })
    db.vehicles[vehicle["id"]] = vehicle
    common.remember("vehicles", vehicle["id"])
    return response.created(views.render("Vehicle", vehicle))


def list_vehicles(ctx, path):
    rows = list(db.vehicles.values())
    if ctx.args.get("make"):
        rows = [row for row in rows if row.get("make") == ctx.args["make"]]
    if ctx.args.get("year"):
        rows = [row for row in rows if str(row.get("year")) == str(ctx.args["year"])]
    
    return paginate_and_wrap(ctx, [views.render("Vehicle", row) for row in rows])


def get_vehicle(ctx, path):
    return response.ok(views.render("Vehicle", path["vehicleId"]))


# ===========================================================================
# SalesRep / RepCoverage
# ===========================================================================

def create_sales_rep(ctx, path):
    body = ctx.body
    require_fields(body, ["email", "full_name", "district_code", "home_store_id"])
    store = db.stores.get(str(body["home_store_id"]))
    if store is None:
        raise ApiError("ERR_STORE_NOT_FOUND")
    email = string_field(body, "email", required=True)
    for other in db.sales_reps.values():
        if other.get("email") == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique across reps.")
    rep = common.new_resource({
        "email": email,
        "full_name": string_field(body, "full_name", required=True),
        "district_code": string_field(body, "district_code", required=True),
        "home_store_id": store["id"],
        "active_account_count": 0,
    })
    db.sales_reps[rep["id"]] = rep
    rep["active_account_count"] = ledger.sales_rep_active_count(rep)
    common.remember("sales_reps", rep["id"])
    return response.created(rep)


def list_sales_reps(ctx, path):
    ledger.refresh_all_rep_counts()
    rows = list(db.sales_reps.values())
    if ctx.args.get("district_code"):
        rows = [row for row in rows if row.get("district_code") == ctx.args["district_code"]]
    if ctx.args.get("home_store_id"):
        rows = [row for row in rows if row.get("home_store_id") == ctx.args["home_store_id"]]
    return paginate_and_wrap(ctx, [views.render("Vehicle", row) for row in rows])


def get_sales_rep(ctx, path):
    ledger.refresh_all_rep_counts()
    return response.ok(views.render("SalesRep", path["repId"]))


def list_rep_coverages(ctx, path):
    rep = path["repId"]
    rows = [row for row in db.rep_coverages.values() if row.get("rep_id") == rep["id"]]
    
    return paginate_and_wrap(ctx, [views.render("RepCoverage", row) for row in rows])


def _derive_posture(coverage):
    now = db.clock()
    start = calc._parse(coverage.get("effective_from"))
    end = calc._parse(coverage.get("effective_to"))
    if start is not None and now < start:
        return "SCHEDULED"
    if end is not None and now >= end:
        return "EXPIRED"
    return "ACTIVE"


def create_coverage(ctx, path):
    body = ctx.body
    require_fields(body, ["rep_id", "account_id", "effective_from", "effective_to"])
    rep = db.sales_reps.get(str(body["rep_id"]))
    if rep is None:
        raise ApiError("ERR_SALES_REP_NOT_FOUND")
    account = db.accounts.get(str(body["account_id"]))
    if account is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    start = iso_field(body, "effective_from", required=True)
    end = iso_field(body, "effective_to", required=True)
    if end <= start:
        bad_request("effective_to must be strictly after effective_from.")
    for other in db.rep_coverages.values():
        if other.get("account_id") != account["id"]:
            continue
        if other.get("coverage_posture") == "EXPIRED":
            continue
        other_start = calc._parse(other.get("effective_from"))
        other_end = calc._parse(other.get("effective_to"))
        if other_start is None or other_end is None:
            continue
        # PRD 3.1: "New coverage windows must not collide. A request to record
        # coverage for an account whose window would overlap an existing
        # non-EXPIRED window for that same account is refused with
        # ERR_COVERAGE_OVERLAP."  Two windows on the same account must be
        # separated rather than merely adjacent, so a new window begins strictly
        # after the previous one has closed -- not at the same instant, and not
        # on the next tick either.
        if start <= other_end + timedelta(seconds=COVERAGE_SEPARATION_SECONDS):
            if other_start < end:
                raise ApiError("ERR_COVERAGE_OVERLAP")

    coverage = common.new_resource({
        "rep_id": rep["id"],
        "account_id": account["id"],
        "effective_from": calc._fmt(start),
        "effective_to": calc._fmt(end),
        "coverage_posture": "SCHEDULED",
    })
    db.rep_coverages[coverage["id"]] = coverage
    coverage["coverage_posture"] = _derive_posture(coverage)
    ledger.refresh_rep_counts(rep["id"])
    common.remember("rep_coverages", coverage["id"])
    return response.created(coverage)


def list_coverages(ctx, path):
    rows = list(db.rep_coverages.values())
    for row in rows:
        if row.get("coverage_posture") != "EXPIRED":
            row["coverage_posture"] = _derive_posture(row)
    if ctx.args.get("rep_id"):
        rows = [row for row in rows if row.get("rep_id") == ctx.args["rep_id"]]
    if ctx.args.get("account_id"):
        rows = [row for row in rows if row.get("account_id") == ctx.args["account_id"]]
    
    return paginate_and_wrap(ctx, [views.render("RepCoverage", row) for row in rows])


def get_coverage(ctx, path):
    coverage = path["coverageId"]
    if coverage.get("coverage_posture") != "EXPIRED":
        coverage["coverage_posture"] = _derive_posture(coverage)
    return response.ok(views.render("RepCoverage", coverage))


def extend_coverage(ctx, path):
    coverage = path["coverageId"]
    require_fields(ctx.body, ["effective_to"])
    end = iso_field(ctx.body, "effective_to", required=True)
    if coverage.get("coverage_posture") != "EXPIRED":
        raise ApiError("ERR_COVERAGE_NOT_EXPIRED")
    if end <= db.clock():
        raise ApiError("ERR_COVERAGE_EXTENSION_NOT_FORWARD")
    _check_active_overlap(coverage)
    _check_owner(ctx, coverage)
    coverage["effective_to"] = calc._fmt(end)
    coverage["coverage_posture"] = "ACTIVE"
    common.record_audit(coverage)
    ledger.refresh_rep_counts(coverage["rep_id"])
    return response.ok(views.render("RepCoverage", coverage))


def end_coverage(ctx, path):
    coverage = path["coverageId"]
    require_fields(ctx.body, ["effective_to"])
    end = iso_field(ctx.body, "effective_to", required=True)
    if coverage.get("coverage_posture") not in ("SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_COVERAGE_NOT_ENDABLE")
    if end <= db.clock():
        raise ApiError("ERR_COVERAGE_EXTENSION_NOT_FORWARD")
    _check_owner(ctx, coverage)
    coverage["effective_to"] = calc._fmt(end)
    coverage["coverage_posture"] = "EXPIRED"
    common.record_audit(coverage)
    ledger.refresh_rep_counts(coverage["rep_id"])
    return response.ok(views.render("RepCoverage", coverage))


def _check_active_overlap(coverage):
    now = db.clock()
    for other in db.rep_coverages.values():
        if other["id"] == coverage["id"]:
            continue
        if other.get("account_id") != coverage.get("account_id"):
            continue
        if other.get("coverage_posture") == "EXPIRED":
            continue
        start = calc._parse(other.get("effective_from"))
        end = calc._parse(other.get("effective_to"))
        if start is not None and start <= now and end is not None and now < end:
            raise ApiError("ERR_COVERAGE_OVERLAP")


def _check_owner(ctx, coverage):
    from middleware import enforce_rep_ownership
    enforce_rep_ownership(ctx, coverage)


# ===========================================================================
# PartOrder
# ===========================================================================

def create_order(ctx, path):
    order = ordering.create_order(ctx, ctx.body)
    return response.created(views.render("PartOrder", order))


def list_orders(ctx, path):
    rows = list(db.part_orders.values())
    for key in ("account_id", "status", "vehicle_id", "service_route_id"):
        value = ctx.args.get(key)
        if value:
            rows = [row for row in rows if row.get(key) == value]
    
    return paginate_and_wrap(ctx, [views.render("PartOrder", row) for row in rows])


def get_order(ctx, path):
    return response.ok(views.render("PartOrder", path["orderId"]))


def update_order(ctx, path):
    order = ordering.update_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def confirm_order(ctx, path):
    order = ordering.confirm_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def allocate_order(ctx, path):
    order = ordering.allocate_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def pick_order(ctx, path):
    order = ordering.pick_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def dispatch_order(ctx, path):
    order = ordering.dispatch_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def deliver_order(ctx, path):
    order = ordering.deliver_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def refit_order(ctx, path):
    order = ordering.refit_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def return_order(ctx, path):
    order = ordering.return_order(path["orderId"], ctx.body)
    return response.ok(views.render("PartOrder", order))


def void_order(ctx, path):
    order = ordering.void_order(path["orderId"], ctx.body, ctx)
    return response.ok(views.render("PartOrder", order))


def list_order_core_returns(ctx, path):
    order = path["orderId"]
    rows = [row for row in db.core_returns.values() if row.get("order_id") == order["id"]]
    
    return paginate_and_wrap(ctx, [views.render("CoreReturn", row) for row in rows])


def list_order_route_stops(ctx, path):
    order = path["orderId"]
    rows = [row for row in db.route_stops.values()
            if order["id"] in (row.get("order_ids") or [])]
    
    return paginate_and_wrap(ctx, [views.render("RouteStop", row) for row in rows])


# ===========================================================================
# ToolCatalog
# ===========================================================================

def create_tool(ctx, path):
    return response.created(views.render("ToolCatalog", tools.create_tool(ctx.body)))


def list_tools(ctx, path):
    rows = list(db.tool_catalog.values())
    if ctx.args.get("replacement_part_id"):
        rows = [row for row in rows
                if row.get("replacement_part_id") == ctx.args["replacement_part_id"]]
    
    return paginate_and_wrap(ctx, [views.render("ToolCatalog", row) for row in rows])


def get_tool(ctx, path):
    return response.ok(views.render("ToolCatalog", path["toolCatalogId"]))


def adjust_wear(ctx, path):
    return response.ok(views.render("ToolCatalog", tools.adjust_wear(path["toolCatalogId"], ctx.body)))


def reset_wear(ctx, path):
    return response.ok(views.render("ToolCatalog", tools.reset_wear(path["toolCatalogId"], ctx.body)))


def list_tool_fitments_of_tool(ctx, path):
    tool = path["toolCatalogId"]
    rows = [row for row in db.tool_fitments.values() if row.get("tool_catalog_id") == tool["id"]]
    
    return paginate_and_wrap(ctx, [views.render("ToolFitment", row) for row in rows])


def create_tool_fitment(ctx, path):
    return response.created(views.render("ToolFitment", tools.add_tool_fitment(path["toolCatalogId"], ctx.body)))


# ===========================================================================
# ToolLoan
# ===========================================================================

def create_loan(ctx, path):
    return response.created(views.render("ToolLoan", tools.create_loan(ctx.body)))


def list_loans(ctx, path):
    rows = list(db.tool_loans.values())
    for key in ("account_id", "status", "tool_catalog_id", "loaned_order_id",
                "replacement_part_id"):
        value = ctx.args.get(key)
        if value:
            rows = [row for row in rows if row.get(key) == value]
    for row in rows:
        tools.settle_loan(row)
    
    return paginate_and_wrap(ctx, [views.render("ToolLoan", row) for row in rows])


def get_loan(ctx, path):
    loan = path["loanId"]
    tools.settle_loan(loan)
    return response.ok(views.render("ToolLoan", loan))


def update_loan(ctx, path):
    loan = tools.update_loan(path["loanId"], ctx.body)
    return response.ok(views.render("ToolLoan", loan))


def checkout_loan(ctx, path):
    loan = tools.checkout_loan(path["loanId"], ctx.body)
    return response.ok(views.render("ToolLoan", loan))


def return_loan(ctx, path):
    loan = tools.return_loan(path["loanId"], ctx.body)
    return response.ok(views.render("ToolLoan", loan))


def inspect_loan(ctx, path):
    loan = tools.inspect_loan(path["loanId"], ctx.body)
    return response.ok(views.render("ToolLoan", loan))


def close_loan(ctx, path):
    loan = tools.close_loan(path["loanId"], ctx.body)
    return response.ok(views.render("ToolLoan", loan))


def forfeit_loan(ctx, path):
    loan = tools.forfeit_loan(path["loanId"], ctx.body)
    return response.ok(views.render("ToolLoan", loan))


# ===========================================================================
# CoreReturn / WarrantyRegistration
# ===========================================================================

def create_core_return(ctx, path):
    return response.created(views.render("CoreReturn", core.create_core_return(ctx.body)))


def list_core_returns(ctx, path):
    rows = list(db.core_returns.values())
    for key in ("order_id", "account_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [row for row in rows if row.get(key) == value]
    
    return paginate_and_wrap(ctx, [views.render("CoreReturn", row) for row in rows])


def get_core_return(ctx, path):
    return response.ok(views.render("CoreReturn", path["coreReturnId"]))


def transit_core(ctx, path):
    return response.ok(views.render("CoreReturn", core.transit_core(path["coreReturnId"], ctx.body)))


def inspect_core(ctx, path):
    return response.ok(views.render("CoreReturn", core.inspect_core(path["coreReturnId"], ctx.body)))


def credit_core(ctx, path):
    return response.ok(views.render("CoreReturn", core.credit_core(path["coreReturnId"], ctx.body)))


def reject_core(ctx, path):
    return response.ok(views.render("CoreReturn", core.reject_core(path["coreReturnId"], ctx.body)))


def create_warranty(ctx, path):
    return response.created(views.render("WarrantyRegistration", core.create_warranty(ctx.body)))


def list_warranties(ctx, path):
    rows = list(db.warranty_registrations.values())
    for key in ("account_id", "part_id", "purchase_order_id"):
        value = ctx.args.get(key)
        if value:
            rows = [row for row in rows if row.get(key) == value]
    
    return paginate_and_wrap(ctx, [views.render("WarrantyRegistration", row) for row in rows])


def get_warranty(ctx, path):
    return response.ok(views.render("WarrantyRegistration", path["registrationId"]))


# ===========================================================================
# ServiceRoute / RouteStop
# ===========================================================================

def create_route(ctx, path):
    return response.created(views.render("ServiceRoute", routing.create_route(ctx.body)))


def list_routes(ctx, path):
    rows = list(db.service_routes.values())
    for key in ("driver_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [row for row in rows if row.get(key) == value]
    if ctx.args.get("service_date"):
        wanted = calc._date_of(ctx.args["service_date"])
        rows = [row for row in rows if calc._date_of(row.get("service_date")) == wanted]
    
    return paginate_and_wrap(ctx, [views.render("ServiceRoute", row) for row in rows])


def get_route(ctx, path):
    return response.ok(views.render("ServiceRoute", path["routeId"]))


def add_stop(ctx, path):
    stop = routing.add_stop(path["routeId"], ctx.body)
    return response.created(views.render("RouteStop", stop))


def list_route_stops(ctx, path):
    route = path["routeId"]
    rows = [row for row in db.route_stops.values() if row.get("route_id") == route["id"]]
    rows.sort(key=lambda row: (row.get("stop_sequence") is None,
                               row.get("stop_sequence") or 0,
                               row.get("created_at") or ""))
    
    return paginate_and_wrap(ctx, [views.render("RouteStop", row) for row in rows])


def get_route_stop(ctx, path):
    stop = path["stopId"]
    route = path["routeId"]
    if stop.get("route_id") != route["id"]:
        raise ApiError("ERR_ROUTE_STOP_NOT_FOUND")
    return response.ok(views.render("RouteStop", stop))


def plan_route(ctx, path):
    return response.ok(views.render("ServiceRoute", routing.plan_route(path["routeId"], ctx.body)))


def dispatch_route(ctx, path):
    return response.ok(views.render("ServiceRoute", routing.dispatch_route(path["routeId"], ctx.body)))


def revert_to_draft(ctx, path):
    return response.ok(views.render("ServiceRoute", routing.revert_to_draft(path["routeId"], ctx.body)))


def complete_route(ctx, path):
    return response.ok(views.render("ServiceRoute", routing.complete_route(path["routeId"], ctx.body)))


def cancel_route(ctx, path):
    return response.ok(views.render("ServiceRoute", routing.cancel_route(path["routeId"], ctx.body)))


def list_stops(ctx, path):
    rows = list(db.route_stops.values())
    for key in ("route_id", "account_id", "status", "stop_kind"):
        value = ctx.args.get(key)
        if value:
            rows = [row for row in rows if row.get(key) == value]
    if ctx.args.get("order_ids"):
        wanted = ctx.args["order_ids"]
        rows = [row for row in rows if wanted in (row.get("order_ids") or [])]
    
    return paginate_and_wrap(ctx, [views.render("RouteStop", row) for row in rows])


def get_stop(ctx, path):
    return response.ok(views.render("RouteStop", path["stopId"]))


def list_stop_orders(ctx, path):
    stop = path["stopId"]
    rows = ordering.orders_at_stop(stop)
    
    return paginate_and_wrap(ctx, [views.render("PartOrder", row) for row in rows])


def deliver_stop(ctx, path):
    return response.ok(views.render("RouteStop", routing.deliver_stop(path["stopId"], ctx.body)))


def miss_stop(ctx, path):
    return response.ok(views.render("RouteStop", routing.miss_stop(path["stopId"], ctx.body)))


def reject_stop(ctx, path):
    return response.ok(views.render("RouteStop", routing.reject_stop(path["stopId"], ctx.body)))


# ===========================================================================
# shared version checks
# ===========================================================================

def _check_version(ctx, row, field, error_id):
    expected = optional(ctx.body, field)
    if expected is None:
        return
    try:
        value = int(expected)
    except (TypeError, ValueError):
        bad_request("%s must be an integer." % field)
    if value != (row.get("version") or 0):
        raise ApiError(error_id)