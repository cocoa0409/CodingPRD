"""Rehearsal services: scheduling, union-compliant booking, publication and
clock-out settlement."""

from datetime import timedelta

from flask import Blueprint, request

from calc import base_pay_cents, final_pay_cents, overtime_minutes_of
from db import db
from domain import (agreement_for_season, base_fields, created_key,
                    engagements_of_service, recompute_readiness, serialize,
                    touch, try_promote_lock)
from errors import raise_err
from middleware import endpoint
from response import ok, ok_list
from validate import (body, check_body_fks, opt_int, paginate, req_dt,
                      req_enum, req_int, req_str)

bp = Blueprint("rehearsals", __name__)

SERVICE_TYPES = ("REHEARSAL", "DRESS_REHEARSAL", "PERFORMANCE")


def get_service_or_404(service_id):
    service = db.services.get(service_id)
    if service is None:
        raise_err("ERR_SERVICE_NOT_FOUND")
    return service


def agreement_for_service(service):
    concert = db.concerts.get(service["concert_id"])
    if concert is None:
        return None
    return agreement_for_season(concert["season_id"])


def _minutes(delta):
    return int(delta.total_seconds() // 60)


@bp.route("/orchestra/rehearsals", methods=["POST"])
@endpoint(["OrchestraManager"])
def create_service():
    data = body()
    check_body_fks(data, ["venue_id", "concert_id"])         # rung 4
    concert = db.concerts.get(data.get("concert_id"))
    if concert is None:
        req_str(data, "concert_id")
        raise_err("ERR_CONCERT_NOT_FOUND")
    venue = db.venues.get(data.get("venue_id"))
    if venue is None:
        req_str(data, "venue_id")
        raise_err("ERR_VENUE_NOT_FOUND")

    service_type = req_enum(data, "service_type", SERVICE_TYPES)   # rung 6
    start = req_dt(data, "scheduled_start_utc")
    end = req_dt(data, "scheduled_end_utc")
    if end <= start:
        raise_err("ERR_INVALID_REQUEST",
                  "Field 'scheduled_end_utc' must be strictly after 'scheduled_start_utc'.")
    minimum_complement = req_int(data, "minimum_complement", minv=0)
    break_minutes = opt_int(data, "break_minutes", 0, minv=0)

    if concert["programming_status"] not in ("PROGRAMMED", "LOCKED"):   # rung 8
        raise_err("ERR_CONCERT_NOT_PROGRAMMED")

    service = base_fields()
    service.update({
        "concert_id": concert["id"],
        "venue_id": venue["id"],
        "service_type": service_type,
        "scheduled_start_utc": data["scheduled_start_utc"],
        "scheduled_end_utc": data["scheduled_end_utc"],
        "break_minutes": break_minutes,
        "minimum_complement": minimum_complement,
        "actual_start_utc": None,
        "actual_end_utc": None,
        "status": "DRAFT",
        "confirmed_engagement_count": 0,
        "compliance_status": "COMPLIANT",
        "provisional_service_cost_cents": 0,
        "final_service_cost_cents": None,
        "_sched_start_dt": start,
        "_sched_end_dt": end,
        "_actual_start_dt": None,
        "_actual_end_dt": None,
    })
    db.services[service["id"]] = service
    return ok(serialize(service), 201)


@bp.route("/orchestra/rehearsals/<service_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "Musician"])
def read_service(service_id):
    return ok(serialize(get_service_or_404(service_id)))


@bp.route("/orchestra/rehearsals", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "Musician"])
def list_services():
    concert_id = request.args.get("concert_id")
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    records = []
    for service in db.services.values():
        if concert_id is not None and service["concert_id"] != concert_id:
            continue
        if venue_id is not None and service["venue_id"] != venue_id:
            continue
        if status is not None and service["status"] != status:
            continue
        records.append(service)
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)


@bp.route("/orchestra/rehearsals/<service_id>/publish", methods=["POST"])
@endpoint(["OrchestraManager"])
def publish_service(service_id):
    service = get_service_or_404(service_id)                 # rung 3
    if service["status"] != "DRAFT":                         # rung 7
        raise_err("ERR_SERVICE_NOT_DRAFT")
    agreement = agreement_for_service(service)
    if agreement is None:
        raise_err("ERR_UNION_AGREEMENT_MISSING")

    # rung 10 -- union break rule
    scheduled_minutes = _minutes(service["_sched_end_dt"] - service["_sched_start_dt"])
    if scheduled_minutes > 90 and service["break_minutes"] < agreement["mandatory_break_minutes"]:
        raise_err("ERR_UNION_BREAK_VIOLATION")

    # rung 14 -- venue changeover rule
    venue = db.venues.get(service["venue_id"])
    buffer_minutes = venue["changeover_buffer_minutes"] if venue else 0
    buffer = timedelta(minutes=buffer_minutes)
    for other in db.services.values():
        if other["id"] == service["id"]:
            continue
        if other["venue_id"] != service["venue_id"] or other["status"] != "PUBLISHED":
            continue
        if (service["_sched_start_dt"] < other["_sched_end_dt"] + buffer
                and other["_sched_start_dt"] < service["_sched_end_dt"] + buffer):
            raise_err("ERR_VENUE_CHANGEOVER_CONFLICT")

    # rung 15 -- minimum complement
    if service["confirmed_engagement_count"] < service["minimum_complement"]:
        raise_err("ERR_INSUFFICIENT_COMPLEMENT")

    total = 0
    for engagement in sorted(engagements_of_service(service["id"]), key=created_key):
        if engagement["status"] != "CONFIRMED":
            continue
        musician = db.musicians.get(engagement["musician_id"])
        if musician is None:
            continue
        pay = base_pay_cents(agreement, musician, engagement["doubling_count"])
        with touch(engagement):
            engagement["provisional_pay_cents"] = pay
        with touch(musician):
            musician["services_charged_ytd"] += 1
            musician["ytd_earnings_cents"] += pay
        total += pay

    with touch(service):
        service["status"] = "PUBLISHED"
        service["compliance_status"] = "COMPLIANT"
        service["provisional_service_cost_cents"] = total

    concert = db.concerts.get(service["concert_id"])
    if concert is not None:
        with touch(concert):
            try_promote_lock(concert)
            recompute_readiness(concert)
    return ok(serialize(service))


@bp.route("/orchestra/rehearsals/<service_id>/clock", methods=["POST"])
@endpoint(["OrchestraManager"])
def clock_service(service_id):
    service = get_service_or_404(service_id)                 # rung 3
    data = body()
    start = req_dt(data, "actual_start_utc")                 # rung 6
    end = req_dt(data, "actual_end_utc")
    if end <= start:
        raise_err("ERR_INVALID_REQUEST",
                  "Field 'actual_end_utc' must be strictly after 'actual_start_utc'.")
    if service["status"] != "PUBLISHED":                     # rung 7
        raise_err("ERR_SERVICE_NOT_PUBLISHED")

    agreement = agreement_for_service(service)
    worked_minutes = _minutes(end - start) - service["break_minutes"]
    overtime = 0
    rate = 0
    if agreement is not None:
        overtime = overtime_minutes_of(worked_minutes, agreement["max_service_minutes"])
        rate = agreement["overtime_rate_cents_per_minute"]

    total = 0
    for engagement in sorted(engagements_of_service(service["id"]), key=created_key):
        if engagement["status"] != "CONFIRMED":
            continue
        base = engagement["provisional_pay_cents"]
        if base is None:
            musician_record = db.musicians.get(engagement["musician_id"])
            base = (base_pay_cents(agreement, musician_record, engagement["doubling_count"])
                    if (agreement and musician_record) else 0)
        final = final_pay_cents(base, overtime, rate)
        with touch(engagement):
            engagement["overtime_minutes"] = overtime
            engagement["final_pay_cents"] = final
            engagement["status"] = "SETTLED"
        musician = db.musicians.get(engagement["musician_id"])
        if musician is not None:
            with touch(musician):
                musician["ytd_earnings_cents"] += (final - base)
        total += final

    with touch(service):
        service["status"] = "COMPLETED"
        service["actual_start_utc"] = data["actual_start_utc"]
        service["actual_end_utc"] = data["actual_end_utc"]
        service["_actual_start_dt"] = start
        service["_actual_end_dt"] = end
        service["final_service_cost_cents"] = total
    return ok(serialize(service))


@bp.route("/orchestra/rehearsals/<service_id>/engagements", methods=["POST"])
@endpoint(["OrchestraManager"])
def create_engagement(service_id):
    service = get_service_or_404(service_id)                 # rung 3
    data = body()
    check_body_fks(data, ["musician_id"])                    # rung 4
    musician = db.musicians.get(data.get("musician_id"))
    if musician is None:
        req_str(data, "musician_id")
        raise_err("ERR_MUSICIAN_NOT_FOUND")

    doubling_count = opt_int(data, "doubling_count", 0, minv=0)   # rung 6

    if service["status"] != "DRAFT":                         # rung 7
        raise_err("ERR_SERVICE_NOT_DRAFT")
    agreement = agreement_for_service(service)
    if agreement is None:
        raise_err("ERR_UNION_AGREEMENT_MISSING")

    # rung 11 -- union rest rule
    min_rest = timedelta(minutes=agreement["min_rest_minutes_between_services"])
    new_start = service["_sched_start_dt"]
    new_end = service["_sched_end_dt"]
    for engagement in db.engagements.values():
        if engagement["musician_id"] != musician["id"] or engagement["status"] != "CONFIRMED":
            continue
        other = db.services.get(engagement["service_id"])
        if other is None or other["id"] == service["id"]:
            continue
        if other["_sched_end_dt"] <= new_start:
            gap = new_start - other["_sched_end_dt"]
        elif new_end <= other["_sched_start_dt"]:
            gap = other["_sched_start_dt"] - new_end
        else:
            raise_err("ERR_UNION_REST_VIOLATION")
            gap = None
        if gap < min_rest:
            raise_err("ERR_UNION_REST_VIOLATION")

    # rung 12 -- union daily-service cap
    same_day = 0
    new_date = new_start.date()
    for engagement in db.engagements.values():
        if engagement["musician_id"] != musician["id"] or engagement["status"] != "CONFIRMED":
            continue
        other = db.services.get(engagement["service_id"])
        if other is None:
            continue
        if other["_sched_start_dt"].date() == new_date:
            same_day += 1
    if same_day >= agreement["max_services_per_day"]:
        raise_err("ERR_UNION_DAILY_SERVICE_CAP")

    # rung 13 -- doubling limit
    if doubling_count > 2:
        raise_err("ERR_DOUBLING_LIMIT_EXCEEDED")

    engagement = base_fields()
    engagement.update({
        "service_id": service["id"],
        "musician_id": musician["id"],
        "doubling_count": doubling_count,
        "status": "CONFIRMED",
        "provisional_pay_cents": None,
        "final_pay_cents": None,
        "overtime_minutes": 0,
    })
    db.engagements[engagement["id"]] = engagement
    with touch(service):
        service["confirmed_engagement_count"] += 1
    return ok(serialize(engagement), 201)
