"""Construction milestone routes."""
import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_enum, req_int, req_iso, get_user_id,
    success_obj, success_arr, pagination_args, paginate, now_common, touch,
    iso_from_epoch,
)
from serializers import milestone_view
from logic import get_project, get_milestone, cod_cascade

READ_ROLES = ["ConstructionManager", "TaxCounsel", "DeveloperAdmin", "Auditor", "PlatformAdmin"]
MILESTONE_TYPES = {
    "FOUNDATION", "ERECTION", "ENERGIZATION", "SUBSTANTIAL_COMPLETION",
    "COMMERCIAL_OPERATION", "CONTINUOUS_WORK",
}


def register(app):

    @app.post("/api/projects/<pid>/construction-milestones")
    def create_milestone(pid):
        require_auth(["ConstructionManager"])
        get_project(pid)
        body = payload()
        mtype = req_enum(body, "milestone_type", MILESTONE_TYPES)
        seq = req_int(body, "sequence_no")
        planned = req_iso(body, "planned_date")
        mid = db.new_id()
        m = {
            "id": mid,
            "project_id": pid,
            "milestone_type": mtype,
            "sequence_no": seq,
            "planned_date": iso_from_epoch(planned),
            "evidence_uri": None,
            "work_date": None,
            "_work_epoch": None,
            "submitted_by_user_id": None,
            "certified_by_user_id": None,
            "status": "PLANNED",
        }
        now_common(m)
        db.construction_milestones[mid] = m
        return success_obj(milestone_view(m), 201)

    @app.get("/api/projects/<pid>/construction-milestones")
    def list_milestones(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [m for m in db.construction_milestones.values() if m["project_id"] == pid],
            key=lambda m: (m["created_at"], m["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([milestone_view(m) for m in page], limit, offset, total)

    @app.get("/api/construction-milestones/<mid>")
    def get_milestone_route(mid):
        require_auth(READ_ROLES)
        m = get_milestone(mid)
        return success_obj(milestone_view(m))

    @app.post("/api/construction-milestones/<mid>/submit-evidence")
    def submit_evidence(mid):
        require_auth(["ConstructionManager"])
        m = get_milestone(mid)
        body = payload()
        if m["status"] not in ("PLANNED", "REJECTED"):
            raise_err("ERR_INVALID_STATE",
                      f"Cannot submit evidence from {m['status']}")
        ev = body.get("evidence_uri")
        wd = body.get("work_date")
        if not ev or not isinstance(ev, str) or wd is None:
            raise_err("ERR_MILESTONE_EVIDENCE_REQUIRED",
                      "evidence_uri and work_date are required")
        work_epoch = req_iso(body, "work_date")
        m["evidence_uri"] = ev
        m["work_date"] = iso_from_epoch(work_epoch)
        m["_work_epoch"] = work_epoch
        m["submitted_by_user_id"] = get_user_id()
        m["status"] = "EVIDENCE_SUBMITTED"
        touch(m)
        return success_obj(milestone_view(m))

    @app.post("/api/construction-milestones/<mid>/certify")
    def certify(mid):
        require_auth(["TaxCounsel"])
        m = get_milestone(mid)
        body = payload()
        decision = req_enum(body, "decision", {"CERTIFIED", "REJECTED"})
        if m["status"] != "EVIDENCE_SUBMITTED":
            raise_err("ERR_INVALID_STATE",
                      f"Cannot certify from {m['status']}")
        caller = get_user_id()
        if caller is not None and caller == m["submitted_by_user_id"]:
            raise_err("ERR_SEGREGATION_OF_DUTIES",
                      "Certifier must differ from submitter")
        if decision == "REJECTED":
            m["certified_by_user_id"] = caller
            m["status"] = "REJECTED"
            touch(m)
            return success_obj(milestone_view(m))
        # CERTIFIED
        for other in db.construction_milestones.values():
            if (other["project_id"] == m["project_id"] and other["id"] != mid
                    and other["sequence_no"] < m["sequence_no"]
                    and other["status"] != "CERTIFIED"):
                raise_err("ERR_MILESTONE_OUT_OF_ORDER",
                          "A lower sequence_no milestone is not CERTIFIED")
        if m["milestone_type"] == "COMMERCIAL_OPERATION":
            project = get_project(m["project_id"])
            if project["status"] != "COMMISSIONING":
                raise_err("ERR_COD_MILESTONE_PREREQUISITE",
                          "COMMERCIAL_OPERATION milestone requires project in COMMISSIONING")
        m["certified_by_user_id"] = caller
        m["status"] = "CERTIFIED"
        touch(m)
        if m["milestone_type"] == "COMMERCIAL_OPERATION":
            project = get_project(m["project_id"])
            cod_cascade(project)
        return success_obj(milestone_view(m))
