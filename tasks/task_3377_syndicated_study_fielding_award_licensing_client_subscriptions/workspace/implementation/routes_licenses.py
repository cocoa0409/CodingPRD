"""License lifecycle and UsageAudit endpoints."""
from flask import Blueprint, g

from db import clock, store
from envelope import filter_params, ok_object, paginated
from errors import fail
from middleware import require
from records import new_record, ser_audit, ser_license, touch
from services import (
    MINOR_SUSPENSION_THRESHOLD,
    fee_invoice,
    fee_quote,
    resolve_open_audits,
    suspend_license,
)
from timeutil import add_months
from validation import Body

bp = Blueprint("licenses", __name__, url_prefix="/research")

LICENSE_READ_ROLES = ("StudyAdmin", "LicensingManager", "ClientUser")
TIERS = ("DIGITAL", "NATIONAL", "GLOBAL")
VALID_TERMS = (12, 24, 36)


@bp.post("/licenses")
@require("LicensingManager", "ClientUser")
def create_license():
    b = Body()
    award_id = b.str_("award_id")
    client_id = b.str_("client_id")
    tier = b.enum_("tier", TIERS)
    term = b.int_("term_months")
    markets = b.int_("markets_count")
    # ownership (priority 2): ClientUser quotes only for its own client record
    if g.role == "ClientUser" and client_id is not None and client_id != g.user_id:
        fail("ERR_FORBIDDEN", "ClientUser may create licenses only for its own client_id")
    # existence (priority 3)
    if award_id is not None and award_id not in store.awards:
        fail("ERR_NOT_FOUND", "award_id does not reference an existing award")
    if client_id is not None and client_id not in store.clients:
        fail("ERR_NOT_FOUND", "client_id does not reference an existing client")
    # domain (priority 8): term and market bounds
    if term is not None and term not in VALID_TERMS:
        fail("ERR_LICENSE_TERM_INVALID", "term_months must be one of 12, 24, 36")
    if markets is not None and markets < 1:
        fail("ERR_MARKETS_INVALID", "markets_count must be >= 1")
    # syntactic (priority 11)
    b.finalize()
    rec = new_record()
    rec.update({
        "award_id": award_id,
        "client_id": client_id,
        "tier": tier,
        "term_months": term,
        "markets_count": markets,
        "fee_quote_cents": fee_quote(tier, markets),
        "fee_final_cents": None,
        "status": "QUOTED",
        "activated_at": None,
        "expires_at": None,
        "suspension_count": 0,
    })
    store.licenses[rec["id"]] = rec
    return ok_object(ser_license(rec), 201)


@bp.get("/licenses")
@require(*LICENSE_READ_ROLES)
def list_licenses():
    items = list(store.licenses.values())
    if g.role == "ClientUser":
        items = [l for l in items if l["client_id"] == g.user_id]
    items = filter_params(items, ("client_id", "award_id", "status"))
    return paginated(items, ser_license)


@bp.get("/licenses/<lid>")
@require(*LICENSE_READ_ROLES)
def get_license(lid):
    lic = store.licenses.get(lid)
    if lic is None:
        fail("ERR_NOT_FOUND", "License not found")
    if g.role == "ClientUser" and lic["client_id"] != g.user_id:
        fail("ERR_FORBIDDEN", "ClientUser may read only its own licenses")
    return ok_object(ser_license(lic))


@bp.post("/licenses/<lid>/state")
@require("LicensingManager")
def license_state(lid):
    lic = store.licenses.get(lid)
    if lic is None:
        fail("ERR_NOT_FOUND", "License not found")
    b = Body()
    to = b.str_("to_status")
    b.finalize()
    cur = lic["status"]
    if to == "ACTIVE":
        if cur == "QUOTED":
            award = store.awards.get(lic["award_id"])
            if award is None or award["status"] != "PUBLISHED":
                fail("ERR_AWARD_NOT_PUBLISHED", "License activation requires a PUBLISHED award")
            now = clock.now()
            for o in store.licenses.values():
                if o["id"] == lic["id"] or o["award_id"] != lic["award_id"] or o["status"] != "ACTIVE":
                    continue
                # half-open occupation [activated_at, expires_at)
                if o["activated_at"] <= now < o["expires_at"]:
                    fail("ERR_LICENSE_CONFLICT", "Another license on this award is ACTIVE")
            lic["fee_final_cents"] = fee_invoice(lic)
            lic["activated_at"] = now
            lic["expires_at"] = add_months(now, lic["term_months"])
            lic["status"] = "ACTIVE"
        elif cur == "SUSPENDED":
            open_audits = [
                a for a in store.usage_audits.values()
                if a["license_id"] == lid and a["status"] in ("OPEN", "ESCALATED")
            ]
            if open_audits:
                fail("ERR_AUDITS_UNRESOLVED", "Reinstatement requires zero open or escalated audits")
            # expires_at and fee_final_cents MUST NOT change on reinstate
            lic["status"] = "ACTIVE"
        else:
            fail("ERR_INVALID_STATE", "Cannot transition license from %s to ACTIVE" % cur)
    elif to == "SUSPENDED":
        if cur != "ACTIVE":
            fail("ERR_INVALID_STATE", "Cannot transition license from %s to SUSPENDED" % cur)
        suspend_license(lic)
    elif to == "REVOKED":
        if cur not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "Cannot transition license from %s to REVOKED" % cur)
        lic["status"] = "REVOKED"
        resolve_open_audits(lid, "LICENSE_REVOKED_AUTO")
    elif to == "WITHDRAWN":
        if cur != "QUOTED":
            fail("ERR_INVALID_STATE", "Cannot transition license from %s to WITHDRAWN" % cur)
        lic["status"] = "WITHDRAWN"
    elif to == "EXPIRED":
        if cur != "ACTIVE":
            fail("ERR_INVALID_STATE", "Cannot transition license from %s to EXPIRED" % cur)
        if clock.now() < lic["expires_at"]:
            fail("ERR_LICENSE_NOT_EXPIRED", "Logical clock has not reached expires_at")
        lic["status"] = "EXPIRED"
    else:
        fail("ERR_INVALID_STATE", "License transition to %r is not defined" % to)
    touch(lic)
    return ok_object(ser_license(lic), 200)


@bp.post("/usage-audits")
@require("LicensingManager")
def create_audit():
    b = Body()
    license_id = b.str_("license_id")
    severity = b.enum_("severity", ("MINOR", "MAJOR"))
    note = b.str_("note", required=False)
    lic = store.licenses.get(license_id) if license_id is not None else None
    if license_id is not None and lic is None:
        fail("ERR_NOT_FOUND", "license_id does not reference an existing license")
    if lic is not None and lic["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "Audits require the license to be ACTIVE or SUSPENDED")
    b.finalize()
    rec = new_record()
    rec.update({
        "license_id": license_id,
        "severity": severity,
        "note": note,
        "status": "OPEN",
        "resolution": None,
    })
    store.usage_audits[rec["id"]] = rec
    return ok_object(ser_audit(rec), 201)


@bp.get("/licenses/<lid>/usage-audits")
@require("StudyAdmin", "LicensingManager")
def list_audits(lid):
    lic = store.licenses.get(lid)
    if lic is None:
        fail("ERR_NOT_FOUND", "License not found")
    items = [a for a in store.usage_audits.values() if a["license_id"] == lid]
    items = filter_params(items, ("status",))
    return paginated(items, ser_audit)


@bp.post("/usage-audits/<aid>/state")
@require("LicensingManager")
def audit_state(aid):
    audit = store.usage_audits.get(aid)
    if audit is None:
        fail("ERR_NOT_FOUND", "Usage audit not found")
    b = Body()
    to = b.str_("to_status")
    b.finalize()
    cur = audit["status"]
    if to == "ESCALATED":
        if cur != "OPEN":
            fail("ERR_INVALID_STATE", "Cannot transition audit from %s to ESCALATED" % cur)
        audit["status"] = "ESCALATED"
        touch(audit)
        lic = store.licenses.get(audit["license_id"])
        if lic is not None and lic["status"] == "ACTIVE":
            if audit["severity"] == "MAJOR":
                suspend_license(lic)
            else:
                escalated_minor = sum(
                    1 for a in store.usage_audits.values()
                    if a["license_id"] == lic["id"]
                    and a["status"] == "ESCALATED"
                    and a["severity"] == "MINOR"
                )
                if escalated_minor >= MINOR_SUSPENSION_THRESHOLD:
                    suspend_license(lic)
    elif to == "RESOLVED":
        if cur not in ("OPEN", "ESCALATED"):
            fail("ERR_INVALID_STATE", "Cannot transition audit from %s to RESOLVED" % cur)
        audit["status"] = "RESOLVED"
        audit["resolution"] = "CONFIRMED"
        touch(audit)
    else:
        fail("ERR_INVALID_STATE", "Audit transition to %r is not defined" % to)
    return ok_object(ser_audit(audit), 200)
