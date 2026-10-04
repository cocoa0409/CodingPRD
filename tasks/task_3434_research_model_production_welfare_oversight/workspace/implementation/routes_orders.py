"""Customers, customer orders, and allocations (PRD 3.6, 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import domain
import validation as V
from auth import authenticate, require_role, require_ownership
from responses import ApiError, success_object
from store import db, new_id, next_seq, now, touch

bp = Blueprint("orders", __name__)


def _invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------

@bp.post("/api/customers")
def create_customer():
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    b = V.body()
    name = V.v_str(b, "institution_name")
    account = V.v_str(b, "account_number")
    limit = V.v_int(b, "credit_limit_cents", minv=0)
    min_health = V.v_enum(b, "accepted_min_health_status", V.BARRIER_LEVELS)
    commercial = V.opt_bool(b, "is_commercial", False)
    for c in db["customers"].values():
        if c["account_number"] == account:
            raise ApiError("ERR_DUPLICATE_KEY", 409, "account_number already exists")
    cid = new_id()
    db["customers"][cid] = {
        "id": cid,
        "institution_name": name,
        "account_number": account,
        "credit_limit_cents": limit,
        "account_status": "ACTIVE",
        "accepted_min_health_status": min_health,
        "is_commercial": commercial,
        "_billed_cents": 0,
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_customer(db["customers"][cid]), 201)


def _customer_owned_read(cid):
    """Shared p1-p4 for customer-scoped reads: auth, role, ownership, existence."""
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin", "FacilityManager", "Customer"])
    if role == "Customer":
        require_ownership(uid, cid)
    return V.get_or_404("customers", cid)


@bp.get("/api/customers/<cid>")
def get_customer(cid):
    cust = _customer_owned_read(cid)
    return success_object(calc.ser_customer(cust))


@bp.post("/api/customers/<cid>/transition")
def customer_transition(cid):
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    cust = V.get_or_404("customers", cid)
    b = V.body()
    target = V.v_str(b, "target_state")
    cur = cust["account_status"]
    if target == "CREDIT_HOLD":
        if cur != "ACTIVE":
            raise _invalid_state("Account cannot enter CREDIT_HOLD from %s" % cur)
        cust["account_status"] = "CREDIT_HOLD"
    elif target == "ACTIVE":
        if cur == "CREDIT_HOLD":
            cust["account_status"] = "ACTIVE"
        elif cur == "SUSPENDED":
            for insp in db["inspections"].values():
                if insp["customer_id"] == cid and insp["status"] == "ESCALATED":
                    raise _invalid_state("An escalated inspection blocks reinstatement")
            cust["account_status"] = "ACTIVE"
        else:
            raise _invalid_state("Account cannot enter ACTIVE from %s" % cur)
    elif target == "SUSPENDED":
        if cur not in ("ACTIVE", "CREDIT_HOLD"):
            raise _invalid_state("Account cannot be suspended from %s" % cur)
        cust["account_status"] = "SUSPENDED"
    else:
        raise _invalid_state("Unknown target_state %s" % target)
    touch("customers", cid)
    return success_object(calc.ser_customer(cust))


@bp.get("/api/customers/<cid>/orders")
def customer_orders(cid):
    _customer_owned_read(cid)
    items = [o for o in db["orders"].values() if o["customer_id"] == cid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [o for o in items if o["status"] == status_filter]
    return V.paginate(items, calc.ser_order)


@bp.get("/api/customers/<cid>/contracts")
def customer_contracts(cid):
    _customer_owned_read(cid)
    items = [c for c in db["contracts"].values() if c["customer_id"] == cid]
    return V.paginate(items, calc.ser_contract)


@bp.get("/api/customers/<cid>/inspections")
def customer_inspections(cid):
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin", "FacilityManager", "Veterinarian", "Customer", "WelfareInspector"])
    if role == "Customer":
        require_ownership(uid, cid)
    V.get_or_404("customers", cid)
    items = [i for i in db["inspections"].values() if i["customer_id"] == cid]
    return V.paginate(items, calc.ser_inspection)


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------

@bp.post("/api/orders")
def create_order():
    uid, role = authenticate()
    require_role(role, ["Customer"])
    # The Customer identity is entity-backed: it must name an existing customer.
    customer = db["customers"].get(uid)
    if customer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer %s not found" % uid)
    b = V.body()
    # Priority 4: present body foreign keys resolve.
    strain = V.get_or_404("strains", b["strain_id"]) if b.get("strain_id") is not None else None
    # Priority 7: minimum lead time (14 days), evaluated when parseable.
    if b.get("required_delivery_date") is not None:
        try:
            rdd = V.parse_dt(b["required_delivery_date"])
        except (ValueError, TypeError):
            rdd = None
        if rdd is not None and rdd < now() + timedelta(days=calc.MIN_ORDER_LEAD_DAYS):
            raise ApiError(
                "ERR_DELIVERY_WINDOW_INFEASIBLE",
                422,
                "required_delivery_date precedes the minimum 14-day lead time",
            )
    # Priority 8: fields, enums, quantity, windows.
    strain_id = V.v_str(b, "strain_id")
    qm = V.v_int(b, "quantity_male", minv=0)
    qf = V.v_int(b, "quantity_female", minv=0)
    min_age = V.v_int(b, "min_age_weeks", minv=0)
    max_age = V.v_int(b, "max_age_weeks", minv=0)
    min_w = V.v_num(b, "min_weight_g", minv=0, exclusive_min=True)
    max_w = V.v_num(b, "max_weight_g", minv=0, exclusive_min=True)
    rdd = V.v_dt(b, "required_delivery_date")
    min_health = V.opt_enum(b, "min_health_status", V.BARRIER_LEVELS, "MPF")
    if qm + qf < 1:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "quantity_male + quantity_female must be >= 1")
    if min_age > max_age:
        raise ApiError("ERR_INVALID_AGE_WINDOW", 422, "min_age_weeks exceeds max_age_weeks")
    if not min_w < max_w:
        raise ApiError("ERR_INVALID_WEIGHT_WINDOW", 422, "min_weight_g must be < max_weight_g")
    # Priority 10: account standing.
    if customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 403, "Customer account is not ACTIVE")
    oid = new_id()
    db["orders"][oid] = {
        "id": oid,
        "customer_id": uid,
        "strain_id": strain_id,
        "quantity_male": qm,
        "quantity_female": qf,
        "min_age_weeks": min_age,
        "max_age_weeks": max_age,
        "min_weight_g": min_w,
        "max_weight_g": max_w,
        "required_delivery_date": rdd,
        "min_health_status": min_health,
        "status": "SUBMITTED",
        "quoted_total_cents": None,
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_order(db["orders"][oid]), 201)


def _order_read(oid):
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin", "FacilityManager", "Customer", "LogisticsCoordinator"])
    order = V.get_or_404("orders", oid)
    if role == "Customer":
        require_ownership(uid, order["customer_id"])
    return uid, role, order


@bp.get("/api/orders/<oid>")
def get_order(oid):
    uid, role, order = _order_read(oid)
    return success_object(calc.ser_order(order))


@bp.post("/api/orders/<oid>/transition")
def order_transition(oid):
    uid, role = authenticate()
    require_role(role, ["FacilityManager", "Customer", "PlatformAdmin"])
    order = V.get_or_404("orders", oid)
    b = V.body()
    target = V.v_str(b, "target_state")
    # Per-target authorization, then ownership, then state.
    if target in ("SOURCING", "BACKORDERED", "REJECTED"):
        require_role(role, ["FacilityManager"])
    elif target == "CANCELLED":
        require_role(role, ["Customer", "PlatformAdmin"])
        if role == "Customer":
            require_ownership(uid, order["customer_id"])
    elif target == "CLOSED":
        require_role(role, ["Customer"])
        require_ownership(uid, order["customer_id"])
    else:
        raise _invalid_state("Unknown target_state %s" % target)
    cur = order["status"]

    if target == "SOURCING":
        if cur == "BACKORDERED":
            # Supply-loop retry: no gates, RESERVED allocations are kept.
            order["status"] = "SOURCING"
        elif cur == "SUBMITTED":
            strain = db["strains"].get(order["strain_id"])
            # Priority 8: PROJECTED feasibility over eligible colonies.
            supply = calc.eligible_projected_supply(order)
            if supply < order["quantity_male"] + order["quantity_female"]:
                raise ApiError(
                    "ERR_SUPPLY_INSUFFICIENT",
                    422,
                    "PROJECTED availability is below the requested total; route to BACKORDERED",
                )
            customer = db["customers"].get(order["customer_id"])
            # Priority 10: account standing, then credit exposure.
            if customer is None or customer["account_status"] != "ACTIVE":
                raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 403, "Customer account is not ACTIVE")
            quote = calc.order_quote(order, strain)
            _, exposure = calc.credit_positions(customer)
            if exposure + quote > customer["credit_limit_cents"]:
                raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 422, "Credit limit would be exceeded")
            order["quoted_total_cents"] = quote
            order["status"] = "SOURCING"
        else:
            raise _invalid_state("Order cannot enter SOURCING from %s" % cur)
    elif target == "BACKORDERED":
        if cur == "SUBMITTED":
            customer = db["customers"].get(order["customer_id"])
            if customer is None or customer["account_status"] != "ACTIVE":
                raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 403, "Customer account is not ACTIVE")
            strain = db["strains"].get(order["strain_id"])
            order["quoted_total_cents"] = calc.order_quote(order, strain)
            order["status"] = "BACKORDERED"
        elif cur == "SOURCING":
            order["status"] = "BACKORDERED"
        else:
            raise _invalid_state("Order cannot enter BACKORDERED from %s" % cur)
    elif target == "REJECTED":
        if cur != "SUBMITTED":
            raise _invalid_state("Order cannot be rejected from %s" % cur)
        order["status"] = "REJECTED"
    elif target == "CANCELLED":
        if cur not in ("SUBMITTED", "SOURCING", "BACKORDERED", "ALLOCATED", "SCHEDULED"):
            raise _invalid_state("Order cannot be cancelled from %s" % cur)
        if cur == "SCHEDULED":
            for sh in db["shipments"].values():
                if sh["order_id"] == oid and sh["status"] in ("PLANNED", "LOADED"):
                    domain.cancel_shipment(sh)
        for a in db["allocations"].values():
            if a["order_id"] == oid and a["status"] == "RESERVED":
                domain.release_allocation(a)
        order["status"] = "CANCELLED"
    elif target == "CLOSED":
        if cur != "DELIVERED":
            raise _invalid_state("Order cannot be closed from %s" % cur)
        order["status"] = "CLOSED"
    touch("orders", oid)
    return success_object(calc.ser_order(order))


@bp.get("/api/orders/<oid>/allocations")
def order_allocations(oid):
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin", "FacilityManager", "Veterinarian", "IACUCReviewer", "Customer", "LogisticsCoordinator", "WelfareInspector"])
    order = V.get_or_404("orders", oid)
    if role == "Customer":
        require_ownership(uid, order["customer_id"])
    items = [a for a in db["allocations"].values() if a["order_id"] == oid]
    return V.paginate(items, calc.ser_allocation)


@bp.get("/api/orders/<oid>/shipments")
def order_shipments(oid):
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin", "FacilityManager", "Veterinarian", "IACUCReviewer", "Customer", "LogisticsCoordinator", "WelfareInspector"])
    order = V.get_or_404("orders", oid)
    if role == "Customer":
        require_ownership(uid, order["customer_id"])
    items = [s for s in db["shipments"].values() if s["order_id"] == oid]
    return V.paginate(items, calc.ser_shipment)


# --------------------------------------------------------------------------
# Allocations
# --------------------------------------------------------------------------

@bp.post("/api/allocations")
def create_allocation():
    uid, role = authenticate()
    require_role(role, ["FacilityManager"])
    b = V.body()
    # Priority 4: present body foreign keys resolve.
    order = V.get_or_404("orders", b["order_id"]) if b.get("order_id") is not None else None
    cohort = V.get_or_404("cohorts", b["cohort_id"]) if b.get("cohort_id") is not None else None
    # Priority 5: optimistic concurrency on the order's version.
    if order is not None and V.is_int(b.get("expected_order_version")):
        if b["expected_order_version"] != order["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_order_version is stale")
    colony = db["colonies"].get(cohort["colony_id"]) if cohort is not None else None
    room = db["rooms"].get(colony["room_id"]) if colony is not None else None
    # Priority 6: business safety gates.
    if room is not None and room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_QUARANTINED", 409, "Room is not ACTIVE")
    if colony is not None:
        if colony["genetic_status"] == "DRIFT_DETECTED":
            raise ApiError("ERR_GENETIC_DRIFT", 409, "Colony is DRIFT_DETECTED")
        if colony["genetic_status"] == "PANEL_DUE":
            raise ApiError("ERR_PANEL_OVERDUE", 409, "Colony SNP panel is overdue")
        protocol = db["protocols"].get(colony["protocol_id"])
        if protocol is not None and protocol["status"] != "APPROVED":
            raise ApiError("ERR_PROTOCOL_NOT_APPROVED", 409, "Protocol is not APPROVED")
    # Priority 7: cohort age at the order's required delivery date.
    if order is not None and cohort is not None:
        age = calc.age_weeks(cohort["birth_date"], order["required_delivery_date"])
        if not (order["min_age_weeks"] <= age <= order["max_age_weeks"]):
            raise ApiError("ERR_AGE_SPEC_MISMATCH", 422, "Cohort age at delivery is outside the window")
    # Priority 8: required fields, types, quantity minimum.
    order_id = V.v_str(b, "order_id")
    cohort_id = V.v_str(b, "cohort_id")
    qty_m = V.v_int(b, "qty_male", minv=0)
    qty_f = V.v_int(b, "qty_female", minv=0)
    V.v_int(b, "expected_order_version")
    if qty_m + qty_f < 1:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "qty_male + qty_female must be >= 1")
    # Priority 9: referential rules in ladder order.
    if colony["strain_id"] != order["strain_id"]:
        raise ApiError("ERR_STRAIN_MISMATCH", 422, "Cohort colony strain differs from the order strain")
    if qty_m > 0 and not (order["min_weight_g"] <= cohort["avg_weight_g_male"] <= order["max_weight_g"]):
        raise ApiError("ERR_WEIGHT_SPEC_MISMATCH", 422, "Male average weight outside the window")
    if qty_f > 0 and not (order["min_weight_g"] <= cohort["avg_weight_g_female"] <= order["max_weight_g"]):
        raise ApiError("ERR_WEIGHT_SPEC_MISMATCH", 422, "Female average weight outside the window")
    rm, rf = calc.cohort_reserved(cohort_id)
    if (
        cohort["status"] not in ("HOLD", "PARTIALLY_ALLOCATED")
        or cohort["count_male"] - rm < qty_m
        or cohort["count_female"] - rf < qty_f
    ):
        raise ApiError("ERR_COHORT_NOT_ALLOCATABLE", 409, "Cohort has insufficient free headcount")
    if order["status"] not in ("SOURCING", "BACKORDERED"):
        raise ApiError("ERR_ORDER_NOT_SOURCING", 409, "Order is not in SOURCING or BACKORDERED")
    aid = new_id()
    db["allocations"][aid] = {
        "id": aid,
        "order_id": order_id,
        "cohort_id": cohort_id,
        "qty_male": qty_m,
        "qty_female": qty_f,
        "status": "RESERVED",
        "created_at": now(),
        "_seq": next_seq(),
    }
    domain.recompute_cohort(cohort)
    touch("cohorts", cohort_id)
    domain.order_coverage(order)
    touch("orders", order_id)
    return success_object(calc.ser_allocation(db["allocations"][aid]), 201)


@bp.post("/api/allocations/<aid>/release")
def release_allocation(aid):
    uid, role = authenticate()
    require_role(role, ["FacilityManager"])
    alloc = V.get_or_404("allocations", aid)
    if alloc["status"] != "RESERVED":
        raise _invalid_state("Allocation is not RESERVED")
    domain.release_allocation(alloc)
    return success_object(calc.ser_allocation(alloc))
