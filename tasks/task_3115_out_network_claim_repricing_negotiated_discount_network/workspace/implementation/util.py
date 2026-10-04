"""Shared helpers: request parsing, pagination, serialization."""
import uuid
from datetime import datetime, timezone, timedelta

from flask import request

import db
import errors


def new_id():
    return str(uuid.uuid4())


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return b


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"Missing or invalid field: {field}")
    return v


def opt_str(b, field):
    v = b.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.invalid_request(f"Invalid field: {field}")
    return v


def req_int(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Missing or invalid field: {field}")
    return v


def opt_int(b, field):
    v = b.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Invalid field: {field}")
    return v


def req_num(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Missing or invalid field: {field}")
    return v


def opt_num(b, field):
    v = b.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Invalid field: {field}")
    return v


def opt_bool(b, field):
    v = b.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Invalid field: {field}")
    return v


def req_enum(b, field, choices):
    v = req_str(b, field)
    if v not in choices:
        raise errors.invalid_request(f"Invalid value for {field}")
    return v


def req_datetime(b, field):
    v = req_str(b, field)
    dt = parse_datetime(v)
    if dt is None:
        raise errors.invalid_request(f"Invalid datetime for {field}")
    return dt


def parse_datetime(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        # try date only
        try:
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None


def paginate_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("Invalid limit")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("Invalid offset")
        if offset < 0:
            offset = 0
    return limit, offset


def sort_and_page(records, limit, offset):
    """records: list of dicts each with created_at string; sorted ascending."""
    records = sorted(
        records,
        key=lambda r: (r.get("_created_at_dt") is None,
                       r.get("_created_at_dt") or r.get("created_at") or "",
                       r.get("_seq", 0),
                       r.get("id") or ""))
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_common(rec, include_common=True):
    out = dict(rec)
    if include_common:
        out["created_at"] = db.fmt(rec.get("_created_at_dt"))
        out["updated_at"] = db.fmt(rec.get("_updated_at_dt"))
    else:
        out["created_at"] = db.fmt(rec.get("_created_at_dt"))
    out.pop("_created_at_dt", None)
    out.pop("_updated_at_dt", None)
    return out


def ser_payer_client(p):
    out = ser_common(p)
    out["status"] = p["status"]
    return out


def ser_policy(p):
    return ser_common(p)


def ser_provider(p):
    return ser_common(p)


def ser_agreement(a):
    out = ser_common(a)
    out["effective_start"] = db.fmt(a.get("_effective_start_dt"))
    out["effective_end"] = db.fmt(a.get("_effective_end_dt"))
    out.pop("_effective_start_dt", None)
    out.pop("_effective_end_dt", None)
    return out


def ser_medicare(m):
    return ser_common(m, include_common=False)


def ser_ucr(u):
    return ser_common(u, include_common=False)


def ser_claim(c):
    out = ser_common(c)
    out["service_date"] = db.fmt(c.get("_service_date_dt"))
    out.pop("_service_date_dt", None)
    return out


def ser_claim_line(l):
    return ser_common(l)


def ser_determination(d):
    return ser_common(d)


def ser_negotiation_case(n):
    return ser_common(n)


def ser_settlement(s):
    out = ser_common(s)
    out["payer_signed_at"] = db.fmt(s.get("_payer_signed_at_dt"))
    out["provider_signed_at"] = db.fmt(s.get("_provider_signed_at_dt"))
    out.pop("_payer_signed_at_dt", None)
    out.pop("_provider_signed_at_dt", None)
    return out


def ser_open_negotiation(o):
    out = ser_common(o)
    out["initiated_at"] = db.fmt(o.get("_initiated_at_dt"))
    out["expires_at"] = db.fmt(o.get("_expires_at_dt"))
    out.pop("_initiated_at_dt", None)
    out.pop("_expires_at_dt", None)
    return out


def ser_idr(i):
    out = ser_common(i)
    out["submitted_at"] = db.fmt(i.get("_submitted_at_dt"))
    out.pop("_submitted_at_dt", None)
    return out


def ser_appeal(a):
    out = ser_common(a)
    out["appeal_window_deadline"] = db.fmt(a.get("_appeal_window_deadline_dt"))
    out.pop("_appeal_window_deadline_dt", None)
    return out


def ser_feed_batch(f):
    out = ser_common(f)
    out["received_at"] = db.fmt(f.get("_received_at_dt"))
    out["sla_due_at"] = db.fmt(f.get("_sla_due_at_dt"))
    out["processed_at"] = db.fmt(f.get("_processed_at_dt"))
    out.pop("_received_at_dt", None)
    out.pop("_sla_due_at_dt", None)
    out.pop("_processed_at_dt", None)
    return out


def ser_fee_invoice(f):
    return ser_common(f)


def ser_transparency_report(t):
    return ser_common(t)


def touch(rec):
    """Bump version and updated_at using the logical clock."""
    rec["version"] = rec.get("version", 1) + 1
    rec["_updated_at_dt"] = db.now()
