"""Campaign endpoints: schedule, get, list, start, abort, complete,
record-production, auto-allocate (the allocation waterfall)."""
from flask import Blueprint, request

import cascades
import clock
import constants as C
import serializers
import store
from calculations import (
    allocated_units,
    campaign_days,
    changeover_total_cents,
    expected_good_units,
    provisional_yield_rate,
    realized_yield_value,
    supply_coverage_value,
    unit_cost_cents,
)
from errors import (
    ApiError,
    ERR_CAMPAIGN_NOT_ENDED,
    ERR_CAMPAIGN_NOT_STARTED,
    ERR_CAMPAIGN_OVER_CAPACITY,
    ERR_COMPOSITION_NOT_QUALIFIED,
    ERR_INVALID_CAMPAIGN_WINDOW,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NONPOSITIVE_UNITS,
    ERR_NOT_FOUND,
    ERR_TANK_SCHEDULE_CONFLICT,
    ERR_TANK_UNDER_CONSTRUCTION,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_CAPACITY_PLANNER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_int,
    as_datetime,
    pagination_args,
)

bp = Blueprint("campaigns", __name__)

NON_TERMINAL_CAMPAIGN = {"SCHEDULED", "RUNNING"}
_TIER_RANK = {"TIER_A": 3, "TIER_B": 2, "TIER_C": 1}


def _get_campaign_or_404(campaign_id):
    campaign = store.campaigns.get(campaign_id)
    if campaign is None:
        raise ApiError(ERR_NOT_FOUND, "Campaign not found")
    return campaign


@bp.route("/glass/campaigns", methods=["POST"])
def create_campaign():
    authenticate({ROLE_CAPACITY_PLANNER})
    body = get_body()
    tank_id = as_str(req_field(body, "tank_id"), "tank_id")
    composition_id = as_str(req_field(body, "composition_id"), "composition_id")
    start = as_datetime(req_field(body, "start_date"), "start_date")
    end = as_datetime(req_field(body, "end_date"), "end_date")
    planned = as_int(req_field(body, "planned_units"), "planned_units")
    tank = store.tanks.get(tank_id)
    if tank is None:
        raise ApiError(ERR_NOT_FOUND, "Tank not found")
    composition = store.compositions.get(composition_id)
    if composition is None:
        raise ApiError(ERR_NOT_FOUND, "Composition not found")
    # Priority 12: window shape and length.
    days = campaign_days(start, end)
    if end <= start or days < C.MIN_CAMPAIGN_DAYS or days > C.MAX_CAMPAIGN_DAYS:
        raise ApiError(
            ERR_INVALID_CAMPAIGN_WINDOW,
            "Window must be strictly positive and span {}-{} days".format(
                C.MIN_CAMPAIGN_DAYS, C.MAX_CAMPAIGN_DAYS
            ),
        )
    # Priority 13: tank schedule — half-open overlap vs non-terminal windows;
    # changeover gap vs every existing different-composition campaign.
    for other in store.campaigns.values():
        if other["tank_id"] != tank["id"]:
            continue
        overlap = start < other["end_date"] and other["start_date"] < end
        if overlap:
            if other["status"] in NON_TERMINAL_CAMPAIGN:
                raise ApiError(
                    ERR_TANK_SCHEDULE_CONFLICT,
                    "Window overlaps a non-terminal campaign on this tank",
                )
            continue
        if other["composition_id"] != composition["id"]:
            if end <= other["start_date"]:
                gap = (other["start_date"] - end).days
            else:
                gap = (start - other["end_date"]).days
            if gap < C.CHANGEOVER_GAP_DAYS:
                raise ApiError(
                    ERR_TANK_SCHEDULE_CONFLICT,
                    "Changeover gap below {} days".format(C.CHANGEOVER_GAP_DAYS),
                )
    # Priority 17: composition maturity, then tank readiness.
    if composition["status"] not in ("TUNED", "QUALIFIED", "LOCKED"):
        raise ApiError(
            ERR_COMPOSITION_NOT_QUALIFIED,
            "Campaign creation requires TUNED, QUALIFIED, or LOCKED",
        )
    if tank["status"] != "COMMISSIONED":
        raise ApiError(ERR_TANK_UNDER_CONSTRUCTION, "Tank is not COMMISSIONED")
    # Priority 21: positivity then capacity.
    if planned <= 0:
        raise ApiError(ERR_NONPOSITIVE_UNITS, "planned_units must be strictly positive")
    if planned > tank["capacity_units_per_day"] * days:
        raise ApiError(ERR_CAMPAIGN_OVER_CAPACITY, "planned_units exceeds tank capacity")
    # Provisional yield / cost variants, computed at scheduling time.
    rate = provisional_yield_rate(planned)
    expected = expected_good_units(planned)
    new_ref = {"id": None, "tank_id": tank["id"], "start_date": start}
    prior = cascades.prior_campaign(new_ref)
    changeover = changeover_total_cents(prior, composition["id"], days)
    cost = unit_cost_cents(composition["complexity_multiplier"], planned, rate, changeover)
    campaign = store.base_fields()
    campaign.update(
        {
            "tank_id": tank["id"],
            "composition_id": composition["id"],
            "start_date": start,
            "end_date": end,
            "planned_units": planned,
            "status": "SCHEDULED",
            "expected_good_units": expected,
            "unallocated_units": expected,
            "cumulative_good_units": 0,
            "cumulative_scrap_units": 0,
            "realized_yield": None,
            "provisional_unit_cost_cents": cost,
            "final_unit_cost_cents": None,
        }
    )
    store.campaigns[campaign["id"]] = campaign
    return success_object(serializers.campaign(campaign), status=201)


@bp.route("/glass/campaigns/<campaignId>", methods=["GET"])
def get_campaign(campaignId):
    authenticate(ALL_ROLES)
    return success_object(serializers.campaign(_get_campaign_or_404(campaignId)))


@bp.route("/glass/campaigns", methods=["GET"])
def list_campaigns():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_tank = request.args.get("tank_id")
    f_comp = request.args.get("composition_id")
    f_status = request.args.get("status")
    items = list(store.campaigns.values())
    if f_tank is not None:
        items = [c for c in items if c["tank_id"] == f_tank]
    if f_comp is not None:
        items = [c for c in items if c["composition_id"] == f_comp]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.campaign(c) for c in page], limit, offset, total)


@bp.route("/glass/campaigns/<campaignId>/start", methods=["POST"])
def start_campaign(campaignId):
    authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    campaign = _get_campaign_or_404(campaignId)
    if campaign["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "start requires SCHEDULED")
    # The half-open window excludes its end instant: start at/after end_date
    # is a state-legality failure (PRD 2.8 row 6).
    if clock.now() >= campaign["end_date"]:
        raise ApiError(ERR_INVALID_STATE, "Campaign window has already ended")
    if clock.now() < campaign["start_date"]:
        raise ApiError(ERR_CAMPAIGN_NOT_STARTED, "Campaign start_date not reached")
    composition = store.compositions[campaign["composition_id"]]
    if composition["status"] not in ("QUALIFIED", "LOCKED"):
        raise ApiError(
            ERR_COMPOSITION_NOT_QUALIFIED, "Campaign start requires QUALIFIED or LOCKED"
        )
    tank = store.tanks[campaign["tank_id"]]
    if tank["status"] != "COMMISSIONED":
        raise ApiError(ERR_TANK_UNDER_CONSTRUCTION, "Tank is not COMMISSIONED")
    campaign["status"] = "RUNNING"
    store.touch(campaign)
    return success_object(serializers.campaign(campaign))


@bp.route("/glass/campaigns/<campaignId>/complete", methods=["POST"])
def complete_campaign(campaignId):
    authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    campaign = _get_campaign_or_404(campaignId)
    if campaign["status"] != "RUNNING":
        raise ApiError(ERR_INVALID_STATE, "complete requires RUNNING")
    if clock.now() < campaign["end_date"]:
        raise ApiError(ERR_CAMPAIGN_NOT_ENDED, "Campaign end_date not reached")
    campaign["status"] = "COMPLETED"
    cascades.finalize_campaign(campaign)
    store.touch(campaign)
    return success_object(serializers.campaign(campaign))


@bp.route("/glass/campaigns/<campaignId>/abort", methods=["POST"])
def abort_campaign(campaignId):
    authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    campaign = _get_campaign_or_404(campaignId)
    if campaign["status"] not in NON_TERMINAL_CAMPAIGN:
        raise ApiError(ERR_INVALID_STATE, "abort requires SCHEDULED or RUNNING")
    was_running = campaign["status"] == "RUNNING"
    had_records = (
        campaign["cumulative_good_units"] + campaign["cumulative_scrap_units"] > 0
    )
    campaign["status"] = "ABORTED"
    # Abort from RUNNING with at least one production record -> final cost.
    if was_running and had_records:
        cascades.finalize_campaign(campaign)
    store.touch(campaign)
    # Abort cascade (as composition retirement minus the cancel hop).
    affected = cascades.release_reserved_allocations(campaign)
    cascades.breach_check_commitments(affected)
    return success_object(serializers.campaign(campaign))


@bp.route("/glass/campaigns/<campaignId>/record-production", methods=["POST"])
def record_production(campaignId):
    authenticate({ROLE_CAPACITY_PLANNER})
    body = get_body()
    as_datetime(req_field(body, "record_date"), "record_date")
    good = as_int(req_field(body, "good_units"), "good_units")
    scrap = as_int(req_field(body, "scrap_units"), "scrap_units")
    if good < 0 or scrap < 0:
        raise ApiError(
            ERR_INVALID_REQUEST, "good_units and scrap_units must be non-negative"
        )
    campaign = _get_campaign_or_404(campaignId)
    if campaign["status"] != "RUNNING":
        raise ApiError(ERR_INVALID_STATE, "record-production requires RUNNING")
    if good + scrap <= 0:
        raise ApiError(
            ERR_NONPOSITIVE_UNITS, "good_units plus scrap_units must be positive"
        )
    campaign["cumulative_good_units"] += good
    campaign["cumulative_scrap_units"] += scrap
    campaign["realized_yield"] = realized_yield_value(
        campaign["cumulative_good_units"], campaign["cumulative_scrap_units"]
    )
    store.touch(campaign)
    return success_object(serializers.campaign(campaign))


@bp.route("/glass/campaigns/<campaignId>/auto-allocate", methods=["POST"])
def auto_allocate(campaignId):
    authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    campaign = _get_campaign_or_404(campaignId)
    composition = store.compositions[campaign["composition_id"]]
    program_id = composition["program_id"]
    candidates = []
    for c in store.commitments.values():
        if c["program_id"] != program_id:
            continue
        if c["status"] not in ("SECURED", "BREACH_WATCH"):
            continue
        maker = store.device_makers.get(c["device_maker_id"])
        if maker is not None and maker["ip_review_status"] == "CONFIRMED_INFRINGEMENT":
            continue
        candidates.append(c)
    # Deterministic rank: BREACH_WATCH first, tier descending, signed_at then
    # created_at ascending; no id anywhere in the ordering.
    candidates.sort(
        key=lambda c: (
            0 if c["status"] == "BREACH_WATCH" else 1,
            -_TIER_RANK[c["coverage_tier"]],
            c["signed_at"],
            c["created_at"],
        )
    )
    headroom = campaign["unallocated_units"]
    created = []
    for c in candidates:
        if headroom <= 0:
            break
        need = c["committed_units"] - allocated_units(c["id"], store.allocations.values())
        grant = min(need, headroom)
        if grant <= 0:
            continue
        allocation = store.base_fields()
        allocation.update(
            {
                "commitment_id": c["id"],
                "campaign_id": campaign["id"],
                "units": grant,
                "status": "RESERVED",
            }
        )
        store.allocations[allocation["id"]] = allocation
        created.append(allocation)
        headroom -= grant
        campaign["unallocated_units"] -= grant
        store.touch(campaign)
        c["supply_coverage"] = supply_coverage_value(c, store.allocations.values())
        store.touch(c)
        if c["status"] == "BREACH_WATCH" and c["supply_coverage"] >= C.SUPPLY_COVERAGE_MIN:
            c["status"] = "SECURED"
            c["breach_deadline"] = None
    items = [serializers.allocation(a) for a in created]
    return success_list(items, max(len(items), 1), 0, len(items))
