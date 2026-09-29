"""Teams, adoption measurement and the team dashboard (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import calc
import errors
from auth import CONTRIBUTING_TEAM, SYSTEM_ADMIN, ensure_owner, require_roles
from entities import get_team, scan_json, team_json
from errors import fail
from responses import created, ok
from routes.common import respond_list
from store import iso, store
from validation import (body, opt_decimal, opt_enum, pagination, query_enum,
                        req_datetime, req_enum, req_int, req_string)

bp = Blueprint("teams", __name__, url_prefix="/design-system")

PLATFORM_SCOPES = ("WEB_ONLY", "MOBILE_ONLY", "ALL")
SCAN_KINDS = ("CODE_SCAN", "DESIGN_LINT")
VIEWS = ("LATEST_SCAN", "TRAILING_WINDOW")


@bp.post("/teams")
@require_roles(SYSTEM_ADMIN)
def create_team():
    payload = body()
    name = req_string(payload, "name", 1, 120)
    slug = req_string(payload, "slug", 1, 120)
    platform_scope = opt_enum(payload, "platform_scope", PLATFORM_SCOPES, "ALL")
    budget = opt_decimal(payload, "debt_budget_points", places=2,
                         minimum=Decimal("0"), default=Decimal("40.00"))

    for existing in store.teams.values():
        if existing["slug"] == slug:
            fail(errors.ERR_UNIQUENESS_CONFLICT,
                 "A team with slug '%s' already exists." % slug)

    row = store.new_row()
    row.update({
        "name": name,
        "slug": slug,
        "platform_scope": platform_scope,
        "debt_budget_points": budget,
        "outstanding_debt_points": Decimal("0.00"),
        "lifetime_debt_points": Decimal("0.00"),
        "debt_state": "CLEAR",
        "blocked_implementation_count": 0,
        "adoption_index_latest": Decimal("0.00"),
        "adoption_index_trailing": Decimal("0.00"),
    })
    store.teams[row["id"]] = row
    return created(team_json(row))


@bp.get("/teams/<team_id>")
@require_roles()
def read_team(team_id):
    team = get_team(team_id)
    ensure_owner(team["id"])
    return ok(team_json(team))


@bp.get("/teams/<team_id>/dashboard")
@require_roles()
def team_dashboard(team_id):
    view = query_enum("view", VIEWS, "LATEST_SCAN")
    team = get_team(team_id)
    ensure_owner(team["id"])

    code_ratio, design_ratio, index = calc.adoption_view(team["id"], view)
    kinds = set(s["scan_kind"] for s in calc.team_scans(team["id"]))
    open_count = sum(1 for g in calc.team_grants(team["id"])
                     if g["state"] == "REQUESTED")

    return ok({
        "team_id": team["id"],
        "view": view,
        "adoption_index": index,
        "code_scan_ratio": code_ratio,
        "design_lint_ratio": design_ratio,
        "outstanding_debt_points": team["outstanding_debt_points"],
        "debt_state": team["debt_state"],
        "blocked_implementation_count": team["blocked_implementation_count"],
        "open_exception_count": open_count,
        "scanned_kind_count": len(kinds),
    })


@bp.post("/teams/<team_id>/adoption-scans")
@require_roles(CONTRIBUTING_TEAM, SYSTEM_ADMIN)
def file_adoption_scan(team_id):
    payload = body()
    scan_kind = req_enum(payload, "scan_kind", SCAN_KINDS)
    window_start = req_datetime(payload, "window_start_at")
    window_end = req_datetime(payload, "window_end_at")
    system_count = req_int(payload, "system_instance_count", minimum=0)
    legacy_count = req_int(payload, "legacy_instance_count", minimum=0)
    one_off_count = req_int(payload, "one_off_instance_count", minimum=0)
    if not window_start < window_end:
        fail(errors.ERR_INVALID_REQUEST,
             "Field 'window_start_at' must be strictly before 'window_end_at'.")

    team = get_team(team_id)
    ensure_owner(team["id"])

    for existing in calc.team_scans(team["id"], scan_kind):
        if (window_start <= existing["_window_end"]
                and existing["_window_start"] <= window_end):
            fail(errors.ERR_SCAN_WINDOW_OVERLAP,
                 "The measurement window overlaps an existing scan of this channel.")

    row = store.new_row(mutable=False)
    row.update({
        "team_id": team["id"],
        "scan_kind": scan_kind,
        "window_start_at": iso(window_start),
        "window_end_at": iso(window_end),
        "system_instance_count": system_count,
        "legacy_instance_count": legacy_count,
        "one_off_instance_count": one_off_count,
        "adoption_ratio": calc.scan_ratio(system_count, legacy_count, one_off_count),
        "scanned_at": store.now_iso,
        "_window_start": window_start,
        "_window_end": window_end,
    })
    store.scans[row["id"]] = row

    calc.recompute_team_adoption(team)
    store.touch(team)

    return created(scan_json(row))


@bp.get("/teams/<team_id>/adoption-scans")
@require_roles()
def list_adoption_scans(team_id):
    limit, offset = pagination()
    scan_kind = query_enum("scan_kind", SCAN_KINDS)
    team = get_team(team_id)
    ensure_owner(team["id"])
    rows = calc.recency_order(calc.team_scans(team["id"], scan_kind))
    return respond_list(rows, scan_json, limit, offset)
