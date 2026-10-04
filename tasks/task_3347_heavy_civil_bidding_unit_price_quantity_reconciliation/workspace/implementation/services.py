"""Administrative services: logical clock, sessions, sureties, commitments, bonds."""

from datetime import timedelta

import calc
import db
from errors import ApiError
from util import dec, parse_iso

# ---------------------------------------------------------------------------
# Lookup helpers — the referential-existence band of PRD 2.5
# ---------------------------------------------------------------------------


def get_project(project_id):
    record = db.find("project", project_id)
    if record is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", "No project resolves to %s." % project_id, 404)
    return record


def get_item(item_id):
    record = db.find("bid_item", item_id)
    if record is None:
        raise ApiError("ERR_BID_ITEM_NOT_FOUND", "No pay item resolves to %s." % item_id, 404)
    return record


def get_item_in_project(project, item_id):
    record = db.find("bid_item", item_id)
    if record is None or record["project_id"] != project["id"]:
        raise ApiError("ERR_BID_ITEM_NOT_FOUND",
                       "No pay item %s belongs to project %s." % (item_id, project["id"]), 404)
    return record


def get_surety(surety_id):
    record = db.find("surety", surety_id)
    if record is None:
        raise ApiError("ERR_SURETY_NOT_FOUND", "No surety resolves to %s." % surety_id, 404)
    return record


def get_quote(quote_id):
    record = db.find("quote", quote_id)
    if record is None:
        raise ApiError("ERR_QUOTE_NOT_FOUND", "No quote resolves to %s." % quote_id, 404)
    return record


def get_bond(bond_id):
    record = db.find("bond", bond_id)
    if record is None:
        raise ApiError("ERR_BOND_NOT_FOUND", "No bond resolves to %s." % bond_id, 404)
    return record


def get_measurement(measurement_id):
    record = db.find("measurement", measurement_id)
    if record is None:
        raise ApiError("ERR_MEASUREMENT_NOT_FOUND",
                       "No measurement resolves to %s." % measurement_id, 404)
    return record


def get_reconciliation_in_project(project, reconciliation_id):
    record = db.find("reconciliation", reconciliation_id)
    if record is None or record["project_id"] != project["id"]:
        raise ApiError("ERR_RECONCILIATION_NOT_FOUND",
                       "No reconciliation %s belongs to project %s."
                       % (reconciliation_id, project["id"]), 404)
    return record


def get_condition(condition_id):
    record = db.find("condition", condition_id)
    if record is None:
        raise ApiError("ERR_CONDITION_NOT_FOUND",
                       "No differing site condition resolves to %s." % condition_id, 404)
    return record


def get_determination(determination_id):
    record = db.find("determination", determination_id)
    if record is None:
        raise ApiError("ERR_DETERMINATION_NOT_FOUND",
                       "No engineer determination resolves to %s." % determination_id, 404)
    return record


def get_commitment(commitment_id):
    record = db.find("commitment", commitment_id)
    if record is None:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND",
                       "No surety commitment resolves to %s." % commitment_id, 404)
    return record


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_current_utc(to_iso8601):
    moment = parse_iso(to_iso8601)
    db.set_clock(moment)
    for condition in db.CONDITIONS.values():
        condition["notice_days_elapsed"] = calc.notice_days_elapsed(condition)
    return {}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

ROLES = ("PlatformAdmin", "Estimator", "ContractingOfficer", "ProjectManager",
         "Engineer", "Surety", "Anonymous")


def create_session(role, user_id=None):
    token = "sess_" + db.new_id().replace("-", "")
    resolved_user = user_id if user_id else ("user_" + db.new_id().replace("-", "")[:16])
    return {
        "session_token": token,
        "role": role,
        "user_id": resolved_user,
    }


# ---------------------------------------------------------------------------
# Surety
# ---------------------------------------------------------------------------

def create_surety(surety_name, aggregate_capacity_cents, single_job_limit_cents):
    for existing in db.SURETIES.values():
        if existing["surety_name"] == surety_name:
            raise ApiError("ERR_INVALID_REQUEST",
                           "A surety named %r is already registered." % surety_name, 400)
    if aggregate_capacity_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "aggregate_capacity_cents must be strictly greater than zero.", 400)
    if single_job_limit_cents > aggregate_capacity_cents:
        raise ApiError("ERR_INVALID_REQUEST",
                       "single_job_limit_cents must not exceed aggregate_capacity_cents.", 400)
    if single_job_limit_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "single_job_limit_cents must not be negative.", 400)
    record = db.create("surety", {
        "surety_name": surety_name,
        "aggregate_capacity_cents": aggregate_capacity_cents,
        "single_job_limit_cents": single_job_limit_cents,
        "capacity_consumed_cents": 0,
        "available_capacity_cents": aggregate_capacity_cents,
        "unavailable_capacity_cents": 0,
        "surety_status": "ACTIVE",
    })
    return record


def suspend_surety(surety):
    if surety["surety_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The surety is not ACTIVE.", 409)
    surety["surety_status"] = "SUSPENDED"
    calc.recalc_surety(surety)
    return surety


def reinstate_surety(surety):
    if surety["surety_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "The surety is not SUSPENDED.", 409)
    surety["surety_status"] = "ACTIVE"
    calc.recalc_surety(surety)
    return surety


# ---------------------------------------------------------------------------
# SuretyCommitment
# ---------------------------------------------------------------------------

def _intersects(start_a, end_a, start_b, end_b):
    """Half-open interval intersection; None means unbounded."""
    if end_b is not None and start_a >= end_b:
        return False
    if end_a is not None and start_b >= end_a:
        return False
    return True


def create_commitment(surety_id, project_id, committed_amount_cents):
    project = get_project(project_id)
    surety = get_surety(surety_id)
    if committed_amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "committed_amount_cents must be strictly greater than zero.", 400)

    now = db.clock()
    intersecting = 0
    for commitment in db.COMMITMENTS.values():
        if commitment["surety_id"] != surety["id"]:
            continue
        if commitment["commitment_status"] not in ("RESERVED", "ACTIVE"):
            continue
        if _intersects(now, None, commitment["reserved_at"], commitment["released_at"]):
            intersecting += commitment["committed_amount_cents"]
    if intersecting + committed_amount_cents > surety["aggregate_capacity_cents"]:
        raise ApiError("ERR_AGGREGATE_CAPACITY_EXCEEDED",
                       "The reservation would exceed the surety's aggregate capacity.", 422)

    record = db.create("commitment", {
        "surety_id": surety["id"],
        "project_id": project["id"],
        "committed_amount_cents": committed_amount_cents,
        "commitment_status": "RESERVED",
        "reserved_at": now,
        "released_at": None,
    })
    calc.recalc_surety(surety)
    return record


def release_commitment(commitment):
    if commitment["commitment_status"] not in ("RESERVED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", "The commitment is not RESERVED or ACTIVE.", 409)
    commitment["commitment_status"] = "RELEASED"
    commitment["released_at"] = db.clock()
    db.touch(commitment)
    surety = get_surety(commitment["surety_id"])
    calc.recalc_surety(surety)
    return commitment


# ---------------------------------------------------------------------------
# Bond
# ---------------------------------------------------------------------------

BOND_TYPES = ("BID", "PERFORMANCE", "PAYMENT", "MAINTENANCE")


def create_bond(project_id, surety_id, bond_type, bond_amount_cents, effective_from,
                effective_to, maintain_bond_horizon_days=30):
    project = get_project(project_id)
    surety = get_surety(surety_id)
    if bond_amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "bond_amount_cents must be strictly greater than zero.", 400)
    start = parse_iso(effective_from)
    end = parse_iso(effective_to)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_to must fall strictly after effective_from.", 400)
    if maintain_bond_horizon_days < 1 or maintain_bond_horizon_days > 365:
        raise ApiError("ERR_INVALID_REQUEST",
                       "maintain_bond_horizon_days must be between 1 and 365.", 400)

    record = db.create("bond", {
        "project_id": project["id"],
        "surety_id": surety["id"],
        "bond_type": bond_type,
        "bond_amount_cents": bond_amount_cents,
        "required_bond_cents": 0,
        "bond_status": "PENDING",
        "effective_from": start,
        "effective_to": end,
        "maintain_bond_horizon_days": maintain_bond_horizon_days,
        "issued_at": None,
        "released_at": None,
        "lien_claim_amount_cents": 0,
        "capacity_consumed_cents": 0,
    })
    record["required_bond_cents"] = calc.required_bond_cents(record, project)
    return record


def _intervals_intersect(bond, other):
    return _intersects(bond["effective_from"], bond["effective_to"],
                       other["effective_from"], other["effective_to"])


def issue_bond(bond, actor_user_id):
    if bond["surety_id"] != actor_user_id:
        raise ApiError("ERR_FORBIDDEN",
                       "A surety may only issue bonds against its own surety_id.", 403)
    if bond["bond_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The bond is not PENDING.", 409)
    project = get_project(bond["project_id"])
    surety = get_surety(bond["surety_id"])

    if surety["surety_status"] != "ACTIVE":
        raise ApiError("ERR_SURETY_SUSPENDED",
                       "The backing surety is suspended and may not issue bonds.", 422)

    for other in db.BONDS.values():
        if other["id"] == bond["id"]:
            continue
        if other["project_id"] != bond["project_id"]:
            continue
        if other["bond_type"] != bond["bond_type"]:
            continue
        if other["bond_status"] not in ("ISSUED", "EXECUTED"):
            continue
        if _intervals_intersect(bond, other):
            raise ApiError("ERR_RESERVATION_OVERLAP",
                           "Another bond of the same type covers an intersecting interval.", 409)

    bond["required_bond_cents"] = calc.required_bond_cents(bond, project)
    if bond["required_bond_cents"] > bond["bond_amount_cents"]:
        raise ApiError("ERR_BOND_AMOUNT_INSUFFICIENT",
                       "The bond's face amount is below its statutory requirement.", 422)

    available = calc.surety_available_cents(surety)
    if available < bond["bond_amount_cents"]:
        raise ApiError("ERR_AGGREGATE_CAPACITY_EXCEEDED",
                       "The bond exceeds the surety's available capacity.", 422)
    if bond["bond_type"] == "PERFORMANCE" and bond["bond_amount_cents"] > surety["single_job_limit_cents"]:
        raise ApiError("ERR_AGGREGATE_CAPACITY_EXCEEDED",
                       "The bond exceeds the surety's single-job limit.", 422)

    bond["bond_status"] = "ISSUED"
    bond["issued_at"] = db.clock()
    bond["capacity_consumed_cents"] = bond["bond_amount_cents"]
    if bond["bond_type"] == "PERFORMANCE":
        bond["required_bond_cents"] = calc.required_bond_cents(bond, project)
    db.touch(bond)
    calc.recalc_surety(surety)
    return bond


def execute_bond(bond):
    if bond["bond_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "The bond is not ISSUED.", 409)
    if bond["bond_type"] != "PERFORMANCE":
        raise ApiError("ERR_INVALID_STATE", "Only a performance bond may be called.", 409)
    project = get_project(bond["project_id"])
    lien_claim = 0
    for other in db.BONDS.values():
        if other["project_id"] == project["id"] and other["bond_type"] == "PAYMENT":
            lien_claim += calc.lien_claim_amount_cents(other, project)
    if lien_claim <= 0:
        raise ApiError("ERR_NO_LIEN_CLAIM",
                       "The project's payment bond shows no outstanding lien claim.", 422)
    bond["bond_status"] = "EXECUTED"
    bond["capacity_consumed_cents"] = bond["bond_amount_cents"]
    db.touch(bond)
    surety = get_surety(bond["surety_id"])
    calc.recalc_surety(surety)
    return bond


def release_bond(bond):
    project = get_project(bond["project_id"])
    status = bond["bond_status"]
    if status == "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "The bond is already RELEASED.", 409)
    if status == "ISSUED":
        reconciliation = calc.latest_reconciliation(project)
        if project["project_status"] != "COMPLETE":
            raise ApiError("ERR_INVALID_STATE",
                           "An issued bond may only be released once the project is COMPLETE.", 409)
        if reconciliation is None or reconciliation["reconciliation_status"] != "CLOSED":
            raise ApiError("ERR_INVALID_STATE",
                           "An issued bond may only be released once the reconciliation is CLOSED.", 409)
    elif status == "EXECUTED":
        if project["project_status"] != "COMPLETE":
            raise ApiError("ERR_INVALID_STATE",
                           "An executed bond may only be released once the project is COMPLETE.", 409)
    bond["bond_status"] = "RELEASED"
    bond["released_at"] = db.clock()
    bond["capacity_consumed_cents"] = 0
    db.touch(bond)
    surety = get_surety(bond["surety_id"])
    calc.recalc_surety(surety)
    return bond
