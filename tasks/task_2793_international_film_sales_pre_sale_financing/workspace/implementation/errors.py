"""Error catalogue (PRD section 5) and the ApiError exception."""
from __future__ import annotations

ERROR_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    # existence
    "ERR_FILM_NOT_FOUND": 404,
    "ERR_TERRITORY_NOT_FOUND": 404,
    "ERR_MARKET_NOT_FOUND": 404,
    "ERR_BUYER_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_VALUATION_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_MARKET_ITEM_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # entity backed ownership
    "ERR_NOT_CONTRACT_BUYER": 403,
    # optimistic concurrency
    "ERR_STALE_FILM_VERSION": 412,
    "ERR_STALE_BUYER_VERSION": 412,
    # own row state
    "ERR_INVALID_STATE": 409,
    # related row state
    "ERR_FILM_NOT_IN_MARKET": 409,
    "ERR_MARKET_NOT_OPEN": 409,
    "ERR_COLLECTION_ACCOUNT_NOT_OPEN": 409,
    # business safety
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_BUYER_BLOCKED": 422,
    "ERR_COMPLETION_BOND_REQUIRED": 422,
    # business referential
    "ERR_AGENCY_AGREEMENT_NOT_IN_FORCE": 422,
    "ERR_NO_PUBLISHED_VALUATION": 422,
    "ERR_NO_ELIGIBLE_COLLATERAL": 422,
    # temporal
    "ERR_SCREENING_ROOM_CONFLICT": 409,
    "ERR_MEETING_SLOT_CONFLICT": 409,
    "ERR_OUTSIDE_MARKET_WINDOW": 422,
    "ERR_HOLDBACK_NOT_ELAPSED": 422,
    "ERR_LICENSE_TERM_NOT_EXPIRED": 422,
    "ERR_CURE_WINDOW_ELAPSED": 422,
    # business constraints
    "ERR_DUPLICATE_TERRITORY_OFFER": 409,
    "ERR_NO_COMPARABLE_TITLES": 422,
    "ERR_INSUFFICIENT_COMP_SAMPLE": 422,
    "ERR_MILESTONE_SCHEDULE_INVALID": 422,
    "ERR_NEGOTIATION_ROUND_LIMIT": 422,
    "ERR_MEETING_MINUTES_CAP_EXCEEDED": 422,
    "ERR_DELIVERABLES_INCOMPLETE": 422,
    "ERR_TIER_ORDER_TAKEN": 409,
    "ERR_TERRITORY_CODE_TAKEN": 409,
    # fiscal
    "ERR_BUYER_EXPOSURE_EXCEEDED": 422,
    "ERR_BUYER_NET_EXPOSURE_EXCEEDED": 422,
    "ERR_MG_BELOW_FLOOR": 422,
    "ERR_RECEIPT_AMOUNT_MISMATCH": 422,
    "ERR_INSUFFICIENT_ACCOUNT_BALANCE": 422,
    "ERR_RECEIPT_ALREADY_DISTRIBUTED": 422,
    "ERR_EXPENSE_LOG_LIMIT": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is unknown.",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation.",
    "ERR_FILM_NOT_FOUND": "Film not found.",
    "ERR_TERRITORY_NOT_FOUND": "Territory not found.",
    "ERR_MARKET_NOT_FOUND": "Market not found.",
    "ERR_BUYER_NOT_FOUND": "Buyer not found.",
    "ERR_CONTRACT_NOT_FOUND": "Pre-sale contract not found.",
    "ERR_VALUATION_NOT_FOUND": "Territory valuation not found.",
    "ERR_AGREEMENT_NOT_FOUND": "Sales agency agreement not found.",
    "ERR_MILESTONE_NOT_FOUND": "Payment milestone not found.",
    "ERR_PACKAGE_NOT_FOUND": "Deliverable package not found.",
    "ERR_FACILITY_NOT_FOUND": "Banking facility not found.",
    "ERR_ACCOUNT_NOT_FOUND": "Collection account not found.",
    "ERR_MARKET_ITEM_NOT_FOUND": "Market item not found.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_NOT_CONTRACT_BUYER": "The acting buyer does not own this contract.",
    "ERR_STALE_FILM_VERSION": "The supplied film version is stale.",
    "ERR_STALE_BUYER_VERSION": "The supplied buyer version is stale.",
    "ERR_INVALID_STATE": "The requested transition is not permitted from the current state.",
    "ERR_FILM_NOT_IN_MARKET": "The film is not in a market-ready sales status.",
    "ERR_MARKET_NOT_OPEN": "The market is not open.",
    "ERR_COLLECTION_ACCOUNT_NOT_OPEN": "No open collection account exists for the film.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not both prepare and approve this step.",
    "ERR_BUYER_BLOCKED": "The buyer is blocked from trading.",
    "ERR_COMPLETION_BOND_REQUIRED": "A completion bond must be posted first.",
    "ERR_AGENCY_AGREEMENT_NOT_IN_FORCE": "No sales agency agreement is in force for the film.",
    "ERR_NO_PUBLISHED_VALUATION": "No published territory valuation exists for this film and territory.",
    "ERR_NO_ELIGIBLE_COLLATERAL": "The facility has no eligible collateral.",
    "ERR_SCREENING_ROOM_CONFLICT": "The screening room is already occupied in that window.",
    "ERR_MEETING_SLOT_CONFLICT": "The meeting slot conflicts with an existing booking.",
    "ERR_OUTSIDE_MARKET_WINDOW": "The requested window falls outside the market window.",
    "ERR_HOLDBACK_NOT_ELAPSED": "The holdback period has not elapsed.",
    "ERR_LICENSE_TERM_NOT_EXPIRED": "The licence term has not expired.",
    "ERR_CURE_WINDOW_ELAPSED": "The cure window has elapsed.",
    "ERR_DUPLICATE_TERRITORY_OFFER": "The territory already carries a live or licensed offer.",
    "ERR_NO_COMPARABLE_TITLES": "No comparable titles are available for the territory.",
    "ERR_INSUFFICIENT_COMP_SAMPLE": "The comparable sample is too small.",
    "ERR_MILESTONE_SCHEDULE_INVALID": "The payment milestone schedule is invalid.",
    "ERR_NEGOTIATION_ROUND_LIMIT": "The negotiation round limit has been reached.",
    "ERR_MEETING_MINUTES_CAP_EXCEEDED": "The buyer meeting minutes cap would be exceeded.",
    "ERR_DELIVERABLES_INCOMPLETE": "The deliverables package is incomplete.",
    "ERR_TIER_ORDER_TAKEN": "The waterfall tier order is already taken.",
    "ERR_TERRITORY_CODE_TAKEN": "The territory code is already taken.",
    "ERR_BUYER_EXPOSURE_EXCEEDED": "The buyer's gross exposure limit would be exceeded.",
    "ERR_BUYER_NET_EXPOSURE_EXCEEDED": "The buyer's net exposure headroom would be exceeded.",
    "ERR_MG_BELOW_FLOOR": "The minimum guarantee is below the territory floor price.",
    "ERR_RECEIPT_AMOUNT_MISMATCH": "The receipt amount does not match the milestone amount.",
    "ERR_INSUFFICIENT_ACCOUNT_BALANCE": "The collection account balance is insufficient.",
    "ERR_RECEIPT_ALREADY_DISTRIBUTED": "The receipt has already been distributed.",
    "ERR_EXPENSE_LOG_LIMIT": "The expense log limit would be exceeded.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with one error."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)
        super().__init__(self.message)
