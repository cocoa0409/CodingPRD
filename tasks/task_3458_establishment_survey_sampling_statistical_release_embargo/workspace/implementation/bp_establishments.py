"""POST /survey/establishments (PRD 3.2)."""
from flask import Blueprint

from authz import get_auth, require_role
from envelope import ok
from errors import raise_err, ERR_DUPLICATE_ESTABLISHMENT
from store import DB, new_entity
from validate import get_body, req_str, req_industry, req_size

bp = Blueprint("establishments", __name__)


@bp.post("/establishments")
def create_establishment():
    _user, role = get_auth()
    require_role(role, {"CollectionOfficer"})
    data = get_body()

    ein = req_str(data, "ein")
    name = req_str(data, "name")
    industry = req_industry(data)
    size = req_size(data)

    if any(e["ein"] == ein for e in DB["establishments"].values()):
        raise_err(ERR_DUPLICATE_ESTABLISHMENT, f"ein '{ein}' is already registered")

    est = new_entity("establishments", {
        "ein": ein,
        "name": name,
        "industry_code": industry,
        "size_class": size,
    })
    return ok(est, status=201)
