"""Jurisdiction, delivery-center and vehicle-configuration routes."""

from flask import Blueprint, request

from db import DB
from repository import get, matches, serialize
from response import list_response, object_response
from routes.common import body, bool_field, counted, int_field, need, paged, text_field
from services import sales

bp = Blueprint("catalog", __name__)


# --- StateJurisdiction ---

@bp.post("/jurisdictions")
def create_jurisdiction():
    payload = body()
    row = sales.create_jurisdiction(
        text_field(payload, "state_code"),
        bool_field(payload, "direct_sales_permitted", False),
        bool_field(payload, "gallery_only_required", False),
        bool_field(payload, "out_of_state_delivery_required", False),
        int_field(payload, "cooling_off_days", 3),
        int_field(payload, "doc_fee_cap_cents", 0),
        bool_field(payload, "mobile_service_permitted", True),
        int_field(payload, "delivery_buffer_minutes", 60),
        int_field(payload, "allocation_window_days", 14),
        int_field(payload, "transport_lead_days", 7),
    )
    return object_response(serialize(row), 201)


@bp.get("/jurisdictions")
def list_jurisdictions():
    rows = [r for r in DB.jurisdictions.values()
            if matches(request.args, "state_code", r["state_code"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/jurisdictions/<jurisdiction_id>")
def get_jurisdiction(jurisdiction_id):
    return object_response(serialize(get("jurisdiction", jurisdiction_id)))


@bp.post("/jurisdictions/<jurisdiction_id>/enact")
def enact_jurisdiction(jurisdiction_id):
    row = get("jurisdiction", jurisdiction_id)
    return object_response(serialize(sales.enact_jurisdiction(row)))


# --- DeliveryCenter ---

@bp.post("/delivery-centers")
def create_center():
    payload = body()
    center = sales.create_center(
        text_field(payload, "center_name"),
        text_field(payload, "center_kind"),
        text_field(payload, "state_code"),
        int_field(payload, "bay_count", 0),
        int_field(payload, "home_delivery_radius_miles", 0),
        int_field(payload, "van_count", 0),
    )
    return object_response(serialize(center), 201)


@bp.get("/delivery-centers")
def list_centers():
    rows = [r for r in DB.centers.values()
            if matches(request.args, "state_code", r["state_code"])
            and matches(request.args, "center_kind", r["center_kind"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/delivery-centers/<center_id>")
def get_center(center_id):
    return object_response(serialize(get("center", center_id)))


@bp.post("/delivery-centers/<center_id>/suspend")
def suspend_center(center_id):
    return object_response(serialize(sales.suspend_center(get("center", center_id))))


@bp.post("/delivery-centers/<center_id>/reinstate")
def reinstate_center(center_id):
    return object_response(serialize(sales.reinstate_center(get("center", center_id))))


@bp.get("/delivery-centers/<center_id>/delivery-appointments")
def center_appointments(center_id):
    center = get("center", center_id)
    rows = [r for r in DB.appointments.values()
            if r["delivery_center_id"] == center["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/delivery-centers/<center_id>/service-appointments")
def center_service_appointments(center_id):
    center = get("center", center_id)
    rows = [r for r in DB.service_appointments.values()
            if r["service_center_id"] == center["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/delivery-centers/<center_id>/mobile-service-visits")
def center_visits(center_id):
    center = get("center", center_id)
    rows = [r for r in DB.visits.values()
            if r["parts_hub_id"] == center["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


# --- VehicleConfiguration ---

@bp.post("/vehicle-configurations")
def create_configuration():
    payload = body()
    configuration = sales.create_configuration(
        text_field(payload, "model_code"), int_field(payload, "base_price_cents", 0))
    return object_response(serialize(configuration), 201)


@bp.get("/vehicle-configurations")
def list_configurations():
    rows = [r for r in DB.configurations.values()
            if matches(request.args, "model_code", r["model_code"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/vehicle-configurations/<configuration_id>")
def get_configuration(configuration_id):
    return object_response(serialize(get("configuration", configuration_id)))


@bp.post("/vehicle-configurations/<configuration_id>/options")
def add_option(configuration_id):
    configuration = get("configuration", configuration_id)
    payload = body()
    option = sales.add_option(configuration,
                              text_field(payload, "option_sku"),
                              text_field(payload, "option_category"),
                              int_field(payload, "price_cents", 0))
    return object_response(serialize(option), 201)


@bp.get("/vehicle-configurations/<configuration_id>/options")
def list_configuration_options(configuration_id):
    configuration = get("configuration", configuration_id)
    rows = [r for r in DB.options.values()
            if r["configuration_id"] == configuration["id"]
            and matches(request.args, "option_category", r["option_category"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/configuration-options")
def list_options():
    rows = [r for r in DB.options.values()
            if matches(request.args, "configuration_id", r["configuration_id"])
            and matches(request.args, "option_category", r["option_category"])
            and matches(request.args, "status", r["status"])]
    wanted = request.args.get("is_software_entitlement")
    if wanted not in (None, ""):
        truthy = str(wanted).strip().lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r["is_software_entitlement"]) is truthy]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/configuration-options/<option_id>")
def get_option(option_id):
    return object_response(serialize(get("option", option_id)))


@bp.post("/configuration-options/<option_id>/retire")
def retire_option(option_id):
    return object_response(serialize(sales.retire_option(get("option", option_id))))