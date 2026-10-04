"""Counterfeit reporting and disposition (PRD §3.9). A CONFIRMED_COUNTERFEIT
disposition fires the confirmation sweep; CLEARED_GENUINE / INCONCLUSIVE run
the release rule."""

from flask import Blueprint, request

import auth
import cascades
import envelope
import serialization as ser
import store
import validation
from errors import invalid_state, not_found

bp = Blueprint("counterfeit", __name__)

OUTCOMES = {"CONFIRMED_COUNTERFEIT", "CLEARED_GENUINE", "INCONCLUSIVE"}


def _get_report(rid):
    row = store.STORE["reports"].get(rid)
    if row is None:
        raise not_found("CounterfeitReport not found")
    return row


@bp.post("/stewardship/counterfeit-reports")
def create_report():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["Converter", "Distributor", "QualityAuditor"])
    payload = validation.get_payload()
    formulation_id = validation.req_str(payload, "formulation_id")
    lot_code = validation.req_str(payload, "lot_code")
    channel_description = validation.req_str(payload, "channel_description")
    implicated = validation.opt_str(payload, "implicated_converter_id")
    if store.STORE["formulations"].get(formulation_id) is None:
        raise not_found("Formulation not found")
    if (implicated is not None
            and store.STORE["converters"].get(implicated) is None):
        raise not_found("Implicated converter not found")
    row = store.stamp_new({
        "formulation_id": formulation_id,
        "lot_code": lot_code,
        "channel_description": channel_description,
        "implicated_converter_id": implicated,
        "reporter_role": role,
        "status": "REPORTED",
        "investigator_note": None,
    })
    store.STORE["reports"][row["id"]] = row
    return envelope.success_object(ser.counterfeit_report(row), 201)


@bp.get("/stewardship/counterfeit-reports/<rid>")
def get_report(rid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.counterfeit_report(_get_report(rid)), 200)


@bp.get("/stewardship/counterfeit-reports")
def list_reports():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["reports"].values(), request.args,
        ["formulation_id", "implicated_converter_id", "status"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.counterfeit_report(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/counterfeit-reports/<rid>/disposition")
def disposition_report(rid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["QualityAuditor"])
    payload = validation.get_payload()
    outcome = validation.req_enum(payload, "outcome", OUTCOMES)
    note = validation.opt_str(payload, "investigator_note")
    report = _get_report(rid)
    if report["status"] != "REPORTED":
        raise invalid_state(
            "Only a REPORTED report can be dispositioned")
    report["status"] = outcome
    if note is not None:
        report["investigator_note"] = note
    store.touch(report)
    if outcome == "CONFIRMED_COUNTERFEIT":
        cascades.counterfeit_confirmed_sweep(report)
    else:
        cascades.counterfeit_release_sweep(report)
    return envelope.success_object(ser.counterfeit_report(report), 200)
