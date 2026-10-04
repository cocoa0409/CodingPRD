"""Error responses: envelope shape, role vocabulary and the 402 mapping."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    POST_RELEASE_CLOCK_UTC,
    SPECIALIST,
    api_client,
    assert_error_envelope,
    build_user_headers,
    create_school,
    create_send,
    get_send,
    setup_released_score,
    validate_error,
)


def test_missing_required_field_returns_the_error_envelope():
    """PRD §2.6: "| 29 | Required fields are present and enum-valued fields carry a declared member | `ERR_INVALID_REQUEST` | 400 |"
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/invalid_request_error_envelope_shape
    """
    response = api_client.create_school(
        {
            "name": "Corner Ten High",
            "school_code": "CN0010",
            "country_code": "US",
            "center_code": "7010",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    body = response.json()
    assert_error_envelope(body)
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_REQUEST
    assert "school_code" not in body["data"]


def test_undeclared_role_header_is_rejected_as_unauthenticated():
    """PRD §2.1: "A request naming a role outside that set is rejected the same way as a request with no headers at all."
    PRD §2.6: "| 2 | `X-User-Role` is a declared role, and for an entity-backed role `X-User-ID` equals the `id` of an existing instance of the backing entity | `ERR_UNAUTHENTICATED` | 401 |"

    Design: Corner/errors/undeclared_role_header_returns_unauthenticated
    """
    school = create_school()

    response = api_client.get_school(school["id"], build_user_headers("ghost-cn-11", "GhostRole"))
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error["error_id"] != ApiErrorId.ERR_RESOURCE_NOT_FOUND, (
        "the path resource exists, so the refusal cannot be a not-found"
    )
    assert response.status_code == 401


def test_unsettled_send_fee_is_refused_with_payment_required():
    """PRD §3.8: "the move requires the send's `fee_cents` to have been settled, and an unsettled send is refused with `ERR_SEND_FEE_UNPAID`."
    PRD §2.6: "| 25 | A score send is only dispatched when its `fee_cents` has been settled | `ERR_SEND_FEE_UNPAID` | 402 |"

    Design: Corner/errors/unpaid_send_fee_maps_to_402
    """
    bundle = setup_released_score(release_clock=POST_RELEASE_CLOCK_UTC)
    score, school = bundle["score"], bundle["school"]
    sends = [
        create_send(score, school, recipient_type="COLLEGE", recipient_code=f"C-120{index}")
        for index in range(1, 6)
    ]
    fifth = sends[4]
    assert fifth["fee_cents"] > 0, (
        "five college sends exceed the two-send allowance under either variant"
    )

    response = api_client.transition_score_send(
        fifth["id"], {"to_status": "SENT", "fees_paid_cents": 0}, SPECIALIST
    )
    validate_error(response, ApiErrorId.ERR_SEND_FEE_UNPAID)
    assert response.status_code == 402

    assert get_send(fifth["id"], school)["status"] == "PENDING"
