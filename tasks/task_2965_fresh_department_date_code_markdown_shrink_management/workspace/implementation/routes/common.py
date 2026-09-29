"""Helpers shared by the route modules."""
import re

from db import ordered
from response import ok_list, public
from validate import paginate, pagination

DEPARTMENT_CODES = ("MEAT", "DELI", "BAKERY", "PRODUCE", "SEAFOOD", "DAIRY")
ACTIVE_SUSPENDED = ("ACTIVE", "SUSPENDED")
ITEM_STATUSES = ("ACTIVE", "DISCONTINUED")
LADDER_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
COMPLIANCE_STATUSES = ("COMPLIANT", "WATCH", "BLOCKED")
POLICY_PROFILES = ("STANDARD", "AGGRESSIVE", "CONSERVATIVE")
LOT_STATUSES = ("FRESH", "MARKED_DOWN", "DONATION_PENDING", "DONATED",
                "WITHDRAWN", "DEPLETED")
LABEL_STATUSES = ("QUEUED", "PRINTED", "APPLIED", "VOIDED")
LABEL_REASONS = ("LADDER_AUTO", "SELL_THROUGH", "MANUAL_OVERRIDE", "RE_LADDER")
CHECK_OUTCOMES = ("MATCH", "OVERCHARGE", "UNDERCHARGE")
ENFORCEMENT_ACTIONS = ("NONE", "PRICE_CORRECTION", "LOT_WITHDRAWN")
LOGISTICS_STATUSES = ("SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED",
                      "MISSED")
MANIFEST_STATUSES = ("DRAFT", "SEALED", "RECONCILED")
ASSIGNMENT_STATUSES = ("ASSIGNED", "PICKED_UP", "REJECTED")
SHRINK_CAUSE_CODES = ("SPOILAGE", "DAMAGE", "SAMPLING", "THEFT")
SHRINK_STATUSES = ("RECORDED", "VERIFIED", "DISPUTED", "POSTED", "VOIDED")
SHRINK_ORIGINS = ("MANUAL", "WITHDRAWAL_AUTO")
SWEEP_STATUSES = ("NOT_STARTED", "SWEPT")
DISPOSITION_STATUSES = ("PENDING", "REMEDIATED", "ESCALATED")
SEVERITIES = ("NONE", "MINOR", "MAJOR", "CRITICAL")
FINDING_STATUSES = ("OPEN", "RESOLVED", "WAIVED")
REMEDIATIONS = ("NONE", "WITHDRAWN")
RECOMMENDATION_STATUSES = ("DRAFT", "ISSUED", "SUPERSEDED")
RECOMMENDATION_METHODS = ("CHRONOLOGICAL_ACTUAL", "FORWARD_LOOKING_PROJECTED")
PRICING_VARIANTS = ("LADDER_DAYS", "SELL_THROUGH")

STORE_NUMBER_RE = re.compile(r"^[0-9]{4}$")
REGION_CODE_RE = re.compile(r"^[A-Z0-9-]+$")
UPC_RE = re.compile(r"^[0-9]{12}$")


def listing(records):
    """Paginated list read: always created_at ASC, never a client sort param."""
    limit, offset = pagination()
    rows = ordered(records)
    page, total = paginate(rows, limit, offset)
    return ok_list([public(row) for row in page], limit, offset, total)


def matches(record, field, value):
    return value is None or record.get(field) == value
