"""Role-based access control, the logical clock and operations-run identity."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import (
    create_bureau_snapshot_payload,
    create_consumer_payload,
    create_lender_program_payload,
)
from test_helpers.fixtures import (
    BUREAU_CONNECTOR,
    COMPLIANCE_OFFICER,
    LENDER_OPS,
    PLATFORM_ADMIN,
    REFEREE,
    create_active_catalog_item,
    create_active_lender,
    create_active_program,
    create_active_score_tier,
    create_consumer,
    create_referral_for,
    fund_referral,
    read_consumer_version,
    reset_clock,
    setup_consented_scenario,
    setup_monitored,
    setup_offer_scenario,
)


def test_bureau_connector_cannot_read_consumer_identity(api, as_consumer):
    """PRD §2.1: "`LenderOps` authors targeting criteria and records referrals, funding
    and declines." PRD §2.1: "`BureauConnector` performs scheduled pulls and replays
    cancelled ones and is deliberately barred from reading consumer identity data."

    Design: Corner/rbac/bureau_connector_cannot_read_consumer_identity
    """
    ctx = setup_monitored(api=api)
    response = api.get_consumer(ctx["consumer"]["id"], BUREAU_CONNECTOR)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    validate_success(api.get_consumer(ctx["consumer"]["id"], as_consumer(ctx["consumer"]["id"])), 200)


def test_referee_cannot_author_targeting_criteria(api, as_consumer):
    """PRD §2.1: "A `LenderOps` operator ... records referrals, funding and declines."
    PRD §2.1: "When the headers are well formed but the caller's role is not among the
    roles an endpoint admits, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` and
    an HTTP 403 status."

    Design: Corner/rbac/referee_cannot_author_targeting_criteria
    """
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    program = create_active_program(lender_id=lender["id"], item_id=item["id"], api=api)

    response = api.create_targeting_criterion(
        program["id"],
        {"criterion_field": "SCORE", "operator": "GTE", "criterion_value": "640",
         "is_hard_requirement": True},
        REFEREE,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    assert validate_success(
        api.list_program_targeting_criteria(program["id"], PLATFORM_ADMIN), 200
    ) == []

    validate_success(
        api.create_targeting_criterion(
            program["id"],
            {"criterion_field": "SCORE", "operator": "GTE", "criterion_value": "640",
             "is_hard_requirement": True},
            LENDER_OPS,
        ),
        201,
    )


def test_lender_ops_cannot_reverse_a_funded_referral(api, as_consumer):
    """PRD §2.1: "A `ComplianceOfficer` performs reversals, records lender compliance
    determinations, pauses and resumes programs, withdraws offers, and sets render
    policy jointly with a `PlatformAdmin`."

    Design: Corner/rbac/lender_ops_cannot_reverse_a_funded_referral
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9600", api=api)
    funded = fund_referral(referral["id"], funded_amount_cents=500_000, api=api)
    assert funded["status"] == "FUNDED"

    response = api.reverse_referral(
        referral["id"], {"reason_code": "LENDER_RETURNED_FUNDS"}, LENDER_OPS
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    assert validate_success(
        api.get_referral(referral["id"], PLATFORM_ADMIN), 200
    )["status"] == "FUNDED"


def test_consumer_cannot_qualify_a_decision(api, as_consumer):
    """PRD §2.1: "A `Referee` is an operations referee and never owns consumer data:
    they promote an eligible decision to pre-qualified, drive dispute submission and
    acknowledgement, author content quality scores, set render policy, suppress score
    alerts, and re-derive a simulation against the settled variant."
    PRD §2.1: "When the headers are well formed but the caller's role is not among the
    roles an endpoint admits, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` and
    an HTTP 403 status."

    Design: Corner/rbac/consumer_cannot_qualify_a_decision_or_acknowledge_a_dispute
    """
    from test_helpers.fixtures import create_decision, setup_catalog_scenario

    ctx = setup_catalog_scenario(api=api)
    consumer = setup_monitored(api=api, email="role@example.com", bureau_pin="2604")["consumer"]
    decision = create_decision(consumer["id"], ctx["program"]["id"], api=api)
    assert decision["decision_status"] == "ELIGIBLE"

    response = api.qualify_decision(decision["id"], as_consumer(consumer["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    assert validate_success(
        api.get_prequalification_decision(decision["id"], REFEREE), 200
    )["decision_status"] == "ELIGIBLE"


def test_consumer_cannot_acknowledge_a_dispute(api, as_consumer):
    """PRD §2.1: "A `Consumer` self-enrols, grants monitoring consent, requests pulls
    of their own monitoring views, runs simulations, creates pre-qualification decisions
    for themselves, generates and renders their own offers, and acknowledges their own
    score alerts; the alert threshold override is likewise theirs alone to set."

    Design: Corner/rbac/consumer_cannot_qualify_a_decision_or_acknowledge_a_dispute
    """
    from test_helpers.factories import create_dispute_referral_payload

    ctx = setup_monitored(api=api, email="role2@example.com", bureau_pin="2605")
    dispute = validate_success(
        api.create_dispute_referral(
            create_dispute_referral_payload(ctx["consumer"]["id"], ctx["snapshot"]["id"]),
            REFEREE,
        ),
        201,
    )
    response = api.acknowledge_dispute_referral(
        dispute["id"], {"bureau_case_ref": "BUR-123"}, as_consumer(ctx["consumer"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


def test_platform_admin_cannot_score_content_quality(api, as_consumer):
    """PRD §2.1: "A `Referee` ... author content quality scores".
    PRD §2.1: "When the headers are well formed but the caller's role is not among the
    roles an endpoint admits, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/platform_admin_can_run_the_ops_sweep_but_not_author_content
    """
    from test_helpers.factories import create_content_quality_facet_payload

    ctx = setup_monitored(api=api, email="adminb@example.com", bureau_pin="3715")
    facet = validate_success(
        api.create_content_quality_facet(
            ctx["consumer"]["id"],
            create_content_quality_facet_payload(topic="factor_explanations", score_bps=5000),
            REFEREE,
        ),
        201,
    )
    response = api.score_content_quality_facet(facet["id"], {"score_bps": 9000}, PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    unchanged = validate_success(
        api.list_consumer_content_quality_facets(ctx["consumer"]["id"], REFEREE), 200
    )[0]
    assert unchanged["score_bps"] == 5000
    assert unchanged["status"] == "INCOMPLETE"


def test_forbidden_role_outranks_a_nonexistent_resource(api, consumer_headers):
    """PRD §2.11: "Role authorization is second, yielding `ERR_FORBIDDEN_FOR_ROLE` at
    HTTP 403. Path-segment existence is third, yielding `ERR_CONSUMER_NOT_FOUND` at
    HTTP 404".
    PRD §2.11: "Authentication is evaluated first".

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_nonexistent_resource
    """
    ctx = setup_monitored(api=api)
    response = api.create_simulation(
        ctx["consumer"]["id"],
        {"actions": [{"action_code": "PAY_DOWN_REVOLVING", "amount_cents": 50_000}],
         "expected_consumer_version": ctx["consumer"]["version"]},
        BUREAU_CONNECTOR,
    )
    data = validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    assert data["error_id"] == "ERR_FORBIDDEN_FOR_ROLE"
    assert validate_success(
        api.list_consumer_simulations(ctx["consumer"]["id"], consumer_headers), 200
    ) == []


def test_settled_index_is_role_restricted(api, consumer_headers):
    """PRD §2.1: "When the headers are well formed but the caller's role is not among
    the roles an endpoint admits, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    and an HTTP 403 status."

    Design: Corner/endpoints/conditional_action_requires_free_decision_expiry_window
    """
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    create_active_lender(api=api)

    response = api.get_catalog_item_settled_index(item["id"], consumer_headers)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    validate_success(api.get_catalog_item(item["id"], consumer_headers), 200)


def test_clock_cannot_be_moved_backwards(api, as_consumer):
    """PRD §2.4: "The clock is monotonic: setting it to an instant strictly earlier
    than its current value is rejected with `ERR_CLOCK_NOT_MONOTONIC`, while setting it
    to the value it already holds is accepted and treated as a no-op."

    Design: Corner/errors/clock_cannot_be_moved_backwards
    """
    reset_clock(api=api)
    validate_success(api.set_clock("2026-10-01T00:00:00Z", PLATFORM_ADMIN), 200)

    rewind = api.set_clock("2026-09-15T00:00:00Z", PLATFORM_ADMIN)
    validate_error(rewind, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC, 409)

    validate_success(api.set_clock("2026-10-01T00:00:00Z", PLATFORM_ADMIN), 200)

    created_after = validate_success(
        api.create_consumer(create_consumer_payload(email="clock@example.com"), as_consumer("clock")),
        201,
    )
    assert created_after["created_at"].startswith("2026-10-01")


def test_ops_run_key_cannot_be_replayed(api):
    """PRD §2.4: "A `run_key` must be unique across all `OpsRun` rows; a repeat is
    rejected with `ERR_OPS_RUN_KEY_DUPLICATE`."

    Design: Corner/errors/ops_run_key_cannot_be_replayed
    """
    reset_clock(api=api)
    first = validate_success(
        api.run_ops({"run_key": "daily-2026-09-01"}, PLATFORM_ADMIN), 201
    )
    assert first["status"] in ("COMPLETED", "PARTIAL")
    assert first["status"] != "RUNNING"

    replay = api.run_ops({"run_key": "daily-2026-09-01"}, PLATFORM_ADMIN)
    validate_error(replay, ApiErrorId.ERR_OPS_RUN_KEY_DUPLICATE, 409)

    validate_success(api.run_ops({"run_key": "daily-2026-09-02"}, PLATFORM_ADMIN), 201)


def test_status_filters_select_on_the_exact_enumerated_string(api, as_consumer):
    """PRD §3.2: "The alert listing also accepts a `status` filter, and the decision
    listing accepts a `decision_status` filter, both of which select on the exact
    enumerated status strings rather than on any derived label."

    Design: Corner/entities/referrals_list_paginates_and_reports_total_count_and_has_more
    """
    ctx = setup_monitored(api=api, email="nadia@example.com", bureau_pin="6600")

    pending = validate_success(
        api.list_consumer_score_alerts(
            ctx["consumer"]["id"], as_consumer(ctx["consumer"]["id"]), params={"status": "PENDING"}
        ),
        200,
    )
    suppresseed = validate_success(
        api.list_consumer_score_alerts(
            ctx["consumer"]["id"], as_consumer(ctx["consumer"]["id"]),
            params={"status": "SUPPRESSED"},
        ),
        200,
    )
    assert pending == [] or all(a["status"] == "PENDING" for a in pending)
    assert suppresseed == [] or all(a["status"] == "SUPPRESSED" for a in suppresseed)


def test_referral_listing_paginates_and_reports_total_count(api, as_consumer):
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`; these four fields are the pagination contract and
    appear on every list response."
    PRD §2.3: "`limit` caps the number of items returned and defaults to 10 when
    omitted".

    Design: Corner/entities/referrals_list_paginates_and_reports_total_count_and_has_more
    """
    from test_helpers import validate_paginated

    ctx = setup_consented_scenario(api=api)
    create_referral_for(ctx, external_referral_ref="NS-L-9200", api=api)

    data, meta = validate_paginated(
        api.list_referrals(
            PLATFORM_ADMIN, params={"consumer_id": ctx["consumer"]["id"], "limit": 1, "offset": 0}
        )
    )
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    matched, matched_meta = validate_paginated(
        api.list_referrals(
            PLATFORM_ADMIN, params={"consumer_id": ctx["consumer"]["id"], "status": "SENT"}
        )
    )
    assert len(matched) == 1

    empty, empty_meta = validate_paginated(
        api.list_referrals(
            PLATFORM_ADMIN, params={"consumer_id": ctx["consumer"]["id"], "status": "FUNDED"}
        )
    )
    assert empty == []
    assert empty_meta["total_count"] == 0


def test_referral_listing_applies_the_default_page_window(api, as_consumer):
    """PRD §2.3: "`limit` caps the number of items returned and defaults to 10 when
    omitted". PRD §2.3: "`offset` states how many items to skip and defaults to 0."

    Design: Corner/entities/referrals_list_paginates_and_reports_total_count_and_has_more
    """
    from test_helpers import validate_paginated

    ctx = setup_consented_scenario(api=api)
    create_referral_for(ctx, external_referral_ref="NS-L-9201", api=api)

    data, meta = validate_paginated(
        api.list_referrals(PLATFORM_ADMIN, params={"consumer_id": ctx["consumer"]["id"]})
    )
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) <= 10


def test_revenue_entries_are_append_only_with_no_separate_route(api):
    """PRD §2.10: "A `RevenueRecognitionEntry` is an append-only ledger line and also
    carries only `id` and `created_at`."
    PRD §4: `GET /credit/revenue-recognition-entries` | List revenue recognition entries.

    Design: Corner/entities/revenue_recognition_entry_has_no_update_endpoint
    """
    reset_clock(api=api)
    data = validate_success(api.list_revenue_entries(PLATFORM_ADMIN), 200)
    assert data == []

    response = api.list_revenue_entries(PLATFORM_ADMIN)
    assert response.json()["response_type"] == "array"


def test_decision_creation_requires_an_existing_program(api, as_consumer):
    """PRD §2.9: "The rejection is an HTTP 404 with `ERR_CONSUMER_NOT_FOUND`, raised for
    any path-segment identifier that does not resolve to a resource of the type the
    segment names".
    PRD §2.9: "Creation operations follow the same order: the container is verified,
    then its rules, then the child payload."

    Design: Corner/entities/decision_creation_requires_an_existing_program
    """
    consumer = create_consumer(email="orphan@example.com", bureau_pin="5555", api=api)
    validate_success(
        api.grant_monitoring_consent(consumer["id"], as_consumer(consumer["id"])), 200
    )
    from test_helpers.fixtures import pull_bureau_snapshot

    pull_bureau_snapshot(consumer["id"], score=660, balance_cents=100_000, api=api)

    response = api.create_prequalification(
        consumer["id"],
        {"lender_program_id": "6f2b1c44-0000-4000-8000-000000000002"},
        as_consumer(consumer["id"]),
    )
    data = validate_error(response, ApiErrorId.ERR_CONSUMER_NOT_FOUND, 404)
    assert data["error_id"] is not None
    assert validate_success(
        api.list_consumer_decisions(consumer["id"], PLATFORM_ADMIN), 200
    ) == []