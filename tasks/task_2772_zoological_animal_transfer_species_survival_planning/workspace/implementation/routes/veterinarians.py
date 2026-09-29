from flask import Blueprint

import db
import services
from core import (JURISDICTION_RE, actor, auth, body, fail, get_enum, get_str, ok,
                  pagination, paginate, q_enum, q_str, sorted_rows)

bp = Blueprint("veterinarians", __name__)

LICENSE_STATUSES = ("ACTIVE", "LAPSED", "REVOKED")
USDA_CATEGORIES = ("NONE", "CATEGORY_I", "CATEGORY_II")


@bp.post("/veterinarians")
@auth("Registrar")
def create_vet():
    b = body()
    institution_id = get_str(b, "institution_id", required=True)
    full_name = get_str(b, "full_name", required=True)
    license_number = get_str(b, "license_number", required=True)
    license_jurisdiction = get_str(b, "license_jurisdiction", required=True,
                                  pattern=JURISDICTION_RE)
    license_status = get_enum(b, "license_status", LICENSE_STATUSES, default="ACTIVE")
    category = get_enum(b, "usda_accreditation_category", USDA_CATEGORIES, default="NONE")

    db.get_institution(institution_id)
    if actor() != institution_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    rec = db.insert(db.veterinarians, {
        "institution_id": institution_id,
        "full_name": full_name,
        "license_number": license_number,
        "license_jurisdiction": license_jurisdiction,
        "license_status": license_status,
        "usda_accreditation_category": category,
    })
    return ok(services.vet_out(rec), 201)


@bp.get("/veterinarians/<vet_id>")
@auth()
def read_vet(vet_id):
    return ok(services.vet_out(db.get_vet(vet_id)))


@bp.get("/veterinarians")
@auth()
def list_vets():
    limit, offset = pagination()
    institution_id = q_str("institution_id")
    license_status = q_enum("license_status", LICENSE_STATUSES)
    category = q_enum("usda_accreditation_category", USDA_CATEGORIES)
    rows = list(db.veterinarians.values())
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    if license_status is not None:
        rows = [r for r in rows if r["license_status"] == license_status]
    if category is not None:
        rows = [r for r in rows if r["usda_accreditation_category"] == category]
    return paginate(sorted_rows(rows), limit, offset, services.vet_out)
