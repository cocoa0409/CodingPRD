"""Shared route helpers: body parsing, path-param resolution, pagination.

Path-param resolution follows PRD §2.5: identifiers resolve left to right and
the first unresolvable identifier rejects with its resource-specific 404 before
any business rule for the operation is evaluated.

Pagination parameter names, defaults and bounds come from
`response_envelope.pagination_fields` / `pagination_defaults`.
"""

from flask import request

from db import DB, parse_iso8601, as_int
from errors import ApiError
from serializers import serialize

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


def get_one(collection, key, error_id):
    obj = getattr(DB, collection).get(key)
    if obj is None:
        raise ApiError(error_id)
    return obj


# The identifier-to-code mapping is fixed by PRD §2.5.
def get_account(account_id):
    return get_one("hospital_accounts", account_id, "ERR_ACCOUNT_NOT_FOUND")


def get_agreement(agreement_id):
    return get_one("placement_agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def get_system(system_id):
    return get_one("robot_systems", system_id, "ERR_SYSTEM_NOT_FOUND")


def get_review(review_id):
    return get_one("site_readiness_reviews", review_id, "ERR_READINESS_REVIEW_NOT_FOUND")


def get_expansion_review(review_id):
    return get_one("expansion_reviews", review_id, "ERR_EXPANSION_REVIEW_NOT_FOUND")


def get_case(case_id):
    return get_one("procedure_cases", case_id, "ERR_CASE_NOT_FOUND")


def get_record(record_id):
    return get_one("surgeon_training_records", record_id, "ERR_TRAINING_RECORD_NOT_FOUND")


def get_evidence(evidence_id):
    return get_one("credentialing_evidence", evidence_id, "ERR_EVIDENCE_NOT_FOUND")


def get_contract(contract_id):
    return get_one("service_contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")


def get_incident(incident_id):
    return get_one("incidents", incident_id, "ERR_INCIDENT_NOT_FOUND")


def get_config(config_id):
    return get_one("system_configurations", config_id, "ERR_CONFIGURATION_NOT_FOUND")


def get_deployment(deployment_id):
    return get_one("software_deployments", deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")


def get_release(release_id):
    return get_one("software_releases", release_id, "ERR_SOFTWARE_RELEASE_NOT_FOUND")


def get_dispatch(dispatch_id):
    return get_one("loaner_dispatches", dispatch_id, "ERR_LOANER_DISPATCH_NOT_FOUND")


def get_proctor_case(proctor_case_id):
    return get_one("proctor_cases", proctor_case_id, "ERR_PROCTOR_CASE_NOT_FOUND")


def get_ledger(ledger_id):
    return get_one("consumption_ledgers", ledger_id, "ERR_LEDGER_NOT_FOUND")


def get_transfer(transaction_id):
    return get_one("transfer_transactions", transaction_id, "ERR_TRANSFER_NOT_FOUND")


def get_cycle(cycle_id):
    return get_one("utilization_cycles", cycle_id, "ERR_INVALID_REQUEST")


# ---------------------------------------------------------------------------
# Body field helpers
# ---------------------------------------------------------------------------

def require(body, field):
    if field not in body or body.get(field) is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return body.get(field)


def require_int(body, field, default=None):
    value = body.get(field)
    if value is None:
        if default is None:
            raise ApiError("ERR_INVALID_REQUEST")
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST")


def optional_int(body, field, default=None):
    value = body.get(field)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST")


def require_str(body, field):
    value = body.get(field)
    if value is None or not str(value).strip():
        raise ApiError("ERR_INVALID_REQUEST")
    return str(value).strip()


def require_dt(body, field):
    value = body.get(field)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST")
    parsed = parse_iso8601(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return parsed


def optional_dt(body, field):
    value = body.get(field)
    if value is None:
        return None
    parsed = parse_iso8601(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return parsed


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------

def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def arg_int(name):
    value = arg(name)
    if value is None:
        return None
    return as_int(value, None)


def arg_dt(name):
    value = arg(name)
    if value is None:
        return None
    return parse_iso8601(value)


def arg_bool(name):
    value = arg(name)
    if value is None:
        return None
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3, ordered by created_at ascending
# ---------------------------------------------------------------------------

def paginate(records, collection):
    limit = as_int(request.args.get("limit"), DEFAULT_LIMIT)
    offset = as_int(request.args.get("offset"), 0)
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    ordered = sorted(records, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(collection, r) for r in page], limit, offset, total


def paged(records, collection):
    """Return the standard list envelope for a page of `records`."""
    from response import list_success
    payload, limit, offset, total = paginate(records, collection)
    return list_success(payload, limit=limit, offset=offset, total_count=total)