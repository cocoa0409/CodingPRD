"""Credit enhancement: proposal, commitment and compensating withdrawal (PRD 3.3)."""
from decimal import Decimal

from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate, require_deal_ownership
from services import calc, derive
from validation import dec, parse_body, query_value, spec

bp = Blueprint("enhancements", __name__)

ENHANCEMENT_TYPES = ["BOND_INSURANCE", "LETTER_OF_CREDIT", "STATE_INTERCEPT"]
COMMIT_DEAL_STATUSES = ("STRUCTURING", "PRICING_COMPETITIVE", "PRICING_NEGOTIATED")
WITHDRAW_DEAL_STATUSES = (
    "STRUCTURING",
    "PRICING_COMPETITIVE",
    "PRICING_NEGOTIATED",
    "PRICED",
)

PREMIUM_BPS_MIN = Decimal(1)
PREMIUM_BPS_MAX = Decimal(200)
MAX_INSURED_TRANCHES = 40

ENHANCEMENT_SPECS = [
    spec("provider_name", "string", min_len=1, max_len=120),
    spec("enhancement_type", "enum", values=ENHANCEMENT_TYPES),
    spec("enhanced_rating", "string", min_len=1, max_len=6),
    spec("premium_bps", "number", max_decimals=2),
    spec("insured_tranche_ids", "string_array", max_items=MAX_INSURED_TRANCHES),
]


@bp.route("/bond-offerings/deals/<deal_id>/credit-enhancements", methods=["POST"])
def create_enhancement(deal_id):
    actor = authenticate(["MunicipalAdvisor", "IssuerOfficial"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(ENHANCEMENT_SPECS)
    # tier 7: every named maturity must exist
    tranches = [lookup.get_tranche(value) for value in body["insured_tranche_ids"]]
    # tier 8: actor ownership
    require_deal_ownership(actor, deal)
    # tier 9: every named maturity belongs to this deal
    for tranche in tranches:
        if tranche["deal_id"] != deal_id:
            raise ApiError("ERR_CROSS_DEAL_REFERENCE")
    # tier 16: fiscal shape of the proposal
    premium_bps = dec(body["premium_bps"])
    if premium_bps < PREMIUM_BPS_MIN or premium_bps > PREMIUM_BPS_MAX:
        raise ApiError("ERR_ENHANCEMENT_ALREADY_COMMITTED")
    ids = body["insured_tranche_ids"]
    if not ids or len(set(ids)) != len(ids):
        raise ApiError("ERR_ENHANCEMENT_ALREADY_COMMITTED")
    row = db.new_row(
        deal_id=deal_id,
        provider_name=body["provider_name"],
        enhancement_type=body["enhancement_type"],
        enhanced_rating=body["enhanced_rating"],
        premium_bps=premium_bps,
        insured_tranche_ids=list(ids),
        status="PROPOSED",
        insured_debt_service_usd=None,
        premium_usd=None,
        withdrawal_reason=None,
    )
    db.db.enhancements[row["id"]] = row
    return response.created(serializers.enhancement(row))


@bp.route("/bond-offerings/deals/<deal_id>/credit-enhancements", methods=["GET"])
def list_enhancements(deal_id):
    authenticate(ALL_ROLES)
    lookup.get_deal(deal_id)
    rows = sorted(
        lookup.enhancements_of_deal(deal_id),
        key=lambda row: (row["created_at"], row["_seq"]),
    )
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.enhancement)


def _insured_rows(enhancement, deal_id):
    ids = set(enhancement["insured_tranche_ids"])
    return [row for row in lookup.tranches_of_deal(deal_id) if row["id"] in ids]


@bp.route("/bond-offerings/credit-enhancements/<enhancement_id>/commit", methods=["POST"])
def commit_enhancement(enhancement_id):
    actor = authenticate(["IssuerOfficial"])
    enhancement = lookup.get_enhancement(enhancement_id)
    parse_body([])
    deal = lookup.deal_of_enhancement(enhancement)
    require_deal_ownership(actor, deal)
    # tier 11: state legality
    if enhancement["status"] != "PROPOSED":
        raise ApiError("ERR_ENHANCEMENT_INVALID_STATE")
    if deal["status"] not in COMMIT_DEAL_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    # tier 16: at most one committed enhancement per deal
    if derive.committed_enhancement(deal["id"]) is not None:
        raise ApiError("ERR_ENHANCEMENT_ALREADY_COMMITTED")
    insured = _insured_rows(enhancement, deal["id"])
    for tranche in insured:
        if not tranche["is_insured"] or tranche["rating_basis"] != "ENHANCED":
            tranche["is_insured"] = True
            tranche["rating_basis"] = "ENHANCED"
            db.touch(tranche)
    debt_service = calc.insured_debt_service(insured)
    premium = calc.enhancement_premium(debt_service, enhancement["premium_bps"])
    enhancement["status"] = "COMMITTED"
    enhancement["insured_debt_service_usd"] = debt_service
    enhancement["premium_usd"] = premium
    db.touch(enhancement)
    deal["credit_enhancement_premium_usd"] = premium
    if deal["status"] == "PRICED":
        derive.recompute_net_proceeds(deal)
    db.touch(deal)
    return response.ok(serializers.enhancement(enhancement))


@bp.route("/bond-offerings/credit-enhancements/<enhancement_id>/withdraw", methods=["POST"])
def withdraw_enhancement(enhancement_id):
    actor = authenticate(["IssuerOfficial"])
    enhancement = lookup.get_enhancement(enhancement_id)
    body = parse_body([spec("withdrawal_reason", "string", min_len=1)])
    deal = lookup.deal_of_enhancement(enhancement)
    require_deal_ownership(actor, deal)
    if enhancement["status"] != "COMMITTED":
        raise ApiError("ERR_ENHANCEMENT_INVALID_STATE")
    if deal["status"] not in WITHDRAW_DEAL_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    # hop 1: the enhancement itself
    enhancement["status"] = "WITHDRAWN"
    enhancement["enhanced_rating"] = None
    enhancement["withdrawal_reason"] = body["withdrawal_reason"]
    db.touch(enhancement)
    # hop 2: the insured maturities revert
    for tranche in _insured_rows(enhancement, deal["id"]):
        if tranche["is_insured"]:
            tranche["is_insured"] = False
            tranche["rating_basis"] = "UNDERLYING"
            db.touch(tranche)
    # hop 3: the deal's premium and net proceeds
    deal["credit_enhancement_premium_usd"] = Decimal("0.00")
    if deal["status"] == "PRICED":
        derive.recompute_net_proceeds(deal)
    # hop 4: the disclosure that quoted the proceeds re-opens
    statement = derive.governing_statement(deal["id"])
    if statement is not None:
        derive.unapprove_sections(
            statement, lambda section: section["references_credit_enhancement"]
        )
        if derive.apply_mandatory_sections_approved(statement):
            db.touch(statement)
        derive.recompute_disclosure_clearance(deal)
    derive.cancel_scheduled_presentations(deal["id"], "DISCLOSURE_BLOCKED")
    db.touch(deal)
    return response.ok(serializers.enhancement(enhancement))
