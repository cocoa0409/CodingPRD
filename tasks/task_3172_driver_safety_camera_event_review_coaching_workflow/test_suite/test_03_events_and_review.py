"""Safety event ingestion, review cycle, OCC, and the review queue."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_review_decision,
    assert_safety_event,
    get_event,
    ingest_event,
    make_driver_headers,
    make_safety_manager_headers,
    register_clip,
    review_event,
    set_clock,
    setup_base,
    upload_clip,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_safety_event_payload, create_vehicle_payload
from test_helpers.fixtures import create_vehicle

MANAGER = TEST_USERS["safety_manager_headers"]
INGEST = TEST_USERS["telematics_ingest_headers"]


class TestUploadPriorityScore:
    def test_upload_priority_collision_boost(self, api):
        """PRD §3.3: "The base score is the severity weight — 1 for `LOW`, 3
        for `MEDIUM`, 6 for `HIGH`, 10 for `CRITICAL` — multiplied by the age
        step, multiplied by the vehicle's bandwidth tier multiplier (1 for
        `LOW`, 2 for `STANDARD`, 3 for `HIGH`). A `COLLISION` event
        additionally receives a flat boost of 1000 points."
        PRD §3.3: "The age contributes a step multiplier: 4 when the age is at
        most 6 hours, 2 when the age is greater than 6 hours and at most 24
        hours, and 1 beyond 24 hours."

        Design: Difficulty/combinatorial_formula/upload_priority_combinatorial
        """
        base = setup_base(clock="2026-08-30T00:00:00Z")
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="CRITICAL",
            occurred_at="2026-08-29T21:00:00Z",
        )
        assert event["upload_priority_score"] == 1120, (
            f"CRITICAL 10 x age_step 4 x HIGH tier 3 + 1000 boost = 1120, "
            f"got {event['upload_priority_score']}"
        )
        assert event["status"] == "DETECTED"

    def test_upload_priority_low_tier_old_event_and_queue_ordering(self, api, safety_manager_headers):
        """PRD §3.3: "The base score is the severity weight — 1 for `LOW`, 3
        for `MEDIUM`, 6 for `HIGH`, 10 for `CRITICAL` — multiplied by the age
        step, multiplied by the vehicle's bandwidth tier multiplier (1 for
        `LOW`, 2 for `STANDARD`, 3 for `HIGH`). A `COLLISION` event
        additionally receives a flat boost of 1000 points."
        PRD §3.3: "The review queue listing presents the fleet's events
        ordered by `upload_priority_score` descending; ties break by
        `occurred_at` ascending, then by `created_at` ascending, and a
        resource's `id` is never used as a tie-break input."

        Design: Difficulty/combinatorial_formula/upload_priority_combinatorial
        """
        base = setup_base(clock="2026-08-30T00:00:00Z")
        low_vehicle = create_vehicle(
            base["terminal"]["id"], vin="5YJSA1E26HF122334",
            camera_unit_id="CAM-12", bandwidth_tier="LOW",
        )
        ev_hi = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="CRITICAL",
            occurred_at="2026-08-29T21:00:00Z",
        )
        ev_lo = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], low_vehicle["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-27T00:00:00Z",
        )
        assert ev_lo["upload_priority_score"] == 1, (
            f"LOW 1 x age_step 1 x LOW tier 1 = 1, got {ev_lo['upload_priority_score']}"
        )
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(base["fleet"]["id"], safety_manager_headers)
        )
        assert len(rows) == 2
        assert rows[0]["id"] == ev_hi["id"], "higher score must sort first"
        assert rows[1]["id"] == ev_lo["id"]


class TestFirstUploadBubble:
    def test_first_upload_bubbles_event_to_in_review(self, api, safety_manager_headers, platform_admin_headers):
        """PRD §3.4: "An event becomes reviewable when its evidence arrives:
        the first footage clip of the event to complete upload transitions the
        event from `DETECTED` to `IN_REVIEW` automatically, bumps the event's
        `version`, and brings the event into the provisional scoring input set
        described in Section 3.9."
        PRD §3.5: "A completed upload also adds the clip's `size_mb` to the
        fleet's `retention_used_mb`."

        Design: Corner/state_machines/first_upload_bubbles_event_to_in_review
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip1 = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        clip2 = register_clip(
            event["id"], camera_angle="SIDE", captured_at="2026-08-30T00:00:01Z"
        )
        api.upload_begin_clip(clip1["id"], INGEST)
        api.upload_begin_clip(clip2["id"], INGEST)
        validate_success(api.upload_complete_clip(clip1["id"], INGEST), 200)
        after_first = get_event(event["id"])
        assert after_first["status"] == "IN_REVIEW"
        assert after_first["version"] == event["version"] + 1
        validate_success(api.upload_complete_clip(clip2["id"], INGEST), 200)
        after_second = get_event(event["id"])
        assert after_second["status"] == "IN_REVIEW"
        assert after_second["version"] == after_first["version"]
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["retention_used_mb"] == 10


class TestReviewCycle:
    def test_event_reclassify_reopen_cycle(self, api):
        """PRD §3.4: "Reclassifying moves it from `IN_REVIEW` to
        `RECLASSIFIED`, applying the supplied `new_event_type` and/or
        `new_severity`; at least one of the two must be supplied and differ
        from the current value, otherwise the request fails validation. A
        `RECLASSIFIED` or `DISMISSED` event may be returned to `IN_REVIEW` by
        the reopen action; reopening a reclassified event leaves
        `confirmed_at` unset as it was. An event may be reviewed repeatedly —
        there is no cap on `review_count`."
        PRD §3.4: "The log records, for every action, the acting manager's
        identifier as `reviewer_id`, the `action` (`CONFIRM`, `DISMISS`,
        `RECLASSIFY`, or `REOPEN`), the event's `prior_event_type` and
        `prior_severity`, the `new_event_type` and `new_severity` (both
        recorded only for `RECLASSIFY`, and left unset otherwise), the
        reviewer-supplied `rationale`, and the `decided_at` logical-clock
        instant."

        Design: Difficulty/non_linear_state_machine/event_reclassify_reopen_cycle
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        review_event(
            event["id"], "RECLASSIFY",
            rationale="actually a following-distance event, and worse",
            new_event_type="FOLLOWING_DISTANCE", new_severity="HIGH",
        )
        review_event(event["id"], "REOPEN", rationale="second look after driver statement")
        confirmed = review_event(event["id"], "CONFIRM", rationale="confirmed after reopen")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["event_type"] == "FOLLOWING_DISTANCE"
        assert confirmed["severity"] == "HIGH"
        assert confirmed["review_count"] == 3
        resp = api.list_event_review_decisions(event["id"], MANAGER)
        rows, meta = validate_paginated(resp)
        assert len(rows) == 3
        assert [r["action"] for r in rows] == ["RECLASSIFY", "REOPEN", "CONFIRM"]
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_final"]) == 85.00
        assert driver["confirmed_events_90d"] == 1

    def test_event_reclassify_then_reopen_restores_in_review_state(self, api):
        """PRD §3.4: "A `RECLASSIFIED` or `DISMISSED` event may be returned to
        `IN_REVIEW` by the reopen action; reopening a reclassified event
        leaves `confirmed_at` unset as it was."

        Design: Difficulty/non_linear_state_machine/event_reclassify_reopen_cycle
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        reclassified = review_event(
            event["id"], "RECLASSIFY", rationale="wrong type",
            new_event_type="FOLLOWING_DISTANCE",
        )
        assert reclassified["status"] == "RECLASSIFIED"
        assert reclassified["event_type"] == "FOLLOWING_DISTANCE"
        reopened = review_event(event["id"], "REOPEN", rationale="requeue")
        assert reopened["status"] == "IN_REVIEW"
        assert reopened.get("confirmed_at") in (None,)
        assert reopened["review_count"] == 2

    def test_review_decisions_append_only_no_mutation(self, api):
        """PRD §2.4: "Review decisions are the deliberate exception: as an
        append-only audit record, a `ReviewDecision` carries only `id` and
        `created_at` among the common fields; both `updated_at` and `version`
        are absent from it entirely."
        PRD §3.4: "The log records, for every action, the acting manager's
        identifier as `reviewer_id`, the `action` (`CONFIRM`, `DISMISS`,
        `RECLASSIFY`, or `REOPEN`), the event's `prior_event_type` and
        `prior_severity`, the `new_event_type` and `new_severity` (both
        recorded only for `RECLASSIFY`, and left unset otherwise), the
        reviewer-supplied `rationale`, and the `decided_at` logical-clock
        instant."

        Design: Corner/entities/review_decisions_append_only_no_mutation
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        review_event(
            event["id"], "RECLASSIFY", rationale="wrong type",
            new_event_type="FOLLOWING_DISTANCE",
        )
        review_event(event["id"], "REOPEN", rationale="requeue")
        rows, meta = validate_paginated(api.list_event_review_decisions(event["id"], MANAGER))
        assert len(rows) == 2
        for row in rows:
            assert_review_decision(row)
        first, second = rows
        assert first["action"] == "RECLASSIFY"
        assert first["prior_event_type"] == "HARSH_BRAKE"
        assert first["new_event_type"] == "FOLLOWING_DISTANCE"
        assert first["reviewer_id"] == "sm-1"
        assert second["action"] == "REOPEN"
        assert second["new_event_type"] is None
        assert second["reviewer_id"] == "sm-1"


class TestReviewStateMachine:
    def test_review_confirm_from_detected_rejected(self, api, safety_manager_headers):
        """PRD §3.4: "An event becomes reviewable when its evidence arrives:
        the first footage clip of the event to complete upload transitions the
        event from `DETECTED` to `IN_REVIEW` automatically, bumps the event's
        `version`, and brings the event into the provisional scoring input set
        described in Section 3.9."
        PRD §3.4: "Confirming an event from `IN_REVIEW` to `CONFIRMED` is the
        most consequential action in the system."

        Design: Corner/state_machines/review_confirm_from_detected_rejected
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        resp = api.review_safety_event(
            event["id"],
            {
                "action": "CONFIRM",
                "rationale": "too early",
                "expected_event_version": event["version"],
            },
            safety_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_event(event["id"])
        assert after["status"] == "DETECTED"
        assert after["review_count"] == 0

    def test_dismiss_then_reopen_returns_to_in_review(self, api):
        """PRD §3.4: "Dismissing an event moves it from `IN_REVIEW` to
        `DISMISSED` and removes it from the provisional scoring input set. ...
        A `RECLASSIFIED` or `DISMISSED` event may be returned to `IN_REVIEW`
        by the reopen action."
        PRD §3.9: "The two variants differ only in their input sets:
        `safety_score_provisional` includes events in `IN_REVIEW`,
        `CONFIRMED`, and `RECLASSIFIED`, serving the live operational view,
        the review queue, and projected incentive pricing;
        `safety_score_final` includes only `CONFIRMED` events."

        Design: Corner/state_machines/dismiss_then_reopen_returns_to_in_review
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        review_event(event["id"], "DISMISS", rationale="not actionable")
        reopened = review_event(event["id"], "REOPEN", rationale="driver appealed")
        assert reopened["status"] == "IN_REVIEW"
        assert reopened["review_count"] == 2
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_provisional"]) == 92.50
        assert float(driver["safety_score_final"]) == 100.00


class TestOptimisticConcurrency:
    def test_review_stale_event_version_returns_412(self, api, safety_manager_headers):
        """PRD §2.6: "A review action on a safety event must carry
        `expected_event_version` equal to the event's current `version`. If
        the event's version has advanced since the client last read it —
        whether through a prior review action or through the automatic
        transition into review triggered by the first uploaded clip — the
        request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), and no
        review decision is recorded."

        Design: Corner/cross-cutting complexity layers/review_stale_event_version_returns_412
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        current = get_event(event["id"])
        dismissed = validate_success(
            api.review_safety_event(
                event["id"],
                {
                    "action": "DISMISS",
                    "rationale": "first pass",
                    "expected_event_version": current["version"],
                },
                safety_manager_headers,
            ),
            200,
        )
        stale_resp = api.review_safety_event(
            event["id"],
            {
                "action": "REOPEN",
                "rationale": "stale view",
                "expected_event_version": current["version"],
            },
            safety_manager_headers,
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_EVENT_VERSION)
        after_stale = get_event(event["id"])
        assert after_stale["status"] == "DISMISSED"
        assert after_stale["review_count"] == 1
        fresh = validate_success(
            api.review_safety_event(
                event["id"],
                {
                    "action": "REOPEN",
                    "rationale": "fresh view",
                    "expected_event_version": dismissed["version"],
                },
                safety_manager_headers,
            ),
            200,
        )
        assert fresh["status"] == "IN_REVIEW"
        assert fresh["review_count"] == 2


class TestImmediateConsistency:
    def test_immediate_visibility_in_same_response(self, api, safety_manager_headers):
        """PRD §4: "Endpoints that create a new resource return HTTP 201 with
        the created resource; endpoints that modify an existing resource or
        perform a read return HTTP 200 with the affected resource (or resource
        list)."
        PRD §3.9: "Both variants are computed on read and recomputed after
        every review action, every exoneration decision, and every clock
        movement observed via maintenance."

        Design: Corner/consistency model/immediate_visibility_in_same_response
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        current = get_event(event["id"])
        confirmed = validate_success(
            api.review_safety_event(
                event["id"],
                {
                    "action": "CONFIRM",
                    "rationale": "immediate check",
                    "expected_event_version": current["version"],
                },
                safety_manager_headers,
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["review_count"] == 1
        assert confirmed["version"] == current["version"] + 1
        reread = get_event(event["id"])
        assert reread["status"] == "CONFIRMED"
        assert reread["review_count"] == 1
        assert reread["version"] == confirmed["version"]
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_final"]) == 92.50


class TestReviewQueuePagination:
    def test_events_list_paginates_total_count_has_more(self, api, safety_manager_headers, telematics_ingest_headers):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`. `limit` defaults to 10, must be at least 1, and may not
        exceed 100; `offset` defaults to 0. List responses report `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` envelope."
        PRD §3.3: "The queue may be filtered by `status`, `event_type`,
        `driver_id`, or `vehicle_id`."

        Design: Corner/entities/events_list_paginates_total_count_has_more
        """
        base = setup_base()
        for severity, occurred in (
            ("LOW", "2026-08-28T00:00:00Z"),
            ("MEDIUM", "2026-08-29T00:00:00Z"),
            ("HIGH", "2026-08-30T00:00:00Z"),
        ):
            ingest_event(
                base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                event_type="HARSH_BRAKE", severity=severity, occurred_at=occurred,
            )
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(
                base["fleet"]["id"], safety_manager_headers,
                params={"limit": 2, "offset": 0},
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(
                base["fleet"]["id"], safety_manager_headers,
                params={"limit": 2, "offset": 2},
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(base["fleet"]["id"], safety_manager_headers)
        )
        assert len(rows) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(
                base["fleet"]["id"], safety_manager_headers,
                params={"status": "DETECTED"},
            )
        )
        assert len(rows) == 3
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(
                base["fleet"]["id"], safety_manager_headers,
                params={"status": "CONFIRMED"},
            )
        )
        assert len(rows) == 0


class TestFutureEventIngest:
    def test_future_event_ingest_rejected(self, api, telematics_ingest_headers, safety_manager_headers):
        """PRD §3.3: "the `occurred_at` instant, which must not lie after the
        logical clock (a future timestamp is rejected with
        `ERR_EVENT_IN_FUTURE`)."

        Design: Corner/validations/future_event_ingest_rejected
        """
        base = setup_base()
        resp = api.create_safety_event(
            create_safety_event_payload(
                base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                event_type="HARSH_BRAKE", severity="LOW",
                occurred_at="2026-09-01T00:00:01Z",
            ),
            telematics_ingest_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_IN_FUTURE)
        ok = validate_success(
            api.create_safety_event(
                create_safety_event_payload(
                    base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                    event_type="HARSH_BRAKE", severity="LOW",
                    occurred_at="2026-09-01T00:00:00Z",
                ),
                telematics_ingest_headers,
            ),
            201,
        )
        assert_safety_event(ok)
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(base["fleet"]["id"], safety_manager_headers)
        )
        assert len(rows) == 1
