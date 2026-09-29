"""Path- and body-resource resolution with family-specific not-found ids."""
from errors import fail
from store import store


def _get(bucket, row_id, error_id):
    row = bucket.get(row_id)
    if row is None:
        fail(error_id, "no such resource: %s" % row_id)
    return row


def get_employee(row_id):
    return _get(store.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")


def get_module(row_id):
    return _get(store.modules, row_id, "ERR_MODULE_NOT_FOUND")


def get_assignment(row_id):
    return _get(store.assignments, row_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_template(row_id):
    return _get(store.templates, row_id, "ERR_TEMPLATE_NOT_FOUND")


def get_campaign(row_id):
    return _get(store.campaigns, row_id, "ERR_CAMPAIGN_NOT_FOUND")


def get_delivery(row_id):
    return _get(store.deliveries, row_id, "ERR_DELIVERY_NOT_FOUND")


def get_notice(row_id):
    return _get(store.notices, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_consequence(row_id):
    return _get(store.consequences, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_intervention(row_id):
    return _get(store.interventions, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_incident(row_id):
    return _get(store.incidents, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_window(row_id):
    return _get(store.windows, row_id, "ERR_RESOURCE_NOT_FOUND")
