"""Test-driving controls and the liveness probe (outside the business surface).

These are the only endpoints exempt from the authentication rung, together with
the two phase-boundary roll parameters.
"""

from flask import Blueprint

from db import DB, DEFAULT_CLOCK_ISO, iso3, new_id, parse_iso
from errors import ApiError
from middleware import (ALLOCATION_PLANNER, CUSTOMER_SERVICE,
                        FULFILLMENT_OPERATOR, GIVING_PARTNER_COORDINATOR,
                        IMPACT_AUDITOR, MARKETING_MANAGER, PROVISIONING_PARTNER,
                        roles)
from response import success
from validation import as_instant, body, require

bp = Blueprint("operator", __name__)

CLOCK_ROLES = [IMPACT_AUDITOR, PROVISIONING_PARTNER, GIVING_PARTNER_COORDINATOR]


def _roll(to_instant):
    """Apply every deterministic consequence of moving the logical clock.

    Returns the list of human-readable rollover events.
    """
    events = []
    previous = DB.now()
    if to_instant < previous:
        materialized = False
        for season in DB.impact_seasons.values():
            if season.get("status") in ("FROZEN", "CLOSED", "FINALIZED"):
                materialized = True
        if materialized:
            raise ApiError("ERR_CLOCK_ROLL_CONFLICT")
    for season in DB.impact_seasons.values():
        if season.get("status") == "FINALIZED":
            continue
        start = parse_iso(season["starts_at"])
        freeze = parse_iso(season["freezes_at"])
        if to_instant < start:
            continue

        if season.get("status") == "PLANNED":
            # Opening demotes provisional receipts taken inside a PLANNED season.
            for dist in DB.season_distributions(season["id"]):
                if dist.get("status") == "RECEIVED":
                    dist["status"] = "SHIPPED"
                    dist["received_units"] = 0
                    dist["impact_units_confirmed"] = 0
                    dist["received_at"] = None
                    DB.touch(dist)
            season["status"] = "OPEN"
            events.append("season %s opened" % season.get("season_code"))

        if season.get("status") == "OPEN" and to_instant >= freeze:
            blocked = any(c.get("status") not in
                          ("DRAFT", "SUBSTANTIATED", "OVERSTATED", "UNSUBSTANTIATED",
                           "SEASON_RESTRICTED")
                          for c in DB.season_claims(season["id"]))
            if not blocked:
                season["status"] = "FROZEN"
                events.append("season %s frozen" % season.get("season_code"))
                for liability in DB.season_liabilities(season["id"]):
                    if liability.get("status") in ("ACCUMULATING", "CARRIED"):
                        from services import core as core_service
                        core_service.recompute_liability(liability)
                        liability["status"] = "FROZEN"
                        liability["frozen_units"] = liability.get("provisional_liability_units") or 0
                        liability["donation_liability_units"] = liability.get("final_liability_units") or 0
                        liability["freeze_recorded_at"] = iso3(to_instant)
                        cost = 0
                        for variant in DB.product_lines(liability.get("donation_product_id")):
                            cost = variant.get("unit_obligation_cost_cents") or 0
                            break
                        liability["accrued_obligation_cents"] = (
                            (liability.get("obligation_units") or 0) * cost)

    DB.set_clock(to_instant)

    from services import core as core_service

    # Product-line sunset transitions re-evaluated in one step.
    frozen_now = core_service.DB.frozen_season()
    frozen_code = frozen_now.get("season_code") if frozen_now else None
    for season in DB.impact_seasons.values():
        if season.get("status") != "FROZEN":
            continue
        if not (parse_iso(season["starts_at"]) <= to_instant < parse_iso(season["ends_at"])):
            continue
        events.append("season %s holds the clock" % season.get("season_code"))
    for variant in DB.donation_product_lines.values():
        product = DB.product(variant.get("donation_product_id"))
        if not product:
            continue
        if product.get("design_channel") != "DONATION_ONLY":
            continue
        if product.get("obligation_model") != "AT_VESTING":
            continue
        # PRD 3.4: a donation-only, at-vesting variant is excluded from every
        # later season once the season holding the clock reaches FROZEN,
        # whichever of ACTIVE or VESTED it had reached.
        if variant.get("status") not in ("ACTIVE", "VESTED"):
            continue
        if frozen_code is not None:
            variant["status"] = "SUNSET"
            DB.touch(variant)
            events.append("line %s sunset" % variant["id"])

    core_service.reconcile_all()
    for season in DB.impact_seasons.values():
        core_service.recompute_season(season)

    # PRD §3.1: "If the logical clock passes a round's `valid_until` while the
    # round is still `REQUESTED`, the system expires it: the round's outcome
    # becomes `EXPIRED`, the partner returns to `CANDIDATE`, and — when the
    # season containing the current clock has reached `FROZEN` or `CLOSED` —
    # a capacity profile is created for the next `PLANNED` season."  A round
    # that has advanced past `REQUESTED` but has not reached a terminal outcome
    # is still an in-flight review, so its `valid_until` lapse expires it too.
    holding = DB.season_containing(to_instant)
    for vetting in DB.vetting_rounds.values():
        if vetting.get("outcome") not in ("REQUESTED", "DOCUMENTS_SUBMITTED",
                                          "EVALUATING"):
            continue
        valid_until = vetting.get("valid_until")
        if not valid_until or parse_iso(valid_until) >= to_instant:
            continue
        vetting["outcome"] = "EXPIRED"
        DB.touch(vetting)
        partner = DB.partner(vetting.get("partner_id"))
        if partner is not None:
            partner["status"] = "CANDIDATE"
            DB.touch(partner)
        events.append("vetting round %s expired" % vetting.get("id"))
        if holding is not None and holding.get("status") in ("FROZEN", "CLOSED"):
            _profile_for_next_planned_season(partner)

    return events


def _profile_for_next_planned_season(partner):
    """PRD §3.1's expiry cascade opens a ceiling for the next PLANNED season."""
    if partner is None:
        return None
    upcoming = [s for s in DB.impact_seasons.values() if s.get("status") == "PLANNED"]
    if not upcoming:
        return None
    upcoming.sort(key=lambda s: parse_iso(s["starts_at"]))
    season = upcoming[0]
    for profile in DB.capacity_profiles.values():
        if profile.get("partner_id") == partner["id"] \
                and profile.get("season_code") == season.get("season_code"):
            return profile
    record = {
        "id": new_id(),
        "created_at": iso3(DB.now()),
        "updated_at": iso3(DB.now()),
        "version": 1,
        "partner_id": partner["id"],
        "season_code": season.get("season_code"),
        "max_allocatable_units": 0,
        "reserved_units": 0,
        "committed_units": 0,
        "capacity_utilization_units": 0,
        "effective_from": iso3(parse_iso(season["starts_at"])),
        "effective_to": iso3(parse_iso(season["ends_at"])),
        "status": "ACTIVE",
        "need_tier": partner.get("need_tier"),
        "_system_created": True,
    }
    DB.capacity_profiles[record["id"]] = record
    return record


@bp.route("/_clock/set_current_utc", methods=["POST"])
@roles(*CLOCK_ROLES)
def set_clock():
    payload = body()
    require(payload, "to_iso8601")
    to_instant = as_instant(payload, "to_iso8601", required=True)
    events = _roll(to_instant)
    season = DB.season_containing()
    return success({
        "current_utc": iso3(DB.now()),
        "rolling_season_code": season.get("season_code") if season else None,
        "rollover_events": events,
    })


@bp.route("/_seasons/roll", methods=["POST"])
@roles(*CLOCK_ROLES)
def roll_seasons():
    payload = body()
    require(payload, "to_iso8601")
    to_instant = as_instant(payload, "to_iso8601", required=True)
    events = _roll(to_instant)
    rewritten = 0
    for liability in DB.donation_liabilities.values():
        rewritten += 1
    veil = sum(1 for p in DB.giving_partners.values()
               if p.get("status") in ("VETTING", "CANDIDATE"))
    return success({
        "rolled_to": iso3(DB.now()),
        "seasons_transitioned": len(events),
        "ledger_rows_rewritten": rewritten,
        "rollover_events": events + (["partners_reveiled=%d" % veil] if veil else []),
    })


@bp.route("/_healthz", methods=["GET"])
@roles(ALLOCATION_PLANNER, CUSTOMER_SERVICE, FULFILLMENT_OPERATOR,
       GIVING_PARTNER_COORDINATOR, IMPACT_AUDITOR, MARKETING_MANAGER,
       PROVISIONING_PARTNER)
def healthz():
    return success({
        "status": "ok",
        "logical_clock_default": DEFAULT_CLOCK_ISO,
        "server_started_at": iso3(DB.started_at),
    })