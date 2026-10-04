"""Pattern-of-violations screening and notice endpoints (PRD section 3.7)."""
from datetime import timedelta

from flask import Blueprint

import clock
import services_pov
import store
from constants import (
    BUSINESS_READ_ROLES,
    POV_THRESHOLD,
    POV_WINDOW_DAYS,
    ROLE_DISTRICT_MANAGER,
    ROLE_MSHA_ADMIN,
)
from envelope import list_response, ok_object
from errors import ApiError, ERR_POV_NOTICE_REQUIRES_POTENTIAL, ERR_POV_SCORE_INSUFFICIENT
from serialize import pov_screening as ser_screening
from validate import ensure_empty_body, get_or_404, require_roles

bp = Blueprint("pov", __name__, url_prefix="/msha")


def _new_screening(mine_id, variant, screened_at, ss_count, weighted_score, result):
    return store.new_entity(store.screenings, {
        "mine_id": mine_id,
        "variant": variant,
        "screened_at": screened_at,
        "window_start": screened_at - timedelta(days=POV_WINDOW_DAYS),
        "ss_citation_count": ss_count,
        "weighted_score": weighted_score,
        "result": result,
    })


@bp.route("/mines/<mineId>/pov-screenings", methods=["POST"])
def run_screening(mineId):
    require_roles(ROLE_MSHA_ADMIN)
    ensure_empty_body()
    mine = get_or_404(store.mines, mineId, "mine")
    screened_at = clock.now()
    ss_count, weighted_score = services_pov.compute_pov(mineId, screened_at, "SCREENING")
    result = "POTENTIAL_POV" if weighted_score >= POV_THRESHOLD else "BELOW_THRESHOLD"
    screening = _new_screening(mineId, "SCREENING", screened_at, ss_count, weighted_score, result)
    if result == "POTENTIAL_POV" and mine["pov_status"] == "NONE":
        mine["pov_status"] = "POTENTIAL_POV"
        store.touch(mine)
    elif result == "BELOW_THRESHOLD" and mine["pov_status"] == "POTENTIAL_POV":
        mine["pov_status"] = "NONE"
        store.touch(mine)
    return ok_object(ser_screening(screening), 201)


@bp.route("/mines/<mineId>/pov-screenings", methods=["GET"])
def list_screenings(mineId):
    require_roles(*BUSINESS_READ_ROLES)
    get_or_404(store.mines, mineId, "mine")
    items = [s for s in store.screenings.values() if s["mine_id"] == mineId]
    return list_response(items, ser_screening)


@bp.route("/mines/<mineId>/pov-notices", methods=["POST"])
def issue_notice(mineId):
    require_roles(ROLE_DISTRICT_MANAGER)
    ensure_empty_body()
    mine = get_or_404(store.mines, mineId, "mine")
    if mine["pov_status"] != "POTENTIAL_POV":
        raise ApiError(
            ERR_POV_NOTICE_REQUIRES_POTENTIAL,
            "a POV notice requires the mine to stand at POTENTIAL_POV",
        )
    screened_at = clock.now()
    ss_count, weighted_score = services_pov.compute_pov(mineId, screened_at, "FINAL_DETERMINATION")
    if weighted_score < POV_THRESHOLD:
        raise ApiError(
            ERR_POV_SCORE_INSUFFICIENT,
            "the final-determination weighted_score is below the threshold of 8",
        )
    screening = _new_screening(mineId, "FINAL_DETERMINATION", screened_at, ss_count, weighted_score, "CONFIRMED_POV")
    mine["pov_status"] = "POV_FINAL"
    store.touch(mine)
    for cycle in store.cycles.values():
        if cycle["mine_id"] == mineId and cycle["status"] == "OPEN":
            cycle["required_inspections"] += 1
            store.touch(cycle)
    return ok_object(ser_screening(screening), 201)
