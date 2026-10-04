import re, uuid, random, string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import jsonify, request

ROLES = {"PlatformAdmin", "BrandManager", "StudioRep", "RetailerOps", "SafetyEngineer"}

class ApiErr(Exception):
    def __init__(self, eid, status, msg):
        super().__init__(msg); self.eid = eid; self.status = status; self.msg = msg

def req_meta():
    rid = "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond//1000:03d}Z"
    return {"api_request_id": rid, "api_request_timestamp": ts}

def ok_obj(data, code=200):
    return jsonify({"meta": req_meta(), "response_type": "object", "data": data}), code

def ok_list(items, code=200):
    return jsonify({"meta": req_meta(), "response_type": "array", "data": items}), code

def ok_list_page(items, limit, offset, total):
    meta = req_meta()
    meta["limit"] = limit; meta["offset"] = offset; meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200

def err_resp(e):
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": e.eid, "message": e.msg}}), e.status

def not_found(msg="resource not found"):
    raise ApiErr("ERR_NOT_FOUND", 404, msg)

def bad_req(msg="invalid request"):
    raise ApiErr("ERR_INVALID_REQUEST", 400, msg)

def invalid_state(msg="invalid state"):
    raise ApiErr("ERR_INVALID_STATE", 409, msg)

def parse_iso(s):
    if not isinstance(s, str): bad_req("expected ISO8601 string")
    v = s
    if v.endswith("Z"): v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        bad_req(f"invalid datetime: {s}")
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def round_half_up(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def half_up_dec(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def new_id():
    return str(uuid.uuid4())

def now_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond//1000:03d}Z"

def get_body():
    if request.data in (b"", b"null"):
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        bad_req("body must be JSON object")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        bad_req("body must be JSON object")
    return body

def get_pagination():
    q = request.args
    try:
        limit = int(q.get("limit", 10)); offset = int(q.get("offset", 0))
    except Exception:
        bad_req("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        bad_req("limit/offset out of range")
    return limit, offset

def paged(items):
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = get_pagination()
    total = len(items)
    return ok_list_page(items[offset:offset+limit], limit, offset, total)
