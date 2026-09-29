"""Transparency reports, the retention sweep and the logical clock
(PRD 3.9, 3.6, 2.5)."""
from flask import Blueprint

import auth
import calc
import engine
import envelope
import fetch
import serialize
import store
import validators as v
from errors import ApiError
from routes_agency import require_onboarded
from store import db, now

bp = Blueprint("report", __name__)

VARIANTS = ("PROVISIONAL", "CERTIFIED")
CERTIFIED_DENOMINATOR_STATUSES = ("SHARED", "DECLINED", "EXPIRED")


def _in_scope(agency_id, period_start, period_end):
    """Requests of this agency submitted inside the half-open window."""
    requests = []
    for row in db.video_requests.values():
        if row["agency_id"] != agency_id:
            continue
        submitted = row["submitted_at"]
        if submitted is None:
            continue
        if period_start <= submitted < period_end:
            requests.append(row)
    request_ids = set(r["id"] for r in requests)
    sols = [s for s in db.solicitations.values()
            if s["video_request_id"] in request_ids]
    clips = [c for c in db.clips.values()
             if c["video_request_id"] in request_ids]
    return requests, sols, clips


def _tally(agency_id, period_start, period_end):
    requests, sols, clips = _in_scope(agency_id, period_start, period_end)
    buckets = {"SOLICITED": 0, "SHARED": 0, "DECLINED": 0, "EXPIRED": 0,
               "WITHDRAWN": 0}
    suppressed = 0
    opted_out = 0
    for sol in sols:
        buckets[sol["status"]] += 1
        if sol["notification_suppressed"]:
            suppressed += 1
        resident = db.residents.get(sol["resident_id"])
        if resident is not None and resident["data_sharing_opt_out"]:
            opted_out += 1
    certified_denominator = 0
    certified_numerator = 0
    for sol in sols:
        if sol["notification_suppressed"]:
            continue
        if sol["status"] in CERTIFIED_DENOMINATOR_STATUSES:
            certified_denominator += 1
            if sol["status"] == "SHARED":
                certified_numerator += 1
    return {
        "requests_submitted_count": len(requests),
        "solicitations_dispatched_count": len(sols),
        "suppressed_dispatch_count": suppressed,
        "shared_count": buckets["SHARED"],
        "declined_count": buckets["DECLINED"],
        "expired_count": buckets["EXPIRED"],
        "withdrawn_count": buckets["WITHDRAWN"],
        "pending_count": buckets["SOLICITED"],
        "opt_out_excluded_count": opted_out,
        "purged_clip_count": sum(1 for c in clips if c["status"] == "PURGED"),
        "provisional_share_rate_bps": calc.share_rate_bps(buckets["SHARED"],
                                                          len(sols)),
        "certified_share_rate_bps": calc.share_rate_bps(certified_numerator,
                                                        certified_denominator),
    }


@bp.post("/neighborhood-safety/transparency-reports")
def compile_report():
    actor = auth.authenticate(("PlatformAdmin",))
    body = v.body_json()
    v.require_present(body, "agency_id")
    agency = fetch.must("Agency", body.get("agency_id"))
    period_start = v.dt_field(body, "period_start_utc")
    period_end = v.dt_field(body, "period_end_utc")
    expected_version = v.int_field(body, "expected_agency_version")
    require_onboarded(agency)
    if expected_version != agency["version"]:
        raise ApiError("ERR_STALE_AGENCY_VERSION",
                       "expected_agency_version does not match the agency")
    if period_start >= period_end:
        raise ApiError("ERR_INVALID_WINDOW",
                       "period_start_utc must fall strictly before period_end_utc")

    tally = _tally(agency["id"], period_start, period_end)
    row = engine.new_row({
        "agency_id": agency["id"],
        "period_start_utc": period_start,
        "period_end_utc": period_end,
        "variant": "PROVISIONAL",
        "compiled_by_user_id": actor.user_id,
        "published_share_rate_bps": tally["provisional_share_rate_bps"],
        "certification_note": None,
        "certified_at": None,
        "certified_by_user_id": None,
    })
    row.update(tally)
    db.reports[row["id"]] = row
    agency["latest_report_id"] = row["id"]
    engine.touch(agency)
    return envelope.created(serialize.dump("TransparencyReport", row))


@bp.post("/neighborhood-safety/transparency-reports/<report_id>/certify")
def certify_report(report_id):
    actor = auth.authenticate(("PlatformAdmin",))
    report = fetch.must("TransparencyReport", report_id)
    body = v.body_json()
    note = v.str_field(body, "certification_note", min_len=1)
    if note.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST",
                       "certification_note must be non-empty")
    if report["compiled_by_user_id"] == actor.user_id:
        auth.sod("The certifying admin may not be the compiling admin")
    if report["variant"] != "PROVISIONAL":
        raise ApiError("ERR_REPORT_ALREADY_CERTIFIED",
                       "Report %s is already certified" % report["id"])

    tally = _tally(report["agency_id"], report["period_start_utc"],
                   report["period_end_utc"])
    report.update(tally)
    report["variant"] = "CERTIFIED"
    report["published_share_rate_bps"] = report["certified_share_rate_bps"]
    report["certification_note"] = note
    report["certified_at"] = now()
    report["certified_by_user_id"] = actor.user_id
    engine.touch(report)
    return envelope.ok(serialize.dump("TransparencyReport", report))


@bp.get("/neighborhood-safety/transparency-reports/<report_id>")
def read_report(report_id):
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Moderator",
                       "Resident"))
    report = fetch.must("TransparencyReport", report_id)
    return envelope.ok(serialize.dump("TransparencyReport", report))


@bp.get("/neighborhood-safety/transparency-reports")
def list_reports():
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Moderator",
                       "Resident"))
    limit, offset = v.pagination()
    agency_id = v.query_str("agency_id")
    variant = v.query_enum("variant", VARIANTS)
    rows = list(db.reports.values())
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("TransparencyReport", page),
                               limit, offset, total)


# --------------------------------------------------------------------------
# the retention sweep (PRD 3.6)
# --------------------------------------------------------------------------

@bp.post("/neighborhood-safety/retention-sweeps")
def run_sweep():
    auth.authenticate(("PlatformAdmin",))
    v.body_json()
    instant = now()
    open_before = set(r["id"] for r in db.video_requests.values()
                      if r["lifecycle_state"] == "SOLICITING")

    lapsed = [s for s in db.solicitations.values()
              if s["status"] == "SOLICITED"
              and s["respond_deadline_utc"] <= instant]
    lapsed.sort(key=lambda s: (s["respond_deadline_utc"], s["created_at"]))
    for sol in lapsed:
        engine.expire_solicitation(sol)
    expired_count = len(lapsed)

    purged_count = 0
    due = [c for c in db.clips.values()
           if c["status"] == "RETAINED"
           and c["retention_expires_at"] is not None
           and c["retention_expires_at"] <= instant]
    for clip in store.by_created(due):
        engine.purge_clip(clip, "RETENTION_EXPIRED")
        purged_count += 1
    pending = [c for c in db.clips.values() if c["status"] == "PURGE_PENDING"]
    for clip in store.by_created(pending):
        engine.purge_clip(clip, "ACCOUNT_DEACTIVATED")
        purged_count += 1

    held_count = sum(1 for c in db.clips.values()
                     if c["status"] == "LEGAL_HOLD"
                     and c["retention_expires_at"] is not None
                     and c["retention_expires_at"] <= instant)

    for row in store.by_created([r for r in db.video_requests.values()
                                 if r["lifecycle_state"] == "SOLICITING"]):
        engine.sync_request(row)
    closed_count = sum(1 for request_id in open_before
                       if db.video_requests[request_id]["lifecycle_state"]
                       != "SOLICITING")

    return envelope.ok({
        "run_at_utc": store.fmt_ts(instant),
        "solicitations_expired_count": expired_count,
        "clips_purged_count": purged_count,
        "clips_held_count": held_count,
        "requests_auto_closed_count": closed_count,
    })


# --------------------------------------------------------------------------
# the logical clock (PRD 2.5)
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate(("PlatformAdmin",))
    body = v.body_json()
    instant = v.dt_field(body, "to_iso8601")
    previous = db.clock
    db.clock = instant
    reset_count = 0
    if store.utc_date(instant) > store.utc_date(previous):
        for resident in store.by_created(list(db.residents.values())):
            if resident["notifications_sent_today"] == 0:
                continue
            resident["notifications_sent_today"] = 0
            engine.rederive_fatigue(resident)
            reset_count += 1
    return envelope.ok({
        "current_utc": store.fmt_ts(instant),
        "residents_daily_counter_reset_count": reset_count,
    })
