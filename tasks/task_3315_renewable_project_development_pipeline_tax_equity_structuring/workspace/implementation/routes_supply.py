"""Supply agreement routes."""
import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_string, req_enum, req_positive_number, opt_number,
    opt_bool, success_obj, success_arr, pagination_args, paginate, now_common, touch,
)
from serializers import sa_view
from logic import get_project, get_sa, clawback_order

READ_ROLES = ["ProcurementLead", "DeveloperAdmin", "TaxCounsel", "Auditor", "PlatformAdmin"]


def register(app):

    @app.post("/api/projects/<pid>/supply-agreements")
    def create_sa(pid):
        require_auth(["ProcurementLead"])
        get_project(pid)
        body = payload()
        equipment_type = req_enum(body, "equipment_type", {"TURBINE", "MODULE"})
        supplier_name = req_string(body, "supplier_name")
        total = req_positive_number(body, "total_contract_usd")
        dcc = opt_bool(body, "domestic_content_certified", False)
        sid = db.new_id()
        s = {
            "id": sid,
            "project_id": pid,
            "equipment_type": equipment_type,
            "supplier_name": supplier_name,
            "total_contract_usd": float(total),
            "domestic_content_certified": dcc,
            "status": "DRAFT",
            "amendment_count": 0,
            "_amendment_value": None,
        }
        now_common(s)
        db.supply_agreements[sid] = s
        return success_obj(sa_view(s), 201)

    @app.get("/api/projects/<pid>/supply-agreements")
    def list_sa(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [s for s in db.supply_agreements.values() if s["project_id"] == pid],
            key=lambda s: (s["created_at"], s["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([sa_view(s) for s in page], limit, offset, total)

    @app.get("/api/supply-agreements/<sid>")
    def get_sa_route(sid):
        require_auth(READ_ROLES)
        s = get_sa(sid)
        return success_obj(sa_view(s))

    @app.post("/api/supply-agreements/<sid>/transitions")
    def sa_transition(sid):
        require_auth(["ProcurementLead"])
        s = get_sa(sid)
        body = payload()
        to = req_enum(body, "to", {
            "EXECUTED", "AMENDMENT_PENDING", "DELIVERING", "FULFILLED", "TERMINATED",
        })
        cur = s["status"]
        valid = {
            ("DRAFT", "EXECUTED"),
            ("EXECUTED", "AMENDMENT_PENDING"),
            ("AMENDMENT_PENDING", "EXECUTED"),
            ("EXECUTED", "DELIVERING"),
            ("DELIVERING", "FULFILLED"),
            ("DRAFT", "TERMINATED"),
            ("EXECUTED", "TERMINATED"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")

        if to == "AMENDMENT_PENDING":
            amend = opt_number(body, "amendment_total_contract_usd", None)
            if amend is None:
                raise_err("ERR_VALIDATION", "amendment_total_contract_usd is required")
            s["_amendment_value"] = float(amend)
            s["status"] = "AMENDMENT_PENDING"
            touch(s)
            return success_obj(sa_view(s))

        if cur == "AMENDMENT_PENDING" and to == "EXECUTED":
            s["total_contract_usd"] = s["_amendment_value"]
            s["_amendment_value"] = None
            s["amendment_count"] += 1
            s["status"] = "EXECUTED"
            touch(s)
            return success_obj(sa_view(s))

        if to == "TERMINATED":
            s["status"] = "TERMINATED"
            touch(s)
            for po in db.procurement_orders.values():
                if po["supply_agreement_id"] != sid:
                    continue
                if po["status"] in ("DELIVERED", "ACCEPTED", "CANCELLED"):
                    continue
                was_qualified = po["status"] == "SAFE_HARBOR_QUALIFIED"
                po["status"] = "CANCELLED"
                if was_qualified:
                    clawback_order(po)
                touch(po)
            return success_obj(sa_view(s))

        s["status"] = to
        touch(s)
        return success_obj(sa_view(s))
