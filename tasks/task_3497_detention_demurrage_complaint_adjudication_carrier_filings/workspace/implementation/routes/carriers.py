"""CarrierOrganization + ShipperAccount registration and reads (PRD §3.1)."""
from flask import Blueprint

import store
from auth import require_roles, any_role
from envelope import ok_object
from errors import fail, ERR_CARRIER_NOT_FOUND, ERR_SHIPPER_NOT_FOUND
from serialization import ser_carrier, ser_shipper
from util import body, req_str, req_enum
from constants import SCORE_INITIAL

bp = Blueprint("carriers", __name__)

ORG_TYPES = ("VOCC", "MTO", "NVOCC", "OFF")


@bp.post("/fmc/carriers")
def create_carrier():
    require_roles("CommissionAdmin")
    b = body()
    org_name = req_str(b, "org_name")
    org_type = req_enum(b, "org_type", ORG_TYPES)
    rec = store.base_record()
    rec.update(
        org_name=org_name,
        org_type=org_type,
        status="ACTIVE",
        compliance_score=SCORE_INITIAL,
        cumulative_civil_penalties_cents=0,
    )
    store.carriers[rec["id"]] = rec
    return ok_object(ser_carrier(rec), 201)


@bp.get("/fmc/carriers/<carrierId>")
def get_carrier(carrierId):
    any_role()
    c = store.carriers.get(carrierId)
    if c is None:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    return ok_object(ser_carrier(c))


@bp.post("/fmc/shippers")
def create_shipper():
    require_roles("CommissionAdmin")
    b = body()
    company_name = req_str(b, "company_name")
    contact_email = req_str(b, "contact_email")
    rec = store.base_record()
    rec.update(
        company_name=company_name,
        contact_email=contact_email,
        total_recovery_cents=0,
    )
    store.shippers[rec["id"]] = rec
    return ok_object(ser_shipper(rec), 201)


@bp.get("/fmc/shippers/<shipperId>")
def get_shipper(shipperId):
    any_role()
    s = store.shippers.get(shipperId)
    if s is None:
        fail(ERR_SHIPPER_NOT_FOUND, "shipper account not found: %s" % shipperId)
    return ok_object(ser_shipper(s))
