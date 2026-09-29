"""Advertiser onboarding and credit posture (PRD 3.1)."""

from flask import Blueprint

from auth import require_roles
from constants import CATEGORY_CODES
from response import created
from routes.common import listing, read_one
from serializers import serialize
from store import store
from validation import body

bp = Blueprint("advertisers", __name__)


@bp.post("/advertisers")
@require_roles("AgencyController")
def create_advertiser():
    data = body()
    name = data.string("name", max_len=120)
    category_code = data.enum("category_code", CATEGORY_CODES)
    payment_terms_days = data.integer(
        "payment_terms_days", required=False, minimum=0, maximum=120, default=30
    )
    sequential_liability_enabled = data.boolean(
        "sequential_liability_enabled", required=False, default=True
    )
    credit_limit_cents = data.integer("credit_limit_cents", minimum=0)

    record = store.new(
        "advertisers",
        {
            "name": name,
            "category_code": category_code,
            "payment_terms_days": payment_terms_days,
            "sequential_liability_enabled": sequential_liability_enabled,
            "credit_limit_cents": credit_limit_cents,
            "credit_status": "ACTIVE",
            "late_payment_count": 0,
        },
    )
    return created(serialize("advertisers", record))


@bp.get("/advertisers/<advertiser_id>")
def get_advertiser(advertiser_id):
    return read_one("advertisers", advertiser_id)


@bp.get("/advertisers")
def list_advertisers():
    return listing(
        "advertisers",
        {"category_code": "category_code", "credit_status": "credit_status"},
    )
