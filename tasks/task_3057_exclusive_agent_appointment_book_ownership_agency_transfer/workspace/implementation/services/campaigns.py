"""Marketing campaigns and the allowance ledger (PRD §3.4)."""

from decimal import Decimal

import clock
import db
import middleware
import occ
from errors import (
    ApiError, ERR_AGENCY_STAFFING_CAP, ERR_ALLOWANCE_INSUFFICIENT, ERR_INTERVAL_OVERLAP,
    ERR_INVALID_STATE,
)
from money import dec, round_cents
from services import calculations as calc
from services import factories, recompute

POSTURE_OPEN = "OPEN"
LIVE_AGENCY_STATES = ("APPROVED", "ACTIVE")


def create(agency, payload):
    _require_open(agency)
    start = payload.get("start_date")
    end = payload.get("end_date")
    _check_overlap(agency["id"], start, end, exclude_id=None)

    campaign = factories.create_campaign(agency, payload)
    return campaign


def list_campaigns(agency, request):
    rows = [c for c in db.campaign_rows().values() if c["agency_id"] == agency["id"]]
    rows.sort(key=lambda c: c["created_at"])
    return rows


def posture(agency):
    return factories.participation_posture(agency)


def _require_open(agency):
    if posture(agency) != POSTURE_OPEN:
        raise ApiError(ERR_INVALID_STATE)


def _require_editable(agency, campaign):
    _require_open(agency)
    if campaign["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE)
    if agency["status"] not in LIVE_AGENCY_STATES:
        raise ApiError(ERR_INVALID_STATE)


def _check_overlap(agency_id, start, end, exclude_id):
    """Closed intervals must not collide with a sibling over the same owner."""
    if start is None or end is None:
        return
    lo = clock.parse_iso(start)
    hi = clock.parse_iso(end)
    for other in db.campaign_rows().values():
        if other["agency_id"] != agency_id:
            continue
        if other["id"] == exclude_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        other_start = other.get("start_date")
        other_end = other.get("end_date")
        if other_start is None or other_end is None:
            continue
        olo = clock.parse_iso(other_start)
        ohi = clock.parse_iso(other_end)
        if lo <= ohi and olo <= hi:
            raise ApiError(ERR_INTERVAL_OVERLAP)


def update(agency, campaign, payload):
    _require_editable(agency, campaign)
    _check_overlap(agency["id"],
                   payload.get("start_date", campaign.get("start_date")),
                   payload.get("end_date", campaign.get("end_date")),
                   exclude_id=campaign["id"])
    if "marketing_allowance_cents" in payload:
        campaign["marketing_allowance_cents"] = round_cents(
            dec(payload.get("marketing_allowance_cents") or 0))
    if "expected_leads" in payload:
        campaign["expected_leads"] = payload.get("expected_leads")
    campaign["participation_posture"] = posture(agency)
    recompute.touch(campaign)
    return campaign


def participate(agency, campaign, expected_agency_version):
    _require_open(agency)
    # The stale version is refused before any fiscal computation (PRD §2.12).
    occ.check(agency, expected_agency_version, "expected_agency_version")

    if campaign["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE)

    agreement = _agreement_for(agency)
    # The carryover that heads the ledger is the balance the term OPENED with
    # (established at the term rollover); spend accumulates against it inside
    # the term, so the pool never absorbs an already-spent draw twice.
    carryover = agreement.get("carryover_input_cents", Decimal(0)) if agreement \
        else Decimal(0)
    pool = calc.marketing_allowance_pool_cents(agency["id"], carryover)
    spent = calc.marketing_allowance_spent_cents(agency["id"])
    remaining = round_cents(pool - spent)
    draw = dec(campaign["marketing_allowance_cents"])
    if remaining < draw:
        raise ApiError(ERR_ALLOWANCE_INSUFFICIENT)

    campaign["status"] = "PARTICIPATED"
    campaign["participation_posture"] = posture(agency)
    recompute.touch(campaign)

    recompute.recompute_agency(agency["id"])
    return campaign


def cancel(agency, campaign):
    _require_open(agency)
    if campaign["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE)
    campaign["status"] = "CANCELLED"
    campaign["participation_posture"] = posture(agency)
    recompute.touch(campaign)
    return campaign


def _agreement_for(agency):
    rows = recompute.agreements_for(agency["id"])
    return rows[0] if rows else None