"""HTTP views, grouped by resource area.

Views own request-shape checks (the highest-precedence rung), authentication,
role authorization, existence checks and the calls into the workflow services.
"""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ERR_ALREADY_COMMITTED, ERR_CAPACITY_EXCEEDED,
                    ERR_COUNTERFEIT_OVERCOUNT, ERR_DESIGN_NOT_APPROVED,
                    ERR_DESIGN_NOT_FOUND, ERR_EVENT_WINDOW_CLOSED,
                    ERR_FULFILLMENT_ORDER_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_LICENSOR_MISMATCH,
                    ERR_LICENSOR_NOT_FOUND, ERR_LICENSOR_PROJECT_NOT_FOUND,
                    ERR_LISTING_UNVERIFIED, ERR_NOT_FOUND,
                    ERR_PRINT_QUANTITY_EXCEEDED, ERR_PRINT_TYPECAST_MISMATCH,
                    ERR_PRODUCTION_ALREADY_COMMITTED,
                    ERR_PRODUCTION_ORDER_NOT_FOUND, ERR_RUSH_COMMITMENT_BREACH,
                    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_VERSION,
                    ERR_UNBALANCED_ALLOCATION, fail)
from response import (authenticate, ok_array, ok_object, paginate, pagination,
                      require_roles)
from services import fulfillment, ledger, pricing, production

api = Blueprint("api", __name__)

EVENT_WINDOW_HOURS = 48
GARMENT_SKUS = ("JERSEY", "TRACTOR", "DUFFEL", "CAP", "MINI", "PENNANT")
PRINT_TYPES = ("BASE", "EMBROIDER", "HEAT_PRESS", "PENNANT")
CAPACITY_TYPES = ("BASE", "EMBROIDER", "HEAT_PRESS")
TRIGGER_TYPES = ("CHAMPIONSHIP_WIN", "MILESTONE", "ATHLETE_TRANSACTION", "STANDARD")
EVENT_OUTCOMES = ("WIN_FAVORED_TEAM", "WIN_UNDERDOG_TEAM", "NO_OUTCOME")
CHANNELS = ("VENUE_RETAIL", "EVENT_POPUP", "ECOM")
CARRIERS = ("RUSH_AIR", "GROUND")
DESTROY_MODES = ("DESTROY", "DONATE", "SHORTFALL")
RETIRE_REASONS = ("OUTCOME_COMMITTED", "LOSING_OUTCOME", "ASSORTMENT_CHANGED",
                  "DEMAND_COLLAPSE")
DISTRESS_REASONS = ("LOSING_OUTCOME", "DEMAND_COLLAPSE", "DAMAGED_ON_SITE")
DECISIONS = ("APPROVE", "REJECT")
# A run with no outcome instant scheduled is treated as unhurried (PRD 3.2).
DEFAULT_HOURS_TO_OUTCOME = 24.0


# --- Body helpers ---------------------------------------------------------

def body():
    return request.get_json(silent=True) or {}


def require_field(payload, name):
    if name not in payload or payload[name] is None:
        fail(ERR_INVALID_REQUEST, "field %r is required" % name)
    return payload[name]


def require_enum(payload, name, allowed, optional=False, default=None):
    if name not in payload or payload[name] is None:
        if optional:
            return default
        fail(ERR_INVALID_REQUEST, "field %r is required" % name)
    value = payload[name]
    if value not in allowed:
        fail(ERR_INVALID_REQUEST,
             "field %r must be one of %s" % (name, ", ".join(allowed)))
    return value


def require_int(payload, name, positive=False, optional=False, default=None):
    if name not in payload or payload[name] is None:
        if optional:
            return default
        fail(ERR_INVALID_REQUEST, "field %r is required" % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail(ERR_INVALID_REQUEST, "field %r must be an integer" % name)
    if positive and value <= 0:
        fail(ERR_INVALID_REQUEST, "field %r must be strictly positive" % name)
    return value


def require_number(payload, name, optional=False, default=None, low=None, high=None):
    if name not in payload or payload[name] is None:
        if optional:
            return default
        fail(ERR_INVALID_REQUEST, "field %r is required" % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(ERR_INVALID_REQUEST, "field %r must be a number" % name)
    if low is not None and value < low:
        fail(ERR_INVALID_REQUEST, "field %r is out of range" % name)
    if high is not None and value > high:
        fail(ERR_INVALID_REQUEST, "field %r is out of range" % name)
    return value


def optional_string(payload, name, default=None):
    value = payload.get(name)
    if value is None:
        return default
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "field %r must be a string" % name)
    return value


def require_instant(payload, name, optional=False, default=None):
    if name not in payload or payload[name] is None:
        if optional:
            return default
        fail(ERR_INVALID_REQUEST, "field %r is required" % name)
    try:
        return db.parse_iso(payload[name])
    except Exception:
        fail(ERR_INVALID_REQUEST, "field %r must be an ISO 8601 instant" % name)


def path_param(name):
    return request.view_args.get(name)


# --- Existence helpers ----------------------------------------------------

def get_licensor(licensor_id, error_id=ERR_LICENSOR_NOT_FOUND):
    licensor = db.store.licensors.get(licensor_id)
    if licensor is None:
        fail(error_id, "licensor %s does not exist" % licensor_id)
    return licensor


def get_design(design_id, error_id=ERR_DESIGN_NOT_FOUND):
    design = db.store.designs.get(design_id)
    if design is None:
        fail(error_id, "design %s does not exist" % design_id)
    return design


def get_run(run_id, error_id=ERR_PRODUCTION_ORDER_NOT_FOUND):
    run = db.store.production_orders.get(run_id)
    if run is None:
        fail(error_id, "production order %s does not exist" % run_id)
    return run


def get_order(order_id):
    order = db.store.fulfillment_orders.get(order_id)
    if order is None:
        fail(ERR_FULFILLMENT_ORDER_NOT_FOUND, "fulfillment order %s does not exist" % order_id)
    return order


def require_order_version(payload, run):
    """A pick of units from a run's shared pool is one of the two designated
    concurrency-controlled writes of record (PRD 2.8)."""
    if "expected_production_order_version" not in payload:
        fail(ERR_INVALID_REQUEST,
             "field 'expected_production_order_version' is a required input")
    return require_version(payload, "expected_production_order_version",
                           run.get("version", 0))


def get_layer(layer_id):
    layer = db.store.print_layers.get(layer_id)
    if layer is None:
        fail(ERR_NOT_FOUND, "print layer %s does not exist" % layer_id)
    return layer


def get_capacity(capacity_id):
    window = db.store.print_capacities.get(capacity_id)
    if window is None:
        fail(ERR_NOT_FOUND, "print capacity %s does not exist" % capacity_id)
    return window


def get_report(report_id):
    report = db.store.counterfeit_reports.get(report_id)
    if report is None:
        fail(ERR_NOT_FOUND, "counterfeit report %s does not exist" % report_id)
    return report


# --- Authorization helpers ------------------------------------------------

def check_segregation(caller, design):
    """The operator that recorded the licensor decision on a design may not
    commit a run using it, nor settle that licensor's minimum guarantee."""
    decider = db.store.design_deciders.get(design["id"])
    if decider is not None and decider == caller.user_id:
        fail(ERR_SEGREGATION_OF_DUTIES,
             "the operator recording the licensor decision may not commit or settle")


def check_licensor_ownership(caller, licensor_id):
    if caller.role == "LicensingOps" and caller.user_id != licensor_id:
        fail(ERR_LICENSOR_MISMATCH,
             "a LicensingOps caller may only act on its own licensor")


def licensor_projects(licensor):
    """The licensor's recorded rights projects.  A rights holder registered
    through POST /licensors records projects covering every trigger type and
    every garment SKU it may produce under."""
    key = licensor.get("id")
    projects = db.store.rights_projects.get(key)
    if projects is None:
        projects = set(TRIGGER_TYPES) | set(GARMENT_SKUS)
        db.store.rights_projects[key] = projects
    return projects


def check_licensor_project(licensor, trigger_type):
    """The licensor must hold a recorded rights project covering the run's
    trigger_type; a run whose licensor holds none is refused."""
    if trigger_type not in licensor_projects(licensor):
        fail(ERR_LICENSOR_PROJECT_NOT_FOUND,
             "the licensor holds no recorded rights project for trigger_type %s" % trigger_type)


def run_design_licensor(run):
    return (db.store.designs.get(run.get("design_id")),
            db.store.licensors.get(run.get("licensor_id")))


def require_version(payload, field, current):
    """Optimistic concurrency (PRD 2.8): the supplied expected version is a
    non-optional input and must equal the parent entity's current version."""
    if field not in payload or payload[field] is None:
        fail(ERR_INVALID_REQUEST, "field %r is required" % field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail(ERR_INVALID_REQUEST, "field %r must be an integer" % field)
    if value != int(current):
        fail(ERR_STALE_VERSION,
             "%s does not match the entity's current version" % field)
    return value


