"""Price agreements: tiered pricing with volume breakpoints, half-open
effectiveness windows, buyer-consistency rules, and the distributor channel
price floor (PRD §3.5)."""

from flask import Blueprint, request

import auth
import calcs
import constants
import envelope
import serialization as ser
import store
import validation
from errors import api_err, invalid_request, not_found

bp = Blueprint("pricing", __name__)

TIERS = {"CONVERTER_AUTHORIZED", "DISTRIBUTOR_PREFERRED", "STANDARD"}


def _validate_breakpoints(payload):
    breakpoints = validation.opt_list(payload, "volume_breakpoints", [])
    cleaned = []
    for entry in breakpoints:
        if not isinstance(entry, dict):
            raise invalid_request("volume_breakpoints entries must be objects")
        min_qty = validation.req_int(entry, "min_qty")
        extra = validation.req_number(entry, "extra_discount_pct")
        cleaned.append({"min_qty": min_qty, "extra_discount_pct": extra})
    if len(cleaned) > constants.MAX_VOLUME_BREAKPOINTS:
        raise invalid_request(
            "volume_breakpoints may hold at most %d entries"
            % constants.MAX_VOLUME_BREAKPOINTS)
    for prev, curr in zip(cleaned, cleaned[1:]):
        if curr["min_qty"] < prev["min_qty"]:
            raise invalid_request(
                "volume_breakpoints must be sorted by min_qty ascending")
    return cleaned


def _buyer_ids(payload):
    converter_id = validation.opt_str(payload, "converter_id")
    distributor_id = validation.opt_str(payload, "distributor_id")
    if converter_id is None and distributor_id is None:
        # Both-absent surfaces at intake (shape tier) as 400.
        raise invalid_request(
            "Exactly one of converter_id / distributor_id must be set")
    return converter_id, distributor_id


@bp.post("/stewardship/price-agreements")
def create_price_agreement():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    payload = validation.get_payload()
    formulation_id = validation.req_str(payload, "formulation_id")
    jurisdiction_id = validation.req_str(payload, "jurisdiction_id")
    tier = validation.req_enum(payload, "tier", TIERS)
    base_price_cents = validation.req_int(payload, "base_price_cents")
    if base_price_cents <= 0:
        raise invalid_request("base_price_cents must be > 0")
    effective_from = validation.req_dt(payload, "effective_from")
    effective_to = validation.req_dt(payload, "effective_to")
    validation.check_half_open_window(effective_from, effective_to,
                                      "effective_from", "effective_to")
    breakpoints = _validate_breakpoints(payload)
    converter_id, distributor_id = _buyer_ids(payload)
    # Existence (tier 6): formulation, jurisdiction, and any buyer ids.
    if store.STORE["formulations"].get(formulation_id) is None:
        raise not_found("Formulation not found")
    if store.STORE["jurisdictions"].get(jurisdiction_id) is None:
        raise not_found("Jurisdiction not found")
    if (converter_id is not None
            and store.STORE["converters"].get(converter_id) is None):
        raise not_found("Converter not found")
    if (distributor_id is not None
            and store.STORE["distributors"].get(distributor_id) is None):
        raise not_found("Distributor not found")
    # Priority 16: window overlap for the same buyer + formulation (half-open).
    for existing in store.STORE["agreements"].values():
        same_buyer = (
            (converter_id is not None
             and existing["converter_id"] == converter_id)
            or (distributor_id is not None
                and existing["distributor_id"] == distributor_id))
        if (same_buyer
                and existing["formulation_id"] == formulation_id
                and validation.windows_overlap(
                    existing["effective_from"], existing["effective_to"],
                    effective_from, effective_to)):
            raise api_err(
                "ERR_AGREEMENT_WINDOW_OVERLAP",
                "Price agreement window overlaps an existing agreement for "
                "this buyer and formulation")
    # Priority 17: buyer identity consistency with the tier.
    if converter_id is not None and distributor_id is not None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "Both converter_id and distributor_id were supplied")
    if tier == "CONVERTER_AUTHORIZED" and converter_id is None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "CONVERTER_AUTHORIZED tier requires a converter buyer")
    if tier == "DISTRIBUTOR_PREFERRED" and distributor_id is None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "DISTRIBUTOR_PREFERRED tier requires a distributor buyer")
    # Priority 25: distributor channel price floor.
    if distributor_id is not None:
        if calcs.channel_floor_violation(
                formulation_id, jurisdiction_id, tier, base_price_cents,
                breakpoints, effective_from, effective_to):
            raise api_err(
                "ERR_CHANNEL_FLOOR_VIOLATION",
                "Distributor agreement's worst-case unit price is below the "
                "channel floor")
    row = store.stamp_new({
        "formulation_id": formulation_id,
        "jurisdiction_id": jurisdiction_id,
        "converter_id": converter_id,
        "distributor_id": distributor_id,
        "tier": tier,
        "base_price_cents": base_price_cents,
        "volume_breakpoints": breakpoints,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    store.STORE["agreements"][row["id"]] = row
    return envelope.success_object(ser.price_agreement(row), 201)


@bp.get("/stewardship/price-agreements/<aid>")
def get_price_agreement(aid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    row = store.STORE["agreements"].get(aid)
    if row is None:
        raise not_found("PriceAgreement not found")
    return envelope.success_object(ser.price_agreement(row), 200)


@bp.get("/stewardship/price-agreements")
def list_price_agreements():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["agreements"].values(), request.args,
        ["formulation_id", "jurisdiction_id", "converter_id", "distributor_id"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.price_agreement(r) for r in page], len(rows), limit, offset)
