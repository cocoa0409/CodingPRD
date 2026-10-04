"""Error classes and helpers."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# Convenience not-found errors per resource
NOT_FOUND = {
    "contract": ("ERR_CONTRACT_NOT_FOUND", 404),
    "season": ("ERR_SEASON_NOT_FOUND", 404),
    "service_line": ("ERR_SERVICE_LINE_NOT_FOUND", 404),
    "room_class": ("ERR_ROOM_CLASS_NOT_FOUND", 404),
    "study": ("ERR_STUDY_NOT_FOUND", 404),
    "filing": ("ERR_FILING_NOT_FOUND", 404),
    "reservation": ("ERR_RESERVATION_NOT_FOUND", 404),
    "report": ("ERR_REPORT_NOT_FOUND", 404),
    "statement": ("ERR_STATEMENT_NOT_FOUND", 404),
    "project": ("ERR_PROJECT_NOT_FOUND", 404),
    "housing_unit": ("ERR_HOUSING_UNIT_NOT_FOUND", 404),
    "hire": ("ERR_HIRE_NOT_FOUND", 404),
    "voucher": ("ERR_VOUCHER_NOT_FOUND", 404),
    "incident": ("ERR_INCIDENT_NOT_FOUND", 404),
}


def not_found(kind):
    eid, code = NOT_FOUND[kind]
    return ApiError(eid, code, eid)
