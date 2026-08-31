"""Error catalogue (PRD section 5) and the ApiError exception."""
from __future__ import annotations

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    # existence
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_DEPARTMENT_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_DEVICE_MODEL_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_PM_TASK_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_LOANER_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_RECALL_NOTICE_NOT_FOUND": 404,
    "ERR_RECALL_MATCH_NOT_FOUND": 404,
    "ERR_SERVICE_CONTRACT_NOT_FOUND": 404,
    "ERR_SECURITY_FINDING_NOT_FOUND": 404,
    # request shape / uniqueness
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_FACILITY_CODE": 409,
    # optimistic concurrency
    "ERR_STALE_WORK_ORDER_VERSION": 412,
    "ERR_STALE_DEPARTMENT_VERSION": 412,
    # state
    "ERR_INVALID_WORK_ORDER_STATE": 409,
    "ERR_INVALID_PM_TASK_STATE": 409,
    "ERR_INVALID_RECALL_STATE": 409,
    "ERR_INVALID_RECALL_MATCH_STATE": 409,
    "ERR_INVALID_LOANER_STATE": 409,
    "ERR_INVALID_SECURITY_STATE": 409,
    "ERR_DEVICE_RETIRED": 409,
    # safety / compliance
    "ERR_DEVICE_QUARANTINED": 422,
    "ERR_SECURITY_FINDING_OPEN": 422,
    "ERR_FACILITY_LOCKDOWN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # loaner pool
    "ERR_LOANER_NOT_IN_POOL": 422,
    "ERR_LOANER_SECURITY_INELIGIBLE": 422,
    "ERR_LOANER_UNAVAILABLE": 409,
    "ERR_LOANER_INTERVAL_CONFLICT": 409,
    "ERR_NO_LOANER_AVAILABLE": 409,
    # business constraints
    "ERR_CONTRACT_COVERAGE_OVERLAP": 409,
    "ERR_PM_OUTSIDE_WINDOW": 422,
    "ERR_DEFERRAL_LIMIT_EXCEEDED": 422,
    "ERR_RECALL_MATCHES_PENDING": 409,
    "ERR_VENDOR_NOT_APPROVED": 422,
    # fiscal
    "ERR_DEPARTMENT_BUDGET_ON_HOLD": 402,
}

NOT_FOUND_FOR = {
    "Facility": "ERR_FACILITY_NOT_FOUND",
    "Department": "ERR_DEPARTMENT_NOT_FOUND",
    "Vendor": "ERR_VENDOR_NOT_FOUND",
    "DeviceModel": "ERR_DEVICE_MODEL_NOT_FOUND",
    "Device": "ERR_DEVICE_NOT_FOUND",
    "PMTask": "ERR_PM_TASK_NOT_FOUND",
    "WorkOrder": "ERR_WORK_ORDER_NOT_FOUND",
    "LoanerAssignment": "ERR_LOANER_ASSIGNMENT_NOT_FOUND",
    "RecallNotice": "ERR_RECALL_NOTICE_NOT_FOUND",
    "RecallMatch": "ERR_RECALL_MATCH_NOT_FOUND",
    "ServiceContract": "ERR_SERVICE_CONTRACT_NOT_FOUND",
    "SecurityFinding": "ERR_SECURITY_FINDING_NOT_FOUND",
}


class ApiError(Exception):
    def __init__(self, error_id: str, message: str = None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id: str) -> str:
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def bad_request(message: str = None) -> ApiError:
    return ApiError("ERR_INVALID_REQUEST", message)
