"""Validation precedence between state and research independence, and RBAC walls."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_account,
    create_analyst,
    create_document,
    create_inclusion,
    create_seat,
    create_vendor,
    get_document,
    get_success_data,
    make_analyst_headers,
    make_seat_holder_headers,
    make_vendor_rep_headers,
    set_clock,
    setup_document_with_inclusion,
    setup_published_document,
    validate_error,
)


def test_state_error_precedes_the_self_review_error_on_submit_for_review():
    """PRD §2.11: "Beyond existence, checks run in a fixed precedence. When more than
    one check would fail, the earliest one in this ordering determines the response,
    and later checks are not evaluated".
    PRD §2.11: "Target state: the resource named by the request is in a state from
    which the requested transition exists, and a resource in a terminal state rejects
    every further transition. Failure is `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.11: "Research independence, as defined in §2.5. Failure is
    `ERR_SEPARATION_OF_DUTIES_VIOLATION` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_safety_on_submit_for_review
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    reviewer = create_analyst(
        full_name="Ravi Menon", seniority="SENIOR", topic_routes=["CLOUD_COST"]
    )
    document_a = create_document(lead, title="Comparative Matrix: Observability")
    submit = api_client.submit_for_review(
        document_a["id"], {"peer_reviewer_analyst_id": reviewer["id"]},
        make_analyst_headers(lead["id"]),
    )
    get_success_data(submit, expected_status=200)
    document_b = create_document(lead, title="Comparative Matrix: Data Platforms")

    dual = api_client.submit_for_review(
        document_a["id"], {"peer_reviewer_analyst_id": lead["id"]},
        make_analyst_headers(lead["id"]),
    )
    validate_error(dual, ApiErrorId.ERR_INVALID_STATE)

    safety_only = api_client.submit_for_review(
        document_b["id"], {"peer_reviewer_analyst_id": lead["id"]},
        make_analyst_headers(lead["id"]),
    )
    validate_error(safety_only, ApiErrorId.ERR_SEPARATION_OF_DUTIES_VIOLATION)

    first = get_document(document_a)
    assert first["editorial_status"] == "PEER_REVIEW"
    assert first["peer_review_round"] == 1
    assert get_document(document_b)["editorial_status"] == "DRAFT"


def test_each_submit_for_review_error_is_reproducible_in_isolation():
    """PRD §2.11: "Target state: the resource named by the request is in a state from
    which the requested transition exists, and a resource in a terminal state rejects
    every further transition. Failure is `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.5: "The named reviewer must be set and must differ from `lead_analyst_id`; a
    submission that names the author as reviewer is rejected with
    `ERR_SEPARATION_OF_DUTIES_VIOLATION` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_safety_on_submit_for_review
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    reviewer = create_analyst(
        full_name="Ravi Menon", seniority="SENIOR", topic_routes=["CLOUD_COST"]
    )
    third = create_analyst(
        full_name="Priya Raman", seniority="VP", topic_routes=["CLOUD_COST"]
    )
    in_review = create_document(lead, title="Comparative Matrix: Observability")
    get_success_data(
        api_client.submit_for_review(
            in_review["id"], {"peer_reviewer_analyst_id": reviewer["id"]},
            make_analyst_headers(lead["id"]),
        ),
        expected_status=200,
    )

    state_only = api_client.submit_for_review(
        in_review["id"], {"peer_reviewer_analyst_id": third["id"]},
        make_analyst_headers(lead["id"]),
    )
    validate_error(state_only, ApiErrorId.ERR_INVALID_STATE)

    draft = create_document(lead, title="Comparative Matrix: Data Platforms")
    safety_only = api_client.submit_for_review(
        draft["id"], {"peer_reviewer_analyst_id": lead["id"]},
        make_analyst_headers(lead["id"]),
    )
    validate_error(safety_only, ApiErrorId.ERR_SEPARATION_OF_DUTIES_VIOLATION)
    assert get_document(draft)["editorial_status"] == "DRAFT"


def test_appeal_after_the_window_returns_appeal_window_closed():
    """PRD §3.7: "An appeal filed after the window closes is rejected with
    `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409)".
    PRD §3.7: "while the parent document is `PUBLISHED` and the clock reading is at or
    before `appeal_window_closes_at`".

    Design: Corner/errors/appeal_after_the_window_returns_appeal_window_closed
    """
    scenario = setup_published_document(exclude_vendor=True)
    inclusion = scenario["excluded_inclusion"]
    window = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert window["appeal_window_closes_at"] == "2026-10-01T00:00:00Z"

    set_clock("2026-10-02T00:00:00Z")
    resp = api_client.file_appeal(
        inclusion["id"], {"appeal_grounds": "Filed after the window."},
        make_vendor_rep_headers(scenario["excluded_vendor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    unchanged = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert unchanged["inclusion_status"] == "EXCLUDED"
    assert unchanged["appeal_count"] == 0


def test_reprint_adjustment_beyond_the_authorized_copies_is_refused():
    """PRD §2.9: "An adjustment is refused with `ERR_REPRINT_COPIES_EXCEEDED`
    (HTTP 409) when it would drive `reprint_copies_used` below 0 or above
    `reprint_copies_authorized`."

    Design: Corner/errors/reprint_adjustment_beyond_authorized_copies_returns_reprint_copies_exceeded
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    vendor = create_vendor()
    document = create_document(lead)
    inclusion = create_inclusion(
        document, vendor, reprint_tier="STANDARD", permitted_marketing_use="NO_USE",
        reprint_copies_authorized=800,
    )

    resp = api_client.adjust_reprint_copies(
        inclusion["id"],
        {"delta_copies": 900, "permitted_marketing_use": "SOCIAL_SNIPPET"},
        make_vendor_rep_headers(vendor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REPRINT_COPIES_EXCEEDED)

    unchanged = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert unchanged["reprint_copies_used"] == 0
    assert unchanged["reprint_copies_authorized"] == 800
    assert unchanged["reprint_fee_cents"] == 0, (
        "The NO_USE multiplier is 0.00, so no fee is charged while the licence is unexercised"
    )


def test_sales_rep_cannot_publish_research():
    """PRD §2.1: "A request whose `X-User-Role` value is not listed among the roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/research/documents/{id}/publish` | Publish a cleared document
    and freeze the placement snapshot | ResearchDirector |"

    Design: Corner/rbac/sales_rep_cannot_publish_research
    """
    scenario = setup_published_document(publish=False)
    cleared = get_document(scenario["document"])
    assert cleared["editorial_status"] == "CLEARED"

    resp = api_client.publish_document(cleared["id"], TEST_USERS["sales_rep_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    unchanged = get_document(cleared)
    assert unchanged["editorial_status"] == "CLEARED"
    assert unchanged["published_at"] is None


def test_analyst_cannot_finalize_a_placement():
    """PRD §2.1: "A request whose `X-User-Role` value is not listed among the roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/research/vendor-inclusions/{id}/finalize` | Set the placement to
    INCLUDE or EXCLUDE | ResearchDirector |"

    Design: Corner/rbac/analyst_cannot_finalize_placement
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_document_with_inclusion()
    inclusion = scenario["inclusion"]
    assert inclusion["inclusion_status"] == "UNDER_EVALUATION"

    resp = api_client.finalize_inclusion(
        inclusion["id"], {"outcome": "INCLUDE"}, make_analyst_headers(scenario["lead"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    unchanged = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert unchanged["inclusion_status"] == "UNDER_EVALUATION"


def test_seat_holder_cannot_activate_their_own_seat():
    """PRD §2.1: "A request whose `X-User-Role` value is not listed among the roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/research/seats/{id}/activate` | Activate a provisioned seat and
    derive its research entitlements | ClientAdmin, PlatformAdmin |"

    Design: Corner/rbac/seat_holder_cannot_activate_seats
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    seat = create_seat(account, seat_email="nina@acme.example")

    resp = api_client.activate_seat(seat["id"], make_seat_holder_headers(seat["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    unchanged = get_success_data(api_client.get_seat(seat["id"]))
    assert unchanged["status"] == "PROVISIONED"
    assert unchanged["activated_at"] is None
    account_data = get_success_data(api_client.get_client(account["id"]))
    assert account_data["active_seat_count"] == 0
