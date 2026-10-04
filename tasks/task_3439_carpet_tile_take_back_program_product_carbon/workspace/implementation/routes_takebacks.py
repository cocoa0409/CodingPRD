"""TakeBackRequest endpoints (PRD 3.5): request, schedule, collect, sort
(including cascade C — depolymerized mass re-enters as a feedstock lot),
cancel."""
from decimal import Decimal

from flask import Blueprint, request

from auth import authenticate, authorize, forbid
from calcs import supplier_reliability, takeback_credit
from constants import (
    ALL_ROLES,
    CONDITION_GRADES,
    TAKEBACK_LOT_CARBON_FACTOR,
    TAKEBACK_SUPPLIER_NAME,
)
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_takeback
from store import STORE, new_common, touch
from util import get_body, parse_dt, q2, req_decimal, req_enum, req_str, to_decimal

bp = Blueprint("takebacks", __name__)


@bp.route("/carpetloop/take-back-requests", methods=["POST"])
def create_takeback():
    uid, role = authenticate()
    authorize(role, {"Specifier"})
    body = get_body()
    # Priority 4, canonical order: collection before site (PRD 2.10).
    collection = None
    if body.get("collection_id") is not None:
        collection = STORE.collections.get(body["collection_id"])
        if collection is None:
            raise ApiError("ERR_COLLECTION_NOT_FOUND", 404, "Collection does not exist")
    site = None
    if body.get("site_id") is not None:
        site = STORE.sites.get(body["site_id"])
        if site is None:
            raise ApiError("ERR_SITE_NOT_FOUND", 404, "Site does not exist")
    # Priority 6: the site must be INSTALLED or IN_SERVICE.
    if site is not None and site["status"] not in ("INSTALLED", "IN_SERVICE"):
        raise ApiError("ERR_SITE_NOT_INSTALLED", 409, "Site is not INSTALLED or IN_SERVICE")
    # Priority 11: request shape.
    req_str(body, "collection_id")
    req_str(body, "site_id")
    grade = req_enum(body, "condition_grade", CONDITION_GRADES)
    declared_area = req_decimal(body, "declared_area_m2", min_exclusive=0)
    t = new_common(STORE)
    t.update(
        {
            "site_id": site["id"],
            "collection_id": collection["id"],
            "condition_grade": grade,
            "declared_area_m2": declared_area,
            "pickup_window_start": None,
            "pickup_window_end": None,
            "collected_kg": None,
            "reuse_kg": None,
            "depolymerize_kg": None,
            "downcycle_kg": None,
            "landfill_kg": None,
            "credit_variant": None,
            "credit_cents": None,
            "credited_at": None,
            "status": "REQUESTED",
            "created_by": uid,
        }
    )
    STORE.takebacks[t["id"]] = t
    return success(serialize_takeback(t), 201)


@bp.route("/carpetloop/take-back-requests/<takeback_id>", methods=["GET"])
def get_takeback(takeback_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    t = STORE.takebacks.get(takeback_id)
    if t is None:
        raise ApiError("ERR_TAKEBACK_NOT_FOUND", 404, "Take-back request does not exist")
    return success(serialize_takeback(t), 200)


@bp.route("/carpetloop/take-back-requests", methods=["GET"])
def list_takebacks():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("site_id", "collection_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.takebacks.values(), request.args, filters, serialize_takeback)


def _installer_takeback(takeback_id, uid):
    """Priority 3 ownership via the take-back's site, then priority 4."""
    t = STORE.takebacks.get(takeback_id)
    if t is not None:
        site = STORE.sites.get(t["site_id"])
        if site is not None and uid != site["contractor_name"]:
            forbid("X-User-ID must equal the site's contractor_name")
    if t is None:
        raise ApiError("ERR_TAKEBACK_NOT_FOUND", 404, "Take-back request does not exist")
    return t


@bp.route("/carpetloop/take-back-requests/<takeback_id>/schedule", methods=["POST"])
def schedule_takeback(takeback_id):
    uid, role = authenticate()
    authorize(role, {"Installer"})
    t = _installer_takeback(takeback_id, uid)
    # Priority 5: REQUESTED -> SCHEDULED only.
    if t["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Take-back is not in REQUESTED")
    body = get_body()
    # Priority 10: the window must be well-formed and open strictly in the
    # future per the logical clock.
    pws = parse_dt(body.get("pickup_window_start"))
    pwe = parse_dt(body.get("pickup_window_end"))
    if pws is not None and pwe is not None:
        if not (pws < pwe) or not (pws > STORE.now()):
            raise ApiError(
                "ERR_PICKUP_WINDOW_INVALID",
                422,
                "pickup_window_start must be earlier than pickup_window_end and after the logical clock",
            )
    # Priority 11: request shape.
    pws = req_dt_pair(body, "pickup_window_start", pws)
    pwe = req_dt_pair(body, "pickup_window_end", pwe)
    t["pickup_window_start"] = pws
    t["pickup_window_end"] = pwe
    t["status"] = "SCHEDULED"
    touch(STORE, t)
    return success(serialize_takeback(t), 200)


def req_dt_pair(body, field, parsed):
    if parsed is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field '%s': required ISO-8601 timestamp" % field
        )
    return parsed


@bp.route("/carpetloop/take-back-requests/<takeback_id>/collect", methods=["POST"])
def collect_takeback(takeback_id):
    uid, role = authenticate()
    authorize(role, {"Installer"})
    t = _installer_takeback(takeback_id, uid)
    # Priority 5: SCHEDULED -> COLLECTED only.
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Take-back is not in SCHEDULED")
    # Priority 10: the logical clock must have reached the window's opening.
    if not (STORE.now() >= t["pickup_window_start"]):
        raise ApiError(
            "ERR_COLLECT_WINDOW_NOT_OPEN",
            422,
            "The pickup window has not opened per the logical clock",
        )
    body = get_body()
    # Priority 11: weighed mass must be positive.
    collected = req_decimal(body, "collected_kg", min_exclusive=0)
    t["collected_kg"] = collected
    t["status"] = "COLLECTED"
    touch(STORE, t)
    return success(serialize_takeback(t), 200)


@bp.route("/carpetloop/take-back-requests/<takeback_id>/cancel", methods=["POST"])
def cancel_takeback(takeback_id):
    uid, role = authenticate()
    authorize(role, {"Specifier"})
    t = STORE.takebacks.get(takeback_id)
    # Priority 3: Specifier ownership via created_by.
    if t is not None and uid != t["created_by"]:
        forbid("X-User-ID must equal the take-back's created_by")
    if t is None:
        raise ApiError("ERR_TAKEBACK_NOT_FOUND", 404, "Take-back request does not exist")
    # Priority 5: cancel exists from REQUESTED and SCHEDULED.
    if t["status"] not in ("REQUESTED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Take-back cannot be cancelled from its state")
    if t["status"] == "SCHEDULED":
        t["pickup_window_start"] = None
        t["pickup_window_end"] = None
    t["status"] = "CANCELLED"
    touch(STORE, t)
    return success(serialize_takeback(t), 200)


@bp.route("/carpetloop/take-back-requests/<takeback_id>/sort", methods=["POST"])
def sort_takeback(takeback_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    t = STORE.takebacks.get(takeback_id)
    if t is None:
        raise ApiError("ERR_TAKEBACK_NOT_FOUND", 404, "Take-back request does not exist")
    # Priority 5: COLLECTED -> CREDITED only.
    if t["status"] != "COLLECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Take-back is not in COLLECTED")
    body = get_body()
    # Priority 11: pathway masses present and numeric (400 for shape); each
    # >= 0 and their sum == collected_kg at 2 decimal places (422 imbalance).
    masses = {}
    for f in ("reuse_kg", "depolymerize_kg", "downcycle_kg", "landfill_kg"):
        v = to_decimal(body.get(f))
        if v is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Field '%s': required number" % f
            )
        masses[f] = v
    total = sum(masses.values(), Decimal("0"))
    if any(v < 0 for v in masses.values()) or q2(total) != q2(t["collected_kg"]):
        raise ApiError(
            "ERR_SORT_MASS_IMBALANCE",
            422,
            "Pathway masses must be >= 0 and sum to collected_kg at 2 decimal places",
        )
    t["reuse_kg"] = masses["reuse_kg"]
    t["depolymerize_kg"] = masses["depolymerize_kg"]
    t["downcycle_kg"] = masses["downcycle_kg"]
    t["landfill_kg"] = masses["landfill_kg"]
    collection = STORE.collections.get(t["collection_id"])
    variant, credit_cents = takeback_credit(collection, t)
    t["credit_variant"] = variant
    t["credit_cents"] = credit_cents
    t["credited_at"] = STORE.now()
    t["status"] = "CREDITED"
    touch(STORE, t)
    # Cascade C (PRD 2.9): depolymerized mass re-enters as a feedstock lot.
    if masses["depolymerize_kg"] > 0:
        reliability = supplier_reliability(STORE, TAKEBACK_SUPPLIER_NAME)
        lot = new_common(STORE)
        qty = masses["depolymerize_kg"]
        lot.update(
            {
                "supplier_name": TAKEBACK_SUPPLIER_NAME,
                "source_type": "POST_CONSUMER_TILE",
                "quantity_kg": qty,
                "carbon_factor_kgco2e_per_kg": TAKEBACK_LOT_CARBON_FACTOR,
                "origin_takeback_id": t["id"],
                "supplier_reliability_pct": reliability,
                "allocated_kg": Decimal("0"),
                "available_kg": qty,
                "status": "RECEIVED",
            }
        )
        STORE.lots[lot["id"]] = lot
    return success(serialize_takeback(t), 200)
