"""Project routes + logical clock."""
import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_string, req_enum, req_number, opt_number, opt_bool,
    req_iso, success_obj, success_arr, pagination_args, paginate, now_common, touch,
    iso_from_epoch, money2, dec2,
)
from serializers import project_view
from logic import (
    get_project, tcq_for_project, recompute_project_derived, abandon_project,
    LD_PER_POINT, LD_CAP, TCQ_ANCHORED_STATES,
)
from decimal import Decimal

ALL_ROLES = [
    "DeveloperAdmin", "OriginationManager", "ProcurementLead", "ConstructionManager",
    "TaxCounsel", "InvestorManager", "LenderAgent", "Auditor", "PlatformAdmin",
]

PROJECT_STATUSES = {
    "PROSPECT", "SITE_SECURED", "DEVELOPMENT", "READY_FOR_CONSTRUCTION",
    "UNDER_CONSTRUCTION", "COMMISSIONING", "COMMERCIAL_OPERATION", "OPERATIONAL",
    "ABANDONED",
}


def register(app):

    @app.post("/api/_clock/set_current_utc")
    def set_clock():
        require_auth(["PlatformAdmin"])
        body = payload()
        ts = req_iso(body, "to_iso8601")
        db.clock_set(ts)
        return success_obj({"current_utc": iso_from_epoch(db.clock_now())})

    @app.post("/api/projects")
    def create_project():
        require_auth(["DeveloperAdmin"])
        body = payload()
        name = req_string(body, "name")
        technology = req_enum(body, "technology", {"WIND", "SOLAR", "HYBRID"})
        cap = req_number(body, "target_capacity_mw")
        resource_class = req_enum(body, "resource_class", {"A", "B", "C"})
        ec = opt_bool(body, "energy_community_eligible", False)
        dc = opt_bool(body, "domestic_content_certified", False)
        avail = opt_number(body, "availability_guarantee_pct", Decimal("97.0"))
        pid = db.new_id()
        p = {
            "id": pid,
            "name": name,
            "technology": technology,
            "target_capacity_mw": float(cap),
            "resource_class": resource_class,
            "energy_community_eligible": ec,
            "domestic_content_certified": dc,
            "availability_guarantee_pct": float(avail),
            "status": "PROSPECT",
            "cod_date": None,
            "measured_availability_pct": None,
            "availability_ld_usd": 0.0,
            "tax_credit_anchored": False,
            "total_itc_credits_usd": 0.0,
        }
        now_common(p)
        db.projects[pid] = p
        # Auto-create the TaxCreditQualification in NOT_ELIGIBLE
        tid = db.new_id()
        t = {
            "id": tid,
            "project_id": pid,
            "status": "NOT_ELIGIBLE",
            "continuity_variant": None,
            "safe_harbor_established_date": None,
            "_established_epoch": None,
            "lapse_date": None,
            "_lapse_epoch": None,
            "lapse_count": 0,
            "credit_rate_pct": 0.0,
            "qualified_credit_usd": 0.0,
        }
        now_common(t)
        db.tax_credit_qualifications[tid] = t
        return success_obj(project_view(p), 201)

    @app.get("/api/projects")
    def list_projects():
        require_auth(ALL_ROLES)
        limit, offset = pagination_args()
        status_filter = None
        from flask import request
        if "status" in request.args:
            status_filter = request.args.get("status")
            if status_filter not in PROJECT_STATUSES:
                raise_err("ERR_VALIDATION", "Invalid status filter")
        items = sorted(db.projects.values(), key=lambda p: (p["created_at"], p["id"]))
        if status_filter:
            items = [p for p in items if p["status"] == status_filter]
        page, total = paginate(items, limit, offset)
        return success_arr([project_view(p) for p in page], limit, offset, total)

    @app.get("/api/projects/<pid>")
    def get_project_route(pid):
        require_auth(ALL_ROLES)
        p = get_project(pid)
        return success_obj(project_view(p))

    @app.post("/api/projects/<pid>/transitions")
    def project_transition(pid):
        require_auth(["DeveloperAdmin"])
        p = get_project(pid)
        body = payload()
        to = req_enum(body, "to", PROJECT_STATUSES)
        cur = p["status"]

        if to == "ABANDONED":
            if cur == "OPERATIONAL":
                raise_err("ERR_INVALID_STATE", "Cannot abandon an OPERATIONAL project")
            if cur == "ABANDONED":
                raise_err("ERR_INVALID_STATE", "Project already ABANDONED")
            abandon_project(p)
            return success_obj(project_view(p))

        if cur in ("OPERATIONAL", "ABANDONED"):
            raise_err("ERR_INVALID_STATE", "Transition not permitted from terminal state")

        if to == "SITE_SECURED":
            if cur == "PROSPECT":
                has = any(
                    s["project_id"] == pid and s["status"] in ("EXERCISED", "RECORDED")
                    for s in db.site_control_instruments.values()
                )
                if not has:
                    raise_err("ERR_INVALID_STATE", "No EXERCISED or RECORDED site control instrument")
            elif cur == "DEVELOPMENT":
                pass
            else:
                raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to SITE_SECURED")
            p["status"] = "SITE_SECURED"
            touch(p)
            return success_obj(project_view(p))

        if to == "PROSPECT":
            if cur != "SITE_SECURED":
                raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to PROSPECT")
            p["status"] = "PROSPECT"
            touch(p)
            return success_obj(project_view(p))

        if to == "DEVELOPMENT":
            if cur != "SITE_SECURED":
                raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to DEVELOPMENT")
            has = any(
                r["project_id"] == pid and r["status"] != "WITHDRAWN"
                for r in db.interconnection_requests.values()
            )
            if not has:
                raise_err("ERR_INVALID_STATE", "No non-WITHDRAWN interconnection request")
            p["status"] = "DEVELOPMENT"
            touch(p)
            return success_obj(project_view(p))

        if to == "READY_FOR_CONSTRUCTION":
            if cur != "DEVELOPMENT":
                raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to READY_FOR_CONSTRUCTION")
            if not any(o["project_id"] == pid and o["status"] == "EFFECTIVE"
                       for o in db.offtake_agreements.values()):
                raise_err("ERR_OFFTAKE_REQUIRED", "No EFFECTIVE offtake agreement")
            if not any(r["project_id"] == pid and r["status"] in ("AGREEMENT_EXECUTED", "IN_SERVICE")
                       for r in db.interconnection_requests.values()):
                raise_err("ERR_INTERCONNECTION_NOT_EXECUTED", "No executed interconnection request")
            p["status"] = "READY_FOR_CONSTRUCTION"
            touch(p)
            return success_obj(project_view(p))

        if to == "UNDER_CONSTRUCTION":
            if cur != "READY_FOR_CONSTRUCTION":
                raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to UNDER_CONSTRUCTION")
            tcq = tcq_for_project(pid)
            tcq_status = tcq["status"] if tcq else "NOT_ELIGIBLE"
            if tcq_status == "DISQUALIFIED":
                raise_err("ERR_CREDIT_DISQUALIFIED", "Tax credit qualification is DISQUALIFIED")
            if tcq_status not in TCQ_ANCHORED_STATES:
                raise_err("ERR_SAFE_HARBOR_NOT_QUALIFIED", "Tax credit qualification not anchored")
            p["status"] = "UNDER_CONSTRUCTION"
            touch(p)
            recompute_project_derived(p)
            return success_obj(project_view(p))

        if to == "COMMISSIONING":
            if cur != "UNDER_CONSTRUCTION":
                raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to COMMISSIONING")
            required = {"FOUNDATION", "ERECTION", "ENERGIZATION", "SUBSTANTIAL_COMPLETION"}
            certified = {m["milestone_type"] for m in db.construction_milestones.values()
                         if m["project_id"] == pid and m["status"] == "CERTIFIED"}
            if not required.issubset(certified):
                raise_err("ERR_COD_MILESTONE_PREREQUISITE",
                          "FOUNDATION/ERECTION/ENERGIZATION/SUBSTANTIAL_COMPLETION must all be CERTIFIED")
            p["status"] = "COMMISSIONING"
            touch(p)
            return success_obj(project_view(p))

        if to == "COMMERCIAL_OPERATION":
            raise_err("ERR_INVALID_STATE", "COMMERCIAL_OPERATION is cascade-only")

        if to == "OPERATIONAL":
            if cur != "COMMERCIAL_OPERATION":
                raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to OPERATIONAL")
            measured = opt_number(body, "measured_availability_pct", None)
            if measured is None:
                raise_err("ERR_AVAILABILITY_MEASUREMENT_REQUIRED",
                          "measured_availability_pct is required")
            p["measured_availability_pct"] = float(measured)
            shortfall = dec2(p["availability_guarantee_pct"]) - measured
            if shortfall <= 0:
                p["availability_ld_usd"] = 0.0
            else:
                ld = money2(shortfall * LD_PER_POINT)
                p["availability_ld_usd"] = min(ld, float(LD_CAP))
            p["status"] = "OPERATIONAL"
            touch(p)
            return success_obj(project_view(p))

        raise_err("ERR_INVALID_STATE", f"Unsupported transition to {to}")
