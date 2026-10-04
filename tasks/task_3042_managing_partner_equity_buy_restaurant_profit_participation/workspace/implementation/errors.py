"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"  # 400
ERR_INSUFFICIENT_PERMISSIONS = "ERR_INSUFFICIENT_PERMISSIONS"                              # 403
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                                                # 400
ERR_PARTNER_NOT_FOUND = "ERR_PARTNER_NOT_FOUND"                                            # 404
ERR_CONTRACT_NOT_FOUND = "ERR_CONTRACT_NOT_FOUND"                                          # 404
ERR_RESTAURANT_NOT_FOUND = "ERR_RESTAURANT_NOT_FOUND"                                      # 404
ERR_MARKET_GROUP_NOT_FOUND = "ERR_MARKET_GROUP_NOT_FOUND"                                  # 404
ERR_PERIOD_NOT_FOUND = "ERR_PERIOD_NOT_FOUND"                                              # 404
ERR_LINE_ITEM_NOT_FOUND = "ERR_LINE_ITEM_NOT_FOUND"                                        # 404
ERR_BATCH_NOT_FOUND = "ERR_BATCH_NOT_FOUND"                                                # 404
ERR_PROGRAM_NOT_FOUND = "ERR_PROGRAM_NOT_FOUND"                                            # 404
ERR_GRANT_NOT_FOUND = "ERR_GRANT_NOT_FOUND"                                                # 404
ERR_DISPUTE_NOT_FOUND = "ERR_DISPUTE_NOT_FOUND"                                            # 404
ERR_AGREEMENT_NOT_FOUND = "ERR_AGREEMENT_NOT_FOUND"                                        # 404
ERR_YIELD_STANDARD_NOT_FOUND = "ERR_YIELD_STANDARD_NOT_FOUND"                              # 404
ERR_BUYOUT_NOT_FOUND = "ERR_BUYOUT_NOT_FOUND"                                              # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"                                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                                                    # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                                                    # 412
ERR_CONTRACT_NOT_FUNDABLE = "ERR_CONTRACT_NOT_FUNDABLE"                                    # 409
ERR_BUY_IN_INCOMPLETE = "ERR_BUY_IN_INCOMPLETE"                                            # 422
ERR_BUY_IN_OVERPAYMENT = "ERR_BUY_IN_OVERPAYMENT"                                          # 422
ERR_FUNDING_WINDOW_LAPSED = "ERR_FUNDING_WINDOW_LAPSED"                                    # 422
ERR_RESTAURANT_NOT_ACTIVE = "ERR_RESTAURANT_NOT_ACTIVE"                                    # 422
ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT = "ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT"  # 422
ERR_RESTAURANT_HAS_OPEN_CONTRACTS = "ERR_RESTAURANT_HAS_OPEN_CONTRACTS"                    # 422
ERR_NOT_MANAGING_PARTNER = "ERR_NOT_MANAGING_PARTNER"                                      # 422
ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT = "ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT"            # 422
ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE = "ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE"                # 422
ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE = "ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE"            # 422
ERR_CONTRACT_PARTNER_MISMATCH = "ERR_CONTRACT_PARTNER_MISMATCH"                            # 403
ERR_SUCCESSOR_NOT_ELIGIBLE = "ERR_SUCCESSOR_NOT_ELIGIBLE"                                  # 422
ERR_BUYOUT_ALREADY_OPEN = "ERR_BUYOUT_ALREADY_OPEN"                                        # 422
ERR_CONTRACT_NOT_IN_BUYOUT = "ERR_CONTRACT_NOT_IN_BUYOUT"                                  # 409
ERR_OFFSET_EXCEEDS_PAYOUT = "ERR_OFFSET_EXCEEDS_PAYOUT"                                    # 422
ERR_PERIOD_OVERLAP = "ERR_PERIOD_OVERLAP"                                                  # 422
ERR_PERIOD_NOT_OPEN = "ERR_PERIOD_NOT_OPEN"                                                # 409
ERR_PERIOD_CLOSED_FOR_ENTRIES = "ERR_PERIOD_CLOSED_FOR_ENTRIES"                            # 422
ERR_UNFINALIZED_LINE_ITEMS = "ERR_UNFINALIZED_LINE_ITEMS"                                  # 422
ERR_BATCH_PERIOD_RESTAURANT_MISMATCH = "ERR_BATCH_PERIOD_RESTAURANT_MISMATCH"              # 422
ERR_DUPLICATE_CUT_CODE = "ERR_DUPLICATE_CUT_CODE"                                          # 422
ERR_UNKNOWN_CUT_CODE = "ERR_UNKNOWN_CUT_CODE"                                              # 422
ERR_TRAINING_TENURE_INSUFFICIENT = "ERR_TRAINING_TENURE_INSUFFICIENT"                      # 422
ERR_MARKET_GROUP_NOT_ACTIVE = "ERR_MARKET_GROUP_NOT_ACTIVE"                                # 422
ERR_OVERRIDE_COVERAGE_OVERLAP = "ERR_OVERRIDE_COVERAGE_OVERLAP"                            # 422
ERR_AWARD_SOURCE_PERIOD_INELIGIBLE = "ERR_AWARD_SOURCE_PERIOD_INELIGIBLE"                  # 422
ERR_AWARD_NOT_ELIGIBLE = "ERR_AWARD_NOT_ELIGIBLE"                                          # 422
ERR_AWARD_POOL_EXHAUSTED = "ERR_AWARD_POOL_EXHAUSTED"                                      # 422
ERR_DISPUTE_WINDOW_CLOSED = "ERR_DISPUTE_WINDOW_CLOSED"                                    # 422
ERR_DUPLICATE_OPEN_DISPUTE = "ERR_DUPLICATE_OPEN_DISPUTE"                                  # 422
ERR_DISPUTE_NOT_OWNED = "ERR_DISPUTE_NOT_OWNED"                                            # 403
ERR_ADJUSTMENT_REQUIRED = "ERR_ADJUSTMENT_REQUIRED"                                        # 422
ERR_OPEN_DISPUTE_BLOCKS_LOCK = "ERR_OPEN_DISPUTE_BLOCKS_LOCK"                              # 422


def bad_context(msg="X-User-ID or X-User-Role header missing or empty"):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, msg, 400)


def forbidden_role(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_INSUFFICIENT_PERMISSIONS, msg, 403)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def not_found(error_id, msg="Resource not found"):
    return ApiError(error_id, msg, 404)


def reference_not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, msg, 404)


def conflict(error_id, msg):
    return ApiError(error_id, msg, 409)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def unprocessable(error_id, msg):
    return ApiError(error_id, msg, 422)


def forbidden(error_id, msg):
    return ApiError(error_id, msg, 403)
