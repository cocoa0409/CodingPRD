"""Official statements and their sections (PRD 3.4)."""
from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate, require_deal_ownership
from services import calc, derive
from validation import parse_body, query_value, sorted_rows, spec

bp = Blueprint("statements", __name__)

MAX_DRAFT_ROUNDS = 4
SECTION_TYPES = [
    "RISK_FACTOR",
    "TAX_MATTERS",
    "CONTINUING_DISCLOSURE",
    "UNDERWRITING",
    "GENERAL",
]
CLOSED_DEAL_STATUSES = ("CLOSED", "CANCELLED")

STATEMENT_SPECS = [
    spec("version_label", "string", min_len=1, max_len=40),
    spec("is_preliminary", "boolean"),
    spec("expected_deal_version", "integer"),
]

SECTION_SPECS = [
    spec("section_code", "string", min_len=1, max_len=16),
    spec("title", "string", min_len=1, max_len=160),
    spec("body_text", "string", min_len=1, max_len=8000),
    spec("section_type", "enum", values=SECTION_TYPES),
    spec("is_material_risk", "boolean", required=False, default=False),
    spec("references_credit_enhancement", "boolean", required=False, default=False),
    spec("parent_section_id", "string", required=False, default=None),
]


@bp.route("/bond-offerings/deals/<deal_id>/official-statements", methods=["POST"])
def create_statement(deal_id):
    actor = authenticate(["BondCounsel", "MunicipalAdvisor"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(STATEMENT_SPECS)
    require_deal_ownership(actor, deal)
    # tier 10: optimistic concurrency on the deal
    if body["expected_deal_version"] != deal["version"]:
        raise ApiError("ERR_STALE_DEAL_VERSION")
    # tier 11: a closed or cancelled deal takes no new disclosure
    if deal["status"] in CLOSED_DEAL_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    for existing in lookup.statements_of_deal(deal_id):
        if existing["status"] in ("DRAFTING", "IN_REVIEW", "REVISION_REQUESTED"):
            existing["status"] = "SUPERSEDED"
            db.touch(existing)
    row = db.new_row(
        deal_id=deal_id,
        version_label=body["version_label"],
        is_preliminary=body["is_preliminary"],
        status="DRAFTING",
        draft_round=1,
        mandatory_sections_approved=False,
        posted_preliminary_at=None,
        posted_final_at=None,
        revision_reason=None,
    )
    db.db.statements[row["id"]] = row
    derive.recompute_disclosure_clearance(deal)
    db.touch(deal)
    return response.created(serializers.statement(row))


@bp.route("/bond-offerings/deals/<deal_id>/official-statements", methods=["GET"])
def list_deal_statements(deal_id):
    authenticate(ALL_ROLES)
    lookup.get_deal(deal_id)
    rows = sorted(
        lookup.statements_of_deal(deal_id),
        key=lambda row: (row["created_at"], row["_seq"]),
        reverse=True,
    )
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.statement)


@bp.route("/bond-offerings/official-statements/<statement_id>", methods=["GET"])
def read_statement(statement_id):
    authenticate(ALL_ROLES)
    row = lookup.get_statement(statement_id)
    return response.ok(serializers.statement(row))


@bp.route("/bond-offerings/official-statements/<statement_id>/submit-for-review", methods=["POST"])
def submit_for_review(statement_id):
    authenticate(["BondCounsel"])
    statement = lookup.get_statement(statement_id)
    parse_body([])
    deal = lookup.deal_of_statement(statement)
    if statement["status"] != "DRAFTING":
        raise ApiError("ERR_OS_INVALID_STATE")
    if not lookup.sections_of_statement(statement_id):
        raise ApiError("ERR_OS_INVALID_STATE")
    if deal["status"] in CLOSED_DEAL_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    statement["status"] = "IN_REVIEW"
    derive.apply_mandatory_sections_approved(statement)
    db.touch(statement)
    if derive.recompute_disclosure_clearance(deal):
        db.touch(deal)
    return response.ok(serializers.statement(statement))


@bp.route("/bond-offerings/official-statements/<statement_id>/request-revision", methods=["POST"])
def request_revision(statement_id):
    actor = authenticate(["MunicipalAdvisor"])
    statement = lookup.get_statement(statement_id)
    body = parse_body([spec("revision_reason", "string", min_len=1)])
    deal = lookup.deal_of_statement(statement)
    require_deal_ownership(actor, deal)
    if statement["status"] != "IN_REVIEW":
        raise ApiError("ERR_OS_INVALID_STATE")
    if statement["draft_round"] >= MAX_DRAFT_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")
    # hop 1
    statement["status"] = "REVISION_REQUESTED"
    statement["draft_round"] = statement["draft_round"] + 1
    statement["revision_reason"] = body["revision_reason"]
    # hop 2
    derive.unapprove_sections(
        statement, lambda section: section["section_type"] == "RISK_FACTOR"
    )
    # hop 3
    derive.apply_mandatory_sections_approved(statement)
    db.touch(statement)
    # hop 4
    derive.recompute_disclosure_clearance(deal)
    # hop 5
    derive.cancel_scheduled_presentations(deal["id"], "DISCLOSURE_BLOCKED")
    for engagement in lookup.engagements_of_deal(deal["id"]):
        if engagement["status"] != "UNDER_REVIEW":
            continue
        engagement["status"] = "INFO_REQUESTED"
        engagement["info_request_count"] = engagement["info_request_count"] + 1
        engagement["latest_information_request"] = "DISCLOSURE_BLOCKED_PENDING_OS_REVISION"
        db.touch(engagement)
    db.touch(deal)
    return response.ok(serializers.statement(statement))


@bp.route("/bond-offerings/official-statements/<statement_id>/resume-drafting", methods=["POST"])
def resume_drafting(statement_id):
    authenticate(["BondCounsel"])
    statement = lookup.get_statement(statement_id)
    parse_body([])
    deal = lookup.deal_of_statement(statement)
    if statement["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_OS_INVALID_STATE")
    if deal["status"] in CLOSED_DEAL_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    statement["status"] = "DRAFTING"
    db.touch(statement)
    derive.recompute_disclosure_clearance(deal)
    db.touch(deal)
    return response.ok(serializers.statement(statement))


@bp.route("/bond-offerings/official-statements/<statement_id>/post-preliminary", methods=["POST"])
def post_preliminary(statement_id):
    actor = authenticate(["MunicipalAdvisor"])
    statement = lookup.get_statement(statement_id)
    parse_body([])
    deal = lookup.deal_of_statement(statement)
    require_deal_ownership(actor, deal)
    if statement["status"] != "IN_REVIEW":
        raise ApiError("ERR_OS_INVALID_STATE")
    if deal["status"] not in ("PRICING_COMPETITIVE", "PRICING_NEGOTIATED"):
        raise ApiError("ERR_DEAL_INVALID_STATE")
    # tier 13: the three disclosure gates, in order
    if not statement["mandatory_sections_approved"]:
        raise ApiError("ERR_MANDATORY_SECTION_NOT_APPROVED")
    if derive.active_undertaking(deal["id"]) is None:
        raise ApiError("ERR_UNDERTAKING_NOT_ACTIVE")
    issuer = db.db.issuers[deal["issuer_id"]]
    if issuer["disclosure_risk_score"] >= calc.DISCLOSURE_RISK_GATE:
        sections = lookup.sections_of_statement(statement_id)
        if not any(
            section["section_type"] == "CONTINUING_DISCLOSURE"
            and section["is_material_risk"]
            and section["review_status"] == "APPROVED"
            for section in sections
        ):
            raise ApiError("ERR_DISCLOSURE_RISK_SECTION_REQUIRED")
    statement["status"] = "PRELIMINARY_POSTED"
    statement["posted_preliminary_at"] = db.now()
    db.touch(statement)
    derive.recompute_disclosure_clearance(deal)
    db.touch(deal)
    return response.ok(serializers.statement(statement))


@bp.route("/bond-offerings/official-statements/<statement_id>/post-final", methods=["POST"])
def post_final(statement_id):
    actor = authenticate(["MunicipalAdvisor"])
    statement = lookup.get_statement(statement_id)
    parse_body([])
    deal = lookup.deal_of_statement(statement)
    require_deal_ownership(actor, deal)
    if statement["status"] != "PRELIMINARY_POSTED":
        raise ApiError("ERR_OS_INVALID_STATE")
    if deal["status"] != "AWARDED":
        raise ApiError("ERR_DEAL_INVALID_STATE")
    for section in lookup.sections_of_statement(statement_id):
        if section["review_status"] != "APPROVED":
            raise ApiError("ERR_MANDATORY_SECTION_NOT_APPROVED")
    statement["status"] = "FINAL_POSTED"
    statement["posted_final_at"] = db.now()
    db.touch(statement)
    if derive.recompute_disclosure_clearance(deal):
        db.touch(deal)
    return response.ok(serializers.statement(statement))


@bp.route("/bond-offerings/official-statements/<statement_id>/sections", methods=["POST"])
def create_section(statement_id):
    actor = authenticate(["BondCounsel"])
    statement = lookup.get_statement(statement_id)
    body = parse_body(SECTION_SPECS)
    # section_code is unique within its official statement (PRD 3.4)
    for existing in lookup.sections_of_statement(statement_id):
        if existing["section_code"] == body["section_code"]:
            raise ApiError("ERR_INVALID_REQUEST")
    # tier 7: the parent section must exist
    parent = None
    if body["parent_section_id"] is not None:
        parent = lookup.get_section(body["parent_section_id"])
    # tier 9: the parent belongs to this very statement
    if parent is not None and parent["official_statement_id"] != statement_id:
        raise ApiError("ERR_CROSS_DEAL_REFERENCE")
    row = db.new_row(
        official_statement_id=statement_id,
        parent_section_id=body["parent_section_id"],
        section_code=body["section_code"],
        title=body["title"],
        body_text=body["body_text"],
        section_type=body["section_type"],
        is_material_risk=body["is_material_risk"],
        references_credit_enhancement=body["references_credit_enhancement"],
        review_status="DRAFT",
        authored_by_user_id=actor.user_id,
        approved_by_user_id=None,
        word_count=len(body["body_text"].split()),
    )
    db.db.sections[row["id"]] = row
    return response.created(serializers.section(row))


@bp.route("/bond-offerings/official-statements/<statement_id>/sections", methods=["GET"])
def list_statement_sections(statement_id):
    authenticate(ALL_ROLES)
    lookup.get_statement(statement_id)
    rows = sorted_rows(lookup.sections_of_statement(statement_id))
    section_type = query_value("section_type")
    if section_type is not None:
        rows = [row for row in rows if row["section_type"] == section_type]
    review_status = query_value("review_status")
    if review_status is not None:
        rows = [row for row in rows if row["review_status"] == review_status]
    return response.paginated(rows, serializers.section)


@bp.route("/bond-offerings/os-sections", methods=["GET"])
def list_sections():
    authenticate(["MunicipalAdvisor", "BondCounsel", "ComplianceOfficer"])
    rows = sorted_rows(list(db.db.sections.values()))
    statement_id = query_value("official_statement_id")
    if statement_id is not None:
        rows = [row for row in rows if row["official_statement_id"] == statement_id]
    parent_id = query_value("parent_section_id")
    if parent_id is not None:
        rows = [row for row in rows if row["parent_section_id"] == parent_id]
    review_status = query_value("review_status")
    if review_status is not None:
        rows = [row for row in rows if row["review_status"] == review_status]
    return response.paginated(rows, serializers.section)


@bp.route("/bond-offerings/os-sections/<section_id>", methods=["GET"])
def read_section(section_id):
    authenticate(ALL_ROLES)
    row = lookup.get_section(section_id)
    return response.ok(serializers.section(row))


@bp.route("/bond-offerings/os-sections/<section_id>/approve", methods=["POST"])
def approve_section(section_id):
    actor = authenticate(["BondCounsel"])
    section = lookup.get_section(section_id)
    parse_body([])
    statement = db.db.statements[section["official_statement_id"]]
    deal = lookup.deal_of_statement(statement)
    # tier 11: state legality
    if section["review_status"] not in ("DRAFT", "NEEDS_REVISION"):
        raise ApiError("ERR_SECTION_INVALID_STATE")
    if statement["status"] not in ("DRAFTING", "IN_REVIEW"):
        raise ApiError("ERR_OS_INVALID_STATE")
    # tier 12: MSRB Rule G-17 - the author may not approve their own prose
    if section["authored_by_user_id"] == actor.user_id:
        raise ApiError("ERR_SECTION_SELF_APPROVAL")
    section["review_status"] = "APPROVED"
    section["approved_by_user_id"] = actor.user_id
    db.touch(section)
    derive.apply_mandatory_sections_approved(statement)
    db.touch(statement)
    if derive.recompute_disclosure_clearance(deal):
        db.touch(deal)
    return response.ok(serializers.section(section))
