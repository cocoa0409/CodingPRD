"""Converter onboarding, quality audit, capability authorizations, and
distributor onboarding (PRD §3.3)."""

from flask import Blueprint, request

import auth
import cascades
import constants
import envelope
import serialization as ser
import store
import validation
from errors import api_err, invalid_request, invalid_state, not_found, stale_version

bp = Blueprint("converters", __name__)

CAPABILITIES = {"SLITTING", "DIE_CUTTING", "LAMINATION"}


def _get_converter(cid):
    row = store.STORE["converters"].get(cid)
    if row is None:
        raise not_found("Converter not found")
    return row


@bp.post("/stewardship/converters")
def create_converter():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    payload = validation.get_payload()
    row = store.stamp_new({
        "name": validation.req_str(payload, "name"),
        "home_territory_code": validation.req_str(payload, "home_territory_code"),
        "status": "APPLIED",
        "quality_audit_score": None,
        "audit_standard": None,
        "audited_by": None,
    })
    store.STORE["converters"][row["id"]] = row
    return envelope.success_object(ser.converter(row), 201)


@bp.get("/stewardship/converters/<cid>")
def get_converter(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.converter(_get_converter(cid)), 200)


@bp.post("/stewardship/converters/<cid>/record-audit")
def record_audit(cid):
    uid, role = auth.authenticate()
    auth.require_role(role, ["QualityAuditor"])
    payload = validation.get_payload()
    score = validation.req_int(payload, "audit_score")
    if score < 0 or score > 100:
        raise invalid_request("audit_score must be between 0 and 100")
    standard = validation.req_str(payload, "audit_standard")
    converter = _get_converter(cid)
    if converter["status"] != "APPLIED":
        raise invalid_state("Only an APPLIED converter can record an audit")
    converter["quality_audit_score"] = score
    converter["audit_standard"] = standard
    converter["audited_by"] = uid
    converter["status"] = "AUDIT_RECORDED"
    store.touch(converter)
    return envelope.success_object(ser.converter(converter), 200)


@bp.post("/stewardship/converters/<cid>/authorize")
def authorize_converter(cid):
    uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    converter = _get_converter(cid)
    # Tier 4 segregation of duties: the recording auditor may not authorize.
    if converter["audited_by"] is not None and uid == converter["audited_by"]:
        raise api_err("ERR_SEGREGATION_OF_DUTIES",
                      "The auditor who recorded the audit may not authorize")
    if converter["status"] != "AUDIT_RECORDED":
        raise invalid_state("Only an AUDIT_RECORDED converter can be authorized")
    # Priority 20: minimum audit score (75, inclusive).
    if converter["quality_audit_score"] < constants.MIN_AUDIT_SCORE:
        raise api_err("ERR_AUDIT_SCORE_INSUFFICIENT",
                      "quality_audit_score must be at least %d"
                      % constants.MIN_AUDIT_SCORE)
    converter["status"] = "AUTHORIZED"
    store.touch(converter)
    return envelope.success_object(ser.converter(converter), 200)


@bp.post("/stewardship/converters/<cid>/suspend")
def suspend_converter(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    converter = _get_converter(cid)
    if converter["status"] != "AUTHORIZED":
        raise invalid_state("Only an AUTHORIZED converter can be suspended")
    converter["status"] = "SUSPENDED"
    store.touch(converter)
    # Cascade: in-flight orders flagged; no report caused this, so
    # flagged_by_report_id stays null.
    cascades.cascade_converter_suspension(converter["id"], report_id=None)
    return envelope.success_object(ser.converter(converter), 200)


@bp.post("/stewardship/converters/<cid>/reinstate")
def reinstate_converter(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    converter = _get_converter(cid)
    if converter["status"] != "SUSPENDED":
        raise invalid_state("Only a SUSPENDED converter can be reinstated")
    converter["status"] = "AUTHORIZED"
    store.touch(converter)
    # Deliberate asymmetry: reinstatement does NOT unflag orders.
    return envelope.success_object(ser.converter(converter), 200)


@bp.post("/stewardship/distributors")
def create_distributor():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    payload = validation.get_payload()
    row = store.stamp_new({
        "name": validation.req_str(payload, "name"),
        "home_territory_code": validation.req_str(payload, "home_territory_code"),
    })
    store.STORE["distributors"][row["id"]] = row
    return envelope.success_object(ser.distributor(row), 201)


@bp.get("/stewardship/distributors/<did>")
def get_distributor(did):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    row = store.STORE["distributors"].get(did)
    if row is None:
        raise not_found("Distributor not found")
    return envelope.success_object(ser.distributor(row), 200)


@bp.post("/stewardship/converter-authorizations")
def create_authorization():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    payload = validation.get_payload()
    converter_id = validation.req_str(payload, "converter_id")
    capability = validation.req_enum(payload, "capability", CAPABILITIES)
    territory_code = validation.req_str(payload, "territory_code")
    valid_from = validation.req_dt(payload, "valid_from")
    valid_to = validation.req_dt(payload, "valid_to")
    expected = validation.req_int(payload, "expected_converter_version")
    validation.check_half_open_window(valid_from, valid_to,
                                      "valid_from", "valid_to")
    converter = store.STORE["converters"].get(converter_id)
    if converter is None:
        raise not_found("Converter not found")
    if expected != converter["version"]:
        raise stale_version(
            "expected_converter_version does not match the converter's current "
            "version")
    # Priority 15: window overlap on the same (converter, capability,
    # territory) triple — half-open, adjacency allowed. Evaluated before the
    # converter-standing check (priority 18).
    for existing in store.STORE["authorizations"].values():
        if (existing["converter_id"] == converter_id
                and existing["capability"] == capability
                and existing["territory_code"] == territory_code
                and validation.windows_overlap(
                    existing["valid_from"], existing["valid_to"],
                    valid_from, valid_to)):
            raise api_err(
                "ERR_AUTHORIZATION_WINDOW_OVERLAP",
                "Authorization window overlaps an existing authorization for "
                "this (converter, capability, territory)")
    # Priority 18: the converter must currently be AUTHORIZED.
    if converter["status"] != "AUTHORIZED":
        raise api_err("ERR_CONVERTER_NOT_AUTHORIZED",
                      "Converter must be AUTHORIZED to receive authorizations")
    row = store.stamp_new({
        "converter_id": converter_id,
        "capability": capability,
        "territory_code": territory_code,
        "valid_from": valid_from,
        "valid_to": valid_to,
    })
    store.STORE["authorizations"][row["id"]] = row
    # Cross-entity bump: granting an authorization mutates the converter.
    store.touch(converter)
    return envelope.success_object(ser.authorization(row), 201)


@bp.get("/stewardship/converter-authorizations/<aid>")
def get_authorization(aid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    row = store.STORE["authorizations"].get(aid)
    if row is None:
        raise not_found("ConverterAuthorization not found")
    return envelope.success_object(ser.authorization(row), 200)


@bp.get("/stewardship/converter-authorizations")
def list_authorizations():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["authorizations"].values(), request.args,
        ["converter_id", "capability", "territory_code"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.authorization(r) for r in page], len(rows), limit, offset)
