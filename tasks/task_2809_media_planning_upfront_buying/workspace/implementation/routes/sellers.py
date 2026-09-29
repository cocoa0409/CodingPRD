"""Seller onboarding and make-good exposure (PRD 3.1)."""

from flask import Blueprint

from auth import require_roles
from constants import PLATFORMS
from response import created
from routes.common import listing, read_one
from serializers import serialize
from store import store
from validation import body

bp = Blueprint("sellers", __name__)


@bp.post("/sellers")
@require_roles("AgencyController")
def create_seller():
    data = body()
    name = data.string("name", max_len=120)
    platform_types = data.enum_list("platform_types", PLATFORMS)
    capacity = data.integer("make_good_capacity_impressions", minimum=0)

    record = store.new(
        "sellers",
        {
            "name": name,
            "platform_types": platform_types,
            "make_good_capacity_impressions": capacity,
        },
    )
    return created(serialize("sellers", record))


@bp.get("/sellers/<seller_id>")
def get_seller(seller_id):
    return read_one("sellers", seller_id)


@bp.get("/sellers")
def list_sellers():
    return listing("sellers")
