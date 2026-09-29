"""Existence lookups (band 5) and shared list plumbing."""
from envelope import listing
from errors import ApiError
from store import db, by_seq
from validate import pagination, filters, match

ALL_ROLES = ["BrandAdministrator", "FranchiseOwner", "ClubManager", "ComplianceAuditor",
             "BillingPartner", "Member"]


def _get(table, key, error_id):
    record = table.get(key) if isinstance(key, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def get_franchisee(fid):
    return _get(db.franchisees, fid, "ERR_FRANCHISEE_NOT_FOUND")


def get_territory(tid):
    return _get(db.territories, tid, "ERR_TERRITORY_NOT_FOUND")


def get_club(cid):
    return _get(db.clubs, cid, "ERR_CLUB_NOT_FOUND")


def get_member(mid):
    return _get(db.members, mid, "ERR_MEMBER_NOT_FOUND")


def get_template(pid):
    return _get(db.plan_templates, pid, "ERR_PLAN_ASSET_NOT_FOUND")


def get_promotion(pid):
    return _get(db.promotions, pid, "ERR_PLAN_ASSET_NOT_FOUND")


def get_corporate(cid):
    return _get(db.corporate_accounts, cid, "ERR_PLAN_ASSET_NOT_FOUND")


def get_agreement(aid):
    return _get(db.agreements, aid, "ERR_MEMBERSHIP_RECORD_NOT_FOUND")


def get_transfer(tid):
    return _get(db.transfer_requests, tid, "ERR_MEMBERSHIP_RECORD_NOT_FOUND")


def get_guest_event(gid):
    return _get(db.guest_usage_events, gid, "ERR_MEMBERSHIP_RECORD_NOT_FOUND")


def get_billing_event(bid):
    return _get(db.billing_events, bid, "ERR_MEMBERSHIP_RECORD_NOT_FOUND")


def get_relocation(rid):
    return _get(db.relocation_requests, rid, "ERR_OPS_RECORD_NOT_FOUND")


def get_inspection(iid):
    return _get(db.inspections, iid, "ERR_OPS_RECORD_NOT_FOUND")


def get_settlement(sid):
    return _get(db.usage_settlements, sid, "ERR_OPS_RECORD_NOT_FOUND")


def get_report(rid):
    return _get(db.royalty_reports, rid, "ERR_OPS_RECORD_NOT_FOUND")


# --------------------------------------------------------------------------
# state gates shared by several endpoints
# --------------------------------------------------------------------------
def require_open(club):
    """Band 7: only an OPEN club may host an agreement or receive a transfer."""
    if club["status"] != "OPEN":
        raise ApiError("ERR_CLUB_NOT_OPERATIONAL")


def require_compliant(club):
    """Band 10: a NON_COMPLIANT club is not a safe facility."""
    if club["equipment_compliance_state"] == "NON_COMPLIANT":
        raise ApiError("ERR_CLUB_NOT_OPERATIONAL")


# --------------------------------------------------------------------------
# list endpoints
# --------------------------------------------------------------------------
def paged(table, *filter_names, **kwargs):
    """Filter -> canonical created_at ascending order -> envelope page."""
    limit, offset = pagination()
    supplied = filters(*filter_names)
    rows = kwargs.get("rows")
    if rows is None:
        rows = list(table.values())
    rows = [r for r in rows if match(r, supplied)]
    return listing(by_seq(rows), limit, offset)
