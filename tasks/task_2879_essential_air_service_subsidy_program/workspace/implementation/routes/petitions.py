"""Termination petitions, the hold-in requirement and agreement release (PRD 3.9)."""

from flask import Blueprint, request

import auth
import cascades
import errors
import lookups
import response
import serializers
import validation as v
from auth import (CARRIER, COMMUNITY_REPRESENTATIVE, PROGRAM_ADMIN,
                  SELECTION_OFFICER, endpoint)
from db import base_row, by_seq, fmt_ts, now_iso, store, touch

bp = Blueprint("petitions", __name__)

REASON_CODES = ("SERVICE_QUALITY", "COMMUNITY_PREFERENCE_CHANGE",
                "CARRIER_NONPERFORMANCE", "AIRPORT_CLOSURE")
DECISION_ACTIONS = ("OPEN_REVIEW", "RETURN_FOR_INFO", "GRANT_WITH_HOLD_IN",
                    "GRANT_IMMEDIATE", "DENY")
WITHDRAWABLE = ("FILED", "UNDER_REVIEW")


@bp.route("/termination-petitions", methods=["POST"])
@endpoint(COMMUNITY_REPRESENTATIVE)
def create_petition():
    data = v.body()
    community_id = v.id_field(data, "community_id")
    agreement_id = v.id_field(data, "agreement_id")
    reason_code = v.enum_field(data, "reason_code", REASON_CODES)
    narrative = v.str_field(data, "narrative", min_len=1, max_len=2000)
    requested_effective_at = v.datetime_field(data, "requested_effective_at")

    community = lookups.community(community_id)
    agreement = lookups.agreement(agreement_id)

    auth.require_owner(community["id"])
    auth.require_owner(agreement["community_id"])

    petition = base_row(True)
    petition.update({
        "community_id": community["id"],
        "agreement_id": agreement["id"],
        "reason_code": reason_code,
        "narrative": narrative,
        "requested_effective_at": fmt_ts(requested_effective_at),
        "status": "FILED",
        "return_count": 0,
        "decision_note": None,
        "decided_by_user_id": None,
        "filed_by_user_id": auth.user_id(),
    })
    store.petitions[petition["id"]] = petition
    return response.created(serializers.petition(petition))


@bp.route("/termination-petitions/<tid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def read_petition(tid):
    return response.ok(serializers.petition(lookups.petition(tid)))


@bp.route("/termination-petitions", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def list_petitions():
    rows = list(store.petitions.values())
    for field in ("community_id", "agreement_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return response.paginate(by_seq(rows), serializers.petition)


@bp.route("/termination-petitions/<tid>/decision", methods=["POST"])
@endpoint(SELECTION_OFFICER)
def petition_decision(tid):
    data = v.body()
    action = v.enum_field(data, "action", DECISION_ACTIONS)
    decision_note = v.str_field(data, "decision_note", required=False, min_len=0,
                                max_len=2000)
    petition = lookups.petition(tid)
    status = petition["status"]

    if action == "OPEN_REVIEW":
        if status != "FILED":
            errors.fail(errors.ERR_PETITION_NOT_DECIDABLE,
                        "Only a FILED petition may be opened for review.")
        petition["status"] = "UNDER_REVIEW"
        touch(petition)
        return response.ok(serializers.petition(petition))

    if status != "UNDER_REVIEW":
        errors.fail(errors.ERR_PETITION_NOT_DECIDABLE,
                    "A petition in status %s does not admit this decision." % status)

    if action == "RETURN_FOR_INFO":
        petition["status"] = "FILED"
        petition["return_count"] = petition["return_count"] + 1
        petition["decision_note"] = decision_note
        touch(petition)
        return response.ok(serializers.petition(petition))

    if action == "DENY":
        petition["status"] = "DENIED"
        petition["decision_note"] = decision_note
        petition["decided_by_user_id"] = auth.user_id()
        touch(petition)
        return response.ok(serializers.petition(petition))

    # --- the two grant branches -------------------------------------------
    agreement = lookups.agreement(petition["agreement_id"])
    if agreement["status"] != "ACTIVE":
        errors.fail(errors.ERR_AGREEMENT_NOT_ACTIVE,
                    "An agreement in status %s may not be granted for termination."
                    % agreement["status"])
    community = lookups.community(petition["community_id"])

    if action == "GRANT_IMMEDIATE":
        other_active = [a for a in lookups.agreements_of_community(community["id"])
                        if a["id"] != agreement["id"] and a["status"] == "ACTIVE"]
        if petition["reason_code"] != "AIRPORT_CLOSURE" and not other_active:
            errors.fail(errors.ERR_HOLD_IN_REQUIRED,
                        "The community may not be left without air service.")
        petition["status"] = "GRANTED_IMMEDIATE"
        petition["decision_note"] = decision_note
        petition["decided_by_user_id"] = auth.user_id()
        touch(petition)

        agreement["status"] = "TERMINATED"
        agreement["terminated_at"] = now_iso()
        touch(agreement)

        cascades.decrement_active_agreements(community)
        cascades.settle_community_after_release(community)
        touch(community)
        return response.ok(serializers.petition(petition))

    # GRANT_WITH_HOLD_IN
    petition["status"] = "GRANTED_WITH_HOLD_IN"
    petition["decision_note"] = decision_note
    petition["decided_by_user_id"] = auth.user_id()
    touch(petition)

    agreement["status"] = "HOLD_IN"
    touch(agreement)

    if community["status"] == "SUBSIDIZED":
        community["status"] = "HOLD_IN"
    cascades.decrement_active_agreements(community)
    touch(community)

    cascades.open_replacement_solicitation(community["id"])
    return response.ok(serializers.petition(petition))


@bp.route("/termination-petitions/<tid>/withdraw", methods=["POST"])
@endpoint(COMMUNITY_REPRESENTATIVE)
def withdraw_petition(tid):
    data = v.body(required=False)
    v.str_field(data, "withdraw_note", required=False, min_len=0, max_len=2000)
    petition = lookups.petition(tid)

    auth.require_owner(petition["community_id"])

    if petition["status"] not in WITHDRAWABLE:
        errors.fail(errors.ERR_PETITION_NOT_DECIDABLE,
                    "A petition in status %s may not be withdrawn."
                    % petition["status"])

    petition["status"] = "WITHDRAWN"
    touch(petition)
    return response.ok(serializers.petition(petition))
