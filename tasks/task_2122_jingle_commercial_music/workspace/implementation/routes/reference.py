"""Standing reference data and the logical clock (PRD 3.1, 2.4)."""

from flask import Blueprint

import clock
import db
import licensing
import response
import validators as v
from auth import endpoint

bp = Blueprint("reference", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["MusicHouseProducer", "RightsAdmin", "AFMSteward"])
def set_clock():
    body = v.get_body()
    _raw, target = v.v_datetime(body, "to_iso8601")
    clock.set_now(target)
    moved, lapsed = licensing.renewal_sweep(clock.now())
    return response.ok({
        "current_utc": clock.now_iso(),
        "licenses_moved_to_renewal_due": moved,
        "licenses_lapsed": lapsed,
    })


@bp.post("/clients")
@endpoint(["MusicHouseProducer"])
def create_client():
    body = v.get_body()
    name = v.v_string(body, "name")
    agency_code = v.v_string(body, "agency_code", min_len=1, max_len=16)
    billing_email = v.v_string(body, "billing_email")
    for existing in db.clients.values():
        if existing["agency_code"] == agency_code:
            raise v.invalid("agency_code must be unique across all clients.")
    record = db.create(db.clients, {
        "name": name,
        "agency_code": agency_code,
        "billing_email": billing_email,
    })
    return response.created(db.serialize(record))


@bp.post("/composers")
@endpoint(["MusicHouseProducer"])
def create_composer():
    body = v.get_body()
    display_name = v.v_string(body, "display_name")
    pro_affiliation = v.v_enum(body, "pro_affiliation", ("ASCAP", "BMI", "SESAC", "NONE"))
    record = db.create(db.composers, {
        "display_name": display_name,
        "pro_affiliation": pro_affiliation,
    })
    return response.created(db.serialize(record))


@bp.post("/musicians")
@endpoint(["MusicHouseProducer"])
def create_musician():
    body = v.get_body()
    full_name = v.v_string(body, "full_name")
    instrument = v.v_string(body, "instrument")
    scale_hourly_cents = v.v_int(body, "scale_hourly_cents", minimum=1)
    record = db.create(db.musicians, {
        "full_name": full_name,
        "instrument": instrument,
        "scale_hourly_cents": scale_hourly_cents,
        "afm_member_status": "NON_UNION",
    })
    return response.created(db.serialize(record))


@bp.post("/musicians/<musician_id>/afm-clearance")
@endpoint(["AFMSteward"])
def set_afm_clearance(musician_id):
    musician = v.path_lookup(db.musicians, musician_id, "ERR_MUSICIAN_NOT_FOUND")
    body = v.get_body()
    status = v.v_enum(body, "afm_member_status", ("SIGNATORY_CLEARED", "NON_UNION", "SUSPENDED"))
    if musician["afm_member_status"] != status:
        musician["afm_member_status"] = status
        db.touch(musician)
    return response.ok(db.serialize(musician))


@bp.post("/studio-rooms")
@endpoint(["MusicHouseProducer"])
def create_studio_room():
    body = v.get_body()
    name = v.v_string(body, "name")
    hourly_rate_cents = v.v_int(body, "hourly_rate_cents", minimum=1)
    capacity_players = v.v_int(body, "capacity_players", minimum=1)
    status = v.v_enum(body, "status", ("ACTIVE", "MAINTENANCE"), required=False, default="ACTIVE")
    record = db.create(db.studio_rooms, {
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
        "capacity_players": capacity_players,
        "status": status,
    })
    return response.created(db.serialize(record))


@bp.post("/library-tracks")
@endpoint(["MusicHouseProducer"])
def create_library_track():
    body = v.get_body()
    title = v.v_string(body, "title")
    blanket_fee_cents = v.v_int(body, "blanket_fee_cents", minimum=0)
    per_market_fee_cents = v.v_int(body, "per_market_fee_cents", minimum=0)
    max_markets = v.v_int(body, "max_markets", minimum=1)
    min_length_seconds = v.v_int(body, "min_length_seconds", minimum=1)
    status = v.v_enum(body, "status", ("ACTIVE", "RETIRED"), required=False, default="ACTIVE")
    record = db.create(db.library_tracks, {
        "title": title,
        "blanket_fee_cents": blanket_fee_cents,
        "per_market_fee_cents": per_market_fee_cents,
        "max_markets": max_markets,
        "min_length_seconds": min_length_seconds,
        "status": status,
    })
    return response.created(db.serialize(record))
