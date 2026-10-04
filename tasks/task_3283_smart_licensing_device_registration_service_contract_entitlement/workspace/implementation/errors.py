"""Error classes and the scaffold error catalog."""

HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_NON_COMPLIANT": 409,
    "ERR_PRODUCT_END_OF_LIFE": 409,
    "ERR_PRODUCT_END_OF_SUPPORT": 422,
    "ERR_SELF_APPROVAL_FORBIDDEN": 403,
    "ERR_CONTRACT_WINDOW_INVALID": 422,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_REPORT_POOL_MISMATCH": 422,
    "ERR_STALE_REPORT": 422,
    "ERR_INSUFFICIENT_TRANSFERABLE": 422,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_NO_ACTIVE_COVERAGE": 422,
    "ERR_RMA_BRANCH_VIOLATION": 409,
    "ERR_DUPLICATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_TIER_DOWNGRADE_FORBIDDEN": 422,
}

MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_FORBIDDEN": "Role is not permitted to perform this operation.",
    "ERR_NOT_FOUND": "Referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "Missing required field, wrong type, or invalid enum value.",
    "ERR_INVALID_STATE": "Resource is not in a state that supports this transition.",
    "ERR_ACCOUNT_NOT_ACTIVE": "Owning smart account is not ACTIVE.",
    "ERR_ACCOUNT_NON_COMPLIANT": "Owning smart account is NON_COMPLIANT.",
    "ERR_PRODUCT_END_OF_LIFE": "Product family has an in-effect END_OF_LIFE milestone.",
    "ERR_PRODUCT_END_OF_SUPPORT": "Product family has an in-effect END_OF_SUPPORT milestone.",
    "ERR_SELF_APPROVAL_FORBIDDEN": "Partner-initiated request cannot be approved by the partner side.",
    "ERR_CONTRACT_WINDOW_INVALID": "Contract window invalid or clock outside the coverage window.",
    "ERR_COVERAGE_OVERLAP": "Device already has an ACTIVE coverage.",
    "ERR_REPORT_POOL_MISMATCH": "Usage report line references a pool outside the device's virtual account.",
    "ERR_STALE_REPORT": "Usage report reported_at is earlier than the last accepted report.",
    "ERR_INSUFFICIENT_TRANSFERABLE": "Source pool has insufficient un-consumed balance.",
    "ERR_INVALID_QUANTITY": "Quantity out of bounds.",
    "ERR_NO_ACTIVE_COVERAGE": "No active hardware-capable coverage authorizes this RMA.",
    "ERR_RMA_BRANCH_VIOLATION": "RMA transition inconsistent with the contract's service level branch.",
    "ERR_DUPLICATE": "Uniqueness constraint violated.",
    "ERR_STALE_VERSION": "Expected version does not match the current version.",
    "ERR_TIER_DOWNGRADE_FORBIDDEN": "Tier upgrade target must be strictly above the current tier.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP[error_id]
        self.message = message or MESSAGES[error_id]
