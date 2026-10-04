"""Consent and privacy routes."""
from flask import Blueprint, request
from db import db, now, touch
from errors import (ApiError, err_forbidden, err_not_found, err_invalid_request,
                    ERR_INVALID_STATE, ERR_CONSENT_NOT_GRANTED,
                    ERR_MINOR_CONSENT_LOCKED, ERR_PRIVACY_SELF_ONLY,
                    ERR_STALE_VERSION)
from middleware import (get_actor, require_roles, require_circle_member,
                        require_not_frozen)
from response import success, list_response, pagination_params
from serializers import ser, ser_many
from services import (append_consent_record, on_consent_revoked,
                      recompute_member_interval)
from routes_circles import _get_circle_or_404, _get_member_or_404

bp = Blueprint("consent", __name__)

SCOPES = {"LOCATION", "DRIVING", "CRASH", "FULL"}
PRIVACY_MODES = {"PRECISE", "BLURRED", "HIDDEN"}


def _actor_member(actor, circle):
    m = actor.member
    if m is None or m["circle_id"] != circle["id"]:
        raise err_forbidden()
    return m


@bp.route("/api/circles/<circle_id>/members/<member_id>/consent/grant", methods=["POST"])
def grant_consent(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor"})
    circle = _get_circle_or_404(circle_id)
    target = _get_member_or_404(circle, member_id)
    require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    actor_m = _actor_member(actor, circle)
    require_not_frozen(circle)

    body = request.get_json(silent=True) or {}
    scope = body.get("scope")
    if scope not in SCOPES:
        raise err_invalid_request("scope must be one of LOCATION, DRIVING, CRASH, FULL")
    monetization_opt_in = bool(body.get("monetization_opt_in", False))

    # Actor matrix
    if target["role"] == "MINOR":
        if actor_m["role"] not in ("OWNER", "ADMIN") or actor_m["id"] == target["id"]:
            raise err_forbidden("MINOR grant requires OWNER/ADMIN other than target")
    else:
        if not (actor_m["id"] == target["id"] or actor_m["role"] == "OWNER"):
            raise err_forbidden("Adult grant requires self or OWNER")

    # EXPIRED re-entry requires FULL scope
    if target["consent_state"] == "EXPIRED" and scope != "FULL":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Re-grant from EXPIRED requires FULL scope")

    target["consent_state"] = "GRANTED"
    target["monetization_opt_in"] = monetization_opt_in
    recompute_member_interval(target, circle)
    touch(target)
    rec = append_consent_record(target, actor_m["id"], scope, "GRANT",
                                monetization_opt_in=monetization_opt_in)
    return success(ser(rec))


@bp.route("/api/circles/<circle_id>/members/<member_id>/consent/revoke", methods=["POST"])
def revoke_consent(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor"})
    circle = _get_circle_or_404(circle_id)
    target = _get_member_or_404(circle, member_id)
    require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    actor_m = _actor_member(actor, circle)
    require_not_frozen(circle)

    if target["role"] == "MINOR":
        if actor_m["role"] != "OWNER":
            raise ApiError(ERR_MINOR_CONSENT_LOCKED, 403,
                           "Only OWNER may revoke a MINOR's consent")
    else:
        if not (actor_m["id"] == target["id"] or actor_m["role"] in ("OWNER", "ADMIN")):
            raise err_forbidden()

    if target["consent_state"] != "GRANTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Consent not GRANTED")

    target["consent_state"] = "REVOKED"
    touch(target)
    rec = append_consent_record(target, actor_m["id"], "FULL", "REVOKE",
                                monetization_opt_in=target.get("monetization_opt_in", False))
    on_consent_revoked(target)
    return success(ser(rec))


@bp.route("/api/circles/<circle_id>/members/<member_id>/consent-records", methods=["GET"])
def list_consent_records(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    target = _get_member_or_404(circle, member_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    items = [r for r in db.consent_records.values() if r["member_id"] == target["id"]]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/consent-records/<rec_id>", methods=["GET"])
def get_consent_record(rec_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    rec = db.consent_records.get(rec_id)
    if rec is None:
        raise err_not_found("Consent record not found")
    if not actor.is_system:
        member = db.members.get(rec["member_id"])
        circle = db.circles.get(member["circle_id"]) if member else None
        if circle is None:
            raise err_not_found("Consent record not found")
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    return success(ser(rec))


@bp.route("/api/consent-records", methods=["GET"])
def list_consent_records_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.consent_records.values())
    member_id = request.args.get("member_id")
    granted_by = request.args.get("granted_by_member_id")
    if member_id:
        items = [r for r in items if r["member_id"] == member_id]
    if granted_by:
        items = [r for r in items if r["granted_by_member_id"] == granted_by]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

@bp.route("/api/circles/<circle_id>/members/<member_id>/privacy", methods=["PATCH"])
def patch_privacy(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor"})
    circle = _get_circle_or_404(circle_id)
    target = _get_member_or_404(circle, member_id)
    require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    actor_m = actor.member
    require_not_frozen(circle)

    body = request.get_json(silent=True) or {}
    new_mode = body.get("privacy_mode")
    if new_mode not in PRIVACY_MODES:
        raise err_invalid_request("privacy_mode must be one of PRECISE, BLURRED, HIDDEN")
    expected = body.get("expected_member_version")
    if expected is None:
        raise err_invalid_request("expected_member_version is required")
    if expected != target["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale member version")

    cur = target["privacy_mode"]
    is_self = actor_m is not None and actor_m["id"] == target["id"]

    # Anti-coercion: HIDDEN -> PRECISE self only
    if cur == "HIDDEN" and new_mode == "PRECISE" and not is_self:
        raise ApiError(ERR_PRIVACY_SELF_ONLY, 403,
                       "HIDDEN -> PRECISE allowed only for the member themselves")

    # Consent gate for -> HIDDEN
    if new_mode == "HIDDEN" and cur != "HIDDEN":
        if target["consent_state"] != "GRANTED":
            raise ApiError(ERR_CONSENT_NOT_GRANTED, 409,
                           "HIDDEN requires consent_state GRANTED")

    # Declared transitions only (per §1.2 privacy machine)
    allowed = (
        (cur == "PRECISE" and new_mode in ("BLURRED", "HIDDEN")) or
        (cur == "BLURRED" and new_mode in ("PRECISE", "HIDDEN")) or
        (cur == "HIDDEN" and new_mode == "PRECISE")
    )
    if cur == new_mode:
        allowed = True  # no-op rewrite of the same mode
    if not allowed:
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Privacy transition {cur} -> {new_mode} not allowed")

    target["privacy_mode"] = new_mode
    if cur == "HIDDEN" and new_mode == "PRECISE" and is_self:
        target["tension_flag"] = False
    if target["role"] == "MINOR" and not is_self and new_mode != "PRECISE":
        # Parent-imposed override on a MINOR away from PRECISE / into HIDDEN
        if cur == "PRECISE" or new_mode == "HIDDEN":
            target["tension_flag"] = True
    touch(target)
    return success(ser(target))
