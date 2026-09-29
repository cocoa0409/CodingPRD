"""Existence resolution (PRD 2.6 rung 5) and shared list plumbing."""

import store
from envelope import ok_list
from errors import ApiError
from validation import pagination, paginate


def _need(collection, identifier, error_id):
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id, "No such resource: %s." % identifier)
    return row


def need_tier(identifier):
    return _need(store.program_tiers, identifier, "ERR_PROGRAM_CONFIG_NOT_FOUND")


def need_category(identifier):
    return _need(store.device_categories, identifier, "ERR_PROGRAM_CONFIG_NOT_FOUND")


def need_criterion(identifier):
    return _need(store.security_criteria, identifier, "ERR_CRITERION_NOT_FOUND")


def need_manufacturer(identifier):
    return _need(store.manufacturers, identifier, "ERR_MANUFACTURER_NOT_FOUND")


def need_product(identifier):
    return _need(store.products, identifier, "ERR_PRODUCT_NOT_FOUND")


def need_assessment(identifier):
    return _need(store.assessments, identifier, "ERR_ASSESSMENT_NOT_FOUND")


def need_response(identifier):
    return _need(store.criterion_responses, identifier, "ERR_CRITERION_NOT_FOUND")


def need_lab(identifier):
    return _need(store.test_labs, identifier, "ERR_TEST_LAB_NOT_FOUND")


def need_engagement(identifier):
    return _need(store.test_engagements, identifier, "ERR_ENGAGEMENT_NOT_FOUND")


def need_grant(identifier):
    return _need(store.label_grants, identifier, "ERR_GRANT_NOT_FOUND")


def need_retailer(identifier):
    return _need(store.retailers, identifier, "ERR_RETAILER_NOT_FOUND")


def need_authorization(identifier):
    return _need(store.display_authorizations, identifier, "ERR_AUTHORIZATION_NOT_FOUND")


def need_case(identifier):
    return _need(store.enforcement_cases, identifier, "ERR_CASE_NOT_FOUND")


def need_survey(identifier):
    return _need(store.recognition_surveys, identifier, "ERR_PROGRAM_CONFIG_NOT_FOUND")


def unique_or_reject(collection, field, value):
    """Uniqueness constraints are request-shape failures (ERR_INVALID_REQUEST)."""
    if store.find_unique(collection, field, value) is not None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be unique: %s." % (field, value))


def listing(rows, serializer):
    """Apply pagination to an already-sorted row list and build the envelope."""
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list([serializer(row) for row in page], limit=limit, offset=offset, total=total)


def resolve_fk(body, field, need):
    """Existence (rung 5) runs before request shape (rung 6): resolve a body
    foreign key when it is syntactically usable, and otherwise leave the
    complaint to the shape rung."""
    if not isinstance(body, dict):
        return None
    value = body.get(field)
    if isinstance(value, str) and value != "":
        return need(value)
    return None
