"""Domain helpers: common spine, input validation, pagination, clock, math."""
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, iso
from errors import err

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")

# ---- constants (PRD / scaffold) ----
TRANSFER_WINDOW_DAYS = 10
MATCH_WINDOW_DAYS = 60
APPEAL_WINDOW_DAYS = 30
TIER_RATES = ((1, 15, 2500), (16, 30, 5000), (31, None, 10000))
W_SEVERITY = {"CRITICAL": Decimal("1.0"), "MAJOR": Decimal("0.5"), "MINOR": Decimal("0.2")}
BASE_SANCTION = {"CRITICAL": 500000, "MAJOR": 100000, "MINOR": 25005}
REPEAT_MULTIPLIER = Decimal("1.5")
PROVEN_PRIOR_STATUSES = {"UPHELD", "REDUCED", "PAID"}
ASSIGN_OUT_STATES = {"NY", "CA"}
ORG_ID_TYPES = {"TAX_ID", "CHARTER_NUMBER", "LEI"}
MEMBER_TYPES = {"ORIGINATOR", "SERVICER", "INVESTOR", "SUBSERVICER", "CUSTODIAN"}
ROLE_SCOPES = {"REGISTRATION", "TRANSFER", "FORECLOSURE", "ALL"}
TRANSFER_TYPES = {"BENEFICIAL", "SERVICING", "BOTH"}
FIELD_NAMES = {"MIN", "CURRENT_SERVICER", "CURRENT_INVESTOR", "PROPERTY_STATE", "CLOSING_DATE"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}
INACTIVE_LOAN_STATUSES = {"INACTIVE_ASSIGNED_OUT", "INACTIVE_TERMINATED", "INACTIVE_SATISFIED"}


# ---- spine ----

def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return iso(store.clock)


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def base_record():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


# ---- parsing / validation ----

def get_body(required=(), optional=()):
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for field in required:
        if field not in body or body[field] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body


def req_str(body, field):
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field):
    v = body[field]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def parse_iso(value, field):
    if not isinstance(value, str) or not _ISO_RE.match(value):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 UTC timestamp")
    text = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} is not a valid timestamp")


def req_iso(body, field):
    return parse_iso(body[field], field)


def opt_iso(body, field):
    if field not in body or body[field] is None:
        return None
    return parse_iso(body[field], field)


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def opt_number(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    return Decimal(str(v))


# ---- pagination ----

def paginate(items):
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be non-negative")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def sorted_items(mapping):
    return sorted(mapping.values(), key=lambda r: (r["created_at"], r["id"]))


# ---- lookups ----

def find_member(mid):
    m = store.members.get(mid)
    if m is None:
        raise err("ERR_MEMBER_NOT_FOUND", f"Member {mid} not found")
    return m


def find_signer(sid):
    s = store.signers.get(sid)
    if s is None:
        raise err("ERR_SIGNER_NOT_FOUND", f"Signer {sid} not found")
    return s


def find_signer_under(member_id, signer_id):
    s = store.signers.get(signer_id)
    if s is None or s["member_id"] != member_id:
        raise err("ERR_SIGNER_NOT_FOUND", f"Signer {signer_id} not found for member {member_id}")
    return s


def find_loan(lid):
    l = store.loans.get(lid)
    if l is None:
        raise err("ERR_LOAN_NOT_FOUND", f"Loan {lid} not found")
    return l


def find_transfer(tid):
    t = store.transfers.get(tid)
    if t is None:
        raise err("ERR_TRANSFER_NOT_FOUND", f"Transfer {tid} not found")
    return t


def find_match(mid_):
    m = store.matches.get(mid_)
    if m is None:
        raise err("ERR_TRANSFER_NOT_FOUND", f"TransferMatch {mid_} not found")
    return m


def find_review(rid):
    r = store.reviews.get(rid)
    if r is None:
        raise err("ERR_REVIEW_NOT_FOUND", f"QA review {rid} not found")
    return r


def find_finding(fid):
    f = store.findings.get(fid)
    if f is None:
        raise err("ERR_FINDING_NOT_FOUND", f"Finding {fid} not found")
    return f


def find_finding_under(review_id, finding_id):
    f = store.findings.get(finding_id)
    if f is None or f["review_id"] != review_id:
        raise err("ERR_FINDING_NOT_FOUND", f"Finding {finding_id} not found for review {review_id}")
    return f


def find_report(rid):
    r = store.reports.get(rid)
    if r is None:
        raise err("ERR_REPORT_NOT_FOUND", f"Annual report {rid} not found")
    return r


def find_sanction(sid):
    s = store.sanctions.get(sid)
    if s is None:
        raise err("ERR_SANCTION_NOT_FOUND", f"Sanction {sid} not found")
    return s


def find_run(rid):
    r = store.runs.get(rid)
    if r is None:
        raise err("ERR_RUN_NOT_FOUND", f"Reconciliation run {rid} not found")
    return r


def find_exception(eid):
    e = store.exceptions.get(eid)
    if e is None:
        raise err("ERR_EXCEPTION_NOT_FOUND", f"SOR exception {eid} not found")
    return e


# ---- calculations ----

def luhn_check_digit(payload: str) -> int:
    total = 0
    weight = 2
    for ch in reversed(payload):
        d = int(ch) * weight
        if d > 9:
            d -= 9
        total += d
        weight = 1 if weight == 2 else 2
    return (10 - (total % 10)) % 10


def compute_days_late(clock_dt, effective_dt) -> int:
    delta = clock_dt.date() - effective_dt.date()
    return max(0, delta.days - TRANSFER_WINDOW_DAYS)


def compute_late_fee(days_late: int) -> int:
    fee = 0
    for lo, hi, rate in TIER_RATES:
        if days_late >= lo:
            upper = days_late if hi is None else min(days_late, hi)
            fee += (upper - lo + 1) * rate
    return fee


def round4(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round0_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def member_sample_loans(member_id):
    loans = [l for l in store.loans.values() if l["registering_member_id"] == member_id]
    return sorted(loans, key=lambda l: l["serial"])


def compute_discrepancy(review):
    findings = [f for f in store.findings.values() if f["review_id"] == review["id"]]
    sample = member_sample_loans(review["member_id"])
    sample_size = len(sample)
    weighted = sum(W_SEVERITY[f["severity"]] for f in findings)
    if sample_size == 0:
        score = Decimal("0")
    else:
        score = weighted / Decimal(sample_size)
    return sample_size, round4(score)


def sanction_totals(member_id, review_id, abatement: Decimal):
    priors = [s for s in store.sanctions.values()
              if s["member_id"] == member_id and s["status"] in PROVEN_PRIOR_STATUSES]
    multiplier = REPEAT_MULTIPLIER if priors else Decimal("1.0")
    findings = [f for f in store.findings.values() if f["review_id"] == review_id]
    findings.sort(key=lambda f: (f["created_at"], f["id"]))
    total = 0
    for f in findings:
        line = Decimal(BASE_SANCTION[f["severity"]]) * multiplier * abatement
        total += round0_int(line)
    return total, len(findings)


def year_bounds(year: int):
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)
    return start, end


def compute_report_figures(member_id, report_year):
    start, end = year_bounds(report_year)
    transfers = [t for t in store.transfers.values()
                 if t["from_member_id"] == member_id and t["status"] == "CONFIRMED"
                 and start <= parse_iso(t["effective_date"], "effective_date") <= end]
    n = len(transfers)
    if n == 0:
        reporting_rate = 1.0
        reporting_rate_amt = 1.0
    else:
        on_time = [t for t in transfers if t["days_late"] == 0]
        reporting_rate = round4(Decimal(len(on_time)) / Decimal(n))
        total_amt = sum(store.loans[t["loan_id"]]["loan_amount_cents"] for t in transfers)
        if total_amt == 0:
            reporting_rate_amt = 1.0
        else:
            on_time_amt = sum(store.loans[t["loan_id"]]["loan_amount_cents"] for t in on_time)
            reporting_rate_amt = round4(Decimal(on_time_amt) / Decimal(total_amt))

    settled = [r for r in store.reviews.values()
               if r["member_id"] == member_id and r["status"] == "SETTLED"]
    if settled:
        latest = max(settled, key=lambda r: (r["settled_at"] or "", _neg_created(r)))
        discrepancy_rate = float(latest["discrepancy_score"])
    else:
        discrepancy_rate = 0.0

    open_exceptions = len([m for m in store.matches.values()
                           if m["reported_by_member_id"] == member_id
                           and m["status"] in ("PENDING", "EXPIRED")])

    score = (Decimal("100")
             - Decimal(60) * (Decimal("1") - Decimal(str(reporting_rate)))
             - Decimal(40) * min(Decimal("1"), Decimal(str(discrepancy_rate)))
             - Decimal(2) * Decimal(min(open_exceptions, 10)))
    if score < 0:
        score = Decimal("0")
    if score > 100:
        score = Decimal("100")
    standing_score = round2(score)
    if standing_score >= 80.0:
        band = "GOOD_STANDING"
    elif standing_score >= 60.0:
        band = "PROBATION"
    else:
        band = "DISENGAGEMENT_ELIGIBLE"
    return {
        "reporting_rate": reporting_rate,
        "reporting_rate_amount_weighted": reporting_rate_amt,
        "discrepancy_rate": discrepancy_rate,
        "open_exceptions": open_exceptions,
        "standing_score": standing_score,
        "standing_band": band,
    }


class _NegCreated:
    """Sort helper: earlier created_at ranks higher on settled_at ties."""

    def __init__(self, created_at):
        self.created_at = created_at

    def __lt__(self, other):
        return self.created_at > other.created_at

    def __eq__(self, other):
        return self.created_at == other.created_at


def _neg_created(review):
    return _NegCreated(review["created_at"])


def new_exception(run_id, loan_id, exc_type, detail):
    rec = base_record()
    rec.update({
        "run_id": run_id,
        "loan_id": loan_id,
        "exception_type": exc_type,
        "detail": detail,
        "status": "OPEN",
    })
    store.exceptions[rec["id"]] = rec
    return rec


def maybe_complete_run(run):
    """Resolve-driven completion: OPEN -> COMPLETED when no OPEN exceptions remain."""
    if run["status"] != "OPEN":
        return
    open_exc = [e for e in store.exceptions.values()
                if e["run_id"] == run["id"] and e["status"] == "OPEN"]
    if not open_exc:
        run["status"] = "COMPLETED"
        touch(run)


def run_timed_evaluations():
    """Clock-driven transitions (PRD §2.4): due terminations and match expiry."""
    clock = store.clock
    for m in store.members.values():
        if m["status"] == "TERMINATION_PENDING" and m.get("_term_dt") is not None \
                and clock >= m["_term_dt"]:
            finalize_termination(m)
    for match in store.matches.values():
        if match["status"] == "PENDING":
            transfer = store.transfers.get(match["transfer_id"])
            if transfer is None:
                continue
            eff = parse_iso(transfer["effective_date"], "effective_date")
            if (clock.date() - eff.date()).days > MATCH_WINDOW_DAYS:
                match["status"] = "EXPIRED"
                touch(match)


def finalize_termination(member):
    member["status"] = "TERMINATED"
    touch(member)
    for s in store.signers.values():
        if s["member_id"] == member["id"] and s["status"] == "ACTIVE":
            s["status"] = "REVOKED"
            touch(s)
