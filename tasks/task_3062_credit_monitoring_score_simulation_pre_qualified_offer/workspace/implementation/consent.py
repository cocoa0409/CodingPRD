"""Consent capture, sealing helpers and the data-boundary reads."""

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("consent", __name__)

READ_ROLES = ["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin"]
LIST_ROLES = READ_ROLES + ["DataProtectionOfficer"]
CONSENT_METHODS = ("ELECTRONIC", "WRITTEN")
CONSENT_SCOPES = ("SHARE_PII_WITH_LENDER",)


def consent_for(consumer_id, decision_id):
    for row in store.consent_records.values():
        if row["consumer_id"] == consumer_id and row["decision_id"] == decision_id:
            return row
    return None


def routing_netloc(prog):
    sponsor = store.lenders.get(prog["lender_id"]) if prog else None
    stem = (sponsor["id"][:8] if sponsor else "unknown")
    return "%s.lender-endpoint.example" % stem


def seal_consent(con, prog):
    """Mint the sealed PII blob and stamp the stored routing netloc."""
    moment = store.now()
    con["consumer_pii_ciphertext"] = "sealed::" + con["id"].replace("-", "")[:24]
    con["lender_routing_netloc"] = routing_netloc(prog)
    con["status"] = "SEALED"
    con["sealed_at"] = moment
    return con


def release_consent(con):
    con["status"] = "NOT_SEALED"
    con["consumer_pii_ciphertext"] = None
    con["sealed_at"] = None
    return con


@bp.route("/consumers/<cid>/consents/<did>/complete", methods=["POST"])
def complete_consent(cid, did):
    uid, role = require(["Consumer", "Referee"])
    cns = helpers.consumer(cid)
    dec = helpers.decision(did)
    if dec["consumer_id"] != cid:
        fail("ERR_CONSUMER_NOT_FOUND", "The decision does not belong to this consumer.")
    if role == "Consumer":
        helpers.owned(dec, uid, role, field="consumer_id")
    if cns["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Consent requires an ACTIVE consumer.")
    if dec["decision_status"] != "PREQUALIFIED":
        fail("ERR_CONSENT_DECISION_NOT_PREQUALIFIED")
    fresh_until = dec.get("fresh_until")
    if fresh_until is not None and store.now() >= fresh_until:
        fail("ERR_OFFER_EXPIRED")
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    helpers.checkout_version(cns, data)
    method = data.get("consent_method")
    scope = data.get("consent_scope")
    if method not in CONSENT_METHODS:
        fail("ERR_INVALID_REQUEST", "consent_method must be ELECTRONIC or WRITTEN.")
    if scope not in CONSENT_SCOPES:
        fail("ERR_INVALID_REQUEST", "consent_scope must be SHARE_PII_WITH_LENDER.")
    existing = consent_for(cid, did)
    moment = store.now()
    if existing is not None and existing["status"] != "PENDING":
        fail("ERR_CONSENT_NOT_PENDING")
    if existing is None:
        row = store.make_row({
            "consumer_id": cid,
            "decision_id": did,
            "consent_method": method,
            "consent_scope": scope,
            "consumer_pii_ciphertext": None,
            "lender_routing_netloc": None,
            "status": "PENDING",
            "consented_at": moment,
            "sealed_at": None,
            "archive_status": "LIVE",
        }, moment)
        store.consent_records[row["id"]] = row
    else:
        row = existing
        row["consent_method"] = method
        row["consent_scope"] = scope
        row["status"] = "PENDING"
        row["consented_at"] = moment
        row["archive_status"] = "LIVE"
    dec["decision_status"] = "CONSENTED"
    dec["updated_at"] = moment
    dec["version"] = int(dec.get("version", 0)) + 1
    helpers.bump_consumer(cns)
    return ok(models.consent(row), store.now(), 201)


@bp.route("/consent-records", methods=["GET"])
def list_consents():
    require(LIST_ROLES)
    rows = list(store.consent_records.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    archive = request.args.get("archive_status")
    if archive:
        rows = [r for r in rows if (r.get("archive_status") or "LIVE") == archive]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.consent(r) for r in window], store.now(), pagination)


@bp.route("/consent-records/<rid>", methods=["GET"])
def get_consent(rid):
    uid, role = require(READ_ROLES)
    row = store.consent_records.get(rid)
    if row is None:
        fail("ERR_CONSUMER_NOT_FOUND", "ConsentRecord not found.")
    helpers.owned(row, uid, role, field="consumer_id")
    return ok(models.consent(row), store.now())


@bp.route("/consumers/<cid>/consent-records", methods=["GET"])
def list_consumer_consents(cid):
    require(READ_ROLES)
    helpers.consumer(cid)
    rows = [r for r in store.consent_records.values() if r["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.consent(r) for r in window], store.now(), pagination)


@bp.route("/pre-qualification-decisions/<did>/consent-records", methods=["GET"])
def list_decision_consents(did):
    require(READ_ROLES)
    helpers.decision(did)
    rows = [r for r in store.consent_records.values() if r["decision_id"] == did]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.consent(r) for r in window], store.now(), pagination)