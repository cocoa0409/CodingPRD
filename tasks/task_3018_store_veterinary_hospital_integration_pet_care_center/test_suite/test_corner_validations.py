"""Business rules that refuse a request: claim caps, header framing, envelope.

Two claims from the design index are deliberately not translated here. The
clinic staffing-failure family is not exercised because the PRD states the
staffing requirement without stating that its violation surfaces under the
coverage error, and the certificate-window family is not exercised because the
PRD's prose does not settle the ordering between the window violation and the
weekday violation when a certificate attempt breaks both. Their error
identifiers appear only in the catalogue, which carries no trigger conditions.
"""

from test_helpers import (
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    UNDECLARED_ROLE_HEADERS,
    ApiErrorId,
    approve_claim,
    create_store,
    read_incident,
    setup_incident_under_review,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import TEST_USERS

ANY = TEST_USERS["any_headers"]


def test_a_claim_above_the_state_cap_without_an_override_reason_is_refused(api):
    """The claim stays under review and nothing is paid.

    PRD §3.6: "The claim amount must not exceed the cap set for the store's state
    unless an `override_reason` is supplied as a non-empty string, and a claim
    above the cap without one is refused with `ERR_CLAIM_CAP_EXCEEDED`, which
    carries HTTP 402 because it is a payment rather than a structural refusal."
    PRD §3.6: "Approval then pays the claim in full"
    PRD §3.6: "The `available_claimable_cents` value tracks the claim amount less
    what has been paid, so it is non-zero exactly when the claim status is
    anything other than `APPROVED`."

    Design: Corner/validations/claim_cap_requires_override_reason
    """
    world = setup_incident_under_review(
        api, severity="SEVERE", incident_type="BITE", claim_amount_cents=400000, state_code="CA"
    )
    store_id = world["store"]["id"]
    incident = world["incident"]

    response = api.approve_claim(
        store_id,
        incident["id"],
        {"expected_incident_version": incident["version"]},
        TEST_USERS["store_manager_headers"],
    )
    validate_error(response, ApiErrorId.CLAIM_CAP_EXCEEDED.value, 402)

    unchanged = read_incident(api, incident["id"])
    assert unchanged["claim_status"] == "UNDER_REVIEW"
    assert unchanged["payout_amount_cents"] == 0
    assert unchanged["available_claimable_cents"] == 400000


def test_a_claim_above_the_cap_with_an_override_reason_is_approved(api):
    """The override reason is what admits the payment.

    PRD §3.6: "The claim amount must not exceed the cap set for the store's state
    unless an `override_reason` is supplied as a non-empty string"
    PRD §3.6: "Approval then pays the claim in full — the `payout_amount_cents`
    becomes equal to the `claim_amount_cents` — and records the compensation on
    the risk side by setting `risk_points_lost` equal to the incident's
    `risk_points`."
    PRD §3.6: "The incident's `available_claimable_cents` — the claim amount less
    what has been paid — falls to zero on approval"

    Design: Corner/validations/claim_cap_requires_override_reason
    """
    world = setup_incident_under_review(
        api, severity="SEVERE", incident_type="BITE", claim_amount_cents=400000, state_code="CA"
    )
    store_id = world["store"]["id"]
    incident = world["incident"]

    approved = approve_claim(
        api, store_id, incident, override_reason="Veterinary specialist referral attached"
    )
    assert approved["claim_status"] == "APPROVED"
    assert approved["payout_amount_cents"] == 400000
    assert approved["available_claimable_cents"] == 0
    assert approved["risk_points_lost"] == approved["risk_points"] == 40


def test_a_request_without_a_valid_user_context_is_refused(api):
    """Both headers are required and the role must be from the enumeration.

    PRD §2.1: "A request that omits either header, or that names a role outside
    the enumeration above, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies the
    acting user and `X-User-Role` declares the operational capacity in which that
    user is acting."
    PRD §2.1: "The API recognises nine role names, spelled exactly as follows"

    Design: Corner/validations/collection_satisfaction_returns_the_paginated_envelope
    """
    create_store(api, store_code="ST-1303", state_code="NY", hospital_capacity=3)

    missing_role = api.list_stores(MISSING_ROLE_HEADERS)
    validate_error(missing_role, ApiErrorId.MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)

    missing_user = api.list_stores(MISSING_USER_ID_HEADERS)
    validate_error(missing_user, ApiErrorId.MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)

    undeclared = api.list_stores(UNDECLARED_ROLE_HEADERS)
    validate_error(undeclared, ApiErrorId.MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)


def test_the_store_collection_returns_the_pagination_envelope(api):
    """An authenticated list call carries the four pagination fields.

    PRD §2.3: "Responses to list endpoints carry four pagination fields inside
    the `meta` object of the envelope: `limit`, `offset`, `total_count` and
    `has_more`."
    PRD §2.3: "`total_count` reflects the total number of rows matching the
    applied filters rather than the size of the current page, and `has_more`
    reports whether further rows remain beyond the current page."
    PRD §2.3: "`limit` caps the number of items returned and defaults to 10, with
    a minimum of 1 and a maximum of 100; a value outside that range is rejected
    as an invalid request."

    Design: Corner/validations/collection_satisfaction_returns_the_paginated_envelope
    """
    create_store(api, store_code="ST-1303", state_code="NY", hospital_capacity=3)

    data, meta = validate_paginated(api.list_stores(ANY, {"limit": 1, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(data) == 1

    out_of_range = api.list_stores(ANY, {"limit": 0})
    validate_error(out_of_range, ApiErrorId.INVALID_REQUEST.value, 400)