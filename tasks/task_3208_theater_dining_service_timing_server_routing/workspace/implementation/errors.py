"""Error identifiers, HTTP statuses and the API exception type."""

# --- Auth & existence -------------------------------------------------------
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"

ERR_AUDITORIUM_NOT_FOUND = "ERR_AUDITORIUM_NOT_FOUND"
ERR_SHOWTIME_NOT_FOUND = "ERR_SHOWTIME_NOT_FOUND"
ERR_MENU_ITEM_NOT_FOUND = "ERR_MENU_ITEM_NOT_FOUND"
ERR_PROGRAMMING_EVENT_NOT_FOUND = "ERR_PROGRAMMING_EVENT_NOT_FOUND"
ERR_THEMED_MENU_ITEM_NOT_FOUND = "ERR_THEMED_MENU_ITEM_NOT_FOUND"
ERR_SERVER_NOT_FOUND = "ERR_SERVER_NOT_FOUND"
ERR_SECTION_ASSIGNMENT_NOT_FOUND = "ERR_SECTION_ASSIGNMENT_NOT_FOUND"
ERR_SHOWTIME_FOR_ASSIGNMENT_NOT_FOUND = "ERR_SHOWTIME_FOR_ASSIGNMENT_NOT_FOUND"
ERR_LOCAL_SHIFTABLE_ASSIGNMENT_NOT_FOUND = "ERR_LOCAL_SHIFTABLE_ASSIGNMENT_NOT_FOUND"
ERR_LOCAL_SECTION_ASSIGNMENT_NOT_FOUND = "ERR_LOCAL_SECTION_ASSIGNMENT_NOT_FOUND"
ERR_ORDER_SLIP_NOT_FOUND = "ERR_ORDER_SLIP_NOT_FOUND"
ERR_CHECK_NOT_FOUND = "ERR_CHECK_NOT_FOUND"
ERR_DISTURBANCE_EVENT_NOT_FOUND = "ERR_DISTURBANCE_EVENT_NOT_FOUND"
ERR_KITCHEN_TICKET_NOT_FOUND = "ERR_KITCHEN_TICKET_NOT_FOUND"
ERR_NO_LINKED_SHOWTIME = "ERR_NO_LINKED_SHOWTIME"

# --- State ------------------------------------------------------------------
ERR_AUDITORIUM_NOT_ACTIVE = "ERR_AUDITORIUM_NOT_ACTIVE"
ERR_AUDITORIUM_NOT_DARK = "ERR_AUDITORIUM_NOT_DARK"
ERR_AUDITORIUM_NOT_SERVING = "ERR_AUDITORIUM_NOT_SERVING"
ERR_SHOWTIME_NOT_SCHEDULED = "ERR_SHOWTIME_NOT_SCHEDULED"
ERR_SHOWTIME_NOT_DINING_OPEN = "ERR_SHOWTIME_NOT_DINING_OPEN"
ERR_SHOWTIME_NOT_IN_SERVICE = "ERR_SHOWTIME_NOT_IN_SERVICE"
ERR_SHOWTIME_NOT_RUNNING = "ERR_SHOWTIME_NOT_RUNNING"
ERR_SHOWTIME_NOT_COMPLETED = "ERR_SHOWTIME_NOT_COMPLETED"
ERR_PROGRAMMING_EVENT_NOT_DRAFT = "ERR_PROGRAMMING_EVENT_NOT_DRAFT"
ERR_PROGRAMMING_EVENT_NOT_CANCELLABLE = "ERR_PROGRAMMING_EVENT_NOT_CANCELLABLE"
ERR_PRE_SHOW_NOT_IN_REVIEW = "ERR_PRE_SHOW_NOT_IN_REVIEW"
ERR_PRE_SHOW_NOT_RESUBMITTABLE = "ERR_PRE_SHOW_NOT_RESUBMITTABLE"
ERR_ORDER_SLIP_NOT_ACCEPTED = "ERR_ORDER_SLIP_NOT_ACCEPTED"
ERR_ORDER_SLIP_NOT_PREPARING = "ERR_ORDER_SLIP_NOT_PREPARING"
ERR_ORDER_SLIP_NOT_READY = "ERR_ORDER_SLIP_NOT_READY"
ERR_ORDER_SLIP_NOT_CANCELLABLE = "ERR_ORDER_SLIP_NOT_CANCELLABLE"
ERR_CHECK_NOT_OPEN = "ERR_CHECK_NOT_OPEN"
ERR_DISTURBANCE_NOT_AMENDABLE = "ERR_DISTURBANCE_NOT_AMENDABLE"
ERR_SERVER_NOT_PENALIZED = "ERR_SERVER_NOT_PENALIZED"
ERR_SECTION_ASSIGNMENT_NOT_ACTIVE = "ERR_SECTION_ASSIGNMENT_NOT_ACTIVE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"

# --- OCC --------------------------------------------------------------------
ERR_STALE_SHOWTIME_VERSION = "ERR_STALE_SHOWTIME_VERSION"
ERR_STALE_SECTION_ASSIGNMENT_VERSION = "ERR_STALE_SECTION_ASSIGNMENT_VERSION"
ERR_STALE_PROGRAMMING_EVENT_VERSION = "ERR_STALE_PROGRAMMING_EVENT_VERSION"
ERR_STALE_ORDER_SLIP_VERSION = "ERR_STALE_ORDER_SLIP_VERSION"

# --- Business ---------------------------------------------------------------
ERR_ID_CHECK_REQUIRED = "ERR_ID_CHECK_REQUIRED"
ERR_SILENT_ORDER_VIOLATION = "ERR_SILENT_ORDER_VIOLATION"
ERR_EJECTED_OCCUPANT_NOT_ON_SLIP = "ERR_EJECTED_OCCUPANT_NOT_ON_SLIP"
ERR_DINING_WINDOW_CLOSED = "ERR_DINING_WINDOW_CLOSED"
ERR_DINING_WINDOW_NOT_OPEN = "ERR_DINING_WINDOW_NOT_OPEN"
ERR_NOT_IN_SERVICE_WINDOW = "ERR_NOT_IN_SERVICE_WINDOW"
ERR_ENTREE_DEADLINE_PASSED = "ERR_ENTREE_DEADLINE_PASSED"
ERR_ENTREE_OVERFLOW_ACK_REQUIRED = "ERR_ENTREE_OVERFLOW_ACK_REQUIRED"
ERR_FIRE_WINDOW_NOT_OPEN = "ERR_FIRE_WINDOW_NOT_OPEN"
ERR_TICKET_NOT_READY = "ERR_TICKET_NOT_READY"
ERR_DARK_PERIOD_FULFILMENT_BLOCKED = "ERR_DARK_PERIOD_FULFILMENT_BLOCKED"
ERR_SERVER_SECTION_OVERLAP = "ERR_SERVER_SECTION_OVERLAP"
ERR_SERVER_HARD_CAP_EXCEEDED = "ERR_SERVER_HARD_CAP_EXCEEDED"
ERR_SECTION_OCCUPIED = "ERR_SECTION_OCCUPIED"
ERR_OVERLAPPING_SHOWTIME_WINDOW = "ERR_OVERLAPPING_SHOWTIME_WINDOW"
ERR_THEMED_MENU_REQUIRED = "ERR_THEMED_MENU_REQUIRED"
ERR_PRE_SHOW_NOT_APPROVED = "ERR_PRE_SHOW_NOT_APPROVED"
ERR_SIGNATURE_ITEM_REQUIRED = "ERR_SIGNATURE_ITEM_REQUIRED"
ERR_SHOWTIME_IN_PROGRESS = "ERR_SHOWTIME_IN_PROGRESS"
ERR_OPEN_KITCHEN_TICKETS = "ERR_OPEN_KITCHEN_TICKETS"
ERR_SECTION_UNCOVERED = "ERR_SECTION_UNCOVERED"
ERR_MENU_ITEM_UNAVAILABLE = "ERR_MENU_ITEM_UNAVAILABLE"
ERR_FEATURE_START_BOUNDARY = "ERR_FEATURE_START_BOUNDARY"
ERR_REOPEN_WINDOW_CLOSED = "ERR_REOPEN_WINDOW_CLOSED"
ERR_KITCHEN_CAPACITY_BAND = "ERR_KITCHEN_CAPACITY_BAND"
ERR_NOT_ASSIGNED_SERVER = "ERR_NOT_ASSIGNED_SERVER"
ERR_INVALID_SHOWTIME_RUNTIME = "ERR_INVALID_SHOWTIME_RUNTIME"
ERR_REFUND_EXCEEDS_ORIGINAL = "ERR_REFUND_EXCEEDS_ORIGINAL"


HTTP_STATUS = {
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: 400,
    ERR_UNAUTHORIZED_ROLE: 403,
    ERR_AUDITORIUM_NOT_FOUND: 404,
    ERR_SHOWTIME_NOT_FOUND: 404,
    ERR_MENU_ITEM_NOT_FOUND: 404,
    ERR_PROGRAMMING_EVENT_NOT_FOUND: 404,
    ERR_THEMED_MENU_ITEM_NOT_FOUND: 404,
    ERR_SERVER_NOT_FOUND: 404,
    ERR_SECTION_ASSIGNMENT_NOT_FOUND: 404,
    ERR_SHOWTIME_FOR_ASSIGNMENT_NOT_FOUND: 404,
    ERR_LOCAL_SHIFTABLE_ASSIGNMENT_NOT_FOUND: 404,
    ERR_LOCAL_SECTION_ASSIGNMENT_NOT_FOUND: 404,
    ERR_ORDER_SLIP_NOT_FOUND: 404,
    ERR_CHECK_NOT_FOUND: 404,
    ERR_DISTURBANCE_EVENT_NOT_FOUND: 404,
    ERR_KITCHEN_TICKET_NOT_FOUND: 404,
    ERR_NO_LINKED_SHOWTIME: 404,
    ERR_AUDITORIUM_NOT_ACTIVE: 409,
    ERR_AUDITORIUM_NOT_DARK: 409,
    ERR_AUDITORIUM_NOT_SERVING: 409,
    ERR_SHOWTIME_NOT_SCHEDULED: 409,
    ERR_SHOWTIME_NOT_DINING_OPEN: 409,
    ERR_SHOWTIME_NOT_IN_SERVICE: 409,
    ERR_SHOWTIME_NOT_RUNNING: 409,
    ERR_SHOWTIME_NOT_COMPLETED: 409,
    ERR_PROGRAMMING_EVENT_NOT_DRAFT: 409,
    ERR_PROGRAMMING_EVENT_NOT_CANCELLABLE: 409,
    ERR_PRE_SHOW_NOT_IN_REVIEW: 409,
    ERR_PRE_SHOW_NOT_RESUBMITTABLE: 409,
    ERR_ORDER_SLIP_NOT_ACCEPTED: 409,
    ERR_ORDER_SLIP_NOT_PREPARING: 409,
    ERR_ORDER_SLIP_NOT_READY: 409,
    ERR_ORDER_SLIP_NOT_CANCELLABLE: 409,
    ERR_CHECK_NOT_OPEN: 409,
    ERR_DISTURBANCE_NOT_AMENDABLE: 409,
    ERR_SERVER_NOT_PENALIZED: 409,
    ERR_SECTION_ASSIGNMENT_NOT_ACTIVE: 409,
    ERR_ALREADY_TERMINAL: 409,
    ERR_STALE_SHOWTIME_VERSION: 412,
    ERR_STALE_SECTION_ASSIGNMENT_VERSION: 412,
    ERR_STALE_PROGRAMMING_EVENT_VERSION: 412,
    ERR_STALE_ORDER_SLIP_VERSION: 412,
    ERR_ID_CHECK_REQUIRED: 403,
    ERR_SILENT_ORDER_VIOLATION: 409,
    ERR_EJECTED_OCCUPANT_NOT_ON_SLIP: 400,
    ERR_DINING_WINDOW_CLOSED: 409,
    ERR_DINING_WINDOW_NOT_OPEN: 409,
    ERR_NOT_IN_SERVICE_WINDOW: 409,
    ERR_ENTREE_DEADLINE_PASSED: 409,
    ERR_ENTREE_OVERFLOW_ACK_REQUIRED: 409,
    ERR_FIRE_WINDOW_NOT_OPEN: 409,
    ERR_TICKET_NOT_READY: 409,
    ERR_DARK_PERIOD_FULFILMENT_BLOCKED: 409,
    ERR_SERVER_SECTION_OVERLAP: 409,
    ERR_SERVER_HARD_CAP_EXCEEDED: 409,
    ERR_SECTION_OCCUPIED: 409,
    ERR_OVERLAPPING_SHOWTIME_WINDOW: 409,
    ERR_THEMED_MENU_REQUIRED: 409,
    ERR_PRE_SHOW_NOT_APPROVED: 409,
    ERR_SIGNATURE_ITEM_REQUIRED: 409,
    ERR_SHOWTIME_IN_PROGRESS: 409,
    ERR_OPEN_KITCHEN_TICKETS: 409,
    ERR_SECTION_UNCOVERED: 409,
    ERR_MENU_ITEM_UNAVAILABLE: 409,
    ERR_FEATURE_START_BOUNDARY: 409,
    ERR_REOPEN_WINDOW_CLOSED: 409,
    ERR_KITCHEN_CAPACITY_BAND: 409,
    ERR_NOT_ASSIGNED_SERVER: 403,
    ERR_INVALID_SHOWTIME_RUNTIME: 400,
    ERR_REFUND_EXCEEDS_ORIGINAL: 422,
}

MESSAGES = {
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: "X-User-ID or X-User-Role header is missing, or X-User-Role is not a declared role.",
    ERR_UNAUTHORIZED_ROLE: "The declared role is not permitted on this operation.",
    ERR_AUDITORIUM_NOT_FOUND: "No auditorium exists for the given id.",
    ERR_SHOWTIME_NOT_FOUND: "No showtime exists for the given id.",
    ERR_MENU_ITEM_NOT_FOUND: "No menu item exists for the given id.",
    ERR_PROGRAMMING_EVENT_NOT_FOUND: "No programming event exists for the given id.",
    ERR_THEMED_MENU_ITEM_NOT_FOUND: "No themed menu item exists for the given id.",
    ERR_SERVER_NOT_FOUND: "No server exists for the given id.",
    ERR_SECTION_ASSIGNMENT_NOT_FOUND: "No section assignment exists for the given id.",
    ERR_SHOWTIME_FOR_ASSIGNMENT_NOT_FOUND: "The showtime named by the section assignment request does not exist on the referenced auditorium.",
    ERR_LOCAL_SHIFTABLE_ASSIGNMENT_NOT_FOUND: "The section assignment named by the order slip does not exist.",
    ERR_LOCAL_SECTION_ASSIGNMENT_NOT_FOUND: "The section assignment named by the order slip belongs to a different showtime.",
    ERR_ORDER_SLIP_NOT_FOUND: "No order slip exists for the given id.",
    ERR_CHECK_NOT_FOUND: "No check exists for the given id.",
    ERR_DISTURBANCE_EVENT_NOT_FOUND: "No disturbance event exists for the given id.",
    ERR_KITCHEN_TICKET_NOT_FOUND: "No kitchen ticket exists for the given id, or the slip has no ticket yet.",
    ERR_NO_LINKED_SHOWTIME: "The programming event has no linked special-event showtime.",
    ERR_AUDITORIUM_NOT_ACTIVE: "The operation requires the auditorium to be in a serving state.",
    ERR_AUDITORIUM_NOT_DARK: "The operation requires the auditorium to be DARK.",
    ERR_AUDITORIUM_NOT_SERVING: "The operation requires the parent auditorium to be LIVE or TURNOVER.",
    ERR_SHOWTIME_NOT_SCHEDULED: "The operation requires the showtime to be SCHEDULED.",
    ERR_SHOWTIME_NOT_DINING_OPEN: "The operation requires the showtime to be DINING_OPEN.",
    ERR_SHOWTIME_NOT_IN_SERVICE: "The operation requires the showtime to be in SERVICE.",
    ERR_SHOWTIME_NOT_RUNNING: "The operation requires the showtime to be RUNNING.",
    ERR_SHOWTIME_NOT_COMPLETED: "The operation requires the showtime to be COMPLETED.",
    ERR_PROGRAMMING_EVENT_NOT_DRAFT: "The operation requires the programming event to be DRAFT.",
    ERR_PROGRAMMING_EVENT_NOT_CANCELLABLE: "The operation requires the programming event to be DRAFT or ACTIVATED.",
    ERR_PRE_SHOW_NOT_IN_REVIEW: "The operation requires the pre-show content to be PRE_SHOW_IN_REVIEW.",
    ERR_PRE_SHOW_NOT_RESUBMITTABLE: "The pre-show content is not in a state from which it may be submitted for review.",
    ERR_ORDER_SLIP_NOT_ACCEPTED: "The operation requires the order slip to be ACCEPTED.",
    ERR_ORDER_SLIP_NOT_PREPARING: "The operation requires the order slip to be PREPARING.",
    ERR_ORDER_SLIP_NOT_READY: "The operation requires the order slip to be READY.",
    ERR_ORDER_SLIP_NOT_CANCELLABLE: "The operation requires the order slip to be non-terminal.",
    ERR_CHECK_NOT_OPEN: "The operation requires the check to be unsettled.",
    ERR_DISTURBANCE_NOT_AMENDABLE: "The disturbance event is already at the requested or a higher stage.",
    ERR_SERVER_NOT_PENALIZED: "The server is not currently in a penalty lockout.",
    ERR_SECTION_ASSIGNMENT_NOT_ACTIVE: "The operation requires the section assignment to be ACTIVE.",
    ERR_ALREADY_TERMINAL: "The resource is already in a terminal state.",
    ERR_STALE_SHOWTIME_VERSION: "expected_showtime_version does not match the showtime's current version.",
    ERR_STALE_SECTION_ASSIGNMENT_VERSION: "expected_section_assignment_version does not match the section assignment's current version.",
    ERR_STALE_PROGRAMMING_EVENT_VERSION: "expected_programming_event_version does not match the programming event's current version.",
    ERR_STALE_ORDER_SLIP_VERSION: "expected_order_slip_version does not match the order slip's current version.",
    ERR_ID_CHECK_REQUIRED: "An alcoholic beverage slip cannot be delivered without a completed identification check.",
    ERR_SILENT_ORDER_VIOLATION: "An order was placed against a showtime whose mode is DINING_CLOSED.",
    ERR_EJECTED_OCCUPANT_NOT_ON_SLIP: "The occupant named for ejection is not present on the disturbance event's slip.",
    ERR_DINING_WINDOW_CLOSED: "The logical clock is outside the dining window.",
    ERR_DINING_WINDOW_NOT_OPEN: "The seating window has not opened yet.",
    ERR_NOT_IN_SERVICE_WINDOW: "The service window has not opened yet.",
    ERR_ENTREE_DEADLINE_PASSED: "The entree deadline has passed.",
    ERR_ENTREE_OVERFLOW_ACK_REQUIRED: "The entree will land past the deadline and has no overflow acknowledgement.",
    ERR_FIRE_WINDOW_NOT_OPEN: "A cold-line ticket cannot start preparing before its fire instant.",
    ERR_TICKET_NOT_READY: "The ticket's projected delivery instant has not been reached.",
    ERR_DARK_PERIOD_FULFILMENT_BLOCKED: "Kitchen fulfilment was attempted during the dark period.",
    ERR_SERVER_SECTION_OVERLAP: "The server already holds an active section assignment that overlaps in time.",
    ERR_SERVER_HARD_CAP_EXCEEDED: "The server already holds the daily maximum of sections.",
    ERR_SECTION_OCCUPIED: "The server already holds a non-terminal assignment for the same auditorium and section label.",
    ERR_OVERLAPPING_SHOWTIME_WINDOW: "Another showtime on the same auditorium has an overlapping dining window.",
    ERR_THEMED_MENU_REQUIRED: "A special-event showtime requires a themed menu that has not been attached.",
    ERR_PRE_SHOW_NOT_APPROVED: "Pre-show content has not been approved.",
    ERR_SIGNATURE_ITEM_REQUIRED: "Approval requires at least one signature themed menu item.",
    ERR_SHOWTIME_IN_PROGRESS: "The programming event has a showtime currently RUNNING.",
    ERR_OPEN_KITCHEN_TICKETS: "The showtime still has kitchen tickets that are neither DELIVERED nor VOIDED.",
    ERR_SECTION_UNCOVERED: "A section on the showtime has been served without a delivery or an explicit alcohol refusal.",
    ERR_MENU_ITEM_UNAVAILABLE: "A line references a menu item that is OUT_OF_STOCK.",
    ERR_FEATURE_START_BOUNDARY: "The feature start was requested before the showtime's exact start instant.",
    ERR_REOPEN_WINDOW_CLOSED: "The feature has already finished, so the showtime cannot be reopened.",
    ERR_KITCHEN_CAPACITY_BAND: "The dining order capacity band evaluated to LATE without an acknowledgement, or to BLOCKED.",
    ERR_NOT_ASSIGNED_SERVER: "The acting server is not the server assigned to the slip's section.",
    ERR_INVALID_SHOWTIME_RUNTIME: "runtime_minutes is below the declared floor of 1.",
    ERR_REFUND_EXCEEDS_ORIGINAL: "The refund would push refunded_cents above original_cents.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = HTTP_STATUS.get(error_id, 400)
        self.message = message or MESSAGES.get(error_id, error_id)
        super().__init__(self.message)