# Supplier domain (PRD 3.1): registration, listing, and the two parallel state
# dimensions (QUALIFICATION / AGREEMENT) driven through one transitions route.
from flask import Blueprint, request

import clock
import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_dt, get_enum, get_int, get_str

bp = Blueprint("suppliers", __name__, url_prefix="/protein-ops/suppliers")

ANY_ROLE = constants.ROLES
QUALIFICATION_TARGETS = ["PENDING_AUDIT", "QUALIFIED", "SUSPENDED", "DISQUALIFIED"]
AGREEMENT_TARGETS = ["DRAFT", "ACTIVE", "TERMINATED", "EXPIRED", "COMPLETED"]


@bp.route("", methods=["POST"])
def create_supplier():
    _user_id, role = authenticate()
    authorize(role, ["ProcurementManager"])

    body = body_json()
    shape = Shape()
    supplier_code = get_str(body, "supplier_code", shape, non_empty=True)
    isolate_type = get_enum(body, "isolate_type", constants.ISOLATE_TYPES, shape)
    committed_volume_kg = get_int(body, "committed_volume_kg", shape, minv=1)
    base_price = get_int(body, "base_price_per_kg_cents", shape)
    price_floor = get_int(body, "price_floor_cents", shape)
    price_cap = get_int(body, "price_cap_cents", shape)
    start_raw, start_dt = get_dt(body, "agreement_start_date", shape)
    end_raw, end_dt = get_dt(body, "agreement_end_date", shape)

    # Tier 8: uniqueness of supplier_code.
    if supplier_code is not None:
        for existing in db["suppliers"].values():
            if existing["supplier_code"] == supplier_code:
                raise err("ERR_UNIQUE_CONSTRAINT", "supplier_code already exists")

    # Tier 11 (shape): price rails floor < base < cap; agreement end after start.
    if base_price is not None and price_floor is not None and price_floor >= base_price:
        shape.add("price_floor_cents", "must be strictly below base_price_per_kg_cents")
    if base_price is not None and price_cap is not None and price_cap <= base_price:
        shape.add("price_cap_cents", "must be strictly above base_price_per_kg_cents")
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        shape.add("agreement_end_date", "must be after agreement_start_date")
    shape.raise_if_any()

    supplier = make_entity(
        "suppliers",
        {
            "supplier_code": supplier_code,
            "isolate_type": isolate_type,
            "qualification_status": "PENDING_AUDIT",
            "audit_score": None,
            "agreement_status": "DRAFT",
            "agreement_start_date": start_raw,
            "agreement_end_date": end_raw,
            "committed_volume_kg": committed_volume_kg,
            "delivered_volume_kg": 0,
            "base_price_per_kg_cents": base_price,
            "price_floor_cents": price_floor,
            "price_cap_cents": price_cap,
            "open_lot_count": 0,
        },
    )
    supplier["_dt"]["agreement_start_date"] = start_dt
    supplier["_dt"]["agreement_end_date"] = end_dt
    return success(public(supplier), "object", 201)


@bp.route("", methods=["GET"])
def list_suppliers():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["suppliers"].values())
    for param in ("qualification_status", "agreement_status", "isolate_type"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, meta = paginate([public(s) for s in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<sid>/transitions", methods=["POST"])
def supplier_transition(sid):
    _user_id, role = authenticate()
    authorize(role, ["ProcurementManager"])

    supplier = db["suppliers"].get(sid)
    if supplier is None:
        raise err("ERR_NOT_FOUND", "supplier not found")

    # Terminal lockdown precedence (PRD 3.1): once DISQUALIFIED, every further
    # transition call on either dimension fails before any other gate.
    if supplier["qualification_status"] == "DISQUALIFIED":
        raise err("ERR_INVALID_STATE", "supplier is DISQUALIFIED (terminal)")

    body = body_json()
    shape = Shape()
    dimension = get_enum(body, "dimension", ["QUALIFICATION", "AGREEMENT"], shape)

    if dimension == "QUALIFICATION":
        target = get_enum(body, "target_status", QUALIFICATION_TARGETS, shape)
        audit_score = get_int(body, "audit_score", shape, required=False, minv=0, maxv=100)
        if target is not None:
            _qualification_transition(supplier, target, audit_score, shape)
    elif dimension == "AGREEMENT":
        target = get_enum(body, "target_status", AGREEMENT_TARGETS, shape)
        if target is not None:
            _agreement_transition(supplier, target)
    else:
        # Unknown/missing dimension: shape error only (tier 11).
        shape.raise_if_any()
        return  # unreachable

    shape.raise_if_any()
    mark(supplier)
    flush_dirty()
    return success(public(supplier), "object", 200)


def _qualification_transition(supplier, target, audit_score, shape):
    current = supplier["qualification_status"]
    if target == "QUALIFIED":
        if current not in ("PENDING_AUDIT", "SUSPENDED"):
            raise err("ERR_INVALID_STATE", "cannot qualify from %s" % current)
        threshold = (
            constants.QUALIFY_MIN_AUDIT_SCORE
            if current == "PENDING_AUDIT"
            else constants.REQUALIFY_MIN_AUDIT_SCORE
        )
        if audit_score is not None and audit_score < threshold:
            raise err(
                "ERR_SUPPLIER_NOT_QUALIFIABLE",
                "audit_score %d below required %d" % (audit_score, threshold),
            )
        if audit_score is None:
            shape.add("audit_score", "is required when target_status is QUALIFIED")
            return
        supplier["qualification_status"] = "QUALIFIED"
        supplier["audit_score"] = audit_score
    elif target == "SUSPENDED":
        if current != "QUALIFIED":
            raise err("ERR_INVALID_STATE", "cannot suspend from %s" % current)
        supplier["qualification_status"] = "SUSPENDED"
    elif target == "DISQUALIFIED":
        if current not in ("QUALIFIED", "SUSPENDED"):
            raise err("ERR_INVALID_STATE", "cannot disqualify from %s" % current)
        # Cascade link 1: ACTIVE agreement -> TERMINATED (manual-termination rules).
        if supplier["agreement_status"] == "ACTIVE":
            supplier["agreement_status"] = "TERMINATED"
            # Cascade link 2: every QUARANTINE lot -> REJECTED.
            _reject_quarantine_lots(supplier)
        supplier["qualification_status"] = "DISQUALIFIED"
    else:  # PENDING_AUDIT — no transition ever targets it.
        raise err("ERR_INVALID_STATE", "no transition to %s" % target)


def _agreement_transition(supplier, target):
    current = supplier["agreement_status"]
    if target == "ACTIVE":
        if current != "DRAFT":
            raise err("ERR_INVALID_STATE", "cannot activate agreement from %s" % current)
        # Tier 7 temporal: agreement end must lie in the future.
        end_dt = supplier["_dt"].get("agreement_end_date")
        if end_dt is None or end_dt <= clock.now():
            raise err("ERR_INVALID_WINDOW", "agreement_end_date is not in the future")
        # Tier 9 cross-entity: qualification must already be QUALIFIED.
        if supplier["qualification_status"] != "QUALIFIED":
            raise err("ERR_AGREEMENT_REQUIRES_QUALIFIED", "qualification_status is not QUALIFIED")
        supplier["agreement_status"] = "ACTIVE"
    elif target == "TERMINATED":
        if current not in ("DRAFT", "ACTIVE"):
            raise err("ERR_INVALID_STATE", "cannot terminate agreement from %s" % current)
        if current == "ACTIVE":
            _reject_quarantine_lots(supplier)
        supplier["agreement_status"] = "TERMINATED"
    else:
        # DRAFT (no inbound transition) and EXPIRED/COMPLETED (system-only).
        raise err("ERR_INVALID_STATE", "no client transition to %s" % target)


def _reject_quarantine_lots(supplier):
    for lot in db["lots"].values():
        if lot["supplier_id"] == supplier["id"] and lot["qc_status"] == "QUARANTINE":
            lot["qc_status"] = "REJECTED"
            mark(lot)
            supplier["open_lot_count"] -= 1
