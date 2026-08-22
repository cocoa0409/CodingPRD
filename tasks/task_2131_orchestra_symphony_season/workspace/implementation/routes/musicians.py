"""The musician roster."""

from flask import Blueprint

from db import db
from domain import base_fields, serialize
from errors import raise_err
from middleware import endpoint
from response import ok
from validate import body, check_body_fks, opt_bool, opt_int, req_enum, req_str

bp = Blueprint("musicians", __name__)

INSTRUMENTS = ("VIOLIN", "VIOLA", "CELLO", "BASS", "FLUTE", "OBOE", "CLARINET",
               "BASSOON", "HORN", "TRUMPET", "TROMBONE", "PERCUSSION", "HARP")


def get_musician_or_404(musician_id):
    musician = db.musicians.get(musician_id)
    if musician is None:
        raise_err("ERR_MUSICIAN_NOT_FOUND")
    return musician


@bp.route("/orchestra/musicians", methods=["POST"])
@endpoint(["OrchestraManager"])
def create_musician():
    data = body()
    check_body_fks(data, [])
    full_name = req_str(data, "full_name")
    instrument = req_enum(data, "instrument", INSTRUMENTS)
    is_principal = opt_bool(data, "is_principal", False)
    overscale = opt_int(data, "overscale_bp", 0, minv=0, maxv=10000)

    musician = base_fields()
    musician.update({
        "full_name": full_name,
        "instrument": instrument,
        "is_principal": is_principal,
        "overscale_bp": overscale,
        "services_charged_ytd": 0,
        "ytd_earnings_cents": 0,
    })
    db.musicians[musician["id"]] = musician
    return ok(serialize(musician), 201)


@bp.route("/orchestra/musicians/<musician_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "Musician"])
def read_musician(musician_id):
    return ok(serialize(get_musician_or_404(musician_id)))
