"""SoftwareModification endpoints (PRD 3.9).

Classification pins lead_time_days from PRE-cascade state (base 30, +60 when
component codes touch TABULATION_FIRMWARE/BALLOT_LAYOUT_ENGINE, +45 when a
FEDERAL certificate is ACTIVE/SUSPENDED, all evaluated before any suspension
fires). RECERTIFICATION_PENDING then fires the three-hop cascade; EFFECTIVE on
the recert path compensates (suspended certificates reinstate, cert_holds
clear) and requires a newer CERTIFIED campaign.
"""
from datetime import timedelta

from flask import Blueprint

from auth import auth_context, peek_to_state, require_role, require_transition_actor
from constants import (
    COMPONENT_CODES,
    MOD_BASE_LEAD_DAYS,
    MOD_FEDERAL_CERT_ADD_DAYS,
    MOD_SCOPE_TOUCHING_ADD_DAYS,
    SCOPE_TOUCHING_COMPONENTS,
)
from domains.systems import get_system_or_404
from envelope import apply_filters, list_page, ok_object
from errors import err_invalid_state, err_not_found, raise_err
from store import db
from util import now, stamp_new, touch
from validation import body_json, no_extra, req_enum, req_int, req_list, req_str

bp = Blueprint("modifications", __name__)

MOD_STATES = {"PROPOSED", "DE_MINIMIS_APPROVED", "RECERTIFICATION_PENDING", "EFFECTIVE", "REJECTED", "WITHDRAWN"}
MOD_ACTORS = {
    "DE_MINIMIS_APPROVED": {"CertificationAuthority"},
    "RECERTIFICATION_PENDING": {"CertificationAuthority"},
    "EFFECTIVE": {"VendorRep"},
    "REJECTED": {"CertificationAuthority"},
    "WITHDRAWN": {"VendorRep"},
}
MOD_FROM = {
    "DE_MINIMIS_APPROVED": {"PROPOSED"},
    "RECERTIFICATION_PENDING": {"PROPOSED"},
    "EFFECTIVE": {"DE_MINIMIS_APPROVED", "RECERTIFICATION_PENDING"},
    "REJECTED": {"PROPOSED", "DE_MINIMIS_APPROVED", "RECERTIFICATION_PENDING"},
    "WITHDRAWN": {"PROPOSED"},
}


@bp.post("/evote/software-modifications")
def create_modification():
    _, role = auth_context()
    require_role(role, {"VendorRep"})
    body = body_json()
    no_extra(body, {"voting_system_id", "description", "component_codes", "expected_voting_system_version"})
    system_id = req_str(body, "voting_system_id")
    description = req_str(body, "description")
    component_codes = req_list(body, "component_codes")
    if len(component_codes) == 0 or any(c not in COMPONENT_CODES for c in component_codes):
        raise_err("ERR_INVALID_REQUEST", 400, "component_codes must be a non-empty array of declared codes")
    expected = req_int(body, "expected_voting_system_version")
    system = db.voting_systems.get(system_id)
    if system is None:
        raise_err("ERR_SYSTEM_NOT_FOUND", 404, "voting_system_id does not resolve")
    if expected != system["version"]:
        raise_err("ERR_STALE_VERSION", 412, "expected_voting_system_version does not match")
    if system["status"] == "RETIRED":
        raise_err("ERR_SYSTEM_RETIRED", 422, "voting system is RETIRED")
    rec = stamp_new({})
    rec.update({
        "voting_system_id": system_id,
        "description": description,
        "component_codes": component_codes,
        "classification": None,
        "lead_time_days": None,
        "submitted_at": now(),
        "classified_at": None,
        "effective_at": None,
        "new_baseline_version": None,
        "status": "PROPOSED",
    })
    db.software_modifications[rec["id"]] = rec
    touch(system)  # proposing increments the voting system's version
    return ok_object(rec, 201)


@bp.get("/evote/voting-systems/<system_id>/software-modifications")
def list_system_modifications(system_id):
    auth_context()
    get_system_or_404(system_id)
    items = [m for m in db.software_modifications.values() if m["voting_system_id"] == system_id]
    items = apply_filters(items, {"status"})
    return list_page(items)


def get_modification_or_404(mod_id):
    mod = db.software_modifications.get(mod_id)
    if mod is None:
        err_not_found("software modification not found")
    return mod


def compute_lead_time_days(mod):
    """PRE-cascade evaluation: base + scope-touching + federal-certificate."""
    lead = MOD_BASE_LEAD_DAYS
    if set(mod["component_codes"]) & SCOPE_TOUCHING_COMPONENTS:
        lead += MOD_SCOPE_TOUCHING_ADD_DAYS
    has_federal = any(
        c["voting_system_id"] == mod["voting_system_id"]
        and c["scope"] == "FEDERAL"
        and c["status"] in {"ACTIVE", "SUSPENDED"}
        for c in db.certificates.values()
    )
    if has_federal:
        lead += MOD_FEDERAL_CERT_ADD_DAYS
    return lead


def recertification_cascade(mod):
    """Three-hop cascade fired only by the RECERTIFICATION_PENDING classify."""
    suspended_ids = []
    for cert in db.certificates.values():
        if cert["voting_system_id"] == mod["voting_system_id"] and cert["status"] == "ACTIVE":
            cert["status"] = "SUSPENDED"
            touch(cert)
            suspended_ids.append(cert["id"])
    reverted_definition_ids = []
    for definition in db.election_definitions.values():
        proc = db.procurements.get(definition["procurement_id"])
        if (
            proc is not None
            and proc["certificate_id"] in suspended_ids
            and definition["status"] in {"PROGRAMMED", "LA_PASSED"}
        ):
            definition["status"] = "DRAFT"
            definition["status_reason"] = "CERTIFICATE_SUSPENDED"
            touch(definition)
            reverted_definition_ids.append(definition["id"])
    for proc in db.procurements.values():
        if proc["certificate_id"] in suspended_ids and proc["status"] in {"DELIVERED", "ACCEPTANCE_TESTING"}:
            proc["cert_hold"] = True
            touch(proc)
    for test in db.logic_accuracy_tests.values():
        if test["election_definition_id"] in reverted_definition_ids and test["status"] == "CONDUCTED":
            test["status"] = "CHALLENGED"
            touch(test)


def effective_compensation(mod):
    """Recert path EFFECTIVE: reinstate suspended certs, clear cert holds."""
    for cert in db.certificates.values():
        if cert["voting_system_id"] == mod["voting_system_id"] and cert["status"] == "SUSPENDED":
            cert["status"] = "ACTIVE"
            touch(cert)
    for proc in db.procurements.values():
        if proc["voting_system_id"] == mod["voting_system_id"] and proc["cert_hold"]:
            proc["cert_hold"] = False
            touch(proc)


@bp.post("/evote/software-modifications/<mod_id>/transitions")
def modification_transition(mod_id):
    _, role = auth_context()
    require_role(role, {"VendorRep", "CertificationAuthority"})
    ts = peek_to_state()
    require_transition_actor(role, ts, MOD_ACTORS)
    mod = get_modification_or_404(mod_id)
    body = body_json()
    no_extra(body, {"to_state", "new_baseline_version"})
    to_state = req_enum(body, "to_state", MOD_STATES)
    new_baseline = None
    if to_state == "EFFECTIVE":
        new_baseline = body.get("new_baseline_version")
        if not isinstance(new_baseline, str) or new_baseline == "":
            raise_err("ERR_INVALID_REQUEST", 400, "new_baseline_version is required for EFFECTIVE")
    if to_state not in MOD_FROM or mod["status"] not in MOD_FROM[to_state]:
        err_invalid_state("modification cannot transition from %s to %s" % (mod["status"], to_state))
    if to_state == "EFFECTIVE":
        if now() < mod["classified_at"] + timedelta(days=mod["lead_time_days"]):
            raise_err("ERR_LEAD_TIME_NOT_ELAPSED", 422, "lead time has not elapsed")
        if mod["classification"] == "RECERTIFICATION_REQUIRED":
            recertified = any(
                c["voting_system_id"] == mod["voting_system_id"]
                and c["status"] == "CERTIFIED"
                and c["completed_at"] is not None
                and c["completed_at"] > mod["submitted_at"]
                for c in db.certification_campaigns.values()
            )
            if not recertified:
                raise_err(
                    "ERR_RECERTIFICATION_CAMPAIGN_REQUIRED", 422,
                    "no campaign CERTIFIED after this modification's submitted_at",
                )
    if to_state in {"DE_MINIMIS_APPROVED", "RECERTIFICATION_PENDING"}:
        # Lead time is computed strictly BEFORE the cascade mutates anything.
        lead = compute_lead_time_days(mod)
        mod["classification"] = "DE_MINIMIS" if to_state == "DE_MINIMIS_APPROVED" else "RECERTIFICATION_REQUIRED"
        mod["classified_at"] = now()
        mod["lead_time_days"] = lead
        if to_state == "RECERTIFICATION_PENDING":
            recertification_cascade(mod)
    elif to_state == "EFFECTIVE":
        system = db.voting_systems.get(mod["voting_system_id"])
        if system is not None:
            system["software_baseline_version"] = new_baseline
            touch(system)
        if mod["classification"] == "RECERTIFICATION_REQUIRED":
            effective_compensation(mod)
        mod["effective_at"] = now()
        mod["new_baseline_version"] = new_baseline
    # REJECTED (no compensation) and WITHDRAWN carry no side effects.
    mod["status"] = to_state
    touch(mod)
    return ok_object(mod, 200)
