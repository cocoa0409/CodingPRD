"""Life-path routes: preservation, donation and surrogacy (PRD 3.8)."""

from body import body, opt, require
from bp import api
from clock import parse_dt
from db import db
from errors import APIError
from helpers import employer_of_member, recompute_member
from calculations import pathway_coverage_rule
from listing import apply_filters, ordered, paginate

from middleware import require_member_ownership, resolve_actor
from response import ok, created
from serializers import serialize


@api.route("/pathway-requests", methods=["POST"])
def create_pathway_request():
    actor = resolve_actor()
    data = body()
    member_id = require(data, "member_id")
    pathway_type = require(data, "pathway_type")
    if pathway_type not in ("PRESERVATION", "DONOR_EGG", "DONOR_SPERM", "SURROGACY"):
        raise APIError("ERR_INVALID_REQUEST", "pathway_type is outside its declared enumeration.")

    member = db.find("members", member_id)
    if member is None:
        raise APIError("ERR_NOT_FOUND", "The member_id does not resolve.")

    consent_signed = bool(opt(data, "consent_signed", False))
    consent_signed_on = opt(data, "consent_signed_on")
    coverage_pct = opt(data, "coverage_pct", 0)
    gestational_carrier_ref = opt(data, "gestational_carrier_ref")
    donor_agency_ref = opt(data, "donor_agency_ref")

    # Pathway-specific references, required only for their own enumeration member.
    if pathway_type == "SURROGACY" and not gestational_carrier_ref:
        raise APIError("ERR_SURROGACY_CARRIER_REQUIRED",
                       "A SURROGACY request requires gestational_carrier_ref.")
    if pathway_type in ("DONOR_EGG", "DONOR_SPERM") and not donor_agency_ref:
        raise APIError("ERR_DONOR_AGENCY_REQUIRED",
                       "A donor pathway requires donor_agency_ref.")

    row = db.common()
    row.update({
        "_collection": "pathway_requests",
        "member_id": member_id,
        "care_advocate_id": member.get("care_advocate_id") or actor.user_id,
        "pathway_type": pathway_type,
        "pathway_status": "DRAFT",
        "consent_signed": consent_signed,
        "consent_signed_on": parse_dt(consent_signed_on) if consent_signed_on else None,
        "gestational_carrier_ref": gestational_carrier_ref,
        "donor_agency_ref": donor_agency_ref,
        "coverage_pct": coverage_pct,
        "pathway_cost_cents": 0,
    })
    db.add(row)
    return created(serialize("pathway_requests", row))


@api.route("/pathway-requests/<request_id>", methods=["GET"])
def get_pathway_request(request_id):
    actor = resolve_actor()
    row = db.find("pathway_requests", request_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The pathway request does not resolve.")
    require_member_ownership(actor, row["member_id"])
    return ok(serialize("pathway_requests", row))


@api.route("/pathway-requests", methods=["GET"])
def list_pathway_requests():
    actor = resolve_actor()
    rows = ordered(db.all("pathway_requests"))
    if actor.role == "Member":
        rows = [r for r in rows if r["member_id"] == actor.user_id]
    rows = apply_filters(rows, {
        "member_id": "member_id",
        "care_advocate_id": "care_advocate_id",
        "pathway_type": "pathway_type",
        "pathway_status": "pathway_status",
    })
    return paginate(rows, "pathway_requests")


@api.route("/pathway-requests/<request_id>/begin-clinical-review", methods=["POST"])
def begin_pathway_review(request_id):
    resolve_actor()
    row = db.find("pathway_requests", request_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The pathway request does not resolve.")

    if row["pathway_status"] not in ("DRAFT", "DENIED"):
        raise APIError("ERR_INVALID_STATE", "The request is not DRAFT or DENIED.")

    if row["pathway_status"] == "DRAFT":
        if not row.get("consent_signed") or row.get("consent_signed_on") is None:
            raise APIError("ERR_INVALID_STATE", "The pathway-specific consent packet is incomplete.")
        if row["pathway_type"] == "SURROGACY" and not row.get("gestational_carrier_ref"):
            raise APIError("ERR_INVALID_STATE", "A SURROGACY request requires a carrier reference.")
        if row["pathway_type"] in ("DONOR_EGG", "DONOR_SPERM") and not row.get("donor_agency_ref"):
            raise APIError("ERR_INVALID_STATE", "A donor pathway requires an agency reference.")

    row["pathway_status"] = "CLINICAL_REVIEW"
    db.touch(row)
    return ok(serialize("pathway_requests", row))


@api.route("/pathway-requests/<request_id>/decide", methods=["POST"])
def decide_pathway_request(request_id):
    resolve_actor()
    row = db.find("pathway_requests", request_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The pathway request does not resolve.")

    if row["pathway_status"] != "CLINICAL_REVIEW":
        raise APIError("ERR_INVALID_STATE", "The request is not in CLINICAL_REVIEW.")

    data = body()
    decision = require(data, "decision")
    if decision not in ("APPROVE", "DENY"):
        raise APIError("ERR_INVALID_REQUEST", "The decision is outside its declared enumeration.")

    member = db.find("members", row["member_id"])
    account = employer_of_member(db, member) if member is not None else None

    if decision == "DENY":
        row["pathway_status"] = "DENIED"
        db.touch(row)
        return ok(serialize("pathway_requests", row))

    if account is None or account["account_status"] != "ACTIVE":
        raise APIError("ERR_BENEFIT_INACTIVE", "The sponsoring account is not ACTIVE.")

    row["pathway_status"] = "APPROVED"
    row["pathway_cost_cents"] = pathway_coverage_rule(row["pathway_type"], row.get("coverage_pct"))
    db.touch(row)

    if member is not None:
        recompute_member(db, member)
    return ok(serialize("pathway_requests", row))


@api.route("/pathway-requests/<request_id>/activate", methods=["POST"])
def activate_pathway(request_id):
    resolve_actor()
    row = db.find("pathway_requests", request_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The pathway request does not resolve.")
    if row["pathway_status"] != "APPROVED":
        raise APIError("ERR_INVALID_STATE", "The request is not APPROVED.")

    member = db.find("members", row["member_id"])
    account = employer_of_member(db, member) if member is not None else None
    if account is None or account["account_status"] != "ACTIVE":
        raise APIError("ERR_BENEFIT_INACTIVE", "The sponsoring account is not ACTIVE.")

    row["pathway_status"] = "ACTIVE"
    db.touch(row)
    if member is not None:
        recompute_member(db, member)
    return ok(serialize("pathway_requests", row))


@api.route("/pathway-requests/<request_id>/complete", methods=["POST"])
def complete_pathway(request_id):
    resolve_actor()
    row = db.find("pathway_requests", request_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The pathway request does not resolve.")
    if row["pathway_status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", "The request is not ACTIVE.")

    row["pathway_status"] = "COMPLETED"
    db.touch(row)
    member = db.find("members", row["member_id"])
    if member is not None:
        recompute_member(db, member)
    return ok(serialize("pathway_requests", row))


@api.route("/pathway-requests/<request_id>/withdraw", methods=["POST"])
def withdraw_pathway(request_id):
    resolve_actor()
    row = db.find("pathway_requests", request_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The pathway request does not resolve.")
    if row["pathway_status"] not in ("DRAFT", "CLINICAL_REVIEW", "APPROVED", "ACTIVE"):
        raise APIError("ERR_INVALID_STATE", "The request may not be withdrawn from its current state.")

    row["pathway_status"] = "WITHDRAWN"
    db.touch(row)
    member = db.find("members", row["member_id"])
    if member is not None:
        recompute_member(db, member)
    return ok(serialize("pathway_requests", row))