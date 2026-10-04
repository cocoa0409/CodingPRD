"""Existence lookups that raise the catalogued 404 error for a given id."""

import errors
import storage

NOT_FOUND = {
    "accounts": "ERR_ACCOUNT_NOT_FOUND",
    "subscriber_lines": "ERR_SUBSCRIBER_LINE_NOT_FOUND",
    "port_requests": "ERR_PORT_REQUEST_NOT_FOUND",
    "number_reservations": "ERR_RESERVATION_NOT_FOUND",
    "port_protection_cases": "ERR_PROTECTION_CASE_NOT_FOUND",
    "migration_requests": "ERR_MIGRATION_REQUEST_NOT_FOUND",
    "line_addition_requests": "ERR_LINE_ADDITION_REQUEST_NOT_FOUND",
    "trade_in_assessments": "ERR_TRADE_IN_ASSESSMENT_NOT_FOUND",
    "device_installment_plans": "ERR_INSTALLMENT_PLAN_NOT_FOUND",
    "promo_credit_schedules": "ERR_PROMO_SCHEDULE_NOT_FOUND",
}

MESSAGES = {
    "ERR_ACCOUNT_NOT_FOUND": "No account exists for the supplied id.",
    "ERR_SUBSCRIBER_LINE_NOT_FOUND": "No subscriber line exists for the supplied id.",
    "ERR_PORT_REQUEST_NOT_FOUND": "No port request exists for the supplied id.",
    "ERR_RESERVATION_NOT_FOUND": "No number reservation exists for the supplied id.",
    "ERR_PROTECTION_CASE_NOT_FOUND": "No protection case exists for the supplied id.",
    "ERR_MIGRATION_REQUEST_NOT_FOUND": "No migration request exists for the supplied id.",
    "ERR_LINE_ADDITION_REQUEST_NOT_FOUND": "No line addition request exists for the supplied id.",
    "ERR_TRADE_IN_ASSESSMENT_NOT_FOUND": "No trade-in assessment exists for the supplied id.",
    "ERR_INSTALLMENT_PLAN_NOT_FOUND": "No installment plan exists for the supplied id.",
    "ERR_PROMO_SCHEDULE_NOT_FOUND": "No promotional credit schedule exists for the supplied id.",
}


def fetch(collection, entity_id):
    """Return the record, or raise the collection's not-found error."""
    record = storage.db.get(collection, entity_id)
    if record is None:
        error_id = NOT_FOUND.get(collection, "ERR_INVALID_REQUEST")
        if error_id == "ERR_PROMO_SCHEDULE_NOT_FOUND":
            error_id = "ERR_INVALID_REQUEST"
        errors.fail(error_id, MESSAGES.get(error_id))
    return record


def line(line_id):
    return fetch("subscriber_lines", line_id)


def account(account_id):
    return fetch("accounts", account_id)


def port_request(request_id):
    return fetch("port_requests", request_id)


def reservation(reservation_id):
    return fetch("number_reservations", reservation_id)


def protection_case(case_id):
    return fetch("port_protection_cases", case_id)


def migration(migration_id):
    return fetch("migration_requests", migration_id)


def addition(addition_id):
    return fetch("line_addition_requests", addition_id)


def assessment(assessment_id):
    return fetch("trade_in_assessments", assessment_id)


def plan(plan_id):
    return fetch("device_installment_plans", plan_id)