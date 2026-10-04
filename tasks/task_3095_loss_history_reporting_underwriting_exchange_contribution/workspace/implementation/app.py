"""Loss History Exchange API — Flask application with all routes."""
import re
from datetime import timedelta
from functools import wraps

from flask import Flask, request

from db import db
from services import (
    RULE_DEFAULTS, LOSS_TYPES, CLAIM_STATUS_CODES, PERMISSIBLE_PURPOSES,
    DISPUTE_REASONS, RESOLUTION_CODES, NOTICE_ACTION_TYPES,
    get_rules, add_event, serialize_event, carrier_lag_days, stamp_new, touch,
    serialize, sorted_by_creation, compute_match, issue_report, sweep_clock,
)
from util import (
    ApiError, error_response, success, paginate, authenticate, require_roles,
    require_owner, body_json, require_fields, fmt_dt, parse_iso, parse_date,
    add_years, LOCK,
    ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_NOT_FOUND,
    ERR_REFERENCED_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
    ERR_INVALID_STATE, ERR_CARRIER_NOT_ACTIVE, ERR_RECIPROCITY_REQUIRED,
    ERR_PERMISSIBLE_PURPOSE, ERR_CONSUMER_FILE_FROZEN, ERR_DISPUTE_ALREADY_OPEN,
    ERR_DISPUTE_OVERDUE, ERR_BATCH_CONSTRAINT, ERR_INQUIRY_CAP_EXCEEDED,
    ERR_EXCHANGE_RULE_EXISTS,
    PA, ECO, CDS, CU, CONS, ALL_ROLES,
)

app = Flask(__name__)

CAUSE_CODE_RE = re.compile(r"^[A-Z0-9]{1,8}$")
REASON_CODE_RE = re.compile(r"^[A-Z0-9-]{2,16}$")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, 500, "Internal error"))


# ---------------------------------------------------------------------------
# Route decorator: auth + role gate, serialized writes
# ---------------------------------------------------------------------------

def endpoint(methods, path, roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                uid, role = authenticate()
                require_roles(role, roles)
                return fn(uid, role, *args, **kwargs)

        app.add_url_rule(path, fn.__name__ + "_" + "_".join(methods),
                         wrapper, methods=methods)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def get_carrier_or_404(carrier_id):
    c = db.carriers.get(carrier_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Carrier not found")
    return c


def get_consumer_or_404(consumer_id):
    c = db.consumers.get(consumer_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Consumer not found")
    return c


def get_batch_or_404(batch_id):
    b = db.batches.get(batch_id)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Contribution batch not found")
    return b


def get_claim_or_404(claim_id):
    c = db.claims.get(claim_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loss claim not found")
    return c


def get_inquiry_or_404(inquiry_id):
    i = db.inquiries.get(inquiry_id)
    if i is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Quote inquiry not found")
    return i


def get_report_or_404(report_id):
    r = db.reports.get(report_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loss history report not found")
    return r


def get_entry_or_404(entry_id):
    e = db.entries.get(entry_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Report claim entry not found")
    return e


def get_dispute_or_404(dispute_id):
    d = db.disputes.get(dispute_id)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Dispute not found")
    return d


def get_notice_or_404(notice_id):
    n = db.notices.get(notice_id)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Adverse action notice not found")
    return n


def carrier_scoped_read_guard(uid, role, carrier_id):
    """Entity-backed carrier roles may only touch their own carrier."""
    if role in (CDS, CU):
        require_owner(uid, carrier_id)


def consumer_scoped_guard(uid, role, consumer_id):
    if role == CONS:
        require_owner(uid, consumer_id)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_carrier(c):
    lag = carrier_lag_days(c)
    out = serialize(c)
    out["contribution_lag_days"] = lag
    return out


def ser_consumer(c):
    return serialize(c)


def ser_batch(b):
    return serialize(b)


def ser_claim(c):
    return serialize(c)


def ser_inquiry(i):
    return serialize(i)


def ser_report(r):
    return serialize(r)


def ser_entry(e):
    return serialize(e)


def ser_dispute(d):
    return serialize(d)


def ser_notice(n):
    return serialize(n)


def ser_rules(r):
    return serialize(r)


# ===========================================================================
# Logical clock
# ===========================================================================

@endpoint(["POST"], "/_clock/set_current_utc", [PA])
def set_clock(uid, role):
    data = body_json()
    require_fields(data, ["to_iso8601"])
    try:
        target = parse_iso(data["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 timestamp")
    db.set_clock(target)
    result = sweep_clock()
    return success(result, 200)


# ===========================================================================
# ExchangeRule singleton
# ===========================================================================

@endpoint(["POST"], "/exchange-rules", [PA])
def create_exchange_rules(uid, role):
    if db.exchange_rule is not None:
        raise ApiError(ERR_EXCHANGE_RULE_EXISTS, 409,
                       "ExchangeRule singleton already exists")
    rec = {"id": db.new_id()}
    rec.update(RULE_DEFAULTS)
    stamp_new(rec)
    db.exchange_rule = rec
    return success(ser_rules(rec), 201)


@endpoint(["GET"], "/exchange-rules", ALL_ROLES)
def get_exchange_rules(uid, role):
    if db.exchange_rule is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ExchangeRule not initialized")
    return success(ser_rules(db.exchange_rule), 200)


@endpoint(["PATCH"], "/exchange-rules", [PA])
def patch_exchange_rules(uid, role):
    if db.exchange_rule is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ExchangeRule not initialized")
    data = body_json()
    for key, value in data.items():
        if key not in RULE_DEFAULTS:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Unknown tunable: {key}")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Tunable {key} must be an integer")
        db.exchange_rule[key] = value
    touch(db.exchange_rule)
    return success(ser_rules(db.exchange_rule), 200)


# ===========================================================================
# Carriers
# ===========================================================================

@endpoint(["POST"], "/carriers", [PA])
def create_carrier(uid, role):
    data = body_json()
    require_fields(data, ["legal_name", "naic_code"])
    for c in db.carriers.values():
        if c["naic_code"] == data["naic_code"]:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "naic_code must be unique across all carriers")
    rec = {
        "id": db.new_id(),
        "legal_name": data["legal_name"],
        "naic_code": data["naic_code"],
        "status": "PROVISIONAL",
        "accepted_batch_count": 0,
        "accepted_claim_count": 0,
    }
    stamp_new(rec)
    db.carriers[rec["id"]] = rec
    return success(ser_carrier(rec), 201)


@endpoint(["GET"], "/carriers", [PA, ECO])
def list_carriers(uid, role):
    items = sorted_by_creation(db.carriers.values())
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return paginate([ser_carrier(c) for c in items])


@endpoint(["GET"], "/carriers/<carrier_id>", [PA, ECO, CDS, CU])
def get_carrier(uid, role, carrier_id):
    c = get_carrier_or_404(carrier_id)
    carrier_scoped_read_guard(uid, role, carrier_id)
    return success(ser_carrier(c), 200)


@endpoint(["POST"], "/carriers/<carrier_id>/withdraw", [ECO])
def withdraw_carrier(uid, role, carrier_id):
    c = get_carrier_or_404(carrier_id)
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or SUSPENDED carrier may be withdrawn")
    for b in db.batches.values():
        if b["carrier_id"] == c["id"] and b["status"] in ("RECEIVED", "VALIDATED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Carrier has in-flight contribution batches")
    c["status"] = "WITHDRAWN"
    touch(c)
    return success(ser_carrier(c), 200)


# ===========================================================================
# Contribution batches
# ===========================================================================

def _validate_claim_row_shape(row):
    """Envelope-level row shape; returns list of missing fields."""
    required = ["consumer_id", "policy_number", "claim_number", "loss_date",
                "loss_type", "cause_of_loss_code", "paid_amount_cents",
                "claim_status_code"]
    return [f for f in required if f not in row or row[f] is None]


def _row_coding_ok(row):
    if row["loss_type"] not in LOSS_TYPES:
        return False, "LOSS_TYPE"
    if row["claim_status_code"] not in CLAIM_STATUS_CODES:
        return False, "CLAIM_STATUS_CODE"
    if not isinstance(row["cause_of_loss_code"], str) or \
            not CAUSE_CODE_RE.match(row["cause_of_loss_code"]):
        return False, "CAUSE_OF_LOSS_CODE"
    if not isinstance(row["paid_amount_cents"], int) or \
            isinstance(row["paid_amount_cents"], bool) or \
            row["paid_amount_cents"] < 0:
        return False, "PAID_AMOUNT"
    try:
        parse_date(row["loss_date"])
    except (ValueError, TypeError):
        return False, "LOSS_DATE"
    return True, None


@endpoint(["POST"], "/carriers/<carrier_id>/batches", [CDS])
def create_batch(uid, role, carrier_id):
    carrier = get_carrier_or_404(carrier_id)
    require_owner(uid, carrier_id)
    if carrier["status"] == "WITHDRAWN":
        raise ApiError(ERR_CARRIER_NOT_ACTIVE, 409,
                       "A WITHDRAWN carrier cannot contribute batches")

    data = body_json()
    if "claims" not in data or not isinstance(data["claims"], list):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "claims must be provided as an array")
    rows = data["claims"]
    for row in rows:
        if not isinstance(row, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Each claim row must be an object")
        missing = _validate_claim_row_shape(row)
        if missing:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Claim row missing required fields: " + ", ".join(missing))

    # Body-declared foreign keys resolve in input declaration order.
    for row in rows:
        if row["consumer_id"] not in db.consumers:
            raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                           f"Consumer not found: {row['consumer_id']}")

    rules = get_rules()
    if not (rules["min_batch_claims"] <= len(rows) <= rules["max_batch_claims"]):
        raise ApiError(ERR_BATCH_CONSTRAINT, 422,
                       "Batch size outside [min_batch_claims, max_batch_claims]")

    seen_numbers = set()
    contributed_numbers = {c["claim_number"] for c in db.claims.values()
                           if c["contributing_carrier_id"] == carrier_id}
    for row in rows:
        cn = row["claim_number"]
        if cn in seen_numbers or cn in contributed_numbers:
            raise ApiError(ERR_BATCH_CONSTRAINT, 422,
                           "Duplicate claim_number within the carrier")
        seen_numbers.add(cn)

    # Per-row standardized coding validation.
    now = fmt_dt(db.now())
    batch = {
        "id": db.new_id(),
        "carrier_id": carrier_id,
        "submitted_at": now,
        "claim_count": len(rows),
        "accepted_count": 0,
        "rejected_count": 0,
        "status": "RECEIVED",
        "_submitted_dt": db.now(),
    }
    stamp_new(batch)
    db.batches[batch["id"]] = batch

    accepted_rows = []
    for row in rows:
        ok, code = _row_coding_ok(row)
        if ok:
            accepted_rows.append(row)
        else:
            add_event("CLAIM_REJECTED", carrier_id=carrier_id,
                      consumer_id=row["consumer_id"],
                      details={"claim_number": row["claim_number"],
                               "rejection_code": code})
    batch["accepted_count"] = len(accepted_rows)
    batch["rejected_count"] = len(rows) - len(accepted_rows)

    # RECEIVED -> VALIDATED
    batch["status"] = "VALIDATED"
    touch(batch)
    add_event("BATCH_RECEIVED", carrier_id=carrier_id,
              details={"batch_id": batch["id"], "claim_count": len(rows)})

    rules = get_rules()
    if accepted_rows:
        # VALIDATED -> COMPLETED
        for row in accepted_rows:
            loss_d = parse_date(row["loss_date"])
            retention_exp = add_years(loss_d, rules["retention_years"])
            claim = {
                "id": db.new_id(),
                "contributing_carrier_id": carrier_id,
                "batch_id": batch["id"],
                "consumer_id": row["consumer_id"],
                "policy_number": row["policy_number"],
                "claim_number": row["claim_number"],
                "loss_date": row["loss_date"],
                "loss_type": row["loss_type"],
                "cause_of_loss_code": row["cause_of_loss_code"],
                "paid_amount_cents": row["paid_amount_cents"],
                "claim_status_code": row["claim_status_code"],
                "vehicle_identifier": row.get("vehicle_identifier") or "",
                "status": "ACTIVE",
                "amendment_of_id": None,
                "retention_expires_on": retention_exp.isoformat(),
                "_loss_date_ord": loss_d.toordinal(),
                "_retention_expires_date": retention_exp,
                "_retention_redacted": False,
            }
            stamp_new(claim)
            db.claims[claim["id"]] = claim
            add_event("CLAIM_ACCEPTED", carrier_id=carrier_id,
                      consumer_id=row["consumer_id"],
                      details={"claim_id": claim["id"],
                               "claim_number": row["claim_number"]})
        batch["status"] = "COMPLETED"
        touch(batch)
        carrier["accepted_batch_count"] += 1
        carrier["accepted_claim_count"] += len(accepted_rows)
        touch(carrier)
        add_event("BATCH_COMPLETED", carrier_id=carrier_id,
                  details={"batch_id": batch["id"],
                           "accepted_count": len(accepted_rows)})
        # Standing cascades.
        lag = carrier_lag_days(carrier)
        threshold = rules["reciprocity_lag_threshold_days"]
        if carrier["status"] == "PROVISIONAL":
            carrier["status"] = "ACTIVE"
            touch(carrier)
            add_event("CARRIER_REACTIVATED", carrier_id=carrier_id,
                      details={"contribution_lag_days": lag})
        elif carrier["status"] == "SUSPENDED" and (lag is None or lag < threshold):
            carrier["status"] = "ACTIVE"
            touch(carrier)
            add_event("CARRIER_REACTIVATED", carrier_id=carrier_id,
                      details={"contribution_lag_days": lag})
    else:
        # VALIDATED -> FAILED
        batch["status"] = "FAILED"
        touch(batch)
        add_event("BATCH_FAILED", carrier_id=carrier_id,
                  details={"batch_id": batch["id"],
                           "rejected_count": batch["rejected_count"]})

    return success(ser_batch(batch), 201)


@endpoint(["GET"], "/carriers/<carrier_id>/batches", [PA, ECO, CDS])
def list_carrier_batches(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    carrier_scoped_read_guard(uid, role, carrier_id)
    items = [b for b in sorted_by_creation(db.batches.values())
             if b["carrier_id"] == carrier_id]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    return paginate([ser_batch(b) for b in items])


@endpoint(["GET"], "/batches", [PA, ECO])
def list_batches(uid, role):
    items = sorted_by_creation(db.batches.values())
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")
    if carrier_id:
        items = [b for b in items if b["carrier_id"] == carrier_id]
    if status:
        items = [b for b in items if b["status"] == status]
    return paginate([ser_batch(b) for b in items])


@endpoint(["GET"], "/batches/<batch_id>", [PA, ECO, CDS])
def get_batch(uid, role, batch_id):
    b = get_batch_or_404(batch_id)
    if role == CDS:
        require_owner(uid, b["carrier_id"])
    return success(ser_batch(b), 200)


@endpoint(["POST"], "/batches/<batch_id>/void", [ECO])
def void_batch(uid, role, batch_id):
    b = get_batch_or_404(batch_id)
    open_disputes = [d for d in db.disputes.values()
                     if d["status"] in ("FILED", "UNDER_REINVESTIGATION")
                     and db.claims.get(d["loss_claim_id"]) is not None
                     and db.claims[d["loss_claim_id"]]["batch_id"] == batch_id]
    if b["status"] in ("COMPLETED",):
        if not open_disputes:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Voiding a terminal batch is rejected")
    elif b["status"] not in ("RECEIVED", "VALIDATED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Voiding a terminal batch is rejected")

    b["status"] = "VOIDED"
    touch(b)
    add_event("BATCH_VOIDED", carrier_id=b["carrier_id"],
              details={"batch_id": batch_id})

    # Correction hold: if any open dispute on this batch's claims has lapsed
    # its hold window, voiding additionally suspends the carrier.
    rules = get_rules()
    hold = timedelta(days=rules["correction_hold_days"])
    lapsed = False
    for d in open_disputes:
        claim = db.claims[d["loss_claim_id"]]
        batch = db.batches.get(claim["batch_id"])
        if batch is None:
            continue
        gap = d["_filed_dt"] - batch["_submitted_dt"]
        if not (gap < hold):
            lapsed = True
            break
    if lapsed:
        carrier = db.carriers.get(b["carrier_id"])
        if carrier is not None and carrier["status"] in ("ACTIVE",):
            carrier["status"] = "SUSPENDED"
            touch(carrier)
            add_event("BATCH_FROZEN_BY_CORRECTION", carrier_id=carrier["id"],
                      details={"batch_id": batch_id})
            add_event("CARRIER_SUSPENDED", carrier_id=carrier["id"],
                      details={"contribution_lag_days": carrier_lag_days(carrier)})
    return success(ser_batch(b), 200)


@endpoint(["GET"], "/batches/<batch_id>/claims", [PA, ECO, CDS])
def list_batch_claims(uid, role, batch_id):
    b = get_batch_or_404(batch_id)
    if role == CDS:
        require_owner(uid, b["carrier_id"])
    items = [c for c in sorted_by_creation(db.claims.values())
             if c["batch_id"] == batch_id]
    return paginate([ser_claim(c) for c in items])


# ===========================================================================
# Loss claims
# ===========================================================================

@endpoint(["GET"], "/claims", [PA, ECO])
def list_claims(uid, role):
    items = sorted_by_creation(db.claims.values())
    for param, field in (("contributing_carrier_id", "contributing_carrier_id"),
                         ("batch_id", "batch_id"),
                         ("consumer_id", "consumer_id"),
                         ("amendment_of_id", "amendment_of_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    return paginate([ser_claim(c) for c in items])


@endpoint(["GET"], "/claims/<claim_id>", [PA, ECO, CDS, CONS])
def get_claim(uid, role, claim_id):
    c = get_claim_or_404(claim_id)
    if role == CDS:
        require_owner(uid, c["contributing_carrier_id"])
    if role == CONS:
        require_owner(uid, c["consumer_id"])
    return success(ser_claim(c), 200)


@endpoint(["GET"], "/carriers/<carrier_id>/claims", [PA, ECO, CDS])
def list_carrier_claims(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    carrier_scoped_read_guard(uid, role, carrier_id)
    items = [c for c in sorted_by_creation(db.claims.values())
             if c["contributing_carrier_id"] == carrier_id]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return paginate([ser_claim(c) for c in items])


def _validate_amendment_fields(data, prefix=""):
    """Validate replacement-claim fields; returns dict of clean values."""
    fields = {}
    names = ["loss_date", "loss_type", "cause_of_loss_code",
             "paid_amount_cents", "claim_status_code"]
    for n in names:
        key = prefix + n
        if key not in data or data[key] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {key}")
        fields[n] = data[key]
    row = dict(fields)
    ok, code = _row_coding_ok(row)
    if not ok:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Corrected claim fails standardized coding: {code}")
    veh = data.get(prefix + "vehicle_identifier")
    fields["vehicle_identifier"] = veh if isinstance(veh, str) else ""
    return fields


def _create_replacement_claim(original, fields):
    rules = get_rules()
    loss_d = parse_date(fields["loss_date"])
    retention_exp = add_years(loss_d, rules["retention_years"])
    claim = {
        "id": db.new_id(),
        "contributing_carrier_id": original["contributing_carrier_id"],
        "batch_id": original["batch_id"],
        "consumer_id": original["consumer_id"],
        "policy_number": original["policy_number"],
        "claim_number": original["claim_number"],
        "loss_date": fields["loss_date"],
        "loss_type": fields["loss_type"],
        "cause_of_loss_code": fields["cause_of_loss_code"],
        "paid_amount_cents": fields["paid_amount_cents"],
        "claim_status_code": fields["claim_status_code"],
        "vehicle_identifier": fields["vehicle_identifier"]
            if fields["vehicle_identifier"] != ""
            else original["vehicle_identifier"],
        "status": "ACTIVE",
        "amendment_of_id": original["id"],
        "retention_expires_on": retention_exp.isoformat(),
        "_loss_date_ord": loss_d.toordinal(),
        "_retention_expires_date": retention_exp,
        "_retention_redacted": False,
    }
    stamp_new(claim)
    db.claims[claim["id"]] = claim
    original["status"] = "AMENDED"
    touch(original)
    add_event("CLAIM_AMENDED", carrier_id=original["contributing_carrier_id"],
              consumer_id=original["consumer_id"],
              details={"claim_id": original["id"],
                       "replacement_claim_id": claim["id"]})
    return claim


@endpoint(["POST"], "/claims/<claim_id>/amendments", [CDS])
def create_claim_amendment(uid, role, claim_id):
    original = get_claim_or_404(claim_id)
    require_owner(uid, original["contributing_carrier_id"])
    data = body_json()
    if "expected_claim_version" not in data or data["expected_claim_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing required field: expected_claim_version")
    fields = _validate_amendment_fields(data)
    if data["expected_claim_version"] != original["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_claim_version does not match the claim's current version")
    if original["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE claim may be superseded by an amendment")
    claim = _create_replacement_claim(original, fields)
    return success(ser_claim(claim), 201)


@endpoint(["GET"], "/claims/<claim_id>/amendments", [PA, ECO, CDS, CONS])
def list_claim_amendments(uid, role, claim_id):
    c = get_claim_or_404(claim_id)
    if role == CDS:
        require_owner(uid, c["contributing_carrier_id"])
    if role == CONS:
        require_owner(uid, c["consumer_id"])
    items = [x for x in sorted_by_creation(db.claims.values())
             if x["amendment_of_id"] == claim_id]
    return paginate([ser_claim(x) for x in items])


@endpoint(["GET"], "/claims/<claim_id>/disputes", [PA, ECO, CONS])
def list_claim_disputes(uid, role, claim_id):
    c = get_claim_or_404(claim_id)
    if role == CONS:
        require_owner(uid, c["consumer_id"])
    items = [d for d in sorted_by_creation(db.disputes.values())
             if d["loss_claim_id"] == claim_id]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    return paginate([ser_dispute(d) for d in items])


@endpoint(["GET"], "/claims/<claim_id>/report-entries", [PA, ECO, CDS, CONS])
def list_claim_report_entries(uid, role, claim_id):
    c = get_claim_or_404(claim_id)
    if role == CDS:
        require_owner(uid, c["contributing_carrier_id"])
    if role == CONS:
        require_owner(uid, c["consumer_id"])
    items = [e for e in sorted_by_creation(db.entries.values())
             if e["loss_claim_id"] == claim_id]
    return paginate([ser_entry(e) for e in items])


# ===========================================================================
# Consumers
# ===========================================================================

@endpoint(["POST"], "/consumers", [PA])
def create_consumer(uid, role):
    data = body_json()
    require_fields(data, ["full_name", "date_of_birth", "address_line",
                          "driver_license_number"])
    rec = {
        "id": db.new_id(),
        "full_name": data["full_name"],
        "date_of_birth": data["date_of_birth"],
        "address_line": data["address_line"],
        "driver_license_number": data["driver_license_number"],
        "file_frozen": False,
        "frozen_until": None,
        "_frozen_until_dt": None,
    }
    stamp_new(rec)
    db.consumers[rec["id"]] = rec
    return success(ser_consumer(rec), 201)


@endpoint(["GET"], "/consumers", [PA, ECO])
def list_consumers(uid, role):
    items = sorted_by_creation(db.consumers.values())
    return paginate([ser_consumer(c) for c in items])


@endpoint(["GET"], "/consumers/<consumer_id>", [PA, ECO, CONS])
def get_consumer(uid, role, consumer_id):
    c = get_consumer_or_404(consumer_id)
    consumer_scoped_guard(uid, role, consumer_id)
    return success(ser_consumer(c), 200)


@endpoint(["GET"], "/consumers/<consumer_id>/file", [CONS])
def get_consumer_file(uid, role, consumer_id):
    c = get_consumer_or_404(consumer_id)
    require_owner(uid, consumer_id)
    if c["file_frozen"]:
        raise ApiError(ERR_CONSUMER_FILE_FROZEN, 409,
                       "Consumer file is frozen; file access blocked until frozen_until")
    claims = [ser_claim(x) for x in sorted_by_creation(db.claims.values())
              if x["consumer_id"] == consumer_id]
    disputes = [ser_dispute(x) for x in sorted_by_creation(db.disputes.values())
                if x["consumer_id"] == consumer_id]
    notices = [ser_notice(x) for x in sorted_by_creation(db.notices.values())
               if x["consumer_id"] == consumer_id]
    return success({
        "consumer": ser_consumer(c),
        "claims": claims,
        "disputes": disputes,
        "adverse_action_notices": notices,
    }, 200)


@endpoint(["POST"], "/consumers/<consumer_id>/freeze", [ECO])
def freeze_consumer(uid, role, consumer_id):
    c = get_consumer_or_404(consumer_id)
    if c["file_frozen"]:
        raise ApiError(ERR_INVALID_STATE, 409, "Consumer file is already frozen")
    rules = get_rules()
    until = db.now() + timedelta(days=rules["data_freeze_days"])
    c["file_frozen"] = True
    c["frozen_until"] = fmt_dt(until)
    c["_frozen_until_dt"] = until
    touch(c)
    add_event("DATA_FREEZE_APPLIED", consumer_id=c["id"],
              details={"frozen_until": c["frozen_until"]})
    # Cascade: every ISSUED report of this consumer -> FROZEN.
    for r in db.reports.values():
        if r["consumer_id"] == c["id"] and r["status"] == "ISSUED":
            r["status"] = "FROZEN"
            touch(r)
            add_event("REPORT_FROZEN", carrier_id=r["carrier_id"],
                      consumer_id=c["id"], details={"report_id": r["id"]})
    return success(ser_consumer(c), 200)


@endpoint(["GET"], "/consumers/<consumer_id>/claims", [PA, ECO, CONS])
def list_consumer_claims(uid, role, consumer_id):
    get_consumer_or_404(consumer_id)
    consumer_scoped_guard(uid, role, consumer_id)
    items = [c for c in sorted_by_creation(db.claims.values())
             if c["consumer_id"] == consumer_id]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return paginate([ser_claim(c) for c in items])


@endpoint(["GET"], "/consumers/<consumer_id>/reports", [PA, ECO, CONS])
def list_consumer_reports(uid, role, consumer_id):
    get_consumer_or_404(consumer_id)
    consumer_scoped_guard(uid, role, consumer_id)
    items = [r for r in sorted_by_creation(db.reports.values())
             if r["consumer_id"] == consumer_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return paginate([ser_report(r) for r in items])


@endpoint(["GET"], "/consumers/<consumer_id>/report-entries", [PA, ECO, CONS])
def list_consumer_report_entries(uid, role, consumer_id):
    get_consumer_or_404(consumer_id)
    consumer_scoped_guard(uid, role, consumer_id)
    items = [e for e in sorted_by_creation(db.entries.values())
             if e["consumer_id"] == consumer_id]
    return paginate([ser_entry(e) for e in items])


@endpoint(["GET"], "/consumers/<consumer_id>/inquiries", [PA, ECO, CONS])
def list_consumer_inquiries(uid, role, consumer_id):
    get_consumer_or_404(consumer_id)
    consumer_scoped_guard(uid, role, consumer_id)
    items = [i for i in sorted_by_creation(db.inquiries.values())
             if i["matched_consumer_id"] == consumer_id]
    return paginate([ser_inquiry(i) for i in items])


@endpoint(["GET"], "/consumers/<consumer_id>/adverse-action-notices", [PA, ECO, CONS])
def list_consumer_notices(uid, role, consumer_id):
    get_consumer_or_404(consumer_id)
    consumer_scoped_guard(uid, role, consumer_id)
    items = [n for n in sorted_by_creation(db.notices.values())
             if n["consumer_id"] == consumer_id]
    status = request.args.get("status")
    if status:
        items = [n for n in items if n["status"] == status]
    return paginate([ser_notice(n) for n in items])


@endpoint(["GET"], "/consumers/<consumer_id>/audit-events", [PA, ECO])
def list_consumer_audit_events(uid, role, consumer_id):
    get_consumer_or_404(consumer_id)
    items = [e for e in sorted_by_creation(db.audit_events.values())
             if e["consumer_id"] == consumer_id]
    event_type = request.args.get("event_type")
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]
    items = list(reversed(items))  # most recent first
    return paginate([serialize_event(e) for e in items])


# ===========================================================================
# Quote inquiries and reports
# ===========================================================================

@endpoint(["POST"], "/carriers/<carrier_id>/inquiries", [CU])
def create_inquiry(uid, role, carrier_id):
    carrier = get_carrier_or_404(carrier_id)
    require_owner(uid, carrier_id)
    data = body_json()
    require_fields(data, ["subject_name", "subject_dob", "subject_address",
                          "subject_driver_license", "permissible_purpose"])
    purpose = data["permissible_purpose"]
    if purpose not in PERMISSIBLE_PURPOSES:
        raise ApiError(ERR_PERMISSIBLE_PURPOSE, 403,
                       "permissible_purpose missing or out of enum")
    if carrier["status"] in ("PROVISIONAL", "WITHDRAWN"):
        raise ApiError(ERR_CARRIER_NOT_ACTIVE, 409,
                       "Carrier has no report access: contributions required")

    matched, grades, score, disposition = compute_match(
        data["subject_name"], data["subject_dob"], data["subject_address"],
        data["subject_driver_license"],
        data.get("subject_vehicle_identifier") or "")

    if purpose == "CONSUMER_REQUEST":
        if matched is None or matched["id"] != uid:
            raise ApiError(ERR_PERMISSIBLE_PURPOSE, 403,
                           "CONSUMER_REQUEST subject must resolve to the acting consumer")

    # Frozen + failing reciprocity together: the safety check ranks first.
    if matched is not None and matched["file_frozen"] \
            and carrier["status"] != "ACTIVE":
        raise ApiError(ERR_CONSUMER_FILE_FROZEN, 409,
                       "Consumer file is frozen; report issuance blocked")

    inquiry = {
        "id": db.new_id(),
        "carrier_id": carrier_id,
        "subject_name": data["subject_name"],
        "subject_dob": data["subject_dob"],
        "subject_address": data["subject_address"],
        "subject_driver_license": data["subject_driver_license"],
        "subject_vehicle_identifier": data.get("subject_vehicle_identifier") or "",
        "permissible_purpose": purpose,
        "matched_consumer_id": matched["id"] if matched else None,
        "individual_match_grade": grades["individual"] if grades else None,
        "address_match_grade": grades["address"] if grades else None,
        "vehicle_match_grade": grades["vehicle"] if grades else None,
        "match_score": score,
        "match_disposition": disposition,
        "report_id": None,
        "report_blocked_reason": "NONE",
        "status": "RESOLVED",
    }
    stamp_new(inquiry)
    db.inquiries[inquiry["id"]] = inquiry

    if disposition != "UNMATCHED" and matched is not None:
        if matched["file_frozen"]:
            inquiry["report_blocked_reason"] = "FROZEN"
        elif carrier["status"] != "ACTIVE":
            inquiry["report_blocked_reason"] = "RECIPROCITY"
        else:
            report = issue_report(inquiry, carrier, matched, disposition, score)
            inquiry["report_id"] = report["id"]
            touch(inquiry)

    return success(ser_inquiry(inquiry), 201)


@endpoint(["GET"], "/carriers/<carrier_id>/inquiries", [PA, ECO, CU])
def list_carrier_inquiries(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    carrier_scoped_read_guard(uid, role, carrier_id)
    items = [i for i in sorted_by_creation(db.inquiries.values())
             if i["carrier_id"] == carrier_id]
    md = request.args.get("match_disposition")
    if md:
        items = [i for i in items if i["match_disposition"] == md]
    return paginate([ser_inquiry(i) for i in items])


@endpoint(["GET"], "/inquiries", [PA, ECO])
def list_inquiries(uid, role):
    items = sorted_by_creation(db.inquiries.values())
    for param, field in (("carrier_id", "carrier_id"),
                         ("matched_consumer_id", "matched_consumer_id"),
                         ("report_id", "report_id"),
                         ("match_disposition", "match_disposition")):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i[field] == v]
    return paginate([ser_inquiry(i) for i in items])


@endpoint(["GET"], "/inquiries/<inquiry_id>", [PA, ECO, CU])
def get_inquiry(uid, role, inquiry_id):
    i = get_inquiry_or_404(inquiry_id)
    if role == CU:
        require_owner(uid, i["carrier_id"])
    return success(ser_inquiry(i), 200)


@endpoint(["GET"], "/reports", [PA, ECO])
def list_reports(uid, role):
    items = sorted_by_creation(db.reports.values())
    for param, field in (("inquiry_id", "inquiry_id"),
                         ("consumer_id", "consumer_id"),
                         ("carrier_id", "carrier_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    return paginate([ser_report(r) for r in items])


@endpoint(["GET"], "/reports/<report_id>", [PA, ECO, CU, CONS])
def get_report(uid, role, report_id):
    r = get_report_or_404(report_id)
    if role == CU:
        require_owner(uid, r["carrier_id"])
    if role == CONS:
        require_owner(uid, r["consumer_id"])
    return success(ser_report(r), 200)


@endpoint(["GET"], "/carriers/<carrier_id>/reports", [PA, ECO, CU])
def list_carrier_reports(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    carrier_scoped_read_guard(uid, role, carrier_id)
    items = [r for r in sorted_by_creation(db.reports.values())
             if r["carrier_id"] == carrier_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return paginate([ser_report(r) for r in items])


@endpoint(["GET"], "/report-entries", [PA, ECO])
def list_report_entries(uid, role):
    items = sorted_by_creation(db.entries.values())
    for param, field in (("report_id", "report_id"),
                         ("loss_claim_id", "loss_claim_id"),
                         ("consumer_id", "consumer_id"),
                         ("contributing_carrier_id", "contributing_carrier_id")):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e[field] == v]
    return paginate([ser_entry(e) for e in items])


@endpoint(["GET"], "/report-entries/<entry_id>", [PA, ECO, CU, CONS])
def get_report_entry(uid, role, entry_id):
    e = get_entry_or_404(entry_id)
    if role == CU:
        r = db.reports.get(e["report_id"])
        require_owner(uid, r["carrier_id"] if r else None)
    if role == CONS:
        require_owner(uid, e["consumer_id"])
    return success(ser_entry(e), 200)


@endpoint(["GET"], "/reports/<report_id>/entries", [PA, ECO, CU, CONS])
def list_report_entries_for_report(uid, role, report_id):
    r = get_report_or_404(report_id)
    if role == CU:
        require_owner(uid, r["carrier_id"])
    if role == CONS:
        require_owner(uid, r["consumer_id"])
    items = [e for e in sorted_by_creation(db.entries.values())
             if e["report_id"] == report_id]
    items.sort(key=lambda e: e["entry_sequence"])
    return paginate([ser_entry(e) for e in items])


@endpoint(["GET"], "/reports/<report_id>/adverse-action-notices", [PA, ECO, CU])
def list_report_notices(uid, role, report_id):
    r = get_report_or_404(report_id)
    if role == CU:
        require_owner(uid, r["carrier_id"])
    items = [n for n in sorted_by_creation(db.notices.values())
             if n["report_id"] == report_id]
    status = request.args.get("status")
    if status:
        items = [n for n in items if n["status"] == status]
    return paginate([ser_notice(n) for n in items])


@endpoint(["GET"], "/carriers/<carrier_id>/report-entries", [PA, ECO, CDS])
def list_carrier_report_entries(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    carrier_scoped_read_guard(uid, role, carrier_id)
    items = [e for e in sorted_by_creation(db.entries.values())
             if e["contributing_carrier_id"] == carrier_id]
    return paginate([ser_entry(e) for e in items])


# ===========================================================================
# Disputes
# ===========================================================================

@endpoint(["POST"], "/consumers/<consumer_id>/disputes", [CONS])
def create_dispute(uid, role, consumer_id):
    consumer = get_consumer_or_404(consumer_id)
    require_owner(uid, consumer_id)
    data = body_json()
    require_fields(data, ["loss_claim_id", "dispute_reason",
                          "dispute_statement", "expected_consumer_version"])
    claim = db.claims.get(data["loss_claim_id"])
    if claim is None:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                       "Referenced loss claim does not exist")
    if data["dispute_reason"] not in DISPUTE_REASONS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "dispute_reason out of enum")
    if not isinstance(data["dispute_statement"], str) or \
            len(data["dispute_statement"]) > 2000:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "dispute_statement must be at most 2000 characters")
    if data["expected_consumer_version"] != consumer["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_consumer_version does not match the consumer's current version")
    open_existing = [d for d in db.disputes.values()
                     if d["loss_claim_id"] == claim["id"]
                     and d["status"] in ("FILED", "UNDER_REINVESTIGATION")]
    if open_existing:
        raise ApiError(ERR_DISPUTE_ALREADY_OPEN, 409,
                       "A dispute against this claim is already open")
    if claim["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The disputed claim must be ACTIVE")

    rules = get_rules()
    now = db.now()
    due = now + timedelta(days=rules["reinvestigation_days"])
    dispute = {
        "id": db.new_id(),
        "consumer_id": consumer_id,
        "loss_claim_id": claim["id"],
        "dispute_reason": data["dispute_reason"],
        "dispute_statement": data["dispute_statement"],
        "filed_at": fmt_dt(now),
        "reinvestigation_due_at": fmt_dt(due),
        "resolved_at": None,
        "resolution_code": None,
        "resolution_notes": "",
        "status": "FILED",
        "_filed_dt": now,
        "_due_dt": due,
        "_overdue_flagged": False,
    }
    stamp_new(dispute)
    db.disputes[dispute["id"]] = dispute
    claim["status"] = "UNDER_DISPUTE"
    touch(claim)
    touch(consumer)
    add_event("DISPUTE_FILED", carrier_id=claim["contributing_carrier_id"],
              consumer_id=consumer_id,
              details={"dispute_id": dispute["id"], "claim_id": claim["id"]})
    return success(ser_dispute(dispute), 201)


@endpoint(["GET"], "/consumers/<consumer_id>/disputes", [PA, ECO, CONS])
def list_consumer_disputes(uid, role, consumer_id):
    get_consumer_or_404(consumer_id)
    consumer_scoped_guard(uid, role, consumer_id)
    items = [d for d in sorted_by_creation(db.disputes.values())
             if d["consumer_id"] == consumer_id]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    return paginate([ser_dispute(d) for d in items])


@endpoint(["GET"], "/disputes", [PA, ECO])
def list_disputes(uid, role):
    items = sorted_by_creation(db.disputes.values())
    for param, field in (("consumer_id", "consumer_id"),
                         ("loss_claim_id", "loss_claim_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[field] == v]
    return paginate([ser_dispute(d) for d in items])


@endpoint(["GET"], "/disputes/<dispute_id>", [PA, ECO, CONS])
def get_dispute(uid, role, dispute_id):
    d = get_dispute_or_404(dispute_id)
    if role == CONS:
        require_owner(uid, d["consumer_id"])
    return success(ser_dispute(d), 200)


def _check_dispute_actionable(d):
    if d["status"] not in ("FILED", "UNDER_REINVESTIGATION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Dispute is already resolved")
    if db.now() >= d["_due_dt"]:
        raise ApiError(ERR_DISPUTE_OVERDUE, 409,
                       "Logical clock at or past reinvestigation_due_at")


@endpoint(["POST"], "/disputes/<dispute_id>/begin-reinvestigation", [ECO])
def begin_reinvestigation(uid, role, dispute_id):
    d = get_dispute_or_404(dispute_id)
    if d["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a FILED dispute may begin reinvestigation")
    if db.now() >= d["_due_dt"]:
        raise ApiError(ERR_DISPUTE_OVERDUE, 409,
                       "Logical clock at or past reinvestigation_due_at")
    d["status"] = "UNDER_REINVESTIGATION"
    touch(d)
    claim = db.claims.get(d["loss_claim_id"])
    add_event("DISPUTE_REINVESTIGATED",
              carrier_id=claim["contributing_carrier_id"] if claim else None,
              consumer_id=d["consumer_id"],
              details={"dispute_id": d["id"]})
    return success(ser_dispute(d), 200)


@endpoint(["POST"], "/disputes/<dispute_id>/resolve", [ECO])
def resolve_dispute(uid, role, dispute_id):
    d = get_dispute_or_404(dispute_id)
    data = body_json()
    _check_dispute_actionable(d)
    require_fields(data, ["resolution_code"])
    code = data["resolution_code"]
    if code not in RESOLUTION_CODES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "resolution_code out of enum")
    notes = data.get("resolution_notes")
    if notes is None:
        notes = ""
    claim = db.claims.get(d["loss_claim_id"])

    if code == "AMENDED":
        fields = _validate_amendment_fields(data, prefix="corrected_")

    now = fmt_dt(db.now())
    d["resolved_at"] = now
    d["resolution_code"] = code
    d["resolution_notes"] = notes

    if code == "VERIFIED_ACCURATE":
        claim["status"] = "ACTIVE"
        touch(claim)
        d["status"] = "RESOLVED_VERIFIED"
    elif code == "DELETED":
        claim["status"] = "WITHDRAWN"
        touch(claim)
        d["status"] = "RESOLVED_DELETED"
        add_event("CLAIM_WITHDRAWN",
                  carrier_id=claim["contributing_carrier_id"],
                  consumer_id=d["consumer_id"],
                  details={"claim_id": claim["id"]})
    else:  # AMENDED
        _create_replacement_claim(claim, fields)
        d["status"] = "RESOLVED_AMENDED"

    touch(d)
    add_event("DISPUTE_RESOLVED",
              carrier_id=claim["contributing_carrier_id"] if claim else None,
              consumer_id=d["consumer_id"],
              details={"dispute_id": d["id"], "resolution_code": code})
    return success(ser_dispute(d), 200)


# ===========================================================================
# Adverse action notices
# ===========================================================================

def _outstanding_notices(carrier_id, exclude_id=None):
    return [n for n in db.notices.values()
            if n["carrier_id"] == carrier_id
            and n["status"] in ("DRAFT", "SENT")
            and n["id"] != exclude_id]


@endpoint(["POST"], "/carriers/<carrier_id>/adverse-action-notices", [CU])
def create_notice(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    require_owner(uid, carrier_id)
    data = body_json()
    require_fields(data, ["report_id", "action_type", "notice_reason_codes",
                          "report_influence_rank"])
    report = db.reports.get(data["report_id"])
    if report is None:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                       "Referenced report does not exist")
    if data["action_type"] not in NOTICE_ACTION_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "action_type out of enum")
    codes = data["notice_reason_codes"]
    if not isinstance(codes, list) or not (1 <= len(codes) <= 5) or \
            any(not isinstance(x, str) or not REASON_CODE_RE.match(x) for x in codes):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "notice_reason_codes must be 1-5 codes of ^[A-Z0-9-]{2,16}$")
    rank = data["report_influence_rank"]
    if not isinstance(rank, int) or isinstance(rank, bool) or not (1 <= rank <= 3):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "report_influence_rank must be in 1..3")
    rules = get_rules()
    if len(_outstanding_notices(carrier_id)) >= rules["max_outstanding_inquiries"]:
        raise ApiError(ERR_INQUIRY_CAP_EXCEEDED, 409,
                       "Outstanding adverse-action notices at or above the cap")
    deadline = db.now() + timedelta(days=rules["disclosure_window_days"])
    notice = {
        "id": db.new_id(),
        "carrier_id": carrier_id,
        "report_id": report["id"],
        "consumer_id": report["consumer_id"],
        "action_type": data["action_type"],
        "notice_reason_codes": codes,
        "report_influence_rank": rank,
        "disclosure_deadline": fmt_dt(deadline),
        "status": "DRAFT",
    }
    stamp_new(notice)
    db.notices[notice["id"]] = notice
    add_event("ADVERSE_ACTION_FILED", carrier_id=carrier_id,
              consumer_id=notice["consumer_id"],
              details={"notice_id": notice["id"], "report_id": report["id"]})
    return success(ser_notice(notice), 201)


@endpoint(["GET"], "/carriers/<carrier_id>/adverse-action-notices", [PA, ECO, CU])
def list_carrier_notices(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    carrier_scoped_read_guard(uid, role, carrier_id)
    items = [n for n in sorted_by_creation(db.notices.values())
             if n["carrier_id"] == carrier_id]
    status = request.args.get("status")
    if status:
        items = [n for n in items if n["status"] == status]
    return paginate([ser_notice(n) for n in items])


@endpoint(["GET"], "/adverse-action-notices", [PA, ECO])
def list_notices(uid, role):
    items = sorted_by_creation(db.notices.values())
    for param, field in (("carrier_id", "carrier_id"),
                         ("report_id", "report_id"),
                         ("consumer_id", "consumer_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [n for n in items if n[field] == v]
    return paginate([ser_notice(n) for n in items])


@endpoint(["GET"], "/adverse-action-notices/<notice_id>", [PA, ECO, CU, CONS])
def get_notice(uid, role, notice_id):
    n = get_notice_or_404(notice_id)
    if role == CU:
        require_owner(uid, n["carrier_id"])
    if role == CONS:
        require_owner(uid, n["consumer_id"])
    return success(ser_notice(n), 200)


@endpoint(["POST"], "/adverse-action-notices/<notice_id>/send", [CU])
def send_notice(uid, role, notice_id):
    n = get_notice_or_404(notice_id)
    require_owner(uid, n["carrier_id"])
    if n["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT notice may be sent")
    report = db.reports.get(n["report_id"])
    if report is None or report["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Referenced report is not in ISSUED status")
    rules = get_rules()
    if len(_outstanding_notices(n["carrier_id"], exclude_id=notice_id)) \
            >= rules["max_outstanding_inquiries"]:
        raise ApiError(ERR_INQUIRY_CAP_EXCEEDED, 409,
                       "Outstanding adverse-action notices at or above the cap")
    deadline = db.now() + timedelta(days=rules["disclosure_window_days"])
    n["status"] = "SENT"
    n["disclosure_deadline"] = fmt_dt(deadline)
    touch(n)
    add_event("ADVERSE_ACTION_SENT", carrier_id=n["carrier_id"],
              consumer_id=n["consumer_id"],
              details={"notice_id": n["id"]})
    return success(ser_notice(n), 200)


@endpoint(["POST"], "/adverse-action-notices/<notice_id>/acknowledge", [CONS])
def acknowledge_notice(uid, role, notice_id):
    n = get_notice_or_404(notice_id)
    require_owner(uid, n["consumer_id"])
    if n["status"] != "SENT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SENT notice may be acknowledged")
    n["status"] = "ACKNOWLEDGED"
    touch(n)
    add_event("ADVERSE_ACTION_ACKNOWLEDGED", carrier_id=n["carrier_id"],
              consumer_id=n["consumer_id"],
              details={"notice_id": n["id"]})
    return success(ser_notice(n), 200)


@endpoint(["POST"], "/adverse-action-notices/<notice_id>/cancel", [CU])
def cancel_notice(uid, role, notice_id):
    n = get_notice_or_404(notice_id)
    require_owner(uid, n["carrier_id"])
    if n["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT notice may be cancelled")
    n["status"] = "CANCELLED"
    touch(n)
    return success(ser_notice(n), 200)


# ===========================================================================
# Audit events
# ===========================================================================

@endpoint(["GET"], "/audit-events", [PA, ECO])
def list_audit_events(uid, role):
    items = sorted_by_creation(db.audit_events.values())
    for param, field in (("carrier_id", "carrier_id"),
                         ("consumer_id", "consumer_id"),
                         ("event_type", "event_type")):
            v = request.args.get(param)
            if v is not None:
                items = [e for e in items if e[field] == v]
    items = list(reversed(items))  # most recent first
    return paginate([serialize_event(e) for e in items])


@endpoint(["GET"], "/audit-events/<event_id>", [PA, ECO])
def get_audit_event(uid, role, event_id):
    e = db.audit_events.get(event_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Audit event not found")
    return success(serialize_event(e), 200)


@endpoint(["GET"], "/carriers/<carrier_id>/audit-events", [PA, ECO])
def list_carrier_audit_events(uid, role, carrier_id):
    get_carrier_or_404(carrier_id)
    items = [e for e in sorted_by_creation(db.audit_events.values())
             if e["carrier_id"] == carrier_id]
    event_type = request.args.get("event_type")
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]
    items = list(reversed(items))  # most recent first
    return paginate([serialize_event(e) for e in items])


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
