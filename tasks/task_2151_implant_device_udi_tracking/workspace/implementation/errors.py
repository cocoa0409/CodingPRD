"""Error catalog (PRD section 5) and the exception type carrying it."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_CATALOG_ITEM_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_DEVICE_UNIT_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_IMPLANT_RECORD_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_REGISTRY_SUBMISSION_NOT_FOUND": 404,
    "ERR_FIELD_ACTION_NOT_FOUND": 404,
    "ERR_RECALL_NOTIFICATION_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_EXPLANT_RECORD_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    # path-target state
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_INVALID_UNIT_STATE": 409,
    "ERR_INVALID_RECORD_STATE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_INVALID_LIFECYCLE_STATE": 409,
    # clinical safety / compliance
    "ERR_UNIT_RECALLED": 422,
    "ERR_UNIT_EXPIRED": 422,
    "ERR_UDI_INCOMPLETE": 422,
    "ERR_PATIENT_LINK_MISMATCH": 422,
    "ERR_REGISTRY_SUBMISSION_INCOMPLETE": 422,
    # cross-entity referential state
    "ERR_LOT_NOT_RELEASED": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_VENDOR_ON_HOLD": 409,
    # uniqueness / constraint
    "ERR_DUPLICATE_UDI_SERIAL": 409,
    "ERR_DUPLICATE_LOT_NUMBER": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_UNIT_ALREADY_INVOICED": 409,
    # temporal
    "ERR_OR_ROOM_CONFLICT": 409,
    "ERR_PATIENT_SCHEDULE_CONFLICT": 409,
    # selector
    "ERR_NO_ELIGIBLE_UNIT": 409,
    # workflow gates
    "ERR_CASE_READINESS_UNMET": 409,
    "ERR_REGISTRY_OUTSTANDING": 409,
    "ERR_RECALL_REMEDIATION_INCOMPLETE": 409,
    # fiscal
    "ERR_UNIT_NOT_BILLABLE": 409,
    "ERR_INVOICE_TOLERANCE_EXCEEDED": 422,
    "ERR_VARIANCE_ACK_MISMATCH": 422,
    "ERR_CHARGE_VARIANCE_UNRESOLVED": 409,
    "ERR_CREDIT_EXCEEDS_EXPECTED": 422,
    # transport-level fallbacks (never produced by a business rule)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# Path parameter -> not-found error id (resolved strictly left to right).
NOT_FOUND_FOR = {
    "vendor_id": "ERR_VENDOR_NOT_FOUND",
    "agreement_id": "ERR_AGREEMENT_NOT_FOUND",
    "consignment_agreement_id": "ERR_AGREEMENT_NOT_FOUND",
    "catalog_item_id": "ERR_CATALOG_ITEM_NOT_FOUND",
    "lot_id": "ERR_LOT_NOT_FOUND",
    "device_unit_id": "ERR_DEVICE_UNIT_NOT_FOUND",
    "replaced_unit_id": "ERR_DEVICE_UNIT_NOT_FOUND",
    "replacement_device_unit_id": "ERR_DEVICE_UNIT_NOT_FOUND",
    "patient_id": "ERR_PATIENT_NOT_FOUND",
    "case_id": "ERR_CASE_NOT_FOUND",
    "surgical_case_id": "ERR_CASE_NOT_FOUND",
    "implant_record_id": "ERR_IMPLANT_RECORD_NOT_FOUND",
    "charge_id": "ERR_CHARGE_NOT_FOUND",
    "submission_id": "ERR_REGISTRY_SUBMISSION_NOT_FOUND",
    "field_action_id": "ERR_FIELD_ACTION_NOT_FOUND",
    "notification_id": "ERR_RECALL_NOTIFICATION_NOT_FOUND",
    "invoice_id": "ERR_INVOICE_NOT_FOUND",
    "explant_record_id": "ERR_EXPLANT_RECORD_NOT_FOUND",
}
