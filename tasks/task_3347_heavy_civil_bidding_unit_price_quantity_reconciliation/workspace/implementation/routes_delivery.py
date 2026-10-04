"""Routes: bonds, progress measurements, reconciliations, claims and determinations."""

from flask import request

import db
import services
import services_delivery as svc
import views
from errors import ApiError
from response import array_response, object_response
from util import parse_pagination, read_body, require_int, require_str

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
# Bond
# ---------------------------------------------------------------------------

def create_bond():
    payload = read_body(
        required=["project_id", "surety_id", "bond_type", "bond_amount_cents",
                  "effective_from", "effective_to"],
        optional=["maintain_bond_horizon_days"],
        enums={"bond_type": services.BOND_TYPES},
    )
    project_id = require_str(payload, "project_id")
    surety_id = require_str(payload, "surety_id")
    amount = require_int(payload, "bond_amount_cents", minimum=1)
    horizon = require_int(payload, "maintain_bond_horizon_days", minimum=1, maximum=365) \
        if payload.get("maintain_bond_horizon_days") is not None else 30
    record = services.create_bond(project_id, surety_id, payload["bond_type"], amount,
                                  payload["effective_from"], payload["effective_to"], horizon)
    return object_response(views.bond_view(record), 201)


def list_bonds():
    records = _filtered(
        db.ordered("bond"),
        project_id=request.args.get("project_id"),
        surety_id=request.args.get("surety_id"),
        bond_type=request.args.get("bond_type"),
        bond_status=request.args.get("bond_status"),
    )
    return _paginate(records, views.bond_view)


def get_bond(bond_id):
    return object_response(views.bond_view(services.get_bond(bond_id)))


def issue_bond(bond_id):
    bond = services.get_bond(bond_id)
    actor = request.headers.get("X-User-ID")
    return object_response(views.bond_view(services.issue_bond(bond, actor)))


def execute_bond(bond_id):
    bond = services.get_bond(bond_id)
    return object_response(views.bond_view(services.execute_bond(bond)))


def release_bond(bond_id):
    bond = services.get_bond(bond_id)
    return object_response(views.bond_view(services.release_bond(bond)))


# ---------------------------------------------------------------------------
# ProgressMeasurement
# ---------------------------------------------------------------------------

def create_measurement(bid_item_id):
    payload = read_body(required=["measured_quantity", "measured_at", "expected_bid_item_version"])
    item = services.get_item(bid_item_id)
    return object_response(views.measurement_view(svc.create_measurement(item, payload)), 201)


def list_measurements():
    records = _filtered(
        db.ordered("measurement"),
        bid_item_id=request.args.get("bid_item_id"),
        measurement_status=request.args.get("measurement_status"),
    )
    return _paginate(records, views.measurement_view)


def get_measurement(measurement_id):
    return object_response(views.measurement_view(services.get_measurement(measurement_id)))


def approve_measurement(measurement_id):
    measurement = services.get_measurement(measurement_id)
    return object_response(views.measurement_view(svc.approve_measurement(measurement)))


def pay_measurement(measurement_id):
    measurement = services.get_measurement(measurement_id)
    return object_response(views.measurement_view(svc.pay_measurement(measurement)))


def void_measurement(measurement_id):
    measurement = services.get_measurement(measurement_id)
    return object_response(views.measurement_view(svc.void_measurement(measurement)))


# ---------------------------------------------------------------------------
# QuantityReconciliation
# ---------------------------------------------------------------------------

def open_reconciliation(project_id):
    project = services.get_project(project_id)
    return object_response(views.reconciliation_view(svc.open_reconciliation(project)), 201)


def list_reconciliations():
    records = _filtered(
        db.ordered("reconciliation"),
        project_id=request.args.get("project_id"),
        reconciliation_status=request.args.get("reconciliation_status"),
    )
    return _paginate(records, views.reconciliation_view)


def get_reconciliation(reconciliation_id):
    reconciliation = db.find("reconciliation", reconciliation_id)
    if reconciliation is None:
        raise ApiError("ERR_RECONCILIATION_NOT_FOUND",
                       "No reconciliation resolves to %s." % reconciliation_id, 404)
    return object_response(views.reconciliation_view(reconciliation))


def finalize_reconciliation(project_id, id):
    payload = read_body(required=["expected_project_version"])
    project = services.get_project(project_id)
    reconciliation = services.get_reconciliation_in_project(project, id)
    expected = require_int(payload, "expected_project_version")
    return object_response(views.reconciliation_view(
        svc.finalize_reconciliation(project, reconciliation, expected)))


def release_retention(project_id, id):
    project = services.get_project(project_id)
    reconciliation = services.get_reconciliation_in_project(project, id)
    return object_response(views.reconciliation_view(
        svc.release_retention(project, reconciliation)))


# ---------------------------------------------------------------------------
# DifferingSiteCondition
# ---------------------------------------------------------------------------

def report_condition():
    payload = read_body(required=["project_id", "reported_at"], optional=["claimed_amount_cents"])
    return object_response(views.condition_view(svc.report_condition(payload)), 201)


def list_conditions():
    records = _filtered(
        db.ordered("condition"),
        project_id=request.args.get("project_id"),
        condition_status=request.args.get("condition_status"),
    )
    return _paginate(records, views.condition_view)


def get_condition(condition_id):
    return object_response(views.condition_view(services.get_condition(condition_id)))


def document_condition(condition_id):
    payload = read_body(optional=["documentation_package_urls"])
    condition = services.get_condition(condition_id)
    return object_response(views.condition_view(svc.document_condition(condition, payload)))


def submit_claim(condition_id):
    condition = services.get_condition(condition_id)
    return object_response(views.condition_view(svc.submit_claim(condition)))


def return_for_documentation(condition_id):
    condition = services.get_condition(condition_id)
    return object_response(views.condition_view(svc.return_for_documentation(condition)))


def engineer_determination(condition_id):
    payload = read_body(
        required=["determination_type"],
        optional=["target_bid_item_id", "determined_unit_rate_cents", "days_granted"],
        enums={"determination_type": svc.DETERMINATION_TYPES},
    )
    condition = services.get_condition(condition_id)
    return object_response(views.determination_view(
        svc.issue_determination(condition, payload)))


def deny_condition(condition_id):
    condition = services.get_condition(condition_id)
    return object_response(views.condition_view(svc.deny_condition(condition)))


# ---------------------------------------------------------------------------
# EngineerDetermination
# ---------------------------------------------------------------------------

def list_determinations():
    records = _filtered(
        db.ordered("determination"),
        condition_id=request.args.get("condition_id"),
        target_bid_item_id=request.args.get("target_bid_item_id"),
        determination_status=request.args.get("determination_status"),
    )
    return _paginate(records, views.determination_view)


def get_determination(determination_id):
    return object_response(views.determination_view(services.get_determination(determination_id)))


def finalize_determination(determination_id):
    determination = services.get_determination(determination_id)
    return object_response(views.determination_view(svc.finalize_determination(determination)))


ROUTES = [
    ("POST", "/construction/bonds", ("Surety", "Estimator"), True, create_bond),
    ("GET", "/construction/bonds", ALL_ROLES, True, list_bonds),
    ("GET", "/construction/bonds/<bond_id>", ALL_ROLES, True, get_bond),
    ("POST", "/construction/bonds/<bond_id>/issue", ("Surety",), True, issue_bond),
    ("POST", "/construction/bonds/<bond_id>/execute", ("PlatformAdmin",), True, execute_bond),
    ("POST", "/construction/bonds/<bond_id>/release-bond", ("ContractingOfficer",), True,
     release_bond),

    ("POST", "/construction/bid-items/<bid_item_id>/measurements",
     ("ProjectManager", "Estimator"), True, create_measurement),
    ("GET", "/construction/measurements", ALL_ROLES, True, list_measurements),
    ("GET", "/construction/measurements/<measurement_id>", ALL_ROLES, True, get_measurement),
    ("POST", "/construction/measurements/<measurement_id>/approve", ("ProjectManager",), True,
     approve_measurement),
    ("POST", "/construction/measurements/<measurement_id>/pay", ("ProjectManager",), True,
     pay_measurement),
    ("POST", "/construction/measurements/<measurement_id>/void", ("ProjectManager",), True,
     void_measurement),

    ("POST", "/construction/projects/<project_id>/reconciliations",
     ("ContractingOfficer", "Estimator"), True, open_reconciliation),
    ("GET", "/construction/reconciliations", ALL_ROLES, True, list_reconciliations),
    ("GET", "/construction/reconciliations/<reconciliation_id>", ALL_ROLES, True,
     get_reconciliation),
    ("POST", "/construction/projects/<project_id>/reconciliations/<id>/finalize",
     ("ContractingOfficer",), True, finalize_reconciliation),
    ("POST", "/construction/projects/<project_id>/reconciliations/<id>/release-retention",
     ("ContractingOfficer",), True, release_retention),

    ("POST", "/construction/differing-site-conditions", ("ProjectManager",), True,
     report_condition),
    ("GET", "/construction/differing-site-conditions", ALL_ROLES, True, list_conditions),
    ("GET", "/construction/differing-site-conditions/<condition_id>", ALL_ROLES, True,
     get_condition),
    ("POST", "/construction/differing-site-conditions/<condition_id>/document",
     ("ProjectManager",), True, document_condition),
    ("POST", "/construction/differing-site-conditions/<condition_id>/submit-claim",
     ("ProjectManager",), True, submit_claim),
    ("POST", "/construction/differing-site-conditions/<condition_id>/return-for-documentation",
     ("Engineer",), True, return_for_documentation),
    ("POST", "/construction/differing-site-conditions/<condition_id>/engineer-determination",
     ("Engineer",), True, engineer_determination),
    ("POST", "/construction/differing-site-conditions/<condition_id>/deny", ("Engineer",), True,
     deny_condition),

    ("GET", "/construction/engineer-determinations", ALL_ROLES, True, list_determinations),
    ("GET", "/construction/engineer-determinations/<determination_id>", ALL_ROLES, True,
     get_determination),
    ("POST", "/construction/engineer-determinations/<determination_id>/finalize",
     ("PlatformAdmin",), True, finalize_determination),
]
