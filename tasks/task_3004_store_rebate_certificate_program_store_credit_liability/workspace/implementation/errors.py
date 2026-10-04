"""Error catalog and exception type.

Every error_id and its HTTP status is taken verbatim from PRD.md section 5
(Error Code Catalogue) / SCAFFOLD.yaml `errors`.
"""

# ---------------------------------------------------------------------------
# error_id -> (http_status, default message)
# ---------------------------------------------------------------------------
ERROR_CATALOG = {
    # --- authentication / authorization ------------------------------------
    "ERR_UNAUTHENTICATED": (401, "X-User-Role header missing or not a declared role"),
    "ERR_FORBIDDEN": (403, "Role not permitted for this endpoint, or entity-backed role acting on another account's resource"),

    # --- existence ----------------------------------------------------------
    "ERR_NOT_FOUND": (404, "Path resource does not exist or is mis-nested"),

    # --- request shape ------------------------------------------------------
    "ERR_INVALID_REQUEST": (400, "Malformed payload: missing required field, invalid enum, quantity or amount below 1"),

    # --- receipt / tender ---------------------------------------------------
    "ERR_TENDER_SPLIT_MISMATCH": (422, "A receipt line's tender_splits amounts do not sum exactly to quantity * unit_price_cents"),
    "ERR_RECEIPT_IN_FUTURE": (422, "Receipt purchase_at is after the logical clock"),
    "ERR_DUPLICATE_RECEIPT_NUMBER": (409, "receipt_number already exists at this store"),
    "ERR_INVALID_JOB_PURCHASE": (422, "job_purchase_id set on a non-CONTRACTOR account, job not owned by the account, or job not OPEN"),

    # --- submission ----------------------------------------------------------
    "ERR_SUBMISSION_WINDOW_CLOSED": (422, "Logical clock past purchase date + submission_window_days"),
    "ERR_DUPLICATE_RECEIPT_SUBMISSION": (409, "A non-REVERSED submission already exists for this receipt"),
    "ERR_INVALID_STATE": (409, "Resource not in a state that permits the operation"),
    "ERR_RESUBMIT_LIMIT_REACHED": (409, "resubmit_count already at MAX_RESUBMITS (3)"),

    # --- account / fraud ------------------------------------------------------
    "ERR_ACCOUNT_FROZEN": (409, "Account FROZEN blocks this operation"),
    "ERR_ACCOUNT_BALANCE_NONZERO": (409, "Account close attempted with nonzero credit or pending award balance"),
    "ERR_FRAUD_FLAG_OPEN": (409, "Unfreeze blocked while a DUPLICATE_RECEIPT fraud flag is OPEN on the account"),
    "ERR_ACCOUNT_FRAUD_CONFIRMED": (409, "Reissue blocked while a CONFIRMED fraud flag exists on the account"),

    # --- certificate -----------------------------------------------------------
    "ERR_CERTIFICATE_HELD": (409, "Certificate fraud_hold = HELD blocks redeem and reissue"),
    "ERR_CERTIFICATE_EXPIRED": (422, "Redeem attempted at logical clock >= expires_at"),
    "ERR_CERTIFICATE_WRONG_STORE": (422, "Certificate redeemed against a receipt of a different store, or owned by a different account than the receipt"),
    "ERR_CERTIFICATE_REBATE_PURCHASE_BARRED": (422, "Certificates may not pay for further rebate-eligible purchases"),
    "ERR_REDEMPTION_EXCEEDS_BALANCE": (422, "amount_cents exceeds remaining_balance_cents"),
    "ERR_REISSUE_WINDOW_CLOSED": (422, "Reissue attempted at logical clock >= expires_at + 30 days"),

    # --- returns ---------------------------------------------------------------
    "ERR_RETURN_QUANTITY_EXCEEDS_SOLD": (422, "Cumulative returned quantity on a line would exceed sold quantity"),

    # --- program -----------------------------------------------------------------
    "ERR_PROGRAM_EMPTY": (409, "Program activation with zero program items"),
    "ERR_PROGRAM_WEEK_OVERLAP": (409, "Another ACTIVE program at the same store has an overlapping advertised week"),
    "ERR_PROGRAM_WEEK_PAST": (409, "Program activation when the advertised week has already fully passed"),

    # --- optimistic concurrency ---------------------------------------------------
    "ERR_STALE_VERSION": (412, "expected_store_version does not match the store's current version"),
}


class ApiError(Exception):
    """Domain error carrying the scaffold error_id and its HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        status, default_message = ERROR_CATALOG.get(
            error_id, (400, "Request could not be processed")
        )
        self.error_id = error_id
        self.message = message or default_message
        self.http_status = http_status or status
        super().__init__(self.message)


def api_error(error_id, message=None):
    return ApiError(error_id, message)


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
