"""Percentage-rent charges: the billing axis, the collection axis and payments."""

from flask import request

import calc
from core import (
    ApiError,
    DB,
    all_of,
    body,
    clock_now,
    endpoint,
    must_get,
    need_int,
    need_str,
    ok,
    paginate,
    require_lease_tenant,
    touch,
)
from serializers import ser


def register(app):
    @app.get("/retail/charges/<cid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def get_charge(cid):
        return ok(ser(must_get("charges", cid)))

    @app.get("/retail/charges")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def list_charges():
        rows = all_of("charges")
        for key in (
            "lease_year_id",
            "sales_report_id",
            "supersedes_charge_id",
            "charge_type",
            "billing_status",
            "collection_status",
        ):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        return paginate(rows, ser)

    @app.post("/retail/charges/<cid>/issue")
    @endpoint("LeaseAdministrator")
    def issue_charge(cid):
        charge = must_get("charges", cid)
        ly = DB["lease_years"][charge["lease_year_id"]]
        if charge["billing_status"] != "DRAFT":
            raise ApiError("ERR_CHARGE_STATE_INVALID", 409)
        calc.require_year_not_closed(ly)
        charge["billing_status"] = "ISSUED"
        charge["issued_at"] = clock_now()
        touch(charge)
        amount = charge["amount_cents"]
        calc.move_billed(
            ly,
            amount,
            "TRUE_UP_ISSUED" if amount > 0 else "CREDIT_ISSUED",
            "PercentageRentCharge issued",
        )
        calc.occupancy_cost_ratio(calc.lease_of_year(ly))
        return ok(ser(charge))

    @app.post("/retail/charges/<cid>/void")
    @endpoint("LeaseAdministrator")
    def void_charge(cid):
        charge = must_get("charges", cid)
        ly = DB["lease_years"][charge["lease_year_id"]]
        payload = body()
        need_str(payload, "reason")
        if charge["billing_status"] not in ("DRAFT", "ISSUED"):
            raise ApiError("ERR_CHARGE_STATE_INVALID", 409)
        if charge["billing_status"] == "ISSUED" and charge["collection_status"] not in (
            "UNPAID",
            "PARTIAL",
        ):
            raise ApiError("ERR_CHARGE_STATE_INVALID", 409)
        calc.require_year_not_closed(ly)

        was_issued = charge["billing_status"] == "ISSUED"
        charge["billing_status"] = "VOID"
        if charge["collection_status"] in ("UNPAID", "PARTIAL"):
            charge["collection_status"] = "WRITTEN_OFF"
        touch(charge)
        if was_issued:
            delta = -charge["amount_cents"]
            if charge["charge_type"] == "ESTIMATE":
                entry_type = "ESTIMATE_VOIDED"
            else:
                entry_type = "TRUE_UP_ISSUED" if delta > 0 else "CREDIT_ISSUED"
            calc.move_billed(ly, delta, entry_type, "PercentageRentCharge voided")
            calc.occupancy_cost_ratio(calc.lease_of_year(ly))
        return ok(ser(charge))

    @app.post("/retail/charges/<cid>/payments")
    @endpoint("LeaseAdministrator", "TenantUser")
    def pay_charge(cid):
        charge = must_get("charges", cid)
        ly = DB["lease_years"][charge["lease_year_id"]]
        require_lease_tenant(calc.lease_of_year(ly))
        payload = body()
        amount = need_int(payload, "amount_cents")
        if charge["billing_status"] != "ISSUED":
            raise ApiError("ERR_CHARGE_STATE_INVALID", 409)
        calc.require_year_not_closed(ly)
        outstanding = charge["amount_cents"] - charge["paid_cents"]
        if amount <= 0 or amount > outstanding:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422)
        charge["paid_cents"] += amount
        if charge["paid_cents"] == charge["amount_cents"]:
            charge["collection_status"] = "PAID"
        else:
            charge["collection_status"] = "PARTIAL"
        touch(charge)
        return ok(ser(charge))
