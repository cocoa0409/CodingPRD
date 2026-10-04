"""Trend signals (PRD 3.1): register, list, and drive the lifecycle
DISCOVERED -> EVALUATING -> {SELECTED (score-gated) | PARKED} plus ARCHIVED.
"""
from flask import Blueprint

from core import clock
from core.auth import authenticate, require_role
from core.constants import (
    ROLE_TREND_SCOUT,
    SOURCE_PRESTIGE_LAUNCH,
    SOURCE_SOCIAL_PLATFORM,
    TREND_SELECT_THRESHOLD,
)
from core.envelope import pub, success_object
from core.errors import bad_request, err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, opt_num, req_enum, req_int, req_num, req_str
from services import calc

bp = Blueprint("trends", __name__)

SOURCES = (SOURCE_SOCIAL_PLATFORM, SOURCE_PRESTIGE_LAUNCH)
STATUSES = ("DISCOVERED", "EVALUATING", "PARKED", "SELECTED", "ARCHIVED")


@bp.post("/trend-signals")
def create_trend_signal():
    _, role = authenticate()
    require_role(role, ROLE_TREND_SCOUT)
    body = get_body()
    source = req_enum(body, "source", SOURCES)
    platform = req_str(body, "platform")
    category = req_str(body, "category")
    velocity = req_int(body, "mention_velocity_7d", minimum=0)
    growth = req_num(body, "engagement_growth_pct", minimum=0)
    # Conditional-required: exactly the source's own signal field must be
    # supplied; supplying the other source's field is rejected (PRD 3.1).
    prestige = opt_num(body, "prestige_similarity", minimum=0, maximum=1)
    spread = opt_num(body, "cross_platform_spread", minimum=0, maximum=1)
    if source == SOURCE_PRESTIGE_LAUNCH:
        if prestige is None:
            raise bad_request(
                "field 'prestige_similarity' is required when source is "
                "PRESTIGE_LAUNCH"
            )
        if spread is not None:
            raise bad_request(
                "field 'cross_platform_spread' must not be supplied when source "
                "is PRESTIGE_LAUNCH"
            )
    else:
        if spread is None:
            raise bad_request(
                "field 'cross_platform_spread' is required when source is "
                "SOCIAL_PLATFORM"
            )
        if prestige is not None:
            raise bad_request(
                "field 'prestige_similarity' must not be supplied when source "
                "is SOCIAL_PLATFORM"
            )
    rec = new_record(
        {
            "source": source,
            "platform": platform,
            "category": category,
            "mention_velocity_7d": velocity,
            "engagement_growth_pct": growth,
            "prestige_similarity": prestige,
            "cross_platform_spread": spread,
            "status": "DISCOVERED",
            "momentum_score": None,
            "evaluated_at": None,
        }
    )
    store.trend_signals[rec["id"]] = rec
    return success_object(pub(rec), code=201)


@bp.get("/trend-signals")
def list_trend_signals():
    authenticate()
    return list_response(
        store.trend_signals.values(),
        {"status": "status", "source": "source", "category": "category"},
        pub,
    )


@bp.patch("/trend-signals/<rid>")
def patch_trend_signal(rid):
    _, role = authenticate()
    require_role(role, ROLE_TREND_SCOUT)
    body = get_body()
    target = None
    if "status" in body and body["status"] is not None:
        target = req_enum(body, "status", STATUSES)
    rec = store.trend_signals.get(rid)
    if rec is None:
        raise not_found("ERR_TREND_SIGNAL_NOT_FOUND", "trend signal not found")
    if target is None:
        return success_object(pub(rec))
    current = rec["status"]
    if target == "EVALUATING" and current in ("DISCOVERED", "PARKED"):
        # (Re-)entry into EVALUATING recomputes the score from current field
        # values and stamps evaluated_at with the logical clock.
        rec["momentum_score"] = calc.momentum_score(rec)
        rec["evaluated_at"] = clock.now()
        rec["status"] = "EVALUATING"
    elif target == "SELECTED" and current == "EVALUATING":
        score = rec["momentum_score"]
        if score is None or calc.D(score) < TREND_SELECT_THRESHOLD:
            raise err(
                "ERR_TREND_SCORE_BELOW_THRESHOLD",
                "momentum_score is below the selection threshold of 70.0",
            )
        rec["status"] = "SELECTED"
    elif target == "PARKED" and current == "EVALUATING":
        rec["status"] = "PARKED"
    elif target == "ARCHIVED" and current in ("DISCOVERED", "EVALUATING", "PARKED"):
        rec["status"] = "ARCHIVED"
    else:
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition a trend signal from %s to %s" % (current, target),
        )
    touch(rec)
    return success_object(pub(rec))
