"""The 47-entry error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


ERROR_STATUS = {
    # authentication and authorization
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_WRONG_PERMIT_PARTY": 403,
    # request shape
    "ERR_MISSING_REQUIRED_FIELD": 422,
    "ERR_INVALID_FIELD_TYPE": 422,
    "ERR_FIELD_OUT_OF_RANGE": 422,
    # existence
    "ERR_SERVICE_CATEGORY_NOT_FOUND": 404,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_INSTALLER_NOT_FOUND": 404,
    "ERR_INSTALLER_CREDENTIAL_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_MEASUREMENT_NOT_FOUND": 404,
    "ERR_CHANGE_ORDER_NOT_FOUND": 404,
    "ERR_MATERIAL_DELIVERY_NOT_FOUND": 404,
    "ERR_INSTALLER_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PUNCH_LIST_ITEM_NOT_FOUND": 404,
    "ERR_WARRANTY_CLAIM_NOT_FOUND": 404,
    # uniqueness and optimistic concurrency
    "ERR_DUPLICATE_CODE": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_INSTALLER_VERSION": 412,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_PROJECT_CANCELLED": 409,
    "ERR_REFERENCE_NOT_ELIGIBLE": 409,
    # safety, licensing and compliance
    "ERR_INSTALLER_NOT_ASSIGNABLE": 409,
    "ERR_INSTALLER_NOT_LICENSED": 409,
    "ERR_BACKGROUND_CHECK_STALE": 409,
    "ERR_INSURANCE_INSUFFICIENT": 409,
    "ERR_MEASUREMENT_STALE": 409,
    "ERR_PUNCH_LIST_NOT_CLEARED": 409,
    "ERR_INSPECTION_NOT_PASSED": 409,
    # temporal, capacity and constraint satisfaction
    "ERR_INSTALLER_WINDOW_CONFLICT": 409,
    "ERR_INSTALLER_CAPACITY_EXCEEDED": 409,
    "ERR_DELIVERY_SLACK_INSUFFICIENT": 409,
    "ERR_INSPECTION_LEAD_TIME": 422,
    "ERR_INSPECTION_CAPACITY_FULL": 409,
    "ERR_CHANGE_ORDER_SHAPE": 422,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_REINSTATE_WINDOW_CLOSED": 409,
    "ERR_REMOVAL_NOT_ELIGIBLE": 409,
    # fiscal, evaluated last
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 422,
    "ERR_DEPOSIT_NOT_HELD": 409,
    "ERR_BALANCE_AMOUNT_MISMATCH": 422,
    "ERR_CREDIT_EXCEEDS_CAP": 422,
    "ERR_NOT_CANCELLABLE": 409,
}

DEFAULT_MESSAGE = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role are both required.",
    "ERR_UNAUTHORIZED_ROLE": "The acting role may not call this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own this resource.",
    "ERR_WRONG_PERMIT_PARTY": "The acting role does not match the project's permit responsibility.",
    "ERR_MISSING_REQUIRED_FIELD": "A required field is absent or null.",
    "ERR_INVALID_FIELD_TYPE": "A field has the wrong type or an undeclared enum value.",
    "ERR_FIELD_OUT_OF_RANGE": "A field violates its range or length constraint.",
    "ERR_DUPLICATE_CODE": "The supplied code is already in use.",
    "ERR_STALE_PROJECT_VERSION": "expected_project_version does not match the project's current version.",
    "ERR_STALE_INSTALLER_VERSION": "expected_installer_version does not match the installer's current version.",
    "ERR_INVALID_STATE": "The target entity's current status has no transition for this trigger.",
    "ERR_ALREADY_TERMINAL": "The target entity is already in a terminal state.",
    "ERR_PROJECT_CANCELLED": "The owning project is cancelled.",
    "ERR_REFERENCE_NOT_ELIGIBLE": "A referenced row exists but is not eligible.",
    "ERR_INSTALLER_NOT_ASSIGNABLE": "The installer's network status does not permit assignment.",
    "ERR_INSTALLER_NOT_LICENSED": "The installer holds no verified credential for this jurisdiction and trade.",
    "ERR_BACKGROUND_CHECK_STALE": "The installer's background check is missing, failed or stale.",
    "ERR_INSURANCE_INSUFFICIENT": "The installer's liability insurance is expired or below the jurisdiction minimum.",
    "ERR_MEASUREMENT_STALE": "The project has no usable completed measurement for this window.",
    "ERR_PUNCH_LIST_NOT_CLEARED": "The punch list blocks this operation.",
    "ERR_INSPECTION_NOT_PASSED": "The permit dimension has not reached CLOSED.",
    "ERR_INSTALLER_WINDOW_CONFLICT": "The requested window conflicts with a live assignment.",
    "ERR_INSTALLER_CAPACITY_EXCEEDED": "The installer's committed minutes cap would be exceeded.",
    "ERR_DELIVERY_SLACK_INSUFFICIENT": "The material delivery does not give enough slack before the window.",
    "ERR_INSPECTION_LEAD_TIME": "The requested inspection slot violates the jurisdiction lead time.",
    "ERR_INSPECTION_CAPACITY_FULL": "The jurisdiction's concurrent inspection capacity is full.",
    "ERR_CHANGE_ORDER_SHAPE": "The change order's shape does not match its origin.",
    "ERR_WARRANTY_EXPIRED": "The labour warranty does not cover this claim.",
    "ERR_REINSTATE_WINDOW_CLOSED": "The reinstatement window has closed.",
    "ERR_REMOVAL_NOT_ELIGIBLE": "The installer is not eligible for removal.",
    "ERR_DEPOSIT_AMOUNT_MISMATCH": "amount_cents must equal deposit_required_cents exactly.",
    "ERR_DEPOSIT_NOT_HELD": "The project's deposit is not held.",
    "ERR_BALANCE_AMOUNT_MISMATCH": "amount_cents must equal balance_due_cents exactly.",
    "ERR_CREDIT_EXCEEDS_CAP": "The change order credit exceeds the credit cap.",
    "ERR_NOT_CANCELLABLE": "The project cannot be cancelled or closed from its current state.",
}

NOT_FOUND = {
    "service_categories": "ERR_SERVICE_CATEGORY_NOT_FOUND",
    "jurisdictions": "ERR_JURISDICTION_NOT_FOUND",
    "installers": "ERR_INSTALLER_NOT_FOUND",
    "installer_credentials": "ERR_INSTALLER_CREDENTIAL_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
    "measurements": "ERR_MEASUREMENT_NOT_FOUND",
    "change_orders": "ERR_CHANGE_ORDER_NOT_FOUND",
    "material_deliveries": "ERR_MATERIAL_DELIVERY_NOT_FOUND",
    "installer_assignments": "ERR_INSTALLER_ASSIGNMENT_NOT_FOUND",
    "punch_list_items": "ERR_PUNCH_LIST_ITEM_NOT_FOUND",
    "warranty_claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
}
