"""POST /rideshare/customers — register a customer organization."""
from flask import Blueprint

from envelope import success
from middleware import require_roles
from serialize import ser_customer
from store import db, new_entity
from validate import as_int, as_str, body_json, opt_field, req_field

bp = Blueprint("customers", __name__)


@bp.post("/rideshare/customers")
@require_roles("PlatformAdmin")
def create_customer():
    body = body_json()
    org_name = as_str(req_field(body, "org_name"), "org_name")
    contact_email = as_str(req_field(body, "contact_email"), "contact_email")
    default_rebookings = opt_field(body, "default_rebookings", 1)
    default_rebookings = as_int(default_rebookings, "default_rebookings")

    c = new_entity()
    c.update(
        {
            "org_name": org_name,
            "contact_email": contact_email,
            "default_rebookings": default_rebookings,
        }
    )
    db["customers"][c["id"]] = c
    return success(ser_customer(c), 201)
