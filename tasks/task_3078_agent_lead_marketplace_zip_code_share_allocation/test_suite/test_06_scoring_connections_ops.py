"""Performance scoring variants, live connections, call recordings, and ops-run
snapshots (PRD §3.7, §3.8, §3.11)."""
from test_helpers import (
    create_agent,
    create_routed_lead,
    get_agent,
    get_lead,
    get_success_data,
    make_agent_headers,
    set_clock,
    setup_assigned_lead,
    setup_market_with_active_order,
    validate_paginated,
    validate_success,
)


def _start_bridging_connection(api, lead, agent):
    conn = get_success_data(
        api.create_live_connection(
            {"lead_id": lead["id"], "consumer_key": lead["consumer_key"],
             "listing_agent_id": lead["listing_agent_id"]},
            make_agent_headers(agent["id"]),
        )
    )
    return conn


class TestRollingVsOfficialWindow:
    def test_rolling_survives_empty_second_window_while_official_resets(self, api, marketplace_ops_headers):
        """PRD §3.7: "The rolling variant uses all-time counters; the official variant is
        computed only at ops-run time and considers events inside the window from the
        previous run's `run_at` (exclusive) up to and including this run's `run_at`. The
        official variant drives the agent's `performance_tier`; the rolling variant is
        the live value used for selector tie-breaks and tier display."

        Design: Difficulty/dual_variant_calc/agent_score_rolling_vs_official_window
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="89101", state_code="NV", consumer_key="c-roll@x.com"
        )
        set_clock("2026-09-01T00:01:00Z")
        run1 = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        mid = get_agent(agent["id"])
        assert mid["rolling_score"] == 65
        assert mid["official_score"] == 65
        assert mid["performance_tier"] == "STANDARD"
        snaps1, _ = validate_paginated(
            api.list_performance_snapshots(
                marketplace_ops_headers, params={"agent_id": agent["id"], "ops_run_seq": run1["seq"]}
            )
        )
        assert len(snaps1) == 1
        assert snaps1[0]["windowed_score"] == 65, "the accept fell inside the first window"
        # Second run with no new events: the windowed (official) score covers nothing.
        set_clock("2026-09-01T00:02:00Z")
        run2 = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        snaps2, _ = validate_paginated(
            api.list_performance_snapshots(
                marketplace_ops_headers, params={"agent_id": agent["id"], "ops_run_seq": run2["seq"]}
            )
        )
        assert len(snaps2) == 1
        assert snaps2[0]["windowed_score"] == 0, "no events inside the second window"
        final = get_agent(agent["id"])
        assert final["official_score"] == 0
        assert final["rolling_score"] == 65, "rolling is all-time and must not reset"

    def test_first_official_snapshot_matches_rolling_for_single_event(self, api, marketplace_ops_headers):
        """PRD §3.7: "the official variant is computed only at ops-run time and considers
        events inside the window from the previous run's `run_at` (exclusive) up to and
        including this run's `run_at`."
        PRD §3.7: "The weighted sum is rounded half-up to an integer in the range 0 to 100."

        Design: Difficulty/dual_variant_calc/agent_score_rolling_vs_official_window
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="89102", state_code="NV", consumer_key="c-roll2@x.com"
        )
        run1 = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        snaps, _ = validate_paginated(
            api.list_performance_snapshots(
                marketplace_ops_headers, params={"agent_id": agent["id"], "ops_run_seq": run1["seq"]}
            )
        )
        assert snaps[0]["windowed_score"] == 65
        assert snaps[0]["ops_run_seq"] == run1["seq"]


class TestScoreInputSet:
    def test_agent_with_zero_offers_is_unrated_not_low(self, api, marketplace_ops_headers):
        """PRD §3.7: "When an agent has received no offers at all (`offers_received` is
        zero) the score is reported as 0 and the agent's `performance_tier` is `UNRATED`."

        Design: Corner/calculations/score_input_set_excludes_unrated
        """
        set_clock()
        market, _, agent, _ = setup_market_with_active_order(
            zip_code="97213", state_code="OR", share_bps=6000
        )
        fresh = get_agent(agent["id"])
        assert fresh["rolling_score"] == 0
        assert fresh["performance_tier"] == "UNRATED"

    def test_zero_offer_agent_stays_unrated_after_ops_run(self, api, marketplace_ops_headers):
        """PRD §3.7: "When an agent has received no offers at all (`offers_received` is
        zero) the score is reported as 0 and the agent's `performance_tier` is `UNRATED`."

        Design: Corner/calculations/score_input_set_excludes_unrated
        """
        set_clock()
        market, _, agent, _ = setup_market_with_active_order(
            zip_code="97233", state_code="OR", share_bps=1000
        )
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        fresh = get_agent(agent["id"])
        assert fresh["offers_received"] == 0
        assert fresh["official_score"] == 0
        assert fresh["performance_tier"] == "UNRATED"


class TestNoAnswerSideEffects:
    def test_no_answer_increments_connections_missed_and_stores_no_recording(self, api, marketplace_ops_headers):
        """PRD §3.8: "When `duration_seconds` is zero the bridge reports no answer: the
        connection moves to `NO_ANSWER`, no recording is created, the agent's
        `connections_missed` increments by one, and their `rolling_score` is recomputed."

        Design: Corner/state_machines/connection_no_answer_side_effects
        """
        set_clock()
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97211", state_code="OR", consumer_key="c-t1@x.com"
        )
        conn = _start_bridging_connection(api, lead, agent)
        assert conn["connection_status"] == "BRIDGING"
        get_success_data(
            api.record_live_connection(
                conn["id"], {"duration_seconds": 0, "consent_given": True},
                make_agent_headers(agent["id"]),
            )
        )
        conn_after = get_success_data(api.get_live_connection(conn["id"], marketplace_ops_headers))
        assert conn_after["connection_status"] == "NO_ANSWER"
        agent_after = get_agent(agent["id"])
        assert agent_after["connections_missed"] == 1
        recordings, _ = validate_paginated(
            api.list_connection_recordings(conn["id"], marketplace_ops_headers)
        )
        assert len(recordings) == 0

    def test_no_answer_does_not_move_lead_out_of_assigned(self, api, marketplace_ops_headers):
        """PRD §3.8: "When `duration_seconds` is zero the bridge reports no answer: the
        connection moves to `NO_ANSWER`, no recording is created, the agent's
        `connections_missed` increments by one, and their `rolling_score` is recomputed."

        Design: Corner/state_machines/connection_no_answer_side_effects
        """
        set_clock()
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97212", state_code="OR", consumer_key="c-t2@x.com"
        )
        conn = _start_bridging_connection(api, lead, agent)
        get_success_data(
            api.record_live_connection(
                conn["id"], {"duration_seconds": 0, "consent_given": True},
                make_agent_headers(agent["id"]),
            )
        )
        assert get_agent(agent["id"])["rolling_score"] == 45, (
            "65 base minus the 20-point connection component"
        )


class TestRecordingRetention:
    def test_recording_purged_only_after_retention_expires(self, api, marketplace_ops_headers):
        """PRD §3.8: "any recording whose `recording_status` is still `STORED` and whose
        `recording_retention_expires_at` is in the past moves to `PURGED`. Purging
        deletes the audio data but retains the recording's metadata for audit."
        PRD §3.8: "the connection's `recording_retention_expires_at` is set to now plus
        90 days".

        Design: Corner/calculations/recording_purged_after_retention
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97215", state_code="OR", consumer_key="c-t1@x.com"
        )
        conn = _start_bridging_connection(api, lead, agent)
        recording = get_success_data(
            api.record_live_connection(
                conn["id"], {"duration_seconds": 120, "consent_given": True},
                make_agent_headers(agent["id"]),
            )
        )
        assert recording["recording_status"] == "STORED"
        # At exactly the retention boundary the recording survives (exclusive bound).
        set_clock("2026-11-30T00:00:00Z")
        sweep_at = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        assert sweep_at["sweep_counts"]["purged_recordings"] == 0
        recordings, _ = validate_paginated(
            api.list_connection_recordings(conn["id"], marketplace_ops_headers)
        )
        assert recordings[0]["recording_status"] == "STORED"
        # One second past the boundary the sweep purges it.
        set_clock("2026-11-30T00:00:01Z")
        sweep_after = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        assert sweep_after["sweep_counts"]["purged_recordings"] == 1
        recordings, _ = validate_paginated(
            api.list_connection_recordings(conn["id"], marketplace_ops_headers)
        )
        assert recordings[0]["recording_status"] == "PURGED"

    def test_completed_bridge_creates_stored_recording(self, api, marketplace_ops_headers):
        """PRD §3.8: "When `consent_given` is true and `duration_seconds` is at least 1,
        the bridge succeeds: a `CallRecording` is created in `STORED` status attached to
        the connection via `live_connection_id`, the connection's
        `recording_retention_expires_at` is set to now plus 90 days, the connection moves
        to `COMPLETED`, and the lead moves to `LIVE_CONNECTED`."

        Design: Corner/calculations/recording_purged_after_retention
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97216", state_code="OR", consumer_key="c-t9@x.com"
        )
        conn = _start_bridging_connection(api, lead, agent)
        recording = get_success_data(
            api.record_live_connection(
                conn["id"], {"duration_seconds": 60, "consent_given": True},
                make_agent_headers(agent["id"]),
            )
        )
        assert recording["recording_status"] == "STORED"
        conn_after = get_success_data(api.get_live_connection(conn["id"], marketplace_ops_headers))
        assert conn_after["connection_status"] == "COMPLETED"
        assert conn_after["recording_retention_expires_at"] is not None
        assert get_lead(lead["id"])["lead_status"] == "LIVE_CONNECTED"


class TestRatingReconciliation:
    def test_rating_updates_counters_and_recomputes_rolling_score(self, api, marketplace_ops_headers):
        """PRD §3.9: "Each accepted rating increments the agent's `rating_sum` by the
        score and `rating_count` by one, then recomputes `rolling_score`."
        PRD §3.7: "The rating component is the agent's average consumer rating —
        `rating_sum` divided by `rating_count` (zero denominator treated as one) —
        multiplied by 20 to put it on a 0-to-100 scale, weighted at 15 percent."

        Design: Corner/complexity_layers/rating_reconciles_derived_score
        """
        set_clock()
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97227", state_code="OR", consumer_key="c-t1@x.com"
        )
        validate_success(
            api.create_rating({"lead_id": lead["id"], "score": 4}, marketplace_ops_headers), 201
        )
        fresh = get_agent(agent["id"])
        assert fresh["rating_sum"] == 4
        assert fresh["rating_count"] == 1
        assert fresh["rolling_score"] == 77, "65 base + 0.15 * 4 * 20 = +12"

    def test_second_rating_reweights_average(self, api, marketplace_ops_headers):
        """PRD §3.9: "Each accepted rating increments the agent's `rating_sum` by the
        score and `rating_count` by one, then recomputes `rolling_score`."

        Design: Corner/complexity_layers/rating_reconciles_derived_score
        """
        set_clock()
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97230", state_code="OR", consumer_key="c-t5@x.com"
        )
        validate_success(
            api.create_rating({"lead_id": lead["id"], "score": 5}, marketplace_ops_headers), 201
        )
        validate_success(
            api.create_rating({"lead_id": lead["id"], "score": 1}, marketplace_ops_headers), 201
        )
        fresh = get_agent(agent["id"])
        assert fresh["rating_sum"] == 6
        assert fresh["rating_count"] == 2
        # avg 3.0 -> component 0.15 * 3 * 20 = 9 -> 25 + 20 + 20 + 9 = 74
        assert fresh["rolling_score"] == 74


class TestOpsRunEpoch:
    def test_empty_sweep_still_advances_seq_and_snapshots_agents(self, api, marketplace_ops_headers):
        """PRD §2.4: "Each `OpsRun` carries a monotonically increasing `seq` starting at
        1, the `run_at` instant from the logical clock, and a `sweep_counts` object
        reporting how many entities of each kind were touched".
        PRD §3.11: "Snapshot every `ACTIVE` agent into a `PerformanceSnapshot` with the
        official-variant score for the window between the previous run's `run_at` and
        this run's `run_at`."

        Design: Corner/complexity_layers/scheduled_ops_run_advances_epoch
        """
        set_clock()
        market, _, agent, _ = setup_market_with_active_order(
            zip_code="97228", state_code="OR", share_bps=6000
        )
        run1 = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        assert run1["seq"] == 1
        counts = run1["sweep_counts"]
        assert counts["expired_offers"] == 0
        assert counts["expired_orders"] == 0
        assert counts["purged_recordings"] == 0
        assert counts["snapshotted_agents"] == 1
        run2 = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        assert run2["seq"] == 2

    def test_ops_run_records_run_at_from_logical_clock(self, api, marketplace_ops_headers):
        """PRD §2.4: "Each `OpsRun` carries a monotonically increasing `seq` starting at
        1, the `run_at` instant from the logical clock".

        Design: Corner/complexity_layers/scheduled_ops_run_advances_epoch
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, _ = setup_market_with_active_order(
            zip_code="97231", state_code="OR", share_bps=1000
        )
        set_clock("2026-09-05T12:00:00Z")
        run = validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        assert run["run_at"].startswith("2026-09-05T12:00:00")
        assert run["sweep_counts"]["snapshotted_agents"] == 1
