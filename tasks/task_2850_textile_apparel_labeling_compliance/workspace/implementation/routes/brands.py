"""Trade parties, responsibility of record and posture (PRD 3.1)."""
from flask import Blueprint, request

import calc
from auth import require_roles
from envelope import created, listing, ok
from errors import fail
from serializers import brand_json
from store import create_row, db, ordered
from validate import (body, find_brand, present, req_enum, req_string)

bp = Blueprint("brands", __name__)

PARTY_TYPES = ("BRAND_OWNER", "PRIVATE_LABEL_RETAILER", "LICENSEE")
RESPONSIBILITY_MODES = ("SELF_OF_RECORD", "LICENSOR_OF_RECORD")


@bp.post("/labeling/brands")
def register_brand():
    require_roles("ComplianceAdmin")
    payload = body()
    # Ladder step 5: body references resolve before the shape check.
    licensor_id = None
    if present(payload, "licensor_brand_id"):
        licensor_id = find_brand(payload["licensor_brand_id"])["id"]
    legal_name = req_string(payload, "legal_name", min_len=1, max_len=120)
    party_type = req_enum(payload, "party_type", PARTY_TYPES)
    rn_number = None
    if present(payload, "rn_number"):
        rn_number = req_string(payload, "rn_number", min_len=7, max_len=7,
                               pattern=r"^RN[0-9]{5}$")
    mode = req_enum(payload, "responsibility_mode", RESPONSIBILITY_MODES)
    # Ladder step 7: licensor coherence.
    if party_type == "LICENSEE" and licensor_id is None:
        fail("ERR_LICENSOR_REQUIRED", "A licensee must name its licensor.")
    if party_type != "LICENSEE" and licensor_id is not None:
        fail("ERR_LICENSOR_REQUIRED", "Only a licensee may name a licensor.")
    if mode == "LICENSOR_OF_RECORD" and licensor_id is None:
        fail("ERR_LICENSOR_REQUIRED", "LICENSOR_OF_RECORD requires a licensor.")
    row = create_row(db.brands, {
        "legal_name": legal_name,
        "party_type": party_type,
        "rn_number": rn_number,
        "licensor_brand_id": licensor_id,
        "responsibility_mode": mode,
    })
    return created(brand_json(row))


@bp.get("/labeling/brands/<bid>")
def read_brand(bid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "CustomsOfficer", "Auditor")
    row = db.brands.get(bid)
    if row is None:
        fail("ERR_BRAND_NOT_FOUND", "Brand not found.")
    return ok(brand_json(row))


@bp.get("/labeling/brands")
def list_brands():
    require_roles("ComplianceAdmin", "Auditor")
    rows = ordered(list(db.brands.values()))
    args = request.args
    if args.get("party_type") is not None:
        rows = [r for r in rows if r["party_type"] == args.get("party_type")]
    if args.get("licensor_brand_id") is not None:
        rows = [r for r in rows if r["licensor_brand_id"] == args.get("licensor_brand_id")]
    if args.get("responsible_brand_id") is not None:
        rows = [r for r in rows
                if calc.responsible_of(r) == args.get("responsible_brand_id")]
    if args.get("posture") is not None:
        rows = [r for r in rows if calc.brand_posture(r["id"]) == args.get("posture")]
    return listing(rows, brand_json)
