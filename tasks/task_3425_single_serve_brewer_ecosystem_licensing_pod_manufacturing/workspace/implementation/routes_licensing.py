"""License agreements: create, read, list, transition, amend; plus the
suspension / reinstatement / termination cascades shared with quality audits."""
from datetime import datetime
from flask import Blueprint

from store import db
from helpers import (
    ApiError, body, created, find, init_common, list_ok, need, ok, touch,
    parse_date_val, require_roles, v_bool, v_enum, v_int, v_str, err400,
)
from calc import eval_agreement_lazy, latest_audit
from serializers import agreement_out

bp = Blueprint("licensing", __name__)

AGREEMENT_TARGETS = ("ACTIVE", "SUSPENDED", "TERMINATED")

_DECLARED = {
    ("DRAFT", "ACTIVE"), ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"), ("SUSPENDED", "TERMINATED"),
    ("DRAFT", "TERMINATED"),
}


def v_tiers(b, field):
    val = b.get(field, None)
    if not isinstance(val, list) or len(val) == 0:
        err400("royalty_tiers must be a non-empty array")
    tiers = []
    prev = None
    for i, t in enumerate(val):
        if not isinstance(t, dict):
            err400("royalty_tiers entries must be objects")
        if "up_to_units" not in t or "millicents_per_pod" not in t:
            err400("royalty_tiers entries require up_to_units and millicents_per_pod")
        up = t["up_to_units"]
        rate = t["millicents_per_pod"]
        if up is not None and (isinstance(up, bool) or not isinstance(up, int)):
            err400("up_to_units must be an integer or null")
        if isinstance(rate, bool) or not isinstance(rate, int):
            err400("millicents_per_pod must be an integer")
        if up is None:
            if i != len(val) - 1:
                err400("only the trailing bracket may carry a null up_to_units")
        else:
            if prev is not None and up <= prev:
                err400("up_to_units boundaries must be strictly ascending")
            prev = up
        tiers.append({"up_to_units": up, "millicents_per_pod": rate})
    if tiers[-1]["up_to_units"] is not None:
        err400("royalty_tiers must end with exactly one null open bracket")
    return tiers


def _chain_root(agr):
    seen = set()
    cur = agr
    while cur.get("amendment_of_id"):
        nxt_id = cur["amendment_of_id"]
        if nxt_id in seen:
            break
        seen.add(nxt_id)
        nxt = db["agreements"].get(nxt_id)
        if nxt is None:
            break
        cur = nxt
    return cur["id"]


def territory_conflict(brand_id, terr, start, end, self_id, self_root):
    """Closed-interval [start, end] overlap at day granularity against ACTIVE
    or SUSPENDED agreements of the same brand+territory; amendment-chain
    members are exempt."""
    for other in db["agreements"].values():
        if other["id"] == self_id:
            continue
        if other["brand_id"] != brand_id or other["territory_code"] != terr:
            continue
        eval_agreement_lazy(other, persist=True)
        if other["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if self_root is not None and _chain_root(other) == self_root:
            continue
        o_start = datetime.strptime(other["effective_start"], "%Y-%m-%d").date()
        o_end = datetime.strptime(other["effective_end"], "%Y-%m-%d").date()
        if start <= o_end and o_start <= end:
            return True
    return False


def _cancel_reserved_runs_of(variety_ids):
    for r in db["runs"].values():
        if r["variety_id"] in variety_ids and r["status"] == "RESERVED":
            r["status"] = "CANCELLED"
            touch(r)


def suspend_cascade(agr):
    """ACTIVE -> SUSPENDED side effects: brand's ACTIVE varieties ->
    SUPPLY_BLOCKED; their RESERVED runs -> CANCELLED (IN_PROGRESS untouched)."""
    agr["status"] = "SUSPENDED"
    touch(agr)
    affected = [v for v in db["varieties"].values()
                if v["brand_id"] == agr["brand_id"] and v["status"] == "ACTIVE"]
    for v in affected:
        v["status"] = "SUPPLY_BLOCKED"
        touch(v)
    _cancel_reserved_runs_of({v["id"] for v in affected})


def _reinstate_cascade(agr):
    agr["status"] = "ACTIVE"
    touch(agr)
    for v in db["varieties"].values():
        if v["brand_id"] == agr["brand_id"] and v["status"] == "SUPPLY_BLOCKED":
            v["status"] = "ACTIVE"
            touch(v)


def _terminate_cascade(agr, from_status):
    agr["status"] = "TERMINATED"
    touch(agr)
    if from_status == "DRAFT":
        return
    targets = {"ACTIVE", "SUPPLY_BLOCKED", "PHASE_OUT"} if from_status == "ACTIVE" \
        else {"SUPPLY_BLOCKED", "PHASE_OUT"}
    vs = [v for v in db["varieties"].values()
          if v["brand_id"] == agr["brand_id"] and v["status"] in targets]
    for v in vs:
        v["status"] = "DELISTED"
        touch(v)
    _cancel_reserved_runs_of({v["id"] for v in vs})


def agreement_write_gate(agr):
    """Agreement-scoped writes: lazy expiry first; an agreement that is (or
    lazily becomes) EXPIRED rejects the write with ERR_AGREEMENT_EXPIRED."""
    eval_agreement_lazy(agr, persist=True)
    if agr["status"] == "EXPIRED":
        raise ApiError("ERR_AGREEMENT_EXPIRED", 409,
                       "Agreement-scoped write after lazy expiry")


@bp.post("/license-agreements")
@require_roles("LicensingManager")
def create_agreement():
    b = body()
    raw_brand = b.get("brand_id")
    if isinstance(raw_brand, str) and raw_brand not in db["brands"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Brand not found: %s" % raw_brand)
    brand_id = v_str(b, "brand_id")
    brand = db["brands"][brand_id]
    terr = v_str(b, "territory_code")
    start = parse_date_val(need(b, "effective_start"))
    end = parse_date_val(need(b, "effective_end"))
    tiers = v_tiers(b, "royalty_tiers")
    qmin = v_int(b, "quality_min_cup_score")
    excl = v_bool(b, "exclusive")
    if start > end:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "effective_start must fall on or before effective_end")
    if territory_conflict(brand_id, terr, start, end, self_id=None, self_root=None):
        raise ApiError("ERR_TERRITORY_WINDOW_CONFLICT", 409,
                       "Territory window overlaps an ACTIVE/SUSPENDED agreement")
    if brand["kind"] != "LICENSED":
        raise ApiError("ERR_BRAND_NOT_LICENSED", 422,
                       "License agreement references a brand whose kind is not LICENSED")
    agr = init_common({
        "brand_id": brand_id, "territory_code": terr,
        "effective_start": start.isoformat(), "effective_end": end.isoformat(),
        "royalty_tiers": tiers, "quality_min_cup_score": qmin,
        "exclusive": excl, "amendment_of_id": None, "status": "DRAFT",
    })
    db["agreements"][agr["id"]] = agr
    return created(agreement_out(agr))


@bp.get("/license-agreements/<rid>")
@require_roles("LicensingManager", "QualityAuditor", "FinanceAnalyst")
def get_agreement(rid):
    agr = find("agreements", rid)
    eval_agreement_lazy(agr, persist=False)
    return ok(agreement_out(agr))


@bp.get("/license-agreements")
@require_roles("LicensingManager", "FinanceAnalyst")
def list_agreements():
    from flask import request
    items = list(db["agreements"].values())
    for a in items:
        eval_agreement_lazy(a, persist=False)
    f_brand = request.args.get("brand_id")
    f_amend = request.args.get("amendment_of_id")
    f_status = request.args.get("status")
    f_terr = request.args.get("territory_code")
    if f_brand is not None:
        items = [a for a in items if a["brand_id"] == f_brand]
    if f_amend is not None:
        items = [a for a in items if a["amendment_of_id"] == f_amend]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    if f_terr is not None:
        items = [a for a in items if a["territory_code"] == f_terr]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return list_ok(items, agreement_out)


@bp.post("/license-agreements/<rid>/transition")
@require_roles("LicensingManager")
def transition_agreement(rid):
    agr = find("agreements", rid)
    b = body()
    target = v_enum(b, "target_state", AGREEMENT_TARGETS)
    agreement_write_gate(agr)
    if (agr["status"], target) not in _DECLARED:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No declared transition from %s to %s" % (agr["status"], target))
    if agr["status"] == "DRAFT" and target == "ACTIVE":
        start = datetime.strptime(agr["effective_start"], "%Y-%m-%d").date()
        end = datetime.strptime(agr["effective_end"], "%Y-%m-%d").date()
        if start > end:
            raise ApiError("ERR_INVALID_WINDOW", 422,
                           "effective_start must fall on or before effective_end")
        if territory_conflict(agr["brand_id"], agr["territory_code"], start, end,
                              self_id=agr["id"], self_root=_chain_root(agr)):
            raise ApiError("ERR_TERRITORY_WINDOW_CONFLICT", 409,
                           "Territory window overlaps an ACTIVE/SUSPENDED agreement")
        brand = db["brands"].get(agr["brand_id"])
        if brand is None or brand["kind"] != "LICENSED":
            raise ApiError("ERR_BRAND_NOT_LICENSED", 422,
                           "License agreement references a brand whose kind is not LICENSED")
        from_status = "DRAFT"
        agr["status"] = "ACTIVE"
        touch(agr)
        if agr["amendment_of_id"]:
            src = db["agreements"].get(agr["amendment_of_id"])
            if src is not None and src["status"] == "ACTIVE":
                src["status"] = "SUPERSEDED"
                touch(src)
        return ok(agreement_out(agr))
    if agr["status"] == "SUSPENDED" and target == "ACTIVE":
        latest = latest_audit(agr["id"])
        if latest is None or latest["result"] != "PASS":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Reinstatement requires the latest audit to be a PASS")
        _reinstate_cascade(agr)
        return ok(agreement_out(agr))
    from_status = agr["status"]
    if target == "SUSPENDED":
        suspend_cascade(agr)
    else:  # TERMINATED
        _terminate_cascade(agr, from_status)
    return ok(agreement_out(agr))


@bp.post("/license-agreements/<rid>/amend")
@require_roles("LicensingManager")
def amend_agreement(rid):
    src = find("agreements", rid)
    b = body()
    expected = v_int(b, "expected_license_agreement_version")
    terr = v_str(b, "territory_code")
    start = parse_date_val(need(b, "effective_start"))
    end = parse_date_val(need(b, "effective_end"))
    tiers = v_tiers(b, "royalty_tiers")
    qmin = v_int(b, "quality_min_cup_score")
    excl = v_bool(b, "exclusive")
    if start > end:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "effective_start must fall on or before effective_end")
    agreement_write_gate(src)
    if src["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE agreement can be amended")
    if expected != src["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_license_agreement_version does not match the current version")
    if territory_conflict(src["brand_id"], terr, start, end,
                          self_id=None, self_root=_chain_root(src)):
        raise ApiError("ERR_TERRITORY_WINDOW_CONFLICT", 409,
                       "Territory window overlaps an ACTIVE/SUSPENDED agreement")
    touch(src)
    agr = init_common({
        "brand_id": src["brand_id"], "territory_code": terr,
        "effective_start": start.isoformat(), "effective_end": end.isoformat(),
        "royalty_tiers": tiers, "quality_min_cup_score": qmin,
        "exclusive": excl, "amendment_of_id": src["id"], "status": "DRAFT",
    })
    db["agreements"][agr["id"]] = agr
    return created(agreement_out(agr))
