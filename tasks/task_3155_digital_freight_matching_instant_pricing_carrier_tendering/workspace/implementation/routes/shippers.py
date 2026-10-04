"""Shipper endpoints."""

from db import clock_now, db, mint_id, touch
from db import serialize
from middleware import require_owner, roles_required
from response import array_response, object_response, paginate
from routers import body, require
from services.common import get_shipper, refresh_shipper
from services import loads as load_service


def register(app):
    @app.route("/v1/shippers", methods=["POST"])
    @roles_required("PlatformAdmin")
    def create_shipper():
        payload = body()
        require(payload, "name", "billing_state_code", "payment_terms_days",
                "quick_pay_discount_pct", "credit_limit_cents", "load_credit_limit")
        now = clock_now()
        shipper = {
            "id": mint_id(),
            "name": payload["name"],
            "billing_state_code": payload["billing_state_code"],
            "payment_terms_days": int(payload["payment_terms_days"]),
            "quick_pay_discount_pct": payload["quick_pay_discount_pct"],
            "credit_limit_cents": int(payload["credit_limit_cents"]),
            "credit_used_cents": 0,
            "credit_available_cents": int(payload["credit_limit_cents"]),
            "load_credit_limit": int(payload["load_credit_limit"]),
            "load_credits_committed": 0,
            "load_credits_available": int(payload["load_credit_limit"]),
            "blocked_carrier_ids": [],
            "breached_pickup_count": 0,
            "last_repriced_lane": None,
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.shippers[shipper["id"]] = shipper
        return object_response(serialize("Shipper", shipper), 201)

    @app.route("/v1/shippers/<shipper_id>", methods=["GET"])
    @roles_required("Shipper", "PlatformAdmin", "ComplianceReviewer", "ClaimsAdjuster")
    def get_shipper_route(shipper_id):
        from middleware import current_actor
        role, identity = current_actor()
        shipper = get_shipper(shipper_id)
        require_owner(role, identity, shipper["id"], "shipper")
        refresh_shipper(shipper)
        return object_response(serialize("Shipper", shipper))

    @app.route("/v1/shippers/<shipper_id>/suspend", methods=["POST"])
    @roles_required("PlatformAdmin")
    def suspend_shipper(shipper_id):
        payload = body()
        require(payload, "reason_code")
        shipper = get_shipper(shipper_id)
        shipper["status"] = "SUSPENDED"
        shipper["suspension_reason"] = payload["reason_code"]
        touch(shipper)
        refresh_shipper(shipper)
        return object_response(serialize("Shipper", shipper))

    @app.route("/v1/shippers/<shipper_id>/loads", methods=["GET"])
    @roles_required("Shipper", "PlatformAdmin", "Carrier", "ClaimsAdjuster")
    def shipper_loads(shipper_id):
        from flask import request
        get_shipper(shipper_id)
        rows = load_service.load_list(
            [row for row in db.loads.values() if row["shipper_id"] == shipper_id],
            request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("Load", row) for row in window], pagination)

    @app.route("/v1/shippers/<shipper_id>/lane-contracts", methods=["GET"])
    @roles_required("Shipper", "PlatformAdmin", "Carrier")
    def shipper_contracts(shipper_id):
        from flask import request
        from services.common import refresh_contract
        get_shipper(shipper_id)
        rows = [row for row in db.contracts.values() if row["shipper_id"] == shipper_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        for row in rows:
            refresh_contract(row)
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("LaneContract", row) for row in window], pagination)