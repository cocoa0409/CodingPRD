"""Option roll-ups and cancellation rights (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint

from auth import current_user_id, require_roles
from constants import RIGHTS_KINDS
from errors import ApiError
from lookup import get
from numeric import D, floor_int
from response import created
from routes.common import listing, read_one
from serializers import serialize
from services import cascades, derive
from store import store
from validation import body

bp = Blueprint("rights", __name__)

FULL = Decimal("100.00")


@bp.post("/rights-exercises")
@require_roles("AgencyBuyer")
def create_rights_exercise():
    data = body()
    buy_id = data.string("buy_id")
    kind = data.enum("kind", RIGHTS_KINDS)
    requested_pct = data.decimal("requested_pct", exclusive_min=True)

    buy = get("buys", buy_id)
    if buy["buy_status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if buy["buy_status"] not in ("PENDING_PLACEMENT", "PLACED"):
        raise ApiError("ERR_BUY_NOT_IN_EXPECTED_STATE")

    now = store.now()
    if kind == "OPTION_ROLL":
        if now >= buy["option_window_close"]:
            raise ApiError("ERR_RIGHTS_WINDOW_CLOSED")
        ceiling = D(buy["option_pct_ceiling"])
    else:
        if now >= buy["cancel_window_2_close"]:
            raise ApiError("ERR_RIGHTS_WINDOW_CLOSED")
        ceiling = derive.cancellation_ceiling_pct(buy, now)

    cumulative = derive.cumulative_pct(buy, kind)
    if requested_pct + cumulative > ceiling:
        raise ApiError("ERR_RIGHTS_PCT_ABOVE_CEILING")

    guaranteed_before = buy["guaranteed_impressions"]
    gross_before = buy["gross_cost_cents"]
    magnitude = floor_int(D(guaranteed_before) * D(requested_pct) / D(100))
    delta_impressions = magnitude if kind == "OPTION_ROLL" else -magnitude

    buy["guaranteed_impressions"] = guaranteed_before + delta_impressions
    derive.apply_cost_stack(buy)

    cancelled_unit_count = 0
    if kind == "CANCELLATION":
        cancelled_unit_count = _sweep_units(buy, magnitude)

    cumulative_after = cumulative + requested_pct
    if kind == "CANCELLATION" and cumulative_after >= FULL:
        buy["buy_status"] = "CANCELLED"
        buy["guaranteed_impressions"] = 0
        buy["net_media_cost_cents"] = 0
        buy["agency_commission_cents"] = 0
        buy["gross_cost_cents"] = 0
    store.touch(buy)

    record = store.new(
        "rights",
        {
            "buy_id": buy["id"],
            "kind": kind,
            "requested_pct": requested_pct,
            "applied_ceiling_pct": ceiling,
            "delta_impressions": delta_impressions,
            "delta_gross_cents": buy["gross_cost_cents"] - gross_before,
            "cancelled_unit_count": cancelled_unit_count,
            "exercised_at": now,
            "exercised_by_user_id": current_user_id(),
        },
        versioned=False,
    )
    cascades.commitment_chain(buy)
    return created(serialize("rights", record))


def _sweep_units(buy, magnitude):
    """Release scheduled inventory until the cancelled magnitude is covered."""
    lines = [
        u for u in derive.units_of_buy(buy["id"]) if u["status"] == "SCHEDULED"
    ]
    lines.sort(key=lambda u: (u["air_window_start"], u["created_at"], u["_seq"]))
    released = 0
    count = 0
    touched = []
    for line in lines:
        if released >= magnitude:
            break
        line["status"] = "CANCELLED"
        store.touch(line)
        released += line["projected_impressions"]
        count += 1
        if line["forecast_id"] not in touched:
            touched.append(line["forecast_id"])
    for forecast_id in touched:
        forecast = store.forecasts.get(forecast_id)
        if forecast is not None:
            cascades.sync_forecast(forecast)
    return count


@bp.get("/rights-exercises/<rights_exercise_id>")
def get_rights_exercise(rights_exercise_id):
    return read_one("rights", rights_exercise_id)


@bp.get("/rights-exercises")
def list_rights_exercises():
    return listing("rights", {"buy_id": "buy_id", "kind": "kind"})
