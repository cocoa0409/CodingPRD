"""Tax Return Accuracy Guarantee & Audit Representation Program API.

Flask entry point: route registration, error handlers, server startup.
"""

import os
import re
from decimal import Decimal

from flask import Flask, request, jsonify

import db
import errors
from errors import ApiError
import middleware
from middleware import get_identity, require_roles
import response
import services

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return response.error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return response.error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_generic(err):
    # Never leak a bare 500 — surface as validation-style error envelope.
    return response.error_response(errors.ERR_VALIDATION, str(err), 400)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")

COMPONENTS_ENUM = set(services.COMPONENT_CREDITS.keys())
FILING_KINDS = {"ORIGINAL", "AMENDED"}
PRODUCT_TIERS = {"STANDARD", "PLUS"}
AUTHORITY_TYPES = {"FEDERAL", "STATE"}
ERROR_ATTRIBUTIONS = {"PREPARER_ERROR", "CLIENT_DATA_ERROR"}
SCOPES = {"IN_SCOPE", "OUT_OF_SCOPE"}
PREPARER_TIERS = set(services.TIER_MULTIPLIER.keys())

NON_TERMINAL_CLAIM_STATUSES = {
    "TRIAGE", "INFO_NEEDED", "SCOPE_CONFIRMED", "ASSIGNED", "REPRESENTING", "REOPENED",
}
TERMINAL_NOTICE_STATUSES = {"PAID", "ABATED", "WITHDRAWN"}


def body():
    """Return the JSON request body ({} if absent). Raise ERR_VALIDATION on bad JSON."""
    if request.data:
        try:
            data = request.get_json(force=True)
        except Exception:
            raise errors.validation("Request body is not valid JSON")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.validation("Request body must be a JSON object")
        return data
    return {}


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise errors.validation(f"Missing required field: {f}")


def parse_dt(value, field):
    try:
        return db._parse_iso(value)
    except Exception:
        raise errors.validation(f"Field {field} is not a valid ISO8601 datetime")


def get_or_404(store, entity_id, label="resource"):
    rec = store.get(entity_id)
    if rec is None:
        raise errors.not_found(f"{label} not found: {entity_id}")
    return rec


def paginate(items):
    """Apply limit/offset pagination. items must already be sorted by created_at."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise errors.validation("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.validation("limit out of range")
    if offset < 0:
        raise errors.validation("offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list(page, limit, offset, total)


def sorted_items(store):
    return sorted(store.values(), key=lambda r: (r["created_at"], r["id"]))


def find_active_product(return_id):
    for p in db.products.values():
        if p["return_id"] == return_id and p["status"] == "ACTIVE":
            return p
    return None


def lazy_expire_poas():
    """Move EXECUTED POAs whose expires_at has passed to EXPIRED."""
    now = db.clock_now()
    for poa in db.poas.values():
        if poa["status"] == "EXECUTED":
            exp = db._parse_iso(poa["expires_at"])
            if now > exp:
                poa["status"] = "EXPIRED"
                db.touch(poa)


# ---------------------------------------------------------------------------
# Serialization (entity views)
# ---------------------------------------------------------------------------


def office_view(o):
    return {
        "id": o["id"],
        "name": o["name"],
        "region_code": o["region_code"],
        "posture": o["posture"],
        "last_close_period": o["last_close_period"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def preparer_view(p):
    return {
        "id": p["id"],
        "office_id": p["office_id"],
        "full_name": p["full_name"],
        "tier": p["tier"],
        "credential_status": p["credential_status"],
        "remediation_status": p["remediation_status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def client_view(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def return_view(r):
    return {
        "id": r["id"],
        "client_id": r["client_id"],
        "office_id": r["office_id"],
        "preparer_id": r["preparer_id"],
        "tax_year": r["tax_year"],
        "components": r["components"],
        "filing_kind": r["filing_kind"],
        "original_return_id": r["original_return_id"],
        "status": r["status"],
        "quoted_fee_cents": r["quoted_fee_cents"],
        "final_fee_cents": r["final_fee_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def product_view(p):
    return {
        "id": p["id"],
        "return_id": p["return_id"],
        "tier": p["tier"],
        "premium_cents": p["premium_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def notice_view(n):
    return {
        "id": n["id"],
        "return_id": n["return_id"],
        "claim_id": n["claim_id"],
        "authority_type": n["authority_type"],
        "notice_reference": n["notice_reference"],
        "tax_delta_cents": n["tax_delta_cents"],
        "penalty_cents": n["penalty_cents"],
        "issued_at": n["issued_at"],
        "due_at": n["due_at"],
        "interest_cents": n["interest_cents"],
        "paid_at": n["paid_at"],
        "status": n["status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "return_id": c["return_id"],
        "notice_id": c["notice_id"],
        "protection_product_id": c["protection_product_id"],
        "status": c["status"],
        "scope": c["scope"],
        "error_attribution": c["error_attribution"],
        "scoped_by_user_id": c["scoped_by_user_id"],
        "payout_interest_cents": c["payout_interest_cents"],
        "payout_penalty_cents": c["payout_penalty_cents"],
        "payout_base_cents": c["payout_base_cents"],
        "payout_total_cents": c["payout_total_cents"],
        "final_liability_cents": c["final_liability_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def agent_view(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "license_number": a["license_number"],
        "max_parallel": a["max_parallel"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def assignment_view(a):
    return {
        "id": a["id"],
        "claim_id": a["claim_id"],
        "agent_id": a["agent_id"],
        "window_start": a["window_start"],
        "window_end": a["window_end"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def poa_view(p):
    return {
        "id": p["id"],
        "claim_id": p["claim_id"],
        "agent_id": p["agent_id"],
        "expires_at": p["expires_at"],
        "executed_at": p["executed_at"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def remediation_view(r):
    return {
        "id": r["id"],
        "preparer_id": r["preparer_id"],
        "due_at": r["due_at"],
        "completed_at": r["completed_at"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def escrow_view(e):
    return {
        "id": e["id"],
        "office_id": e["office_id"],
        "funded_cents": e["funded_cents"],
        "paid_out_cents": e["paid_out_cents"],
        "expected_accrual_cents": e["expected_accrual_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def snapshot_view(s):
    return {
        "id": s["id"],
        "office_id": s["office_id"],
        "period_month": s["period_month"],
        "returns_examined": s["returns_examined"],
        "returns_with_defects": s["returns_with_defects"],
        "defect_rate": s["defect_rate"],
        "quality_score": s["quality_score"],
        "posture_after": s["posture_after"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@app.route("/tax/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin"})
    data = body()
    require_fields(data, ["to_iso8601"])
    new_clock = db.set_clock(data["to_iso8601"])
    return response.success_object({"current_utc": db.utc_iso(new_clock)}, 200)


# ---------------------------------------------------------------------------
# Offices
# ---------------------------------------------------------------------------


@app.route("/tax/offices", methods=["POST"])
def create_office():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin"})
    data = body()
    require_fields(data, ["name", "region_code"])
    if not isinstance(data["name"], str) or not isinstance(data["region_code"], str):
        raise errors.validation("name and region_code must be strings")
    rec = db.base_record()
    rec.update({
        "name": data["name"],
        "region_code": data["region_code"],
        "posture": "OK",
        "last_close_period": None,
    })
    db.offices[rec["id"]] = rec
    return response.success_object(office_view(rec), 201)


@app.route("/tax/offices", methods=["GET"])
def list_offices():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    items = sorted_items(db.offices)
    region = request.args.get("region_code")
    if region is not None:
        items = [o for o in items if o["region_code"] == region]
    return paginate([office_view(o) for o in items])


@app.route("/tax/offices/<oid>", methods=["GET"])
def get_office(oid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager", "Preparer", "EnrolledAgent"})
    o = get_or_404(db.offices, oid, "office")
    return response.success_object(office_view(o))


@app.route("/tax/offices/<oid>/quality-close", methods=["POST"])
def quality_close(oid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    o = get_or_404(db.offices, oid, "office")
    data = body()
    require_fields(data, ["period_month", "returns_examined", "returns_with_defects"])
    period = data["period_month"]
    examined = data["returns_examined"]
    defects = data["returns_with_defects"]
    if not isinstance(period, str) or not PERIOD_RE.match(period):
        raise errors.validation("period_month must be a YYYY-MM string")
    if not isinstance(examined, int) or isinstance(examined, bool) or examined <= 0:
        raise errors.validation("returns_examined must be a positive integer")
    if not isinstance(defects, int) or isinstance(defects, bool) or defects < 0 or defects > examined:
        raise errors.validation("returns_with_defects must be between 0 and returns_examined")
    # period monotonicity (business_temporal, priority 18)
    if o["last_close_period"] is not None and period <= o["last_close_period"]:
        raise ApiError(errors.ERR_CLOSE_PERIOD_REGRESSION,
                       "period_month must be strictly greater than last_close_period", 422)

    # claims resolved with resolution falling inside the closed period
    # resolution time = updated_at at resolution; we track resolved_at on the claim
    claims_in_period = 0
    for c in db.claims.values():
        ret = db.returns.get(c["return_id"])
        if ret is None or ret["office_id"] != oid:
            continue
        ra = c.get("resolved_at")
        if ra is not None and ra[:7] == period:
            claims_in_period += 1

    score = services.office_quality_score(defects, examined, claims_in_period)
    posture = services.posture_for_score(score)
    defect_rate = defects / examined

    rec = db.base_record()
    rec.update({
        "office_id": oid,
        "period_month": period,
        "returns_examined": examined,
        "returns_with_defects": defects,
        "defect_rate": defect_rate,
        "quality_score": score,
        "posture_after": posture,
    })
    db.snapshots[rec["id"]] = rec

    # office mutation
    o["posture"] = posture
    o["last_close_period"] = period
    db.touch(o)

    # probation cascade: suspend preparers with overdue OPEN remediations
    if posture == "PROBATION":
        now = db.clock_now()
        for p in db.preparers.values():
            if p["office_id"] != oid:
                continue
            for r in db.remediations.values():
                if r["preparer_id"] == p["id"] and r["status"] == "OPEN":
                    due = db._parse_iso(r["due_at"])
                    if now > due:
                        if p["credential_status"] != "SUSPENDED":
                            p["credential_status"] = "SUSPENDED"
                            db.touch(p)
                        break

    return response.success_object(snapshot_view(rec), 201)


@app.route("/tax/offices/<oid>/snapshots", methods=["GET"])
def list_snapshots(oid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    get_or_404(db.offices, oid, "office")
    items = [s for s in sorted_items(db.snapshots) if s["office_id"] == oid]
    return paginate([snapshot_view(s) for s in items])


# ---------------------------------------------------------------------------
# Preparers
# ---------------------------------------------------------------------------


@app.route("/tax/preparers", methods=["POST"])
def create_preparer():
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    data = body()
    require_fields(data, ["office_id", "full_name", "tier"])
    get_or_404(db.offices, data["office_id"], "office")
    if data["tier"] not in PREPARER_TIERS:
        raise errors.validation("tier must be one of ASSOCIATE, SENIOR, MASTER, ENROLLED_AGENT")
    if not isinstance(data["full_name"], str):
        raise errors.validation("full_name must be a string")
    rec = db.base_record()
    rec.update({
        "office_id": data["office_id"],
        "full_name": data["full_name"],
        "tier": data["tier"],
        "credential_status": "ACTIVE",
        "remediation_status": "NONE",
    })
    db.preparers[rec["id"]] = rec
    return response.success_object(preparer_view(rec), 201)


@app.route("/tax/preparers", methods=["GET"])
def list_preparers():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    items = sorted_items(db.preparers)
    office_id = request.args.get("office_id")
    if office_id is not None:
        items = [p for p in items if p["office_id"] == office_id]
    return paginate([preparer_view(p) for p in items])


@app.route("/tax/preparers/<pid>", methods=["GET"])
def get_preparer(pid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager", "Preparer"})
    p = get_or_404(db.preparers, pid, "preparer")
    return response.success_object(preparer_view(p))


@app.route("/tax/preparers/<pid>/upgrade", methods=["POST"])
def upgrade_preparer(pid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    p = get_or_404(db.preparers, pid, "preparer")
    data = body()
    require_fields(data, ["tier"])
    new_tier = data["tier"]
    if new_tier not in PREPARER_TIERS:
        raise errors.validation("tier must be one of ASSOCIATE, SENIOR, MASTER, ENROLLED_AGENT")
    # posture gate
    office = db.offices.get(p["office_id"])
    if office is not None and office["posture"] == "PROBATION":
        raise ApiError(errors.ERR_OFFICE_POSTURE_BLOCKED,
                       "Office posture PROBATION blocks preparer upgrades", 409)
    if services.TIER_ORDER.index(new_tier) <= services.TIER_ORDER.index(p["tier"]):
        raise ApiError(errors.ERR_DOWNGRADE_FORBIDDEN,
                       "Upgrade target tier must be strictly higher than current tier", 422)
    p["tier"] = new_tier
    db.touch(p)
    return response.success_object(preparer_view(p), 200)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


@app.route("/tax/clients", methods=["POST"])
def create_client():
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager"})
    data = body()
    require_fields(data, ["full_name", "email"])
    if not isinstance(data["full_name"], str) or not isinstance(data["email"], str):
        raise errors.validation("full_name and email must be strings")
    for c in db.clients.values():
        if c["email"] == data["email"]:
            raise ApiError(errors.ERR_DUPLICATE_CLIENT_EMAIL,
                           "Client email already registered", 409)
    rec = db.base_record()
    rec.update({"full_name": data["full_name"], "email": data["email"]})
    db.clients[rec["id"]] = rec
    return response.success_object(client_view(rec), 201)


@app.route("/tax/clients/<cid>", methods=["GET"])
def get_client(cid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "Client"})
    c = get_or_404(db.clients, cid, "client")
    return response.success_object(client_view(c))


@app.route("/tax/clients/<cid>/returns", methods=["GET"])
def list_client_returns(cid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "Client"})
    get_or_404(db.clients, cid, "client")
    items = [r for r in sorted_items(db.returns) if r["client_id"] == cid]
    return paginate([return_view(r) for r in items])


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


def _validate_components(components):
    """Return the components list or raise. ERR_INVALID_COMPONENTS for enum/dup/empty."""
    if not isinstance(components, list) or len(components) == 0:
        raise ApiError(errors.ERR_INVALID_COMPONENTS,
                       "components must be a non-empty array", 422)
    seen = set()
    for c in components:
        if c not in COMPONENTS_ENUM:
            raise ApiError(errors.ERR_INVALID_COMPONENTS,
                           f"Unknown component code: {c}", 422)
        if c in seen:
            raise ApiError(errors.ERR_INVALID_COMPONENTS,
                           "components must not contain duplicates", 422)
        seen.add(c)
    return components


def _validate_amend(filing_kind, original_return_id):
    """AMENDED requires original_return_id referencing a FILED return."""
    if filing_kind == "AMENDED":
        if not original_return_id:
            raise ApiError(errors.ERR_AMEND_REQUIRES_ORIGINAL,
                           "AMENDED filing requires original_return_id", 422)
        orig = db.returns.get(original_return_id)
        if orig is None:
            raise errors.not_found(f"original return not found: {original_return_id}")
        if orig["status"] != "FILED":
            raise ApiError(errors.ERR_AMEND_REQUIRES_ORIGINAL,
                           "original_return_id must reference a FILED return", 422)


@app.route("/tax/returns", methods=["POST"])
def create_return():
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    data = body()
    require_fields(data, ["client_id", "office_id", "preparer_id", "tax_year", "components"])
    # existence, left to right: client_id, office_id, preparer_id
    get_or_404(db.clients, data["client_id"], "client")
    get_or_404(db.offices, data["office_id"], "office")
    preparer = get_or_404(db.preparers, data["preparer_id"], "preparer")
    if not isinstance(data["tax_year"], int) or isinstance(data["tax_year"], bool):
        raise errors.validation("tax_year must be an integer")
    components = _validate_components(data["components"])
    filing_kind = data.get("filing_kind", "ORIGINAL")
    if filing_kind not in FILING_KINDS:
        raise errors.validation("filing_kind must be ORIGINAL or AMENDED")
    original_return_id = data.get("original_return_id")
    _validate_amend(filing_kind, original_return_id)

    rec = db.base_record()
    rec.update({
        "client_id": data["client_id"],
        "office_id": data["office_id"],
        "preparer_id": data["preparer_id"],
        "tax_year": data["tax_year"],
        "components": list(components),
        "filing_kind": filing_kind,
        "original_return_id": original_return_id if filing_kind == "AMENDED" else None,
        "status": "PREPARING",
        "quoted_fee_cents": services.prep_fee_quote(components, preparer["tier"]),
        "final_fee_cents": None,
    })
    db.returns[rec["id"]] = rec
    return response.success_object(return_view(rec), 201)


@app.route("/tax/returns", methods=["GET"])
def list_returns():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    items = sorted_items(db.returns)
    for param in ("office_id", "preparer_id", "client_id", "original_return_id"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r.get(param) == val]
    return paginate([return_view(r) for r in items])


@app.route("/tax/returns/<rid>", methods=["GET"])
def get_return(rid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager", "Client", "Preparer", "EnrolledAgent"})
    r = get_or_404(db.returns, rid, "return")
    return response.success_object(return_view(r))


@app.route("/tax/returns/<rid>/products", methods=["GET"])
def list_return_products(rid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    get_or_404(db.returns, rid, "return")
    items = [p for p in sorted_items(db.products) if p["return_id"] == rid]
    return paginate([product_view(p) for p in items])


@app.route("/tax/returns/<rid>/notices", methods=["GET"])
def list_return_notices(rid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "EnrolledAgent"})
    get_or_404(db.returns, rid, "return")
    items = [n for n in sorted_items(db.notices) if n["return_id"] == rid]
    return paginate([notice_view(n) for n in items])


@app.route("/tax/returns/<rid>", methods=["PATCH"])
def patch_return(rid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    r = get_or_404(db.returns, rid, "return")
    # terminal lockdown (priority 5): FILED cannot be patched
    if r["status"] == "FILED":
        raise errors.already_terminal("A FILED return cannot be modified")
    if r["status"] != "PREPARING":
        raise errors.invalid_state()
    data = body()
    changed = False
    if "components" in data and data["components"] is not None:
        r["components"] = list(_validate_components(data["components"]))
        changed = True
    if "preparer_id" in data and data["preparer_id"] is not None:
        get_or_404(db.preparers, data["preparer_id"], "preparer")
        r["preparer_id"] = data["preparer_id"]
        changed = True
    if changed:
        preparer = db.preparers[r["preparer_id"]]
        r["quoted_fee_cents"] = services.prep_fee_quote(r["components"], preparer["tier"])
        db.touch(r)
    return response.success_object(return_view(r), 200)


@app.route("/tax/returns/<rid>/file", methods=["POST"])
def file_return(rid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    r = get_or_404(db.returns, rid, "return")
    if r["status"] == "FILED":
        raise errors.already_terminal("Return is already FILED")
    if r["status"] != "PREPARING":
        raise errors.invalid_state()
    preparer = db.preparers.get(r["preparer_id"])
    if preparer is None:
        raise errors.not_found("preparer not found")
    if preparer["credential_status"] != "ACTIVE":
        raise errors.invalid_state("Preparer credential_status is not ACTIVE")
    if r["filing_kind"] == "AMENDED":
        _validate_amend("AMENDED", r["original_return_id"])
    r["final_fee_cents"] = services.prep_fee_quote(r["components"], preparer["tier"])
    r["status"] = "FILED"
    db.touch(r)
    return response.success_object(return_view(r), 200)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@app.route("/tax/products", methods=["POST"])
def create_product():
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    data = body()
    require_fields(data, ["return_id", "tier"])
    ret = get_or_404(db.returns, data["return_id"], "return")
    if data["tier"] not in PRODUCT_TIERS:
        raise errors.validation("tier must be STANDARD or PLUS")
    # posture gate (priority 8)
    office = db.offices.get(ret["office_id"])
    if office is not None and office["posture"] == "PROBATION":
        raise ApiError(errors.ERR_OFFICE_POSTURE_BLOCKED,
                       "Office posture PROBATION blocks product sales", 409)
    # duplicate active product (priority 13)
    if find_active_product(ret["id"]) is not None:
        raise ApiError(errors.ERR_DUPLICATE_PRODUCT,
                       "Return already has an ACTIVE ProtectionProduct", 409)
    # eligibility (priority 14)
    if ret["status"] != "FILED" or "AMENDED_RETURN" in ret["components"]:
        raise ApiError(errors.ERR_PRODUCT_INELIGIBLE,
                       "Return must be FILED and must not contain AMENDED_RETURN", 422)
    rec = db.base_record()
    rec.update({
        "return_id": ret["id"],
        "tier": data["tier"],
        "premium_cents": services.protection_premium(ret["components"], data["tier"]),
        "status": "ACTIVE",
    })
    db.products[rec["id"]] = rec
    return response.success_object(product_view(rec), 201)


@app.route("/tax/products/<pid>/void", methods=["POST"])
def void_product(pid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin"})
    p = get_or_404(db.products, pid, "product")
    if p["status"] == "VOID":
        raise errors.already_terminal("Product is already VOID")
    if p["status"] != "ACTIVE":
        raise errors.invalid_state()
    for c in db.claims.values():
        if c["protection_product_id"] == pid and c["status"] in NON_TERMINAL_CLAIM_STATUSES:
            raise ApiError(errors.ERR_VOID_CLAIMS_OPEN,
                           "Product has non-terminal claims referencing it", 409)
    p["status"] = "VOID"
    db.touch(p)
    return response.success_object(product_view(p), 200)


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------


def _recompute_claim_payouts(claim):
    notice = db.notices.get(claim["notice_id"])
    product = db.products.get(claim["protection_product_id"])
    if notice is None:
        return
    base, interest, penalty, total = services.reimbursement_payout(claim, notice, product)
    claim["payout_base_cents"] = base
    claim["payout_interest_cents"] = interest
    claim["payout_penalty_cents"] = penalty
    claim["payout_total_cents"] = total
    db.touch(claim)


@app.route("/tax/notices", methods=["POST"])
def create_notice():
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    data = body()
    require_fields(data, ["return_id", "authority_type", "notice_reference",
                          "tax_delta_cents", "penalty_cents", "issued_at", "due_at"])
    ret = get_or_404(db.returns, data["return_id"], "return")
    if ret["status"] != "FILED":
        raise errors.invalid_state("Notice can only be registered against a FILED return")
    if data["authority_type"] not in AUTHORITY_TYPES:
        raise errors.validation("authority_type must be FEDERAL or STATE")
    if not isinstance(data["notice_reference"], str):
        raise errors.validation("notice_reference must be a string")
    for f in ("tax_delta_cents", "penalty_cents"):
        v = data[f]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise errors.validation(f"{f} must be a non-negative integer")
    issued_at = parse_dt(data["issued_at"], "issued_at")
    due_at = parse_dt(data["due_at"], "due_at")
    rec = db.base_record()
    rec.update({
        "return_id": ret["id"],
        "claim_id": None,
        "authority_type": data["authority_type"],
        "notice_reference": data["notice_reference"],
        "tax_delta_cents": data["tax_delta_cents"],
        "penalty_cents": data["penalty_cents"],
        "issued_at": db.utc_iso(issued_at),
        "due_at": db.utc_iso(due_at),
        "interest_cents": None,
        "paid_at": None,
        "status": "OPEN",
    })
    db.notices[rec["id"]] = rec
    return response.success_object(notice_view(rec), 201)


@app.route("/tax/notices", methods=["GET"])
def list_notices():
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "EnrolledAgent"})
    items = sorted_items(db.notices)
    return_id = request.args.get("return_id")
    if return_id is not None:
        items = [n for n in items if n["return_id"] == return_id]
    claim_id = request.args.get("claim_id")
    if claim_id is not None:
        items = [n for n in items if n.get("claim_id") == claim_id]
    return paginate([notice_view(n) for n in items])


@app.route("/tax/notices/<nid>", methods=["GET"])
def get_notice(nid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "EnrolledAgent"})
    n = get_or_404(db.notices, nid, "notice")
    return response.success_object(notice_view(n))


@app.route("/tax/notices/<nid>/pay", methods=["POST"])
def pay_notice(nid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    n = get_or_404(db.notices, nid, "notice")
    if n["status"] in TERMINAL_NOTICE_STATUSES:
        raise errors.already_terminal("Notice is in a terminal state")
    if n["status"] != "OPEN":
        raise errors.invalid_state()
    # pay on a notice whose linked claim is RESOLVED is rejected
    if n.get("claim_id"):
        linked = db.claims.get(n["claim_id"])
        if linked is not None and linked["status"] == "RESOLVED":
            raise ApiError(errors.ERR_CLAIM_ALREADY_RESOLVED,
                           "Linked claim is RESOLVED; reopen it first", 409)
    paid_at = db.clock_now()
    n["paid_at"] = db.utc_iso(paid_at)
    n["interest_cents"] = services.interest_accrual(
        n["tax_delta_cents"], db._parse_iso(n["due_at"]), paid_at)
    n["status"] = "PAID"
    db.touch(n)
    # cascade: linked claim payout recompute
    if n.get("claim_id"):
        linked = db.claims.get(n["claim_id"])
        if linked is not None:
            _recompute_claim_payouts(linked)
    return response.success_object(notice_view(n), 200)


@app.route("/tax/notices/<nid>/abate", methods=["POST"])
def abate_notice(nid):
    ident = get_identity()
    require_roles(ident, {"EnrolledAgent"})
    n = get_or_404(db.notices, nid, "notice")
    if n["status"] in TERMINAL_NOTICE_STATUSES:
        raise errors.already_terminal("Notice is in a terminal state")
    if n["status"] != "OPEN":
        raise errors.invalid_state()
    # notice must be linked to a claim in REPRESENTING and the acting agent
    # must hold the ACTIVE assignment on that claim
    if n.get("claim_id"):
        linked = db.claims.get(n["claim_id"])
        if linked is not None and linked["status"] == "RESOLVED":
            raise ApiError(errors.ERR_CLAIM_ALREADY_RESOLVED,
                           "Linked claim is RESOLVED; reopen it first", 409)
    claim = db.claims.get(n["claim_id"]) if n.get("claim_id") else None
    if claim is None or claim["status"] != "REPRESENTING":
        raise errors.invalid_state("Notice is not linked to a claim in REPRESENTING")
    active_assignment = None
    for a in db.assignments.values():
        if a["claim_id"] == claim["id"] and a["status"] == "ACTIVE":
            active_assignment = a
            break
    if active_assignment is None or active_assignment["agent_id"] != ident.user_id:
        raise errors.forbidden("Acting agent does not hold the ACTIVE assignment on this claim")
    n["interest_cents"] = 0
    n["penalty_cents"] = 0
    n["status"] = "ABATED"
    db.touch(n)
    _recompute_claim_payouts(claim)
    return response.success_object(notice_view(n), 200)


@app.route("/tax/notices/<nid>/withdraw", methods=["POST"])
def withdraw_notice(nid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    n = get_or_404(db.notices, nid, "notice")
    if n["status"] in TERMINAL_NOTICE_STATUSES:
        raise errors.already_terminal("Notice is in a terminal state")
    if n["status"] != "OPEN":
        raise errors.invalid_state()
    if n.get("claim_id") is not None:
        raise errors.invalid_state("A claim-linked notice must be resolved through the claim, not withdrawn")
    n["status"] = "WITHDRAWN"
    db.touch(n)
    return response.success_object(notice_view(n), 200)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


@app.route("/tax/claims", methods=["POST"])
def create_claim():
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    data = body()
    require_fields(data, ["return_id", "notice_id", "expected_return_version"])
    ret = get_or_404(db.returns, data["return_id"], "return")
    notice = get_or_404(db.notices, data["notice_id"], "notice")
    # OCC (priority 6)
    erv = data["expected_return_version"]
    if not isinstance(erv, int) or isinstance(erv, bool):
        raise errors.validation("expected_return_version must be an integer")
    if erv != ret["version"]:
        raise errors.stale_version("expected_return_version does not match the return's current version")
    # intake prerequisites (priority 12)
    product = find_active_product(ret["id"])
    if (ret["status"] != "FILED"
            or notice["status"] != "OPEN"
            or notice.get("claim_id") is not None
            or product is None):
        raise ApiError(errors.ERR_PROTECTION_REQUIRED,
                       "Return must be FILED, notice OPEN and unlinked, and return must carry an ACTIVE ProtectionProduct",
                       422)
    rec = db.base_record()
    rec.update({
        "return_id": ret["id"],
        "notice_id": notice["id"],
        "protection_product_id": product["id"],
        "status": "TRIAGE",
        "scope": None,
        "error_attribution": None,
        "scoped_by_user_id": None,
        "payout_interest_cents": 0,
        "payout_penalty_cents": 0,
        "payout_base_cents": 0,
        "payout_total_cents": 0,
        "final_liability_cents": None,
        "resolved_at": None,
    })
    db.claims[rec["id"]] = rec
    notice["claim_id"] = rec["id"]
    db.touch(notice)
    db.touch(ret)  # intake is itself a mutation of the return
    return response.success_object(claim_view(rec), 201)


@app.route("/tax/claims", methods=["GET"])
def list_claims():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    items = sorted_items(db.claims)
    return_id = request.args.get("return_id")
    if return_id is not None:
        items = [c for c in items if c["return_id"] == return_id]
    office_id = request.args.get("office_id")
    if office_id is not None:
        items = [c for c in items
                 if db.returns.get(c["return_id"], {}).get("office_id") == office_id]
    notice_id = request.args.get("notice_id")
    if notice_id is not None:
        items = [c for c in items if c["notice_id"] == notice_id]
    ppid = request.args.get("protection_product_id")
    if ppid is not None:
        items = [c for c in items if c["protection_product_id"] == ppid]
    return paginate([claim_view(c) for c in items])


@app.route("/tax/claims/<cid>", methods=["GET"])
def get_claim(cid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager", "Client", "EnrolledAgent"})
    lazy_expire_poas()
    c = get_or_404(db.claims, cid, "claim")
    return response.success_object(claim_view(c))


@app.route("/tax/claims/<cid>/poas", methods=["GET"])
def list_claim_poas(cid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "EnrolledAgent"})
    get_or_404(db.claims, cid, "claim")
    lazy_expire_poas()
    items = [p for p in sorted_items(db.poas) if p["claim_id"] == cid]
    return paginate([poa_view(p) for p in items])


@app.route("/tax/claims/<cid>/assignments", methods=["GET"])
def list_claim_assignments(cid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "EnrolledAgent"})
    get_or_404(db.claims, cid, "claim")
    items = [a for a in sorted_items(db.assignments) if a["claim_id"] == cid]
    return paginate([assignment_view(a) for a in items])


@app.route("/tax/claims/<cid>/scope", methods=["POST"])
def scope_claim(cid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    lazy_expire_poas()
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] == "RESOLVED":
        raise errors.already_terminal("Claim is RESOLVED")
    if c["status"] not in ("TRIAGE", "REOPENED"):
        raise errors.invalid_state()
    data = body()
    require_fields(data, ["scope"])
    scope = data["scope"]
    if scope not in SCOPES:
        raise errors.validation("scope must be IN_SCOPE or OUT_OF_SCOPE")
    if scope == "IN_SCOPE":
        ea = data.get("error_attribution")
        if ea not in ERROR_ATTRIBUTIONS:
            raise errors.validation("error_attribution is required and must be PREPARER_ERROR or CLIENT_DATA_ERROR")
        c["scope"] = "IN_SCOPE"
        c["error_attribution"] = ea
        c["scoped_by_user_id"] = ident.user_id
        c["status"] = "SCOPE_CONFIRMED"
    else:
        c["scope"] = "OUT_OF_SCOPE"
        c["status"] = "DENIED"
    db.touch(c)
    return response.success_object(claim_view(c), 200)


@app.route("/tax/claims/<cid>/request-info", methods=["POST"])
def request_info(cid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] == "RESOLVED":
        raise errors.already_terminal("Claim is RESOLVED")
    if c["status"] not in ("TRIAGE", "REOPENED"):
        raise errors.invalid_state()
    c["status"] = "INFO_NEEDED"
    db.touch(c)
    return response.success_object(claim_view(c), 200)


@app.route("/tax/claims/<cid>/provide-info", methods=["POST"])
def provide_info(cid):
    ident = get_identity()
    require_roles(ident, {"Client"})
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] == "RESOLVED":
        raise errors.already_terminal("Claim is RESOLVED")
    if c["status"] != "INFO_NEEDED":
        raise errors.invalid_state()
    # entity-backed ownership: acting client must own the claim's return
    ret = db.returns.get(c["return_id"])
    if ret is None or ret["client_id"] != ident.user_id:
        raise errors.forbidden("Client may only provide info on own claims")
    c["status"] = "TRIAGE"
    db.touch(c)
    return response.success_object(claim_view(c), 200)


@app.route("/tax/claims/<cid>/assign", methods=["POST"])
def assign_claim(cid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    lazy_expire_poas()
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] == "RESOLVED":
        raise errors.already_terminal("Claim is RESOLVED")
    if c["status"] != "SCOPE_CONFIRMED" or c["scope"] != "IN_SCOPE":
        raise errors.invalid_state("Claim must be SCOPE_CONFIRMED with scope IN_SCOPE")
    data = body()
    require_fields(data, ["agent_id", "window_start", "window_end"])
    agent = get_or_404(db.agents, data["agent_id"], "agent")
    window_start = parse_dt(data["window_start"], "window_start")
    window_end = parse_dt(data["window_end"], "window_end")
    # invalid window (priority 17)
    if window_end <= window_start:
        raise ApiError(errors.ERR_INVALID_WINDOW, "window_end must be strictly after window_start", 422)
    # no ACTIVE assignment on this claim
    for a in db.assignments.values():
        if a["claim_id"] == cid and a["status"] == "ACTIVE":
            raise errors.invalid_state("Claim already has an ACTIVE assignment")
    # capacity (priority 15): claims in REPRESENTING under this agent
    representing = 0
    for a in db.assignments.values():
        if a["agent_id"] == agent["id"] and a["status"] == "ACTIVE":
            ac = db.claims.get(a["claim_id"])
            if ac is not None and ac["status"] == "REPRESENTING":
                representing += 1
    if representing >= agent["max_parallel"]:
        raise ApiError(errors.ERR_AGENT_CAPACITY,
                       "Agent's REPRESENTING claim count is at max_parallel", 409)
    # window overlap (priority 16): half-open [start, end)
    for a in db.assignments.values():
        if a["agent_id"] == agent["id"] and a["status"] == "ACTIVE":
            a_start = db._parse_iso(a["window_start"])
            a_end = db._parse_iso(a["window_end"])
            if window_start < a_end and a_start < window_end:
                raise ApiError(errors.ERR_WINDOW_OVERLAP,
                               "Window overlaps another ACTIVE assignment for this agent", 409)
    rec = db.base_record()
    rec.update({
        "claim_id": cid,
        "agent_id": agent["id"],
        "window_start": db.utc_iso(window_start),
        "window_end": db.utc_iso(window_end),
        "status": "ACTIVE",
    })
    db.assignments[rec["id"]] = rec
    c["status"] = "ASSIGNED"
    db.touch(c)
    return response.success_object(assignment_view(rec), 201)


@app.route("/tax/claims/<cid>/poa", methods=["POST"])
def draft_poa(cid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    lazy_expire_poas()
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] == "RESOLVED":
        raise errors.already_terminal("Claim is RESOLVED")
    data = body()
    require_fields(data, ["agent_id", "expires_at"])
    get_or_404(db.agents, data["agent_id"], "agent")
    expires_at = parse_dt(data["expires_at"], "expires_at")
    # supersede any existing DRAFT POA on the claim
    superseded_version = 0
    for p in db.poas.values():
        if p["claim_id"] == cid and p["status"] == "DRAFT":
            p["status"] = "REVOKED"
            db.touch(p)
            superseded_version = max(superseded_version, p["version"])
    rec = db.base_record()
    rec.update({
        "claim_id": cid,
        "agent_id": data["agent_id"],
        "expires_at": db.utc_iso(expires_at),
        "executed_at": None,
        "status": "DRAFT",
    })
    if superseded_version:
        # The superseding draft continues the claim's draft-POA version line:
        # its version must differ from the superseded draft's, so an execute
        # request carrying the pre-supersede version is detected as stale
        # (§2.6).
        rec["version"] = superseded_version + 1
    db.poas[rec["id"]] = rec
    return response.success_object(poa_view(rec), 201)


@app.route("/tax/claims/<cid>/poa/execute", methods=["POST"])
def execute_poa(cid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    lazy_expire_poas()
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] == "RESOLVED":
        raise errors.already_terminal("Claim is RESOLVED")
    if c["status"] != "ASSIGNED":
        raise errors.invalid_state("Claim must be ASSIGNED")
    data = body()
    require_fields(data, ["expected_poa_version"])
    epv = data["expected_poa_version"]
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise errors.validation("expected_poa_version must be an integer")
    # POA state precondition (priority 4) applies when the claim carries no
    # DRAFT POA but does carry a POA in a non-DRAFT state (revoked directly or
    # superseded): the request then targets a POA resource whose state forbids
    # execution, surfacing ERR_INVALID_STATE before any business rule. When a
    # DRAFT exists, §2.6 pins OCC against that draft's current version: any
    # mismatch — including the stale view of a superseded draft — is
    # ERR_STALE_VERSION.
    draft = None
    non_draft_exists = False
    for p in db.poas.values():
        if p["claim_id"] != cid:
            continue
        if p["status"] == "DRAFT":
            draft = p
        elif p["status"] in ("REVOKED", "EXPIRED"):
            non_draft_exists = True
    if draft is None:
        if non_draft_exists:
            raise errors.invalid_state("The claim's POA is no longer DRAFT")
        raise ApiError(errors.ERR_POA_NOT_DRAFT, "No DRAFT POA exists on the claim", 409)
    # OCC (priority 6)
    if epv != draft["version"]:
        raise errors.stale_version("expected_poa_version does not match the POA's current version")
    # temporal validity (priority 9)
    if db.clock_now() >= db._parse_iso(draft["expires_at"]):
        raise ApiError(errors.ERR_POA_EXPIRED, "POA expires_at is not after the logical clock", 422)
    # agent match
    active_assignment = None
    for a in db.assignments.values():
        if a["claim_id"] == cid and a["status"] == "ACTIVE":
            active_assignment = a
            break
    if active_assignment is None or draft["agent_id"] != active_assignment["agent_id"]:
        raise errors.invalid_state("POA agent_id must be the agent of the claim's ACTIVE assignment")
    now = db.clock_now()
    draft["status"] = "EXECUTED"
    draft["executed_at"] = db.utc_iso(now)
    db.touch(draft)
    c["status"] = "REPRESENTING"
    db.touch(c)
    return response.success_object(claim_view(c), 200)


@app.route("/tax/poas/<pid>/revoke", methods=["POST"])
def revoke_poa(pid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    p = get_or_404(db.poas, pid, "poa")
    if p["status"] in ("EXECUTED", "EXPIRED", "REVOKED"):
        if p["status"] == "REVOKED":
            raise errors.already_terminal("POA is already REVOKED")
        raise errors.invalid_state("Only a DRAFT POA may be revoked")
    if p["status"] != "DRAFT":
        raise errors.invalid_state()
    p["status"] = "REVOKED"
    db.touch(p)
    return response.success_object(poa_view(p), 200)


@app.route("/tax/poas/<pid>", methods=["GET"])
def get_poa(pid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "EnrolledAgent"})
    lazy_expire_poas()
    p = get_or_404(db.poas, pid, "poa")
    return response.success_object(poa_view(p))


@app.route("/tax/poas", methods=["GET"])
def list_poas():
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "EnrolledAgent"})
    lazy_expire_poas()
    items = sorted_items(db.poas)
    agent_id = request.args.get("agent_id")
    if agent_id is not None:
        items = [p for p in items if p["agent_id"] == agent_id]
    claim_id = request.args.get("claim_id")
    if claim_id is not None:
        items = [p for p in items if p["claim_id"] == claim_id]
    return paginate([poa_view(p) for p in items])


@app.route("/tax/claims/<cid>/resolve", methods=["POST"])
def resolve_claim(cid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    lazy_expire_poas()
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] == "RESOLVED":
        raise errors.already_terminal("Claim is RESOLVED")
    if c["status"] != "REPRESENTING":
        raise errors.invalid_state("Claim must be REPRESENTING")
    # segregation of duties (priority 7)
    if ident.user_id == c["scoped_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES,
                       "Resolver must differ from the scoping operator", 403)
    # every linked notice terminal (priority 10)
    for n in db.notices.values():
        if n.get("claim_id") == cid and n["status"] not in TERMINAL_NOTICE_STATUSES:
            raise ApiError(errors.ERR_NOTICE_NOT_TERMINAL,
                           "Every linked notice must be terminal before resolution", 409)
    # payout computation
    notice = db.notices.get(c["notice_id"])
    product = db.products.get(c["protection_product_id"])
    base, interest, penalty, total = services.reimbursement_payout(c, notice, product)
    c["payout_base_cents"] = base
    c["payout_interest_cents"] = interest
    c["payout_penalty_cents"] = penalty
    c["payout_total_cents"] = total
    c["final_liability_cents"] = services.final_liability(total, base)
    now = db.clock_now()
    c["resolved_at"] = db.utc_iso(now)
    # cascade: complete ACTIVE assignment
    for a in db.assignments.values():
        if a["claim_id"] == cid and a["status"] == "ACTIVE":
            a["status"] = "COMPLETED"
            db.touch(a)
    # cascade: escrow debit + accrual
    ret = db.returns.get(c["return_id"])
    if ret is not None:
        for e in db.escrows.values():
            if e["office_id"] == ret["office_id"]:
                e["paid_out_cents"] += c["final_liability_cents"]
                e["expected_accrual_cents"] += services.accrual_contribution(total)
                db.touch(e)
                break
    c["status"] = "RESOLVED"
    db.touch(c)
    return response.success_object(claim_view(c), 200)


@app.route("/tax/claims/<cid>/reopen", methods=["POST"])
def reopen_claim(cid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    c = get_or_404(db.claims, cid, "claim")
    if c["status"] == "DENIED":
        raise errors.invalid_state("DENIED is terminal")
    if c["status"] != "RESOLVED":
        raise errors.invalid_state("Only a RESOLVED claim may be reopened")
    # credit the escrow paid_out (accrual unchanged — historical)
    ret = db.returns.get(c["return_id"])
    if ret is not None:
        for e in db.escrows.values():
            if e["office_id"] == ret["office_id"]:
                e["paid_out_cents"] -= (c["final_liability_cents"] or 0)
                db.touch(e)
                break
    c["status"] = "REOPENED"
    db.touch(c)
    return response.success_object(claim_view(c), 200)


@app.route("/tax/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    ident = get_identity()
    require_roles(ident, {"CaseManager"})
    a = get_or_404(db.assignments, aid, "assignment")
    if a["status"] in ("COMPLETED", "CANCELLED"):
        raise errors.already_terminal("Assignment is in a terminal state")
    if a["status"] != "ACTIVE":
        raise errors.invalid_state()
    claim = db.claims.get(a["claim_id"])
    if claim is None or claim["status"] != "ASSIGNED":
        raise errors.invalid_state("Cannot cancel once the claim has advanced past ASSIGNED")
    a["status"] = "CANCELLED"
    db.touch(a)
    return response.success_object(assignment_view(a), 200)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@app.route("/tax/agents", methods=["POST"])
def create_agent():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin"})
    data = body()
    require_fields(data, ["full_name", "license_number"])
    if not isinstance(data["full_name"], str) or not isinstance(data["license_number"], str):
        raise errors.validation("full_name and license_number must be strings")
    for a in db.agents.values():
        if a["license_number"] == data["license_number"]:
            raise errors.validation("license_number already registered")
    max_parallel = data.get("max_parallel", 3)
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or max_parallel < 1:
        raise errors.validation("max_parallel must be an integer >= 1")
    rec = db.base_record()
    rec.update({
        "full_name": data["full_name"],
        "license_number": data["license_number"],
        "max_parallel": max_parallel,
    })
    db.agents[rec["id"]] = rec
    return response.success_object(agent_view(rec), 201)


@app.route("/tax/agents/<aid>", methods=["GET"])
def get_agent(aid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager", "EnrolledAgent"})
    a = get_or_404(db.agents, aid, "agent")
    return response.success_object(agent_view(a))


@app.route("/tax/agents/<aid>/assignments", methods=["GET"])
def list_agent_assignments(aid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager", "EnrolledAgent"})
    get_or_404(db.agents, aid, "agent")
    items = [a for a in sorted_items(db.assignments) if a["agent_id"] == aid]
    return paginate([assignment_view(a) for a in items])


# ---------------------------------------------------------------------------
# Remediations
# ---------------------------------------------------------------------------


@app.route("/tax/remediations", methods=["POST"])
def create_remediation():
    ident = get_identity()
    require_roles(ident, {"OfficeManager"})
    data = body()
    require_fields(data, ["preparer_id", "due_at"])
    preparer = get_or_404(db.preparers, data["preparer_id"], "preparer")
    due_at = parse_dt(data["due_at"], "due_at")
    # auto-close any existing OPEN remediation on this preparer
    for r in db.remediations.values():
        if r["preparer_id"] == preparer["id"] and r["status"] == "OPEN":
            r["status"] = "COMPLETED"
            r["completed_at"] = db.utc_iso(db.clock_now())
            db.touch(r)
    rec = db.base_record()
    rec.update({
        "preparer_id": preparer["id"],
        "due_at": db.utc_iso(due_at),
        "completed_at": None,
        "status": "OPEN",
    })
    db.remediations[rec["id"]] = rec
    preparer["remediation_status"] = "ACTIVE"
    db.touch(preparer)
    return response.success_object(remediation_view(rec), 201)


@app.route("/tax/remediations", methods=["GET"])
def list_remediations():
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "Preparer"})
    items = sorted_items(db.remediations)
    preparer_id = request.args.get("preparer_id")
    if preparer_id is not None:
        items = [r for r in items if r["preparer_id"] == preparer_id]
    return paginate([remediation_view(r) for r in items])


@app.route("/tax/remediations/<rid>", methods=["GET"])
def get_remediation(rid):
    ident = get_identity()
    require_roles(ident, {"OfficeManager", "CaseManager", "Preparer"})
    r = get_or_404(db.remediations, rid, "remediation")
    return response.success_object(remediation_view(r))


@app.route("/tax/remediations/<rid>/complete", methods=["POST"])
def complete_remediation(rid):
    ident = get_identity()
    require_roles(ident, {"Preparer"})
    r = get_or_404(db.remediations, rid, "remediation")
    if r["status"] == "COMPLETED":
        raise errors.already_terminal("Remediation is already COMPLETED")
    if r["status"] != "OPEN":
        raise errors.invalid_state()
    # entity-backed ownership
    if r["preparer_id"] != ident.user_id:
        raise errors.forbidden("Preparer may only complete own remediation")
    if db.clock_now() > db._parse_iso(r["due_at"]):
        raise ApiError(errors.ERR_REMEDIATION_OVERDUE,
                       "Remediation is overdue and cannot be completed", 422)
    r["status"] = "COMPLETED"
    r["completed_at"] = db.utc_iso(db.clock_now())
    db.touch(r)
    preparer = db.preparers.get(r["preparer_id"])
    if preparer is not None:
        preparer["remediation_status"] = "COMPLETED"
        db.touch(preparer)
    return response.success_object(remediation_view(r), 200)


# ---------------------------------------------------------------------------
# Escrows
# ---------------------------------------------------------------------------


@app.route("/tax/escrows", methods=["POST"])
def create_escrow():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin"})
    data = body()
    require_fields(data, ["office_id", "funded_cents"])
    get_or_404(db.offices, data["office_id"], "office")
    fc = data["funded_cents"]
    if not isinstance(fc, int) or isinstance(fc, bool) or fc <= 0:
        raise errors.validation("funded_cents must be a positive integer")
    for e in db.escrows.values():
        if e["office_id"] == data["office_id"]:
            raise ApiError(errors.ERR_DUPLICATE_ESCROW,
                           "Office already has an escrow", 409)
    rec = db.base_record()
    rec.update({
        "office_id": data["office_id"],
        "funded_cents": fc,
        "paid_out_cents": 0,
        "expected_accrual_cents": 0,
    })
    db.escrows[rec["id"]] = rec
    return response.success_object(escrow_view(rec), 201)


@app.route("/tax/escrows", methods=["GET"])
def list_escrows():
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    items = sorted_items(db.escrows)
    office_id = request.args.get("office_id")
    if office_id is not None:
        items = [e for e in items if e["office_id"] == office_id]
    return paginate([escrow_view(e) for e in items])


@app.route("/tax/escrows/<eid>", methods=["GET"])
def get_escrow(eid):
    ident = get_identity()
    require_roles(ident, {"ProgramAdmin", "OfficeManager", "CaseManager"})
    e = get_or_404(db.escrows, eid, "escrow")
    return response.success_object(escrow_view(e))


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
