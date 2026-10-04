"""Distribution partners, promo codes, entitlements."""
from datetime import timedelta

import clock
import util
from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_FORBIDDEN, ERR_PROMO_QUOTA_EXHAUSTED, ERR_PROMO_INVALID,
)

BUNDLED_TIERS = {"AD_SUPPORTED", "PREMIUM"}


def create_partner(body):
    util.require_fields(body, ["partner_code", "display_name", "bundled_tier", "max_promo_codes"])
    util.req_str(body["partner_code"], "partner_code")
    util.req_str(body["display_name"], "display_name")
    util.req_enum(body["bundled_tier"], "bundled_tier", BUNDLED_TIERS)
    max_codes = util.req_int(body["max_promo_codes"], "max_promo_codes", minimum=0)
    for p in db.partners.values():
        if p["partner_code"] == body["partner_code"]:
            raise_err(ERR_INVALID_REQUEST, "partner_code must be unique")
    now_iso = clock.now_iso()
    partner = {
        "id": util.new_id(),
        "partner_code": body["partner_code"],
        "display_name": body["display_name"],
        "partner_status": "ACTIVE",
        "bundled_tier": body["bundled_tier"],
        "max_promo_codes": max_codes,
        "codes_issued": 0,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.partners[partner["id"]] = partner
    return partner


def issue_promo_code(partner):
    if partner["codes_issued"] >= partner["max_promo_codes"]:
        raise_err(ERR_PROMO_QUOTA_EXHAUSTED, "partner promo code quota exhausted")
    now = clock.now()
    now_iso = clock.now_iso()
    import secrets
    code = {
        "id": util.new_id(),
        "partner_id": partner["id"],
        "code": "PROMO-" + secrets.token_hex(6).upper(),
        "code_status": "ISSUED",
        "issued_at": now,
        "expires_at": now + timedelta(hours=72),
        "redeemed_by_viewer_id": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.promo_codes[code["id"]] = code
    partner["codes_issued"] += 1
    util.touch(partner)
    return code


def redeem_promo(body, actor_id):
    util.require_fields(body, ["code", "viewer_id"])
    viewer = db.viewers.get(body["viewer_id"])
    pc = None
    for c in db.promo_codes.values():
        if c["code"] == body["code"]:
            pc = c
            break
    # Existence check, left-to-right on body references: code then viewer
    if pc is None:
        raise_err(ERR_NOT_FOUND, "promo code not found")
    if viewer is None:
        raise_err(ERR_NOT_FOUND, "viewer not found")
    if body["viewer_id"] != actor_id:
        raise_err(ERR_FORBIDDEN, "viewer may only redeem for itself")

    partner = db.partners.get(pc["partner_id"])
    now = clock.now()
    valid = (
        pc["code_status"] == "ISSUED"
        and now < pc["expires_at"]
        and partner is not None and partner["partner_status"] == "ACTIVE"
        and not any(
            e["viewer_id"] == viewer["id"] and e["source_type"] == "PARTNER_BUNDLE" and e["active"]
            for e in db.entitlements.values()
        )
    )
    if not valid:
        raise_err(ERR_PROMO_INVALID, "promo code not redeemable")

    pc["code_status"] = "REDEEMED"
    pc["redeemed_by_viewer_id"] = viewer["id"]
    util.touch(pc)

    ent = {
        "id": util.new_id(),
        "viewer_id": viewer["id"],
        "source_type": "PARTNER_BUNDLE",
        "partner_id": partner["id"],
        "tier_granted": partner["bundled_tier"],
        "active_from": now,
        "active": True,
        "created_at": clock.now_iso(),
    }
    db.entitlements[ent["id"]] = ent

    viewer["subscription_tier"] = partner["bundled_tier"]
    viewer["subscription_status"] = "ACTIVE"
    viewer["grace_entered_at"] = None
    if viewer.get("acquisition_source") is None:
        viewer["acquisition_source"] = "PARTNER_BUNDLE"
    util.touch(viewer)
    return ent


def revoke_promo(pc):
    if pc["code_status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "promo code not ISSUED")
    pc["code_status"] = "REVOKED"
    util.touch(pc)
    return pc
