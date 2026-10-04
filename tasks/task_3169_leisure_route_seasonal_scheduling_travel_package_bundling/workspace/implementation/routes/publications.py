"""Schedule publications: publish (with flight generation), list, get, retire."""

from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    new_entity,
    get_or_404,
    body,
    require_field,
    require_date,
    require_time_hhmm,
    require_positive_int,
    check_occ,
    touch,
    parse_date,
    iso_week_key,
    logical_clock_date,
    logical_clock_iso,
)
from errors import ApiError, stale_version
from middleware import require_role, require_any_authenticated
from response import ok, paginate
from routes.routes import _get_route_or_404, _cancel_flight

bp = Blueprint("publications", __name__)

PUBLISH_HORIZON_MIN_DAYS = 180


def _get_pub_or_404(pub_id):
    return get_or_404(
        db.schedule_publications,
        pub_id,
        "ERR_PUBLICATION_NOT_FOUND",
        "SchedulePublication",
    )


@bp.route("/routes/<route_id>/publications", methods=["POST"])
def create_publication(route_id):
    require_role("NetworkPlanner")
    route = _get_route_or_404(route_id)
    data = body()

    window_id = require_field(data, "season_window_id", str)
    window = db.season_windows.get(window_id)
    if window is None:
        raise ApiError(
            "ERR_WINDOW_NOT_FOUND", "SeasonWindow id does not exist", 404
        )

    mask = require_field(data, "operating_days_mask", list)
    for day in mask:
        if not isinstance(day, int) or isinstance(day, bool) or day < 1 or day > 7:
            raise ApiError(
                "ERR_VALIDATION",
                "operating_days_mask entries must be integers 1..7",
                422,
            )
    first = require_date(data, "first_operating_date")
    last = require_date(data, "last_operating_date")
    dep_time = require_time_hhmm(data, "departure_time_local")
    block = require_positive_int(data, "block_minutes", minimum=1)

    if window["route_id"] != route_id:
        raise ApiError(
            "ERR_WINDOW_NOT_FOUND", "SeasonWindow id does not exist", 404
        )
    if window["window_status"] != "OPEN":
        raise ApiError(
            "ERR_WINDOW_NOT_OPEN", "Operation requires OPEN window", 409
        )

    first_d = parse_date(first)
    last_d = parse_date(last)
    if last_d < first_d:
        raise ApiError(
            "ERR_PUBLICATION_OUTSIDE_WINDOW",
            "Publication dates lie outside their SeasonWindow",
            422,
        )

    # Business temporal rule 1: window containment
    w_start = parse_date(window["window_start_date"])
    w_end = parse_date(window["window_end_date"])
    if first_d < w_start or last_d > w_end:
        raise ApiError(
            "ERR_PUBLICATION_OUTSIDE_WINDOW",
            "Publication dates lie outside their SeasonWindow",
            422,
        )

    # Business temporal rule 2: publish horizon (>= 180 days; == allowed)
    clock_date = logical_clock_date()
    days_ahead = (first_d - clock_date).days
    if days_ahead < PUBLISH_HORIZON_MIN_DAYS:
        raise ApiError(
            "ERR_PUBLISH_HORIZON_VIOLATION",
            "first_operating_date fewer than 180 days ahead of the logical clock",
            422,
        )

    # Business capacity rule 3: weekly frequency cap (reject iff > cap)
    mask_set = set(mask)
    new_dates = []
    d = first_d
    while d <= last_d:
        if d.isoweekday() in mask_set:
            new_dates.append(d)
        d += timedelta(days=1)

    weekly_counts = {}
    for d in new_dates:
        key = iso_week_key(d)
        weekly_counts[key] = weekly_counts.get(key, 0) + 1

    for key, new_count in weekly_counts.items():
        existing = 0
        for pub in db.schedule_publications.values():
            if pub["route_id"] != route_id:
                continue
            if pub["publication_status"] == "RETIRED":
                continue
            for f in db.flight_instances.values():
                if f["publication_id"] != pub["id"]:
                    continue
                if iso_week_key(parse_date(f["flight_date"])) == key:
                    existing += 1
        if new_count + existing > route["weekly_frequency_cap"]:
            raise ApiError(
                "ERR_FREQUENCY_CAP_EXCEEDED",
                "Weekly departures would exceed Route.weekly_frequency_cap",
                409,
            )

    # OCC check — evaluated last
    check_occ(data, "expected_window_version", window)

    # Create the publication
    pub = new_entity(
        {
            "route_id": route_id,
            "season_window_id": window_id,
            "operating_days_mask": list(mask),
            "first_operating_date": first,
            "last_operating_date": last,
            "departure_time_local": dep_time,
            "block_minutes": block,
            "publication_status": "PUBLISHED",
            "published_at": logical_clock_iso(),
        }
    )
    db.schedule_publications[pub["id"]] = pub

    # Generate flight instances
    for d in new_dates:
        iso_weekday = d.isoweekday()
        is_peak = iso_weekday in (6, 7)
        flight = new_entity(
            {
                "publication_id": pub["id"],
                "route_id": route_id,
                "flight_date": d.isoformat(),
                "aircraft_id": None,
                "is_peak_day": is_peak,
                "seats_sold": 0,
                "flight_status": "SCHEDULED",
                "cancelled_by_disruption_id": None,
            }
        )
        db.flight_instances[flight["id"]] = flight

    # Publishing mutates the window: version += 1
    touch(window)

    return ok(pub, 201)


@bp.route("/routes/<route_id>/publications", methods=["GET"])
def list_pubs_for_route(route_id):
    require_any_authenticated()
    _get_route_or_404(route_id)
    items = [
        p for p in db.schedule_publications.values() if p["route_id"] == route_id
    ]
    status = request.args.get("publication_status")
    if status:
        items = [p for p in items if p["publication_status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/routes/<route_id>/publications/<pub_id>", methods=["GET"])
def get_pub_nested(route_id, pub_id):
    require_any_authenticated()
    _get_route_or_404(route_id)
    pub = _get_pub_or_404(pub_id)
    if pub["route_id"] != route_id:
        raise ApiError(
            "ERR_PUBLICATION_NOT_FOUND",
            "SchedulePublication id does not exist",
            404,
        )
    return ok(pub)


@bp.route("/routes/<route_id>/publications/<pub_id>/retire", methods=["POST"])
def retire_publication(route_id, pub_id):
    require_role("NetworkPlanner")
    _get_route_or_404(route_id)
    pub = _get_pub_or_404(pub_id)
    if pub["route_id"] != route_id:
        raise ApiError(
            "ERR_PUBLICATION_NOT_FOUND",
            "SchedulePublication id does not exist",
            404,
        )
    if pub["publication_status"] not in ("PUBLISHED", "FROZEN"):
        raise ApiError(
            "ERR_PUBLICATION_NOT_PUBLISHED",
            "Retire requires PUBLISHED or FROZEN publication",
            409,
        )
    if pub["publication_status"] == "PUBLISHED":
        booked = [
            f
            for f in db.flight_instances.values()
            if f["publication_id"] == pub_id
            and f["flight_status"] == "SCHEDULED"
            and f["seats_sold"] > 0
        ]
        if booked:
            raise ApiError(
                "ERR_PUBLICATION_HAS_BOOKED_FLIGHTS",
                "Retire blocked: SCHEDULED flight with seats_sold > 0 exists",
                409,
            )
        remaining = [
            f
            for f in db.flight_instances.values()
            if f["publication_id"] == pub_id and f["flight_status"] == "SCHEDULED"
        ]
        for flight in remaining:
            flight["flight_status"] = "CANCELLED"
            touch(flight)
    pub["publication_status"] = "RETIRED"
    touch(pub)
    return ok(pub)


@bp.route("/schedule-publications", methods=["GET"])
def list_pubs_flat():
    require_any_authenticated()
    items = list(db.schedule_publications.values())
    rid = request.args.get("route_id")
    if rid:
        items = [p for p in items if p["route_id"] == rid]
    wid = request.args.get("season_window_id")
    if wid:
        items = [p for p in items if p["season_window_id"] == wid]
    status = request.args.get("publication_status")
    if status:
        items = [p for p in items if p["publication_status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/schedule-publications/<pub_id>", methods=["GET"])
def get_pub_flat(pub_id):
    require_any_authenticated()
    pub = _get_pub_or_404(pub_id)
    return ok(pub)
