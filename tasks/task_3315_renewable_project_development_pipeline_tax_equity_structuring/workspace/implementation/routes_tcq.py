"""Tax credit qualification routes."""
import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_enum, success_obj, success_arr, pagination_args,
    paginate, now_common, touch, iso_from_epoch,
)
from serializers import tcq_view
from logic import (
    get_project, get_tcq, assess_continuity, compute_itc, recompute_project_derived,
    orders_for_project, ORDER_CREDIT_STATES, CURE_WINDOW_DAYS, DAY,
)

READ_ROLES = ["TaxCounsel", "DeveloperAdmin", "InvestorManager", "Auditor", "PlatformAdmin"]
TCQ_TARGETS = {"SAFE_HARBOR_ESTABLISHED", "CONTINUITY_MAINTAINED", "CURED", "QUALIFIED"}


def register(app):

    @app.get("/api/projects/<pid>/tax-credit-qualifications")
    def list_tcq(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [t for t in db.tax_credit_qualifications.values() if t["project_id"] == pid],
            key=lambda t: (t["created_at"], t["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([tcq_view(t) for t in page], limit, offset, total)

    @app.get("/api/tax-credit-qualifications/<tid>")
    def get_tcq_route(tid):
        require_auth(READ_ROLES)
        t = get_tcq(tid)
        return success_obj(tcq_view(t))

    @app.post("/api/tax-credit-qualifications/<tid>/transitions")
    def tcq_transition(tid):
        require_auth(["TaxCounsel"])
        t = get_tcq(tid)
        project = get_project(t["project_id"])
        body = payload()
        to = req_enum(body, "to", TCQ_TARGETS)
        cur = t["status"]

        if to == "SAFE_HARBOR_ESTABLISHED":
            if cur != "NOT_ELIGIBLE":
                raise_err("ERR_INVALID_STATE", f"Cannot establish from {cur}")
            variant = body.get("continuity_variant")
            if variant not in ("FOUR_YEAR_SAFE_HARBOR", "FACTS_AND_CIRCUMSTANCES"):
                raise_err("ERR_VALIDATION", "continuity_variant is required")
            if not any(o["status"] in ORDER_CREDIT_STATES
                       for o in orders_for_project(t["project_id"])):
                raise_err("ERR_SAFE_HARBOR_NOT_QUALIFIED",
                          "No safe-harbor-qualified procurement order")
            t["status"] = "SAFE_HARBOR_ESTABLISHED"
            t["continuity_variant"] = variant
            now = db.clock_now()
            t["_established_epoch"] = now
            t["safe_harbor_established_date"] = iso_from_epoch(now)
            touch(t)
            project["tax_credit_anchored"] = True
            return success_obj(tcq_view(t))

        if to == "CONTINUITY_MAINTAINED":
            if cur not in ("SAFE_HARBOR_ESTABLISHED", "CURED"):
                raise_err("ERR_INVALID_STATE", f"Cannot assess continuity from {cur}")
            if assess_continuity(t, project):
                t["status"] = "CONTINUITY_MAINTAINED"
                touch(t)
                recompute_project_derived(project)
                return success_obj(tcq_view(t))
            # failure: auto-lapse
            t["status"] = "CONTINUITY_LAPSED"
            now = db.clock_now()
            t["_lapse_epoch"] = now
            t["lapse_date"] = iso_from_epoch(now)
            t["lapse_count"] += 1
            touch(t)
            recompute_project_derived(project)
            raise_err("ERR_CONTINUITY_LAPSED", "Continuity assessment failed")

        if to == "CURED":
            if cur != "CONTINUITY_LAPSED":
                raise_err("ERR_INVALID_STATE", f"Cannot cure from {cur}")
            if db.clock_now() > t["_lapse_epoch"] + CURE_WINDOW_DAYS * DAY:
                t["status"] = "DISQUALIFIED"
                touch(t)
                project["tax_credit_anchored"] = False
                raise_err("ERR_CURE_WINDOW_EXPIRED", "Cure window expired")
            has_work = any(
                m["project_id"] == t["project_id"]
                and m["milestone_type"] == "CONTINUOUS_WORK"
                and m["status"] == "CERTIFIED"
                and m["_work_epoch"] is not None
                and m["_work_epoch"] >= t["_lapse_epoch"]
                for m in db.construction_milestones.values()
            )
            if not has_work:
                raise_err("ERR_VALIDATION",
                          "No CERTIFIED CONTINUOUS_WORK milestone on or after lapse_date")
            t["status"] = "CURED"
            touch(t)
            recompute_project_derived(project)
            return success_obj(tcq_view(t))

        if to == "QUALIFIED":
            if cur != "CONTINUITY_MAINTAINED":
                raise_err("ERR_INVALID_STATE", f"Cannot qualify from {cur}")
            if project["status"] not in ("COMMERCIAL_OPERATION", "OPERATIONAL"):
                raise_err("ERR_INVALID_STATE",
                          "Project must be in COMMERCIAL_OPERATION or OPERATIONAL")
            t["status"] = "QUALIFIED"
            compute_itc(project, t)
            touch(t)
            recompute_project_derived(project)
            return success_obj(tcq_view(t))

        raise_err("ERR_INVALID_STATE", f"Unsupported transition to {to}")
