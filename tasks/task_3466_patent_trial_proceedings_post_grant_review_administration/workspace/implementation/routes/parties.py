"""POST /ptab/parties — register a party (PRD 3.1)."""

from flask import Blueprint

from db import store, strip_internal
from helpers import (
    require_roles, get_body, req_string, opt_string, req_enum, success_object,
)

bp = Blueprint("parties", __name__)

PARTY_TYPES = ("PETITIONER", "PATENT_OWNER")


@bp.post("/ptab/parties")
def create_party():
    require_roles("PlatformAdmin")
    body = get_body()
    name = req_string(body, "name")
    party_type = req_enum(body, "party_type", PARTY_TYPES)
    counsel_firm = opt_string(body, "counsel_firm")

    party = store.new_common()
    party.update({
        "name": name,
        "party_type": party_type,
        "counsel_firm": counsel_firm,
    })
    store.parties[party["id"]] = party
    return success_object(strip_internal(party), status=201)
