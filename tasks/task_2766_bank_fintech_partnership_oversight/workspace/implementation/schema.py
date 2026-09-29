"""Enumerations and rank-18 request-schema validation (ERR_VALIDATION / 422)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from util import is_int, parse_iso

BUSINESS_MODELS = ["LENDING", "DEPOSIT_WALLET", "CARD_ISSUING", "PAYMENT_FACILITATION"]
FUNDING_STAGES = ["SEED", "SERIES_A", "SERIES_B_PLUS", "PUBLIC"]
PARTNER_STATUSES = ["PROSPECT", "IN_DILIGENCE", "DILIGENCE_PASSED", "DILIGENCE_FAILED",
                    "CONTRACTED", "LIVE", "WIND_DOWN", "TERMINATED"]
POSTURES = ["OPEN", "HEIGHTENED", "RESTRICTED", "FROZEN"]
TIERS = ["UNRATED", "TIER_1", "TIER_2", "TIER_3"]
REVIEW_TYPES = ["INITIAL", "RENEWAL"]
REVIEW_STATUSES = ["DRAFT", "SUBMITTED", "INFO_REQUESTED", "PASSED", "FAILED"]
OWNERS = ["BANK", "PARTNER", "SHARED"]
OVERSIGHT_RIGHTS = ["STANDARD", "ENHANCED", "FULL_ACCESS"]
TERMINATION_TRIGGERS = ["COMPLAINT_RATE", "RESERVE_SHORTFALL", "SANCTIONS_EVENT",
                        "CONCENTRATION_CAP", "GROWTH_BREACH", "VOLUNTARY"]
AGREEMENT_STATUSES = ["DRAFT", "PENDING_RISK_APPROVAL", "EXECUTED", "TERMINATED"]
MATERIAL_TYPES = ["AD", "DISCLOSURE", "APP_SCREEN", "EMAIL"]
PLACEMENT_CHANNELS = ["PAID_SOCIAL", "SEARCH", "IN_APP", "DIRECT_MAIL", "PARTNER_SITE"]
DISCLOSURE_ELEMENTS = ["APR", "FEE_SCHEDULE", "FDIC_SIGNAGE", "BANK_NAME",
                       "PASS_THROUGH_INSURANCE", "DISPUTE_RIGHTS"]
MARKETING_STATUSES = ["SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "EXPIRED"]
ACCOUNT_TYPES = ["FBO_END_USER", "RESERVE"]
ACCOUNT_STATUSES = ["ACTIVE", "FROZEN", "CLOSED"]
ENTRY_TYPES = ["END_USER_CREDIT", "END_USER_DEBIT", "RESERVE_FUND", "RESERVE_RELEASE",
               "FEE", "VARIANCE_ADJUSTMENT", "CLAWBACK"]
RECON_STATUSES = ["UNRECONCILED", "MATCHED", "VARIANCE_OPEN", "VARIANCE_CLEARED"]
FUNDING_STATUSES = ["UNFUNDED", "FUNDED", "CLAWED_BACK"]
CLAWBACK_REASONS = ["RECONCILIATION_ERROR", "PARTNER_FRAUD", "RESERVE_BREACH",
                    "DUPLICATE_FUNDING"]
COMPLAINT_CHANNELS = ["CFPB_PORTAL", "STATE_AG", "SOCIAL", "BANK_CALL_CENTER",
                      "PARTNER_APP", "EMAIL"]
COMPLAINT_CATEGORIES = ["FEES", "DISCLOSURE", "ACCOUNT_ACCESS",
                        "UNAUTHORIZED_TRANSACTION", "CREDIT_REPORTING", "SERVICING"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
COMPLAINT_STATUSES = ["RECEIVED", "ROOT_CAUSE_ASSIGNED", "ESCALATED", "RESOLVED",
                      "WITHDRAWN"]
ROOT_CAUSE_CODES = ["DISCLOSURE_DEFECT", "SYSTEM_OUTAGE", "FEE_CONFIG_ERROR",
                    "KYC_FRICTION", "VENDOR_ERROR", "PARTNER_TRAINING_GAP"]
ALERT_TYPES = ["STRUCTURING", "VELOCITY", "SANCTIONS_HIT", "ACH_RETURN_RATE"]
ALERT_DISPOSITIONS = ["OPEN", "PARTNER_RESPONSE_PENDING", "CLEARED", "SAR_FILED"]
CYCLE_STATUSES = ["OPEN", "CLOSING", "CLOSED"]
FUNDS_DISPOSITIONS = ["RETURN_TO_END_USERS", "TRANSFER_TO_SUCCESSOR_BANK", "ESCHEAT"]
MILESTONES = ["STOP_NEW_ACCOUNTS", "NOTIFY_END_USERS", "FINAL_SETTLEMENT",
              "RETURN_FUNDS", "CLOSE_CUSTODY"]
PLAN_STATUSES = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "IN_EXECUTION", "COMPLETED"]


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None):
    if not _present(data, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % name)
    if len(value.strip()) < min_len if min_len else False:
        fail("ERR_VALIDATION", "%s must not be blank" % name)
    if len(value) < min_len:
        fail("ERR_VALIDATION", "%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "%s exceeds %d characters" % (name, max_len))
    return value


def opt_str(data, name, default=None, min_len=0, max_len=None):
    if not _present(data, name):
        return default
    return req_str(data, name, min_len=min_len, max_len=max_len)


def req_enum(data, name, allowed):
    if not _present(data, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = data[name]
    if not is_int(value):
        fail("ERR_VALIDATION", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s" % (name, maximum))
    return value


def opt_int(data, name, default=0, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_decimal(data, name, minimum=None, maximum=None, exclusive_min=None):
    if not _present(data, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    if not dec.is_finite():
        fail("ERR_VALIDATION", "%s must be a finite number" % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        fail("ERR_VALIDATION", "%s must be > %s" % (name, exclusive_min))
    if maximum is not None and dec > Decimal(str(maximum)):
        fail("ERR_VALIDATION", "%s must be <= %s" % (name, maximum))
    return dec


def req_bool(data, name, default=None):
    if not _present(data, name):
        if default is None:
            fail("ERR_VALIDATION", "%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


def req_dt(data, name):
    if not _present(data, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    parsed = parse_iso(data[name])
    if parsed is None:
        fail("ERR_VALIDATION", "%s must be an ISO-8601 instant" % name)
    return parsed


def req_enum_array(data, name, allowed, non_empty=True, default=None):
    if not _present(data, name):
        if default is None:
            fail("ERR_VALIDATION", "%s is required" % name)
        return list(default)
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "%s must be an array" % name)
    if non_empty and not value:
        fail("ERR_VALIDATION", "%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_VALIDATION", "%s contains an unrecognised member" % name)
    return list(value)


def req_str_array(data, name, non_empty=True, default=None):
    if not _present(data, name):
        if default is None:
            fail("ERR_VALIDATION", "%s is required" % name)
        return list(default)
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "%s must be an array" % name)
    if non_empty and not value:
        fail("ERR_VALIDATION", "%s must be a non-empty array of strings" % name)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_VALIDATION", "%s must contain strings only" % name)
    return list(value)


def filter_enum(name, allowed):
    """Query-string filter whose value must be a recognised enum member."""
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_VALIDATION", "%s filter must be one of %s" % (name, ", ".join(allowed)))
    return value


def filter_str(name):
    return request.args.get(name)
