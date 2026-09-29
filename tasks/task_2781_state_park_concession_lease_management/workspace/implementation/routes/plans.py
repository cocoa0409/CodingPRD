"""Operating seasons, service levels and public rate standards — PRD 3.6."""
import calc
from auth import ALL_ROLES, fetch, guard, require_owner
from envelope import created, listing, ok
from errors import ApiError
from logic import closed_overlap, lease_of, park_of
from money import parse_date
from router import route
from shape import body, ref, req_date, req_enum, req_int, req_str
from store import db, insert, touch

SERVICE_LEVELS = ("FULL", "REDUCED", "WINTER_LIMITED")


@route("/operating-plans", methods=["POST"])
def plans_create():
    guard("Concessionaire")
    data = body()
    lease = None
    lease_ref = ref(data, "lease_id")
    if lease_ref is not None:
        lease = fetch(db.leases, lease_ref, "ERR_LEASE_NOT_FOUND")
        require_owner(lease["offeror_id"])
    row = {
        "lease_id": req_str(data, "lease_id"),
        "season_start": req_date(data, "season_start")[0],
        "season_end": req_date(data, "season_end")[0],
        "service_level": req_enum(data, "service_level", SERVICE_LEVELS),
        "max_lodging_rate_cents": req_int(data, "max_lodging_rate_cents", minimum=1),
        "max_meal_rate_cents": req_int(data, "max_meal_rate_cents", minimum=1),
        "max_activity_rate_cents": req_int(data, "max_activity_rate_cents", minimum=1),
        "deficiency_note": None,
        "status": "SUBMITTED",
    }
    expected_version = req_int(data, "expected_lease_version")
    if parse_date(row["season_start"]) > parse_date(row["season_end"]):
        raise ApiError("ERR_INVALID_INTERVAL", "season_start must be at or before season_end")
    if expected_version != lease["version"]:
        raise ApiError("ERR_STALE_LEASE_VERSION", "The lease version is stale")
    if lease["contract_status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "The lease is not ACTIVE")
    plan = insert(db.plans, row)
    touch(lease)
    return created(plan)


@route("/operating-plans/<plan_id>/approve", methods=["POST"])
def plans_approve(plan_id):
    guard("ContractingOfficer")
    plan = fetch(db.plans, plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_OPERATING_PLAN_STATUS_INVALID",
                       "Plan status %s cannot be approved" % plan["status"])
    lease = lease_of(plan)
    if lease is None or lease["contract_status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "The lease is not ACTIVE")
    season_start = parse_date(plan["season_start"])
    season_end = parse_date(plan["season_end"])
    for other in db.plans.values():
        if other["id"] == plan_id or other["status"] != "APPROVED":
            continue
        if other["lease_id"] != plan["lease_id"]:
            continue
        if closed_overlap(season_start, season_end,
                          parse_date(other["season_start"]), parse_date(other["season_end"])):
            raise ApiError("ERR_SEASON_OVERLAP",
                           "The season collides with an approved season on this lease")
    park = park_of(lease)
    if park is not None:
        pairs = (
            ("max_lodging_rate_cents", "comparable_lodging_rate_cents"),
            ("max_meal_rate_cents", "comparable_meal_rate_cents"),
            ("max_activity_rate_cents", "comparable_activity_rate_cents"),
        )
        for rate_field, benchmark_field in pairs:
            if plan[rate_field] > calc.rate_ceiling(park[benchmark_field]):
                raise ApiError("ERR_RATE_EXCEEDS_CEILING",
                               "%s exceeds the park's benchmark ceiling" % rate_field)
    plan["status"] = "APPROVED"
    touch(plan)
    return ok(plan)


@route("/operating-plans/<plan_id>/return", methods=["POST"])
def plans_return(plan_id):
    guard("ContractingOfficer")
    plan = fetch(db.plans, plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    data = body()
    note = req_str(data, "deficiency_note")
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_OPERATING_PLAN_STATUS_INVALID",
                       "Plan status %s cannot be returned" % plan["status"])
    plan["deficiency_note"] = note
    plan["status"] = "RETURNED"
    touch(plan)
    return ok(plan)


@route("/operating-plans/<plan_id>/resubmit", methods=["POST"])
def plans_resubmit(plan_id):
    guard("Concessionaire")
    plan = fetch(db.plans, plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    lease = lease_of(plan)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    season_start_raw, season_start = req_date(data, "season_start")
    season_end_raw, season_end = req_date(data, "season_end")
    service_level = req_enum(data, "service_level", SERVICE_LEVELS)
    lodging = req_int(data, "max_lodging_rate_cents", minimum=1)
    meal = req_int(data, "max_meal_rate_cents", minimum=1)
    activity = req_int(data, "max_activity_rate_cents", minimum=1)
    if season_start > season_end:
        raise ApiError("ERR_INVALID_INTERVAL", "season_start must be at or before season_end")
    if plan["status"] != "RETURNED":
        raise ApiError("ERR_OPERATING_PLAN_STATUS_INVALID",
                       "Plan status %s cannot be resubmitted" % plan["status"])
    plan["season_start"] = season_start_raw
    plan["season_end"] = season_end_raw
    plan["service_level"] = service_level
    plan["max_lodging_rate_cents"] = lodging
    plan["max_meal_rate_cents"] = meal
    plan["max_activity_rate_cents"] = activity
    plan["deficiency_note"] = None
    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok(plan)


@route("/operating-plans", methods=["GET"])
def plans_list():
    guard(*ALL_ROLES)
    return listing(db.plans, ("lease_id", "status"))


@route("/operating-plans/<plan_id>", methods=["GET"])
def plans_read(plan_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.plans, plan_id, "ERR_OPERATING_PLAN_NOT_FOUND"))
