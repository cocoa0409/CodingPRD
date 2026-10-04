"""Store registration, conversion projects, conversions, reversions and
multi-price issue batches (PRD §3.8)."""

from db import db
from errors import (
    ApiError,
    ERR_AISLE_COVERAGE_SHORTFALL,
    ERR_CONVERSION_NOT_DRAFT,
    ERR_CONVERSION_NOT_IN_PROGRESS,
    ERR_CONVERSION_PREREQUISITES_UNMET,
    ERR_DUPLICATE_SKU,
    ERR_INVALID_REQUEST,
    ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT,
    ERR_PRICE_POINT_NOT_ACTIVE,
    ERR_STALE_VERSION,
    ERR_STORE_ALREADY_CONVERTING,
    ERR_STORE_NOT_CONVERTING,
    ERR_STORE_NOT_MULTI_PRICE,
    ERR_STORE_NOT_SINGLE_PRICE,
)
from common import (
    apply_eq,
    as_int_opt,
    body,
    get_ok,
    get_row,
    insert,
    new_row,
    paginate,
    query,
    require,
    route,
    serialize,
    touch,
)
from response import ok_object
from derivations import (
    COVERAGE_TOLERANCE_PCT,
    PROJECTED_RESET_STATES,
    SHORTFALL_FLOOR_AISLES,
    dec,
    refresh_after_config_change,
    refresh_store,
    round_half_up,
    serialize_project,
    serialize_store,
)

ARTIFACTS = {
    "SIGN_ORDER": "sign_order_filed",
    "SHELF_TAG": "shelf_tag_filed",
    "REGISTER_FILE": "register_file_locked",
    "SIGN_ORDER_FILED": "sign_order_filed",
    "SHELF_TAG_FILE": "shelf_tag_filed",
    "SHELF_TAG_FILED": "shelf_tag_filed",
    "REGISTER_FILE_LOCK": "register_file_locked",
    "REGISTER_FILE_LOCKED": "register_file_locked",
    "SIGNAGE_ORDER": "sign_order_filed",
    "SHELF_TAG_FILE_FILED": "shelf_tag_filed",
}


def coverage_numbers(store_id):
    resets = [r for r in db.aisle_resets.values() if r["store_id"] == store_id]
    completed = sum(1 for r in resets if r["status"] == "EXECUTED")
    projected = sum(1 for r in resets if r["status"] in PROJECTED_RESET_STATES)
    baseline = max(projected, SHORTFALL_FLOOR_AISLES)
    delta = round_half_up(dec(completed - baseline) / dec(baseline), 3)
    return completed, projected, baseline, delta


def refresh_project_coverage(project, force=False):
    _, _, _, delta = coverage_numbers(project["store_id"])
    value = float(delta)
    if not force and project.get("coverage_delta_pct") == value:
        return False
    project["coverage_delta_pct"] = value
    touch(project)
    return True


def get_project_for_store(store_id, conversion_id):
    project = get_row("conversion_project", conversion_id)
    if project["store_id"] != store_id:
        raise ApiError("ERR_CONVERSION_PROJECT_NOT_FOUND")
    return project


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

@route("/merchandise/stores", ["POST"], ["StoreOperationsManager"])
def create_store():
    data = body()
    require(data, ["store_number", "shelf_facing_capacity_sqft"])
    capacity = data["shelf_facing_capacity_sqft"]
    try:
        capacity = float(capacity)
    except (TypeError, ValueError):
        invalid("shelf_facing_capacity_sqft must be a number.")
    if not capacity > 0:
        invalid("shelf_facing_capacity_sqft must be greater than zero.")
    if any(s["store_number"] == data["store_number"] for s in db.stores.values()):
        raise ApiError(ERR_DUPLICATE_SKU, "store_number is already held by another store.")

    row = new_row("store", {
        "store_number": data["store_number"],
        "shelf_facing_capacity_sqft": capacity,
        "conversion_price_point_id": None,
        "sign_order_filed": False,
        "shelf_tag_filed": False,
        "register_file_locked": False,
        "status": "SINGLE_PRICE",
        "price_integrity_audit_count": 0,
        "open_violation_count": 0,
    })
    insert("store", row)
    refresh_after_config_change()
    return ok_object(serialize_store(row), 201)


@route("/merchandise/stores", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst", "MerchandiseBuyer", "LegalCostEngineer"])
def list_stores():
    rows = db.creation_order(db.stores)
    rows = apply_eq(rows, "status", query("status"))
    rows = apply_eq(rows, "conversion_price_point_id", query("conversion_price_point_id"))
    return paginate([serialize_store(r) for r in rows])


@route("/merchandise/stores/<store_id>", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst", "MerchandiseBuyer", "LegalCostEngineer"])
def read_store(store_id):
    return get_ok("store", store_id)


@route("/merchandise/stores/<store_id>/conversions", ["POST"], ["StoreOperationsManager"])
def begin_conversion(store_id):
    store = get_row("store", store_id)
    data = body()
    require(data, ["to_price_point_id"])
    price_point = get_row("price_point", data["to_price_point_id"])

    if store["status"] != "SINGLE_PRICE":
        raise ApiError(ERR_STORE_NOT_SINGLE_PRICE)
    if store["conversion_price_point_id"] is not None:
        raise ApiError(ERR_STORE_ALREADY_CONVERTING)
    if price_point["status"] != "ACTIVE":
        raise ApiError(ERR_PRICE_POINT_NOT_ACTIVE)

    store["conversion_price_point_id"] = price_point["id"]
    store["status"] = "CONVERTING"
    store["sign_order_filed"] = False
    store["shelf_tag_filed"] = False
    store["register_file_locked"] = False
    touch(store)
    return ok_object(serialize_store(store))


@route("/merchandise/stores/<store_id>/reversions", ["POST"], ["StoreOperationsManager"])
def begin_reversion(store_id):
    store = get_row("store", store_id)
    data = body()
    require(data, ["to_price_point_id"])
    price_point = get_row("price_point", data["to_price_point_id"])

    if store["status"] != "MULTI_PRICE":
        raise ApiError(ERR_STORE_NOT_MULTI_PRICE)
    if price_point["status"] != "ACTIVE":
        raise ApiError(ERR_PRICE_POINT_NOT_ACTIVE)

    store["conversion_price_point_id"] = price_point["id"]
    store["status"] = "REVERTING"
    touch(store)
    return ok_object(serialize_store(store))


@route("/merchandise/stores/<store_id>/conversions/<conversion_id>/filing", ["POST"],
       ["StoreOperationsManager"])
def file_artifact(store_id, conversion_id):
    store = get_row("store", store_id)
    get_project_for_store(store_id, conversion_id)
    data = body()
    require(data, ["artifact"])
    artifact = data["artifact"]
    field = ARTIFACTS.get(str(artifact).strip().upper())
    if field is None:
        invalid("'artifact' must name the signage order, the shelf-tag file or the register file lock.")

    store[field] = True
    touch(store)
    return ok_object(serialize_store(store))


@route("/merchandise/stores/<store_id>/conversions/<conversion_id>/complete", ["POST"],
       ["StoreOperationsManager"])
def complete_conversion(store_id, conversion_id):
    store = get_row("store", store_id)
    project = get_project_for_store(store_id, conversion_id)

    if store["status"] not in ("CONVERTING", "REVERTING"):
        raise ApiError(ERR_STORE_NOT_CONVERTING)
    if not (store["sign_order_filed"] and store["shelf_tag_filed"] and store["register_file_locked"]):
        raise ApiError(ERR_CONVERSION_PREREQUISITES_UNMET)
    if store["status"] == "CONVERTING" and project["status"] != "IN_PROGRESS":
        # The CONVERTING -> MULTI_PRICE transition gates on the project being
        # IN_PROGRESS; the REVERTING -> SINGLE_PRICE transition deliberately
        # does not (PRD §3.8 names only the artefacts and the coverage
        # tolerance for a reversion, and a reversion's project can never reach
        # IN_PROGRESS because starting one requires a CONVERTING store).
        raise ApiError(ERR_CONVERSION_NOT_IN_PROGRESS)

    _, _, _, delta = coverage_numbers(store["id"])
    refresh_project_coverage(project)
    if dec(delta) < COVERAGE_TOLERANCE_PCT:
        raise ApiError(ERR_AISLE_COVERAGE_SHORTFALL)

    landing = "MULTI_PRICE" if store["status"] == "CONVERTING" else "SINGLE_PRICE"
    store["status"] = landing
    store["conversion_price_point_id"] = None
    project["status"] = "COMPLETED"
    touch(project)
    # Cascade: every open integrity violation on the store closes with it.
    for audit in db.audits.values():
        if audit["store_id"] == store["id"] and audit["status"] == "OPEN":
            audit["status"] = "RESOLVED"
    touch(store)
    refresh_store(store)
    return ok_object(serialize_store(store))


@route("/merchandise/stores/<store_id>/conversions/<conversion_id>/rollback", ["POST"],
       ["StoreOperationsManager"])
def rollback_conversion(store_id, conversion_id):
    store = get_row("store", store_id)
    project = get_project_for_store(store_id, conversion_id)

    if store["status"] not in ("CONVERTING", "REVERTING"):
        raise ApiError(ERR_STORE_NOT_CONVERTING)
    if project["status"] != "IN_PROGRESS":
        raise ApiError(ERR_CONVERSION_NOT_IN_PROGRESS)

    store["status"] = "SINGLE_PRICE"
    store["conversion_price_point_id"] = None
    store["sign_order_filed"] = False
    store["shelf_tag_filed"] = False
    store["register_file_locked"] = False
    project["status"] = "ROLLBACK"
    touch(project)
    touch(store)
    return ok_object(serialize_store(store))


@route("/merchandise/stores/<store_id>/price-integrity-audits", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst", "LegalCostEngineer"])
def store_audits(store_id):
    get_row("store", store_id)
    rows = [r for r in db.creation_order(db.audits) if r["store_id"] == store_id]
    rows = apply_eq(rows, "result", query("result"))
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize("audit", r) for r in rows])


@route("/merchandise/stores/<store_id>/aisle-resets", ["GET"],
       ["StoreOperationsManager", "ResetCalendarPlanner", "MerchandiseAnalyst"])
def store_aisle_resets(store_id):
    get_row("store", store_id)
    rows = [r for r in db.creation_order(db.aisle_resets) if r["store_id"] == store_id]
    rows = apply_eq(rows, "status", query("status"))
    rows = apply_eq(rows, "season_window_id", query("season_window_id"))
    return paginate([serialize("aisle_reset", r) for r in rows])


@route("/merchandise/stores/<store_id>/conversion-projects", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst"])
def store_conversion_projects(store_id):
    get_row("store", store_id)
    rows = [r for r in db.creation_order(db.conversion_projects) if r["store_id"] == store_id]
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_project(r) for r in rows])


# ---------------------------------------------------------------------------
# ConversionProject
# ---------------------------------------------------------------------------

@route("/merchandise/conversion-projects", ["POST"], ["StoreOperationsManager"])
def create_conversion_project():
    data = body()
    require(data, ["store_id", "from_price_point_id", "to_price_point_id", "expected_store_version"])
    store = get_row("store", data["store_id"])
    from_p = get_row("price_point", data["from_price_point_id"])
    to_p = get_row("price_point", data["to_price_point_id"])

    expected = as_int_opt(data, "expected_store_version")
    if expected is None:
        invalid("expected_store_version must be an integer.")
    # OCC token equality (priority 6) precedes declared request shape (priority 7).
    if expected != store["version"]:
        raise ApiError(ERR_STALE_VERSION)
    if data["to_price_point_id"] == data["from_price_point_id"]:
        invalid("to_price_point_id must differ from from_price_point_id.")

    row = new_row("conversion_project", {
        "store_id": store["id"],
        "from_price_point_id": from_p["id"],
        "to_price_point_id": to_p["id"],
        "expected_store_version": expected,
        "status": "DRAFT",
        "coverage_delta_pct": 0.0,
    })
    insert("conversion_project", row)
    refresh_project_coverage(row)
    store["version"] = store["version"] + 1
    store["updated_at"] = db.now_iso()
    return ok_object(serialize_project(row), 201)


@route("/merchandise/conversion-projects", ["GET"], ["StoreOperationsManager", "MerchandiseAnalyst"])
def list_conversion_projects():
    rows = db.creation_order(db.conversion_projects)
    rows = apply_eq(rows, "store_id", query("store_id"))
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_project(r) for r in rows])


@route("/merchandise/conversion-projects/<project_id>", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst"])
def read_conversion_project(project_id):
    return get_ok("conversion_project", project_id)


@route("/merchandise/conversion-projects/<project_id>/coverage", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst"])
def read_coverage(project_id):
    project = get_row("conversion_project", project_id)
    completed, projected, baseline, delta = coverage_numbers(project["store_id"])
    return ok_object({
        "conversion_project_id": project["id"],
        "completed_aisle_count": completed,
        "projected_convertible_aisle_count": projected,
        "adjusted_baseline": baseline,
        "coverage_delta_pct": float(delta),
        "shortfall": dec(delta) < COVERAGE_TOLERANCE_PCT,
    })


@route("/merchandise/conversion-projects/<project_id>/start", ["POST"],
       ["StoreOperationsManager"])
def start_conversion_project(project_id):
    project = get_row("conversion_project", project_id)
    if project["status"] != "DRAFT":
        raise ApiError(ERR_CONVERSION_NOT_DRAFT)
    store = get_row("store", project["store_id"])
    if store["status"] != "CONVERTING":
        raise ApiError(ERR_STORE_NOT_CONVERTING)
    project["status"] = "IN_PROGRESS"
    touch(project)
    return ok_object(serialize_project(project))


@route("/merchandise/conversion-projects/<project_id>", ["PATCH"], ["StoreOperationsManager"])
def patch_conversion_project(project_id):
    project = get_row("conversion_project", project_id)
    data = body()
    require(data, ["to_price_point_id", "expected_store_version"])
    to_p = get_row("price_point", data["to_price_point_id"])
    expected = as_int_opt(data, "expected_store_version")
    if expected is None:
        invalid("expected_store_version must be an integer.")
    store = get_row("store", project["store_id"])
    if expected != store["version"]:
        raise ApiError(ERR_STALE_VERSION)
    if data["to_price_point_id"] == project["from_price_point_id"]:
        invalid("to_price_point_id must differ from from_price_point_id.")

    project["to_price_point_id"] = to_p["id"]
    project["expected_store_version"] = expected
    touch(project)
    store["version"] = store["version"] + 1
    store["updated_at"] = db.now_iso()
    return ok_object(serialize_project(project))


@route("/merchandise/multi-price-issues", ["POST"], ["MerchandiseBuyer"])
def multi_price_issue():
    data = body()
    require(data, ["store_id", "from_price_point_id", "item_ids", "to_price_point_id"])
    store = get_row("store", data["store_id"])
    from_p = get_row("price_point", data["from_price_point_id"])
    to_p = get_row("price_point", data["to_price_point_id"])

    item_ids = data["item_ids"]
    if not isinstance(item_ids, list) or not item_ids:
        invalid("item_ids must be a non-empty array.")
    if data["from_price_point_id"] == data["to_price_point_id"]:
        invalid("to_price_point_id must differ from from_price_point_id.")

    items = [get_row("item", item_id) for item_id in item_ids]
    for item in items:
        if item["price_point_id"] != from_p["id"]:
            raise ApiError(ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT)

    row = new_row("conversion_project", {
        "store_id": store["id"],
        "from_price_point_id": from_p["id"],
        "to_price_point_id": to_p["id"],
        "expected_store_version": store["version"],
        "status": "DRAFT",
        "coverage_delta_pct": 0.0,
    })
    insert("conversion_project", row)
    refresh_project_coverage(row)
    store["version"] = store["version"] + 1
    store["updated_at"] = db.now_iso()
    return ok_object({
        "store_id": store["id"],
        "issued_item_count": len(items),
        "to_price_point_id": to_p["id"],
        "rejected_item_ids": [],
    }, 201)


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message)