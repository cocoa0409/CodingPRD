"""Charge ledger routes (read-only for clients)."""
from flask import Blueprint, request

import store
from response import success_list
from serializers import ser_charge
from util import find_or_404, pagination_params, require_auth, sort_by_created

bp = Blueprint("charges", __name__)


def _filter_charges(items):
    kind_filter = request.args.get("kind")
    if kind_filter:
        items = [c for c in items if c["kind"] == kind_filter]
    ref_type = request.args.get("reference_type")
    if ref_type:
        items = [c for c in items if c["reference_type"] == ref_type]
    ref_id = request.args.get("reference_id")
    if ref_id:
        items = [c for c in items if c["reference_id"] == ref_id]
    return items


@bp.get("/messaging/accounts/<account_id>/charges")
def list_account_charges(account_id):
    require_auth(["PlatformAdmin", "ComplianceOfficer", "CampaignManager"])
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [c for c in store.CHARGES.values() if c["account_id"] == account_id]
    items = _filter_charges(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_charge(c) for c in page], limit, offset, total)


@bp.get("/messaging/charges")
def list_charges():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.CHARGES.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [c for c in items if c["account_id"] == account_filter]
    items = _filter_charges(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_charge(c) for c in page], limit, offset, total)
