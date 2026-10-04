"""Exclusive set launches: scheduling, reading and rescheduling."""

from datetime import timedelta

from flask import Blueprint

from db import db, now
from errors import fail
from middleware import require
from response import envelope
from services.core import get_launch, new_record, touch
from utils import body, out, require_fields

bp = Blueprint("theme_launches", __name__)


def resolve_instants(days_from_default_clock, vip_early_days_before_release):
    """Offsets are resolved against the logical clock at creation and then stored."""
    release = now() + timedelta(days=float(days_from_default_clock))
    early = release - timedelta(days=float(vip_early_days_before_release or 0))
    return early, release


def has_early_window(vip_early_days_before_release):
    """A caller who names no early-access lead time asks for no VIP window.

    PRD §3.4 refuses an early-access instant that is not strictly before the
    release instant; when no lead time is requested there is no separate
    early-access instant to validate and the launch simply opens at release.
    A negative lead time is a request for a degenerate window -- the early
    instant resolves to after the release -- so it is validated and refused,
    not skipped.
    """
    return float(vip_early_days_before_release or 0) != 0


@bp.route("/stores/theme-launches", methods=["POST"])
def schedule_launch():
    require("PlatformAdmin")
    payload = body()
    require_fields(payload, "theme", "exclusive_set_sku", "allocated_exclusive_units",
                   "exclusive_set_unit_price_cents", "days_from_default_clock")

    per_customer_limit = int(payload.get("per_customer_limit", 1))
    if per_customer_limit < 1:
        fail("ERR_CONSTRAINT_VIOLATION", "per_customer_limit must be at least 1.")

    lead_days = payload.get("vip_early_days_before_release", 0)
    early, release = resolve_instants(payload["days_from_default_clock"], lead_days)

    # Width is validated before overlap, and overlap before the allocation size.
    if has_early_window(lead_days) and not early < release:
        fail("ERR_LAUNCH_WINDOW_INVALID",
             "The early-access window must have positive width.")

    theme = payload["theme"]
    if has_early_window(lead_days):
        for existing in db().theme_launches.values():
            if existing["theme"] != theme:
                continue
            if early < existing["release_utc"] and existing["vip_early_access_utc"] < release:
                fail("ERR_LAUNCH_WINDOW_OVERLAP",
                     "The requested window intersects an existing launch window "
                     "for this theme.")

    allocation = int(payload["allocated_exclusive_units"])
    if allocation < 0:
        fail("ERR_CONSTRAINT_VIOLATION", "allocated_exclusive_units may not be negative.")

    launch = new_record({
        "theme": theme,
        "release_utc": release,
        "vip_early_access_utc": early,
        "per_customer_limit": per_customer_limit,
        "exclusive_set_sku": payload["exclusive_set_sku"],
        "exclusive_set_unit_price_cents": int(payload["exclusive_set_unit_price_cents"]),
        "stage": "SCHEDULED",
        "exclusive_set_units_remaining": allocation,
        "allocated_exclusive_units": allocation,
        "soft_hold_units": 0,
    })
    db().theme_launches[launch["id"]] = launch
    return envelope(out(launch), status=201)


@bp.route("/stores/theme-launches/<launch_id>", methods=["GET"])
def read_launch(launch_id):
    require("PlatformAdmin", "StoreAssociate", "Member")
    return envelope(out(get_launch(launch_id)))


@bp.route("/stores/theme-launches/<launch_id>/reschedule", methods=["POST"])
def reschedule_launch(launch_id):
    require("PlatformAdmin")
    payload = body()
    require_fields(payload, "days_from_default_clock")
    launch = get_launch(launch_id)

    early, release = resolve_instants(payload["days_from_default_clock"],
                                      _early_days_back(launch))

    if launch["stage"] == "VIP_EARLY":
        if any(q["launch_id"] == launch["id"] and q["status"] in ("GRANTED", "PURCHASED")
               for q in db().launch_queues.values()):
            fail("ERR_INVALID_STATE",
                 "A launch holding granted or purchased rows may not be postponed.")
        launch["stage"] = "SCHEDULED"
    elif launch["stage"] == "CLOSED":
        launch["stage"] = "SCHEDULED"
        launch["exclusive_set_units_remaining"] = launch["allocated_exclusive_units"]
    else:
        fail("ERR_INVALID_STATE",
             "Only a launch in VIP_EARLY or CLOSED may be rescheduled.")

    launch["release_utc"] = release
    launch["vip_early_access_utc"] = early
    touch(launch)
    return envelope(out(launch))


def _early_days_back(launch):
    delta = launch["release_utc"] - launch["vip_early_access_utc"]
    return delta.total_seconds() / 86400.0