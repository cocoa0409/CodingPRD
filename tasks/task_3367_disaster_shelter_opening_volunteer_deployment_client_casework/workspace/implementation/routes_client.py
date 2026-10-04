"""Client records and shelter registration reads."""

from core import (authenticate, base_row, insert, list_response, must_get,
                  ok_object, read_json, rows, serialize, validate_body)
from errors import ApiError
from flask import Blueprint, request

bp = Blueprint("client", __name__)

CLIENT_WRITE_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "Caseworker", "ShelterManager"]
CLIENT_READ_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "Caseworker", "ShelterManager"]
REGISTRATION_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "ShelterManager", "Caseworker"]


@bp.post("/api/v1/clients")
def create_client():
    authenticate(CLIENT_WRITE_ROLES)
    body = read_json()
    validate_body(body, required={
        "full_name": str,
        "household_size": int,
        "region_id": str,
    }, optional={"primary_client_id": str})
    if body["household_size"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "household_size must be >= 1")
    must_get("regions", body["region_id"])
    if body.get("primary_client_id") is not None:
        must_get("clients", body["primary_client_id"])
    record = base_row()
    record.update({
        "full_name": body["full_name"],
        "household_size": body["household_size"],
        "region_id": body["region_id"],
        "primary_client_id": body.get("primary_client_id"),
    })
    insert("clients", record)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/clients/<client_id>")
def read_client(client_id):
    user_id, role = authenticate(CLIENT_READ_ROLES + ["Client"])
    if role == "Client" and user_id != client_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "a client may only read their own record")
    return ok_object(serialize(must_get("clients", client_id)))


@bp.get("/api/v1/clients")
def list_clients():
    authenticate(["NationalHQAdmin", "RegionalCoordinator", "Caseworker"])
    clients = rows("clients")
    region_id = request.args.get("region_id")
    primary_id = request.args.get("primary_client_id")
    if region_id:
        clients = [c for c in clients if c["region_id"] == region_id]
    if primary_id:
        clients = [c for c in clients if c.get("primary_client_id") == primary_id]
    return list_response(clients)


@bp.get("/api/v1/shelter-registrations/<registration_id>")
def read_registration(registration_id):
    authenticate(REGISTRATION_ROLES)
    return ok_object(serialize(must_get("shelter_registrations", registration_id)))


@bp.get("/api/v1/shelter-registrations")
def list_registrations():
    authenticate(REGISTRATION_ROLES)
    registrations = rows("shelter_registrations")
    shelter_id = request.args.get("shelter_operation_id")
    client_id = request.args.get("client_id")
    if shelter_id:
        registrations = [r for r in registrations if r["shelter_operation_id"] == shelter_id]
    if client_id:
        registrations = [r for r in registrations if r["client_id"] == client_id]
    return list_response(registrations)
