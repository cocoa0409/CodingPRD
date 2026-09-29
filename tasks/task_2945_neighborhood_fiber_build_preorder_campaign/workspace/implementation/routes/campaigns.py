"""Campaigns, the qualification run and the sequencing run (PRD 3.1, 3.4, 3.5)."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("campaigns", __name__)

READ_ROLES = auth.ALL_ROLES


@bp.post("/campaigns")
def create_campaign():
    auth.gate(("ProgramManager",))
    data = shape.body()
    name = shape.req_str(data, "name", 1, 120, blank_ok=False)
    city = shape.req_str(data, "city", 1, 80)
    open_at = shape.req_dt(data, "prereg_window_open_at")
    close_at = shape.req_dt(data, "prereg_window_close_at")
    if close_at <= open_at:
        shape.bad("prereg_window_close_at", "must be strictly after prereg_window_open_at")
    row = new_row(
        {
            "name": name,
            "city": city,
            "prereg_window_open_at": open_at,
            "prereg_window_close_at": close_at,
            "default_threshold_pct": shape.req_dec(data, "default_threshold_pct", "0.01", "100.00"),
            "deposit_amount_cents": shape.req_int(data, "deposit_amount_cents", 0),
            "max_deadline_extensions": shape.opt_int(data, "max_deadline_extensions", 0, 5, 2),
            "extension_grant_days": shape.opt_int(data, "extension_grant_days", 1, 90, 30),
            "claim_filing_window_days": shape.opt_int(data, "claim_filing_window_days", 1, 365, 45),
            "restoration_sla_days": shape.opt_int(data, "restoration_sla_days", 1, 60, 7),
            "late_filing_factor": shape.opt_dec(
                data, "late_filing_factor", "0.00", "1.00", calc.pct("0.60")
            ),
        }
    )
    insert("campaigns", row)
    return envelope.created(serialize.campaign(row))


@bp.get("/campaigns/<campaign_id>")
def read_campaign(campaign_id):
    auth.gate(READ_ROLES)
    row = must_find("campaigns", campaign_id)
    return envelope.ok(serialize.campaign(row))


@bp.get("/campaigns")
def list_campaigns():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(ordered(rows("campaigns")), (listing.text("city", "city"),))
    return envelope.list_response(items, serialize.campaign)


def _campaign_zones(campaign_id):
    return ordered([z for z in rows("build_zones") if z["campaign_id"] == campaign_id])


@bp.post("/campaigns/<campaign_id>/qualification-run")
def qualification_run(campaign_id):
    auth.gate(("ProgramManager",))
    campaign = must_find("campaigns", campaign_id)
    zones = _campaign_zones(campaign["id"])
    open_zones = [z for z in zones if z["campaign_status"] in ("PREREG_OPEN", "PREREG_EXTENDED")]
    due = [z for z in open_zones if z["prereg_deadline_at"] < now()]
    if not due:
        raise ApiError(
            "ERR_PREREG_DEADLINE_NOT_REACHED",
            "no open zone of this campaign has passed its preregistration deadline",
        )
    for zone in due:
        _evaluate_zone(zone)
    return envelope.array([serialize.build_zone(z) for z in due])


def _evaluate_zone(zone):
    count, rate = calc.prereg_rate(zone, "FINAL")
    zone["final_qualifying_count"] = count
    zone["final_rate_pct"] = rate
    qualified = rate >= zone["threshold_pct"]
    zone["campaign_status"] = "QUALIFIED" if qualified else "NOT_QUALIFIED"
    bump(zone)
    if qualified:
        _qualify_preorders(zone)
    else:
        _fail_zone(zone)


def _lapse(preorder, reason):
    preorder["preorder_status"] = "LAPSED"
    preorder["lapse_reason"] = reason
    if preorder["deposit_status"] == "HELD":
        cascades.move_deposit(preorder, "REFUNDED", "DEPOSIT_REFUNDED")
    bump(preorder)


def _qualify_preorders(zone):
    for preorder in ordered(calc.zone_preorders(zone["id"])):
        if preorder["preorder_status"] != "PENDING":
            continue
        if calc.preorder_counts(preorder):
            preorder["preorder_status"] = "QUALIFIED"
            bump(preorder)
        else:
            _lapse(preorder, "ADDRESS_NOT_COUNTED")


def _fail_zone(zone):
    lapsed_addresses = []
    for preorder in ordered(calc.zone_preorders(zone["id"])):
        if preorder["preorder_status"] != "PENDING":
            continue
        _lapse(preorder, "ZONE_NOT_QUALIFIED")
        if preorder["service_address_id"] not in lapsed_addresses:
            lapsed_addresses.append(preorder["service_address_id"])
    for address in ordered(calc.zone_addresses(zone["id"])):
        touched = False
        lapsed_here = address["id"] in lapsed_addresses
        if lapsed_here or address["serviceability"] in ("UNDETERMINED", "CONDITIONAL_MDU"):
            if address["serviceability"] != "NOT_SERVICEABLE":
                address["serviceability"] = "NOT_SERVICEABLE"
                address["not_serviceable_reason"] = "BUILD_NOT_QUALIFIED"
                touched = True
        if lapsed_here and address["exception_status"] == "NONE":
            address["exception_status"] = "REQUESTED"
            address["exception_reason"] = "zone build did not qualify"
            touched = True
        if touched:
            bump(address)


@bp.post("/campaigns/<campaign_id>/sequencing-run")
def sequencing_run(campaign_id):
    auth.gate(("ProgramManager",))
    campaign = must_find("campaigns", campaign_id)
    candidates = [
        z for z in _campaign_zones(campaign["id"]) if z["campaign_status"] == "QUALIFIED"
    ]
    for zone in candidates:
        zone["readiness_score"] = calc.readiness_score(zone)
    candidates.sort(
        key=lambda z: (
            -z["readiness_score"],
            z["prereg_deadline_at"],
            -z["household_count"],
            z["created_at"],
            z["_seq"],
        )
    )
    for index, zone in enumerate(candidates, start=1):
        zone["build_sequence_index"] = index
        if zone["construction_status"] == "NOT_STARTED":
            zone["construction_status"] = "SEQUENCED"
        bump(zone)
    return envelope.array([serialize.build_zone(z) for z in candidates])
