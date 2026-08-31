"""Member registry, stratification history and the utilization feed."""
from flask import Blueprint, request

import analytics
import core
import domain
import http_util as h
import serializers as S
from core import clock, db
from errors import ApiError

bp = Blueprint("member", __name__)

ALL_READ = ["ProgramAdmin", "CareManager", "ClinicalReviewer", "UtilizationAnalyst"]


# --------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------
@bp.post("/members")
def create_member():
    h.authenticate(["ProgramAdmin"])
    data = h.body()
    external_member_id = h.req_str(data, "external_member_id")
    full_name = h.req_str(data, "full_name")
    birth_date = h.req_date_str(data, "birth_date")
    state_code = h.req_state_code(data, "state_code")
    chronic = h.opt_int(data, "chronic_condition_count", default=0, minimum=0)
    consent = h.opt_enum(data, "social_data_consent_status", core.CONSENT_STATUSES,
                         default="GRANTED")
    for existing in db.members.values():
        if existing["external_member_id"] == external_member_id:
            raise ApiError("ERR_INVALID_REQUEST",
                           "external_member_id must be unique across all members.")
    rec = domain.base_record()
    rec.update({
        "external_member_id": external_member_id,
        "full_name": full_name,
        "birth_date": birth_date,
        "state_code": state_code,
        "chronic_condition_count": chronic,
        "social_data_consent_status": consent,
        "latest_concurrent_score": None,
        "latest_concurrent_tier": None,
        "latest_prospective_score": None,
        "latest_prospective_tier": None,
    })
    db.members[rec["id"]] = rec
    return h.ok(S.member_out(rec), 201)


@bp.get("/members/<member_id>")
def read_member(member_id):
    h.authenticate(ALL_READ)
    rec = domain.get_member(member_id)
    return h.ok(S.member_out(rec))


@bp.get("/members")
def list_members():
    h.authenticate(["ProgramAdmin", "UtilizationAnalyst"])
    limit, offset = h.pagination()
    rows = list(db.members.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.member_out(r) for r in page], limit, offset, total)


@bp.post("/members/<member_id>/consent")
def set_consent(member_id):
    h.authenticate(["ProgramAdmin", "CareManager"])
    data = h.body()
    consent = h.req_enum(data, "social_data_consent_status", core.CONSENT_STATUSES)
    rec = domain.get_member(member_id)
    rec["social_data_consent_status"] = consent
    domain.touch_record(rec)
    return h.ok(S.member_out(rec))


# --------------------------------------------------------------------------
# Stratifications
# --------------------------------------------------------------------------
@bp.post("/members/<member_id>/stratifications")
def create_stratification(member_id):
    h.authenticate(["ProgramAdmin", "UtilizationAnalyst"])
    data = h.body()
    variant = h.req_enum(data, "variant", core.STRAT_VARIANTS)
    member = domain.get_member(member_id)
    record = analytics.compute_stratification(member, variant)
    db.stratifications[record["id"]] = record
    analytics.refresh_member_cache(member, variant)
    return h.ok(S.stratification_out(record), 201)


@bp.get("/members/<member_id>/stratifications")
def list_stratifications(member_id):
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    member = domain.get_member(member_id)
    variant = request.args.get("variant")
    rows = analytics.member_stratifications(member["id"], variant)
    rows = analytics.strat_history_sorted(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.stratification_out(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Transition (utilization) events
# --------------------------------------------------------------------------
@bp.post("/transition-events")
def create_transition_event():
    h.authenticate(["ProgramAdmin", "UtilizationAnalyst"])
    data = h.body()
    member_id = h.req_str(data, "member_id")
    event_type = h.req_enum(data, "event_type", core.EVENT_TYPES)
    occurred_at = h.req_instant(data, "occurred_at")
    facility_name = h.req_str(data, "facility_name")
    episode_cost = h.opt_int(data, "episode_cost_cents", default=0)
    adjudication = h.opt_enum(data, "adjudication_status",
                              core.ADJUDICATION_STATUSES, default="OPEN")
    if event_type == "DISCHARGE":
        disposition = h.req_enum(data, "discharge_disposition",
                                 core.DISCHARGE_DISPOSITIONS)
    else:
        h.opt_enum(data, "discharge_disposition", core.DISCHARGE_DISPOSITIONS)
        disposition = None
    index_id = h.opt_str(data, "index_admission_event_id")

    member = domain.get_member(member_id)
    if index_id is not None:
        domain.get_transition_event(index_id)
    if event_type != "DISCHARGE":
        index_id = None
    if event_type == "DISCHARGE":
        episode_cost = 0

    rec = domain.base_record(versioned=False)
    rec.update({
        "member_id": member["id"],
        "index_admission_event_id": index_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "facility_name": facility_name,
        "episode_cost_cents": episode_cost,
        "adjudication_status": adjudication,
        "discharge_disposition": disposition,
        "toc_triggered_enrollment_count": 0,
    })
    db.transition_events[rec["id"]] = rec

    if event_type == "DISCHARGE":
        affected = [e for e in domain.member_enrollments(member["id"])
                    if e["enrollment_status"] == "ACTIVE"]
        for enrollment in affected:
            domain.toc_escalate(enrollment, rec)
            rec["toc_triggered_enrollment_count"] += 1

    return h.ok(S.transition_event_out(rec), 201)


@bp.get("/transition-events/<event_id>")
def read_transition_event(event_id):
    h.authenticate(ALL_READ)
    rec = domain.get_transition_event(event_id)
    return h.ok(S.transition_event_out(rec))


@bp.get("/transition-events")
def list_transition_events():
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    rows = list(db.transition_events.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    event_type = request.args.get("event_type")
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    index_id = request.args.get("index_admission_event_id")
    if index_id is not None:
        rows = [r for r in rows if r["index_admission_event_id"] == index_id]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.transition_event_out(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    h.authenticate(["ProgramAdmin"])
    data = h.body()
    instant = h.req_instant(data, "to_iso8601")
    clock.set(instant)
    return h.ok({"current_utc": core.fmt_instant(clock.now())})
