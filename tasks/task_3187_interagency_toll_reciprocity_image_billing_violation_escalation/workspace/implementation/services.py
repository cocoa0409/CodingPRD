"""Shared domain services: serialization, fare math, cascades, sweeps."""

import uuid
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import ApiError, ERR_NOT_FOUND
from response import iso3


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def round_half_up_cents(value):
    """value may be int/Decimal/float-compatible; returns int cents."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def stamp_new(entity, with_version=True):
    now = iso3(store.current_dt_wall())
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1


def touch(entity):
    entity["updated_at"] = iso3(store.current_dt_wall())
    entity["version"] = entity.get("version", 1) + 1


def get_or_404(mapping, rid, what="resource"):
    obj = mapping.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, f"{what} not found: {rid}", 404)
    return obj


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def agency_view(a):
    return {k: a[k] for k in (
        "id", "agency_code", "name", "home_state", "reciprocity_fee_bps",
        "settlement_currency", "status", "created_at", "updated_at", "version")}


def rate_schedule_view(r):
    return {k: r[k] for k in (
        "id", "agency_id", "plaza_code", "vehicle_class", "base_rate_cents",
        "axle_multiplier", "peak_multiplier", "image_fee_cents",
        "effective_from", "effective_to", "status",
        "created_at", "updated_at", "version")}


def discount_plan_view(p):
    return {k: p[k] for k in (
        "id", "agency_id", "plan_code", "discount_pct",
        "daily_discount_cap_cents", "applies_to_agency_codes",
        "min_trips_per_month", "status",
        "created_at", "updated_at", "version")}


def account_view(a):
    return {k: a[k] for k in (
        "id", "home_agency_id", "holder_name", "holder_email",
        "discount_plan_id", "balance_cents", "low_balance_threshold_cents",
        "replenishment_amount_cents", "replenishment_fail_count",
        "discount_used_today_cents", "trips_this_month", "status",
        "suspended_reason", "created_at", "updated_at", "version")}


def transponder_view(t):
    return {k: t[k] for k in (
        "id", "account_id", "tag_number", "vehicle_class", "plate_number",
        "plate_state", "status", "created_at", "updated_at", "version")}


def transaction_view(t):
    return {k: t[k] for k in (
        "id", "account_id", "transponder_id", "away_agency_id",
        "rate_schedule_id", "plaza_code", "trip_timestamp", "is_peak",
        "billed_vehicle_class", "detection_method", "gross_amount_cents",
        "discount_amount_cents", "charged_amount_cents", "status",
        "settlement_file_id", "idempotency_key", "created_at")}


def image_bill_view(b):
    return {k: b[k] for k in (
        "id", "account_id", "plate_number", "plate_state",
        "toll_transaction_id", "lookup_agency_id", "billed_amount_cents",
        "misread_flag", "status", "created_at", "updated_at", "version")}


def violation_view(v):
    return {k: v[k] for k in (
        "id", "account_id", "plate_number", "plate_state",
        "toll_transaction_id", "image_bill_id", "toll_amount_cents",
        "notice_count", "admin_fees_cents", "total_outstanding_cents",
        "first_notice_day", "current_notice_day",
        "registration_hold_referred", "status",
        "created_at", "updated_at", "version")}


def dispute_view(d):
    return {k: d[k] for k in (
        "id", "account_id", "dispute_type", "toll_transaction_id",
        "image_bill_id", "violation_id", "claimed_vehicle_class",
        "claimed_plate_number", "rental_agreement_ref", "filed_day",
        "status", "created_at", "updated_at", "version")}


def settlement_file_view(f):
    return {k: f[k] for k in (
        "id", "from_agency_id", "to_agency_id", "settlement_day",
        "line_count", "gross_amount_cents", "fee_amount_cents",
        "net_amount_cents", "exception_count", "status",
        "created_at", "updated_at", "version")}


def agreement_view(g):
    return {k: g[k] for k in (
        "id", "requesting_agency_id", "providing_agency_id",
        "effective_from", "effective_to", "covers_states",
        "per_lookup_fee_cents", "status",
        "created_at", "updated_at", "version")}


# ---------------------------------------------------------------------------
# business logic
# ---------------------------------------------------------------------------

def find_active_rate_schedule(agency_id, plaza_code, vehicle_class, trip_dt):
    """Locate ACTIVE schedule whose half-open window contains trip_dt."""
    for r in store.rate_schedules.values():
        if r["agency_id"] != agency_id:
            continue
        if r["status"] != "ACTIVE":
            continue
        if r["plaza_code"] != plaza_code:
            continue
        if r["vehicle_class"] != vehicle_class:
            continue
        ef = r["_ef_dt"]
        et = r["_et_dt"]
        if ef <= trip_dt < et:
            return r
    return None


def find_transponder_by_tag(tag_number):
    for t in store.transponders.values():
        if t["tag_number"] == tag_number:
            return t
    return None


def compute_fare(rate, is_peak, detection_method, account, away_agency):
    """Returns (gross_amount_cents, discount_amount_cents, charged_amount_cents)."""
    axle_component = round_half_up_cents(
        Decimal(str(rate["base_rate_cents"])) * Decimal(str(rate["axle_multiplier"])))
    if is_peak:
        gross_no_fee = round_half_up_cents(
            Decimal(axle_component) * Decimal(str(rate["peak_multiplier"])))
    else:
        gross_no_fee = axle_component

    if detection_method == "TRANSPONDER":
        discount = 0
        plan = store.discount_plans.get(account["discount_plan_id"])
        if plan is not None and plan["status"] == "ACTIVE" and away_agency is not None:
            applies = plan["applies_to_agency_codes"]
            if len(applies) == 0:
                plan_applies = away_agency["id"] == account["home_agency_id"]
            else:
                plan_applies = away_agency["agency_code"] in applies
            eligible = plan_applies and (
                plan["min_trips_per_month"] == 0
                or account["trips_this_month"] >= plan["min_trips_per_month"])
            if eligible:
                raw_discount = round_half_up_cents(
                    Decimal(gross_no_fee) * Decimal(str(plan["discount_pct"])))
                cap = plan["daily_discount_cap_cents"]
                if cap > 0:
                    remaining = max(0, cap - account["discount_used_today_cents"])
                    discount = min(raw_discount, remaining)
                else:
                    discount = raw_discount
        gross = gross_no_fee
    else:  # IMAGE
        discount = 0
        gross = gross_no_fee + rate["image_fee_cents"]

    charged = gross - discount
    return gross, discount, charged


def debit_account(account, amount_cents):
    """Debit balance, bump version, run replenishment decision."""
    account["balance_cents"] -= amount_cents
    touch(account)
    replenishment_decision(account)


def credit_account(account, amount_cents):
    account["balance_cents"] += amount_cents
    touch(account)


def replenishment_decision(account):
    if account["status"] == "ACTIVE" and \
            account["balance_cents"] < account["low_balance_threshold_cents"]:
        # automatic replenishment always succeeds in this system
        account["balance_cents"] += account["replenishment_amount_cents"]
        account["replenishment_fail_count"] = 0


def suspend_account(account, reason):
    account["status"] = "SUSPENDED"
    account["suspended_reason"] = reason
    touch(account)


def create_violation(account_id, plate_number, plate_state,
                     toll_transaction_id, image_bill_id, toll_amount_cents):
    v = {
        "id": new_id(),
        "account_id": account_id,
        "plate_number": plate_number,
        "plate_state": plate_state,
        "toll_transaction_id": toll_transaction_id,
        "image_bill_id": image_bill_id,
        "toll_amount_cents": toll_amount_cents,
        "notice_count": 0,
        "admin_fees_cents": 0,
        "total_outstanding_cents": toll_amount_cents,
        "first_notice_day": None,
        "current_notice_day": None,
        "registration_hold_referred": False,
        "status": "OPEN",
    }
    stamp_new(v)
    v["_seq"] = store.next_seq()
    store.violations[v["id"]] = v
    return v


def escalate_to_hold_referred(v):
    v["status"] = "HOLD_REFERRED"
    v["registration_hold_referred"] = True
    touch(v)
    if v["account_id"]:
        account = store.accounts.get(v["account_id"])
        if account is not None and account["status"] == "ACTIVE" \
                and v["total_outstanding_cents"] > 0:
            suspend_account(account, "VIOLATION_ESCALATION")


def run_advance_day_sweeps(month_rolled):
    """Sweeps run on advance_day: agreement expiry, violation escalation,
    dispute auto-reject, counter resets."""
    now = store.current_dt

    # PlateDataAgreement expiry
    for g in store.plate_data_agreements.values():
        if g["status"] == "ACTIVE" and now >= g["_et_dt"]:
            g["status"] = "EXPIRED"
            touch(g)

    # Violation escalation sweep
    for v in store.violations.values():
        if v["status"] == "NOTICED" and v["notice_count"] == 3 \
                and v["first_notice_day"] is not None \
                and store.epoch_day >= v["first_notice_day"] + 60:
            if v["total_outstanding_cents"] >= 10000:
                escalate_to_hold_referred(v)
            else:
                v["status"] = "ESCALATED"
                touch(v)
        elif v["status"] == "ESCALATED" \
                and v["total_outstanding_cents"] >= 10000:
            escalate_to_hold_referred(v)

    # Dispute auto-reject at 30 days unreviewed
    for d in store.disputes.values():
        if d["status"] == "FILED" and store.epoch_day >= d["filed_day"] + 30:
            d["status"] = "REJECTED"
            touch(d)
            if d["dispute_type"] == "VEHICLE_CLASSIFICATION" \
                    and d.get("toll_transaction_id"):
                txn = store.toll_transactions.get(d["toll_transaction_id"])
                if txn is not None and txn["status"] == "DISPUTED":
                    txn["status"] = "POSTED"

    # Counter resets
    for a in store.accounts.values():
        a["discount_used_today_cents"] = 0
        if month_rolled:
            a["trips_this_month"] = 0
