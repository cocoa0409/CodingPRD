"""Retailer verification loop (queue A, non_linear_state_machine): a bounded
PENDING -> MORE_INFO_REQUESTED -> PENDING cycle capped at three resubmissions."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    make_retailer_headers,
    read_retailer,
    register_retailer,
    validate_error,
    validate_success,
)


def _request_more_info(api, retailer_id):
    return validate_success(
        api.request_more_info(retailer_id, {"reason": "unclear"}, ADMIN)
    )


def _resubmit(api, retailer_id):
    return api.resubmit_verification(
        retailer_id,
        {
            "storefront_proof_url": "https://proof.example/new",
            "resale_certificate_no": "RC-NEW",
        },
        make_retailer_headers(retailer_id),
    )


def test_resubmission_loop_cycles_back_to_pending(api):
    """PRD §3.1: "The retailer itself — and only that retailer, since
    `X-User-ID` must equal the retailer's own `id` — may then resubmit a fresh
    `storefront_proof_url` and `resale_certificate_no`, which returns the
    retailer to `PENDING`, resets both document sub-states to `PENDING`, and
    increments `verification_resubmission_count`."

    Design: Difficulty/non_linear_state_machine/retailer_verification_cycle
    """
    retailer = register_retailer(api)
    _request_more_info(api, retailer["id"])

    resubmitted = validate_success(_resubmit(api, retailer["id"]))
    assert resubmitted["verification_status"] == "PENDING"
    assert resubmitted["verification_resubmission_count"] == 1
    assert resubmitted["storefront_proof_status"] == "PENDING"
    assert resubmitted["resale_cert_status"] == "PENDING"

    # A second full cycle also succeeds.
    _request_more_info(api, retailer["id"])
    resubmitted = validate_success(_resubmit(api, retailer["id"]))
    assert resubmitted["verification_resubmission_count"] == 2


def test_fourth_resubmission_is_rejected_at_the_cap(api):
    """PRD §3.1: "This loop is capped: a resubmission attempted when the count
    has already reached 3 is rejected with `ERR_RESUBMISSION_LIMIT` (HTTP 422),
    so a retailer cycles through at most three rounds of additional
    information."

    Design: Difficulty/non_linear_state_machine/retailer_verification_cycle
    """
    retailer = register_retailer(api)
    for _ in range(3):
        _request_more_info(api, retailer["id"])
        validate_success(_resubmit(api, retailer["id"]))
    _request_more_info(api, retailer["id"])

    response = _resubmit(api, retailer["id"])
    validate_error(response, ApiErrorId.ERR_RESUBMISSION_LIMIT, 422)

    refreshed = read_retailer(api, retailer["id"])
    assert refreshed["verification_status"] == "MORE_INFO_REQUESTED"
    assert refreshed["verification_resubmission_count"] == 3
