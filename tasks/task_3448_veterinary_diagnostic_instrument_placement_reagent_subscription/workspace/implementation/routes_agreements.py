"""Placement agreements and commitment periods: draft/approve/activate,
renegotiation loop, OCC-guarded close, and record-payment."""
from flask import Blueprint, request

import db
import ser
import services
import util
from constants import (
    ALLOWED_TERM_MONTHS,
    MIN_MONTHLY_MINIMUM_CENTS,
    MODELS,
    PROGRAM_TYPES,
    RENEGOTIATION_CASELOAD_DELTA_PCT,
    SHORTFALL_BILLING_RATE,
    SHORTFALL_BREACH_THRESHOLD_CENTS,
)
from errors import err

bp = Blueprint("agreements", __name__)


def _load_agreement(aid):
    a = db.agreements.get(aid)
    if a is None:
        raise err("ERR_AGREEMENT_NOT_FOUND", "placement agreement does not exist")
    return a


# ------------------------------------------------------------------ create
@bp.post("/api/placement-agreements")
def create_agreement():
    uid, role = util.auth()
    util.require(role, ["ClinicManager"])
    b = util.body()

    # Tier 3 ownership: body clinic_id must equal X-User-ID.
    clinic_id = b.get("clinic_id")
    if clinic_id is not None and uid != clinic_id:
        raise err("ERR_CLINIC_OWNERSHIP_MISMATCH",
                  "X-User-ID must equal the body clinic_id")

    # Tier 4 existence.
    if clinic_id is None:
        raise err("ERR_INVALID_REQUEST", "clinic_id is required")
    clinic = db.clinics.get(clinic_id)
    if clinic is None:
        raise err("ERR_CLINIC_NOT_FOUND", "clinic_id does not exist")

    # Tier 5 input shape.
    model = b.get("model")
    if model not in MODELS:
        raise err("ERR_INVALID_REQUEST", f"model must be one of {MODELS}")
    program_type = b.get("program_type")
    if program_type not in PROGRAM_TYPES:
        raise err("ERR_INVALID_REQUEST",
                  f"program_type must be one of {PROGRAM_TYPES}")
    term_months = b.get("term_months")
    if not util.is_int(term_months) or term_months not in ALLOWED_TERM_MONTHS:
        raise err("ERR_INVALID_REQUEST",
                  "term_months must be one of {24, 36, 48, 60}")
    try:
        start = util.parse_iso(b.get("start_date"))
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST",
                  "start_date must be a valid ISO 8601 timestamp")

    monthly_min = b.get("monthly_minimum_cents")
    lease_rate = b.get("lease_rate_cents")
    purchase_price = b.get("purchase_price_cents")
    if program_type == "REAGENT_COMMITMENT":
        if not util.is_int(monthly_min) or monthly_min < MIN_MONTHLY_MINIMUM_CENTS:
            raise err("ERR_INVALID_PROGRAM_TERMS",
                      "REAGENT_COMMITMENT requires monthly_minimum_cents >= 50000")
        if lease_rate is not None or purchase_price is not None:
            raise err("ERR_INVALID_PROGRAM_TERMS",
                      "lease_rate_cents / purchase_price_cents must be absent for "
                      "REAGENT_COMMITMENT")
    elif program_type == "LEASE":
        if not util.is_int(lease_rate) or lease_rate < 0:
            raise err("ERR_INVALID_PROGRAM_TERMS",
                      "LEASE requires lease_rate_cents")
        if monthly_min is not None or purchase_price is not None:
            raise err("ERR_INVALID_PROGRAM_TERMS",
                      "monthly_minimum_cents / purchase_price_cents must be absent "
                      "for LEASE")
    else:  # PURCHASE
        if not util.is_int(purchase_price) or purchase_price < 0:
            raise err("ERR_INVALID_PROGRAM_TERMS",
                      "PURCHASE requires purchase_price_cents")
        if monthly_min is not None or lease_rate is not None:
            raise err("ERR_INVALID_PROGRAM_TERMS",
                      "monthly_minimum_cents / lease_rate_cents must be absent for "
                      "PURCHASE")

    # Tier 6 state: clinic must be ACTIVE.
    if clinic["status"] != "ACTIVE":
        raise err("ERR_CLINIC_NOT_ACTIVE",
                  "the clinic must be ACTIVE to draft an agreement")

    a = services.stamp({
        "clinic_id": clinic_id,
        "model": model,
        "program_type": program_type,
        "term_months": term_months,
        "_start": start,
        "_end": util.add_months(start, term_months),
        "monthly_minimum_cents": monthly_min,
        "lease_rate_cents": lease_rate,
        "purchase_price_cents": purchase_price,
        "baseline_caseload_snapshot": None,
        "proposed_minimum_cents": None,
        "cumulative_billed_cents": 0,
        "cumulative_unpaid_billed_cents": 0,
        "service_credit_cents": 0,
        "status": "DRAFT",
    })
    db.agreements[a["id"]] = a
    return util.ok(ser.agreement(a), code=201)


# -------------------------------------------------------------------- read
@bp.get("/api/placement-agreements/<aid>")
def get_agreement(aid):
    util.auth()
    return util.ok(ser.agreement(_load_agreement(aid)))


@bp.get("/api/placement-agreements")
def list_agreements():
    util.auth()
    items = util.sorted_items(db.agreements.values())
    cid = request.args.get("clinic_id")
    if cid is not None:
        items = [a for a in items if a["clinic_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return util.paginate([ser.agreement(a) for a in items])


# ------------------------------------------------------------------ approve
@bp.post("/api/placement-agreements/<aid>/approve")
def approve_agreement(aid):
    _, role = util.auth()
    util.require(role, ["FinanceReviewer"])
    a = _load_agreement(aid)
    if a["status"] != "DRAFT":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "approve requires status DRAFT")
    a["status"] = "APPROVED"
    services.bump(a)
    return util.ok(ser.agreement(a))


# ----------------------------------------------------------------- activate
@bp.post("/api/placement-agreements/<aid>/activate")
def activate_agreement(aid):
    _, role = util.auth()
    util.require(role, ["PlatformAdmin"])
    a = _load_agreement(aid)
    if a["status"] != "APPROVED":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "activate requires status APPROVED")
    clinic = db.clinics.get(a["clinic_id"])
    if clinic is None or clinic["status"] != "ACTIVE":
        raise err("ERR_CLINIC_NOT_ACTIVE",
                  "the owning clinic must be ACTIVE to activate")
    if clinic["caseload_current_tests"] <= 0:
        raise err("ERR_INVALID_REQUEST",
                  "the clinic's caseload_current_tests must be strictly positive")
    # Closed-interval [start_date, end_date] overlap per (clinic_id, model):
    # touching endpoints conflict.
    for o in db.agreements.values():
        if (o["id"] != a["id"] and o["clinic_id"] == a["clinic_id"]
                and o["model"] == a["model"]
                and o["status"] in ("APPROVED", "ACTIVE", "RENEGOTIATION")
                and a["_start"] <= o["_end"] and o["_start"] <= a["_end"]):
            raise err("ERR_PLACEMENT_TERM_OVERLAP",
                      "another agreement for this clinic and model overlaps the "
                      "closed term interval")
    a["status"] = "ACTIVE"
    a["baseline_caseload_snapshot"] = clinic["caseload_current_tests"]
    services.bump(a)
    services.create_periods(a)
    return util.ok(ser.agreement(a))


# --------------------------------------------------- request renegotiation
@bp.post("/api/placement-agreements/<aid>/request-renegotiation")
def request_renegotiation(aid):
    uid, role = util.auth()
    util.require(role, ["ClinicManager"])
    a = _load_agreement(aid)
    if uid != a["clinic_id"]:
        raise err("ERR_CLINIC_OWNERSHIP_MISMATCH",
                  "X-User-ID must equal the agreement's clinic_id")
    if a["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "request-renegotiation requires status ACTIVE")
    clinic = db.clinics.get(a["clinic_id"])
    current = clinic["caseload_current_tests"]
    baseline = a["baseline_caseload_snapshot"]
    delta = abs(util.dec(current) - util.dec(baseline))
    if delta < RENEGOTIATION_CASELOAD_DELTA_PCT * util.dec(baseline):
        raise err("ERR_RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT",
                  "caseload deviation is below 0.30 of the baseline snapshot")
    scaled = util.round_cents(
        util.dec(a["monthly_minimum_cents"] or 0)
        * util.dec(current) / util.dec(baseline))
    a["proposed_minimum_cents"] = max(MIN_MONTHLY_MINIMUM_CENTS, scaled)
    a["status"] = "RENEGOTIATION"
    services.bump(a)
    return util.ok(ser.agreement(a))


# ---------------------------------------------------- resolve renegotiation
@bp.post("/api/placement-agreements/<aid>/resolve-renegotiation")
def resolve_renegotiation(aid):
    _, role = util.auth()
    util.require(role, ["FinanceReviewer"])
    a = _load_agreement(aid)
    b = util.body()

    # Tier 5 input shape.
    accept = b.get("accept")
    if not isinstance(accept, bool):
        raise err("ERR_INVALID_REQUEST", "accept is required and must be boolean")
    expected = b.get("expected_agreement_version")
    if not util.is_int(expected):
        raise err("ERR_INVALID_REQUEST",
                  "expected_agreement_version is required and must be an integer")
    new_minimum = b.get("new_minimum_cents")
    if accept and (not util.is_int(new_minimum)
                   or new_minimum < MIN_MONTHLY_MINIMUM_CENTS):
        raise err("ERR_INVALID_REQUEST",
                  "accept requires new_minimum_cents >= 50000")
    waive_ids = b.get("waive_period_ids", [])
    if waive_ids is None:
        waive_ids = []
    if not isinstance(waive_ids, list):
        raise err("ERR_INVALID_REQUEST", "waive_period_ids must be an array")

    # Tier 6 state.
    if a["status"] != "RENEGOTIATION":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "resolve-renegotiation requires status RENEGOTIATION")

    # Waive-target validity: each id must be a CLOSED, ISSUED period of this
    # agreement.
    waive_targets = []
    for pid in waive_ids:
        p = db.periods.get(pid)
        if (p is None or p["agreement_id"] != a["id"]
                or p["period_status"] != "CLOSED"
                or p["billing_status"] != "ISSUED"):
            raise err("ERR_PERIOD_INVALID_STATE",
                      "every waive_period_ids entry must reference a CLOSED "
                      "CommitmentPeriod of this agreement with billing_status "
                      "ISSUED")
        waive_targets.append(p)

    # Tier 11 OCC: after every other precondition, before mutations.
    if expected != a["version"]:
        raise err("ERR_STALE_AGREEMENT_VERSION",
                  "expected_agreement_version does not match the current version")

    if accept:
        a["monthly_minimum_cents"] = new_minimum
        for p in db.periods.values():
            if p["agreement_id"] == a["id"] and p["period_status"] == "OPEN":
                p["minimum_cents"] = new_minimum
                services.bump(p)
        for p in waive_targets:
            p["billing_status"] = "WAIVED"
            a["cumulative_unpaid_billed_cents"] -= p["billed_cents"]
            services.bump(p)
    a["proposed_minimum_cents"] = None
    a["status"] = "ACTIVE"
    services.bump(a)
    return util.ok(ser.agreement(a))


# ------------------------------------------------------ close-commitment-period
@bp.post("/api/placement-agreements/<aid>/close-commitment-period")
def close_commitment_period(aid):
    _, role = util.auth()
    util.require(role, ["PlatformAdmin"])
    a = _load_agreement(aid)
    b = util.body()

    period_month = b.get("period_month")
    if not isinstance(period_month, str) or not util.MONTH_RE.match(period_month):
        raise err("ERR_INVALID_REQUEST", "period_month must be YYYY-MM")
    expected = b.get("expected_agreement_version")
    if not util.is_int(expected):
        raise err("ERR_INVALID_REQUEST",
                  "expected_agreement_version is required and must be an integer")

    if a["status"] not in ("ACTIVE", "RENEGOTIATION", "BREACHED"):
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "close requires status ACTIVE, RENEGOTIATION or BREACHED")

    months = util.term_months(a["_start"], a["term_months"])
    if period_month not in months:
        raise err("ERR_PERIOD_INVALID_STATE",
                  "period_month is not one of the agreement's term months")
    if period_month >= util.month_of(db.now()):
        raise err("ERR_PERIOD_INVALID_STATE",
                  "period_month must be strictly before the clock's current month")
    target = None
    for p in db.periods.values():
        if p["agreement_id"] == a["id"]:
            if p["period_month"] == period_month:
                target = p
            elif p["period_month"] < period_month and p["period_status"] != "CLOSED":
                raise err("ERR_PERIOD_INVALID_STATE",
                          "earlier term months must be closed first "
                          "(chronological close order)")
    if target is None or target["period_status"] != "OPEN":
        raise err("ERR_PERIOD_INVALID_STATE", "the period is not OPEN")

    if expected != a["version"]:
        raise err("ERR_STALE_AGREEMENT_VERSION",
                  "expected_agreement_version does not match the current version")

    # Final attribution: order-month attribution over FULFILLED orders.
    fulfilled = 0
    for o in db.orders.values():
        if (o["agreement_id"] == a["id"] and o["status"] == "FULFILLED"
                and o["order_month"] == period_month):
            fulfilled += o["final_total_cents"]
    minimum = target["minimum_cents"] or 0
    shortfall = max(0, minimum - fulfilled)
    billed = util.round_cents(util.dec(shortfall) * SHORTFALL_BILLING_RATE)
    target["fulfilled_cents"] = fulfilled
    target["shortfall_cents"] = shortfall
    target["billed_cents"] = billed
    target["period_status"] = "CLOSED"
    if billed > 0:
        target["billing_status"] = "ISSUED"
    services.bump(target)

    a["cumulative_billed_cents"] += billed
    a["cumulative_unpaid_billed_cents"] += billed
    services.bump(a)

    # Breach cascade.
    if (a["cumulative_unpaid_billed_cents"] >= SHORTFALL_BREACH_THRESHOLD_CENTS
            and a["status"] == "ACTIVE"):
        a["status"] = "BREACHED"
        services.bump(a)
        clinic = db.clinics.get(a["clinic_id"])
        if clinic is not None and clinic["status"] == "ACTIVE":
            clinic["status"] = "SUSPENDED"
            services.bump(clinic)
    return util.ok(ser.period(target))


# ------------------------------------------------------------- periods list
@bp.get("/api/placement-agreements/<aid>/commitment-periods")
def list_periods(aid):
    util.auth()
    _load_agreement(aid)
    items = [p for p in db.periods.values() if p["agreement_id"] == aid]
    st = request.args.get("period_status")
    if st is not None:
        items = [p for p in items if p["period_status"] == st]
    items.sort(key=lambda p: (p["period_month"], p["_seq"]))
    return util.paginate([ser.period(p) for p in items])


# ------------------------------------------------------------ record payment
@bp.post("/api/commitment-periods/<pid>/record-payment")
def record_payment(pid):
    _, role = util.auth()
    util.require(role, ["FinanceReviewer"])
    p = db.periods.get(pid)
    if p is None:
        raise err("ERR_PERIOD_NOT_FOUND", "commitment period does not exist")
    b = util.body()
    amount = b.get("amount_cents")
    if not util.is_int(amount):
        raise err("ERR_INVALID_REQUEST",
                  "amount_cents is required and must be an integer")
    if p["billing_status"] != "ISSUED":
        raise err("ERR_PERIOD_INVALID_STATE",
                  "record-payment requires billing_status ISSUED")
    if amount != p["billed_cents"]:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH",
                  "amount_cents must equal billed_cents exactly")

    p["billing_status"] = "PAID"
    services.bump(p)
    a = db.agreements.get(p["agreement_id"])
    a["cumulative_unpaid_billed_cents"] -= amount
    services.bump(a)

    # Recovery cascade from BREACHED.
    if (a["status"] == "BREACHED"
            and a["cumulative_unpaid_billed_cents"] < SHORTFALL_BREACH_THRESHOLD_CENTS):
        a["status"] = "ACTIVE" if db.now() <= a["_end"] else "COMPLETED"
        services.bump(a)
    return util.ok(ser.period(p))
