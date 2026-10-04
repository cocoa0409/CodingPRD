"""Publications, circulation, and advertising-standard ad bookings."""

from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from db import locked, mint, store
from serializers import booking_view, publication_view
from services import RESTRICTED_AD_CATEGORIES, circulation_count
from util import err, get_body, is_int, paginate, parse_date_strict, require_str, round_half_up, success_object

bp = Blueprint("publications", __name__)

AD_CATEGORIES = {"TRAVEL", "INSURANCE", "HEALTH", "FINANCE", "RETAIL", "TOBACCO", "FIREARMS", "POLITICAL"}
PUBLICATION_READ_ROLES = ("StandardsReviewer", "MemberServicesAgent", "PlatformAdmin")


@bp.post("/api/publications")
@locked
def create_publication():
    require_roles("StandardsReviewer")
    body = get_body()
    title = require_str(body, "title")
    pub_date_raw = body.get("publication_date")
    if parse_date_strict(pub_date_raw) is None:
        err("ERR_INVALID_REQUEST", 400, "publication_date is required and must be an ISO date")
    min_cpm = body.get("min_cpm_cents")
    max_cpm = body.get("max_cpm_cents")
    if min_cpm is None or not is_int(min_cpm) or max_cpm is None or not is_int(max_cpm):
        err("ERR_INVALID_REQUEST", 400, "min_cpm_cents and max_cpm_cents are required integers")
    if max_cpm < min_cpm:
        err("ERR_INVALID_REQUEST", 400, "max_cpm_cents must be at least min_cpm_cents")
    publication = mint(store.publications)
    publication.update(
        {
            "title": title,
            "publication_date": pub_date_raw,
            "min_cpm_cents": min_cpm,
            "max_cpm_cents": max_cpm,
        }
    )
    return success_object(publication_view(publication), status=201)


@bp.get("/api/publications/<publication_id>")
@locked
def get_publication(publication_id):
    require_roles(*PUBLICATION_READ_ROLES)
    publication = store.publications.get(publication_id)
    if publication is None:
        err("ERR_NOT_FOUND", 404, "Publication not found")
    return success_object(publication_view(publication))


@bp.post("/api/publications/<publication_id>/ad-bookings")
@locked
def book_ad(publication_id):
    require_roles("StandardsReviewer")
    body = get_body()
    advertiser_name = require_str(body, "advertiser_name")
    category = body.get("category")
    if category is None or category not in AD_CATEGORIES:
        err("ERR_INVALID_REQUEST", 400, "category must be a declared ad category")
    agreed_cpm = body.get("agreed_cpm_cents")
    if agreed_cpm is None or not is_int(agreed_cpm):
        err("ERR_INVALID_REQUEST", 400, "agreed_cpm_cents is required and must be an integer")
    publication = store.publications.get(publication_id)
    if publication is None:
        err("ERR_NOT_FOUND", 404, "Publication not found")
    # Rung 10: advertising standards.
    if category in RESTRICTED_AD_CATEGORIES:
        err("ERR_AD_CATEGORY_RESTRICTED", 422, "Category %s violates advertising standards" % category)
    # Rung 12, pinned order: rate card first, then the circulation base.
    if not (publication["min_cpm_cents"] <= agreed_cpm <= publication["max_cpm_cents"]):
        err("ERR_RATE_CARD_VIOLATION", 422, "agreed_cpm_cents is outside the rate card")
    circulation = circulation_count(publication["publication_date"])
    if circulation == 0:
        err("ERR_NO_CIRCULATION_BASE", 422, "The issue has zero circulation")
    estimated_cost = round_half_up(Decimal(agreed_cpm) * Decimal(circulation) / Decimal(1000))
    booking = mint(store.bookings)
    booking.update(
        {
            "publication_id": publication_id,
            "advertiser_name": advertiser_name,
            "category": category,
            "agreed_cpm_cents": agreed_cpm,
            "estimated_cost_cents": estimated_cost,
            "status": "BOOKED",
        }
    )
    return success_object(booking_view(booking), status=201)


@bp.get("/api/publications/<publication_id>/ad-bookings")
@locked
def list_ad_bookings(publication_id):
    require_roles("StandardsReviewer", "PlatformAdmin")
    if publication_id not in store.publications:
        err("ERR_NOT_FOUND", 404, "Publication not found")
    bookings = [
        b
        for b in sorted(store.bookings.values(), key=lambda r: r["_seq"])
        if b["publication_id"] == publication_id
    ]
    return paginate([booking_view(b) for b in bookings])
