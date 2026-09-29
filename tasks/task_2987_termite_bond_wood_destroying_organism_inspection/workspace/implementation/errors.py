"""Error type used across the API.

Every error_id / http status pair here traces to PRD.md section 5 (Error Code
Catalogue).  The envelope shape is built in envelope.py.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# --- convenience constructors for the most frequently raised codes ----------

def invalid_request(message="Request body failed shape validation"):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_pagination(message="limit must be an integer in [1, 100] and offset an integer >= 0"):
    return ApiError("ERR_INVALID_PAGINATION", 400, message)


def field_combination(message="Conditionally required or forbidden field combination is invalid"):
    return ApiError("ERR_FIELD_COMBINATION_INVALID", 422, message)


NOT_FOUND = {
    "Property": "ERR_PROPERTY_NOT_FOUND",
    "Inspector": "ERR_INSPECTOR_NOT_FOUND",
    "Inspection": "ERR_INSPECTION_NOT_FOUND",
    "TreatmentPlan": "ERR_TREATMENT_PLAN_NOT_FOUND",
    "Bond": "ERR_BOND_NOT_FOUND",
    "BondRenewal": "ERR_BOND_RENEWAL_NOT_FOUND",
    "WdoReport": "ERR_WDO_REPORT_NOT_FOUND",
    "BaitStation": "ERR_BAIT_STATION_NOT_FOUND",
    "DamageClaim": "ERR_DAMAGE_CLAIM_NOT_FOUND",
}


def not_found(kind, ident=None):
    return ApiError(NOT_FOUND[kind], 404, "%s %s does not exist" % (kind, ident))


INVALID_STATE = {
    "Inspector": "ERR_INVALID_INSPECTOR_STATE",
    "Inspection": "ERR_INVALID_INSPECTION_STATE",
    "TreatmentPlan": "ERR_INVALID_PLAN_STATE",
    "Bond": "ERR_INVALID_BOND_STATE",
    "BondRenewal": "ERR_INVALID_RENEWAL_STATE",
    "WdoReport": "ERR_INVALID_REPORT_STATE",
    "BaitStation": "ERR_INVALID_STATION_STATE",
    "DamageClaim": "ERR_INVALID_CLAIM_STATE",
}


def invalid_state(kind, message=None):
    return ApiError(INVALID_STATE[kind], 409,
                    message or "%s is not in a status from which this transition is declared" % kind)
