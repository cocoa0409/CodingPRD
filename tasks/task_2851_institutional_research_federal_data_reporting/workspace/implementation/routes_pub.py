"""DashboardPublication and RestatementRequest routes."""
from flask import Blueprint

from auth import actor, check_sod, require_roles
from db import READ_ROLES, public, stamp_new, store, touch
from errors import fail
from response import created, filter_eq, ok, paginate
from svc_common import (get_component, get_cycle, get_publication,
                        get_restatement, restatements_of)
from svc_cycle import require_frozen
from svc_pub import (apply_restatement, create_restatement, publication_sort_key,
                     supersede_submitted, void_submitted, window_overlaps)
from util import num1, parse_instant
from validation import (get_body, opt_instant, opt_string, req_instant, req_int,
                        req_number, req_string)

bp = Blueprint("publications", __name__)


def serialize_publication(row):
    return public(row)


def serialize_restatement(row):
    return public(row)


@bp.post("/publications")
def create_publication():
    require_roles("IRAnalyst")
    body = get_body()
    component_id = req_string(body, "component_id", 1, None)
    metric_key = req_string(body, "metric_key", 3, 64)
    published_value = req_number(body, "published_value")
    effective_from = req_instant(body, "effective_from")
    effective_to = opt_instant(body, "effective_to")
    component = get_component(component_id)
    cycle = get_cycle(component["cycle_id"])
    require_frozen(cycle)
    if effective_to is not None and \
            parse_instant(effective_to) <= parse_instant(effective_from):
        fail("ERR_INVALID_EFFECTIVE_WINDOW",
             "effective_to must fall strictly after effective_from")
    if window_overlaps(component_id, metric_key, effective_from, effective_to):
        fail("ERR_PUBLICATION_WINDOW_OVERLAP",
             "the effective window overlaps a live publication of the same metric")
    row = {
        "component_id": component_id,
        "metric_key": metric_key,
        "published_value": published_value,
        "original_value": published_value,
        "net_applied_delta": num1(0),
        "restatement_count": 0,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "publication_status": "PUBLISHED",
        "published_by_user_id": actor(),
        "withdrawal_reason": None,
    }
    stamp_new(row)
    store.publications[row["id"]] = row
    return created(serialize_publication(row))


@bp.get("/publications/<publication_id>")
def read_publication(publication_id):
    require_roles(*READ_ROLES)
    return ok(serialize_publication(get_publication(publication_id)))


@bp.get("/publications")
def list_publications():
    require_roles(*READ_ROLES)
    rows = sorted(store.publications.values(), key=publication_sort_key)
    rows = filter_eq(rows, {"component_id": "component_id", "metric_key": "metric_key",
                            "publication_status": "publication_status"})
    return paginate(rows, serialize_publication)


@bp.post("/publications/<publication_id>/withdraw")
def withdraw(publication_id):
    require_roles("IRDirector")
    body = get_body()
    reason = req_string(body, "withdrawal_reason", 10, 500)
    publication = get_publication(publication_id)
    if publication["publication_status"] not in ("PUBLISHED", "RESTATEMENT_PENDING",
                                                 "RESTATED"):
        fail("ERR_INVALID_PUBLICATION_STATE",
             "a withdrawn publication cannot be withdrawn again")
    publication["publication_status"] = "WITHDRAWN"
    publication["withdrawal_reason"] = reason
    touch(publication)
    void_submitted(publication)
    return ok(serialize_publication(publication))


# ---------------------------------------------------------------- RestatementRequest


@bp.post("/publications/<publication_id>/restatements")
def file_restatement(publication_id):
    require_roles("IRAnalyst")
    body = get_body()
    proposed_value = req_number(body, "proposed_value")
    justification = req_string(body, "justification", 20, 1000)
    expected_version = req_int(body, "expected_publication_version")
    publication = get_publication(publication_id)
    if expected_version != publication["version"]:
        fail("ERR_STALE_PUBLICATION_VERSION",
             "the publication has changed since it was read")
    if publication["publication_status"] == "WITHDRAWN":
        fail("ERR_INVALID_PUBLICATION_STATE",
             "a withdrawn publication never accepts a restatement")
    row = create_restatement(publication, proposed_value, justification, actor(),
                             "ANALYST")
    supersede_submitted(publication, exclude_id=row["id"])
    publication["publication_status"] = "RESTATEMENT_PENDING"
    touch(publication)
    return created(serialize_restatement(row))


@bp.get("/restatements/<restatement_id>")
def read_restatement(restatement_id):
    require_roles(*READ_ROLES)
    return ok(serialize_restatement(get_restatement(restatement_id)))


@bp.get("/restatements")
def list_restatements():
    require_roles(*READ_ROLES)
    rows = sorted(store.restatements.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"publication_id": "publication_id", "status": "status",
                            "origin": "origin"})
    return paginate(rows, serialize_restatement)


@bp.post("/restatements/<restatement_id>/approve")
def approve_restatement(restatement_id):
    require_roles("IRDirector")
    body = get_body()
    reference = opt_string(body, "public_notice_reference", 3, 120)
    request_row = get_restatement(restatement_id)
    publication = get_publication(request_row["publication_id"])
    if request_row["status"] != "SUBMITTED":
        fail("ERR_INVALID_RESTATEMENT_STATE",
             "only a SUBMITTED restatement request can be approved")
    if publication["publication_status"] != "RESTATEMENT_PENDING":
        fail("ERR_INVALID_PUBLICATION_STATE",
             "the publication is not awaiting a restatement")
    check_sod(request_row.get("requested_by_user_id"))
    if request_row["public_notice_required"] and reference is None:
        fail("ERR_PUBLIC_NOTICE_REQUIRED",
             "a material restatement requires a public notice reference")
    request_row["status"] = "APPLIED"
    request_row["approved_by_user_id"] = actor()
    request_row["public_notice_reference"] = reference
    touch(request_row)
    apply_restatement(publication, request_row)
    return ok(serialize_restatement(request_row))


@bp.post("/restatements/<restatement_id>/reject")
def reject_restatement(restatement_id):
    require_roles("IRDirector")
    body = get_body()
    reason = opt_string(body, "rejection_reason", None, 500)
    request_row = get_restatement(restatement_id)
    publication = get_publication(request_row["publication_id"])
    if request_row["status"] != "SUBMITTED":
        fail("ERR_INVALID_RESTATEMENT_STATE",
             "only a SUBMITTED restatement request can be rejected")
    check_sod(request_row.get("requested_by_user_id"))
    if reason is None or len(reason) < 10:
        fail("ERR_REJECTION_REASON_REQUIRED",
             "a rejection requires a reason of 10 to 500 characters")
    request_row["status"] = "REJECTED"
    request_row["approved_by_user_id"] = actor()
    request_row["rejection_reason"] = reason
    touch(request_row)
    still_live = [r for r in restatements_of(publication["id"])
                  if r["status"] == "SUBMITTED"]
    if not still_live and publication["publication_status"] == "RESTATEMENT_PENDING":
        publication["publication_status"] = \
            "PUBLISHED" if publication["restatement_count"] == 0 else "RESTATED"
        touch(publication)
    return ok(serialize_restatement(request_row))
