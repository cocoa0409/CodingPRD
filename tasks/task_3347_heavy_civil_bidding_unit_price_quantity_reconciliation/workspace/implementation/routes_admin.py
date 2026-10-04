"""Routes: logical clock, sessions, sureties and surety commitments."""

from flask import request

import db
import services
import views
from response import array_response, object_response
from util import invalid_request, parse_pagination, read_body, require_int, require_str

ALL_ROLES = ("PlatformAdmin", "Estimator", "ContractingOfficer", "ProjectManager",
             "Engineer", "Surety")


def _filtered(records, **filters):
    out = records
    for field, value in filters.items():
        if value is not None:
            out = [r for r in out if r[field] == value]
    return out


def _paginate(records, view):
    limit, offset = parse_pagination()
    return array_response([view(r) for r in records], limit, offset)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock():
    payload = read_body(required=["to_iso8601"])
    services.set_current_utc(payload["to_iso8601"])
    return object_response({})


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session():
    payload = read_body(required=["role"], optional=["user_id"],
                        enums={"role": services.ROLES})
    user_id = payload.get("user_id")
    if user_id is not None and not isinstance(user_id, str):
        raise invalid_request("The field 'user_id' must be a string.")
    return object_response(services.create_session(payload["role"], user_id), 201)


# ---------------------------------------------------------------------------
# Surety
# ---------------------------------------------------------------------------

def create_surety():
    payload = read_body(required=["surety_name", "aggregate_capacity_cents",
                                  "single_job_limit_cents"])
    name = require_str(payload, "surety_name")
    aggregate = require_int(payload, "aggregate_capacity_cents", minimum=1)
    single_job = require_int(payload, "single_job_limit_cents", minimum=0)
    return object_response(views.surety_view(
        services.create_surety(name, aggregate, single_job)), 201)


def list_sureties():
    records = _filtered(db.ordered("surety"), surety_status=request.args.get("surety_status"))
    return _paginate(records, views.surety_view)


def get_surety(surety_id):
    return object_response(views.surety_view(services.get_surety(surety_id)))


def suspend_surety(surety_id):
    surety = services.get_surety(surety_id)
    return object_response(views.surety_view(services.suspend_surety(surety)))


def reinstate_surety(surety_id):
    surety = services.get_surety(surety_id)
    return object_response(views.surety_view(services.reinstate_surety(surety)))


# ---------------------------------------------------------------------------
# SuretyCommitment
# ---------------------------------------------------------------------------

def create_commitment():
    payload = read_body(required=["surety_id", "project_id", "committed_amount_cents"])
    surety_id = require_str(payload, "surety_id")
    project_id = require_str(payload, "project_id")
    amount = require_int(payload, "committed_amount_cents", minimum=1)
    record = services.create_commitment(surety_id, project_id, amount)
    return object_response(views.commitment_view(record), 201)


def list_commitments():
    records = _filtered(
        db.ordered("commitment"),
        surety_id=request.args.get("surety_id"),
        project_id=request.args.get("project_id"),
        commitment_status=request.args.get("commitment_status"),
    )
    return _paginate(records, views.commitment_view)


def get_commitment(commitment_id):
    return object_response(views.commitment_view(services.get_commitment(commitment_id)))


def release_commitment(commitment_id):
    commitment = services.get_commitment(commitment_id)
    return object_response(views.commitment_view(services.release_commitment(commitment)))


ROUTES = [
    ("POST", "/construction/_clock/set_current_utc", ("PlatformAdmin",), False, set_clock),
    ("POST", "/construction/sessions", ("Anonymous",), False, create_session),

    ("POST", "/construction/sureties", ("PlatformAdmin",), True, create_surety),
    ("GET", "/construction/sureties", ALL_ROLES, True, list_sureties),
    ("GET", "/construction/sureties/<surety_id>", ALL_ROLES, True, get_surety),
    ("POST", "/construction/sureties/<surety_id>/suspend", ("PlatformAdmin",), True, suspend_surety),
    ("POST", "/construction/sureties/<surety_id>/reinstate", ("PlatformAdmin",), True, reinstate_surety),

    ("POST", "/construction/surety-commitments", ("ContractingOfficer", "Estimator"), True,
     create_commitment),
    ("GET", "/construction/surety-commitments", ALL_ROLES, True, list_commitments),
    ("GET", "/construction/surety-commitments/<commitment_id>", ALL_ROLES, True, get_commitment),
    ("POST", "/construction/surety-commitments/<commitment_id>/release-commitment",
     ("ContractingOfficer",), True, release_commitment),
]
