"""Violation-to-error tests: auth, shape, duplicates, in-progress review,
privacy consent, statement-dispute state, and the appeal window."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_channel,
    create_published_channel,
    create_ad_slot_grant,
    create_viewer,
    create_active_campaign,
    create_campaign,
    create_manufacturer,
    create_certified_model,
    create_device_unit,
    submit_channel_version,
    generate_statement,
    finalize_statement,
    set_clock,
    make_publisher_headers,
    make_viewer_headers,
    make_manufacturer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting caller, and `X-User-Role`, naming the
    caller's operational role. If either header is missing or empty, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any
    other processing."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.list_channels(headers={})
    assert resp.status_code == 401
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_invalid_enum_value_returns_invalid_request():
    """PRD §3.2: "A `Publisher` creates a channel by naming the owning
    publisher via `publisher_id`, choosing a display `name`, a `category` —
    one of `VIDEO`, `AUDIO`, `GAME`, `NEWS`, or `KIDS` — and a
    `content_rating` of `G`, `PG`, or `R18`."
    PRD §2.8: "Request shape: required fields present, types valid, enum
    membership, amounts positive where required, window ordering
    (`window_start` strictly before `window_end` for placements,
    `window_start` before or equal to `window_end` for lab benches), and
    period format `YYYY-MM` — else `ERR_INVALID_REQUEST`."

    Design: Corner/validations/invalid_enum_value_returns_invalid_request
    """
    publisher = create_publisher(legal_name="Enum Pub")

    resp = api_client.create_channel(
        {
            "publisher_id": publisher["id"],
            "name": "Bad Enum",
            "category": "MOVIES",
            "content_rating": "G",
        },
        make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    resp = api_client.list_channels(
        ADMIN, params={"publisher_id": publisher["id"]},
    )
    rows, meta = validate_paginated(resp)
    assert len(rows) == 0
    assert meta["total_count"] == 0


def test_grant_duplicate_period_rejected():
    """PRD §3.4: "Only one grant per channel per period may be live: if an
    `OPEN` grant already exists for the same channel and period, creation is
    rejected with `ERR_GRANT_PERIOD_DUPLICATE`."

    Design: Corner/validations/grant_duplicate_period_rejected
    """
    publisher = create_publisher(legal_name="Dup Pub")
    channel = create_published_channel(publisher)
    create_ad_slot_grant(channel["id"], period="2026-09", total_slots=100)

    resp = api_client.create_ad_slot_grant(
        {"channel_id": channel["id"], "period": "2026-09",
         "total_slots": 200},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_PERIOD_DUPLICATE, 409)

    resp = api_client.create_ad_slot_grant(
        {"channel_id": channel["id"], "period": "2026-10",
         "total_slots": 200},
        ADMIN,
    )
    validate_success(resp, expected_status=201)


def test_duplicate_serial_rejected_across_manufacturers():
    """PRD §3.10: "A `TvManufacturer` manufactures a unit by supplying the
    `device_model_id` — the model must be `CERTIFIED` and the manufacturer
    `LICENSED`, evaluated in the pinned referential order of §2.8 — a
    globally unique `serial_number` (a duplicate is rejected with
    `ERR_DUPLICATE_SERIAL`), the `hardware_cost_cents` (positive), and the
    near-cost `sale_price_cents` (zero or more)."

    Design: Corner/validations/duplicate_serial_rejected_across_manufacturers
    """
    ma = create_manufacturer(legal_name="MA TV")
    mb = create_manufacturer(legal_name="MB TV")
    moda = create_certified_model(ma, recovery_policy="MONETIZATION",
                                  model_code="A-1", bench_code="B1")
    modb = create_certified_model(mb, recovery_policy="MONETIZATION",
                                  model_code="B-1", bench_code="B2")
    create_device_unit(ma, moda["id"], serial_number="GLOBAL-1",
                       hardware_cost_cents=9000, sale_price_cents=9000)

    resp = api_client.create_device_unit(
        {
            "device_model_id": modb["id"],
            "serial_number": "GLOBAL-1",
            "hardware_cost_cents": 9000,
            "sale_price_cents": 9000,
        },
        make_manufacturer_headers(mb["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL, 409)


def test_review_while_in_review_rejected():
    """PRD §3.2: "If a version of the channel is already being reviewed (the
    channel is in `IN_REVIEW`), a new submission passes the state gate but is
    rejected at the business-constraint tier with `ERR_REVIEW_IN_PROGRESS`: a
    second review may not begin while one is in flight."

    Design: Corner/validations/review_while_in_review_rejected
    """
    publisher = create_publisher(legal_name="Rev Pub")
    channel = create_channel(publisher, name="Rev Channel")
    v1 = submit_channel_version(channel["id"], publisher["id"],
                                version_label="1.0.0")
    get_success_data(api_client.review_channel_version(v1["id"], ADMIN))

    current = get_success_data(api_client.get_channel(channel["id"], ADMIN))
    resp = api_client.create_channel_version(
        channel["id"],
        {
            "version_label": "1.0.1",
            "technical_checklist": {
                "deep_linking": True, "drm": True, "trick_play": True,
            },
            "expected_channel_version": current["version"],
        },
        make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_IN_PROGRESS, 409)
    assert get_success_data(
        api_client.get_channel_version(v1["id"], ADMIN)
    )["review_status"] == "IN_REVIEW"


def test_personalized_impression_on_opted_out_viewer_rejected():
    """PRD §3.5: "When a batch carries a `viewer_id` and the campaign's
    `targeting_mode` is `PERSONALIZED`, that viewer's `ad_consent` must be
    `PERSONALIZED`; a viewer who is `NON_PERSONALIZED` or `OPTED_OUT` rejects
    the personalized measurement with `ERR_PRIVACY_OPTED_OUT`."

    Design: Corner/validations/personalized_impression_on_opted_out_viewer_rejected
    """
    publisher = create_publisher(legal_name="Priv Pub")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(
        publisher, channel["id"], targeting_mode="PERSONALIZED",
    )
    viewer = create_viewer(email="priv@x.com", ad_consent="OPTED_OUT")

    resp = api_client.record_campaign_impressions(
        campaign["id"],
        {"impression_count": 100, "cpm_cents": 1000,
         "viewer_id": viewer["id"]},
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_PRIVACY_OPTED_OUT, 422)

    # After the viewer opts in, the identical batch succeeds — the consent
    # check is live, not a creation-time snapshot.
    get_success_data(api_client.update_viewer_privacy(
        viewer["id"], {"ad_consent": "PERSONALIZED"},
        make_viewer_headers(viewer["id"]),
    ))
    updated = validate_success(api_client.record_campaign_impressions(
        campaign["id"],
        {"impression_count": 100, "cpm_cents": 1000,
         "viewer_id": viewer["id"]},
        ADOPS,
    ))
    assert updated["spent_cents"] == 100
    assert updated["impressions_delivered"] == 100


def test_statement_dispute_requires_finalized_state():
    """PRD §3.7: "A publisher who disagrees with a finalized statement may
    raise a dispute against it (the statement dispute capability described in
    §3.9), which moves the statement from `FINALIZED` to `DISPUTED`,
    increments the statement's `version` by 1, and freezes settlement until
    the dispute is resolved; when the dispute is closed, the statement
    returns to `FINALIZED`."

    Design: Corner/validations/statement_dispute_requires_finalized_state
    """
    publisher = create_publisher(legal_name="Dsp Pub")
    statement = generate_statement(publisher["id"], "2026-09")
    assert statement["status"] == "OPEN"

    resp = api_client.create_statement_dispute(
        statement["id"], {"reason": "premature"},
        make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_success_data(api_client.get_statement(statement["id"], ADMIN))[
        "status"] == "OPEN"


def _setup_decided_upheld_dispute(publisher, channel_name):
    """Carry a channel to PUBLISHED, remove it, file + decide UPHELD."""
    channel = create_published_channel(publisher)
    get_success_data(api_client.remove_channel(
        channel["id"], {"reason": "policy"}, ADMIN,
    ))
    resp = api_client.create_dispute(
        {
            "publisher_id": publisher["id"],
            "subject_type": "CHANNEL_REMOVAL",
            "channel_id": channel["id"],
            "reason": "removal contested",
        },
        make_publisher_headers(publisher["id"]),
    )
    dispute = get_success_data(resp)
    get_success_data(api_client.triage_dispute(dispute["id"], ADMIN))
    get_success_data(api_client.request_dispute_evidence(dispute["id"], ADMIN))
    get_success_data(api_client.decide_dispute(
        dispute["id"], {"decision": "UPHELD"}, ADMIN,
    ))
    return channel, dispute


def test_appeal_at_exactly_seven_days_succeeds():
    """PRD §3.9: "The publisher may appeal a `DECIDED` dispute — but only
    within seven days of `decided_at`, with the boundary inclusive: an appeal
    at exactly seven days after the decision succeeds, one later than that is
    rejected with `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/validations/appeal_after_seven_day_window_expires
    """
    publisher = create_publisher(legal_name="App Pub")
    _, dispute = _setup_decided_upheld_dispute(publisher, "App C1")

    set_clock("2026-09-08T00:00:00Z")
    appealed = validate_success(api_client.appeal_dispute(
        dispute["id"], {"reason": "on the boundary"},
        make_publisher_headers(publisher["id"]),
    ))
    assert appealed["status"] == "APPEALED"


def test_appeal_after_seven_day_window_expires():
    """PRD §3.9: "The publisher may appeal a `DECIDED` dispute — but only
    within seven days of `decided_at`, with the boundary inclusive: an appeal
    at exactly seven days after the decision succeeds, one later than that is
    rejected with `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/validations/appeal_after_seven_day_window_expires
    """
    publisher = create_publisher(legal_name="App Pub 2")
    _, dispute = _setup_decided_upheld_dispute(publisher, "App C2")

    set_clock("2026-09-09T00:00:00Z")
    resp = api_client.appeal_dispute(
        dispute["id"], {"reason": "one day late"},
        make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, 409)
    assert get_success_data(api_client.get_dispute(dispute["id"], ADMIN))[
        "status"] == "DECIDED"
