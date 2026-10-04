"""ManufacturingTarget endpoints (PRD 3.7): creation and intensity readings,
with cascade B — a reading that pushes posture into BREACHED reverts every
IN_REVIEW claim referencing the target back to DRAFT."""
from decimal import Decimal

from flask import Blueprint

from auth import authenticate, authorize
from calcs import recompute_target
from constants import ALL_ROLES
from envelope import success
from errors import ApiError
from serialize import serialize_target
from store import STORE, new_common, touch
from util import get_body, req_decimal, req_dt, req_str, to_decimal

bp = Blueprint("targets", __name__)


@bp.route("/carpetloop/manufacturing-targets", methods=["POST"])
def create_target():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    # Priority 11: request shape — baseline positive, reduction strictly in (0, 1).
    program_name = req_str(body, "program_name")
    baseline = req_decimal(body, "baseline_intensity_kgco2e_per_m2", min_exclusive=0)
    reduction = to_decimal(body.get("target_reduction_pct"))
    if reduction is None or not (Decimal("0") < reduction < Decimal("1")):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Field 'target_reduction_pct': must be strictly between 0 and 1",
        )
    t = new_common(STORE)
    t.update(
        {
            "program_name": program_name,
            "baseline_intensity_kgco2e_per_m2": baseline,
            "target_reduction_pct": reduction,
            # Baseline until the first reading; initial posture AT_RISK.
            "current_intensity_kgco2e_per_m2": baseline,
            "posture": "AT_RISK",
            "readings_log": [],
        }
    )
    STORE.targets[t["id"]] = t
    return success(serialize_target(t), 201)


@bp.route("/carpetloop/manufacturing-targets/<target_id>", methods=["GET"])
def get_target(target_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    t = STORE.targets.get(target_id)
    if t is None:
        raise ApiError("ERR_TARGET_NOT_FOUND", 404, "Manufacturing target does not exist")
    return success(serialize_target(t), 200)


@bp.route("/carpetloop/manufacturing-targets/<target_id>/readings", methods=["POST"])
def add_reading(target_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    t = STORE.targets.get(target_id)
    if t is None:
        raise ApiError("ERR_TARGET_NOT_FOUND", 404, "Manufacturing target does not exist")
    body = get_body()
    # Priority 11: request shape — both fields present; intensity numeric.
    period_end = req_dt(body, "period_end")
    intensity = to_decimal(body.get("intensity_kgco2e_per_m2"))
    if intensity is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Field 'intensity_kgco2e_per_m2': required number",
        )
    t["readings_log"].append(
        {
            "period_end": period_end,
            "intensity_kgco2e_per_m2": intensity,
            "recorded_at": STORE.now(),
        }
    )
    recompute_target(t)
    touch(STORE, t)
    # Cascade B (PRD 2.9): a posture of BREACHED reverts every claim that
    # references this target and is currently IN_REVIEW back to DRAFT; the
    # earlier review is cleared, the offset requirement retained for audit.
    if t["posture"] == "BREACHED":
        for c in STORE.claims.values():
            if c["manufacturing_target_id"] == t["id"] and c["status"] == "IN_REVIEW":
                c["status"] = "DRAFT"
                c["reviewed_by"] = None
                touch(STORE, c)
    return success(serialize_target(t), 200)
