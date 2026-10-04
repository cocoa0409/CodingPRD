"""Purchase orders: reads and the advance action (SHIP / DELIVER /
REPORT_DIVERSION)."""
from flask import request

import store
from envelope import ok, page_payload
from errors import bad_request, conflict, forbidden, invalid_state, not_found
from security import actor, require_roles
from serializers import purchase_order_json
from validators import as_enum, json_body, pagination_args, require_present

READ_ROLES = ("PlatformAdmin", "Reviewer", "Teacher", "Vendor")
ACTIONS = ("SHIP", "DELIVER", "REPORT_DIVERSION")


def _get_po(po_id):
    po = store.purchase_orders.get(po_id)
    if po is None:
        raise not_found("Purchase order not found")
    return po


def register(app):
    @app.route("/giving/purchase-orders/<po_id>", methods=["GET"])
    def get_po(po_id):
        _, role = actor()
        require_roles(role, READ_ROLES)
        return ok(purchase_order_json(_get_po(po_id)), 200)

    @app.route("/giving/purchase-orders", methods=["GET"])
    def list_pos():
        _, role = actor()
        require_roles(role, READ_ROLES)
        vendor_id = request.args.get("vendor_id")
        project_id = request.args.get("project_id")
        status = request.args.get("status")
        rows = list(store.purchase_orders.values())
        if vendor_id is not None:
            rows = [po for po in rows if po["vendor_id"] == vendor_id]
        if project_id is not None:
            rows = [po for po in rows if po["project_id"] == project_id]
        if status is not None:
            rows = [po for po in rows if po["status"] == status]
        rows.sort(key=lambda po: (po["created_at"], po["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload([purchase_order_json(po) for po in rows], limit, offset)
        return ok(page, 200, pagination=meta)

    @app.route("/giving/purchase-orders/<po_id>/advance", methods=["POST"])
    def advance_po(po_id):
        data = json_body()
        action = as_enum(require_present(data, "action"), "action", ACTIONS)
        tracking_number = None
        if action == "SHIP":
            tracking_number = data.get("tracking_number")
            if not isinstance(tracking_number, str) or tracking_number == "":
                raise bad_request("tracking_number is required for SHIP")
        user_id, role = actor()
        require_roles(role, ("Vendor", "Teacher", "PlatformAdmin"))
        # Per-action role gate.
        if action == "SHIP" and role != "Vendor":
            raise forbidden("Only the vendor ships a purchase order")
        if action == "DELIVER" and role not in ("Teacher", "PlatformAdmin"):
            raise forbidden("Only the owning teacher or a PlatformAdmin confirms delivery")
        if action == "REPORT_DIVERSION" and role != "PlatformAdmin":
            raise forbidden("Only a PlatformAdmin reports diversion")
        po = _get_po(po_id)
        project = store.projects.get(po["project_id"])
        # Ownership gate.
        if action == "SHIP" and user_id != po["vendor_id"]:
            raise forbidden("A vendor may only ship its own purchase orders")
        if action == "DELIVER" and role != "PlatformAdmin":
            if project is None or project["teacher_id"] != user_id:
                raise forbidden("Only the project's owning teacher confirms delivery")
        now = store.logical_now()
        if action == "SHIP":
            if po["status"] != "ISSUED":
                raise invalid_state("Only an ISSUED purchase order can ship")
            vendor = store.vendors.get(po["vendor_id"])
            if vendor is None or vendor["status"] != "ACTIVE":
                raise invalid_state("A suspended vendor cannot ship")
            po["status"] = "SHIPPED"
            po["tracking_number"] = tracking_number
            po["shipped_at"] = now
            store.touch(po)
            return ok(purchase_order_json(po), 200)
        if action == "DELIVER":
            if po["status"] != "SHIPPED":
                raise invalid_state("Only a SHIPPED purchase order can be delivered")
            po["status"] = "DELIVERED"
            po["delivered_at"] = now
            store.touch(po)
            # Bubble up: every PO of the project DELIVERED -> FULFILLED.
            if project is not None and project["status"] == "FUNDED":
                siblings = [
                    p for p in store.purchase_orders.values()
                    if p["project_id"] == project["id"]
                ]
                if siblings and all(p["status"] == "DELIVERED" for p in siblings):
                    project["status"] = "FULFILLED"
                    store.touch(project)
            return ok(purchase_order_json(po), 200)
        # REPORT_DIVERSION
        if po["status"] != "SHIPPED":
            raise invalid_state("Diversion can be reported only on a SHIPPED purchase order")
        teacher_id = project["teacher_id"] if project is not None else None
        if any(
            fc["teacher_id"] == teacher_id and fc["status"] == "OPEN"
            for fc in store.fraud_cases.values()
        ):
            raise conflict(
                "ERR_FRAUD_CASE_ALREADY_OPEN",
                "An OPEN fraud case already exists for this teacher",
            )
        po["status"] = "DIVERSION_REPORTED"
        store.touch(po)
        case = store.base_record()
        case.update({
            "teacher_id": teacher_id,
            "project_id": po["project_id"],
            "purchase_order_id": po["id"],
            "reason": data.get("reason"),
            "status": "OPEN",
        })
        store.fraud_cases[case["id"]] = case
        return ok(purchase_order_json(po), 200)
