"""Request validation, uniqueness, RBAC, ownership, bookability, rates,
licensing windows, and duplicate-dispute rejections."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_active_talent,
    create_confirmed_order,
    create_delivered_order,
    create_order,
    get_success_data,
    license_grant_payload,
    make_admin_headers,
    make_buyer_headers,
    make_talent_headers,
    moderate_video_clear,
    open_dispute,
    read_order,
    read_talent,
    register_buyer,
    register_talent,
    submit_identity,
    submit_tax_document,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def test_create_talent_missing_email_rejected(api):
    """PRD §3.1: "A creator joins the marketplace by registering a talent
    account with a `stage_name`, a `legal_name`, an `email`, and an
    `identity_document_ref`."
    PRD §2.8: "Fourth, request-body shape is validated: required fields
    present, enum values within their declared sets, datetimes in ISO 8601,
    integers within declared ranges; violations yield `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/create_talent_missing_email_returns_invalid_request
    """
    response = api.create_talent(
        {"stage_name": "No Email", "legal_name": "No Email Legal"},
        headers=make_talent_headers("t-missing-email"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_stage_name_case_insensitive_rejected(api):
    """PRD §3.1: "The `stage_name` is the public display name and must be
    between 1 and 80 characters, unique across all talent records
    case-insensitively; the `email` is likewise unique across talent records
    case-insensitively."
    PRD §3.1: "A registration that collides with an existing `stage_name` or
    `email` is rejected with `ERR_DUPLICATE_UNIQUE_FIELD` (HTTP 409)."

    Design: Corner/entities/create_talent_duplicate_stage_name_rejected
    """
    register_talent(api, stage_name="Case Star", email="case1@example.com")
    response = api.create_talent(
        {
            "stage_name": "case star",
            "legal_name": "Other Legal",
            "email": "case2@example.com",
            "identity_document_ref": "d2",
        },
        headers=make_talent_headers("t-dupe"),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD.value)


def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.8: "Third, every identifier referenced in the request path is
    validated for existence in strict left-to-right order — the talent before
    the order, the order before the child resource — and the first missing
    identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_order_returns_not_found
    """
    response = api.get_order(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers=make_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)


def test_new_talent_computed_fields_start_at_zero(api):
    """PRD §3.1: "A newly registered talent begins in `PENDING_VERIFICATION`
    status with `availability` set to `BOOKABLE`, all balances at zero, and
    `commission_tier` at `STANDARD`."

    Design: Corner/entities/talent_computed_balances_start_at_zero
    """
    talent = register_talent(api)
    assert talent["status"] == "PENDING_VERIFICATION"
    assert talent["availability"] == "BOOKABLE"
    assert talent["pending_balance_cents"] == 0
    assert talent["paid_out_balance_cents"] == 0
    assert talent["trailing_gmv_cents"] == 0
    assert talent["commission_tier"] == "STANDARD"


def test_order_gross_frozen_at_creation(api):
    """PRD §3.3: "Creation freezes the price: `gross_amount_cents` is
    captured from the talent's rate for the chosen `use_type` at the moment
    of creation — the personal rate for `PERSONAL`, the business rate for
    `BUSINESS_USE`, the advertising rate for `ADVERTISING_USE` — and never
    moves afterward, even if the talent changes its rates mid-flight."

    Design: Corner/entities/order_freezes_gross_at_creation_from_use_type_rate
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_order(api, talent, buyer)
    assert order["gross_amount_cents"] == 10000

    # Change the talent's rates mid-flight.
    from test_helpers import set_rates

    set_rates(
        api,
        talent,
        personal_rate_cents=20000,
        business_rate_cents=80000,
        advertising_rate_cents=160000,
    )

    frozen = read_order(api, order["id"])
    assert frozen["gross_amount_cents"] == 10000


def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "`limit` specifies the maximum number of items to return;
    when omitted it defaults to 10, and any supplied value must be at least 1
    and at most 100. `offset` specifies how many items to skip and defaults
    to 0."
    PRD §2.3: "Paginated list responses include the fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the response
    envelope."

    Design: Corner/entities/list_orders_pagination_envelope
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_order(api, talent, buyer)

    data, meta = validate_paginated(
        api.list_orders(headers=make_admin_headers())
    )
    assert isinstance(data, list) and len(data) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_request_without_role_header_rejected(api):
    """PRD §2.1: "Every request must carry `X-User-ID` to identify the acting
    user and `X-User-Role` to specify their operational capacity. The system
    recognizes exactly four roles, spelled precisely as follows: `Talent`,
    `Buyer`, `Moderator`, and `PlatformAdmin`. A request arriving with
    missing or malformed headers — or with a role string outside that set —
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_missing_headers
    """
    response = api.list_talents(headers={"X-User-ID": "someone"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_request_with_unknown_role_rejected(api):
    """PRD §2.1: "Every request must carry `X-User-ID` to identify the acting
    user and `X-User-Role` to specify their operational capacity. The system
    recognizes exactly four roles, spelled precisely as follows: `Talent`,
    `Buyer`, `Moderator`, and `PlatformAdmin`. A request arriving with
    missing or malformed headers — or with a role string outside that set —
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_missing_headers
    """
    response = api.list_talents(headers={"X-User-ID": "x", "X-User-Role": "Wizard"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_buyer_cannot_moderate_videos(api):
    """PRD §2.1: "Admin-scoped actions (activation, suspension, tax review,
    dispute resolution, sweeps, payout lifecycle, logical-clock control,
    forced pricing-suggestion refresh) are reserved for `PlatformAdmin`;
    video moderation may additionally be performed by a `Moderator`."
    PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint per the authorization matrix in §4 is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/buyer_cannot_moderate_videos
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    _order, video = create_delivered_order(api, talent, buyer, moderate=None)

    response = api.moderate_video(
        video["id"], "CLEAR", headers=make_buyer_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    # The video is untouched.
    videos = api.list_videos(_order["id"], headers=make_admin_headers()).json()["data"]
    assert videos[0]["moderation_status"] == "PENDING_REVIEW"


def test_moderator_may_clear_videos(api):
    """PRD §2.1: "Admin-scoped actions (activation, suspension, tax review,
    dispute resolution, sweeps, payout lifecycle, logical-clock control,
    forced pricing-suggestion refresh) are reserved for `PlatformAdmin`;
    video moderation may additionally be performed by a `Moderator`."
    PRD §3.4: "A `PlatformAdmin` or `Moderator` reviews a `PENDING_REVIEW`
    video with a `decision` of `CLEAR` or `FLAG`. Clearing moves the video to
    `CLEARED`."

    Design: Corner/validations/buyer_cannot_moderate_videos
    """
    from test_helpers import make_moderator_headers

    talent = create_active_talent(api)
    buyer = register_buyer(api)
    _order, video = create_delivered_order(api, talent, buyer, moderate=None)

    response = api.moderate_video(
        video["id"], "CLEAR", headers=make_moderator_headers()
    )
    cleared = validate_success(response)
    assert cleared["moderation_status"] == "CLEARED"


def test_talent_cannot_confirm_own_order(api):
    """PRD §2.1: "When `X-User-Role` is `Talent`, `X-User-ID` is the `id` of
    the acting `Talent` record; ownership checks on any resource that
    references a talent (for example, an order's `talent_id`) compare that
    foreign-key field to `X-User-ID`, and a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `Buyer`,
    `X-User-ID` is the `id` of the acting `Buyer` record; ownership checks on
    any resource that references a buyer (for example, an order's `buyer_id`)
    compare that foreign-key field to `X-User-ID` under the same rejection
    rule."

    Design: Corner/validations/talent_cannot_confirm_own_order
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")

    response = api.confirm_order(
        order["id"], headers=make_talent_headers(talent["id"])
    )
    # The PRD §2.8 pipeline rejects a Talent caller at the role check (step 2,
    # ERR_UNAUTHORIZED); the ownership wording in §2.1 additionally admits the
    # ERR_NOT_RESOURCE_OWNER reading. Both honour "the talent cannot confirm".
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_UNAUTHORIZED.value, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value],
    )
    assert read_order(api, order["id"])["status"] == "DELIVERED"


def test_order_against_paused_talent_rejected(api):
    """PRD §3.3: "First, the talent must be bookable — `ACTIVE` in status
    with `availability` equal to `BOOKABLE` — otherwise the request is
    rejected with `ERR_TALENT_NOT_BOOKABLE` (HTTP 409)."
    PRD §3.2: "An `ACTIVE` talent may pause itself, moving to `PAUSED` and
    flipping `availability` to `PAUSED_AVAILABILITY`; pausing increments
    `availability_pause_count_30d`, the count of pauses started within the
    trailing 30 days."

    Design: Corner/validations/order_on_paused_talent_rejected
    """
    talent = create_active_talent(api)
    validate_success(
        api.pause_talent(talent["id"], headers=make_talent_headers(talent["id"]))
    )
    buyer = register_buyer(api)
    response = api.create_order(
        {
            "talent_id": talent["id"],
            "buyer_id": buyer["id"],
            "use_type": "PERSONAL",
            "occasion": "p",
            "script_instructions": "p",
            "recipient_name": "P",
        },
        headers=make_buyer_headers(buyer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TALENT_NOT_BOOKABLE.value)


def test_business_use_order_requires_business_account(api):
    """PRD §3.3: "Second, commercial requests require a commercial account:
    `BUSINESS_USE` and `ADVERTISING_USE` orders may only be placed by a buyer
    whose `is_business_account` flag is true, otherwise the request is
    rejected with `ERR_BUSINESS_ACCOUNT_REQUIRED` (HTTP 403)."

    Design: Corner/validations/business_use_order_requires_business_account
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api, is_business_account=False)
    response = api.create_order(
        {
            "talent_id": talent["id"],
            "buyer_id": buyer["id"],
            "use_type": "BUSINESS_USE",
            "occasion": "promo",
            "script_instructions": "promote us",
            "recipient_name": "Team",
        },
        headers=make_buyer_headers(buyer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_BUSINESS_ACCOUNT_REQUIRED.value)


def test_inverted_rate_ordering_rejected(api):
    """PRD §3.2: "The business rate must be at least four times the
    personal-rate floor — that is, at least 400 cents — and at least the
    personal rate itself. The advertising rate must be at least eight times
    the personal-rate floor — at least 800 cents — and at least the business
    rate. Any violation is rejected with `ERR_RATE_OUT_OF_BOUNDS`."

    Design: Corner/validations/rate_below_floor_or_inverted_rejected
    """
    talent = register_talent(api)
    submit_identity(api, talent)
    submit_tax_document(api, talent, decision="VERIFY")
    current = read_talent(api, talent["id"])
    response = api.set_rates(
        talent["id"],
        {
            "personal_rate_cents": 50000,
            "business_rate_cents": 40000,
            "advertising_rate_cents": 80000,
            "turnaround_hours": 72,
            "expected_talent_version": current["version"],
        },
        headers=make_talent_headers(talent["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RATE_OUT_OF_BOUNDS.value)


def test_personal_rate_below_floor_rejected(api):
    """PRD §3.2: "The personal rate must be at least 100 cents and at most
    10000000 cents."
    PRD §3.2: "Any violation is rejected with `ERR_RATE_OUT_OF_BOUNDS`."

    Design: Corner/validations/rate_below_floor_or_inverted_rejected
    """
    talent = register_talent(api)
    submit_identity(api, talent)
    submit_tax_document(api, talent, decision="VERIFY")
    current = read_talent(api, talent["id"])
    response = api.set_rates(
        talent["id"],
        {
            "personal_rate_cents": 99,
            "business_rate_cents": 400,
            "advertising_rate_cents": 800,
            "turnaround_hours": 72,
            "expected_talent_version": current["version"],
        },
        headers=make_talent_headers(talent["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RATE_OUT_OF_BOUNDS.value)


def test_zero_length_license_window_rejected(api):
    """PRD §3.7: "A window whose `starts_at` is not strictly before `ends_at`
    — zero-length or inverted — is rejected with
    `ERR_INVALID_LICENSE_WINDOW` (HTTP 422)."

    Design: Corner/validations/invalid_license_window_rejected
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api, is_business_account=True)
    order, _video = create_confirmed_order(api, talent, buyer, use_type="BUSINESS_USE")

    response = api.create_license_grant(
        order["id"],
        license_grant_payload(
            license_type="BUSINESS",
            territory="DOMESTIC",
            channels=["SOCIAL"],
            starts_at="2026-10-01T00:00:00Z",
            ends_at="2026-10-01T00:00:00Z",
        ),
        headers=make_buyer_headers(buyer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_LICENSE_WINDOW.value)


def test_second_dispute_rejected(api):
    """PRD §3.6: "An order may have at most one dispute ever; a second
    attempt is rejected with `ERR_DISPUTE_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/validations/duplicate_dispute_rejected
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_confirmed_order(api, talent, buyer)
    open_dispute(api, buyer, order, reason="first dispute")

    current = read_order(api, order["id"])
    response = api.open_dispute(
        order["id"], "second dispute", current["version"],
        headers=make_buyer_headers(buyer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_ALREADY_EXISTS.value)


def test_confirm_with_uncleared_video_rejected(api):
    """PRD §3.4: "The moderation gate is enforced on every buyer-facing
    consumption of a video — confirmation, buyer-initiated re-record
    requests, and license creation all require the latest video on the order
    to be `CLEARED`, and any of the three attempted against an uncleared
    latest video is rejected with `ERR_VIDEO_NOT_CLEARED` (HTTP 409)."

    Design: Corner/errors/err_video_not_cleared_on_confirm
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate=None)

    response = api.confirm_order(order["id"], headers=make_buyer_headers(buyer["id"]))
    validate_error(response, ApiErrorId.ERR_VIDEO_NOT_CLEARED.value)
    assert read_order(api, order["id"])["status"] == "DELIVERED"


def test_rerecord_request_with_uncleared_video_rejected(api):
    """PRD §3.4: "The moderation gate is enforced on every buyer-facing
    consumption of a video — confirmation, buyer-initiated re-record
    requests, and license creation all require the latest video on the order
    to be `CLEARED`, and any of the three attempted against an uncleared
    latest video is rejected with `ERR_VIDEO_NOT_CLEARED` (HTTP 409)."

    Design: Corner/errors/err_video_not_cleared_on_confirm
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate=None)

    response = api.request_rerecord(
        order["id"], "redo it", headers=make_buyer_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.ERR_VIDEO_NOT_CLEARED.value)
