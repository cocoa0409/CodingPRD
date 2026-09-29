"""ExternalSubmission routes: drafting, reconciliation, override and transmission."""
from flask import Blueprint

from auth import actor, require_roles
from db import (READ_ROLES, TARGET_TYPES, TOLERANCE_BY_TARGET, public, stamp_new,
                store, touch)
from errors import fail
from response import created, filter_eq, ok, paginate
from svc_common import get_component, get_cycle, get_submission, metrics_of
from svc_component import metric_domain_ok
from svc_cycle import require_frozen, require_not_archived
from util import D, num2, parse_instant
from validation import get_body, req_enum, req_number, req_string

bp = Blueprint("external", __name__)


def serialize_submission(row):
    return public(row)


def allowance_for(raw_delta):
    """calculations.submission_reconciliation step 2 — tiered on the RAW delta only."""
    if D(raw_delta) < D("1.00"):
        return num2("0.00")
    if D(raw_delta) < D("5.00"):
        return num2("0.50")
    return num2("1.00")


@bp.post("/external-submissions")
def create_submission():
    require_roles("IRAnalyst")
    body = get_body()
    cycle_id = req_string(body, "cycle_id", 1, None)
    component_id = req_string(body, "component_id", 1, None)
    target_type = req_enum(body, "target_type", TARGET_TYPES)
    target_name = req_string(body, "target_name", 3, 120)
    metric_key = req_string(body, "metric_key", 3, 64)
    reported_value = req_number(body, "reported_value", 0)
    cycle = get_cycle(cycle_id)
    component = get_component(component_id)
    if component["cycle_id"] != cycle_id:
        fail("ERR_COMPONENT_NOT_FOUND", "the source component does not belong to this cycle")
    require_not_archived(cycle)
    if not metric_domain_ok(component["component_code"], metric_key):
        fail("ERR_METRIC_DOMAIN_MISMATCH",
             "the metric key is not part of the source component's survey domain")
    for peer in store.submissions.values():
        if (peer["cycle_id"] == cycle_id and peer["target_name"] == target_name
                and peer["metric_key"] == metric_key
                and peer["status"] != "TRANSMITTED"):
            fail("ERR_DUPLICATE_SUBMISSION",
                 "a live submission to this recipient already exists for the metric")
    row = {
        "cycle_id": cycle_id,
        "component_id": component_id,
        "target_type": target_type,
        "target_name": target_name,
        "metric_key": metric_key,
        "reported_value": reported_value,
        "status": "DRAFT",
        "federal_value": None,
        "raw_delta_pct": None,
        "allowance_pct": None,
        "effective_delta_pct": None,
        "tolerance_pct": None,
        "override_reason": None,
        "overridden_by_user_id": None,
        "transmission_reference": None,
        "transmitted_at": None,
    }
    stamp_new(row)
    store.submissions[row["id"]] = row
    return created(serialize_submission(row))


@bp.get("/external-submissions/<submission_id>")
def read_submission(submission_id):
    require_roles(*READ_ROLES)
    return ok(serialize_submission(get_submission(submission_id)))


@bp.get("/external-submissions")
def list_submissions():
    require_roles(*READ_ROLES)
    rows = sorted(store.submissions.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"cycle_id": "cycle_id", "component_id": "component_id",
                            "target_type": "target_type", "status": "status"})
    return paginate(rows, serialize_submission)


@bp.post("/external-submissions/<submission_id>/reconcile")
def reconcile(submission_id):
    require_roles("IRAnalyst")
    submission = get_submission(submission_id)
    component = get_component(submission["component_id"])
    if submission["status"] != "DRAFT":
        fail("ERR_INVALID_SUBMISSION_STATE", "only a DRAFT submission can be reconciled")
    if component["prep_status"] not in ("CERTIFIED", "SUBMITTED"):
        fail("ERR_SOURCE_NOT_CERTIFIED",
             "the source component is not certified, so it carries no authoritative value")
    federal = None
    for metric in metrics_of(component["id"]):
        if metric["metric_key"] == submission["metric_key"]:
            federal = metric
            break
    if federal is None:
        fail("ERR_FEDERAL_VALUE_UNAVAILABLE",
             "the source component reports no metric under this key")
    federal_value = federal["reported_value"]
    if D(federal_value) == 0:
        fail("ERR_ZERO_BASE_RECONCILIATION",
             "the federal counterpart value is zero, so no percentage gap is defined")
    raw = num2(abs(D(submission["reported_value"]) - D(federal_value))
               / abs(D(federal_value)) * D(100))
    allowance = allowance_for(raw)
    effective = num2(D(raw) - D(allowance))
    if D(effective) < 0:
        effective = num2("0.00")
    tolerance = num2(TOLERANCE_BY_TARGET[submission["target_type"]])
    submission["federal_value"] = federal_value
    submission["raw_delta_pct"] = raw
    submission["allowance_pct"] = allowance
    submission["effective_delta_pct"] = effective
    submission["tolerance_pct"] = tolerance
    submission["status"] = "RECONCILED" if D(effective) <= D(tolerance) else "VARIANCE_HOLD"
    touch(submission)
    return ok(serialize_submission(submission))


@bp.post("/external-submissions/<submission_id>/variance-override")
def variance_override(submission_id):
    require_roles("IRDirector")
    body = get_body()
    reason = req_string(body, "override_reason", 20, 500)
    submission = get_submission(submission_id)
    if submission["status"] != "VARIANCE_HOLD":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "only a submission on VARIANCE_HOLD can be overridden")
    submission["status"] = "RECONCILED"
    submission["override_reason"] = reason
    submission["overridden_by_user_id"] = actor()
    touch(submission)
    return ok(serialize_submission(submission))


@bp.post("/external-submissions/<submission_id>/transmit")
def transmit(submission_id):
    require_roles("IRDirector")
    body = get_body()
    reference = req_string(body, "transmission_reference", 3, 64)
    submission = get_submission(submission_id)
    cycle = get_cycle(submission["cycle_id"])
    require_frozen(cycle)
    if submission["status"] != "RECONCILED":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "only a RECONCILED submission can be transmitted")
    if store.now() > parse_instant(cycle["collection_deadline"]):
        fail("ERR_COLLECTION_DEADLINE_PASSED", "the collection deadline has passed")
    submission["status"] = "TRANSMITTED"
    submission["transmission_reference"] = reference
    submission["transmitted_at"] = store.now_iso()
    touch(submission)
    return ok(serialize_submission(submission))
