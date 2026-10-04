"""Flask app: all routes, error handlers."""
import os
import sys

from flask import Flask, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import errors
import core
from core import (new_id, now, make_common, touch, find_by, ensure_unique,
                  enqueue_signal, dispatch_signal, ack_signal, fail_signal,
                  has_exhausted_signal, compute_term_price, find_anchor,
                  recompute_family, post_ledger, create_subscription,
                  subscription_refund_cents, cancel_immediate,
                  cancel_end_of_term, run_renewals, apply_supersession,
                  signal_path_for, retry_base_minutes, MAX_ATTEMPTS,
                  HW_ORDER, PAID_KINDS, PAID_STATUSES, TERMINAL_SUB_STATUSES,
                  SECONDS_PER_DAY, RENEWAL_DISCLOSURE_LEAD_DAYS)
from middleware import get_auth, require_roles
from response import (success_object, success_list, error_response,
                      iso_from_ts, ts_from_iso, parse_pagination)
import serializers as S

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(errors.ApiError)
def _api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _not_found(e):
    return error_response(errors.not_found("route not found"))


@app.errorhandler(405)
def _method(e):
    return error_response(errors.not_found("route not found"))


@app.errorhandler(Exception)
def _generic(e):
    if isinstance(e, errors.ApiError):
        return error_response(e)
    return error_response(errors.invalid_request(str(e)))


def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def get_or_404(store, key):
    e = store.get(key)
    if e is None:
        raise errors.not_found()
    return e


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"{field} required")
    return v


def opt_enum(b, field, allowed, default=None):
    v = b.get(field, default)
    if v is None:
        raise errors.invalid_request(f"{field} required")
    if v not in allowed:
        raise errors.invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def opt_int(b, field, default=None):
    v = b.get(field, default)
    if v is None:
        raise errors.invalid_request(f"{field} required")
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"{field} must be integer")
    return v


def opt_bool(b, field, default=None):
    v = b.get(field, default)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise errors.invalid_request(f"{field} must be boolean")
    return v


def owner_check(sub, role, user_id):
    if role == "Customer" and sub["customer_id"] != user_id:
        raise errors.forbidden_owner()


ALL_READ_ROLES = ["PlatformAdmin", "AutomakerPartner", "DealerPartner",
                  "Customer", "RetentionAgent", "SystemOperator"]


# --------------------------------------------------------------- clock & ops

@app.post("/api/v1/_clock/set_current_utc")
def set_clock():
    require_roles(["PlatformAdmin", "SystemOperator"])
    b = body()
    ts = ts_from_iso(b.get("to_iso8601"))
    db.set_now(ts)
    # re-evaluate now-dependent system transitions (billing batch semantics)
    result = run_renewals()
    return success_object({"now_iso8601": iso_from_ts(ts)})


@app.post("/api/v1/_billing/run_renewals")
def billing_run():
    require_roles(["SystemOperator"])
    result = run_renewals()
    return success_object(result)


@app.post("/api/v1/_signals/dispatch")
def signals_dispatch():
    require_roles(["SystemOperator"])
    ts = now()
    dispatched = 0
    superseded = 0
    # group by radio, FIFO by created_at (insertion sequence breaks ties
    # among commands enqueued within the same logical instant)
    cmds = sorted(db.signal_commands.values(),
                  key=lambda c: (c["created_at"], c.get("_seq", 0)))
    for c in cmds:
        if c["status"] != "QUEUED":
            continue
        if c["next_retry_at"] is not None and c["next_retry_at"] > ts:
            continue
        # per-radio FIFO: no earlier non-terminal QUEUED/SENT command for same radio
        blocked = False
        for other in db.signal_commands.values():
            if other["radio_id"] != c["radio_id"] or other["id"] == c["id"]:
                continue
            if other["status"] in ("QUEUED", "SENT") and (
                other["created_at"], other.get("_seq", 0)
            ) < (c["created_at"], c.get("_seq", 0)):
                blocked = True
                break
        if blocked:
            continue
        dispatch_signal(c)
        dispatched += 1
    return success_object({"dispatched_count": dispatched, "superseded_count": superseded})


@app.post("/api/v1/_signals/<sid>/force_send")
def signal_force_send(sid):
    require_roles(["SystemOperator"])
    cmd = get_or_404(db.signal_commands, sid)
    if cmd["status"] != "QUEUED":
        raise errors.invalid_state("signal not QUEUED")
    dispatch_signal(cmd)
    return success_object(S.signal_view(cmd))


# --------------------------------------------------------------- reference data

@app.post("/api/v1/automakers")
def create_automaker():
    require_roles(["PlatformAdmin"])
    b = body()
    oem_code = req_str(b, "oem_code")
    name = req_str(b, "name")
    email = req_str(b, "feed_contact_email")
    ensure_unique(db.automakers, "oem_code", oem_code, "oem_code duplicate")
    e = {"id": new_id(), "oem_code": oem_code, "name": name,
         "feed_contact_email": email, "status": "ACTIVE"}
    make_common(e)
    db.automakers[e["id"]] = e
    return success_object(S.automaker_view(e), 201)


@app.get("/api/v1/automakers/<aid>")
def get_automaker(aid):
    require_roles(ALL_READ_ROLES)
    e = get_or_404(db.automakers, aid)
    return success_object(S.automaker_view(e))


@app.get("/api/v1/automakers/<aid>/vehicles")
def automaker_vehicles(aid):
    require_roles(["PlatformAdmin", "AutomakerPartner", "RetentionAgent", "SystemOperator"])
    get_or_404(db.automakers, aid)
    items = [v for v in db.vehicles.values() if v["automaker_id"] == aid]
    items.sort(key=lambda v: (v["created_at"], v["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.vehicle_view(v) for v in page], limit, offset, len(items))


@app.post("/api/v1/dealers")
def create_dealer():
    require_roles(["PlatformAdmin"])
    b = body()
    code = req_str(b, "dealer_code")
    name = req_str(b, "name")
    enrolled = b.get("used_program_enrolled", False)
    if not isinstance(enrolled, bool):
        raise errors.invalid_request("used_program_enrolled must be boolean")
    ensure_unique(db.dealers, "dealer_code", code, "dealer_code duplicate")
    e = {"id": new_id(), "dealer_code": code, "name": name,
         "used_program_enrolled": enrolled,
         "used_program_enrolled_at": now() if enrolled else None,
         "status": "ACTIVE"}
    make_common(e)
    db.dealers[e["id"]] = e
    return success_object(S.dealer_view(e), 201)


@app.get("/api/v1/dealers/<did>")
def get_dealer(did):
    require_roles(ALL_READ_ROLES)
    e = get_or_404(db.dealers, did)
    return success_object(S.dealer_view(e))


@app.post("/api/v1/dealers/<did>/enroll-used-program")
def enroll_dealer(did):
    require_roles(["PlatformAdmin"])
    e = get_or_404(db.dealers, did)
    if not e["used_program_enrolled"]:
        e["used_program_enrolled"] = True
        e["used_program_enrolled_at"] = now()
    touch(e)
    return success_object(S.dealer_view(e))


@app.post("/api/v1/customers")
def create_customer():
    # Anonymous: no auth headers required
    role = request.headers.get("X-User-Role")
    if role is not None and role not in ("Anonymous", "PlatformAdmin"):
        # still allow; but per PRD registration is Anonymous self-service
        pass
    b = body()
    email = req_str(b, "email")
    full_name = req_str(b, "full_name")
    hh = b.get("household_size", 1)
    if isinstance(hh, bool) or not isinstance(hh, int) or hh < 1:
        raise errors.invalid_request("household_size must be >= 1")
    ensure_unique(db.customers, "email", email, "email duplicate")
    e = {"id": new_id(), "email": email, "full_name": full_name,
         "status": "ACTIVE", "household_size": hh}
    make_common(e)
    db.customers[e["id"]] = e
    return success_object(S.customer_view(e), 201)


@app.get("/api/v1/customers/<cid>")
def get_customer(cid):
    role, uid = require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    e = get_or_404(db.customers, cid)
    if role == "Customer" and e["id"] != uid:
        raise errors.forbidden_owner()
    return success_object(S.customer_view(e))


@app.get("/api/v1/customers/<cid>/api/v1/subscriptions")
def customer_subscriptions(cid):
    role, uid = require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    get_or_404(db.customers, cid)
    if role == "Customer" and cid != uid:
        raise errors.forbidden_owner()
    items = [s for s in db.subscriptions.values() if s["customer_id"] == cid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.subscription_view(s) for s in page], limit, offset, len(items))


@app.get("/api/v1/customers/<cid>/vehicles")
def customer_vehicles(cid):
    role, uid = require_roles(ALL_READ_ROLES)
    get_or_404(db.customers, cid)
    if role == "Customer" and cid != uid:
        raise errors.forbidden_owner()
    items = [v for v in db.vehicles.values() if v["owner_customer_id"] == cid]
    items.sort(key=lambda v: (v["created_at"], v["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.vehicle_view(v) for v in page], limit, offset, len(items))


@app.get("/api/v1/customers/<cid>/redemptions")
def customer_redemptions(cid):
    role, uid = require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    get_or_404(db.customers, cid)
    if role == "Customer" and cid != uid:
        raise errors.forbidden_owner()
    items = [r for r in db.redemptions.values() if r["customer_id"] == cid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.redemption_view(r) for r in page], limit, offset, len(items))


@app.post("/api/v1/package-tiers")
def create_tier():
    require_roles(["PlatformAdmin"])
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    ent = b.get("channel_entitlements")
    if not isinstance(ent, list) or not all(isinstance(x, str) for x in ent):
        raise errors.invalid_request("channel_entitlements must be list of strings")
    inc = b.get("includes_streaming", False)
    if not isinstance(inc, bool):
        raise errors.invalid_request("includes_streaming must be boolean")
    mhg = opt_enum(b, "min_hardware_generation", {"GEN1", "GEN2", "GEN3"}, "GEN1")
    ensure_unique(db.package_tiers, "code", code, "tier code duplicate")
    e = {"id": new_id(), "code": code, "name": name, "channel_entitlements": ent,
         "includes_streaming": inc, "min_hardware_generation": mhg}
    make_common(e)
    db.package_tiers[e["id"]] = e
    return success_object(S.package_tier_view(e), 201)


@app.get("/api/v1/package-tiers/<tid>")
def get_tier(tid):
    require_roles(ALL_READ_ROLES)
    e = get_or_404(db.package_tiers, tid)
    return success_object(S.package_tier_view(e))


@app.get("/api/v1/package-tiers/<tid>/subscription-plans")
def tier_plans(tid):
    require_roles(ALL_READ_ROLES)
    get_or_404(db.package_tiers, tid)
    items = [p for p in db.plans.values() if p["package_tier_id"] == tid]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.plan_view(p) for p in page], limit, offset, len(items))


# --------------------------------------------------------------- vehicles & radios

@app.post("/api/v1/vehicles")
def create_vehicle():
    require_roles(["PlatformAdmin", "AutomakerPartner", "DealerPartner"])
    b = body()
    vin = req_str(b, "vin")
    if len(vin) != 17:
        raise errors.invalid_request("vin must be 17 characters")
    am_id = b.get("automaker_id")
    if not isinstance(am_id, str):
        raise errors.invalid_request("automaker_id required")
    if am_id not in db.automakers:
        raise errors.reference_not_found("automaker_id does not resolve")
    my = opt_int(b, "model_year")
    if my < 1990:
        raise errors.invalid_request("model_year must be >= 1990")
    owner = b.get("owner_customer_id")
    if not isinstance(owner, str):
        raise errors.invalid_request("owner_customer_id required")
    if owner not in db.customers:
        raise errors.reference_not_found("owner_customer_id does not resolve")
    cond = opt_enum(b, "condition", {"NEW", "USED"})
    ensure_unique(db.vehicles, "vin", vin, "vin duplicate")
    e = {"id": new_id(), "vin": vin, "automaker_id": am_id, "model_year": my,
         "owner_customer_id": owner, "condition": cond}
    make_common(e)
    db.vehicles[e["id"]] = e
    return success_object(S.vehicle_view(e), 201)


@app.get("/api/v1/vehicles/<vid>")
def get_vehicle(vid):
    require_roles(ALL_READ_ROLES)
    e = get_or_404(db.vehicles, vid)
    return success_object(S.vehicle_view(e))


@app.get("/api/v1/vehicles/<vid>/api/v1/radios")
def vehicle_radios(vid):
    require_roles(ALL_READ_ROLES)
    get_or_404(db.vehicles, vid)
    items = [r for r in db.radios.values() if r["vehicle_id"] == vid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.radio_view(r) for r in page], limit, offset, len(items))


@app.post("/api/v1/radios")
def create_radio():
    require_roles(["PlatformAdmin", "AutomakerPartner"])
    b = body()
    esn = req_str(b, "esn")
    veh_id = b.get("vehicle_id")
    if not isinstance(veh_id, str):
        raise errors.invalid_request("vehicle_id required")
    if veh_id not in db.vehicles:
        raise errors.reference_not_found("vehicle_id does not resolve")
    hg = opt_enum(b, "hardware_generation", {"GEN1", "GEN2", "GEN3"})
    ensure_unique(db.radios, "esn", esn, "esn duplicate")
    e = {"id": new_id(), "esn": esn, "vehicle_id": veh_id,
         "hardware_generation": hg, "activation_status": "UNREGISTERED",
         "last_signal_at": None}
    make_common(e)
    db.radios[e["id"]] = e
    return success_object(S.radio_view(e), 201)


@app.get("/api/v1/radios/<rid>")
def get_radio(rid):
    require_roles(ALL_READ_ROLES)
    e = get_or_404(db.radios, rid)
    return success_object(S.radio_view(e))


@app.get("/api/v1/radios/<rid>/api/v1/subscriptions")
def radio_subscriptions(rid):
    require_roles(ALL_READ_ROLES)
    get_or_404(db.radios, rid)
    items = [s for s in db.subscriptions.values() if s["radio_id"] == rid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.subscription_view(s) for s in page], limit, offset, len(items))


@app.get("/api/v1/radios/<rid>/api/v1/signal-commands")
def radio_signals(rid):
    require_roles(["PlatformAdmin", "SystemOperator", "RetentionAgent"])
    get_or_404(db.radios, rid)
    items = [c for c in db.signal_commands.values() if c["radio_id"] == rid]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.signal_view(c) for c in page], limit, offset, len(items))


# --------------------------------------------------------------- trial provisioning

def _check_trial_eligible(radio):
    if radio["activation_status"] not in ("UNREGISTERED", "DEACTIVATED"):
        raise errors.radio_ineligible("radio activation_status not eligible")
    for s in db.subscriptions.values():
        if s["radio_id"] == radio["id"] and s["status"] not in TERMINAL_SUB_STATUSES:
            raise errors.radio_ineligible("radio has non-terminal subscription")


def _check_hw_gate(plan, radio):
    tier = db.package_tiers.get(plan["package_tier_id"])
    if tier is None:
        raise errors.reference_not_found("plan tier missing")
    if HW_ORDER[tier["min_hardware_generation"]] > HW_ORDER[radio["hardware_generation"]]:
        raise errors.hardware_incompatible()


def _origin_for_actor(role, default="WEB_SIGNUP"):
    if role == "AutomakerPartner":
        return "OEM_FEED"
    if role == "DealerPartner":
        return "USED_DEALER"
    return default


@app.post("/api/v1/radios/<rid>/trials")
def radio_trial(rid):
    role, uid = require_roles(["PlatformAdmin", "AutomakerPartner", "DealerPartner", "Customer"])
    radio = get_or_404(db.radios, rid)
    b = body()
    plan_id = b.get("plan_id")
    customer_id = b.get("customer_id")
    if not isinstance(plan_id, str) or plan_id not in db.plans:
        raise errors.reference_not_found("plan_id does not resolve")
    if not isinstance(customer_id, str) or customer_id not in db.customers:
        raise errors.reference_not_found("customer_id does not resolve")
    plan = db.plans[plan_id]
    # state/business order: eligibility before plan-kind gate per validations table
    _check_trial_eligible(radio)
    if not plan["is_trial"]:
        raise errors.trial_plan_required()
    _check_hw_gate(plan, radio)
    expected = b.get("expected_radio_version")
    if expected is None or not isinstance(expected, int) or expected != radio["version"]:
        raise errors.stale_version()
    origin = _origin_for_actor(role, "WEB_SIGNUP")
    sub = create_subscription(customer_id, plan, radio["id"], "TRIAL", origin)
    touch(radio)
    return success_object(S.subscription_view(sub), 201)


@app.post("/api/v1/automakers/<aid>/data-feeds")
def automaker_feed(aid):
    role, uid = require_roles(["AutomakerPartner"])
    am = get_or_404(db.automakers, aid)
    if am["id"] != uid:
        raise errors.forbidden_owner("data feed only for own automaker record")
    b = body()
    items = b.get("items")
    if not isinstance(items, list):
        raise errors.invalid_request("items must be a list")
    results = []
    provisioned = 0
    rejected = 0
    for item in items:
        if not isinstance(item, dict):
            results.append({"status": "rejected", "reason": "ERR_INVALID_REQUEST"})
            rejected += 1
            continue
        radio_id = item.get("radio_id")
        customer_id = item.get("customer_id")
        plan_id = item.get("plan_id")
        try:
            radio = db.radios.get(radio_id)
            if radio is None:
                raise errors.reference_not_found("radio_id does not resolve")
            cust = db.customers.get(customer_id)
            if cust is None:
                raise errors.reference_not_found("customer_id does not resolve")
            plan = db.plans.get(plan_id)
            if plan is None:
                raise errors.reference_not_found("plan_id does not resolve")
            _check_trial_eligible(radio)
            if not plan["is_trial"]:
                raise errors.trial_plan_required()
            _check_hw_gate(plan, radio)
            sub = create_subscription(cust["id"], plan, radio["id"], "TRIAL", "OEM_FEED")
            touch(radio)
            results.append({"status": "provisioned", "subscription_id": sub["id"],
                            "radio_id": radio_id})
            provisioned += 1
        except errors.ApiError as e:
            results.append({"status": "rejected", "reason": e.error_id,
                            "radio_id": radio_id})
            rejected += 1
    return success_object({"results": results, "provisioned_count": provisioned,
                           "rejected_count": rejected})


@app.post("/api/v1/dealers/<did>/used-reactivations")
def used_reactivation(did):
    role, uid = require_roles(["DealerPartner"])
    dealer = get_or_404(db.dealers, did)
    if dealer["id"] != uid:
        raise errors.forbidden_owner("reactivation only for own dealer record")
    b = body()
    radio_id = b.get("radio_id")
    customer_id = b.get("customer_id")
    plan_id = b.get("plan_id")
    if not isinstance(radio_id, str) or radio_id not in db.radios:
        raise errors.reference_not_found("radio_id does not resolve")
    if not isinstance(customer_id, str) or customer_id not in db.customers:
        raise errors.reference_not_found("customer_id does not resolve")
    if not isinstance(plan_id, str) or plan_id not in db.plans:
        raise errors.reference_not_found("plan_id does not resolve")
    radio = db.radios[radio_id]
    plan = db.plans[plan_id]
    _check_trial_eligible(radio)
    if not dealer["used_program_enrolled"]:
        raise errors.dealer_not_enrolled()
    if not plan["is_trial"]:
        raise errors.trial_plan_required()
    _check_hw_gate(plan, radio)
    sub = create_subscription(customer_id, plan, radio_id, "TRIAL", "USED_DEALER")
    touch(radio)
    return success_object(S.subscription_view(sub), 201)


# --------------------------------------------------------------- transfer

@app.post("/api/v1/vehicles/<vid>/transfer_ownership")
def transfer_vehicle(vid):
    role, uid = require_roles(["PlatformAdmin", "DealerPartner", "Customer"])
    vehicle = get_or_404(db.vehicles, vid)
    b = body()
    new_owner = b.get("new_owner_customer_id")
    if not isinstance(new_owner, str) or new_owner not in db.customers:
        raise errors.reference_not_found("new_owner_customer_id does not resolve")
    used_dealer_id = b.get("used_dealer_id")
    if used_dealer_id is not None:
        if not isinstance(used_dealer_id, str) or used_dealer_id not in db.dealers:
            raise errors.reference_not_found("used_dealer_id does not resolve")
    trial_plan_id = b.get("trial_plan_id")
    trial_plan = None
    if trial_plan_id is not None:
        if not isinstance(trial_plan_id, str) or trial_plan_id not in db.plans:
            raise errors.reference_not_found("trial_plan_id does not resolve")
        trial_plan = db.plans[trial_plan_id]
    # ownership: Customer may only transfer own vehicle
    if role == "Customer" and vehicle["owner_customer_id"] != uid:
        raise errors.forbidden_owner()
    expected = b.get("expected_vehicle_version")
    if expected is None or not isinstance(expected, int) or expected != vehicle["version"]:
        raise errors.stale_version()
    old_owner = vehicle["owner_customer_id"]
    vehicle["owner_customer_id"] = new_owner
    touch(vehicle)
    # transfer away active/cancel_scheduled subs on this vehicle's radios
    radios = [r for r in db.radios.values() if r["vehicle_id"] == vid]
    for radio in radios:
        for s in list(db.subscriptions.values()):
            if s["radio_id"] != radio["id"]:
                continue
            if s["status"] not in ("ACTIVE", "CANCEL_SCHEDULED"):
                continue
            credit = 0
            if s["kind"] in PAID_KINDS:
                credit = subscription_refund_cents(s)
                post_ledger(s["id"], "TRANSFER_ADJUSTMENT", -credit,
                            note="transfer proration credit")
            s["status"] = "TRANSFERRED_AWAY"
            touch(s)
            enqueue_signal(radio["id"], s["id"], "DEACTIVATE")
        # fresh trial for the new owner
        if trial_plan is not None:
            if not trial_plan["is_trial"]:
                raise errors.trial_plan_required()
            origin = "USED_DEALER" if used_dealer_id else "TRANSFER_IN"
            create_subscription(new_owner, trial_plan, radio["id"], "TRIAL", origin)
            touch(radio)
    recompute_family(old_owner)
    if new_owner != old_owner:
        recompute_family(new_owner)
    return success_object(S.vehicle_view(vehicle))


# --------------------------------------------------------------- subscriptions

@app.post("/api/v1/subscriptions")
def purchase_subscription():
    role, uid = require_roles(["Customer", "RetentionAgent", "PlatformAdmin"])
    b = body()
    customer_id = b.get("customer_id")
    plan_id = b.get("plan_id")
    if not isinstance(customer_id, str) or customer_id not in db.customers:
        raise errors.reference_not_found("customer_id does not resolve")
    if not isinstance(plan_id, str) or plan_id not in db.plans:
        raise errors.reference_not_found("plan_id does not resolve")
    plan = db.plans[plan_id]
    radio_id = b.get("radio_id")
    radio = None
    if radio_id is not None:
        if not isinstance(radio_id, str) or radio_id not in db.radios:
            raise errors.reference_not_found("radio_id does not resolve")
        radio = db.radios[radio_id]
    # Customer may only purchase for self
    if role == "Customer" and customer_id != uid:
        raise errors.forbidden_owner()
    if plan["is_trial"]:
        raise errors.paid_plan_required()
    if plan["service_mode"] == "STREAMING_ONLY":
        radio = None
        radio_id = None
    elif radio is None:
        raise errors.invalid_request("radio_id required for non-streaming plan")
    if radio is not None:
        _check_hw_gate(plan, radio)
    auto_renew = b.get("auto_renew")
    if auto_renew is not None and not isinstance(auto_renew, bool):
        raise errors.invalid_request("auto_renew must be boolean")
    origin = "CALL_CENTER" if role == "RetentionAgent" else "WEB_SIGNUP"
    sub = create_subscription(customer_id, plan, radio_id, "PAID", origin,
                              auto_renew=auto_renew)
    return success_object(S.subscription_view(sub), 201)


@app.get("/api/v1/subscriptions/<sid>")
def get_subscription(sid):
    require_roles(ALL_READ_ROLES)
    e = get_or_404(db.subscriptions, sid)
    return success_object(S.subscription_view(e))


@app.get("/api/v1/subscriptions/<sid>/ledger")
def subscription_ledger(sid):
    role, uid = require_roles(["PlatformAdmin", "Customer", "RetentionAgent", "SystemOperator"])
    sub = get_or_404(db.subscriptions, sid)
    if role == "Customer" and sub["customer_id"] != uid:
        raise errors.forbidden_owner()
    items = [e for e in db.ledger_entries.values() if e["subscription_id"] == sid]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.ledger_view(e) for e in page], limit, offset, len(items))


@app.get("/api/v1/subscriptions/<sid>/disclosures")
def subscription_disclosures(sid):
    role, uid = require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    sub = get_or_404(db.subscriptions, sid)
    if role == "Customer" and sub["customer_id"] != uid:
        raise errors.forbidden_owner()
    items = [d for d in db.disclosures.values() if d["subscription_id"] == sid]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.disclosure_view(d) for d in page], limit, offset, len(items))


@app.get("/api/v1/subscriptions/<sid>/signal-commands")
def subscription_signals(sid):
    require_roles(["PlatformAdmin", "SystemOperator", "RetentionAgent"])
    get_or_404(db.subscriptions, sid)
    items = [c for c in db.signal_commands.values() if c["subscription_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.signal_view(c) for c in page], limit, offset, len(items))


@app.get("/api/v1/subscriptions/<sid>/redemptions")
def subscription_redemptions(sid):
    role, uid = require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    sub = get_or_404(db.subscriptions, sid)
    if role == "Customer" and sub["customer_id"] != uid:
        raise errors.forbidden_owner()
    items = [r for r in db.redemptions.values() if r["subscription_id"] == sid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.redemption_view(r) for r in page], limit, offset, len(items))


@app.post("/api/v1/subscriptions/<sid>/suspend")
def suspend_subscription(sid):
    role, uid = require_roles(["Customer", "RetentionAgent"])
    sub = get_or_404(db.subscriptions, sid)
    if sub["status"] != "ACTIVE":
        raise errors.invalid_state("suspend requires ACTIVE")
    owner_check(sub, role, uid)
    if has_exhausted_signal(sub["id"]):
        raise errors.signal_exhausted_block()
    sub["status"] = "SUSPENDED"
    touch(sub)
    if sub["radio_id"] is not None:
        enqueue_signal(sub["radio_id"], sub["id"], "SUSPEND")
    recompute_family(sub["customer_id"])
    return success_object(S.subscription_view(sub))


@app.post("/api/v1/subscriptions/<sid>/resume")
def resume_subscription(sid):
    role, uid = require_roles(["Customer", "RetentionAgent"])
    sub = get_or_404(db.subscriptions, sid)
    if sub["status"] != "SUSPENDED":
        raise errors.invalid_state("resume requires SUSPENDED")
    owner_check(sub, role, uid)
    if now() >= sub["end_at"]:
        raise errors.invalid_state("subscription past end_at must expire, not resume")
    sub["status"] = "ACTIVE"
    touch(sub)
    if sub["radio_id"] is not None:
        enqueue_signal(sub["radio_id"], sub["id"], "RESUME")
    recompute_family(sub["customer_id"])
    return success_object(S.subscription_view(sub))


@app.post("/api/v1/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    role, uid = require_roles(["Customer", "RetentionAgent"])
    sub = get_or_404(db.subscriptions, sid)
    b = body()
    mode = opt_enum(b, "effective_mode", {"IMMEDIATE", "END_OF_TERM"})
    if sub["status"] not in ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("cancel not allowed from current state")
    owner_check(sub, role, uid)
    if mode == "END_OF_TERM":
        if sub["status"] == "PENDING_ACTIVATION":
            raise errors.invalid_state("PENDING_ACTIVATION supports only IMMEDIATE cancel")
        cancel_end_of_term(sub)
        return success_object(S.subscription_view(sub))
    # IMMEDIATE
    if sub["status"] == "PENDING_ACTIVATION":
        cancel_immediate(sub)
        return success_object(S.subscription_view(sub))
    # ACTIVE or SUSPENDED
    if sub["kind"] in PAID_KINDS and sub["auto_renew"]:
        if sub["disclosure_state"] not in ("SENT", "ACKNOWLEDGED"):
            raise errors.renewal_disclosure_required()
    if has_exhausted_signal(sub["id"]):
        raise errors.signal_exhausted_block()
    cancel_immediate(sub)
    return success_object(S.subscription_view(sub))


@app.post("/api/v1/subscriptions/<sid>/save-offers/accept")
def save_offer_accept(sid):
    role, uid = require_roles(["Customer", "RetentionAgent"])
    sub = get_or_404(db.subscriptions, sid)
    b = body()
    step_id = b.get("offer_step_id")
    if not isinstance(step_id, str) or step_id not in db.offer_steps:
        raise errors.reference_not_found("offer_step_id does not resolve")
    step = db.offer_steps[step_id]
    if sub["status"] != "CANCEL_SCHEDULED":
        raise errors.invalid_state("save-accept requires CANCEL_SCHEDULED")
    owner_check(sub, role, uid)
    campaign = db.campaigns.get(step["campaign_id"])
    if campaign is None or campaign["lifecycle_phase"] != "SAVE" or campaign["state"] != "ACTIVE":
        raise errors.invalid_state("save offer must come from an ACTIVE SAVE campaign")
    if sub["save_offers_used_in_term"] >= 2:
        raise errors.save_cap_reached()
    # eligibility + cap
    _check_step_eligible(step, sub["customer_id"])
    _check_step_sequence(step, campaign, sub["customer_id"])
    # accept: revert cancel
    plan = db.plans[sub["plan_id"]]
    sub["cancel_requested_at"] = None
    sub["auto_renew"] = True
    sub["kind"] = "SAVE_OFFER"
    sub["origin"] = "SAVE_ACCEPT"
    sub["status"] = "ACTIVE"
    sub["save_offers_used_in_term"] += 1
    # next-term save price: offer discount applied to base plan price
    base = int(plan["price_cents"])
    pct = (base * int(step["discount_pct_bps"])) // 10000
    offer_discount = pct + int(step["flat_discount_cents"])
    if offer_discount > base:
        offer_discount = base
    next_price = base - offer_discount
    if next_price < 0:
        next_price = 0
    discount_amount = base - next_price
    sub["current_term_price_cents"] = next_price
    sub["disclosure_state"] = "REQUIRED"
    touch(sub)
    post_ledger(sub["id"], "SAVE_CREDIT", -discount_amount, note="save offer next-term discount")
    _record_redemption(campaign["id"], step["id"], sub["customer_id"], sub["id"], next_price)
    recompute_family(sub["customer_id"])
    return success_object(S.subscription_view(sub))


@app.post("/api/v1/subscriptions/<sid>/disclosures/send")
def disclosure_send(sid):
    require_roles(["RetentionAgent", "PlatformAdmin", "SystemOperator"])
    sub = get_or_404(db.subscriptions, sid)
    b = body()
    dtype = opt_enum(b, "disclosure_type",
                     {"RENEWAL_NOTICE", "SAVE_RENEWAL_NOTICE", "TRIAL_END_NOTICE"})
    channel = opt_enum(b, "channel", {"EMAIL", "POSTAL"})
    d = {"id": new_id(), "subscription_id": sid, "disclosure_type": dtype,
         "channel": channel, "sent_at": now(), "due_before": sub["end_at"],
         "acknowledged_at": None, "created_at": now()}
    db.disclosures[d["id"]] = d
    if sub["disclosure_state"] == "REQUIRED":
        need = "SAVE_RENEWAL_NOTICE" if sub["kind"] == "SAVE_OFFER" else "RENEWAL_NOTICE"
        if dtype == need:
            sub["disclosure_state"] = "SENT"
            touch(sub)
    return success_object(S.disclosure_view(d), 201)


@app.post("/api/v1/subscriptions/<sid>/disclosures/<did>/acknowledge")
def disclosure_ack(sid, did):
    role, uid = require_roles(["Customer"])
    sub = get_or_404(db.subscriptions, sid)
    d = db.disclosures.get(did)
    if d is None or d["subscription_id"] != sid:
        raise errors.not_found()
    if sub["customer_id"] != uid:
        raise errors.forbidden_owner()
    if d["acknowledged_at"] is None:
        d["acknowledged_at"] = now()
    if sub["disclosure_state"] == "SENT":
        need = "SAVE_RENEWAL_NOTICE" if sub["kind"] == "SAVE_OFFER" else "RENEWAL_NOTICE"
        recs = [x for x in db.disclosures.values()
                if x["subscription_id"] == sid and x["disclosure_type"] == need]
        if recs and all(x["acknowledged_at"] is not None for x in recs):
            sub["disclosure_state"] = "ACKNOWLEDGED"
            touch(sub)
    return success_object(S.disclosure_view(d))


@app.post("/api/v1/subscriptions/<sid>/signals/requeue")
def signal_requeue(sid):
    require_roles(["RetentionAgent"])
    sub = get_or_404(db.subscriptions, sid)
    b = body()
    ctype = opt_enum(b, "command_type", {"ACTIVATE", "DEACTIVATE", "SUSPEND", "RESUME"})
    idem = req_str(b, "idempotency_key")
    if sub["radio_id"] is None:
        raise errors.invalid_request("subscription has no radio")
    existing = find_by(db.signal_commands, "idempotency_key", idem)
    if existing is not None:
        return success_object(S.signal_view(existing), 201)
    cmd = enqueue_signal(sub["radio_id"], sub["id"], ctype, idem_key=idem)
    # The replacement clears the exhausted-signal block (PRD endpoint table:
    # requeue "clears the block"); the exhausted command remains terminal
    # history.
    for other in db.signal_commands.values():
        if (other["subscription_id"] == sid and other["id"] != cmd["id"]
                and other["status"] == "EXHAUSTED"
                and other["command_type"] == ctype):
            other["block_cleared"] = True
    return success_object(S.signal_view(cmd), 201)


# --------------------------------------------------------------- signal ops

@app.post("/api/v1/signal-commands/<sid>/ack")
def signal_ack(sid):
    require_roles(["SystemOperator"])
    cmd = get_or_404(db.signal_commands, sid)
    ack_signal(cmd)
    return success_object(S.signal_view(cmd))


@app.post("/api/v1/signal-commands/<sid>/fail")
def signal_fail(sid):
    require_roles(["SystemOperator"])
    cmd = get_or_404(db.signal_commands, sid)
    fail_signal(cmd)
    return success_object(S.signal_view(cmd))


@app.get("/api/v1/signal-commands/<sid>")
def signal_get(sid):
    require_roles(["PlatformAdmin", "SystemOperator", "RetentionAgent"])
    cmd = get_or_404(db.signal_commands, sid)
    return success_object(S.signal_view(cmd))


# --------------------------------------------------------------- offers

def _record_redemption(campaign_id, step_id, customer_id, subscription_id, price):
    r = {"id": new_id(), "campaign_id": campaign_id, "offer_step_id": step_id,
         "customer_id": customer_id, "subscription_id": subscription_id,
         "redeemed_price_cents": int(price), "redeemed_at": now(),
         "created_at": now()}
    db.redemptions[r["id"]] = r
    return r


def _customer_redeemed_step_indexes(customer_id, campaign_id):
    out = set()
    for r in db.redemptions.values():
        if r["customer_id"] == customer_id and r["campaign_id"] == campaign_id:
            st = db.offer_steps.get(r["offer_step_id"])
            if st is not None:
                out.add(st["step_index"])
    return out


def _eligibility_holds(step, customer_id):
    expr = step.get("eligibility_expr") or {}
    cust = db.customers.get(customer_id)
    if cust is None:
        return False
    mhs = expr.get("min_household_size")
    if mhs is not None and cust["household_size"] < mhs:
        return False
    if expr.get("requires_streaming"):
        # customer must have a non-terminal subscription on a streaming-capable plan
        ok = False
        for s in db.subscriptions.values():
            if s["customer_id"] != customer_id or s["status"] in TERMINAL_SUB_STATUSES:
                continue
            p = db.plans.get(s["plan_id"])
            if p is None:
                continue
            tier = db.package_tiers.get(p["package_tier_id"])
            if p["service_mode"] in ("STREAMING_ONLY", "BUNDLED") or (tier and tier["includes_streaming"]):
                ok = True
                break
        if not ok:
            return False
    req = expr.get("required_prior_offer_step_indexes") or []
    if req:
        redeemed = _customer_redeemed_step_indexes(customer_id, step["campaign_id"])
        for si in req:
            if si not in redeemed:
                return False
    return True


def _check_step_eligible(step, customer_id):
    if not _eligibility_holds(step, customer_id):
        raise errors.offer_ineligible()
    count = sum(1 for r in db.redemptions.values()
                if r["offer_step_id"] == step["id"] and r["customer_id"] == customer_id)
    if count >= int(step["max_redemptions_per_customer"]):
        raise errors.offer_ineligible("redemption cap reached")


def _check_step_sequence(step, campaign, customer_id):
    rank = int(step["step_up_rank"])
    if rank <= 0:
        return
    redeemed = _customer_redeemed_step_indexes(customer_id, campaign["id"])
    for other in db.offer_steps.values():
        if other["campaign_id"] != campaign["id"] or other["id"] == step["id"]:
            continue
        if int(other["step_up_rank"]) >= rank:
            continue
        if other["step_index"] in redeemed:
            continue
        if not _eligibility_holds(other, customer_id):
            continue
        raise errors.offer_sequence_violation()


@app.post("/api/v1/offer-campaigns")
def create_campaign():
    require_roles(["PlatformAdmin"])
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    phase = opt_enum(b, "lifecycle_phase", {"IN_TRIAL", "POST_TRIAL", "WINBACK", "SAVE"})
    ws = ts_from_iso(b.get("window_start_at"))
    we = ts_from_iso(b.get("window_end_at"))
    if we <= ws:
        raise errors.campaign_window("window_end_at must be > window_start_at")
    ensure_unique(db.campaigns, "code", code, "campaign code duplicate")
    e = {"id": new_id(), "code": code, "name": name, "lifecycle_phase": phase,
         "state": "DRAFT", "window_start_at": ws, "window_end_at": we}
    make_common(e)
    db.campaigns[e["id"]] = e
    return success_object(S.campaign_view(e), 201)


@app.get("/api/v1/offer-campaigns/<cid>")
def get_campaign(cid):
    require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    e = get_or_404(db.campaigns, cid)
    return success_object(S.campaign_view(e))


@app.get("/api/v1/offer-campaigns/<cid>/steps")
def campaign_steps(cid):
    require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    get_or_404(db.campaigns, cid)
    items = [s for s in db.offer_steps.values() if s["campaign_id"] == cid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.offer_step_view(s) for s in page], limit, offset, len(items))


@app.get("/api/v1/offer-campaigns/<cid>/redemptions")
def campaign_redemptions(cid):
    require_roles(["PlatformAdmin", "RetentionAgent"])
    get_or_404(db.campaigns, cid)
    items = [r for r in db.redemptions.values() if r["campaign_id"] == cid]
    cust = request.args.get("customer_id")
    if cust:
        items = [r for r in items if r["customer_id"] == cust]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.redemption_view(r) for r in page], limit, offset, len(items))


@app.post("/api/v1/offer-campaigns/<cid>/steps")
def add_step(cid):
    require_roles(["PlatformAdmin"])
    campaign = get_or_404(db.campaigns, cid)
    b = body()
    if campaign["state"] not in ("DRAFT", "PAUSED"):
        raise errors.invalid_state("steps only on DRAFT or PAUSED campaign")
    plan_id = b.get("plan_id")
    if not isinstance(plan_id, str) or plan_id not in db.plans:
        raise errors.reference_not_found("plan_id does not resolve")
    step_index = opt_int(b, "step_index")
    if step_index < 0:
        raise errors.invalid_request("step_index must be >= 0")
    for s in db.offer_steps.values():
        if s["campaign_id"] == cid and s["step_index"] == step_index:
            raise errors.duplicate("step_index duplicate within campaign")
    rank = opt_int(b, "step_up_rank", 0)
    pct = opt_int(b, "discount_pct_bps", 0)
    if pct < 0 or pct > 10000:
        raise errors.invalid_request("discount_pct_bps must be 0..10000")
    flat = opt_int(b, "flat_discount_cents", 0)
    if flat < 0:
        raise errors.invalid_request("flat_discount_cents must be >= 0")
    expr = b.get("eligibility_expr")
    if expr is not None and not isinstance(expr, dict):
        raise errors.invalid_request("eligibility_expr must be object")
    maxr = opt_int(b, "max_redemptions_per_customer", 1)
    if maxr < 1:
        raise errors.invalid_request("max_redemptions_per_customer must be >= 1")
    e = {"id": new_id(), "campaign_id": cid, "step_index": step_index,
         "plan_id": plan_id, "step_up_rank": rank, "discount_pct_bps": pct,
         "flat_discount_cents": flat, "eligibility_expr": expr,
         "max_redemptions_per_customer": maxr}
    make_common(e)
    db.offer_steps[e["id"]] = e
    return success_object(S.offer_step_view(e), 201)


def _overlap(a, b):
    return a["window_start_at"] < b["window_end_at"] and b["window_start_at"] < a["window_end_at"]


@app.post("/api/v1/offer-campaigns/<cid>/activate")
def activate_campaign(cid):
    require_roles(["PlatformAdmin"])
    c = get_or_404(db.campaigns, cid)
    if c["state"] not in ("DRAFT", "PAUSED"):
        raise errors.invalid_state("activate requires DRAFT or PAUSED")
    if c["state"] == "DRAFT":
        has_step = any(s["campaign_id"] == cid for s in db.offer_steps.values())
        if not has_step:
            raise errors.invalid_state("campaign has no steps")
    if c["window_end_at"] <= now():
        raise errors.campaign_window("campaign window already over")
    for other in db.campaigns.values():
        if other["id"] == cid:
            continue
        if other["lifecycle_phase"] != c["lifecycle_phase"]:
            continue
        if other["state"] not in ("ACTIVE", "PAUSED"):
            continue
        if _overlap(c, other):
            raise errors.campaign_overlap()
    c["state"] = "ACTIVE"
    touch(c)
    return success_object(S.campaign_view(c))


@app.post("/api/v1/offer-campaigns/<cid>/pause")
def pause_campaign(cid):
    require_roles(["PlatformAdmin"])
    c = get_or_404(db.campaigns, cid)
    if c["state"] != "ACTIVE":
        raise errors.invalid_state("pause requires ACTIVE")
    c["state"] = "PAUSED"
    touch(c)
    return success_object(S.campaign_view(c))


@app.post("/api/v1/offer-campaigns/<cid>/archive")
def archive_campaign(cid):
    require_roles(["PlatformAdmin"])
    c = get_or_404(db.campaigns, cid)
    if c["state"] not in ("ACTIVE", "PAUSED"):
        raise errors.invalid_state("archive requires ACTIVE or PAUSED")
    has_red = any(r["campaign_id"] == cid for r in db.redemptions.values())
    if not (now() > c["window_end_at"] or not has_red):
        raise errors.invalid_state("archive requires past window or zero redemptions")
    c["state"] = "ARCHIVED"
    touch(c)
    return success_object(S.campaign_view(c))


@app.post("/api/v1/offer-campaigns/<cid>/redeem")
def redeem(cid):
    role, uid = require_roles(["Customer", "RetentionAgent"])
    campaign = get_or_404(db.campaigns, cid)
    b = body()
    step_id = b.get("offer_step_id")
    customer_id = b.get("customer_id")
    if not isinstance(step_id, str) or step_id not in db.offer_steps:
        raise errors.reference_not_found("offer_step_id does not resolve")
    if not isinstance(customer_id, str) or customer_id not in db.customers:
        raise errors.reference_not_found("customer_id does not resolve")
    step = db.offer_steps[step_id]
    if step["campaign_id"] != cid:
        raise errors.not_found("step not in campaign")
    radio_id = b.get("radio_id")
    radio = None
    if radio_id is not None:
        if not isinstance(radio_id, str) or radio_id not in db.radios:
            raise errors.reference_not_found("radio_id does not resolve")
        radio = db.radios[radio_id]
    if role == "Customer" and customer_id != uid:
        raise errors.forbidden_owner()
    plan = db.plans[step["plan_id"]]
    if plan["is_trial"]:
        raise errors.paid_plan_required()
    if plan["service_mode"] == "STREAMING_ONLY":
        radio = None
        radio_id = None
    elif radio is None:
        raise errors.invalid_request("radio_id required for non-streaming plan")
    if radio is not None:
        _check_hw_gate(plan, radio)
    # campaign window + state
    ts = now()
    if campaign["state"] != "ACTIVE" or not (campaign["window_start_at"] <= ts <= campaign["window_end_at"]):
        raise errors.campaign_window("campaign not ACTIVE or outside window")
    _check_step_sequence(step, campaign, customer_id)
    _check_step_eligible(step, customer_id)
    # price: offer_step_pricing then term engine with family
    base = int(plan["price_cents"])
    pct = (base * int(step["discount_pct_bps"])) // 10000
    offer_discount = pct + int(step["flat_discount_cents"])
    if offer_discount > base:
        offer_discount = base
    origin = "CALL_CENTER" if role == "RetentionAgent" else "WEB_SIGNUP"
    sub = create_subscription(customer_id, plan, radio_id, "PAID", origin,
                              offer_step=step)
    red = _record_redemption(cid, step["id"], customer_id, sub["id"],
                             sub["current_term_price_cents"])
    # Redemption must exist before family recompute derives prices from it;
    # create_subscription ran its recompute before the redemption was recorded.
    recompute_family(customer_id)
    # The recompute may have repriced the new subscription once the redemption
    # became visible; persist the final price on the redemption record.
    if red["redeemed_price_cents"] != sub["current_term_price_cents"]:
        red["redeemed_price_cents"] = int(sub["current_term_price_cents"])
    return success_object(S.redemption_view(red), 201)


# --------------------------------------------------------------- offer steps reads

@app.get("/api/v1/offer-steps")
def list_offer_steps():
    require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    items = list(db.offer_steps.values())
    plan_id = request.args.get("plan_id")
    if plan_id:
        items = [s for s in items if s["plan_id"] == plan_id]
    campaign_id = request.args.get("campaign_id")
    if campaign_id:
        items = [s for s in items if s["campaign_id"] == campaign_id]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.offer_step_view(s) for s in page], limit, offset, len(items))


@app.get("/api/v1/offer-steps/<sid>")
def get_offer_step(sid):
    require_roles(["PlatformAdmin", "Customer", "RetentionAgent"])
    e = get_or_404(db.offer_steps, sid)
    return success_object(S.offer_step_view(e))


@app.get("/api/v1/offer-steps/<sid>/redemptions")
def offer_step_redemptions(sid):
    require_roles(["PlatformAdmin", "RetentionAgent"])
    get_or_404(db.offer_steps, sid)
    items = [r for r in db.redemptions.values() if r["offer_step_id"] == sid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.redemption_view(r) for r in page], limit, offset, len(items))


@app.post("/api/v1/subscription-plans")
def create_plan():
    require_roles(["PlatformAdmin"])
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    tier_id = b.get("package_tier_id")
    if not isinstance(tier_id, str):
        raise errors.invalid_request("package_tier_id required")
    tier = db.package_tiers.get(tier_id)
    if tier is None:
        raise errors.reference_not_found("package_tier_id does not resolve")
    service_mode = opt_enum(b, "service_mode", {"IN_VEHICLE", "STREAMING_ONLY", "BUNDLED"})
    is_trial = b.get("is_trial", False)
    if not isinstance(is_trial, bool):
        raise errors.invalid_request("is_trial must be boolean")
    term_kind = opt_enum(b, "term_kind", {"TRIAL", "MONTHLY", "ANNUAL"})
    tld = opt_int(b, "term_length_days")
    if tld <= 0:
        raise errors.invalid_request("term_length_days must be > 0")
    price = opt_int(b, "price_cents")
    if price < 0:
        raise errors.invalid_request("price_cents must be >= 0")
    ard = b.get("auto_renew_default", True)
    if not isinstance(ard, bool):
        raise errors.invalid_request("auto_renew_default must be boolean")
    ensure_unique(db.plans, "code", code, "plan code duplicate")
    e = {"id": new_id(), "code": code, "name": name, "package_tier_id": tier_id,
         "service_mode": service_mode, "is_trial": is_trial, "term_kind": term_kind,
         "term_length_days": tld, "price_cents": price, "auto_renew_default": ard}
    make_common(e)
    db.plans[e["id"]] = e
    return success_object(S.plan_view(e), 201)


@app.get("/api/v1/subscription-plans/<pid>")
def get_plan(pid):
    require_roles(ALL_READ_ROLES)
    e = get_or_404(db.plans, pid)
    return success_object(S.plan_view(e))


@app.get("/api/v1/subscription-plans/<pid>/subscriptions")
def plan_subscriptions(pid):
    require_roles(["PlatformAdmin", "RetentionAgent", "SystemOperator"])
    get_or_404(db.plans, pid)
    items = [s for s in db.subscriptions.values() if s["plan_id"] == pid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([S.subscription_view(s) for s in page], limit, offset, len(items))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
