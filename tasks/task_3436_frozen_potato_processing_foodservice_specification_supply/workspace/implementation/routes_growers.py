"""Grower registry endpoints."""

import domain
from db import store
from flask import Blueprint
from middleware import ANY_ROLES, require_roles
from response import success_object
from util import body_json, req_enum, req_str
from constants import REGIONS

bp = Blueprint("growers", __name__)


@bp.route("/potato-ops/growers", methods=["POST"])
@require_roles("GrowerRelationsManager")
def create_grower():
    body = body_json()
    grower_code = req_str(body, "grower_code")
    legal_name = req_str(body, "legal_name")
    region = req_enum(body, "region", REGIONS)
    g = domain.new_entity()
    g.update({
        "grower_code": grower_code,
        "legal_name": legal_name,
        "region": region,
    })
    store.growers[g["id"]] = g
    return success_object(domain.grower_view(g), 201)


@bp.route("/potato-ops/growers/<gid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_grower(gid):
    return success_object(domain.grower_view(domain.get_grower_or_404(gid)), 200)
