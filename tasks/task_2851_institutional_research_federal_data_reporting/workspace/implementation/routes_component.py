"""SurveyComponent, ComponentMetric and EditCheck routes."""
from flask import Blueprint

from auth import actor, check_sod, require_roles
from db import (ALL_METRIC_KEYS, READ_ROLES, SURVEY_DOMAINS, public, stamp_new,
                store, touch)
from errors import fail
from response import created, filter_eq, ok, paginate
from svc_common import (checks_of, components_of, get_component, get_cycle,
                        get_edit_check, get_frozen_file, get_metric, metrics_of)
from svc_component import (core_expense_per_fte_cents, derive_edit_status,
                           generate_checks, mapping_coverage_pct,
                           metric_domain_ok, serialize_component, variance_pct)
from svc_cycle import (bubble_archive, cascade_publications, require_not_archived,
                       require_not_frozen, require_posture, void_checks)
from util import parse_instant
from validation import (get_body, opt_number, opt_string, req_enum, req_number,
                        req_string)

bp = Blueprint("components", __name__)

PREP_POSTURES = ("CENSUS_LOCKED", "REOPENED")


def serialize_metric(row):
    return public(row)


def serialize_check(row):
    return public(row)


@bp.post("/survey-components")
def create_component():
    require_roles("IRAnalyst")
    body = get_body()
    cycle_id = req_string(body, "cycle_id", 1, None)
    frozen_file_id = req_string(body, "frozen_file_id", 1, None)
    component_code = req_enum(body, "component_code", SURVEY_DOMAINS)
    cycle = get_cycle(cycle_id)
    frozen_file = get_frozen_file(frozen_file_id)
    if frozen_file["cycle_id"] != cycle_id or frozen_file["domain"] != component_code:
        fail("ERR_FROZEN_FILE_NOT_FOUND",
             "the census extract does not belong to this cycle and component code")
    require_not_frozen(cycle)
    require_posture(cycle, PREP_POSTURES)
    for peer in components_of(cycle_id):
        if peer["component_code"] == component_code:
            fail("ERR_DUPLICATE_COMPONENT",
                 "a component for this survey already exists in the cycle")
    row = {
        "cycle_id": cycle_id,
        "frozen_file_id": frozen_file_id,
        "component_code": component_code,
        "prep_status": "DRAFT",
        "edit_status": "NOT_RUN",
        "prepared_by_user_id": None,
        "certified_by_user_id": None,
        "certification_statement": None,
        "mapping_coverage_pct": None,
        "core_expense_per_fte_cents": None,
        "fatal_open_count": 0,
        "submitted_at": None,
    }
    stamp_new(row)
    store.components[row["id"]] = row
    return created(serialize_component(row))


@bp.get("/survey-components/<component_id>")
def read_component(component_id):
    require_roles(*READ_ROLES)
    return ok(serialize_component(get_component(component_id)))


@bp.get("/survey-components")
def list_components():
    require_roles(*READ_ROLES)
    rows = sorted(store.components.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"cycle_id": "cycle_id", "frozen_file_id": "frozen_file_id",
                            "prep_status": "prep_status", "edit_status": "edit_status"})
    return paginate(rows, serialize_component)


@bp.post("/survey-components/<component_id>/prepare")
def prepare(component_id):
    require_roles("IRAnalyst")
    component = get_component(component_id)
    cycle = get_cycle(component["cycle_id"])
    require_not_frozen(cycle)
    require_posture(cycle, PREP_POSTURES)
    if component["prep_status"] != "DRAFT":
        fail("ERR_INVALID_COMPONENT_STATE", "only a DRAFT component can be prepared")
    frozen_file = store.frozen_files.get(component["frozen_file_id"])
    if frozen_file is None or frozen_file["status"] not in ("ACTIVE", "LOCKED"):
        fail("ERR_FROZEN_FILE_SUPERSEDED", "the source census extract has been superseded")
    metrics = metrics_of(component_id)
    if not metrics:
        fail("ERR_NO_METRICS", "the component has no reported metrics")

    component["prep_status"] = "PREPARED"
    component["prepared_by_user_id"] = actor()
    coverage = mapping_coverage_pct(component, cycle)
    component["mapping_coverage_pct"] = coverage
    component["core_expense_per_fte_cents"] = core_expense_per_fte_cents(component)
    for metric in metrics:
        metric["variance_pct"] = variance_pct(metric)
    raised = generate_checks(component, coverage)
    derive_edit_status(component, force_cleared_if_empty=not raised)
    touch(component)
    return ok(serialize_component(component))


@bp.post("/survey-components/<component_id>/certify")
def certify(component_id):
    require_roles("IRDirector")
    body = get_body()
    statement = req_string(body, "certification_statement", 20, 1000)
    component = get_component(component_id)
    cycle = get_cycle(component["cycle_id"])
    require_not_frozen(cycle)
    require_posture(cycle, PREP_POSTURES)
    if component["prep_status"] != "PREPARED":
        fail("ERR_INVALID_COMPONENT_STATE", "only a PREPARED component can be certified")
    if component["edit_status"] != "CLEARED":
        fail("ERR_EDIT_CHECKS_UNRESOLVED", "every edit check must be resolved")
    check_sod(component.get("prepared_by_user_id"))
    if store.now() > parse_instant(cycle["collection_deadline"]):
        fail("ERR_COLLECTION_DEADLINE_PASSED", "the collection deadline has passed")
    component["prep_status"] = "CERTIFIED"
    component["certified_by_user_id"] = actor()
    component["certification_statement"] = statement
    touch(component)
    return ok(serialize_component(component))


@bp.post("/survey-components/<component_id>/submit")
def submit(component_id):
    require_roles("IRDirector")
    component = get_component(component_id)
    cycle = get_cycle(component["cycle_id"])
    require_posture(cycle, ("FROZEN",))
    if component["prep_status"] != "CERTIFIED":
        fail("ERR_INVALID_COMPONENT_STATE", "only a CERTIFIED component can be submitted")
    if store.now() > parse_instant(cycle["collection_deadline"]):
        fail("ERR_COLLECTION_DEADLINE_PASSED", "the collection deadline has passed")
    component["prep_status"] = "SUBMITTED"
    component["submitted_at"] = store.now_iso()
    touch(component)
    bubble_archive(cycle)
    return ok(serialize_component(component))


@bp.post("/survey-components/<component_id>/revert-to-draft")
def revert_to_draft(component_id):
    require_roles("IRDirector")
    body = get_body()
    req_string(body, "decertify_reason", 10, 500)
    component = get_component(component_id)
    cycle = get_cycle(component["cycle_id"])
    require_not_archived(cycle)
    if component["prep_status"] not in ("PREPARED", "CERTIFIED"):
        fail("ERR_INVALID_COMPONENT_STATE",
             "only a PREPARED or CERTIFIED component can be reverted")
    was_certified = component["prep_status"] == "CERTIFIED"
    component["prep_status"] = "DRAFT"
    component["prepared_by_user_id"] = None
    if was_certified:
        component["certified_by_user_id"] = None
        component["certification_statement"] = None
    void_checks(component)
    component["edit_status"] = "NOT_RUN"
    component["fatal_open_count"] = 0
    touch(component)
    if was_certified:
        cascade_publications(component)
    return ok(serialize_component(component))


# ---------------------------------------------------------------- ComponentMetric


@bp.post("/survey-components/<component_id>/metrics")
def create_metric(component_id):
    require_roles("IRAnalyst")
    body = get_body()
    metric_key = req_enum(body, "metric_key", ALL_METRIC_KEYS)
    reported_value = req_number(body, "reported_value", 0)
    prior_year_value = opt_number(body, "prior_year_value", 0)
    source_field_path = req_string(body, "source_field_path", 3, 120)
    component = get_component(component_id)
    cycle = get_cycle(component["cycle_id"])
    require_not_frozen(cycle)
    require_posture(cycle, PREP_POSTURES)
    if component["prep_status"] != "DRAFT":
        fail("ERR_INVALID_COMPONENT_STATE",
             "reported metrics may only be attached while the component is DRAFT")
    if not metric_domain_ok(component["component_code"], metric_key):
        fail("ERR_METRIC_DOMAIN_MISMATCH",
             "the metric key is not part of this component's survey domain")
    for peer in metrics_of(component_id):
        if peer["metric_key"] == metric_key:
            fail("ERR_DUPLICATE_METRIC_KEY",
                 "this metric key is already reported on the component")
    row = {
        "component_id": component_id,
        "metric_key": metric_key,
        "reported_value": reported_value,
        "prior_year_value": prior_year_value,
        "source_field_path": source_field_path,
        "restated": False,
        "restatement_note": None,
        "variance_pct": None,
    }
    stamp_new(row)
    store.metrics[row["id"]] = row
    return created(serialize_metric(row))


@bp.get("/component-metrics/<metric_id>")
def read_metric(metric_id):
    require_roles(*READ_ROLES)
    return ok(serialize_metric(get_metric(metric_id)))


@bp.get("/component-metrics")
def list_metrics():
    require_roles(*READ_ROLES)
    rows = sorted(store.metrics.values(),
                  key=lambda r: (r["metric_key"], r.get("created_at") or "",
                                 r.get("_seq") or 0))
    rows = filter_eq(rows, {"component_id": "component_id", "metric_key": "metric_key"})
    return paginate(rows, serialize_metric)


@bp.patch("/component-metrics/<metric_id>")
def correct_metric(metric_id):
    require_roles("IRAnalyst")
    body = get_body()
    reported_value = req_number(body, "reported_value", 0)
    note = opt_string(body, "restatement_note", 1, 500)
    metric = get_metric(metric_id)
    component = get_component(metric["component_id"])
    cycle = get_cycle(component["cycle_id"])
    require_not_frozen(cycle)
    if component["prep_status"] != "DRAFT":
        fail("ERR_INVALID_COMPONENT_STATE",
             "reported metrics may only be corrected while the component is DRAFT")
    metric["reported_value"] = reported_value
    metric["restated"] = True
    metric["restatement_note"] = note
    metric["variance_pct"] = variance_pct(metric)
    touch(metric)
    return ok(serialize_metric(metric))


# ---------------------------------------------------------------- EditCheck


@bp.get("/edit-checks/<edit_check_id>")
def read_check(edit_check_id):
    require_roles(*READ_ROLES)
    return ok(serialize_check(get_edit_check(edit_check_id)))


@bp.get("/edit-checks")
def list_checks():
    require_roles(*READ_ROLES)
    rows = sorted(store.edit_checks.values(),
                  key=lambda r: (r["sequence_no"], r.get("created_at") or "",
                                 r.get("_seq") or 0))
    rows = filter_eq(rows, {"component_id": "component_id", "status": "status",
                            "severity": "severity"})
    return paginate(rows, serialize_check)


@bp.post("/edit-checks/<edit_check_id>/explain")
def explain(edit_check_id):
    require_roles("IRAnalyst")
    body = get_body()
    explanation_text = req_string(body, "explanation_text", None, 2000)
    note = req_string(body, "prior_year_comparison_note", 10, 2000)
    check = get_edit_check(edit_check_id)
    component = get_component(check["component_id"])
    if component["prep_status"] != "PREPARED":
        fail("ERR_INVALID_COMPONENT_STATE",
             "the parent component must be PREPARED to resolve its edit checks")
    if check["status"] not in ("OPEN", "REJECTED"):
        fail("ERR_INVALID_EDIT_CHECK_STATE",
             "only an OPEN or REJECTED check can be explained")
    if len(explanation_text.strip()) < 20:
        fail("ERR_EXPLANATION_TOO_SHORT",
             "the explanation must be at least 20 characters after trimming")
    check["status"] = "EXPLAINED"
    check["explanation_text"] = explanation_text
    check["prior_year_comparison_note"] = note
    check["explained_by_user_id"] = actor()
    check["explanation_round"] = (check.get("explanation_round") or 0) + 1
    touch(check)
    derive_edit_status(component)
    touch(component)
    return ok(serialize_check(check))


@bp.post("/edit-checks/<edit_check_id>/adjudicate")
def adjudicate(edit_check_id):
    require_roles("IRDirector")
    body = get_body()
    decision = req_enum(body, "decision", ("ACCEPT", "WAIVE", "REJECT"))
    note = opt_string(body, "adjudication_note", None, 500)
    if decision == "REJECT" and (note is None or len(note) < 10):
        fail("ERR_INVALID_REQUEST",
             "a REJECT decision requires an adjudication_note of 10 to 500 characters")
    check = get_edit_check(edit_check_id)
    component = get_component(check["component_id"])
    if check["status"] != "EXPLAINED":
        fail("ERR_INVALID_EDIT_CHECK_STATE", "only an EXPLAINED check can be adjudicated")
    check_sod(check.get("explained_by_user_id"))
    if decision == "WAIVE" and check["severity"] != "WARNING":
        fail("ERR_WAIVER_NOT_PERMITTED", "a FATAL edit check cannot be waived")
    if decision == "ACCEPT":
        check["status"] = "ACCEPTED"
        check["adjudication_note"] = note
    elif decision == "WAIVE":
        check["status"] = "WAIVED"
        check["adjudication_note"] = note
    else:
        check["status"] = "REJECTED"
        check["adjudication_note"] = note
    check["adjudicated_by_user_id"] = actor()
    touch(check)
    if decision == "REJECT":
        derive_edit_status(component)
        component["edit_status"] = "OPEN_EDITS"
    else:
        derive_edit_status(component)
    touch(component)
    return ok(serialize_check(check))
