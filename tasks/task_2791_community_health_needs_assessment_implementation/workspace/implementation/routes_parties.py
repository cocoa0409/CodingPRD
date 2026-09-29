"""Responsible parties: internal departments and external partner organizations."""

from flask import Blueprint

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, filter_eq, new_record, ok,
                  ok_list, paginate, public, sorted_asc, v_enum, v_int, v_str)

bp = Blueprint("parties", __name__)


@bp.post("/responsible-parties")
def create_party():
    authenticate([K.CBO])
    body = body_or_empty()
    name = v_str(body, "name", 1, 120)
    party_type = v_enum(body, "party_type", K.PARTY_TYPES)
    capacity = v_int(body, "fte_capacity_bp", 0, K.MAX_FTE_BP)
    rec = new_record()
    rec.update({
        "name": name,
        "party_type": party_type,
        "fte_capacity_bp": capacity,
        "committed_fte_bp": 0,
    })
    db.parties[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/responsible-parties")
def list_parties():
    authenticate([K.CBO, K.CO])
    rows = filter_eq(list(db.parties.values()), "party_type")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/responsible-parties/<party_id>")
def get_party(party_id):
    authenticate([K.CBO, K.CO, K.PR])
    return ok(public(D.party_or_404(party_id)))
