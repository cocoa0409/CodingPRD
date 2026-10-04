from flask import Blueprint, request

import auth
import store
from domain import (
    ser_case, ser_service_record, ser_evidence,
    recompute_household, recompute_member_matrix, matrix_response,
    VALID_CATEGORIES,
)
from envelope import success
from errors import err
from helpers import (
    new_row, touch, require_field, optional_field, require_enum, optional_enum,
    require_date, optional_date, optional_bool, date_to_str, d_from_str,
)
from store import clock_today_date
from paginate import list_response

bp = Blueprint("cases", __name__)

BASIS_TYPES = {"DIRECT_SERVICE", "FAMILY_DERIVATION", "CADET_APPOINTMENT"}
RELATIONSHIPS = {"SPOUSE", "WIDOW_WIDOWER", "CHILD", "STEPCHILD", "FORMER_SPOUSE"}
BRANCHES = {"ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD",
            "SPACE_FORCE", "NOAA_CORPS", "PHS_CORPS"}
COMPONENTS = {"ACTIVE_DUTY", "RESERVE", "NATIONAL_GUARD", "CADET"}
DISCHARGES = {"HONORABLE", "GENERAL_UNDER_HONORABLE", "OTHER_THAN_HONORABLE",
              "BAD_CONDUCT", "DISHONORABLE", "MEDICAL", "ENTRY_LEVEL", "STILL_SERVING"}
DOC_TYPES = {"DD214", "NGB22", "MARRIAGE_CERTIFICATE", "BIRTH_CERTIFICATE",
             "ADOPTION_DECREE", "DIVORCE_DECREE", "DEATH_CERTIFICATE",
             "LEAVE_EARNINGS_STATEMENT", "ORDERS"}
DECISIONS = {"APPROVE", "DENY", "REQUEST_MORE_INFO"}

MAX_LINEAGE_DEPTH = 3


def _get_case(case_id):
    c = store.T["eligibility_cases"].get(case_id)
    if c is None:
        raise err("ERR_NOT_FOUND", 404, "eligibility case not found")
    return c


@bp.post("/membership/eligibility-cases")
def create_case():
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    name = require_field(body, "applicant_legal_name")
    dob = require_date(body, "applicant_dob")
    basis = require_enum(body, "basis_type", BASIS_TYPES)
    sponsor = optional_field(body, "sponsor_member_id")
    rel = optional_enum(body, "claimed_relationship", RELATIONSHIPS)
    adop = optional_bool(body, "adoption_or_divorce_flag", False)

    if basis == "FAMILY_DERIVATION":
        if sponsor is None or rel is None:
            raise err("ERR_INVALID_REQUEST", 400,
                      "sponsor_member_id and claimed_relationship required for FAMILY_DERIVATION")
    else:
        if sponsor is not None or rel is not None:
            raise err("ERR_INVALID_REQUEST", 400,
                      "sponsor_member_id and claimed_relationship must be null for this basis")

    row = new_row()
    row.update({
        "applicant_legal_name": name,
        "applicant_dob": date_to_str(dob),
        "basis_type": basis,
        "sponsor_member_id": sponsor,
        "claimed_relationship": rel,
        "eligibility_category": None,
        "adoption_or_divorce_flag": adop,
        "member_id": None,
        "verification_officer_id": None,
        "record_reconstruction_officer_id": None,
        "denial_reason": None,
        "decision_note": None,
        "status": "INTAKE",
    })
    store.insert_row("eligibility_cases", row)
    return success(201, ser_case(row), "object")


@bp.get("/membership/eligibility-cases")
def list_cases():
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant", "VerificationOfficer", "PlatformAdmin"])
    rows = list(store.T["eligibility_cases"].values())
    status = request.args.get("status")
    basis = request.args.get("basis_type")
    sponsor = request.args.get("sponsor_member_id")
    member = request.args.get("member_id")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if basis:
        rows = [r for r in rows if r["basis_type"] == basis]
    if sponsor:
        rows = [r for r in rows if r["sponsor_member_id"] == sponsor]
    if member:
        rows = [r for r in rows if r["member_id"] == member]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_case(r) for r in rows], success)


@bp.get("/membership/eligibility-cases/<case_id>")
def get_case(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant", "VerificationOfficer", "PlatformAdmin"])
    return success(200, ser_case(_get_case(case_id)), "object")


@bp.post("/membership/eligibility-cases/<case_id>/service-records")
def add_service_record(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant"])
    case = _get_case(case_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    branch = require_enum(body, "branch", BRANCHES)
    component = require_enum(body, "component", COMPONENTS)
    rank = require_field(body, "rank_grade")
    start = require_date(body, "service_start_date")
    end = optional_date(body, "service_end_date")
    discharge = require_enum(body, "discharge_characterization", DISCHARGES)

    if case["status"] not in ("INTAKE", "MORE_INFO_REQUIRED"):
        raise err("ERR_INVALID_STATE", 409, "case not in INTAKE or MORE_INFO_REQUIRED")

    end_d = end if end is not None else clock_today_date()
    service_days = (end_d - start).days
    row = new_row()
    row.update({
        "case_id": case_id,
        "branch": branch, "component": component, "rank_grade": rank,
        "service_start_date": date_to_str(start),
        "service_end_date": date_to_str(end) if end else None,
        "discharge_characterization": discharge,
        "service_verified": False,
        "service_days": service_days,
    })
    store.insert_row("service_records", row)
    return success(201, ser_service_record(row), "object")


@bp.get("/membership/eligibility-cases/<case_id>/service-records")
def list_case_service_records(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant", "VerificationOfficer", "PlatformAdmin"])
    _get_case(case_id)
    rows = [r for r in store.T["service_records"].values() if r["case_id"] == case_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_service_record(r) for r in rows], success)


@bp.post("/membership/eligibility-cases/<case_id>/evidence")
def upload_evidence(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant"])
    case = _get_case(case_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    doc_type = require_enum(body, "doc_type", DOC_TYPES)
    issuing = require_field(body, "issuing_authority")
    issued = require_date(body, "issued_on")
    covers = optional_field(body, "covers_service_record_id")
    chash = require_field(body, "content_hash")

    if case["status"] not in ("INTAKE", "MORE_INFO_REQUIRED", "APPROVED"):
        raise err("ERR_INVALID_STATE", 409, "case not accepting evidence")

    # duplicate check
    for d in store.T["evidence_docs"].values():
        if d["case_id"] == case_id and d["content_hash"] == chash:
            raise err("ERR_DUPLICATE_EVIDENCE", 409, "duplicate evidence content hash")

    # FK resolution
    if covers is not None:
        rec = store.T["service_records"].get(covers)
        if rec is None or rec["case_id"] != case_id:
            raise err("ERR_INVALID_REFERENCE", 422, "covers_service_record_id does not resolve")

    row = new_row()
    row.update({
        "case_id": case_id,
        "doc_type": doc_type,
        "issuing_authority": issuing,
        "issued_on": date_to_str(issued),
        "covers_service_record_id": covers,
        "authenticity_channel": "SELF_DECLARED",
        "content_hash": chash,
    })
    store.insert_row("evidence_docs", row)
    return success(201, ser_evidence(row), "object")


@bp.get("/membership/eligibility-cases/<case_id>/evidence")
def list_case_evidence(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant", "VerificationOfficer", "PlatformAdmin"])
    _get_case(case_id)
    rows = [r for r in store.T["evidence_docs"].values() if r["case_id"] == case_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_evidence(r) for r in rows], success)


@bp.post("/membership/eligibility-cases/<case_id>/submit")
def submit_case(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant"])
    case = _get_case(case_id)
    # body well-formed: no required fields
    request.get_json(silent=True)

    from_status = case["status"]
    if from_status not in ("INTAKE", "MORE_INFO_REQUIRED"):
        raise err("ERR_INVALID_STATE", 409, "case not submittable from this state")

    # Priority 12: lineage depth (family)
    sponsor = None
    if case["basis_type"] == "FAMILY_DERIVATION":
        sponsor = store.T["members"].get(case["sponsor_member_id"])
        # sponsor existence is part of the submit preconditions -> NOT_FOUND semantics
        # Scaffold says existence -> ERR_NOT_FOUND handled above for path; for body-level
        # sponsor existence on submit, scaffold precondition wording yields
        # ERR_LINEAGE_DEPTH_EXCEEDED when depth exceeded; sponsor missing is a
        # submit precondition failure. PRD: "requires that the sponsor Member exists".
        # A missing sponsor member means case data is internally inconsistent; treat as 422
        # via lineage depth rule family. But §1.2 submit preconditions group sponsor
        # existence+ACTIVE+depth together under ERR_LINEAGE_DEPTH_EXCEEDED. We follow that.
        if sponsor is None or sponsor["lineage_depth"] + 1 > MAX_LINEAGE_DEPTH:
            raise err("ERR_LINEAGE_DEPTH_EXCEEDED", 422, "lineage depth exceeded or sponsor missing")

    # Priority 20: sponsor activeness
    if case["basis_type"] == "FAMILY_DERIVATION" and sponsor is not None:
        if sponsor["status"] != "ACTIVE":
            raise err("ERR_SPONSOR_NOT_ACTIVE", 422, "sponsor not active")

    # Priority 22: service record presence
    records = [r for r in store.T["service_records"].values() if r["case_id"] == case_id]
    if case["basis_type"] in ("DIRECT_SERVICE", "CADET_APPOINTMENT") and not records:
        raise err("ERR_SERVICE_RECORD_REQUIRED", 422, "service record required")

    # Priority 23: evidence presence
    docs = [d for d in store.T["evidence_docs"].values() if d["case_id"] == case_id]
    if not docs:
        raise err("ERR_EVIDENCE_REQUIRED", 422, "evidence required")

    # Priority 24: resubmit requires new evidence since MORE_INFO_REQUIRED
    if from_status == "MORE_INFO_REQUIRED":
        mir_ts = case.get("_mir_entered_at")
        new_docs = [d for d in docs if mir_ts is not None and d["created_at"] > mir_ts]
        if not new_docs:
            raise err("ERR_NO_NEW_EVIDENCE", 422, "no new evidence since MORE_INFO_REQUIRED")

    case["status"] = "UNDER_REVIEW"
    touch(case)
    return success(200, ser_case(case), "object")


def _derive_category(case):
    basis = case["basis_type"]
    if basis == "CADET_APPOINTMENT":
        return "OFFICER_CADET"
    if basis == "DIRECT_SERVICE":
        records = [r for r in store.T["service_records"].values()
                   if r["case_id"] == case["id"]]
        records.sort(key=lambda r: (r["created_at"], r["id"]))
        r = records[0]  # direct-service cases carry exactly one
        if r["discharge_characterization"] in ("OTHER_THAN_HONORABLE", "BAD_CONDUCT", "DISHONORABLE"):
            raise err("ERR_ELIGIBILITY_DERIVATION_FAILED", 422, "disqualifying discharge")
        if r["discharge_characterization"] == "STILL_SERVING" or r["service_end_date"] is None:
            return "ENLISTED_ACTIVE"
        return "VETERAN_HONORABLE"
    # FAMILY_DERIVATION
    rel = case["claimed_relationship"]
    if rel == "WIDOW_WIDOWER":
        return "FAMILY_WIDOW"
    if rel in ("CHILD", "STEPCHILD"):
        return "FAMILY_CHILD"
    return "FAMILY_SPOUSE"


@bp.post("/membership/eligibility-cases/<case_id>/decide")
def decide_case(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    case = _get_case(case_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    decision = require_enum(body, "decision", DECISIONS)
    note = optional_field(body, "decision_note")

    if case["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "case not under review")

    if decision == "DENY":
        case["status"] = "DENIED"
        case["denial_reason"] = note
        touch(case)
        return success(200, ser_case(case), "object")

    if decision == "REQUEST_MORE_INFO":
        case["status"] = "MORE_INFO_REQUIRED"
        case["decision_note"] = note
        case["_mir_entered_at"] = store.now_iso_ms()
        touch(case)
        return success(200, ser_case(case), "object")

    # APPROVE ---------------------------------------------------------
    # Priority 8: segregation of duties
    if (case["record_reconstruction_officer_id"] is not None
            and c["uid"] == case["record_reconstruction_officer_id"]):
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "reconstruction officer cannot approve")

    # Priority 13: extended lineage proof
    if case["basis_type"] == "FAMILY_DERIVATION" and case["adoption_or_divorce_flag"]:
        docs = [d for d in store.T["evidence_docs"].values() if d["case_id"] == case_id]
        channels_ok = all(
            d["authenticity_channel"] in ("ISSUER_CONFIRMED", "ARCHIVES_CONFIRMED")
            for d in docs
        )
        distinct_types = {d["doc_type"] for d in docs}
        if not channels_ok or len(distinct_types) < 2:
            raise err("ERR_LINEAGE_PROOF_INSUFFICIENT", 422, "extended lineage proof insufficient")

    # Priority 14: derivation rule
    category = _derive_category(case)

    # Priority 20: sponsor still ACTIVE
    sponsor = None
    if case["basis_type"] == "FAMILY_DERIVATION":
        sponsor = store.T["members"].get(case["sponsor_member_id"])
        if sponsor is None or sponsor["status"] != "ACTIVE":
            raise err("ERR_SPONSOR_NOT_ACTIVE", 422, "sponsor not active")

    # Priority 25: all service records verified
    records = [r for r in store.T["service_records"].values() if r["case_id"] == case_id]
    if any(not r["service_verified"] for r in records):
        raise err("ERR_SERVICE_RECORD_UNVERIFIED", 422, "unverified service records")

    # Mint member
    member = new_row()
    lineage_depth = 0
    sponsor_id = None
    claimed_rel = None
    household_id = None
    if case["basis_type"] == "FAMILY_DERIVATION":
        lineage_depth = sponsor["lineage_depth"] + 1
        sponsor_id = sponsor["id"]
        claimed_rel = case["claimed_relationship"]
        household_id = sponsor["household_id"]

    member.update({
        "member_number": store.next_member_number(),
        "legal_name": case["applicant_legal_name"],
        "dob": case["applicant_dob"],
        "case_id": case["id"],
        "eligibility_category": category,
        "sponsor_member_id": sponsor_id,
        "claimed_relationship": claimed_rel,
        "household_id": household_id,
        "lineage_depth": lineage_depth,
        "status": "ACTIVE",
        "deployment_posture": "NONE",
        "product_matrix_cache": None,
    })
    store.insert_row("members", member)
    recompute_member_matrix(member)

    case["eligibility_category"] = category
    case["member_id"] = member["id"]
    case["verification_officer_id"] = c["uid"]
    case["status"] = "APPROVED"
    touch(case)

    if household_id:
        recompute_household(store.T["households"][household_id])

    return success(200, ser_case(case), "object")


@bp.post("/membership/eligibility-cases/<case_id>/record-reconstruction")
def record_reconstruction(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    case = _get_case(case_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})
    note = require_field(body, "decision_note")

    if case["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "case not under review")

    case["record_reconstruction_officer_id"] = c["uid"]
    case["decision_note"] = note
    if decision == "APPROVE":
        for r in store.T["service_records"].values():
            if r["case_id"] == case_id:
                r["service_verified"] = True
                touch(r)
    else:
        case["status"] = "DENIED"
    touch(case)
    return success(200, ser_case(case), "object")


# ---------------------------------------------------------------------------
# Flat service-record / evidence reads
# ---------------------------------------------------------------------------

@bp.get("/membership/service-records")
def list_service_records():
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "PlatformAdmin"])
    rows = list(store.T["service_records"].values())
    case_id = request.args.get("case_id")
    if case_id:
        rows = [r for r in rows if r["case_id"] == case_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_service_record(r) for r in rows], success)


@bp.get("/membership/service-records/<record_id>")
def get_service_record(record_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "PlatformAdmin"])
    r = store.T["service_records"].get(record_id)
    if r is None:
        raise err("ERR_NOT_FOUND", 404, "service record not found")
    return success(200, ser_service_record(r), "object")


@bp.get("/membership/evidence")
def list_evidence():
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant", "VerificationOfficer", "PlatformAdmin"])
    rows = list(store.T["evidence_docs"].values())
    case_id = request.args.get("case_id")
    covers = request.args.get("covers_service_record_id")
    if case_id:
        rows = [r for r in rows if r["case_id"] == case_id]
    if covers:
        rows = [r for r in rows if r["covers_service_record_id"] == covers]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_evidence(r) for r in rows], success)


@bp.get("/membership/evidence/<doc_id>")
def get_evidence(doc_id):
    c = auth.ctx()
    auth.require_roles(c, ["EligibilityApplicant", "VerificationOfficer", "PlatformAdmin"])
    d = store.T["evidence_docs"].get(doc_id)
    if d is None:
        raise err("ERR_NOT_FOUND", 404, "evidence not found")
    return success(200, ser_evidence(d), "object")
