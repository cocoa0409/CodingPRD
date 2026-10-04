"""Media tests: long-form video / infomercial tests with the provisional vs
settled MER dual-variant calculation and the scale-or-kill decision band."""

from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from constants import CONSTANTS
from errors import ApiError
from serializers import ser_media
from services import (get_or_404, posture_gate, req_fk, season_of_variant)
from state import DB, base_fields, bump, now, touch
from util import body, fmt_iso, ok_object, q0int, q4, req_enum, req_int, req_string

bp = Blueprint("media", __name__)

BUYER = ("MediaBuyer",)

_AIRABLE_LIFECYCLES = ("TOOLED", "DR_TESTING", "RETAIL_LIVE")


@bp.post("/media-tests")
def create_media_test():
    require_roles(BUYER)
    data = body()
    variant = req_fk(data, "variant_id", DB.variants, "ERR_VARIANT_NOT_FOUND")
    title = req_string(data, "title")
    spend = req_int(data, "media_spend_cents", min_v=1)
    posture_gate(season_of_variant(variant))
    if variant["lifecycle"] not in _AIRABLE_LIFECYCLES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "media tests require a TOOLED, DR_TESTING, or RETAIL_LIVE variant")
    m = base_fields()
    m.update({
        "variant_id": variant["id"],
        "title": title,
        "media_spend_cents": spend,
        "status": "EDITING",
        "projected_gross_cents": None,
        "provisional_mer": None,
        "order_lines": None,
        "settled_mer": None,
        "aired_at": None,
        "aired_dt": None,
        "decided_at": None,
        "decided_dt": None,
    })
    DB.media_tests[m["id"]] = m
    return ok_object(ser_media(m), 201)


@bp.post("/media-tests/<mid>/air")
def air_media_test(mid):
    require_roles(BUYER)
    m = get_or_404(DB.media_tests, mid, "ERR_MEDIA_TEST_NOT_FOUND")
    variant = get_or_404(DB.variants, m["variant_id"], "ERR_VARIANT_NOT_FOUND")
    # posture first (priority 4): GUARDED throttles exactly this operation
    posture_gate(season_of_variant(variant), air=True)
    if m["status"] != "EDITING":
        raise ApiError("ERR_INVALID_STATE", 409, "only an EDITING test can air")
    if variant["lifecycle"] not in _AIRABLE_LIFECYCLES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "the variant is no longer in an airable lifecycle state")
    if variant["claim_clearance"] != "SUBSTANTIATED":
        raise ApiError("ERR_CLAIM_NOT_SUBSTANTIATED", 422,
                       "the variant's claim clearance is not SUBSTANTIATED")
    projected = req_int(body(), "projected_gross_cents", min_v=0)
    ts = now()
    m["projected_gross_cents"] = projected
    m["provisional_mer"] = q4(Decimal(projected) / Decimal(m["media_spend_cents"]))
    m["aired_at"] = fmt_iso(ts)
    m["aired_dt"] = ts
    m["status"] = "AIRING"
    bump(m)
    if variant["lifecycle"] == "TOOLED":
        # airing a freshly-tooled variant advances it into DR testing
        variant["lifecycle"] = "DR_TESTING"
        touch(variant)  # cross-entity side effect; no ModelVariant version bump
    return ok_object(ser_media(m))


def _parse_order_lines(data):
    lines = data.get("order_lines")
    if not isinstance(lines, list) or not lines:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "order_lines must be a non-empty array")
    parsed = []
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "each order line must be an object")
        parsed.append({
            "revenue_cents": req_int(line, "revenue_cents", min_v=0),
            "cancels_cents": req_int(line, "cancels_cents", min_v=0),
            "returns_cents": req_int(line, "returns_cents", min_v=0),
        })
    return parsed


@bp.post("/media-tests/<mid>/decide")
def decide_media_test(mid):
    require_roles(BUYER)
    m = get_or_404(DB.media_tests, mid, "ERR_MEDIA_TEST_NOT_FOUND")
    posture_gate(season_of_variant(DB.variants.get(m["variant_id"])))
    if m["status"] != "AIRING":
        raise ApiError("ERR_INVALID_STATE", 409, "only an AIRING test can be decided")
    data = body()
    decision = req_enum(data, "decision", ("SCALE", "KILL"))
    lines = _parse_order_lines(data)
    # pinned rounding order: per-line commission rounded to whole cents first,
    # per-line results summed, only the final ratio rounded to 4dp
    commission_keep = Decimal(1) - Decimal(CONSTANTS["AGENCY_COMMISSION_RATE"])
    total = 0
    for line in lines:
        net = line["revenue_cents"] - line["cancels_cents"] - line["returns_cents"]
        total += q0int(Decimal(net) * commission_keep)
    settled = q4(Decimal(total) / Decimal(m["media_spend_cents"]))
    scale_ok = settled >= Decimal(CONSTANTS["MER_SCALE_MIN"])
    if decision == "SCALE" and not scale_ok:
        raise ApiError("ERR_DECISION_BAND_MISMATCH", 422,
                       "SCALE requires settled MER >= the band minimum")
    if decision == "KILL" and scale_ok:
        raise ApiError("ERR_DECISION_BAND_MISMATCH", 422,
                       "KILL requires settled MER below the band minimum")
    ts = now()
    m["order_lines"] = lines
    m["settled_mer"] = settled
    m["decided_at"] = fmt_iso(ts)
    m["decided_dt"] = ts
    m["status"] = "DECIDED_SCALE" if decision == "SCALE" else "KILLED"
    bump(m)
    return ok_object(ser_media(m))
