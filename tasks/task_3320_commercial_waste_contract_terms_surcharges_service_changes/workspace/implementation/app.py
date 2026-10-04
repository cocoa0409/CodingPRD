import os
from datetime import timedelta

from flask import Flask

from util import (
    ApiError, err, guarded, success, error_response, get_body, req_field,
    as_str, as_int, as_num, as_bool, as_enum, as_dt, as_date, paginate,
    D, rhu, dfloor, dceil, fmt_ts, months_ceil,
)
import db
from db import (
    Rec, now, set_clock, run_sweeps, active_config_at, fuel_pct,
    recompute_contract_base, recompute_customer_balance, write_ledger,
    ser_customer, ser_contract, ser_line, ser_pickup, ser_surcharge,
    ser_notice, ser_service_change, ser_offer, ser_cancellation, ser_credit,
    ser_rolloff, ser_ledger,
    CREDIT_FILING_WINDOW_DAYS, DISPUTE_WINDOW_DAYS,
    ROFR_UNDERCUT_CENTS,
)

app = Flask(__name__)

ADMIN = ["PlatformAdmin"]
OPS = ["OpsManager"]
CUST = ["Customer"]
HAULER = ["HaulerAgent"]
ALL_READ = ["PlatformAdmin", "OpsManager", "Customer"]
ALL_READ_H = ["PlatformAdmin", "OpsManager", "Customer", "HaulerAgent"]

CONTAINER_SIZES = {"CY_2", "CY_4", "CY_6", "CY_8"}
ROLLOFF_SIZES = {"YD_10", "YD_20", "YD_30", "YD_40"}
OUTCOMES = {"COMPLETED", "MISSED", "CONTAMINATED", "OVERWEIGHT", "CONTAMINATED_OVERWEIGHT"}
FEE_OUTCOMES = {"CONTAMINATED", "OVERWEIGHT", "CONTAMINATED_OVERWEIGHT"}
REASONS = {"CPI", "FUEL_INDEX", "COST_RECOVERY"}


@app.errorhandler(ApiError)
def _api_err(e):
    return error_response(e)


@app.errorhandler(404)
def _nf(e):
    return error_response(err("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(405)
def _mnf(e):
    return error_response(err("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(Exception)
def _gen(e):
    return error_response(err("ERR_INVALID_REQUEST", 400, str(e)))


def _get(store, rid):
    obj = store.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", 404, "Referenced resource does not exist.")
    return obj


def _touch_children(cascade_fn):
    pass


# ---------------- logical clock ----------------

@app.post("/api/_clock/set_current_utc")
@guarded(ADMIN)
def set_clock_ep():
    body = get_body()
    to = as_dt(req_field(body, "to_iso8601"), "to_iso8601")
    set_clock(to)
    run_sweeps()
    return success({})


# ---------------- customers ----------------

@app.post("/api/customers")
@guarded(ADMIN)
def create_customer():
    body = get_body()
    legal = as_str(req_field(body, "legal_name"), "legal_name")
    email = as_str(req_field(body, "billing_email"), "billing_email")
    c = Rec(legal_name=legal, billing_email=email, credit_balance_cents=0)
    db.customers[c.id] = c
    return success(ser_customer(c), code=201)


@app.get("/api/customers")
@guarded(["PlatformAdmin", "OpsManager"])
def list_customers():
    items = sorted(db.customers.values(), key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_customer(c) for c in page], response_type="array", page_meta=meta)


@app.get("/api/customers/<cid>")
@guarded(["PlatformAdmin", "OpsManager"])
def get_customer(cid):
    return success(ser_customer(_get(db.customers, cid)))


# ---------------- contracts ----------------

@app.post("/api/contracts")
@guarded(OPS)
def create_contract():
    body = get_body()
    cust = _get(db.customers, as_str(req_field(body, "customer_id"), "customer_id"))
    start = as_dt(req_field(body, "start_date"), "start_date")
    term = as_int(req_field(body, "term_months"), "term_months")
    if term < 1:
        raise err("ERR_INVALID_REQUEST", 400, "term_months must be >= 1.")
    renewal = 12
    if "renewal_term_months" in body and body["renewal_term_months"] is not None:
        renewal = as_int(body["renewal_term_months"], "renewal_term_months")
        if renewal < 1:
            raise err("ERR_INVALID_REQUEST", 400, "renewal_term_months must be >= 1.")
    notice_days = 60
    if "cancellation_notice_days" in body and body["cancellation_notice_days"] is not None:
        notice_days = as_int(body["cancellation_notice_days"], "cancellation_notice_days")
        if notice_days < 0:
            raise err("ERR_INVALID_REQUEST", 400, "cancellation_notice_days must be >= 0.")
    rofr = False
    if "rofr_enabled" in body and body["rofr_enabled"] is not None:
        rofr = as_bool(body["rofr_enabled"], "rofr_enabled")
    window = 15
    if "rofr_window_days" in body and body["rofr_window_days"] is not None:
        window = as_int(body["rofr_window_days"], "rofr_window_days")
        if window < 0:
            raise err("ERR_INVALID_REQUEST", 400, "rofr_window_days must be >= 0.")
    from util import add_months
    c = Rec(customer_id=cust.id, start_date=start, term_months=term,
            end_date=add_months(start, term),
            renewal_term_months=renewal, cancellation_notice_days=notice_days,
            rofr_enabled=rofr, rofr_window_days=window,
            status="DRAFT", current_term_index=1, base_monthly_total_cents=0)
    db.contracts[c.id] = c
    return success(ser_contract(c), code=201)


@app.get("/api/contracts")
@guarded(ALL_READ)
def list_contracts():
    items = list(db.contracts.values())
    cid = request_args("customer_id")
    if cid is not None:
        items = [c for c in items if c.customer_id == cid]
    st = request_args("status")
    if st is not None:
        items = [c for c in items if c.status == st]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_contract(c) for c in page], response_type="array", page_meta=meta)


def request_args(name):
    from flask import request
    return request.args.get(name)


@app.get("/api/contracts/<cid>")
@guarded(ALL_READ)
def get_contract(cid):
    return success(ser_contract(_get(db.contracts, cid)))


@app.post("/api/contracts/<cid>/activate")
@guarded(OPS)
def activate_contract(cid):
    c = _get(db.contracts, cid)
    if c.status != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Contract is not in DRAFT status.")
    has_line = any(l.contract_id == c.id for l in db.lines.values())
    if not has_line or c.start_date > now():
        raise err("ERR_INVALID_STATE", 409,
                  "Activation requires at least one service line and start_date <= now.")
    c.status = "ACTIVE"
    c.touch()
    return success(ser_contract(c))


@app.post("/api/contracts/<cid>/reinstate")
@guarded(OPS)
def reinstate_contract(cid):
    c = _get(db.contracts, cid)
    if c.status != "TERMINATED":
        raise err("ERR_INVALID_STATE", 409, "Contract is not in TERMINATED status.")
    if not (now() < c.end_date):
        raise err("ERR_INVALID_STATE", 409, "Reinstatement requires now < end_date.")
    c.status = "ACTIVE"
    c.touch()
    return success(ser_contract(c))


@app.post("/api/contracts/<cid>/service-lines")
@guarded(OPS)
def add_service_line(cid):
    c = _get(db.contracts, cid)
    body = get_body()
    size = as_enum(req_field(body, "container_size"), "container_size", CONTAINER_SIZES)
    freq = as_int(req_field(body, "frequency_per_week"), "frequency_per_week")
    if freq < 1 or freq > 6:
        raise err("ERR_INVALID_REQUEST", 400, "frequency_per_week must be in 1..6.")
    rate = as_int(req_field(body, "base_rate_cents"), "base_rate_cents")
    if rate < 0:
        raise err("ERR_INVALID_REQUEST", 400, "base_rate_cents must be >= 0.")
    if c.status not in ("DRAFT", "ACTIVE"):
        raise err("ERR_INVALID_STATE", 409,
                  "Service lines can only be added to DRAFT or ACTIVE contracts.")
    l = Rec(contract_id=c.id, container_size=size, frequency_per_week=freq,
            base_rate_cents=rate)
    db.lines[l.id] = l
    recompute_contract_base(c)
    c.touch()
    return success(ser_line(l), code=201)


@app.get("/api/contracts/<cid>/service-lines")
@guarded(ALL_READ)
def list_service_lines(cid):
    _get(db.contracts, cid)
    items = sorted((l for l in db.lines.values() if l.contract_id == cid),
                   key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_line(l) for l in page], response_type="array", page_meta=meta)


@app.get("/api/service-lines/<lid>")
@guarded(ALL_READ)
def get_service_line(lid):
    return success(ser_line(_get(db.lines, lid)))


# ---------------- monthly invoice ----------------

@app.get("/api/contracts/<cid>/monthly-invoice")
@guarded(ALL_READ)
def monthly_invoice(cid):
    c = _get(db.contracts, cid)
    B = c.base_monthly_total_cents
    cfg = active_config_at(now())
    if cfg is not None:
        fuel_c = rhu(D(B) * fuel_pct(cfg))
        env_c = rhu(D(B) * D(cfg.environmental_pct))
        admin_c = rhu(D(B) * D(cfg.admin_pct))
    else:
        fuel_c = env_c = admin_c = 0
    line_ids = {l.id for l in db.lines.values() if l.contract_id == c.id}
    t = now()
    lo = (t - timedelta(days=30)).date()
    hi = t.date()
    fees = 0
    for e in db.pickup_events.values():
        if e.service_line_id in line_ids:
            try:
                from util import parse_dt
                d = parse_dt(e.occurred_date).date()
            except Exception:
                continue
            if lo <= d <= hi:
                fees += e.contamination_fee_cents + e.overweight_fee_cents
    credits = sum(cr.credit_cents for cr in db.service_credits.values()
                  if cr.status == "ACTIVE" and cr.service_line_id in line_ids)
    total = B + fuel_c + env_c + admin_c + fees - credits
    return success({
        "base_cents": B,
        "fuel_cents": fuel_c,
        "env_cents": env_c,
        "admin_cents": admin_c,
        "fees_cents": fees,
        "credits_cents": credits,
        "total_cents": total,
    })


# ---------------- ledger entries ----------------

@app.get("/api/contracts/<cid>/ledger-entries")
@guarded(ALL_READ)
def list_contract_ledger(cid):
    _get(db.contracts, cid)
    items = sorted((e for e in db.ledger_entries.values() if e.contract_id == cid),
                   key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_ledger(e) for e in page], response_type="array", page_meta=meta)


@app.get("/api/ledger-entries")
@guarded(ALL_READ)
def list_ledger():
    items = list(db.ledger_entries.values())
    cid = request_args("contract_id")
    if cid is not None:
        items = [e for e in items if e.contract_id == cid]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_ledger(e) for e in page], response_type="array", page_meta=meta)


# ---------------- pickup events ----------------

@app.post("/api/pickup-events")
@guarded(HAULER)
def create_pickup_event():
    body = get_body()
    line = _get(db.lines, as_str(req_field(body, "service_line_id"), "service_line_id"))
    occ = req_field(body, "occurred_date")
    if not isinstance(occ, str):
        raise err("ERR_INVALID_REQUEST", 400, "occurred_date must be a YYYY-MM-DD date string.")
    try:
        from datetime import datetime as _dt
        _dt.strptime(occ, "%Y-%m-%d")
    except Exception:
        raise err("ERR_INVALID_REQUEST", 400, "occurred_date must be a YYYY-MM-DD date string.")
    outcome = as_enum(req_field(body, "outcome"), "outcome", OUTCOMES)
    photo = body.get("photo_evidence_url")
    if photo is not None and not isinstance(photo, str):
        raise err("ERR_INVALID_REQUEST", 400, "photo_evidence_url must be a string.")
    if outcome in FEE_OUTCOMES and not photo:
        raise err("ERR_INVALID_REQUEST", 400,
                  "photo_evidence_url is required for contamination/overweight outcomes.")
    from util import parse_dt
    cfg = active_config_at(parse_dt(occ))
    cont_fee = 0
    over_fee = 0
    if cfg is not None:
        if outcome in ("CONTAMINATED", "CONTAMINATED_OVERWEIGHT"):
            cont_fee = cfg.contamination_fee_cents
        if outcome in ("OVERWEIGHT", "CONTAMINATED_OVERWEIGHT"):
            over_fee = cfg.overweight_fee_cents
    e = Rec(service_line_id=line.id, occurred_date=occ, outcome=outcome,
            photo_evidence_url=photo, contamination_fee_cents=cont_fee,
            overweight_fee_cents=over_fee, dispute_status="NONE", appeal_count=0)
    db.pickup_events[e.id] = e
    return success(ser_pickup(e), code=201)


@app.get("/api/pickup-events")
@guarded(ALL_READ_H)
def list_pickup_events():
    items = list(db.pickup_events.values())
    sl = request_args("service_line_id")
    if sl is not None:
        items = [e for e in items if e.service_line_id == sl]
    oc = request_args("outcome")
    if oc is not None:
        items = [e for e in items if e.outcome == oc]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_pickup(e) for e in page], response_type="array", page_meta=meta)


@app.get("/api/pickup-events/<eid>")
@guarded(ALL_READ_H)
def get_pickup_event(eid):
    return success(ser_pickup(_get(db.pickup_events, eid)))


@app.post("/api/pickup-events/<eid>/dispute")
@guarded(CUST)
def dispute_pickup(eid):
    e = _get(db.pickup_events, eid)
    if e.dispute_status == "NONE":
        if e.outcome not in FEE_OUTCOMES:
            raise err("ERR_INVALID_STATE", 409,
                      "Only contaminated/overweight events may be disputed.")
        from util import parse_dt
        if now() > parse_dt(e.occurred_date) + timedelta(days=DISPUTE_WINDOW_DAYS):
            raise err("ERR_WINDOW_EXPIRED", 422,
                      "Dispute must be filed within 30 days of occurred_date.")
        e.dispute_status = "DISPUTED"
    elif e.dispute_status == "RESOLVED_UPHELD":
        if e.appeal_count != 0:
            raise err("ERR_INVALID_STATE", 409,
                      "No further disputes are possible for this event.")
        e.dispute_status = "DISPUTED"
        e.appeal_count = 1
    else:
        raise err("ERR_INVALID_STATE", 409,
                  "Event cannot be disputed from its current state.")
    e.touch()
    return success(ser_pickup(e))


@app.post("/api/pickup-events/<eid>/resolve-dispute")
@guarded(OPS)
def resolve_dispute(eid):
    e = _get(db.pickup_events, eid)
    body = get_body()
    resolution = as_enum(req_field(body, "resolution"), "resolution", {"UPHELD", "CREDITED"})
    if e.dispute_status != "DISPUTED":
        raise err("ERR_INVALID_STATE", 409, "Event is not in DISPUTED status.")
    if resolution == "UPHELD":
        e.dispute_status = "RESOLVED_UPHELD"
    else:
        e.dispute_status = "RESOLVED_CREDITED"
        for cr in db.service_credits.values():
            if cr.pickup_event_id == e.id and cr.status == "ACTIVE":
                cr.status = "CANCELLED"
                cr.touch()
                line = db.lines.get(cr.service_line_id)
                if line is not None:
                    contract = db.contracts.get(line.contract_id)
                    if contract is not None:
                        cust = db.customers.get(contract.customer_id)
                        if cust is not None:
                            recompute_customer_balance(cust)
    e.touch()
    return success(ser_pickup(e))


# ---------------- surcharge configs ----------------

@app.post("/api/surcharge-configs")
@guarded(ADMIN)
def create_surcharge_config():
    body = get_body()
    mode = as_enum(req_field(body, "fuel_mode"), "fuel_mode", {"FIXED", "INDEXED"})
    env_pct = as_num(req_field(body, "environmental_pct"), "environmental_pct")
    admin_pct = as_num(req_field(body, "admin_pct"), "admin_pct")
    cont_fee = as_int(req_field(body, "contamination_fee_cents"), "contamination_fee_cents")
    over_fee = as_int(req_field(body, "overweight_fee_cents"), "overweight_fee_cents")
    eff = as_dt(req_field(body, "effective_from"), "effective_from")
    fuel_fixed = body.get("fuel_fixed_pct")
    idx_base = body.get("fuel_index_base")
    idx_cur = body.get("fuel_index_current")
    if mode == "FIXED":
        if fuel_fixed is None:
            raise err("ERR_INVALID_REQUEST", 400, "fuel_fixed_pct is required for FIXED mode.")
        fuel_fixed = as_num(fuel_fixed, "fuel_fixed_pct")
    else:
        if idx_base is None or idx_cur is None:
            raise err("ERR_INVALID_REQUEST", 400,
                      "fuel_index_base and fuel_index_current are required for INDEXED mode.")
        idx_base = as_num(idx_base, "fuel_index_base")
        idx_cur = as_num(idx_cur, "fuel_index_current")
        if idx_base == 0:
            raise err("ERR_INVALID_REQUEST", 400, "fuel_index_base must be non-zero.")
    if any(s.effective_from == eff for s in db.surcharge_configs.values()):
        raise err("ERR_DUPLICATE_PENDING", 409,
                  "A surcharge configuration already exists with this effective_from.")
    credit_pct = body.get("credit_pct_of_base")
    if credit_pct is not None:
        credit_pct = as_num(credit_pct, "credit_pct_of_base")
    s = Rec(fuel_mode=mode, fuel_fixed_pct=fuel_fixed, fuel_index_base=idx_base,
            fuel_index_current=idx_cur, environmental_pct=env_pct, admin_pct=admin_pct,
            contamination_fee_cents=cont_fee, overweight_fee_cents=over_fee,
            credit_pct_of_base=credit_pct,
            effective_from=eff)
    db.surcharge_configs[s.id] = s
    return success(ser_surcharge(s), code=201)


@app.get("/api/surcharge-configs")
@guarded(["PlatformAdmin", "OpsManager"])
def list_surcharge_configs():
    items = sorted(db.surcharge_configs.values(),
                   key=lambda x: (x.effective_from, x._seq))
    page, meta = paginate(items)
    return success([ser_surcharge(s) for s in page], response_type="array", page_meta=meta)


# ---------------- rate adjustment notices ----------------

@app.post("/api/rate-notices")
@guarded(OPS)
def create_rate_notice():
    body = get_body()
    c = _get(db.contracts, as_str(req_field(body, "contract_id"), "contract_id"))
    reason = as_enum(req_field(body, "reason"), "reason", REASONS)
    pct = as_num(req_field(body, "pct_increase"), "pct_increase")
    eff = as_dt(req_field(body, "effective_date"), "effective_date")
    if not (eff > now()):
        raise err("ERR_WINDOW_EXPIRED", 422, "effective_date must be strictly after now.")
    if not (pct > 0):
        raise err("ERR_INVALID_AMOUNT", 422, "pct_increase must be greater than 0.")
    n = Rec(contract_id=c.id, reason=reason, pct_increase=pct, effective_date=eff,
            status="SCHEDULED")
    db.rate_notices[n.id] = n
    return success(ser_notice(n), code=201)


@app.get("/api/rate-notices")
@guarded(ALL_READ)
def list_rate_notices():
    items = list(db.rate_notices.values())
    cid = request_args("contract_id")
    if cid is not None:
        items = [n for n in items if n.contract_id == cid]
    st = request_args("status")
    if st is not None:
        items = [n for n in items if n.status == st]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_notice(n) for n in page], response_type="array", page_meta=meta)


@app.get("/api/rate-notices/<nid>")
@guarded(ALL_READ)
def get_rate_notice(nid):
    return success(ser_notice(_get(db.rate_notices, nid)))


@app.post("/api/rate-notices/<nid>/cancel")
@guarded(OPS)
def cancel_rate_notice(nid):
    n = _get(db.rate_notices, nid)
    if n.status != "SCHEDULED":
        raise err("ERR_INVALID_STATE", 409, "Notice is not in SCHEDULED status.")
    if not (now() < n.effective_date):
        raise err("ERR_WINDOW_EXPIRED", 422,
                  "A notice can only be cancelled before its effective_date.")
    n.status = "CANCELLED"
    n.touch()
    return success(ser_notice(n))


# ---------------- service change requests ----------------

def quote_rate(base_rate, cur_freq, new_freq):
    weekly = D(base_rate) / D(cur_freq)
    if new_freq > cur_freq:
        return rhu(weekly * D(new_freq) * D("1.10"))
    return rhu(weekly * D(new_freq) * D("0.95"))


@app.post("/api/service-change-requests")
@guarded(CUST)
def create_service_change():
    body = get_body()
    line = _get(db.lines, as_str(req_field(body, "service_line_id"), "service_line_id"))
    size = as_enum(req_field(body, "new_container_size"), "new_container_size", CONTAINER_SIZES)
    freq = as_int(req_field(body, "new_frequency_per_week"), "new_frequency_per_week")
    if freq < 1 or freq > 6:
        raise err("ERR_INVALID_REQUEST", 400, "new_frequency_per_week must be in 1..6.")
    eff = as_dt(req_field(body, "effective_date"), "effective_date")
    if not (eff > now()):
        raise err("ERR_WINDOW_EXPIRED", 422, "effective_date must be strictly after now.")
    quoted = quote_rate(line.base_rate_cents, line.frequency_per_week, freq)
    r = Rec(service_line_id=line.id, new_container_size=size,
            new_frequency_per_week=freq, effective_date=eff,
            old_rate_cents=line.base_rate_cents,
            quoted_new_rate_cents=quoted, final_applied_rate_cents=None,
            status="PENDING")
    db.service_changes[r.id] = r
    return success(ser_service_change(r), code=201)


@app.get("/api/service-change-requests")
@guarded(ALL_READ)
def list_service_changes():
    items = list(db.service_changes.values())
    sl = request_args("service_line_id")
    if sl is not None:
        items = [r for r in items if r.service_line_id == sl]
    st = request_args("status")
    if st is not None:
        items = [r for r in items if r.status == st]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_service_change(r) for r in page], response_type="array", page_meta=meta)


@app.get("/api/service-change-requests/<rid>")
@guarded(ALL_READ)
def get_service_change(rid):
    return success(ser_service_change(_get(db.service_changes, rid)))


@app.post("/api/service-changes/<rid>/approve")
@guarded(OPS)
def approve_service_change(rid):
    r = _get(db.service_changes, rid)
    line = _get(db.lines, r.service_line_id)
    contract = _get(db.contracts, line.contract_id)
    if r.status != "PENDING":
        raise err("ERR_INVALID_STATE", 409, "Request is not in PENDING status.")
    if contract.status != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409,
                  "Approval requires the owning contract to be ACTIVE.")
    for other in db.service_changes.values():
        if (other.id != r.id and other.service_line_id == r.service_line_id
                and other.status == "APPROVED"):
            raise err("ERR_DUPLICATE_PENDING", 409,
                      "An APPROVED service change already exists on this line.")
    r.status = "APPROVED"
    r.touch()
    return success(ser_service_change(r))


@app.post("/api/service-changes/<rid>/reject")
@guarded(OPS)
def reject_service_change(rid):
    r = _get(db.service_changes, rid)
    if r.status != "PENDING":
        raise err("ERR_INVALID_STATE", 409, "Request is not in PENDING status.")
    r.status = "REJECTED"
    r.touch()
    return success(ser_service_change(r))


@app.post("/api/service-changes/<rid>/apply")
@guarded(OPS)
def apply_service_change(rid):
    r = _get(db.service_changes, rid)
    line = _get(db.lines, r.service_line_id)
    contract = _get(db.contracts, line.contract_id)
    body = get_body()
    exp = as_int(req_field(body, "expected_contract_version"), "expected_contract_version")
    if r.status != "APPROVED":
        raise err("ERR_INVALID_STATE", 409, "Request is not in APPROVED status.")
    if not (now() >= r.effective_date):
        raise err("ERR_INVALID_STATE", 409,
                  "The change cannot be applied before its effective_date.")
    if exp != contract.version:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_contract_version does not match the contract's current version.")
    final_rate = quote_rate(line.base_rate_cents, line.frequency_per_week,
                            r.new_frequency_per_week)
    old_base = contract.base_monthly_total_cents
    line.base_rate_cents = final_rate
    line.container_size = r.new_container_size
    line.frequency_per_week = r.new_frequency_per_week
    line.touch()
    new_base = recompute_contract_base(contract)
    write_ledger(contract.id, r.effective_date, old_base, new_base, "SERVICE_CHANGE")
    contract.touch()
    r.final_applied_rate_cents = final_rate
    r.status = "APPLIED"
    r.touch()
    return success(ser_service_change(r))


@app.post("/api/service-changes/<rid>/withdraw")
@guarded(CUST)
def withdraw_service_change(rid):
    r = _get(db.service_changes, rid)
    if r.status != "PENDING":
        raise err("ERR_INVALID_STATE", 409, "Request is not in PENDING status.")
    r.status = "CANCELLED"
    r.touch()
    return success(ser_service_change(r))


# ---------------- competing offers ----------------

@app.post("/api/competing-offers")
@guarded(CUST)
def create_competing_offer():
    body = get_body()
    c = _get(db.contracts, as_str(req_field(body, "contract_id"), "contract_id"))
    amt = as_int(req_field(body, "competitor_monthly_cents"), "competitor_monthly_cents")
    ev = as_str(req_field(body, "evidence_doc_url"), "evidence_doc_url")
    if any(o.contract_id == c.id and o.status == "SUBMITTED"
           for o in db.competing_offers.values()):
        raise err("ERR_DUPLICATE_PENDING", 409,
                  "A SUBMITTED competing offer already exists on this contract.")
    if not c.rofr_enabled:
        raise err("ERR_ROFR_NOT_ENABLED", 422,
                  "This contract does not carry a right-of-first-refusal clause.")
    if not (amt > 0):
        raise err("ERR_INVALID_AMOUNT", 422,
                  "competitor_monthly_cents must be greater than 0.")
    o = Rec(contract_id=c.id, competitor_monthly_cents=amt,
            evidence_doc_url=ev, status="SUBMITTED")
    db.competing_offers[o.id] = o
    return success(ser_offer(o), code=201)


@app.get("/api/competing-offers")
@guarded(ALL_READ)
def list_competing_offers():
    items = list(db.competing_offers.values())
    cid = request_args("contract_id")
    if cid is not None:
        items = [o for o in items if o.contract_id == cid]
    st = request_args("status")
    if st is not None:
        items = [o for o in items if o.status == st]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_offer(o) for o in page], response_type="array", page_meta=meta)


@app.get("/api/competing-offers/<oid>")
@guarded(ALL_READ)
def get_competing_offer(oid):
    return success(ser_offer(_get(db.competing_offers, oid)))


@app.post("/api/competing-offers/<oid>/match")
@guarded(OPS)
def match_competing_offer(oid):
    o = _get(db.competing_offers, oid)
    c = _get(db.contracts, o.contract_id)
    body = get_body()
    exp = as_int(req_field(body, "expected_contract_version"), "expected_contract_version")
    if o.status != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Offer is not in SUBMITTED status.")
    from util import parse_dt
    if now() > parse_dt(o.created_at) + timedelta(days=c.rofr_window_days):
        raise err("ERR_WINDOW_EXPIRED", 422,
                  "The right-of-first-refusal window has expired.")
    if any(other.id != o.id and other.contract_id == c.id and other.status == "SUBMITTED"
           for other in db.competing_offers.values()):
        raise err("ERR_DUPLICATE_PENDING", 409,
                  "Another SUBMITTED offer exists on this contract.")
    if c.status != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409,
                  "Matching requires the contract to be ACTIVE.")
    if exp != c.version:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_contract_version does not match the contract's current version.")
    matched = max(0, o.competitor_monthly_cents - ROFR_UNDERCUT_CENTS)
    old_base = c.base_monthly_total_cents
    clines = [l for l in db.lines.values() if l.contract_id == c.id]
    clines.sort(key=lambda l: (-l.base_rate_cents, l.created_at, l._seq))
    if not clines:
        c.base_monthly_total_cents = matched
    elif old_base == 0:
        for i, l in enumerate(clines):
            l.base_rate_cents = matched if i == 0 else 0
            l.touch()
        c.base_monthly_total_cents = matched
    else:
        acc = 0
        for l in clines:
            l.base_rate_cents = rhu(D(l.base_rate_cents) * D(matched) / D(old_base))
            acc += l.base_rate_cents
        rem = matched - acc
        if rem != 0:
            clines[0].base_rate_cents += rem
        for l in clines:
            l.touch()
        c.base_monthly_total_cents = matched
    write_ledger(c.id, now(), old_base, matched, "ROFR_MATCH")
    c.touch()
    o.status = "MATCHED"
    o.touch()
    return success(ser_offer(o))


@app.post("/api/competing-offers/<oid>/decline-match")
@guarded(OPS)
def decline_competing_offer(oid):
    o = _get(db.competing_offers, oid)
    if o.status != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Offer is not in SUBMITTED status.")
    o.status = "NOT_MATCHED"
    o.touch()
    return success(ser_offer(o))


# ---------------- cancellation requests ----------------

@app.post("/api/cancellation-requests")
@guarded(CUST)
def create_cancellation():
    body = get_body()
    c = _get(db.contracts, as_str(req_field(body, "contract_id"), "contract_id"))
    red = as_dt(req_field(body, "requested_end_date"), "requested_end_date")
    if not (red > now()):
        raise err("ERR_INVALID_REQUEST", 400,
                  "requested_end_date must be strictly after now.")
    threshold = c.end_date - timedelta(days=c.cancellation_notice_days)
    timely = red <= threshold
    months = 0 if timely else months_ceil(red, c.end_date)
    r = Rec(contract_id=c.id, requested_end_date=red, timely=timely,
            months_remaining=months, ld_base_cents=0, ld_total_cents=0,
            ld_status="NONE", status="PENDING")
    db.cancellations[r.id] = r
    return success(ser_cancellation(r), code=201)


@app.get("/api/cancellation-requests")
@guarded(ALL_READ)
def list_cancellations():
    items = list(db.cancellations.values())
    cid = request_args("contract_id")
    if cid is not None:
        items = [r for r in items if r.contract_id == cid]
    st = request_args("status")
    if st is not None:
        items = [r for r in items if r.status == st]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_cancellation(r) for r in page], response_type="array", page_meta=meta)


@app.get("/api/cancellation-requests/<rid>")
@guarded(ALL_READ)
def get_cancellation(rid):
    return success(ser_cancellation(_get(db.cancellations, rid)))


def _termination_cascade(c):
    for n in db.rate_notices.values():
        if n.contract_id == c.id and n.status == "SCHEDULED":
            n.status = "CANCELLED"
            n.touch()
    line_ids = {l.id for l in db.lines.values() if l.contract_id == c.id}
    for r in db.service_changes.values():
        if r.service_line_id in line_ids and r.status in ("PENDING", "APPROVED"):
            r.status = "CANCELLED"
            r.touch()
    for o in db.competing_offers.values():
        if o.contract_id == c.id and o.status == "SUBMITTED":
            o.status = "VOID"
            o.touch()


@app.post("/api/cancellation-requests/<rid>/approve")
@guarded(OPS)
def approve_cancellation(rid):
    r = _get(db.cancellations, rid)
    c = _get(db.contracts, r.contract_id)
    if r.status != "PENDING":
        raise err("ERR_INVALID_STATE", 409, "Request is not in PENDING status.")
    if c.status != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409,
                  "Approval requires the owning contract to be ACTIVE.")
    _termination_cascade(c)
    if r.timely:
        r.ld_total_cents = 0
        r.status = "APPROVED"
        c.status = "TERMINATED"
        c.touch()
    else:
        r.ld_base_cents = c.base_monthly_total_cents
        r.ld_total_cents = rhu(D(r.ld_base_cents) * D(r.months_remaining) * D("0.5"))
        r.ld_status = "ASSESSED"
        r.status = "APPROVED"
        c.status = "TERMINATION_PENDING"
        c.touch()
        cust = db.customers.get(c.customer_id)
        if cust is not None:
            recompute_customer_balance(cust)
    r.touch()
    return success(ser_cancellation(r))


@app.post("/api/cancellation-requests/<rid>/deny")
@guarded(OPS)
def deny_cancellation(rid):
    r = _get(db.cancellations, rid)
    if r.status != "PENDING":
        raise err("ERR_INVALID_STATE", 409, "Request is not in PENDING status.")
    r.status = "DENIED"
    r.touch()
    return success(ser_cancellation(r))


@app.post("/api/cancellation-requests/<rid>/withdraw")
@guarded(CUST)
def withdraw_cancellation(rid):
    r = _get(db.cancellations, rid)
    if r.status != "PENDING":
        raise err("ERR_INVALID_STATE", 409, "Request is not in PENDING status.")
    if not (now() <= r.requested_end_date):
        raise err("ERR_WINDOW_EXPIRED", 422,
                  "Withdrawal is only permitted at/before the requested end date.")
    r.status = "WITHDRAWN"
    r.touch()
    return success(ser_cancellation(r))


@app.post("/api/cancellation-requests/<rid>/waive-ld")
@guarded(OPS)
def waive_ld(rid):
    r = _get(db.cancellations, rid)
    if r.ld_status != "ASSESSED":
        raise err("ERR_INVALID_STATE", 409,
                  "Liquidated damages are not in ASSESSED status.")
    r.ld_status = "WAIVED"
    r.touch()
    c = db.contracts.get(r.contract_id)
    if c is not None:
        cust = db.customers.get(c.customer_id)
        if cust is not None:
            recompute_customer_balance(cust)
    return success(ser_cancellation(r))


# ---------------- service credits ----------------

@app.post("/api/service-credits")
@guarded(CUST)
def create_service_credit():
    body = get_body()
    line = _get(db.lines, as_str(req_field(body, "service_line_id"), "service_line_id"))
    ev = _get(db.pickup_events,
              as_str(req_field(body, "pickup_event_id"), "pickup_event_id"))
    if ev.outcome != "MISSED" or ev.service_line_id != line.id:
        raise err("ERR_INVALID_STATE", 409,
                  "The referenced event must be a MISSED event on the same service line.")
    filed = now()
    from util import parse_dt
    if filed > parse_dt(ev.occurred_date) + timedelta(days=CREDIT_FILING_WINDOW_DAYS):
        raise err("ERR_WINDOW_EXPIRED", 422,
                  "Credit must be filed within 14 days of occurred_date.")
    if any(cr.pickup_event_id == ev.id for cr in db.service_credits.values()):
        raise err("ERR_DUPLICATE_PENDING", 409,
                  "A service credit already exists for this pickup event.")
    cfg = active_config_at(filed)
    pct = getattr(cfg, "credit_pct_of_base", None) if cfg is not None else None
    amount = dfloor(D(line.base_rate_cents) * D(pct)) if pct is not None else 0
    cr = Rec(service_line_id=line.id, pickup_event_id=ev.id,
             credit_cents=amount, filed_at=fmt_ts(filed), status="ACTIVE")
    db.service_credits[cr.id] = cr
    contract = db.contracts.get(line.contract_id)
    if contract is not None:
        cust = db.customers.get(contract.customer_id)
        if cust is not None:
            recompute_customer_balance(cust)
    return success(ser_credit(cr), code=201)


@app.get("/api/service-credits")
@guarded(ALL_READ)
def list_service_credits():
    items = list(db.service_credits.values())
    sl = request_args("service_line_id")
    if sl is not None:
        items = [c for c in items if c.service_line_id == sl]
    pe = request_args("pickup_event_id")
    if pe is not None:
        items = [c for c in items if c.pickup_event_id == pe]
    st = request_args("status")
    if st is not None:
        items = [c for c in items if c.status == st]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_credit(c) for c in page], response_type="array", page_meta=meta)


@app.get("/api/service-credits/<cid>")
@guarded(ALL_READ)
def get_service_credit(cid):
    return success(ser_credit(_get(db.service_credits, cid)))


# ---------------- roll-off orders ----------------

@app.post("/api/rolloff-orders")
@guarded(CUST)
def create_rolloff():
    body = get_body()
    cust = _get(db.customers, as_str(req_field(body, "customer_id"), "customer_id"))
    size = as_enum(req_field(body, "container_size"), "container_size", ROLLOFF_SIZES)
    dd = as_dt(req_field(body, "delivery_date"), "delivery_date")
    days = as_int(req_field(body, "rental_days"), "rental_days")
    if days < 1 or days > 30:
        raise err("ERR_INVALID_REQUEST", 400, "rental_days must be in 1..30.")
    inc = 2.0
    if "included_tons" in body and body["included_tons"] is not None:
        inc = as_num(body["included_tons"], "included_tons")
    dfee = as_int(req_field(body, "delivery_fee_cents"), "delivery_fee_cents")
    daily = as_int(req_field(body, "daily_rental_cents"), "daily_rental_cents")
    over = as_int(req_field(body, "overage_ton_cents"), "overage_ton_cents")
    o = Rec(customer_id=cust.id, container_size=size, delivery_date=dd,
            rental_days=days, included_tons=inc, actual_tons=None,
            delivery_fee_cents=dfee, daily_rental_cents=daily,
            overage_ton_cents=over, total_cents=0, status="RESERVED")
    db.rolloff_orders[o.id] = o
    return success(ser_rolloff(o), code=201)


@app.get("/api/rolloff-orders")
@guarded(ALL_READ)
def list_rolloffs():
    items = list(db.rolloff_orders.values())
    cid = request_args("customer_id")
    if cid is not None:
        items = [o for o in items if o.customer_id == cid]
    st = request_args("status")
    if st is not None:
        items = [o for o in items if o.status == st]
    items.sort(key=lambda x: (x.created_at, x._seq))
    page, meta = paginate(items)
    return success([ser_rolloff(o) for o in page], response_type="array", page_meta=meta)


@app.get("/api/rolloff-orders/<oid>")
@guarded(ALL_READ)
def get_rolloff(oid):
    return success(ser_rolloff(_get(db.rolloff_orders, oid)))


@app.post("/api/rolloff-orders/<oid>/deliver")
@guarded(OPS)
def deliver_rolloff(oid):
    o = _get(db.rolloff_orders, oid)
    if o.status != "RESERVED":
        raise err("ERR_INVALID_STATE", 409, "Order is not in RESERVED status.")
    if not (now() >= o.delivery_date):
        raise err("ERR_INVALID_STATE", 409,
                  "Delivery cannot be marked before the delivery_date.")
    o.status = "DELIVERED"
    o.touch()
    return success(ser_rolloff(o))


@app.post("/api/rolloff-orders/<oid>/complete")
@guarded(OPS)
def complete_rolloff(oid):
    o = _get(db.rolloff_orders, oid)
    body = get_body()
    if o.status != "DELIVERED":
        raise err("ERR_INVALID_STATE", 409, "Order is not in DELIVERED status.")
    actual = as_num(req_field(body, "actual_tons"), "actual_tons")
    o.actual_tons = actual
    rental = o.daily_rental_cents * o.rental_days
    billable = max(0, dceil(D(actual) - D(o.included_tons)))
    overage = billable * o.overage_ton_cents
    o.total_cents = o.delivery_fee_cents + rental + overage
    o.status = "COMPLETED"
    o.touch()
    return success(ser_rolloff(o))


@app.post("/api/rolloff-orders/<oid>/cancel")
@guarded(CUST)
def cancel_rolloff(oid):
    o = _get(db.rolloff_orders, oid)
    if o.status != "RESERVED":
        raise err("ERR_INVALID_STATE", 409, "Order is not in RESERVED status.")
    if not (now() < o.delivery_date):
        raise err("ERR_INVALID_STATE", 409,
                  "Cancellation is only permitted before the delivery_date.")
    o.status = "CANCELLED"
    o.touch()
    return success(ser_rolloff(o))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
