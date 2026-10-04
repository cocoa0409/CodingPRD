"""PRD 2.5 rung 5 (existence) and shared list plumbing."""
from errors import ApiError
from response import listing
from store import db, by_seq
from validate import filters, match, pagination
import derived

HUMAN_KEY = {
    "Brand": "brand_code",
    "Franchisee": "legal_name",
    "Territory": "territory_code",
    "FranchiseAgreement": "agreement_number",
    "Referral": "referral_code",
    "Lead": None,
    "NationalAccount": None,
    "WorkOrder": None,
    "BrandStandardsAudit": None,
    "RoyaltyStatement": None,
    "TerritoryAssignment": None,
    "TransferApplication": None,
}


def _get(table, key, error_id):
    record = table.get(key) if isinstance(key, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def get_brand(brand_id):
    return _get(db.brands, brand_id, "ERR_BRAND_NOT_FOUND")


def get_franchisee(franchisee_id):
    return _get(db.franchisees, franchisee_id, "ERR_FRANCHISEE_NOT_FOUND")


def get_territory(territory_id):
    return _get(db.territories, territory_id, "ERR_TERRITORY_NOT_FOUND")


def get_agreement(agreement_id):
    return _get(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def get_referral(referral_id):
    return _get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")


def get_lead(lead_id):
    return _get(db.leads, lead_id, "ERR_LEAD_NOT_FOUND")


def get_account(account_id):
    return _get(db.national_accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")


def get_work_order(work_order_id):
    return _get(db.work_orders, work_order_id, "ERR_WORK_ORDER_NOT_FOUND")


def get_audit(audit_id):
    return _get(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")


def get_statement(statement_id):
    return _get(db.statements, statement_id, "ERR_STATEMENT_NOT_FOUND")


def get_transfer(application_id):
    return _get(db.transfer_applications, application_id, "ERR_TRANSFER_APPLICATION_NOT_FOUND")


def get_assignment(assignment_id):
    return _get(db.territory_assignments, assignment_id, "ERR_TRANSFER_APPLICATION_NOT_FOUND")


def paged(table, *filter_names, rows=None):
    """Filter -> canonical order (created_at asc, human key asc) -> envelope page."""
    limit, offset = pagination()
    supplied = filters(*filter_names)
    if rows is None:
        rows = list(table.values())
    rows = [r for r in rows if match(r, supplied)]
    return listing(ordered(table, rows), limit, offset)


def ordered(table, rows):
    """Default list order: creation timestamp ascending.

    Records sharing a created_at instant fall back to the entity's human
    readable key ascending, so random identifiers never decide an outcome.
    """
    human = None
    for record in rows:
        human = HUMAN_KEY.get(record.get("_kind"))
        break
    if human:
        return derived.ordered_by_created(rows, human)
    return derived.ordered_by_created(rows)


def assignments_for_territory(territory_id):
    return [a for a in db.territory_assignments.values() if a.get("territory_id") == territory_id]


def live_assignments_for_territory(territory_id):
    return [a for a in db.territory_assignments.values()
            if a.get("territory_id") == territory_id and a.get("released_on") is None]


def synthesize_assignment(territory_id, franchisee_id, source_agreement_id, kind):
    """A TerritoryAssignment records a holding (PRD 2.6)."""
    from store import common_fields, now_iso, db as _db

    record = common_fields()
    record.update({
        "_kind": "TerritoryAssignment",
        "territory_id": territory_id,
        "franchisee_id": franchisee_id,
        "source_agreement_id": source_agreement_id,
        "assignment_kind": kind,
        "assigned_on": now_iso(),
        "released_on": None,
        "active": True,
    })
    _db.territory_assignments[record["id"]] = record
    return record