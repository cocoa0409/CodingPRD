"""Lane contract endpoints."""

from flask import request

from constants import EQUIPMENT_TYPES, parse_instant
from db import clock_now, db, mint_id, serialize, touch
from errors import ApiError
from middleware import current_actor, require_owner, roles_required
from response import array_response, object_response, paginate
from routers import body, require
from services.common import (
    get_contract, get_facility, get_shipper, refresh_contract,
)
from services.loads import load_list


def register(app):
    @app.route("/v1/lane-contracts", methods=["POST"])
    @roles_required("Shipper", "PlatformAdmin")
    def create_contract():
        payload = body()
        require(payload, "shipper_id", "origin_facility_id", "destination_facility_id",
                "equipment_type", "committed_weekly_volume", "committed_rate_cents",
                "accessorial_allowance_cents", "start_date", "end_date",
                "contract_carrier_ids")
        shipper = get_shipper(payload["shipper_id"])
        role, identity = current_actor()
        if role == "Shipper":
            require_owner(role, identity, shipper["id"], "shipper")
        get_facility(payload["origin_facility_id"])
        get_facility(payload["destination_facility_id"])
        if payload["equipment_type"] not in EQUIPMENT_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown equipment_type.")
        if not isinstance(payload["contract_carrier_ids"], list):
            raise ApiError("ERR_INVALID_REQUEST", "contract_carrier_ids must be a list.")
        now = clock_now()
        contract = {
            "id": mint_id(),
            "shipper_id": shipper["id"],
            "origin_facility_id": payload["origin_facility_id"],
            "destination_facility_id": payload["destination_facility_id"],
            "equipment_type": payload["equipment_type"],
            "committed_weekly_volume": int(payload["committed_weekly_volume"]),
            "committed_rate_cents": int(payload["committed_rate_cents"]),
            "accessorial_allowance_cents": int(payload["accessorial_allowance_cents"]),
            "start_date": parse_instant(payload["start_date"], "start_date"),
            "end_date": parse_instant(payload["end_date"], "end_date"),
            "loads_committed_this_period": 0,
            "period_start": None,
            "contract_carrier_ids": list(payload["contract_carrier_ids"]),
            "status": "DRAFT",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.contracts[contract["id"]] = contract
        return object_response(serialize("LaneContract", contract), 201)

    @app.route("/v1/lane-contracts", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin")
    def list_contracts():
        rows = list(db.contracts.values())
        role, identity = current_actor()
        if role == "Shipper":
            rows = [row for row in rows if row["shipper_id"] == identity]
        for field in ("shipper_id", "origin_facility_id", "destination_facility_id",
                      "equipment_type", "status"):
            value = request.args.get(field)
            if value:
                rows = [row for row in rows if row.get(field) == value]
        for row in rows:
            refresh_contract(row)
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("LaneContract", row) for row in window], pagination)

    @app.route("/v1/lane-contracts/<contract_id>", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ClaimsAdjuster")
    def get_contract_route(contract_id):
        contract = get_contract(contract_id)
        role, identity = current_actor()
        if role == "Shipper":
            require_owner(role, identity, contract["shipper_id"], "contract")
        refresh_contract(contract)
        return object_response(serialize("LaneContract", contract))

    @app.route("/v1/lane-contracts/<contract_id>/activate", methods=["POST"])
    @roles_required("Shipper", "PlatformAdmin")
    def activate_contract(contract_id):
        contract = get_contract(contract_id)
        role, identity = current_actor()
        if role == "Shipper":
            require_owner(role, identity, contract["shipper_id"], "contract")
        if contract["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        contract["status"] = "ACTIVE"
        touch(contract)
        return object_response(serialize("LaneContract", contract))

    @app.route("/v1/lane-contracts/<contract_id>/loads", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin")
    def contract_loads(contract_id):
        contract = get_contract(contract_id)
        role, identity = current_actor()
        if role == "Shipper":
            require_owner(role, identity, contract["shipper_id"], "contract")
        refresh_contract(contract)
        rows = [row for row in db.loads.values() if row["lane_contract_id"] == contract_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("Load", row) for row in window], pagination)