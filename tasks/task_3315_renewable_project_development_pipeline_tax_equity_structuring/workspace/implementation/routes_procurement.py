"""Procurement order routes."""
from decimal import Decimal

import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_enum, req_positive_number, opt_number,
    success_obj, success_arr, pagination_args, paginate, now_common, touch,
    dec2, iso_from_epoch,
)
from serializers import po_view
from logic import (
    get_sa, get_po, tcq_for_project, clawback_order, SAFE_HARBOR_WINDOW_DAYS, DAY,
    SA_ACTIVE_STATES,
)

READ_ROLES = ["ProcurementLead", "DeveloperAdmin", "TaxCounsel", "Auditor", "PlatformAdmin"]


def register(app):

    @app.post("/api/supply-agreements/<sid>/procurement-orders")
    def create_po(sid):
        require_auth(["ProcurementLead"])
        get_sa(sid)
        body = payload()
        amount = req_positive_number(body, "order_amount_usd")
        method = req_enum(body, "safe_harbor_method", {"FIVE_PERCENT_COST", "PHYSICAL_WORK"})
        basis = req_positive_number(body, "eligible_cost_basis_usd")
        oid = db.new_id()
        o = {
            "id": oid,
            "supply_agreement_id": sid,
            "order_amount_usd": float(amount),
            "safe_harbor_method": method,
            "eligible_cost_basis_usd": float(basis),
            "deposit_paid_usd": 0.0,
            "safe_harbor_qualified": False,
            "physical_work_evidence_uri": None,
            "status": "PLACED",
        }
        now_common(o)
        db.procurement_orders[oid] = o
        return success_obj(po_view(o), 201)

    @app.get("/api/supply-agreements/<sid>/procurement-orders")
    def list_po(sid):
        require_auth(READ_ROLES)
        get_sa(sid)
        limit, offset = pagination_args()
        items = sorted(
            [o for o in db.procurement_orders.values() if o["supply_agreement_id"] == sid],
            key=lambda o: (o["created_at"], o["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([po_view(o) for o in page], limit, offset, total)

    @app.get("/api/procurement-orders/<oid>")
    def get_po_route(oid):
        require_auth(READ_ROLES)
        o = get_po(oid)
        return success_obj(po_view(o))

    @app.post("/api/procurement-orders/<oid>/transitions")
    def po_transition(oid):
        require_auth(["ProcurementLead"])
        o = get_po(oid)
        body = payload()
        to = req_enum(body, "to", {
            "DEPOSIT_PAID", "SAFE_HARBOR_QUALIFIED", "DELIVERED", "ACCEPTED", "CANCELLED",
        })
        cur = o["status"]
        valid = {
            ("PLACED", "DEPOSIT_PAID"),
            ("DEPOSIT_PAID", "DEPOSIT_PAID"),
            ("DEPOSIT_PAID", "SAFE_HARBOR_QUALIFIED"),
            ("SAFE_HARBOR_QUALIFIED", "DELIVERED"),
            ("DELIVERED", "ACCEPTED"),
            ("PLACED", "CANCELLED"),
            ("DEPOSIT_PAID", "CANCELLED"),
            ("SAFE_HARBOR_QUALIFIED", "CANCELLED"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")

        if to == "DEPOSIT_PAID":
            amount = opt_number(body, "deposit_amount_usd", None)
            if amount is None or amount <= 0:
                raise_err("ERR_VALIDATION", "deposit_amount_usd must be present and > 0")
            o["deposit_paid_usd"] = float(dec2(o["deposit_paid_usd"]) + amount)
            o["status"] = "DEPOSIT_PAID"
            touch(o)
            return success_obj(po_view(o))

        if to == "SAFE_HARBOR_QUALIFIED":
            sa = get_sa(o["supply_agreement_id"])
            tcq = tcq_for_project(sa["project_id"])
            # priority 8: temporal window
            from helpers import parse_iso
            created_epoch = parse_iso(o["created_at"])
            if db.clock_now() > created_epoch + SAFE_HARBOR_WINDOW_DAYS * DAY:
                raise_err("ERR_SAFE_HARBOR_WINDOW_LAPSED",
                          "Safe-harbor confirm after created_at + 183 days")
            # priority 10: supply agreement executed-or-later
            if sa["status"] not in SA_ACTIVE_STATES:
                raise_err("ERR_SUPPLY_AGREEMENT_NOT_EXECUTED",
                          "Parent supply agreement not executed")
            # priority 12: TCQ not DISQUALIFIED
            if tcq is not None and tcq["status"] == "DISQUALIFIED":
                raise_err("ERR_CREDIT_DISQUALIFIED", "Tax credit qualification is DISQUALIFIED")
            # priority 4/11: method check
            if o["safe_harbor_method"] == "FIVE_PERCENT_COST":
                threshold = (dec2(o["eligible_cost_basis_usd"]) * Decimal("0.05")).quantize(
                    Decimal("0.01"))
                if dec2(o["deposit_paid_usd"]) < threshold:
                    raise_err("ERR_SAFE_HARBOR_TEST_FAILED",
                              "deposit_paid_usd below 5% threshold")
            else:  # PHYSICAL_WORK
                uri = body.get("physical_work_evidence_uri")
                if not uri or not isinstance(uri, str):
                    raise_err("ERR_VALIDATION",
                              "physical_work_evidence_uri required for PHYSICAL_WORK")
                o["physical_work_evidence_uri"] = uri
            o["status"] = "SAFE_HARBOR_QUALIFIED"
            o["safe_harbor_qualified"] = True
            touch(o)
            return success_obj(po_view(o))

        if to == "CANCELLED":
            was_qualified = cur == "SAFE_HARBOR_QUALIFIED"
            o["status"] = "CANCELLED"
            if was_qualified:
                clawback_order(o)
            touch(o)
            return success_obj(po_view(o))

        o["status"] = to
        touch(o)
        return success_obj(po_view(o))
