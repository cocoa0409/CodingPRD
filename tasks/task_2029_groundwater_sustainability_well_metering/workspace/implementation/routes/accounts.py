"""WaterUserAccount endpoints."""
from flask import Blueprint, request

from db import store, new_id, stamp, touch
from errors import err
from middleware import ALL_ROLES, require_roles, body, paginate, sort_default
from response import ok, ok_list
from serializers import ser_account
from services import cascade_close_account
from util import D0, round3, to_decimal, dp_ok, is_int

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = ("AGRICULTURAL", "MUNICIPAL", "INDUSTRIAL", "DOMESTIC")
ACCOUNT_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
VALID_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "CLOSED"),
    ("SUSPENDED", "CLOSED"),
}


@bp.post("/water-user-accounts")
def create_account():
    require_roles("WaterMaster")
    b = body()
    holder = b.get("holder_name")
    atype = b.get("account_type")
    base_raw = b.get("base_allocation_af")
    if not isinstance(holder, str):
        raise err("ERR_INVALID_REQUEST", "holder_name is required and must be a string")
    if atype not in ACCOUNT_TYPES:
        raise err("ERR_INVALID_REQUEST", "account_type must be one of AGRICULTURAL, MUNICIPAL, INDUSTRIAL, DOMESTIC")
    base = to_decimal(base_raw)
    if base is None or base <= 0 or not dp_ok(base, 3):
        raise err("ERR_INVALID_REQUEST", "base_allocation_af must be > 0 with at most 3 decimal places")
    a = {
        "id": new_id(),
        "holder_name": holder,
        "account_type": atype,
        "base_allocation_af": round3(base),
        "status": "ACTIVE",
        "current_water_year": store.clock.year,
        "extracted_af_ytd": D0,
        "pending_extraction_af": D0,
        "credit_balance_af": D0,
        "transfer_out_af_ytd": D0,
        "transfer_reserved_af": D0,
        "penalty_balance_cents": 0,
    }
    stamp(a)
    store.accounts[a["id"]] = a
    return ok(ser_account(a), status=201)


@bp.get("/water-user-accounts")
def list_accounts():
    require_roles(*ALL_ROLES)
    items = list(store.accounts.values())
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    at = request.args.get("account_type")
    if at is not None:
        items = [a for a in items if a["account_type"] == at]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_account(a) for a in page], pg)


@bp.get("/water-user-accounts/<account_id>")
def get_account(account_id):
    require_roles(*ALL_ROLES)
    a = store.accounts.get(account_id)
    if a is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "No WaterUserAccount with the given id")
    return ok(ser_account(a))


@bp.patch("/water-user-accounts/<account_id>")
def update_account(account_id):
    require_roles("WaterMaster")
    b = body()
    # Shape (priority 4) before existence (priority 5).
    if "expected_account_version" not in b:
        raise err("ERR_INVALID_REQUEST", "expected_account_version is required")
    expected = b["expected_account_version"]
    if not is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_account_version must be an integer")
    has_status = "status" in b and b["status"] is not None
    new_status = b.get("status")
    if has_status and new_status not in ACCOUNT_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status must be one of ACTIVE, SUSPENDED, CLOSED")
    has_base = "base_allocation_af" in b and b["base_allocation_af"] is not None
    new_base = None
    if has_base:
        new_base = to_decimal(b["base_allocation_af"])
        if new_base is None or new_base <= 0 or not dp_ok(new_base, 3):
            raise err("ERR_INVALID_REQUEST", "base_allocation_af must be > 0 with at most 3 decimal places")
    a = store.accounts.get(account_id)
    if a is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "No WaterUserAccount with the given id")
    # Optimistic concurrency (SCAFFOLD §1.2.1).
    if expected != a["version"]:
        raise err("ERR_STALE_VERSION", "expected_account_version does not match the account's current version")
    if has_status:
        cur = a["status"]
        if (cur, new_status) not in VALID_TRANSITIONS:
            raise err("ERR_ACCOUNT_NOT_ACTIVE", f"Invalid account status transition {cur} -> {new_status}")
        if new_status == "CLOSED":
            inbound = any(t["buyer_account_id"] == a["id"] and t["status"] == "ACCEPTED"
                          for t in store.transfers.values())
            appealed = any(p["account_id"] == a["id"] and p["status"] == "APPEALED"
                           for p in store.assessments.values())
            if inbound or appealed:
                raise err("ERR_ACCOUNT_NOT_ACTIVE",
                          "Account has inbound ACCEPTED transfers or APPEALED penalty assessments")
    if not has_status and not has_base:
        return ok(ser_account(a))  # no-op: no mutation, no version bump
    if has_base:
        a["base_allocation_af"] = round3(new_base)
    if has_status:
        a["status"] = new_status
        if new_status == "CLOSED":
            cascade_close_account(a)
    a["version"] += 1
    touch(a)
    return ok(ser_account(a))
