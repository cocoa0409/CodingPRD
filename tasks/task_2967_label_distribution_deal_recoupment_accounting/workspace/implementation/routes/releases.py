"""Releases and the allocation of the advance (PRD section 3.2)."""

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (ARTIST, BUSINESS_AFFAIRS, DISTRIBUTION_PARTNER,
                           LABEL_ADMIN, ROYALTY_ANALYST, find_artist, find_deal,
                           find_release)
from services import lookups

bp = Blueprint("releases", __name__)

FORMATS = ("DIGITAL", "VINYL", "CD", "CASSETTE")
PHYSICAL_FORMATS = ("VINYL", "CD", "CASSETTE")


@bp.route("/releases", methods=["POST"])
def create_release():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    deal_id = v.identifier(body, "deal_id", required=True)
    primary_artist_id = v.identifier(body, "primary_artist_id", required=True)
    upc = v.upc(body, "upc", required=True)
    title = v.text(body, "title", required=True, min_len=1, max_len=200)
    planned_release_date = v.date_field(body, "planned_release_date", required=True)
    formats = v.enum_list(body, "formats", FORMATS, required=True)
    advance_share_cents = v.integer(body, "advance_share_cents", required=False,
                                   minimum=0, default=0)

    deal = find_deal(deal_id)
    find_artist(primary_artist_id)

    term_start = db.parse_date(deal["term_start_date"])
    term_end = db.parse_date(deal["term_end_date"])
    if planned_release_date < term_start or planned_release_date > term_end:
        v.bad("planned_release_date", "must fall inside the deal's term.")

    for existing in db.store.releases.values():
        if existing["upc"] == upc:
            raise ApiError("ERR_DUPLICATE_UPC")

    allocated = sum(
        (r.get("advance_share_cents") or 0)
        for r in lookups.releases_of_deal(deal_id)
        if r["status"] != "REVERTED"
    )
    if allocated + advance_share_cents > (deal["advance_amount_cents"] or 0):
        raise ApiError("ERR_ADVANCE_ALLOCATION_EXCEEDED")

    record = db.base_record()
    record.update({
        "deal_id": deal_id,
        "primary_artist_id": primary_artist_id,
        "upc": upc,
        "title": title,
        "planned_release_date": db.date_str(planned_release_date),
        "actual_release_date": None,
        "formats": formats,
        "advance_share_cents": advance_share_cents,
        "status": "PLANNED",
        "reversion_eligible_date": None,
        "net_receipts_to_date_cents": 0,
        "release_advance_recouped_cents": 0,
        "unrecouped_advance_share_cents": 0,
        "recoupable_marketing_applied_cents": 0,
    })
    db.store.releases[record["id"]] = record
    return response.created(serializers.release(record))


@bp.route("/releases/<record_id>", methods=["GET"])
def get_release(record_id):
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS,
                  DISTRIBUTION_PARTNER, ARTIST])
    return response.ok(serializers.release(find_release(record_id)))


@bp.route("/releases", methods=["GET"])
def list_releases():
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS,
                  DISTRIBUTION_PARTNER, ARTIST])
    limit, offset = pagination()
    records = db.ordered(list(db.store.releases.values()))
    for key in ("deal_id", "primary_artist_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.release(r) for r in page], limit, offset, total)


@bp.route("/releases/<record_id>/release", methods=["POST"])
def take_to_market(record_id):
    authenticate([LABEL_ADMIN])
    release = find_release(record_id)
    body = parse_body()
    actual_release_date = v.date_field(body, "actual_release_date", required=True)
    if release["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_RELEASE_STATE")
    deal = lookups.deal_of_release(release)
    if deal is None or deal["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    term_start = db.parse_date(deal["term_start_date"])
    term_end = db.parse_date(deal["term_end_date"])
    if actual_release_date < term_start or actual_release_date > term_end:
        raise ApiError("ERR_PERIOD_OUTSIDE_TERM")
    release["status"] = "RELEASED"
    release["actual_release_date"] = db.date_str(actual_release_date)
    db.touch(release)
    return response.ok(serializers.release(release))


@bp.route("/releases/<record_id>/dsp-revenue-lines", methods=["GET"])
def list_release_lines(record_id):
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS,
                  DISTRIBUTION_PARTNER])
    release = find_release(record_id)
    limit, offset = pagination()
    records = lookups.lines_of_release(release["id"])
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.line(r) for r in page], limit, offset, total)
