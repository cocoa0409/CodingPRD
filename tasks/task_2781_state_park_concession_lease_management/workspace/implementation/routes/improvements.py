"""Capital improvements, closure windows and the maintenance split — PRD 3.7."""
import calc
from auth import ALL_ROLES, fetch, guard, require_owner
from envelope import created, listing, ok
from errors import ApiError
from logic import (bond_of, bump_closure_count, half_open_overlap, lease_of, park_of)
from money import add_days, parse_date
from router import route
from shape import body, ref, req_date, req_enum, req_int, req_str
from store import clock_date, db, insert, touch

FUNDING_SOURCES = ("CONCESSIONAIRE_CAPITAL", "MAINTENANCE_RESERVE")
OWNERSHIP_AT_EXPIRATION = ("AGENCY", "CONCESSIONAIRE")
BOND_OK_FOR_CONSTRUCTION = ("ACTIVE", "PARTIALLY_DRAWN")


def _window_inside_term(lease, start, end):
    term_start = parse_date(lease["term_start"])
    limit = add_days(parse_date(lease["term_end"]), 1)
    return start >= term_start and end <= limit


@route("/capital-improvements", methods=["POST"])
def improvements_create():
    guard("Concessionaire")
    data = body()
    lease = None
    lease_ref = ref(data, "lease_id")
    if lease_ref is not None:
        lease = fetch(db.leases, lease_ref, "ERR_LEASE_NOT_FOUND")
        require_owner(lease["offeror_id"])
    row = {
        "lease_id": req_str(data, "lease_id"),
        "park_id": lease["park_id"],
        "description": req_str(data, "description"),
        "funding_source": req_enum(data, "funding_source", FUNDING_SOURCES),
        "proposed_cost_cents": req_int(data, "proposed_cost_cents", minimum=1),
        "approved_cost_cents": None,
        "actual_cost_cents": None,
        "useful_life_years": req_int(data, "useful_life_years", minimum=1, maximum=40),
        "construction_window_start": req_date(data, "construction_window_start")[0],
        "construction_window_end": req_date(data, "construction_window_end")[0],
        "in_service_date": None,
        "ownership_at_expiration": req_enum(data, "ownership_at_expiration",
                                           OWNERSHIP_AT_EXPIRATION),
        "unamortized_value_cents": None,
        "deficiency_note": None,
        "status": "PROPOSED",
    }
    start = parse_date(row["construction_window_start"])
    end = parse_date(row["construction_window_end"])
    if not start < end:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "construction_window_start must be strictly before its exclusive end")
    if lease["contract_status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "The lease is not ACTIVE")
    if not _window_inside_term(lease, start, end):
        raise ApiError("ERR_CONSTRUCTION_WINDOW_OUTSIDE_TERM",
                       "The closure window falls outside the contract term")
    return created(insert(db.improvements, row))


@route("/capital-improvements/<improvement_id>/approve", methods=["POST"])
def improvements_approve(improvement_id):
    guard("ContractingOfficer")
    improvement = fetch(db.improvements, improvement_id, "ERR_IMPROVEMENT_NOT_FOUND")
    data = body()
    approved_cost = req_int(data, "approved_cost_cents")
    if improvement["status"] != "PROPOSED":
        raise ApiError("ERR_IMPROVEMENT_STATUS_INVALID",
                       "Improvement status %s cannot be approved" % improvement["status"])
    lease = lease_of(improvement)
    if lease is None or lease["contract_status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "The lease is not ACTIVE")
    bond = bond_of(lease)
    if bond is None or bond["status"] not in BOND_OK_FOR_CONSTRUCTION:
        raise ApiError("ERR_BOND_NOT_ACTIVE",
                       "The performance bond does not support construction")
    expires_on = parse_date(lease["insurance_expires_on"]) \
        if lease["insurance_expires_on"] else None
    if expires_on is None or not expires_on > clock_date():
        raise ApiError("ERR_INSURANCE_LAPSED", "The certificate of insurance is not in force")
    start = parse_date(improvement["construction_window_start"])
    end = parse_date(improvement["construction_window_end"])
    overlapping = 0
    for other in db.improvements.values():
        if other["id"] == improvement_id or other["status"] != "APPROVED":
            continue
        if other["park_id"] != improvement["park_id"]:
            continue
        if half_open_overlap(start, end,
                            parse_date(other["construction_window_start"]),
                            parse_date(other["construction_window_end"])):
            overlapping = overlapping + 1
    if not overlapping < calc.MAX_OVERLAPPING_PARK_CLOSURES:
        raise ApiError("ERR_PARK_CLOSURE_CAPACITY",
                       "The park already has its maximum concurrent closures")
    if improvement["funding_source"] == "CONCESSIONAIRE_CAPITAL":
        committed = 0
        for other in db.improvements.values():
            if (other["lease_id"] == improvement["lease_id"]
                    and other["status"] == "APPROVED"
                    and other["approved_cost_cents"] is not None):
                committed = committed + other["approved_cost_cents"]
        total = lease["capital_investment_completed_cents"] + committed + approved_cost
        if total > lease["capital_investment_obligation_cents"]:
            raise ApiError("ERR_IMPROVEMENT_EXCEEDS_OBLIGATION",
                           "The approval would exceed the capital investment obligation")
    else:
        if approved_cost > lease["maintenance_reserve_balance_cents"]:
            raise ApiError("ERR_MAINTENANCE_RESERVE_INSUFFICIENT",
                           "The approval exceeds the accrued maintenance reserve")
    improvement["approved_cost_cents"] = approved_cost
    improvement["status"] = "APPROVED"
    touch(improvement)
    bump_closure_count(park_of(lease), 1)
    if improvement["funding_source"] == "MAINTENANCE_RESERVE":
        lease["maintenance_reserve_balance_cents"] = \
            lease["maintenance_reserve_balance_cents"] - approved_cost
        touch(lease)
    return ok(improvement)


@route("/capital-improvements/<improvement_id>/return", methods=["POST"])
def improvements_return(improvement_id):
    guard("ContractingOfficer")
    improvement = fetch(db.improvements, improvement_id, "ERR_IMPROVEMENT_NOT_FOUND")
    data = body()
    note = req_str(data, "deficiency_note")
    if improvement["status"] != "PROPOSED":
        raise ApiError("ERR_IMPROVEMENT_STATUS_INVALID",
                       "Improvement status %s cannot be returned" % improvement["status"])
    improvement["deficiency_note"] = note
    improvement["status"] = "RETURNED"
    touch(improvement)
    return ok(improvement)


@route("/capital-improvements/<improvement_id>/resubmit", methods=["POST"])
def improvements_resubmit(improvement_id):
    guard("Concessionaire")
    improvement = fetch(db.improvements, improvement_id, "ERR_IMPROVEMENT_NOT_FOUND")
    lease = lease_of(improvement)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    proposed_cost = req_int(data, "proposed_cost_cents", minimum=1)
    useful_life = req_int(data, "useful_life_years", minimum=1, maximum=40)
    start_raw, start = req_date(data, "construction_window_start")
    end_raw, end = req_date(data, "construction_window_end")
    if not start < end:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "construction_window_start must be strictly before its exclusive end")
    if improvement["status"] != "RETURNED":
        raise ApiError("ERR_IMPROVEMENT_STATUS_INVALID",
                       "Improvement status %s cannot be resubmitted" % improvement["status"])
    if lease is None or not _window_inside_term(lease, start, end):
        raise ApiError("ERR_CONSTRUCTION_WINDOW_OUTSIDE_TERM",
                       "The closure window falls outside the contract term")
    improvement["proposed_cost_cents"] = proposed_cost
    improvement["useful_life_years"] = useful_life
    improvement["construction_window_start"] = start_raw
    improvement["construction_window_end"] = end_raw
    improvement["deficiency_note"] = None
    improvement["status"] = "PROPOSED"
    touch(improvement)
    return ok(improvement)


@route("/capital-improvements/<improvement_id>/place-in-service", methods=["POST"])
def improvements_place_in_service(improvement_id):
    guard("Concessionaire")
    improvement = fetch(db.improvements, improvement_id, "ERR_IMPROVEMENT_NOT_FOUND")
    lease = lease_of(improvement)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    actual_cost = req_int(data, "actual_cost_cents", minimum=0)
    in_service_raw, in_service = req_date(data, "in_service_date")
    if improvement["status"] != "APPROVED":
        raise ApiError("ERR_IMPROVEMENT_STATUS_INVALID",
                       "Improvement status %s cannot be placed in service"
                       % improvement["status"])
    if in_service < parse_date(improvement["construction_window_start"]):
        raise ApiError("ERR_IN_SERVICE_BEFORE_WINDOW",
                       "The in-service date precedes the construction window")
    improvement["actual_cost_cents"] = actual_cost
    improvement["in_service_date"] = in_service_raw
    improvement["status"] = "COMPLETED"
    touch(improvement)
    bump_closure_count(park_of(lease) if lease is not None else None, -1)
    if lease is not None:
        credit = min(actual_cost, improvement["approved_cost_cents"])
        lease["capital_investment_completed_cents"] = \
            lease["capital_investment_completed_cents"] + credit
        touch(lease)
    return ok(improvement)


@route("/capital-improvements", methods=["GET"])
def improvements_list():
    guard(*ALL_ROLES)
    return listing(db.improvements, ("lease_id", "park_id", "status"))


@route("/capital-improvements/<improvement_id>", methods=["GET"])
def improvements_read(improvement_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.improvements, improvement_id, "ERR_IMPROVEMENT_NOT_FOUND"))
