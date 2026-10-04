"""Transparency seals: award and renewal (PRD 3.7)."""

from flask import Blueprint

import auth
import calc
import clock
import response
import store
import svc
import webutil
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ORG_NOT_IN_GOOD_STANDING,
    ERR_SEAL_DISCLOSURE_INSUFFICIENT,
    ERR_SEAL_LAPSED,
)

bp = Blueprint("seals", __name__)


@bp.route("/nonprofits/organizations/<org_id>/seals", methods=["POST"])
def award_seal(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_VERIFIER,))
    org = svc.get_organization(org_id)

    data = webutil.body()
    webutil.reject_unknown(data, ())

    # Gate 1 — the organization named in the request must be ACTIVE.
    if org.get("profile_status") != "ACTIVE":
        raise ApiError(
            ERR_ORG_NOT_IN_GOOD_STANDING,
            "A transparency seal may be awarded only to an ACTIVE organization.",
        )

    # Gate 2 — a second award while one seal is live.
    if svc.active_seal(org) is not None:
        raise ApiError(
            ERR_INVALID_STATE,
            "The organization already holds an ACTIVE transparency seal.",
        )

    # Gate 3 — the disclosure floor.
    level = calc.seal_level_award(org, svc.org_filings(org), svc.org_leaders(org))
    if level is None:
        raise ApiError(
            ERR_SEAL_DISCLOSURE_INSUFFICIENT,
            "disclosure_pct must be at least 0.50 to hold a transparency seal.",
        )

    awarded_on = clock.now()
    expires_on = clock.add_days(awarded_on, calc.SEAL_TERM_DAYS)
    seal = store.new_row(
        organization_id=org_id,
        level=level,
        disclosure_pct_at_award=org.get("disclosure_pct"),
        awarded_on=clock.fmt_dt(awarded_on),
        expires_on=clock.fmt_dt(expires_on),
        renewal_window_opens_on=clock.fmt_dt(clock.add_days(expires_on, -calc.RENEWAL_WINDOW_DAYS)),
        renewal_attempt_count=0,
        last_renewal_fee_cents=None,
        status="ACTIVE",
    )
    store.insert("seals", seal)

    org["transparency_seal_level"] = level
    org["seal_expires_on"] = seal["expires_on"]
    store.touch(org)
    return response.ok(svc.ser_seal(seal), status=201)


@bp.route("/nonprofits/seals/<seal_id>/renew", methods=["POST"])
def renew_seal(seal_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_VERIFIER,))
    seal = svc.get_seal(seal_id)

    data = webutil.body()
    webutil.reject_unknown(data, ())

    now = clock.now()
    expires_on = clock.parse_dt(seal.get("expires_on"))
    days_late = clock.floor_days(now, expires_on) if expires_on is not None else 0

    if seal.get("status") != "ACTIVE":
        # Renewal is declared only from ACTIVE. PRD 2.10 evaluates the state rung
        # (5) before the temporal window rung (10), so a seal that has already
        # left ACTIVE — LAPSED or REVOKED — reports the state error; the
        # ERR_SEAL_LAPSED branch belongs to the tier-3 refusal of a still-ACTIVE
        # seal. Every attempt still increments the attempt counter (PRD 3.7).
        seal["renewal_attempt_count"] = (seal.get("renewal_attempt_count") or 0) + 1
        store.touch(seal)
        raise ApiError(
            ERR_INVALID_STATE,
            "A seal in %s status cannot be renewed." % seal.get("status"),
        )

    org = svc.get_organization(seal.get("organization_id"))
    if org.get("profile_status") != "ACTIVE":
        raise ApiError(
            ERR_ORG_NOT_IN_GOOD_STANDING,
            "The owning organization is not ACTIVE.",
        )

    fee_cents, tier = calc.seal_renewal_fee_cents(seal.get("level"), days_late)
    seal["renewal_attempt_count"] = (seal.get("renewal_attempt_count") or 0) + 1

    if tier == 3:
        seal["status"] = "LAPSED"
        store.touch(seal)
        org["transparency_seal_level"] = "NONE"
        org["seal_expires_on"] = None
        store.touch(org)
        raise ApiError(
            ERR_SEAL_LAPSED,
            "The seal is %d days late and has lapsed." % days_late,
        )

    new_expires = clock.add_days(now, calc.SEAL_TERM_DAYS)
    seal["last_renewal_fee_cents"] = fee_cents
    seal["expires_on"] = clock.fmt_dt(new_expires)
    seal["renewal_window_opens_on"] = clock.fmt_dt(
        clock.add_days(new_expires, -calc.RENEWAL_WINDOW_DAYS)
    )
    store.touch(seal)
    org["seal_expires_on"] = seal["expires_on"]
    return response.ok(svc.ser_seal(seal))
