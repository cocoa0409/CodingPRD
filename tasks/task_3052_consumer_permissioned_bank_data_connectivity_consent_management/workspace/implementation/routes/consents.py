"""Consent routes: capture/list/get/revoke, grants, per-recipient/per-consent listings."""

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_object, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_PARENT_NOT_OPERABLE,
    ERR_SCOPE_VIOLATES_MINIMIZATION, ERR_SCOPE_EXCEEDS_TIER,
    ERR_DUPLICATE_ACTIVE, ERR_UNAUTHORIZED,
)
from services import core
from services.serializers import consent_out, connection_out, grant_out
from routes.tiers import active_assignment_for_recipient

bp = Blueprint("consents", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "ComplianceReviewer", "Consumer", "Recipient")


def _get_consent(consent_id, apply_lazy=True):
    c = db.consents.get(consent_id)
    if c is None:
        raise err(ERR_NOT_FOUND, "ConsentRecord not found")
    if apply_lazy:
        core.lazy_expire(c)
    return c


@bp.route("/recipients/<recipientId>/consents", methods=["POST"])
def create_consent(recipientId):
    user_id, role = require_role("Consumer")
    r = db.recipients.get(recipientId)
    if r is None:
        raise err(ERR_NOT_FOUND, "Recipient not found")
    body = request.get_json(silent=True) or {}

    consumer_ref = body.get("consumer_ref")
    data_scopes = body.get("data_scopes")
    expires_at = body.get("expires_at")
    expected_version = body.get("expected_recipient_version")

    # Field-level presence checks come last in priority order (20), but we need
    # values to evaluate earlier gates. We validate presence of required fields
    # only as needed; malformed values get caught at the end. To keep the
    # priority ordering correct, evaluate OCC (6), parent operability (8),
    # minimization (9), tier coverage (10), uniqueness (17) before field
    # validity (20) where possible. Presence of required fields is needed for
    # those gates, so missing required fields surface as ERR_INVALID_REQUEST.

    # OCC (priority 6)
    if expected_version is not None:
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise err(ERR_INVALID_REQUEST, "expected_recipient_version must be an integer")
        if expected_version != r["version"]:
            raise err(ERR_STALE_VERSION, "expected_recipient_version does not match")

    # Parent operability (priority 8)
    if r["status"] != "APPROVED":
        raise err(ERR_PARENT_NOT_OPERABLE, "Recipient must be APPROVED to create consents")

    # consumer_ref must match caller (Consumer ownership)
    if not isinstance(consumer_ref, str) or not consumer_ref:
        raise err(ERR_INVALID_REQUEST, "consumer_ref must be a non-empty string")
    if consumer_ref != user_id:
        raise err(ERR_UNAUTHORIZED, "consumer_ref must match X-User-ID")

    if not isinstance(data_scopes, list) or not data_scopes:
        raise err(ERR_INVALID_REQUEST, "data_scopes must be a non-empty array")
    scope_set = set()
    for s in data_scopes:
        if s not in core.DATA_SCOPES:
            raise err(ERR_INVALID_REQUEST, f"data_scopes contains invalid scope {s}")
        scope_set.add(s)

    # Minimization (priority 9)
    forbidden = core.MINIMIZATION_FORBIDDEN[r["minimization_policy"]]
    if scope_set & forbidden:
        raise err(ERR_SCOPE_VIOLATES_MINIMIZATION,
                  "Consent scopes violate recipient minimization policy")

    # Tier coverage (priority 10)
    ta = active_assignment_for_recipient(r["id"])
    if ta is None:
        raise err(ERR_SCOPE_EXCEEDS_TIER,
                  "Recipient has no ACTIVE tier assignment covering the scopes")
    tier = db.tiers.get(ta["tier_id"])
    tier_scopes = set(tier["scopes_included"]) if tier else set()
    if not scope_set.issubset(tier_scopes):
        raise err(ERR_SCOPE_EXCEEDS_TIER,
                  "Consent scopes exceed the recipient's ACTIVE tier scopes_included")

    # expires_at parse
    exp_dt = core.parse_dt(expires_at, "expires_at") if expires_at is not None else None
    if exp_dt is None:
        raise err(ERR_INVALID_REQUEST, "expires_at is required")

    # Uniqueness (priority 17): no duplicate non-terminal consent for same
    # (consumer_ref, recipient_id, data_scopes set)
    for other in db.consents.values():
        if (other["recipient_id"] == r["id"]
                and other["consumer_ref"] == consumer_ref
                and other["status"] not in core.CONSENT_TERMINAL
                and set(other["data_scopes"]) == scope_set):
            raise err(ERR_DUPLICATE_ACTIVE,
                      "A non-terminal consent already exists for this consumer_ref, recipient, and scope set")

    consent = {
        "recipient_id": r["id"],
        "consumer_ref": consumer_ref,
        "data_scopes": sorted(scope_set),
        "expires_at": core.iso(exp_dt),
        "status": "ACTIVE",
        "revoked_at": None,
        "_expires_dt": exp_dt,
    }
    core.stamp_new(consent)
    db.consents[consent["id"]] = consent

    # materialize DataScopeGrant rows
    for scope in consent["data_scopes"]:
        g = {
            "id": db.new_id(),
            "created_at": db.now_iso(),
            "consent_id": consent["id"],
            "scope": scope,
        }
        db.data_scope_grants[g["id"]] = g

    # Supersede prior ACTIVE consents for the same (consumer_ref, recipient_id)
    for other in list(db.consents.values()):
        if (other["id"] != consent["id"]
                and other["recipient_id"] == r["id"]
                and other["consumer_ref"] == consumer_ref
                and other["status"] == "ACTIVE"):
            _supersede_consent(other, consent)

    core.touch(r)  # recipient version increments
    return success_object(consent_out(consent), 201)


def _supersede_consent(old_consent, new_consent):
    """ACTIVE -> SUPERSEDED with re-point-or-disconnect cascade.

    If the new consent's scopes are a superset of the old consent's scopes,
    connections are re-pointed to the new consent (CONNECTION_MIGRATED webhook);
    otherwise they are DISCONNECTED (CONSENT_REVOKED webhook).
    """
    old_scopes = set(old_consent["data_scopes"])
    new_scopes = set(new_consent["data_scopes"])
    is_superset = old_scopes.issubset(new_scopes)
    old_consent["status"] = "SUPERSEDED"
    core.touch(old_consent)
    for conn in list(db.connections.values()):
        if conn["consent_id"] != old_consent["id"]:
            continue
        if conn["status"] not in core.DISCONNECTABLE_CONN_STATES:
            continue
        if is_superset:
            conn["consent_id"] = new_consent["id"]
            core.touch(conn)
            core.emit_webhook(conn["id"], new_consent["recipient_id"],
                              "CONNECTION_MIGRATED",
                              {"old_consent_id": old_consent["id"],
                               "new_consent_id": new_consent["id"]})
        else:
            conn["status"] = "DISCONNECTED"
            core.touch(conn)
            core.emit_webhook(conn["id"], old_consent["recipient_id"],
                              "CONSENT_REVOKED", {"consent_id": old_consent["id"]})


@bp.route("/consents", methods=["GET"])
def list_consents():
    require_role(*ALL_READ_ROLES)
    limit, offset = parse_limit_offset(request.args)
    consumer_ref = request.args.get("consumer_ref")
    recipient_id = request.args.get("recipient_id")
    status_filter = request.args.get("status")
    items = []
    for c in db.consents.values():
        core.lazy_expire(c)
        if consumer_ref and c["consumer_ref"] != consumer_ref:
            continue
        if recipient_id and c["recipient_id"] != recipient_id:
            continue
        if status_filter and c["status"] != status_filter:
            continue
        items.append(c)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([consent_out(c) for c in page], limit, offset, total)


@bp.route("/consents/<consentId>", methods=["GET"])
def get_consent(consentId):
    require_role(*ALL_READ_ROLES)
    c = _get_consent(consentId)
    return success_object(consent_out(c))


@bp.route("/consents/<consentId>/revoke", methods=["POST"])
def revoke_consent(consentId):
    user_id, role = require_role("Consumer")
    c = _get_consent(consentId)
    # state check (priority 5)
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Consent is not ACTIVE")
    # ownership: X-User-ID must equal consumer_ref
    if c["consumer_ref"] != user_id:
        raise err(ERR_UNAUTHORIZED, "X-User-ID must equal consent consumer_ref")
    core.revoke_consent_cascade(c, actor_role=role)
    return success_object(consent_out(c))


@bp.route("/recipients/<recipientId>/consents", methods=["GET"])
def list_recipient_consents(recipientId):
    require_role(*ALL_READ_ROLES)
    r = db.recipients.get(recipientId)
    if r is None:
        raise err(ERR_NOT_FOUND, "Recipient not found")
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = []
    for c in db.consents.values():
        if c["recipient_id"] != r["id"]:
            continue
        core.lazy_expire(c)
        if status_filter and c["status"] != status_filter:
            continue
        items.append(c)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([consent_out(c) for c in page], limit, offset, total)


@bp.route("/consents/<consentId>/connections", methods=["GET"])
def list_consent_connections(consentId):
    require_role(*ALL_READ_ROLES)
    c = _get_consent(consentId)
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = [x for x in db.connections.values() if x["consent_id"] == c["id"]]
    if status_filter:
        items = [x for x in items if x["status"] == status_filter]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([connection_out(x) for x in page], limit, offset, total)


@bp.route("/consents/<consentId>/grants", methods=["GET"])
def list_consent_grants(consentId):
    require_role(*ALL_READ_ROLES)
    c = _get_consent(consentId)
    limit, offset = parse_limit_offset(request.args)
    # logically purged grants return empty set when a COMPLETED deletion
    # request exists for this consent
    purged = any(
        dr["consent_id"] == c["id"] and dr["status"] == "COMPLETED"
        for dr in db.deletion_requests.values()
    )
    if purged:
        items = []
    else:
        items = [g for g in db.data_scope_grants.values() if g["consent_id"] == c["id"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([grant_out(g) for g in page], limit, offset, total)
