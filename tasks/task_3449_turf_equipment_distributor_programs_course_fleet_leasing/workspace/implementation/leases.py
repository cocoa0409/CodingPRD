"""Fleet lease origination and lifecycle; lease lines expand to LeaseUnits."""
from flask import Blueprint

import appraisals
import calculations as calc
import clock
import helpers
from helpers import as_int, as_str, auth, body, fail, ok, req, require_role, identity_entity
import storage
from storage import STORES, new_record, public, sort_created, touch

bp = Blueprint("leases", __name__)

READ_ROLES = ("CorporateAdmin", "DistributorManager", "CourseManager")

_TRANSITIONS = {
    ("DRAFT", "SPEC_REVIEW"): "DistributorManager",
    ("SPEC_REVIEW", "DRAFT"): "DistributorManager",
    ("SPEC_REVIEW", "APPROVED"): "CorporateAdmin",
    ("APPROVED", "ACTIVE"): "DistributorManager",
    ("DRAFT", "CANCELLED"): "DistributorManager",
    ("SPEC_REVIEW", "CANCELLED"): "CorporateAdmin",
}

OVERLAP_STATES = ("APPROVED", "ACTIVE", "TURNOVER_IN_PROGRESS")


def _parse_lines(raw_lines):
    lines = helpers.as_array(raw_lines, "lines")
    if len(lines) == 0:
        fail("ERR_INVALID_REQUEST", "lease must contain at least one line")
    parsed = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "lines[%d] must be an object" % i)
        model_id = as_str(req(line, "model_id"), "lines[%d].model_id" % i)
        qty = as_int(req(line, "qty"), "lines[%d].qty" % i)
        helpers.get_or_404("models", model_id, "model")
        if qty < 1:
            fail("ERR_INVALID_REQUEST", "lines[%d].qty must be >= 1" % i)
        parsed.append({"model_id": model_id, "qty": qty})
    return parsed


def _closed_overlap(a_start, a_end, b_start, b_end):
    """Closed intervals: shared boundary dates count as overlap."""
    return a_start <= b_end and b_start <= a_end


def _sibling_overlap(course_id, start, end, exclude_id=None):
    for sib in STORES["leases"].values():
        if sib["course_id"] != course_id or sib["id"] == exclude_id:
            continue
        if sib["status"] in OVERLAP_STATES and _closed_overlap(start, end, sib["_start_date"], sib["_end_date"]):
            return True
    return False


@bp.post("/leases")
def create_lease():
    role, uid = auth()
    require_role(role, ("DistributorManager",))
    d = identity_entity(role, uid)
    b = body()
    course_id = as_str(req(b, "course_id"), "course_id")
    course = helpers.get_or_404("courses", course_id, "course")
    lines = _parse_lines(req(b, "lines"))
    cycle_months = as_int(req(b, "cycle_months"), "cycle_months")
    if cycle_months < 1:
        fail("ERR_INVALID_REQUEST", "cycle_months must be >= 1")
    start_raw = as_str(req(b, "start_date"), "start_date")
    start = helpers.as_date(start_raw, "start_date")
    # P9 territory integrity
    if course["assigned_distributor_id"] != uid:
        fail("ERR_TERRITORY_MISMATCH", "course is assigned to a different distributor")
    # P10 temporal: start not before the current logical date
    if start < clock.today():
        fail("ERR_WINDOW_IN_PAST", "start_date lies before the current logical date")
    end = clock.add_months(start, cycle_months)
    if _sibling_overlap(course_id, start, end):
        fail("ERR_LEASE_CYCLE_OVERLAP", "closed [start_date, end_date] intersects a sibling lease")
    # P11 sellable models
    for line in lines:
        if STORES["models"][line["model_id"]]["lifecycle_status"] != "CATALOG_ACTIVE":
            fail("ERR_MODEL_DISCONTINUED", "model " + line["model_id"] + " is past its sales window")
    if d["status"] == "TERMINATED":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", "terminated distributor is read-only")
    rec = new_record("leases", {
        "course_id": course_id,
        "distributor_id": uid,
        "cycle_months": cycle_months,
        "start_date": start_raw,
        "end_date": end.isoformat(),
        "lines": lines,
        "spec_compliant": None,
        "base_value_cents": None,
        "total_contract_value_cents": None,
        "trade_in_credit_cents": 0,
        "net_contract_value_cents": None,
        "monthly_rate_cents": None,
        "billed_to_date_cents": 0,
        "remaining_balance_cents": None,
        "status": "DRAFT",
        "_start_date": start,
        "_end_date": end,
    })
    # Lease lines expand to LeaseUnit rows in line order; unit_seq is 1-based
    # in expansion order and remains the canonical list sort key.
    seq = 0
    for line in lines:
        for _ in range(line["qty"]):
            seq += 1
            new_record("units", {
                "lease_id": rec["id"],
                "model_id": line["model_id"],
                "unit_seq": seq,
                "serial_number": None,
                "hours_used": None,
                "condition_grade": None,
                "delivered_at": None,
                "returned_at": None,
                "asking_price_cents": None,
                "floor_price_cents": None,
                "sale_price_cents": None,
                "reserved_by_course_id": None,
                "reservation_expires_at": None,
                "status": "ORDERED",
                "_res_expires_dt": None,
            })
    return ok(public(rec), 201)


@bp.get("/leases/<lid>")
def get_lease(lid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    lease = helpers.get_or_404("leases", lid, "lease")
    return ok(public(lease))


@bp.get("/leases")
def list_leases():
    role, uid = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(sort_created(STORES["leases"].values()), {
        "course_id": "course_id",
        "distributor_id": "distributor_id",
        "status": "status",
    })
    return helpers.paginate(recs)


@bp.post("/leases/<lid>/transition")
def transition_lease(lid):
    role, uid = auth()
    require_role(role, ("CorporateAdmin", "DistributorManager"))
    if role == "DistributorManager":
        identity_entity(role, uid)
    lease = helpers.get_or_404("leases", lid, "lease")
    if role == "DistributorManager" and lease["distributor_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "lease belongs to another distributor")
    b = body()
    to = as_str(req(b, "to"), "to")
    expected = as_int(req(b, "expected_lease_version"), "expected_lease_version")
    key = (lease["status"], to)
    if key not in _TRANSITIONS:
        fail("ERR_INVALID_STATE", "lease cannot move from " + lease["status"] + " to " + str(to))
    if role != _TRANSITIONS[key]:
        fail("ERR_UNAUTHORIZED", "role " + role + " may not drive lease to " + to)
    # P7: lease optimistic concurrency (surfaces before territory/fiscal issues)
    if expected != lease["version"]:
        fail("ERR_STALE_LEASE_VERSION", "expected_lease_version does not match the lease version")

    d = STORES["distributors"][lease["distributor_id"]]
    course = STORES["courses"][lease["course_id"]]

    if key == ("DRAFT", "SPEC_REVIEW"):
        if d["channel"] != "EQUIPMENT":
            fail("ERR_WRONG_CHANNEL", "fleet leases require the EQUIPMENT channel")
        if d["status"] != "ACTIVE":
            fail("ERR_DISTRIBUTOR_NOT_ACTIVE", "distributor standing is not ACTIVE")
        lease["spec_compliant"] = calc.equipment_spec_compliant(lease["lines"], course)

    elif key == ("SPEC_REVIEW", "DRAFT"):
        appraisals.revert_appraisals(lease["id"])

    elif key == ("SPEC_REVIEW", "APPROVED"):
        # Global priority tiers: overlap (P10) -> sellable models (P11) ->
        # standing and spec (P12) -> credit ceiling (P13).
        if _sibling_overlap(lease["course_id"], lease["_start_date"], lease["_end_date"], exclude_id=lease["id"]):
            fail("ERR_LEASE_CYCLE_OVERLAP", "closed [start_date, end_date] intersects a sibling lease")
        for line in lease["lines"]:
            if STORES["models"][line["model_id"]]["lifecycle_status"] != "CATALOG_ACTIVE":
                fail("ERR_MODEL_DISCONTINUED", "model " + line["model_id"] + " is past its sales window")
        if d["status"] != "ACTIVE":
            fail("ERR_DISTRIBUTOR_NOT_ACTIVE", "distributor standing is not ACTIVE")
        if lease["spec_compliant"] is not True:
            fail("ERR_SPEC_VIOLATION", "lease lines violate the course equipment specification")
        to_credit = [a for a in STORES["appraisals"].values()
                     if a["lease_id"] == lease["id"] and a["status"] == "ACCEPTED"]
        rate = calc.fleet_lease_rate(lease, course, to_credit)
        if rate["total_contract_value_cents"] > course["credit_limit_cents"]:
            fail("ERR_CREDIT_LIMIT_EXCEEDED", "total contract value exceeds the course credit limit")
        lease["base_value_cents"] = rate["base_value_cents"]
        lease["total_contract_value_cents"] = rate["total_contract_value_cents"]
        lease["trade_in_credit_cents"] = rate["trade_in_credit_cents"]
        lease["net_contract_value_cents"] = rate["net_contract_value_cents"]
        lease["monthly_rate_cents"] = rate["monthly_rate_cents"]
        lease["billed_to_date_cents"] = 0
        lease["remaining_balance_cents"] = rate["net_contract_value_cents"]
        for a in to_credit:
            a["status"] = "CREDITED"
            touch(a)

    elif key == ("APPROVED", "ACTIVE"):
        if clock.today() < lease["_start_date"]:
            fail("ERR_LEASE_NOT_STARTED", "current logical date is before start_date")
        if course["status"] in ("PROSPECT", "IN_RENEWAL"):
            course["status"] = "ACTIVE_LEASE"
            touch(course)

    elif key in (("DRAFT", "CANCELLED"), ("SPEC_REVIEW", "CANCELLED")):
        appraisals.revert_appraisals(lease["id"])

    lease["status"] = to
    touch(lease)
    return ok(public(lease))
