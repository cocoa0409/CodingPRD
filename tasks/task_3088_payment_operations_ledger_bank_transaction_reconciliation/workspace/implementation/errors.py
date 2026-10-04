"""Error catalogue for the Payment Operations Ledger Reconciliation API.

Every error identifier and HTTP status below is transcribed from PRD.md S5 and
S1.6.  The identifiers and statuses are the contract; the messages are free text.
"""


class ApiError(Exception):
    """A declared API error carrying an error_id and an HTTP status."""

    def __init__(self, error_id, message="", http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 500)


# error_id -> HTTP status (PRD S5 catalogue, verbatim)
HTTP_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_SELF_APPROVAL_FORBIDDEN": 403,
    "ERR_LEGAL_ENTITY_NOT_FOUND": 404,
    "ERR_LEDGER_NOT_FOUND": 404,
    "ERR_COUNTERPARTY_NOT_FOUND": 404,
    "ERR_BANK_ACCOUNT_NOT_FOUND": 404,
    "ERR_VIRTUAL_ACCOUNT_NOT_FOUND": 404,
    "ERR_BANK_STATEMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_ORDER_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_EXCEPTION_NOT_FOUND": 404,
    "ERR_RELEASE_REQUEST_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TRANSITION": 409,
    "ERR_INVALID_SETTLEMENT_AXIS": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_COUNTERPARTY_BLOCKED": 409,
    "ERR_COUNTERPARTY_NOT_SETTLED": 409,
    "ERR_RELATIONSHIP_ALREADY_ACTIVE": 409,
    "ERR_UNATTRIBUTED_DEPOSIT_OPEN": 409,
    "ERR_RAIL_ACCOUNT_UNSUPPORTED": 422,
    "ERR_SETTLEMENT_SPEED_UNSUPPORTED": 422,
    "ERR_VELOCITY_LIMIT_EXCEEDED": 409,
    "ERR_CALENDAR_HAS_NO_OPEN_CYCLE": 409,
    "ERR_SETTLEMENT_POOL_INSUFFICIENT": 409,
    "ERR_LEDGER_LOCKED": 409,
    "ERR_DUPLICATE_PAYMENT": 409,
    "ERR_APPROVAL_POOL_WITHDRAWN": 409,
    "ERR_PERIOD_CLOSED": 409,
    "ERR_CLOSE_BLOCKED_BY_EXCEPTION": 409,
    "ERR_LEDGER_UNBALANCED": 409,
    "ERR_BALANCE_WOULD_GO_NEGATIVE": 409,
    "ERR_LINE_ALREADY_MATCHED": 409,
    "ERR_DUPLICATE_REFERENCE_CODE": 409,
    "ERR_STATEMENT_VARIANCE_UNRESOLVED": 409,
    "ERR_STATEMENT_ONLY_MUTABLE_BEFORE_RECONCILE": 409,
    "ERR_EXCEPTION_NOT_ASSIGNED_TO_CALLER": 409,
    "ERR_EXCEPTION_NOT_AGED": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 409,
    "ERR_STALE_VERSION": 412,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER":
        "X-User-ID and X-User-Role must both be present and X-User-Role must name a declared role.",
    "ERR_FORBIDDEN_FOR_ROLE": "The caller's role is not permitted on this endpoint.",
    "ERR_SELF_APPROVAL_FORBIDDEN": "The approver is also the initiator of this payment order.",
    "ERR_INVALID_REQUEST": "The request body is malformed or carries an unsupported value.",
    "ERR_INVALID_TRANSITION": "The resource is not in a state from which this transition is declared.",
    "ERR_INVALID_SETTLEMENT_AXIS": "The settlement axis does not admit this operation.",
    "ERR_ALREADY_TERMINAL": "The resource is already in a terminal state.",
    "ERR_COUNTERPARTY_BLOCKED": "The counterparty is not ACTIVE.",
    "ERR_COUNTERPARTY_NOT_SETTLED": "A live payment order still references this counterparty.",
    "ERR_RELATIONSHIP_ALREADY_ACTIVE": "An ACTIVE relationship already exists for this institution pair.",
    "ERR_UNATTRIBUTED_DEPOSIT_OPEN": "An unattributed deposit is still open on one side of the relationship.",
    "ERR_RAIL_ACCOUNT_UNSUPPORTED": "The rail is not supported by the source account.",
    "ERR_SETTLEMENT_SPEED_UNSUPPORTED": "SAME_DAY settlement is only admissible on the ACH rail.",
    "ERR_VELOCITY_LIMIT_EXCEEDED": "The amount is not strictly below the effective velocity limit.",
    "ERR_CALENDAR_HAS_NO_OPEN_CYCLE": "No open banking calendar cell exists inside the lookahead window.",
    "ERR_SETTLEMENT_POOL_INSUFFICIENT": "The source settlement pool cannot cover this payment.",
    "ERR_LEDGER_LOCKED": "The order's ledger is closed or a close pass is in flight.",
    "ERR_DUPLICATE_PAYMENT": "This payment duplicates an existing order.",
    "ERR_APPROVAL_POOL_WITHDRAWN": "The release pool claim was withdrawn by an approval.",
    "ERR_PERIOD_CLOSED": "The effective instant falls inside a closed accounting period.",
    "ERR_CLOSE_BLOCKED_BY_EXCEPTION": "An exception on this ledger is still unresolved.",
    "ERR_LEDGER_UNBALANCED": "The ledger identities could not be restored.",
    "ERR_BALANCE_WOULD_GO_NEGATIVE": "This posting would drive the posted balance below zero.",
    "ERR_LINE_ALREADY_MATCHED": "The bank line or statement duplicates an existing row.",
    "ERR_DUPLICATE_REFERENCE_CODE": "The reference is already used within its uniqueness scope.",
    "ERR_STATEMENT_VARIANCE_UNRESOLVED": "The statement still carries a non-zero variance.",
    "ERR_STATEMENT_ONLY_MUTABLE_BEFORE_RECONCILE": "Lines may only be appended while the statement is IMPORTED.",
    "ERR_EXCEPTION_NOT_ASSIGNED_TO_CALLER": "The exception is not assigned to the caller or has not aged a business day.",
    "ERR_EXCEPTION_NOT_AGED": "The exception's aging bucket does not admit this operation.",
    "ERR_CLOCK_NOT_MONOTONIC": "The logical clock may not move backwards.",
    "ERR_STALE_VERSION": "The expected version is behind the persisted version.",
}

# not-found errors keyed by the entity name they refer to
NOT_FOUND = {
    "LegalEntity": "ERR_LEGAL_ENTITY_NOT_FOUND",
    "Ledger": "ERR_LEDGER_NOT_FOUND",
    "Counterparty": "ERR_COUNTERPARTY_NOT_FOUND",
    "CounterpartyRelationship": "ERR_RELATIONSHIP_ALREADY_ACTIVE",  # unused; reserved
    "BankAccount": "ERR_BANK_ACCOUNT_NOT_FOUND",
    "VirtualAccount": "ERR_VIRTUAL_ACCOUNT_NOT_FOUND",
    "BankStatement": "ERR_BANK_STATEMENT_NOT_FOUND",
    "PaymentOrder": "ERR_PAYMENT_ORDER_NOT_FOUND",
    "Transaction": "ERR_TRANSACTION_NOT_FOUND",
    "ExceptionItem": "ERR_EXCEPTION_NOT_FOUND",
    "ReleaseRequest": "ERR_RELEASE_REQUEST_NOT_FOUND",
}