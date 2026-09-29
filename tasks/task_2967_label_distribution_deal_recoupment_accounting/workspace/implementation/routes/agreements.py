"""Artist agreements, royalty rates and amendments (PRD section 3.3)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (ARTIST, BUSINESS_AFFAIRS, LABEL_ADMIN,
                           ROYALTY_ANALYST, find_agreement, find_artist,
                           find_release)
from services import calculations, lookups

bp = Blueprint("agreements", __name__)

ONE = Decimal("1.0000")
ZERO = Decimal("0.0000")
RATE_MIN = Decimal("0.0100")
RATE_MAX = Decimal("0.5000")


@bp.route("/artist-agreements", methods=["POST"])
def create_agreement():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    artist_id = v.identifier(body, "artist_id", required=True)
    release_id = v.identifier(body, "release_id", required=True)
    royalty_rate_pct = v.percentage(body, "royalty_rate_pct", required=True,
                                    minimum=RATE_MIN, maximum=RATE_MAX)
    escalated_royalty_rate_pct = v.percentage(
        body, "escalated_royalty_rate_pct", required=True, maximum=RATE_MAX)
    if escalated_royalty_rate_pct < royalty_rate_pct:
        v.bad("escalated_royalty_rate_pct", "must be at least royalty_rate_pct.")
    advance_amount_cents = v.integer(body, "advance_amount_cents", required=True,
                                     minimum=0)
    recording_costs_cents = v.integer(body, "recording_costs_cents", required=True,
                                      minimum=0)
    recording_recoupable_pct = v.percentage(
        body, "recording_recoupable_pct", required=True, minimum=ZERO, maximum=ONE)
    marketing_recoup_share_pct = v.percentage(
        body, "marketing_recoup_share_pct", required=True, minimum=ZERO, maximum=ONE)
    supersedes_agreement_id = v.identifier(body, "supersedes_agreement_id",
                                           required=False)

    find_artist(artist_id)
    find_release(release_id)
    if supersedes_agreement_id is not None:
        find_agreement(supersedes_agreement_id)

    record = db.base_record()
    record.update({
        "artist_id": artist_id,
        "release_id": release_id,
        "royalty_rate_pct": royalty_rate_pct,
        "escalated_royalty_rate_pct": escalated_royalty_rate_pct,
        "advance_amount_cents": advance_amount_cents,
        "recording_costs_cents": recording_costs_cents,
        "recording_recoupable_pct": recording_recoupable_pct,
        "marketing_recoup_share_pct": marketing_recoup_share_pct,
        "supersedes_agreement_id": supersedes_agreement_id,
        "status": "DRAFT",
        "active_royalty_rate_pct": None,
        "proposed_royalty_rate_pct": None,
        "proposed_advance_amount_cents": None,
        "unrecouped_artist_advance_cents": 0,
        "unrecouped_recording_cents": 0,
        "post_term_collection_end_date": None,
    })
    db.store.agreements[record["id"]] = record
    return response.created(serializers.agreement(record))


@bp.route("/artist-agreements/<record_id>", methods=["GET"])
def get_agreement(record_id):
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS, ARTIST])
    return response.ok(serializers.agreement(find_agreement(record_id)))


@bp.route("/artist-agreements", methods=["GET"])
def list_agreements():
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS, ARTIST])
    limit, offset = pagination()
    records = db.ordered(list(db.store.agreements.values()))
    for key in ("artist_id", "release_id", "supersedes_agreement_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.agreement(r) for r in page], limit, offset, total)


@bp.route("/artist-agreements/<record_id>/activate", methods=["POST"])
def activate_agreement(record_id):
    authenticate([LABEL_ADMIN])
    agreement = find_agreement(record_id)
    parse_body()
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    release = lookups.release_of_agreement(agreement)
    if release is None or release["status"] not in ("PLANNED", "RELEASED"):
        raise ApiError("ERR_INVALID_RELEASE_STATE")
    predecessor = None
    if agreement["supersedes_agreement_id"] is not None:
        predecessor = db.store.agreements.get(agreement["supersedes_agreement_id"])
        if predecessor is None or predecessor["status"] != "ACTIVE" \
                or predecessor["release_id"] != agreement["release_id"]:
            raise ApiError("ERR_INVALID_AGREEMENT_STATE")

    agreement["status"] = "ACTIVE"
    agreement["unrecouped_artist_advance_cents"] = agreement["advance_amount_cents"]
    agreement["unrecouped_recording_cents"] = db.round_half_up(
        Decimal(agreement["recording_costs_cents"])
        * agreement["recording_recoupable_pct"]
    )
    if predecessor is not None:
        agreement["unrecouped_artist_advance_cents"] += \
            predecessor.get("unrecouped_artist_advance_cents") or 0
        agreement["unrecouped_recording_cents"] += \
            predecessor.get("unrecouped_recording_cents") or 0
        predecessor["status"] = "SUPERSEDED"
        predecessor["unrecouped_artist_advance_cents"] = 0
        predecessor["unrecouped_recording_cents"] = 0
        db.touch(predecessor)
        for statement in lookups.statements_of_agreement(predecessor["id"]):
            if statement["status"] in ("DRAFT", "PREPARED"):
                statement["status"] = "VOIDED"
                db.touch(statement)
    deal = lookups.deal_of_release(release)
    agreement["active_royalty_rate_pct"] = calculations.select_royalty_rate(
        agreement, deal)
    db.touch(agreement)
    return response.ok(serializers.agreement(agreement))


@bp.route("/artist-agreements/<record_id>/propose-amendment", methods=["POST"])
def propose_amendment(record_id):
    authenticate([LABEL_ADMIN])
    agreement = find_agreement(record_id)
    body = parse_body()
    proposed_rate = v.percentage(body, "proposed_royalty_rate_pct", required=True,
                                 minimum=RATE_MIN, maximum=RATE_MAX)
    proposed_advance = v.integer(body, "proposed_advance_amount_cents",
                                 required=True, minimum=0)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    deal = lookups.deal_of_agreement(agreement)
    if deal is None or deal["status"] not in ("EXECUTED", "TERMINATION_NOTICE"):
        raise ApiError("ERR_INVALID_DEAL_STATE")
    agreement["status"] = "AMENDMENT_PENDING"
    agreement["proposed_royalty_rate_pct"] = proposed_rate
    agreement["proposed_advance_amount_cents"] = proposed_advance
    db.touch(agreement)
    return response.ok(serializers.agreement(agreement))


@bp.route("/artist-agreements/<record_id>/resolve-amendment", methods=["POST"])
def resolve_amendment(record_id):
    authenticate([BUSINESS_AFFAIRS])
    agreement = find_agreement(record_id)
    body = parse_body()
    decision = v.enum(body, "decision", ("ACCEPT", "REJECT"), required=True)
    if agreement["status"] != "AMENDMENT_PENDING":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    if decision == "ACCEPT":
        old_advance = agreement["advance_amount_cents"] or 0
        new_advance = agreement["proposed_advance_amount_cents"] or 0
        agreement["royalty_rate_pct"] = agreement["proposed_royalty_rate_pct"]
        agreement["advance_amount_cents"] = new_advance
        delta = new_advance - old_advance
        if delta > 0:
            agreement["unrecouped_artist_advance_cents"] = \
                (agreement.get("unrecouped_artist_advance_cents") or 0) + delta
        deal = lookups.deal_of_agreement(agreement)
        agreement["status"] = "ACTIVE"
        agreement["active_royalty_rate_pct"] = calculations.select_royalty_rate(
            agreement, deal)
    else:
        agreement["status"] = "ACTIVE"
    agreement["proposed_royalty_rate_pct"] = None
    agreement["proposed_advance_amount_cents"] = None
    db.touch(agreement)
    return response.ok(serializers.agreement(agreement))
