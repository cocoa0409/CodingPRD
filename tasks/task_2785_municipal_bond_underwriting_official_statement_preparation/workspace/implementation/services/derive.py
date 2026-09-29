"""Derived fields, recomputation and the cascading side effects (PRD 2.4, 2.8, 2.9)."""
from decimal import Decimal

import db
import lookup
from services import calc
from validation import dec, q2

MANDATORY_SECTION_TYPES = (
    "RISK_FACTOR",
    "TAX_MATTERS",
    "CONTINUING_DISCLOSURE",
    "UNDERWRITING",
)

CLEARED_STATUSES = ("IN_REVIEW", "PRELIMINARY_POSTED", "FINAL_POSTED")
BLOCKED_STATUSES = ("REVISION_REQUESTED", "WITHDRAWN")


def governing_statement(deal_id):
    """PRD 2.9: the governing statement is the most recently created one."""
    statements = lookup.statements_of_deal(deal_id)
    if not statements:
        return None
    statements.sort(key=lambda row: (row["created_at"], row["_seq"]))
    return statements[-1]


def compute_mandatory_sections_approved(statement):
    sections = lookup.sections_of_statement(statement["id"])
    approved = [row for row in sections if row["review_status"] == "APPROVED"]
    for section_type in MANDATORY_SECTION_TYPES:
        if not any(row["section_type"] == section_type for row in approved):
            return False
    if not any(
        row["section_type"] == "RISK_FACTOR" and row["is_material_risk"] for row in approved
    ):
        return False
    return True


def apply_mandatory_sections_approved(statement):
    value = compute_mandatory_sections_approved(statement)
    changed = statement["mandatory_sections_approved"] != value
    statement["mandatory_sections_approved"] = value
    return changed


def compute_disclosure_clearance(deal):
    statement = governing_statement(deal["id"])
    if statement is None:
        return "PENDING"
    if statement["mandatory_sections_approved"] and statement["status"] in CLEARED_STATUSES:
        return "CLEARED"
    if not statement["mandatory_sections_approved"] and statement["status"] in BLOCKED_STATUSES:
        return "BLOCKED"
    return "PENDING"


def recompute_disclosure_clearance(deal):
    value = compute_disclosure_clearance(deal)
    changed = deal["disclosure_clearance"] != value
    deal["disclosure_clearance"] = value
    return changed


def unapprove_sections(statement, predicate):
    """Move APPROVED sections matching predicate to NEEDS_REVISION."""
    touched = []
    for section in lookup.sections_of_statement(statement["id"]):
        if section["review_status"] != "APPROVED":
            continue
        if not predicate(section):
            continue
        section["review_status"] = "NEEDS_REVISION"
        section["approved_by_user_id"] = None
        db.touch(section)
        touched.append(section)
    return touched


def cancel_scheduled_presentations(deal_id, reason):
    cancelled = []
    for presentation in lookup.presentations_of_deal(deal_id):
        if presentation["status"] != "SCHEDULED":
            continue
        presentation["status"] = "CANCELLED"
        presentation["cancellation_reason"] = reason
        db.touch(presentation)
        cancelled.append(presentation)
    return cancelled


def active_undertaking(deal_id):
    for undertaking in lookup.undertakings_of_deal(deal_id):
        if undertaking["status"] == "ACTIVE":
            return undertaking
    return None


def committed_enhancement(deal_id):
    for enhancement in lookup.enhancements_of_deal(deal_id):
        if enhancement["status"] == "COMMITTED":
            return enhancement
    return None


def insured_tranches(deal_id):
    enhancement = committed_enhancement(deal_id)
    if enhancement is None:
        return []
    ids = set(enhancement["insured_tranche_ids"])
    return [row for row in lookup.tranches_of_deal(deal_id) if row["id"] in ids]


def recompute_net_proceeds(deal):
    """Money identity maintained from the stored components (PRD 2.8)."""
    if deal["issue_price_total_usd"] is None or deal["gross_spread_total_usd"] is None:
        return False
    value = calc.net_proceeds(
        deal["issue_price_total_usd"],
        deal["gross_spread_total_usd"],
        deal["credit_enhancement_premium_usd"],
    )
    changed = deal["net_proceeds_to_issuer_usd"] != value
    deal["net_proceeds_to_issuer_usd"] = value
    return changed


def recompute_tranche_par(tranche):
    allotted = Decimal(0)
    for order in lookup.orders_of_tranche(tranche["id"]):
        if order["status"] in ("ALLOTTED", "PARTIALLY_ALLOTTED"):
            allotted += dec(order["par_allotted_usd"])
    unsold = dec(tranche["principal_amount_usd"]) - allotted
    changed = (
        dec(tranche["par_allotted_usd"]) != allotted
        or dec(tranche["par_unsold_usd"]) != unsold
    )
    tranche["par_allotted_usd"] = allotted
    tranche["par_unsold_usd"] = unsold
    if changed:
        db.touch(tranche)
    return changed


def recompute_deal_par_allotted_total(deal):
    total = Decimal(0)
    for tranche in lookup.tranches_of_deal(deal["id"]):
        total += dec(tranche["par_allotted_usd"])
    changed = dec(deal["par_allotted_total_usd"]) != total
    deal["par_allotted_total_usd"] = total
    return changed


def recompute_takedown_credits(deal):
    for member in lookup.active_members_of_deal(deal["id"]):
        value = calc.takedown_credit_for_member(member, deal)
        if member["takedown_credit_usd"] != value:
            member["takedown_credit_usd"] = value
            db.touch(member)


def recompute_period_counters(period):
    orders = lookup.orders_of_period(period["id"])
    received = len([row for row in orders if row["status"] != "CANCELLED"])
    allotted = len(
        [row for row in orders if row["status"] in ("ALLOTTED", "PARTIALLY_ALLOTTED")]
    )
    changed = (
        period["orders_received_count"] != received
        or period["allotted_order_count"] != allotted
    )
    period["orders_received_count"] = received
    period["allotted_order_count"] = allotted
    return changed
