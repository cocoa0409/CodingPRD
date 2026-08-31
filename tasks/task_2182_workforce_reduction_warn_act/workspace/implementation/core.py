"""Core primitives: errors, response envelope, logical clock, in-memory store."""
import random
import re
import threading
import time
import string
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import jsonify

getcontext().prec = 60

UTC = timezone.utc
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload or query string is malformed.",
    "ERR_PLAN_NOT_FOUND": "No ReductionPlan with the referenced id.",
    "ERR_SITE_NOT_FOUND": "No Site with the referenced id.",
    "ERR_EMPLOYEE_NOT_FOUND": "No Employee with the referenced id.",
    "ERR_SELECTION_NOT_FOUND": "No Selection with the referenced id.",
    "ERR_ANALYSIS_NOT_FOUND": "No AdverseImpactAnalysis with the referenced id.",
    "ERR_DISCLOSURE_NOT_FOUND": "No OwbpaDisclosure with the referenced id.",
    "ERR_NOTICE_NOT_FOUND": "No WarnNotice with the referenced id.",
    "ERR_OFFER_NOT_FOUND": "No SeveranceOffer with the referenced id.",
    "ERR_RESTRICTION_NOT_FOUND": "No PositionRestriction with the referenced id.",
    "ERR_WARN_RULE_NOT_FOUND": "No WarnRule configured for the requested jurisdiction.",
    "ERR_NOT_OFFER_RECIPIENT": "The acting employee is not the recipient of this offer.",
    "ERR_SEGREGATION_OF_DUTIES": "The submitter of a plan may not render its legal decision.",
    "ERR_INVALID_PLAN_STATE": "The plan's state forbids the requested transition.",
    "ERR_INVALID_SELECTION_STATE": "The selection's state forbids the requested transition.",
    "ERR_INVALID_ANALYSIS_STATE": "The analysis' state forbids the requested transition.",
    "ERR_INVALID_NOTICE_STATE": "The notice's state forbids the requested transition.",
    "ERR_INVALID_OFFER_STATE": "The offer's state forbids the requested transition.",
    "ERR_INVALID_RESTRICTION_STATE": "The restriction's state forbids the requested transition.",
    "ERR_STALE_PLAN_VERSION": "expected_plan_version does not match the plan's current version.",
    "ERR_STALE_SELECTION_VERSION": "expected_selection_version does not match the selection's current version.",
    "ERR_CRITERIA_NOT_LOCKED": "The plan's selection criteria are not locked.",
    "ERR_CRITERIA_WEIGHT_INVALID": "selection_criteria weights must sum to 100 with unique codes.",
    "ERR_CRITERION_SCORE_MISMATCH": "criterion_scores codes do not match the plan's locked criteria.",
    "ERR_IMPACT_ANALYSIS_NOT_CLEARED": "The plan's latest adverse-impact analysis is not CLEARED.",
    "ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA": "The selection pool cannot support the statistic.",
    "ERR_OWBPA_DISCLOSURE_MISSING": "The plan carries no OWBPA disclosure.",
    "ERR_OWBPA_DISCLOSURE_STALE": "The plan's OWBPA disclosure is stale.",
    "ERR_NOTICE_NOT_DELIVERED": "The individual notice has not been delivered.",
    "ERR_WARN_NOTICE_REQUIRED": "A triggered site has no issued WARN notice for this plan.",
    "ERR_NOTICE_PERIOD_INSUFFICIENT": "The individual notice period is shorter than the site requires.",
    "ERR_CONSIDERATION_PERIOD_EXPIRED": "The consideration period has expired.",
    "ERR_REVOCATION_WINDOW_CLOSED": "The revocation window has closed.",
    "ERR_OFFER_WINDOW_CONFLICT": "Another offer for this employee still occupies its blocking window.",
    "ERR_WARN_WINDOW_COLLISION": "The proposed separation date falls inside a frozen aggregation window.",
    "ERR_DUPLICATE_SELECTION": "The employee already holds a live selection in this plan.",
    "ERR_WARN_CONTENT_INCOMPLETE": "content_codes omits a code the applied rule requires.",
    "ERR_WARN_RULE_ALREADY_EXISTS": "A WarnRule already exists for this jurisdiction and state code.",
    "ERR_WARN_WORKFORCE_EMPTY": "The workforce denominator under the applied rule is zero.",
    "ERR_OFFER_REISSUE_LIMIT": "The offer has already been issued three times.",
    "ERR_PLAN_NOT_APPROVED": "The plan is not APPROVED.",
    "ERR_SCRIPT_JURISDICTION_MISMATCH": "The manager script does not satisfy the jurisdiction's requirements.",
    "ERR_BACKFILL_RESTRICTED": "A rehire restriction covers this site and job title.",
    "ERR_SEVERANCE_BUDGET_EXCEEDED": "Issuing this offer would exceed the plan's severance budget.",
}


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_last_ms = [0]
_ts_lock = threading.Lock()


def _monotonic_ms():
    """Wall-clock milliseconds that never repeat, so created_at/updated_at
    are strictly ordered even when two writes land in the same millisecond."""
    with _ts_lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ms[0]:
            ms = _last_ms[0] + 1
        _last_ms[0] = ms
        return ms


def now_iso():
    return iso_ms(_EPOCH + timedelta(milliseconds=_monotonic_ms()))


def iso_ms(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Strict YYYY-MM-DD -> datetime.date, or None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def date_str(d):
    return None if d is None else d.isoformat()


def date_at_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO-8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime(year, month, day, hh, mm, ss, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        dt = dt - sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return dt


def completed_years(birth, anchor):
    """Whole completed years between two dates."""
    if birth is None or anchor is None:
        return None
    years = anchor.year - birth.year
    if (anchor.month, anchor.day) < (birth.month, birth.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def num(value):
    """Serialise a Decimal as a JSON number, integral values as ints."""
    if value is None:
        return None
    d = D(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, http_status, message=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or _DEFAULT_MESSAGES.get(error_id, error_id),
        },
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.plans = {}
        self.sites = {}
        self.employees = {}
        self.selections = {}
        self.warn_rules = {}
        self.analyses = {}
        self.disclosures = {}
        self.notices = {}
        self.offers = {}
        self.restrictions = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1


def apply_changes(rec, changes):
    """Assign changed fields; touch and return True when anything moved."""
    dirty = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            dirty = True
    if dirty:
        touch(rec)
    return dirty


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_rows(rows):
    return sorted(rows, key=lambda r: r["_seq"])
