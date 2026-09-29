"""Deals: creation, structure, sale method, pricing, award, handoff, close, cancel."""
from decimal import Decimal

from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate, require_deal_ownership
from services import calc, derive
from validation import dec, parse_body, q2, query_value, sorted_rows, spec

bp = Blueprint("deals", __name__)

TAX_STATUSES = ["TAX_EXEMPT", "TAXABLE", "AMT"]
PRICING_STATUSES = ("PRICING_COMPETITIVE", "PRICING_NEGOTIATED")

DEAL_SPECS = [
    spec("issuer_id", "string"),
    spec("series_designation", "string", min_len=1, max_len=40),
    spec("tax_status", "enum", values=TAX_STATUSES),
    spec("dated_date", "datetime"),
    spec("expected_par_amount_usd", "number", exclusive_minimum=0, multiple_of=5000),
    spec("municipal_advisor_firm_id", "string", required=False, default=None),
    spec("record_retention_years", "integer", required=False, default=None),
]


@bp.route("/bond-offerings/deals", methods=["POST"])
def create_deal():
    authenticate(["IssuerOfficial", "MunicipalAdvisor"])
    body = parse_body(DEAL_SPECS)
    # tier 7: body references must name existing rows
    lookup.get_issuer(body["issuer_id"])
    advisor = None
    if body["municipal_advisor_firm_id"] is not None:
        advisor = lookup.get_firm(body["municipal_advisor_firm_id"])
    # tier 12: MSRB conduct
    if advisor is not None and advisor["is_suspended"]:
        raise ApiError("ERR_FIRM_SUSPENDED")
    # tier 15: series designation unique per issuer
    for existing in db.db.deals.values():
        if (
            existing["issuer_id"] == body["issuer_id"]
            and existing["series_designation"] == body["series_designation"]
        ):
            raise ApiError("ERR_DUPLICATE_SERIES_DESIGNATION")
    row = db.new_row(
        issuer_id=body["issuer_id"],
        municipal_advisor_firm_id=body["municipal_advisor_firm_id"],
        series_designation=body["series_designation"],
        tax_status=body["tax_status"],
        dated_date=body["dated_date"],
        expected_par_amount_usd=body["expected_par_amount_usd"],
        par_amount_usd=Decimal(0),
        sale_method="UNDETERMINED",
        status="DRAFT",
        disclosure_clearance="PENDING",
        requires_g17_letter=False,
        requires_notice_of_sale=False,
        gross_spread_basis="UNDETERMINED",
        takedown_per_bond_usd=None,
        management_fee_per_bond_usd=None,
        expenses_per_bond_usd=None,
        winning_bid_price_pct=None,
        issue_price_total_usd=None,
        gross_spread_total_usd=None,
        gross_spread_per_bond_usd=None,
        credit_enhancement_premium_usd=Decimal(0),
        net_proceeds_to_issuer_usd=None,
        arbitrage_yield_pct=None,
        par_allotted_total_usd=Decimal(0),
        post_issuance_handoff_status="NOT_STARTED",
        record_retention_years=body["record_retention_years"],
        cancellation_reason=None,
    )
    db.db.deals[row["id"]] = row
    return response.created(serializers.deal(row))


@bp.route("/bond-offerings/deals", methods=["GET"])
def list_deals():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.db.deals.values()))
    issuer_id = query_value("issuer_id")
    if issuer_id is not None:
        rows = [row for row in rows if row["issuer_id"] == issuer_id]
    advisor_id = query_value("municipal_advisor_firm_id")
    if advisor_id is not None:
        rows = [row for row in rows if row["municipal_advisor_firm_id"] == advisor_id]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    sale_method = query_value("sale_method")
    if sale_method is not None:
        rows = [row for row in rows if row["sale_method"] == sale_method]
    return response.paginated(rows, serializers.deal)


@bp.route("/bond-offerings/deals/<deal_id>", methods=["GET"])
def read_deal(deal_id):
    authenticate(ALL_ROLES)
    deal = lookup.get_deal(deal_id)
    return response.ok(serializers.deal(deal))


@bp.route("/bond-offerings/deals/<deal_id>/submit-structure", methods=["POST"])
def submit_structure(deal_id):
    actor = authenticate(["MunicipalAdvisor"])
    deal = lookup.get_deal(deal_id)
    parse_body([])
    require_deal_ownership(actor, deal)
    if deal["status"] != "DRAFT":
        raise ApiError("ERR_DEAL_INVALID_STATE")
    tranches = lookup.tranches_of_deal(deal_id)
    total = sum((dec(row["principal_amount_usd"]) for row in tranches), Decimal(0))
    if not tranches or total != dec(deal["expected_par_amount_usd"]):
        raise ApiError("ERR_PAR_SCHEDULE_MISMATCH")
    deal["status"] = "STRUCTURING"
    deal["par_amount_usd"] = total
    for tranche in tranches:
        changed = (
            dec(tranche["par_unsold_usd"]) != dec(tranche["principal_amount_usd"])
            or dec(tranche["par_allotted_usd"]) != 0
        )
        tranche["par_unsold_usd"] = dec(tranche["principal_amount_usd"])
        tranche["par_allotted_usd"] = Decimal(0)
        if changed:
            db.touch(tranche)
    for member in lookup.active_members_of_deal(deal_id):
        value = calc.liability_par(member, deal)
        if member["liability_par_usd"] != value:
            member["liability_par_usd"] = value
            db.touch(member)
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/bond-offerings/deals/<deal_id>/designate-sale-method", methods=["POST"])
def designate_sale_method(deal_id):
    actor = authenticate(["MunicipalAdvisor", "IssuerOfficial"])
    deal = lookup.get_deal(deal_id)
    body = parse_body([spec("sale_method", "enum", values=["COMPETITIVE", "NEGOTIATED"])])
    require_deal_ownership(actor, deal)
    # A deal already designated may not be re-designated (PRD 3.6).
    if deal["sale_method"] != "UNDETERMINED":
        raise ApiError("ERR_SALE_METHOD_CONFLICT")
    if deal["status"] != "STRUCTURING":
        raise ApiError("ERR_DEAL_INVALID_STATE")
    method = body["sale_method"]
    if method == "COMPETITIVE":
        advisor_id = deal["municipal_advisor_firm_id"]
        advisor = db.db.firms.get(advisor_id) if advisor_id is not None else None
        if advisor is None or advisor["firm_type"] not in ("MUNICIPAL_ADVISOR", "DUAL_REGISTERED"):
            raise ApiError("ERR_MA_ENGAGEMENT_REQUIRED")
        if advisor["is_suspended"]:
            raise ApiError("ERR_FIRM_SUSPENDED")
        if lookup.members_of_deal(deal_id):
            raise ApiError("ERR_SALE_METHOD_CONFLICT")
        deal["status"] = "PRICING_COMPETITIVE"
        deal["sale_method"] = "COMPETITIVE"
        deal["gross_spread_basis"] = "COMPETITIVE"
        deal["requires_notice_of_sale"] = True
    else:
        seniors = [
            member
            for member in lookup.active_members_of_deal(deal_id)
            if member["member_role"] == "SENIOR_MANAGER"
        ]
        if len(seniors) != 1:
            raise ApiError("ERR_SENIOR_MANAGER_REQUIRED")
        senior_firm = db.db.firms.get(seniors[0]["firm_id"])
        if senior_firm is not None and senior_firm["is_suspended"]:
            raise ApiError("ERR_FIRM_SUSPENDED")
        deal["status"] = "PRICING_NEGOTIATED"
        deal["sale_method"] = "NEGOTIATED"
        deal["gross_spread_basis"] = "NEGOTIATED"
        deal["requires_g17_letter"] = True
    db.touch(deal)
    return response.ok(serializers.deal(deal))


PRICE_SPECS = [
    spec("takedown_per_bond_usd", "number", required=False, default=None),
    spec("management_fee_per_bond_usd", "number", required=False, default=None),
    spec("expenses_per_bond_usd", "number", required=False, default=None),
    spec("winning_bid_price_pct", "number", required=False, default=None),
]


@bp.route("/bond-offerings/deals/<deal_id>/price", methods=["POST"])
def price_deal(deal_id):
    actor = authenticate(["Underwriter"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(PRICE_SPECS)
    require_deal_ownership(actor, deal)
    # tier 11: state legality
    if deal["status"] not in PRICING_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    # tier 12: the acting firm may not be suspended
    if actor.firm is not None and actor.firm["is_suspended"]:
        raise ApiError("ERR_FIRM_SUSPENDED")
    # tier 13: order-book preconditions, then disclosure preconditions
    periods = lookup.periods_of_deal(deal_id)
    if any(period["status"] == "OPEN" for period in periods):
        raise ApiError("ERR_PRICING_PRECONDITION_UNMET")
    if not any(
        period["status"] == "CLOSED" and period["allotment_run_count"] >= 1
        for period in periods
    ):
        raise ApiError("ERR_PRICING_PRECONDITION_UNMET")
    statement = derive.governing_statement(deal_id)
    if statement is None or statement["status"] != "PRELIMINARY_POSTED":
        raise ApiError("ERR_DISCLOSURE_NOT_CLEARED")
    if deal["disclosure_clearance"] != "CLEARED":
        raise ApiError("ERR_DISCLOSURE_NOT_CLEARED")
    # tier 16: compensation inputs, liability sum, then net proceeds
    negotiated = deal["gross_spread_basis"] == "NEGOTIATED"
    per_bond_present = [
        body["takedown_per_bond_usd"] is not None,
        body["management_fee_per_bond_usd"] is not None,
        body["expenses_per_bond_usd"] is not None,
    ]
    bid_present = body["winning_bid_price_pct"] is not None
    if negotiated:
        if not all(per_bond_present) or bid_present:
            raise ApiError("ERR_COMPENSATION_INPUT_MISSING")
    else:
        if any(per_bond_present) or not bid_present:
            raise ApiError("ERR_COMPENSATION_INPUT_MISSING")
    members = lookup.active_members_of_deal(deal_id)
    if negotiated:
        liability_sum = sum((dec(member["liability_pct"]) for member in members), Decimal(0))
        if liability_sum != Decimal("100.0000"):
            raise ApiError("ERR_LIABILITY_PCT_SUM_INVALID")

    tranches = lookup.tranches_of_deal(deal_id)
    issue_price = calc.issue_price_total(tranches)
    if negotiated:
        gross_total = calc.negotiated_gross_spread_total(
            tranches,
            body["takedown_per_bond_usd"],
            body["management_fee_per_bond_usd"],
            body["expenses_per_bond_usd"],
        )
    else:
        gross_total = calc.competitive_gross_spread_total(
            deal["par_amount_usd"], body["winning_bid_price_pct"], issue_price
        )
    per_bond = calc.gross_spread_per_bond(gross_total, deal["par_amount_usd"])
    insured = derive.insured_tranches(deal_id)
    enhancement = derive.committed_enhancement(deal_id)
    if insured and enhancement is not None:
        premium = calc.enhancement_premium(
            calc.insured_debt_service(insured), enhancement["premium_bps"]
        )
    else:
        premium = q2(Decimal(0))
    net = calc.net_proceeds(issue_price, gross_total, premium)
    if net <= 0:
        raise ApiError("ERR_PREMIUM_EXCEEDS_PROCEEDS")

    deal["issue_price_total_usd"] = issue_price
    deal["gross_spread_total_usd"] = gross_total
    deal["gross_spread_per_bond_usd"] = per_bond
    deal["credit_enhancement_premium_usd"] = premium
    deal["net_proceeds_to_issuer_usd"] = net
    deal["arbitrage_yield_pct"] = calc.arbitrage_yield(tranches)
    if negotiated:
        deal["takedown_per_bond_usd"] = body["takedown_per_bond_usd"]
        deal["management_fee_per_bond_usd"] = body["management_fee_per_bond_usd"]
        deal["expenses_per_bond_usd"] = body["expenses_per_bond_usd"]
    else:
        deal["winning_bid_price_pct"] = body["winning_bid_price_pct"]
        deal["takedown_per_bond_usd"] = Decimal(0)
    for member in members:
        credit = calc.takedown_credit_for_member(member, deal)
        liability = calc.liability_par(member, deal)
        if member["takedown_credit_usd"] != credit or member["liability_par_usd"] != liability:
            member["takedown_credit_usd"] = credit
            member["liability_par_usd"] = liability
            db.touch(member)
    deal["status"] = "PRICED"
    for period in periods:
        if period["status"] == "CLOSED":
            period["status"] = "SETTLED"
            db.touch(period)
    db.touch(deal)
    return response.ok(serializers.deal(deal))


AWARD_DOCUMENTS = [
    ("BOND_OPINION", "BondCounsel"),
    ("TAX_CERTIFICATE", "IssuerOfficial"),
    ("ISSUE_PRICE_CERTIFICATE", "Underwriter"),
    ("CONTINUING_DISCLOSURE_AGREEMENT", "IssuerOfficial"),
    ("UNDERWRITER_RECEIPT", "Underwriter"),
]


@bp.route("/bond-offerings/deals/<deal_id>/award", methods=["POST"])
def award_deal(deal_id):
    actor = authenticate(["IssuerOfficial"])
    deal = lookup.get_deal(deal_id)
    parse_body([])
    require_deal_ownership(actor, deal)
    if deal["status"] != "PRICED":
        raise ApiError("ERR_DEAL_INVALID_STATE")
    statement = derive.governing_statement(deal_id)
    if statement is None or statement["status"] != "PRELIMINARY_POSTED":
        raise ApiError("ERR_OS_INVALID_STATE")
    if deal["net_proceeds_to_issuer_usd"] is None or dec(deal["net_proceeds_to_issuer_usd"]) <= 0:
        raise ApiError("ERR_PREMIUM_EXCEEDS_PROCEEDS")
    required = list(AWARD_DOCUMENTS)
    if deal["requires_g17_letter"]:
        required.append(("G17_DISCLOSURE_LETTER", "Underwriter"))
    if deal["requires_notice_of_sale"]:
        required.append(("NOTICE_OF_SALE_CERTIFICATE", "MunicipalAdvisor"))
    for doc_type, signatory_role in required:
        document = db.new_row(
            deal_id=deal_id,
            doc_type=doc_type,
            is_required=True,
            execution_status="PENDING",
            signatory_role=signatory_role,
            signatory_name=None,
            executed_at=None,
            waiver_reason=None,
        )
        db.db.documents[document["id"]] = document
    deal["status"] = "AWARDED"
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/bond-offerings/deals/<deal_id>/post-issuance-handoff", methods=["POST"])
def post_issuance_handoff(deal_id):
    authenticate(["ComplianceOfficer"])
    deal = lookup.get_deal(deal_id)
    body = parse_body([spec("record_retention_years", "integer")])
    if deal["status"] not in ("PRICED", "AWARDED"):
        raise ApiError("ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE")
    if deal["arbitrage_yield_pct"] is None:
        raise ApiError("ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE")
    if derive.active_undertaking(deal_id) is None:
        raise ApiError("ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE")
    if body["record_retention_years"] < 6:
        raise ApiError("ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE")
    deal["post_issuance_handoff_status"] = "READY"
    deal["record_retention_years"] = body["record_retention_years"]
    db.touch(deal)
    return response.ok(serializers.deal(deal))


YIELD_SPECS = [
    spec("projected_investment_yield_pct", "number"),
    spec("unspent_proceeds_usd", "number"),
    spec("investment_days", "integer"),
]


@bp.route("/bond-offerings/deals/<deal_id>/yield-restriction-analysis", methods=["POST"])
def yield_restriction_analysis(deal_id):
    actor = authenticate(["ComplianceOfficer", "MunicipalAdvisor"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(YIELD_SPECS)
    require_deal_ownership(actor, deal)
    arbitrage = calc.arbitrage_yield(lookup.tranches_of_deal(deal_id))
    permitted = calc.permitted_investment_yield(arbitrage)
    projected = body["projected_investment_yield_pct"]
    applies = dec(projected) > permitted
    if applies:
        excess = calc.excess_earnings(
            body["unspent_proceeds_usd"], projected, permitted, body["investment_days"]
        )
    else:
        excess = q2(Decimal(0))
    return response.ok(
        {
            "deal_id": deal_id,
            "arbitrage_yield_pct": float(arbitrage),
            "permitted_investment_yield_pct": float(permitted),
            "projected_investment_yield_pct": float(dec(projected)),
            "yield_restriction_applies": applies,
            "excess_earnings_usd": float(excess),
        }
    )


@bp.route("/bond-offerings/deals/<deal_id>/close", methods=["POST"])
def close_deal(deal_id):
    authenticate(["ComplianceOfficer"])
    deal = lookup.get_deal(deal_id)
    parse_body([])
    if deal["status"] != "AWARDED":
        raise ApiError("ERR_DEAL_INVALID_STATE")
    statement = derive.governing_statement(deal_id)
    if statement is None or statement["status"] != "FINAL_POSTED":
        raise ApiError("ERR_OS_NOT_FINAL_POSTED")
    for document in lookup.documents_of_deal(deal_id):
        if document["is_required"] and document["execution_status"] not in ("EXECUTED", "WAIVED"):
            raise ApiError("ERR_CLOSING_DOCS_INCOMPLETE")
    if deal["post_issuance_handoff_status"] != "READY":
        raise ApiError("ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE")
    deal["status"] = "CLOSED"
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/bond-offerings/deals/<deal_id>/cancel", methods=["POST"])
def cancel_deal(deal_id):
    actor = authenticate(["IssuerOfficial"])
    deal = lookup.get_deal(deal_id)
    body = parse_body([spec("cancellation_reason", "string", min_len=1)])
    require_deal_ownership(actor, deal)
    if deal["status"] in ("CLOSED", "CANCELLED", "AWARDED"):
        raise ApiError("ERR_DEAL_INVALID_STATE")
    deal["status"] = "CANCELLED"
    deal["cancellation_reason"] = body["cancellation_reason"]
    for statement in lookup.statements_of_deal(deal_id):
        if statement["status"] in (
            "DRAFTING",
            "IN_REVIEW",
            "REVISION_REQUESTED",
            "PRELIMINARY_POSTED",
        ):
            statement["status"] = "WITHDRAWN"
            db.touch(statement)
    for order in lookup.orders_of_deal(deal_id):
        if order["status"] in ("PENDING", "ALLOTTED", "PARTIALLY_ALLOTTED", "UNFILLED"):
            order["status"] = "CANCELLED"
            order["par_allotted_usd"] = Decimal(0)
            order["cancellation_reason"] = "DEAL_CANCELLED"
            db.touch(order)
    for period in lookup.periods_of_deal(deal_id):
        changed = False
        if period["status"] in ("SCHEDULED", "OPEN", "CLOSED"):
            period["status"] = "CANCELLED"
            changed = True
        if derive.recompute_period_counters(period):
            changed = True
        if changed:
            db.touch(period)
    for tranche in lookup.tranches_of_deal(deal_id):
        derive.recompute_tranche_par(tranche)
    deal["par_allotted_total_usd"] = Decimal(0)
    for engagement in lookup.engagements_of_deal(deal_id):
        if engagement["status"] in ("REQUESTED", "UNDER_REVIEW", "INFO_REQUESTED"):
            engagement["status"] = "WITHDRAWN"
            db.touch(engagement)
    derive.cancel_scheduled_presentations(deal_id, "DEAL_CANCELLED")
    for enhancement in lookup.enhancements_of_deal(deal_id):
        if enhancement["status"] == "PROPOSED":
            enhancement["status"] = "DECLINED"
            db.touch(enhancement)
        elif enhancement["status"] == "COMMITTED":
            enhancement["status"] = "WITHDRAWN"
            enhancement["withdrawal_reason"] = "DEAL_CANCELLED"
            db.touch(enhancement)
    derive.recompute_disclosure_clearance(deal)
    db.touch(deal)
    return response.ok(serializers.deal(deal))
