"""Error types and catalog for the NKR API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(message="X-User-Role header missing or unrecognized"):
    return ApiError("ERR_UNAUTHENTICATED", message, 401)


def err_unauthorized(message="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", message, 403)


def err_not_found(message="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", message, 404)


def err_invalid_request(message="Malformed body, missing required field, or invalid value"):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def err_invalid_state(message="Resource in wrong state for this transition"):
    return ApiError("ERR_INVALID_STATE", message, 409)


def err_stale_version(message="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", message, 412)


def err_center_suspended(message="Center participation_status forbids this action"):
    return ApiError("ERR_CENTER_SUSPENDED", message, 409)


def err_center_invalid_state(message="Center participation transition invalid from current state"):
    return ApiError("ERR_CENTER_INVALID_STATE", message, 409)


def err_center_mismatch(message="Acting center does not match the resource's center"):
    return ApiError("ERR_CENTER_MISMATCH", message, 403)


def err_center_at_capacity(message="Center active_chain_count >= max_concurrent_chains"):
    return ApiError("ERR_CENTER_AT_CAPACITY", message, 409)


def err_donor_not_cleared(message="Donor medical_status != CLEARED"):
    return ApiError("ERR_DONOR_NOT_CLEARED", message, 409)


def err_donor_post_nephrectomy(message="Operation forbidden after NEPHRECTOMY_DONE"):
    return ApiError("ERR_DONOR_POST_NEPHRECTOMY", message, 409)


def err_recipient_not_listed(message="Recipient medical_status != LISTED"):
    return ApiError("ERR_RECIPIENT_NOT_LISTED", message, 409)


def err_recipient_not_committed(message="Recipient chain_participation_state != COMMITTED"):
    return ApiError("ERR_RECIPIENT_NOT_COMMITTED", message, 409)


def err_organ_not_ready(message="Source offer not in DONOR_SURGERY_DONE"):
    return ApiError("ERR_ORGAN_NOT_READY", message, 409)


def err_organ_not_arrived(message="Offer not ORGAN_SHIPPED or shipment not DELIVERED"):
    return ApiError("ERR_ORGAN_NOT_ARRIVED", message, 409)


def err_cold_ischemia_violation(message="Cold ischemia hours exceeded maximum"):
    return ApiError("ERR_COLD_ISCHEMIA_VIOLATION", message, 409)


def err_review_deadline_passed(message="Logical clock past review/acceptance deadline"):
    return ApiError("ERR_REVIEW_DEADLINE_PASSED", message, 409)


def err_slot_taken(message="Slot is not OPEN"):
    return ApiError("ERR_SLOT_TAKEN", message, 409)


def err_slot_overlap(message="Slot interval overlaps an existing RESERVED/CONSUMED slot"):
    return ApiError("ERR_SLOT_OVERLAP", message, 409)


def err_slot_too_soon(message="Slot start precedes logical clock plus lead time"):
    return ApiError("ERR_SLOT_TOO_SOON", message, 409)


def err_flight_window(message="Itinerary flight window violated"):
    return ApiError("ERR_FLIGHT_ALREADY_DEPARTED", message, 409)


def err_pair_not_incompatible(message="Pair is not ABO-incompatible, not sensitized, and no opt-in"):
    return ApiError("ERR_PAIR_NOT_INCOMPATIBLE", message, 409)


def err_pool_too_small(message="Candidate pool below MIN_POOL_SIZE"):
    return ApiError("ERR_POOL_TOO_SMALL", message, 409)


def err_chain_locked(message="Chain or run is locked against this mutation"):
    return ApiError("ERR_CHAIN_LOCKED", message, 409)


def err_pending_offers(message="Some MatchOffer is not yet CENTER_ACCEPTED"):
    return ApiError("ERR_PENDING_OFFERS", message, 409)


def err_reconstruction_not_viable(message="No viable replacement chain run executed"):
    return ApiError("ERR_RECONSTRUCTION_NOT_VIABLE", message, 409)


def err_no_protection_policy(message="Donor has no active DonorProtectionPolicy"):
    return ApiError("ERR_NO_PROTECTION_POLICY", message, 409)


def err_claim_exceeds_cap(message="Claim approval exceeds bucket headroom"):
    return ApiError("ERR_CLAIM_EXCEEDS_CAP", message, 409)


def err_segregation_of_duties(message="Claim adjudicator must differ from submitter"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", message, 403)


def err_review_policy_violation(message="Crossmatch review fields violate center policy"):
    return ApiError("ERR_REVIEW_POLICY_VIOLATION", message, 409)
