"""ReliabilitySnapshot routes: OCC-guarded compute, nested + flat reads."""

from flask import Blueprint, request

from calculations import (
    SCENARIO_TAGS, accredited_supply, capacity_margin, find_forecast_load,
)
from db import store
from errors import (
    ERR_DUPLICATE_SNAPSHOT, ERR_INVALID_REQUEST, ERR_SNAPSHOT_NOT_FOUND,
    ERR_STALE_PORTFOLIO_VERSION, raise_error,
)
from helpers import (
    body, get_int, get_num, paginate, parse_pagination, require_enum,
    require_fields, stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_portfolios import PORTFOLIO_READ_ROLES, get_portfolio_or_404
from serializers import snapshot_view

bp = Blueprint("snapshots", __name__)


def get_snapshot_or_404(snapshot_id: str, portfolio_id: str = None) -> dict:
    s = store.snapshots.get(snapshot_id)
    if s is None or (portfolio_id is not None and s["portfolio_id"] != portfolio_id):
        raise_error(ERR_SNAPSHOT_NOT_FOUND, f"Snapshot {snapshot_id} not found")
    return s


@bp.route("/portfolios/<portfolioId>/snapshots", methods=["POST"])
@require_roles("UtilityPlanner")
def compute_snapshot(user_id, role, portfolioId):
    pf = get_portfolio_or_404(portfolioId)
    payload = body()
    require_fields(payload, "forecast_year", "scenario_tag",
                   "fuel_price_usd_per_mmbtu", "expected_portfolio_version")
    forecast_year = get_int(payload, "forecast_year")
    scenario_tag = require_enum(payload, "scenario_tag", SCENARIO_TAGS)
    fuel_price = get_num(payload, "fuel_price_usd_per_mmbtu")
    if fuel_price <= 0:
        raise_error(ERR_INVALID_REQUEST, "fuel_price_usd_per_mmbtu must be > 0")
    expected = payload["expected_portfolio_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_portfolio_version must be an integer")
    variant = payload.get("variant")
    if variant is not None and variant not in ("COINCIDENT", "NET_PEAK"):
        raise_error(ERR_INVALID_REQUEST, "variant must be COINCIDENT or NET_PEAK")
    accreditation_mode = payload.get("accreditation_mode", "DECIDED_EXCLUSIVE")
    if accreditation_mode not in ("DECIDED_EXCLUSIVE", "DECIDED_INCLUSIVE"):
        raise_error(ERR_INVALID_REQUEST,
                    "accreditation_mode must be DECIDED_EXCLUSIVE or DECIDED_INCLUSIVE")
    # OCC (priority 4)
    if expected != pf["version"]:
        raise_error(ERR_STALE_PORTFOLIO_VERSION,
                    "expected_portfolio_version does not match the portfolio version")
    # Uniqueness: (portfolio_id, forecast_year) slot occupied by an UNFLAGGED
    # snapshot -> conflict; a retire-flagged occupant is replaced.
    flagged_occupant = None
    for s in store.snapshots.values():
        if s["portfolio_id"] == pf["id"] and s["forecast_year"] == forecast_year:
            if s.get("retire_flagged", False):
                flagged_occupant = s
            else:
                raise_error(ERR_DUPLICATE_SNAPSHOT,
                            "Snapshot for (portfolio, forecast_year) already exists")
    # Demand side.
    use_variant = variant if variant is not None else "COINCIDENT"
    load = find_forecast_load(pf["plan_id"], scenario_tag, forecast_year, use_variant)
    if load is None:
        raise_error(ERR_INVALID_REQUEST,
                    "No load forecast row for (scenario, forecast_year) on this plan")
    # Supply side.
    accredited = accredited_supply(pf, forecast_year, accreditation_mode)
    margin = capacity_margin(accredited, load)
    snap = stamp_new({
        "portfolio_id": pf["id"],
        "forecast_year": forecast_year,
        "scenario_tag": scenario_tag,
        "fuel_price_usd_per_mmbtu": fuel_price,
        "variant": variant,
        "accreditation_mode": accreditation_mode,
        "accredited_supply_mw": accredited,
        "load_mw": load,
        "capacity_margin_mw": margin,
        "meets_requirement": bool(margin >= 0),
        "retire_flagged": False,
    }, with_version=False)
    if flagged_occupant is not None:
        del store.snapshots[flagged_occupant["id"]]
    store.snapshots[snap["id"]] = snap
    touch(pf)
    return success_object(snapshot_view(snap), 201)


@bp.route("/portfolios/<portfolioId>/snapshots", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def list_snapshots(user_id, role, portfolioId):
    pf = get_portfolio_or_404(portfolioId)
    limit, offset = parse_pagination()
    items = [s for s in store.snapshots.values() if s["portfolio_id"] == pf["id"]]
    if "forecast_year" in request.args:
        try:
            fy = int(request.args["forecast_year"])
        except ValueError:
            raise_error(ERR_INVALID_REQUEST, "forecast_year must be an integer")
        items = [s for s in items if s["forecast_year"] == fy]
    page, total = paginate(items, limit, offset)
    return success_list([snapshot_view(s) for s in page], limit, offset, total)


@bp.route("/portfolios/<portfolioId>/snapshots/<snapshotId>", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def get_snapshot(user_id, role, portfolioId, snapshotId):
    get_portfolio_or_404(portfolioId)
    s = get_snapshot_or_404(snapshotId, portfolio_id=portfolioId)
    return success_object(snapshot_view(s), 200)


@bp.route("/snapshots", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def list_snapshots_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.snapshots.values())
    if "portfolio_id" in request.args:
        items = [s for s in items if s["portfolio_id"] == request.args["portfolio_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([snapshot_view(s) for s in page], limit, offset, total)


@bp.route("/snapshots/<snapshotId>", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def get_snapshot_flat(user_id, role, snapshotId):
    s = get_snapshot_or_404(snapshotId)
    return success_object(snapshot_view(s), 200)
