"""Interconnection request and study routes."""
from datetime import timedelta

import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_string, req_enum, req_positive_number, req_iso,
    success_obj, success_arr, pagination_args, paginate, now_common, touch,
    iso_from_epoch,
)
from serializers import ir_view, study_view
from logic import (
    get_project, get_ir, get_study, allocate_upgrade_costs, withdraw_request,
    STUDY_BUFFER_DAYS, DAY,
)

READ_ROLES = ["OriginationManager", "DeveloperAdmin", "Auditor", "PlatformAdmin"]
STUDY_PHASES = {"FEASIBILITY", "SYSTEM_IMPACT", "FACILITIES"}


def _latest_accepted(request_id, phase):
    studies = [s for s in db.interconnection_studies.values()
               if s["request_id"] == request_id and s["phase"] == phase]
    if not studies:
        return None
    studies.sort(key=lambda s: (s["created_at"], s["id"]))
    return studies[-1]


def register(app):

    @app.post("/api/projects/<pid>/interconnection-requests")
    def create_ir(pid):
        require_auth(["OriginationManager"])
        get_project(pid)
        body = payload()
        cluster_id = req_string(body, "cluster_id")
        cap = req_positive_number(body, "requested_capacity_mw")
        active = [r for r in db.interconnection_requests.values()
                  if r["cluster_id"] == cluster_id and r["status"] != "WITHDRAWN"]
        pos = max((r["queue_position"] for r in active), default=0) + 1
        rid = db.new_id()
        r = {
            "id": rid,
            "project_id": pid,
            "cluster_id": cluster_id,
            "requested_capacity_mw": float(cap),
            "queue_position": pos,
            "status": "QUEUED",
            "upgrade_allocated": False,
            "upgrade_cost_share_usd": 0.0,
            "last_upgrade_total_usd": 0.0,
        }
        now_common(r)
        db.interconnection_requests[rid] = r
        return success_obj(ir_view(r), 201)

    @app.get("/api/projects/<pid>/interconnection-requests")
    def list_ir(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [r for r in db.interconnection_requests.values() if r["project_id"] == pid],
            key=lambda r: (r["created_at"], r["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([ir_view(r) for r in page], limit, offset, total)

    @app.get("/api/interconnection-requests/<rid>")
    def get_ir_route(rid):
        require_auth(READ_ROLES)
        r = get_ir(rid)
        return success_obj(ir_view(r))

    @app.post("/api/interconnection-requests/<rid>/transitions")
    def ir_transition(rid):
        require_auth(["OriginationManager"])
        r = get_ir(rid)
        body = payload()
        to = req_enum(body, "to", {
            "FEASIBILITY_STUDY", "SYSTEM_IMPACT_STUDY", "FACILITIES_STUDY",
            "AGREEMENT_EXECUTED", "IN_SERVICE", "WITHDRAWN",
        })
        cur = r["status"]

        if to == "WITHDRAWN":
            if cur in ("IN_SERVICE", "WITHDRAWN"):
                raise_err("ERR_INVALID_STATE", f"Cannot withdraw from {cur}")
            withdraw_request(r, touch)
            return success_obj(ir_view(r))

        valid = {
            ("QUEUED", "FEASIBILITY_STUDY"),
            ("FEASIBILITY_STUDY", "SYSTEM_IMPACT_STUDY"),
            ("SYSTEM_IMPACT_STUDY", "FACILITIES_STUDY"),
            ("FACILITIES_STUDY", "AGREEMENT_EXECUTED"),
            ("AGREEMENT_EXECUTED", "IN_SERVICE"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")

        if to == "SYSTEM_IMPACT_STUDY":
            latest = _latest_accepted(rid, "FEASIBILITY")
            if latest is None or latest["status"] != "ACCEPTED":
                raise_err("ERR_PHASE_STUDY_NOT_ACCEPTED", "Latest FEASIBILITY study is not ACCEPTED")
        elif to == "FACILITIES_STUDY":
            latest = _latest_accepted(rid, "SYSTEM_IMPACT")
            if latest is None or latest["status"] != "ACCEPTED":
                raise_err("ERR_PHASE_STUDY_NOT_ACCEPTED", "Latest SYSTEM_IMPACT study is not ACCEPTED")
            if not r["upgrade_allocated"]:
                raise_err("ERR_UPGRADE_ALLOCATION_REQUIRED", "Upgrade cost allocation has not run")
        elif to == "AGREEMENT_EXECUTED":
            latest = _latest_accepted(rid, "FACILITIES")
            if latest is None or latest["status"] != "ACCEPTED":
                raise_err("ERR_PHASE_STUDY_NOT_ACCEPTED", "Latest FACILITIES study is not ACCEPTED")

        r["status"] = to
        touch(r)
        return success_obj(ir_view(r))

    @app.post("/api/interconnection-requests/<rid>/allocate-upgrade-costs")
    def allocate(rid):
        require_auth(["PlatformAdmin"])
        r = get_ir(rid)
        body = payload()
        total = req_positive_number(body, "total_upgrade_cost_usd")
        allocate_upgrade_costs(r["cluster_id"], float(total))
        # Return the addressed request after re-fetch (it may or may not be in the pool)
        r2 = db.interconnection_requests[rid]
        return success_obj(ir_view(r2))

    @app.post("/api/interconnection-requests/<rid>/studies")
    def create_study(rid):
        require_auth(["OriginationManager"])
        r = get_ir(rid)
        body = payload()
        phase = req_enum(body, "phase", STUDY_PHASES)
        ws = req_iso(body, "window_start")
        we = req_iso(body, "window_end")
        if we < ws:
            raise_err("ERR_VALIDATION", "window_end must be >= window_start")
        buffer = STUDY_BUFFER_DAYS * DAY
        for s in db.interconnection_studies.values():
            other_req = db.interconnection_requests.get(s["request_id"])
            if other_req is None or other_req["cluster_id"] != r["cluster_id"]:
                continue
            if s["phase"] != phase:
                continue
            if s["_we_epoch"] >= ws - buffer and s["_ws_epoch"] <= we + buffer:
                raise_err("ERR_STUDY_WINDOW_CONFLICT",
                          "Study window conflicts with a same-phase study on the cluster")
        sid = db.new_id()
        s = {
            "id": sid,
            "request_id": rid,
            "phase": phase,
            "window_start": iso_from_epoch(ws),
            "window_end": iso_from_epoch(we),
            "_ws_epoch": ws,
            "_we_epoch": we,
            "status": "SCOPED",
            "rework_count": 0,
        }
        now_common(s)
        db.interconnection_studies[sid] = s
        return success_obj(study_view(s), 201)

    @app.get("/api/interconnection-requests/<rid>/studies")
    def list_studies(rid):
        require_auth(READ_ROLES)
        get_ir(rid)
        limit, offset = pagination_args()
        items = sorted(
            [s for s in db.interconnection_studies.values() if s["request_id"] == rid],
            key=lambda s: (s["created_at"], s["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([study_view(s) for s in page], limit, offset, total)

    @app.get("/api/interconnection-studies/<sid>")
    def get_study_route(sid):
        require_auth(READ_ROLES)
        s = get_study(sid)
        return success_obj(study_view(s))

    @app.post("/api/interconnection-studies/<sid>/transitions")
    def study_transition(sid):
        require_auth(["OriginationManager"])
        s = get_study(sid)
        body = payload()
        to = req_enum(body, "to", {"IN_PROGRESS", "DELIVERED", "ACCEPTED", "DEFICIENT"})
        cur = s["status"]
        valid = {
            ("SCOPED", "IN_PROGRESS"),
            ("IN_PROGRESS", "DELIVERED"),
            ("DELIVERED", "ACCEPTED"),
            ("DELIVERED", "DEFICIENT"),
            ("DEFICIENT", "IN_PROGRESS"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")
        if cur == "DEFICIENT" and to == "IN_PROGRESS":
            s["rework_count"] += 1
        s["status"] = to
        touch(s)
        return success_obj(study_view(s))
