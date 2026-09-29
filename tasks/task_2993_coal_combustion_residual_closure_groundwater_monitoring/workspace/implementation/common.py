"""Lookup helpers and the shared refusal gates (PRD 2.10 positions 6-57)."""
from flask import request

import calc
import derive
import store
from errors import ApiError
from shape import bad

# ------------------------------------------------------- discipline admission
D_STABILITY = ("GEOTECHNICAL", "CIVIL")
D_ENGINEERING = ("GEOTECHNICAL", "CIVIL")
D_COST = ("CIVIL",)
D_CLOSURE_WORK = ("CIVIL", "GEOTECHNICAL")
D_HYDRO = ("HYDROGEOLOGY",)
D_STATS = ("STATISTICS",)


# ------------------------------------------------------------------- lookups
def get_unit(unit_id):
    record = store.units.get(unit_id)
    if record is None:
        raise ApiError("ERR_UNIT_NOT_FOUND", "The disposal unit does not exist.")
    return record


def get_monitoring(collection, entity_id):
    record = collection.get(entity_id)
    if record is None:
        raise ApiError("ERR_MONITORING_ENTITY_NOT_FOUND",
                       "The monitoring entity does not exist.")
    return record


def get_program(program_id):
    return get_monitoring(store.programs, program_id)


def get_well(well_id):
    return get_monitoring(store.wells, well_id)


def get_event(event_id):
    return get_monitoring(store.sampling_events, event_id)


def get_result(result_id):
    return get_monitoring(store.analytical_results, result_id)


def get_evaluation(evaluation_id):
    return get_monitoring(store.statistical_evaluations, evaluation_id)


def get_closure(collection, entity_id):
    record = collection.get(entity_id)
    if record is None:
        raise ApiError("ERR_CLOSURE_ENTITY_NOT_FOUND",
                       "The closure entity does not exist.")
    return record


def get_plan(plan_id):
    return get_closure(store.closure_plans, plan_id)


def get_extension(request_id):
    return get_closure(store.extension_requests, request_id)


def get_reuse(collection, entity_id):
    record = collection.get(entity_id)
    if record is None:
        raise ApiError("ERR_REUSE_ENTITY_NOT_FOUND",
                       "The reuse entity does not exist.")
    return record


def get_agreement(agreement_id):
    return get_reuse(store.reuse_agreements, agreement_id)


def get_shipment(shipment_id):
    return get_reuse(store.reuse_shipments, shipment_id)


def get_posting(posting_id):
    record = store.public_postings.get(posting_id)
    if record is None:
        raise ApiError("ERR_POSTING_NOT_FOUND", "The public posting does not exist.")
    return record


def get_body_professional(professional_id):
    record = store.professionals.get(professional_id)
    if record is None:
        raise ApiError("ERR_PROFESSIONAL_NOT_FOUND",
                       "The referenced professional does not exist.")
    return record


# --------------------------------------------------------------------- gates
def no_future_date(*values):
    """Position 12: enumerated event dates may not lead the logical clock."""
    today = store.fmt_date(store.today())
    for value in values:
        if value is not None and value > today:
            raise ApiError("ERR_FUTURE_DATE_NOT_ALLOWED",
                           "The supplied date lies in the future.")


def unique_code(collection, field, value, scope_field=None, scope_value=None):
    """Position 13."""
    for record in collection.values():
        if record.get(field) != value:
            continue
        if scope_field is not None and record.get(scope_field) != scope_value:
            continue
        raise ApiError("ERR_DUPLICATE_CODE",
                       "The business code is already in use.")


def unit_state(unit, allowed):
    """Position 18."""
    if unit["closure_state"] not in allowed:
        raise ApiError("ERR_INVALID_UNIT_STATE",
                       "The unit's closure state does not permit this operation.")


def unit_not_care_complete(unit):
    if unit["closure_state"] == "CARE_COMPLETE":
        raise ApiError("ERR_INVALID_UNIT_STATE",
                       "The unit's closure state does not permit this operation.")


def program_phase(program, allowed):
    """Position 19."""
    if program["phase"] not in allowed:
        raise ApiError("ERR_INVALID_PROGRAM_PHASE",
                       "The monitoring program's phase does not permit this operation.")


def not_frozen(unit):
    """Position 29."""
    if calc.compliance_posture(unit) == "FROZEN":
        raise ApiError("ERR_UNIT_FROZEN",
                       "The unit is FROZEN and accepts only remedial writes.")


def not_restricted(unit):
    """Position 34."""
    if calc.compliance_posture(unit) == "RESTRICTED":
        raise ApiError("ERR_UNIT_RESTRICTED",
                       "The unit's compliance posture is RESTRICTED.")


def segregation(actor_id, other_id):
    """Position 28."""
    if other_id is not None and actor_id == other_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The acting professional may not sign both paired steps.")


def unit_of_program(program):
    return get_unit(program["unit_id"])


def unit_of_agreement(agreement):
    return get_unit(agreement["unit_id"])


def approved_plan(unit_id):
    for plan in store.ordered(store.closure_plans.values()):
        if plan["unit_id"] == unit_id and plan["status"] == "APPROVED":
            return plan
    return None


def governing_inspection(unit_id):
    """Latest cap inspection of the unit by (inspected_on, created_at)."""
    rows = [r for r in store.cap_inspections.values() if r["unit_id"] == unit_id]
    if not rows:
        return None
    return max(rows, key=lambda r: (r["inspected_on"], r["created_at"], r["_seq"]))


# ------------------------------------------------------------------ filtering
def _wanted(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def apply_filters(rows, string_fields=(), bool_fields=()):
    out = list(rows)
    for name in string_fields:
        value = _wanted(name)
        if value is None:
            continue
        out = [r for r in out if r.get(name) == value]
    for name in bool_fields:
        value = _wanted(name)
        if value is None:
            continue
        if value not in ("true", "false"):
            raise bad("Filter '%s' must be true or false." % name)
        flag = value == "true"
        out = [r for r in out if bool(r.get(name)) is flag]
    return out


def settle(unit):
    return derive.settle_unit(unit)
