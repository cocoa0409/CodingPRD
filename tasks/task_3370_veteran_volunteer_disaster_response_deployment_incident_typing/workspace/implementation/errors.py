"""ApiError carries the exact error_id and HTTP status from the PRD section 5 catalog."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def validation(message):
    err("ERR_VALIDATION", 400, message)


def unauthenticated(message="X-User-ID or X-User-Role header missing or malformed"):
    err("ERR_UNAUTHENTICATED", 401, message)


def unauthorized(message="role not permitted or ownership check failed"):
    err("ERR_UNAUTHORIZED", 403, message)


def invalid_state(message="target entity is not in a from-state for the requested transition"):
    err("ERR_INVALID_STATE", 409, message)


def stale_version(message="expected version does not match current version"):
    err("ERR_STALE_VERSION", 412, message)


# Per-entity 404 helpers (left-to-right nested resolution uses these exact ids).
def volunteer_not_found(): err("ERR_VOLUNTEER_NOT_FOUND", 404, "volunteer does not exist")
def certification_not_found(): err("ERR_CERTIFICATION_NOT_FOUND", 404, "certification does not exist")
def incident_not_found(): err("ERR_INCIDENT_NOT_FOUND", 404, "incident does not exist")
def operation_not_found(): err("ERR_OPERATION_NOT_FOUND", 404, "operation does not exist")
def deployment_not_found(): err("ERR_DEPLOYMENT_NOT_FOUND", 404, "deployment does not exist")
def fob_site_not_found(): err("ERR_FOB_SITE_NOT_FOUND", 404, "FOB site does not exist")
def duty_shift_not_found(): err("ERR_DUTY_SHIFT_NOT_FOUND", 404, "duty shift does not exist")
def work_order_not_found(): err("ERR_WORK_ORDER_NOT_FOUND", 404, "work order does not exist")
def partner_not_found(): err("ERR_PARTNER_NOT_FOUND", 404, "partner agency does not exist")
def training_course_not_found(): err("ERR_TRAINING_COURSE_NOT_FOUND", 404, "training course does not exist")
def enrollment_not_found(): err("ERR_ENROLLMENT_NOT_FOUND", 404, "training enrollment does not exist")
def wellness_check_not_found(): err("ERR_WELLNESS_CHECK_NOT_FOUND", 404, "wellness check does not exist")
