"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(msg="Authentication required"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def invalid_state(msg="Invalid state for this operation"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def stale_version(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def payer_suspended(msg="Payer client is suspended"):
    return ApiError("ERR_PAYER_SUSPENDED", msg, 409)


def duplicate_claim_ref(msg="external_claim_ref already used for this payer"):
    return ApiError("ERR_DUPLICATE_CLAIM_REF", msg, 409)


def duplicate_npi(msg="Provider npi already registered"):
    return ApiError("ERR_DUPLICATE_NPI", msg, 409)


def agreement_overlap(msg="Agreement interval overlaps an existing agreement"):
    return ApiError("ERR_AGREEMENT_OVERLAP", msg, 409)


def no_contracted_agreement(msg="No ACTIVE NetworkAgreement covers provider and service date"):
    return ApiError("ERR_NO_CONTRACTED_AGREEMENT", msg, 422)


def no_repricing_policy(msg="No ACTIVE RepricingPolicy matches the claim"):
    return ApiError("ERR_NO_REPRICING_POLICY", msg, 422)


def negotiation_required(msg="Selected policy methodology is NEGOTIATION_REQUIRED"):
    return ApiError("ERR_NEGOTIATION_REQUIRED", msg, 422)


def nsa_methodology_conflict(msg="NSA claim cannot be force-priced under NEGOTIATION_REQUIRED"):
    return ApiError("ERR_NSA_METHODOLOGY_CONFLICT", msg, 422)


def rate_input_missing(msg="Required rate input row is missing"):
    return ApiError("ERR_RATE_INPUT_MISSING", msg, 422)


def claim_has_no_lines(msg="Claim has no non-VOID lines"):
    return ApiError("ERR_CLAIM_HAS_NO_LINES", msg, 422)


def case_already_open(msg="A non-terminal negotiation case already exists for the claim"):
    return ApiError("ERR_CASE_ALREADY_OPEN", msg, 409)


def offer_out_of_range(msg="offer_cents outside (0, billed_amount_cents]"):
    return ApiError("ERR_OFFER_OUT_OF_RANGE", msg, 422)


def counter_below_offer(msg="counter_cents below the current offer on the table"):
    return ApiError("ERR_COUNTER_BELOW_OFFER", msg, 422)


def already_signed(msg="Signing party already signed, or void attempted after a signature"):
    return ApiError("ERR_ALREADY_SIGNED", msg, 409)


def open_negotiation_active(msg="Open negotiation period has not expired"):
    return ApiError("ERR_OPEN_NEGOTIATION_ACTIVE", msg, 409)


def qpa_unavailable(msg="No contracted-rate candidates exist to compute the QPA"):
    return ApiError("ERR_QPA_UNAVAILABLE", msg, 422)


def idr_amount_mismatch(msg="winning_amount_cents does not equal the winning party's offer"):
    return ApiError("ERR_IDR_AMOUNT_MISMATCH", msg, 422)


def appeal_window_closed(msg="Appeal submitted after appeal_window_deadline"):
    return ApiError("ERR_APPEAL_WINDOW_CLOSED", msg, 409)


def appeal_in_progress(msg="An appeal is SUBMITTED or UNDER_REVIEW for this claim"):
    return ApiError("ERR_APPEAL_IN_PROGRESS", msg, 409)


def claim_not_finalized(msg="A claim on the invoice is not FINALIZED"):
    return ApiError("ERR_CLAIM_NOT_FINALIZED", msg, 409)


def claim_already_invoiced(msg="Claim already appears on a non-voided FeeInvoice"):
    return ApiError("ERR_CLAIM_ALREADY_INVOICED", msg, 409)


def transparency_not_enabled(msg="Transparency reporting not enabled or invoice not ISSUED"):
    return ApiError("ERR_TRANSPARENCY_NOT_ENABLED", msg, 422)
