"""Error catalog (SCAFFOLD Table 6 / PRD section 5).

Every rejection raised anywhere in the implementation travels as an
``ApiError`` carrying the catalog's ``error_id`` and its HTTP status.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status=409, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, "The request could not be completed."
        )
        super().__init__("%s: %s" % (error_id, self.message))


E = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_HACCP_WINDOW_FREEZE": 409,
    "ERR_HACCP_HOLD": 409,
    "ERR_POSTURE_HALT": 409,
    "ERR_POSTURE_RESTRICTED": 409,
    "ERR_UNVERIFIED_WASTE_BACKLOG": 409,
    "ERR_ASSOCIATE_NOT_CERTIFIED": 409,
    "ERR_ALLERGEN_CHANGEOVER_REQUIRED": 409,
    "ERR_SLICER_WINDOW_CONFLICT": 409,
    "ERR_SLICER_NOT_SANITIZED": 409,
    "ERR_SLICER_REQUIRED": 400,
    "ERR_NO_CERTIFIED_STAFF": 409,
    "ERR_NO_CLEAN_SLICER": 409,
    "ERR_ALLERGY_HOLD_ACTIVE": 409,
    "ERR_SHELF_OUT": 409,
    "ERR_PRICE_FILE_STALE": 409,
    "ERR_LABEL_STALE": 409,
    "ERR_BREAD_UNAVAILABLE": 409,
    "ERR_PICKUP_WINDOW_MISSED": 409,
    "ERR_LEAD_TIME_VIOLATED": 409,
    "ERR_PICKUP_CAPACITY_EXCEEDED": 409,
    "ERR_PRICE_FILE_OVERLAP": 409,
    "ERR_PRICE_FILE_IN_USE": 409,
    "ERR_PROMO_STATE_BLOCKS_FILE_WITHDRAWAL": 409,
    "ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD": 409,
    "ERR_MARKDOWN_WINDOW_CLOSED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_EMPTY_CART": 400,
    "ERR_SANITATION_CYCLE_NOT_DUE": 409,
    "ERR_CYCLE_NOT_COMPLETE": 409,
    "ERR_REOPEN_LIMIT_EXCEEDED": 409,
    "ERR_LABEL_WEIGHT_EXCEEDED": 400,
    "ERR_DUPLICATE_REQUEST": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_NO_COMPLETED_TICKET_YET": 409,
    "ERR_SLIP_LOCK_VIOLATED": 409,
    "ERR_QUEUE_DEPTH_BREACH": 409,
    "ERR_DELI_ITEM_UNAVAILABLE": 409,
    "ERR_BATCH_WINDOW_INVALID": 400,
    "ERR_WASTE_SEQUENCE_VIOLATION": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role and X-User-ID headers are required and the role must be known.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this operation.",
    "ERR_INVALID_REQUEST": "Malformed body, unknown field, or a required field is missing.",
    "ERR_STORE_NOT_FOUND": "The addressed store does not exist.",
    "ERR_NOT_FOUND": "The addressed resource does not exist under that store.",
    "ERR_INVALID_STATE": "The resource is not in the state the requested transition requires.",
    "ERR_HACCP_WINDOW_FREEZE": "A missed catering pickup window is still open for this store.",
    "ERR_HACCP_HOLD": "The store's haccp_safety_flag is true.",
    "ERR_POSTURE_HALT": "Store posture is HALT; no fresh work is admitted.",
    "ERR_POSTURE_RESTRICTED": "Store posture is RESTRICTED; new production batches are blocked.",
    "ERR_UNVERIFIED_WASTE_BACKLOG": "Three or more waste records await verification.",
    "ERR_ASSOCIATE_NOT_CERTIFIED": "The named associate lacks an ACTIVE certification of the required type.",
    "ERR_ALLERGEN_CHANGEOVER_REQUIRED": "The slicer's allergen profile is not cleared for this item.",
    "ERR_SLICER_WINDOW_CONFLICT": "The slicer is already committed in an overlapping interval.",
    "ERR_SLICER_NOT_SANITIZED": "The slicer is not CLEAN and cannot be claimed.",
    "ERR_SLICER_REQUIRED": "A slicer-required item must name a slicer_id.",
    "ERR_NO_CERTIFIED_STAFF": "No associate in the store holds an ACTIVE SLICER_OPERATION certification.",
    "ERR_NO_CLEAN_SLICER": "No CLEAN slicer exists for a slicer-required line.",
    "ERR_ALLERGY_HOLD_ACTIVE": "The completing associate's allergy_set does not cover every line's allergens.",
    "ERR_SHELF_OUT": "The store's case_on_hand_lbs cannot cover every line's required weight.",
    "ERR_PRICE_FILE_STALE": "No ACTIVE scale price file covers the logical clock.",
    "ERR_LABEL_STALE": "The ticket's label has been voided; the ticket must be remade first.",
    "ERR_BREAD_UNAVAILABLE": "The ticket's bread item is unavailable.",
    "ERR_PICKUP_WINDOW_MISSED": "The pickup window is closed.",
    "ERR_LEAD_TIME_VIOLATED": "The catering lead time requirement is not satisfied.",
    "ERR_PICKUP_CAPACITY_EXCEEDED": "The pickup bucket's aggregate headcount limit would be exceeded.",
    "ERR_PRICE_FILE_OVERLAP": "The price file overlaps an already-ACTIVE file for this store.",
    "ERR_PRICE_FILE_IN_USE": "A price file with ISSUED labels cannot be withdrawn.",
    "ERR_PROMO_STATE_BLOCKS_FILE_WITHDRAWAL": "The associated promotion must be CANCELLED before withdrawal.",
    "ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD": "Markdown must precede discard.",
    "ERR_MARKDOWN_WINDOW_CLOSED": "The half-open markdown window is closed at the logical clock.",
    "ERR_SEGREGATION_OF_DUTIES": "The producer, markdown associate and verifier must be distinct.",
    "ERR_EMPTY_CART": "A ticket must carry at least one line and every line needs half_lb_units >= 1.",
    "ERR_SANITATION_CYCLE_NOT_DUE": "The requested sanitation cycle is not yet due.",
    "ERR_CYCLE_NOT_COMPLETE": "The cycle's cycle_minutes have not elapsed.",
    "ERR_REOPEN_LIMIT_EXCEEDED": "A slicer may be reopened at most twice per production day.",
    "ERR_LABEL_WEIGHT_EXCEEDED": "The scale-locked label weight must be above zero and at most 10 lbs.",
    "ERR_DUPLICATE_REQUEST": "The catering order's request_id has already been used in this store.",
    "ERR_STALE_VERSION": "expected version does not match the parent's current version.",
    "ERR_NO_COMPLETED_TICKET_YET": "A prior COMPLETED ticket in this store is late, so the slip basis is closed.",
    "ERR_SLIP_LOCK_VIOLATED": "The slip lock would be violated by this completion.",
    "ERR_QUEUE_DEPTH_BREACH": "The store's eligible sub queue already holds eight tickets.",
    "ERR_DELI_ITEM_UNAVAILABLE": "A referenced catalog item does not exist or is DISCONTINUED.",
    "ERR_BATCH_WINDOW_INVALID": "The batch's hold window is not a well-formed half-open interval.",
    "ERR_WASTE_SEQUENCE_VIOLATION": "A waste record for this batch is already open.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, E.get(error_id, 409), message)


def invalid(message=None):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)