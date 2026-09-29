"""Clock control, counterparties, artists and stream rate cards."""

from decimal import Decimal

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (ARTIST, BUSINESS_AFFAIRS, DISTRIBUTION_PARTNER,
                           LABEL_ADMIN, ROYALTY_ANALYST, find_artist,
                           find_distributor)

bp = Blueprint("setup", __name__)

TIERS = ("PREMIUM", "AD_SUPPORTED", "FREE_TRIAL")


# ---------------------------------------------------------------------
# Logical clock (PRD section 2.5)
# ---------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    instant = v.instant_field(body, "to_iso8601", required=True)
    db.store.set_now(instant)
    return response.empty()


# ---------------------------------------------------------------------
# Distributors
# ---------------------------------------------------------------------

@bp.route("/distributors", methods=["POST"])
def create_distributor():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    name = v.text(body, "name", required=True, min_len=1, max_len=120)
    legal_entity = v.text(body, "legal_entity", required=True, min_len=1, max_len=160)
    default_pct = v.percentage(
        body, "default_returns_reserve_pct", required=False,
        minimum=Decimal("0.0000"), maximum=Decimal("0.5000"),
        default=Decimal("0.2000"),
    )
    record = db.base_record()
    record.update({
        "name": name,
        "legal_entity": legal_entity,
        "default_returns_reserve_pct": default_pct,
    })
    db.store.distributors[record["id"]] = record
    return response.created(serializers.distributor(record))


@bp.route("/distributors/<record_id>", methods=["GET"])
def get_distributor(record_id):
    authenticate([LABEL_ADMIN, DISTRIBUTION_PARTNER])
    record = find_distributor(record_id)
    return response.ok(serializers.distributor(record))


# ---------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------

@bp.route("/artists", methods=["POST"])
def create_artist():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    legal_name = v.text(body, "legal_name", required=True, min_len=1, max_len=120)
    email = v.email(body, "email", required=True)
    lowered = email.lower()
    for existing in db.store.artists.values():
        if existing["email"].lower() == lowered:
            raise ApiError("ERR_INVALID_REQUEST", "email is already registered.")
    record = db.base_record()
    record.update({"legal_name": legal_name, "email": email})
    db.store.artists[record["id"]] = record
    return response.created(serializers.artist(record))


@bp.route("/artists/<record_id>", methods=["GET"])
def get_artist(record_id):
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS, ARTIST])
    record = find_artist(record_id)
    return response.ok(serializers.artist(record))


# ---------------------------------------------------------------------
# Stream rate cards (immutable)
# ---------------------------------------------------------------------

def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) windows; a null `to` runs forever."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


@bp.route("/stream-rate-cards", methods=["POST"])
def create_rate_card():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    dsp_code = v.dsp_code(body, "dsp_code", required=True)
    territory_code = v.territory(body, "territory_code", required=True)
    tier = v.enum(body, "tier", TIERS, required=True)
    rate = v.integer(body, "rate_micros_per_stream", required=True, minimum=1)
    effective_from = v.date_field(body, "effective_from", required=True)
    effective_to = v.date_field(body, "effective_to", required=False)
    if effective_to is not None and not effective_to > effective_from:
        v.bad("effective_to", "must be strictly after effective_from.")

    for existing in db.store.rate_cards.values():
        if existing["dsp_code"] != dsp_code:
            continue
        if existing["territory_code"] != territory_code:
            continue
        if existing["tier"] != tier:
            continue
        other_from = db.parse_date(existing["effective_from"])
        other_to = db.parse_date(existing["effective_to"]) \
            if existing["effective_to"] else None
        if _windows_overlap(effective_from, effective_to, other_from, other_to):
            raise ApiError("ERR_RATE_CARD_OVERLAP")

    record = db.base_record(mutable=False)
    record.update({
        "dsp_code": dsp_code,
        "territory_code": territory_code,
        "tier": tier,
        "rate_micros_per_stream": rate,
        "effective_from": db.date_str(effective_from),
        "effective_to": db.date_str(effective_to),
    })
    db.store.rate_cards[record["id"]] = record
    return response.created(serializers.rate_card(record))


@bp.route("/stream-rate-cards", methods=["GET"])
def list_rate_cards():
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS,
                  DISTRIBUTION_PARTNER])
    limit, offset = pagination()
    records = db.ordered(list(db.store.rate_cards.values()))
    for key in ("dsp_code", "territory_code", "tier"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.rate_card(r) for r in page], limit, offset, total
    )
