"""Shared route helpers: identifier resolution and the OCC guard.

Resolution order is fixed by validations[priority=3]: path identifiers resolve
left to right and the first unresolved one decides the response.
"""

from db import DB
from errors import ApiError


def partner_or_404(partner_id):
    record = DB.partner(partner_id)
    if not record:
        raise ApiError("ERR_PARTNER_NOT_FOUND")
    return record


def product_or_404(product_id):
    record = DB.product(product_id)
    if not record:
        raise ApiError("ERR_PRODUCT_NOT_FOUND")
    return record


def product_line_or_404(line_id):
    record = DB.product_line(line_id)
    if not record:
        raise ApiError("ERR_DONATION_PRODUCT_LINE_NOT_FOUND")
    return record


def order_or_404(order_id):
    record = DB.order(order_id)
    if not record:
        raise ApiError("ERR_SALES_ORDER_NOT_FOUND")
    return record


def order_line_or_404(order_id, line_id):
    """The line must exist AND belong to the addressed order."""
    record = DB.order_line(line_id)
    if not record or record.get("sales_order_id") != order_id:
        raise ApiError("ERR_SALES_ORDER_LINE_NOT_FOUND")
    return record


def sales_order_line_or_404(line_id):
    record = DB.order_line(line_id)
    if not record:
        raise ApiError("ERR_SALES_ORDER_LINE_NOT_FOUND")
    return record


def season_or_404(season_id):
    record = DB.season(season_id)
    if not record:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    return record


def liability_or_404(liability_id):
    record = DB.liability(liability_id)
    if not record:
        raise ApiError("ERR_LIABILITY_NOT_FOUND")
    return record


def claim_or_404(claim_id):
    record = DB.claim(claim_id)
    if not record:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return record


def allocation_or_404(allocation_id):
    record = DB.allocation(allocation_id)
    if not record:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    return record


def distribution_or_404(distribution_id):
    record = DB.distribution(distribution_id)
    if not record:
        raise ApiError("ERR_DISTRIBUTION_NOT_FOUND")
    return record


def audit_or_404(audit_id):
    record = DB.audit(audit_id)
    if not record:
        raise ApiError("ERR_AUDIT_NOT_FOUND")
    return record


def vetting_or_404(vetting_id):
    record = DB.vetting_round(vetting_id)
    if not record:
        raise ApiError("ERR_VETTING_ROUND_NOT_FOUND")
    return record


def return_or_404(return_id):
    record = DB.return_request(return_id)
    if not record:
        raise ApiError("ERR_RETURN_REQUEST_NOT_FOUND")
    return record


def profile_or_404(profile_id):
    record = DB.capacity_profile(profile_id)
    if not record:
        raise ApiError("ERR_CAPACITY_PROFILE_NOT_FOUND")
    return record


def occ_check(stored_version, expected_version):
    """validations[priority=7]: the echoed version must equal the stored one."""
    if expected_version != stored_version:
        raise ApiError("ERR_STALE_VERSION")
    return True


def season_of(season_id):
    return DB.season(season_id)