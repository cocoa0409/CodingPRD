"""Dual-variant calculations: station-throughput projection (optimistic vs
pessimistic) and host cost share (provisional uncapped vs final capped)."""

from test_helpers import (
    TEST_USERS,
    confirm_agreement,
    create_agreement,
    create_event,
    create_station,
    create_unpacked_sterilizer_manifest,
    create_vetted_site,
    get_success_data,
    run_completed_cycle,
    setup_station,
    submit_agreement,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
SL = TEST_USERS["station_lead_headers"]
ST = TEST_USERS["sterilization_tech_headers"]


class TestStationThroughputOptimisticVsPessimistic:
    def test_pessimistic_projection_counts_degraded_at_half_capacity(self, api):
        """PRD §3.7: "Each contributing station's effective chair count is its
        full `chair_count` when `OPERATIONAL`, or half its `chair_count` rounded
        down when `DEGRADED`." and "the projection considers the event's
        stations of the matching type whose status is `OPERATIONAL` or
        `DEGRADED` — stations in any other status are excluded entirely."

        Design: Difficulty/dual_variant_calc/station_throughput_optimistic_vs_pessimistic_projection
        """
        site = create_vetted_site(
            site_type="ARENA",
            state_code="TN",
            square_footage=40000,
            has_loading_dock=True,
            sterilization_capable=True,
        )
        event = create_event(
            host_state_code="TN",
            service_date="2026-10-03",
            doors_open_utc="2026-10-03T10:00:00Z",
            total_patient_capacity=500,
        )
        agreement = create_agreement(
            {"id": event["id"], "version": event["version"]},
            site["id"],
            liability_cap_cents=90_000_000,
        )
        submit_agreement(event["id"], agreement["id"])
        confirm_agreement(event["id"], agreement["id"])
        create_unpacked_sterilizer_manifest(
            event["id"], requires_loading_dock=True
        )
        station_payload = {
            "station_type": "DENTAL",
            "chair_count": 3,
            "minutes_per_patient": 30,
            "requires_sterilization": True,
            "service_window_open_utc": "2026-10-03T11:00:00Z",
            "service_window_close_utc": "2026-10-03T19:00:00Z",
        }
        st1 = create_station(event["id"], station_label="DENTAL-01", **station_payload)
        st2 = create_station(event["id"], station_label="DENTAL-02", **station_payload)
        get_success_data(api.mark_station_set_up(event["id"], st1["id"], LC))
        get_success_data(api.mark_station_set_up(event["id"], st2["id"], LC))
        run_completed_cycle(event["id"], batch_size=2)
        get_success_data(api.mark_station_operational(event["id"], st1["id"], SL))
        get_success_data(api.mark_station_operational(event["id"], st2["id"], SL))

        # Exclude st1 entirely, then push the backlog strictly above 6 so
        # st2 degrades alone.
        get_success_data(api.take_station_offline(event["id"], st1["id"], SL))
        get_success_data(
            api.start_sterilization_cycle(
                event["id"], {"instrument_batch_size": 7}, ST
            )
        )

        stations, _ = validate_paginated(api.list_event_stations(event["id"], SL))
        by_id = {s["id"]: s for s in stations}
        assert by_id[st2["id"]]["status"] == "DEGRADED"
        assert by_id[st1["id"]]["status"] == "OFFLINE"

        event_now = validate_success(api.get_event(event["id"], ED))
        # Pessimistic persisted variant: floor(floor(3/2) * 480 / 30) = 16.
        # The optimistic variant would give 48 for the same station.
        assert event_now["projected_servable_patients"] == 16

    def test_degraded_station_at_full_chairs_only_inside_ready_gate_variant(
        self, api
    ):
        """PRD §3.7: "when this projection is used inside the posture recompute
        that gates `READY`, `DEGRADED` stations are counted at their full
        `chair_count` rather than half, producing an optimistic figure that is
        strictly larger whenever a degraded station has an odd chair count."
        The persisted `projected_servable_patients` figure keeps the base
        (half-capacity) form even after a DEGRADED->OPERATIONAL recovery.

        Design: Difficulty/dual_variant_calc/station_throughput_optimistic_vs_pessimistic_projection
        """
        site = create_vetted_site(
            site_type="ARENA",
            state_code="TN",
            square_footage=40000,
            has_loading_dock=True,
            sterilization_capable=True,
        )
        event = create_event(
            host_state_code="TN",
            service_date="2026-10-03",
            doors_open_utc="2026-10-03T10:00:00Z",
            total_patient_capacity=500,
        )
        agreement = create_agreement(
            {"id": event["id"], "version": event["version"]},
            site["id"],
            liability_cap_cents=90_000_000,
        )
        submit_agreement(event["id"], agreement["id"])
        confirm_agreement(event["id"], agreement["id"])
        create_unpacked_sterilizer_manifest(event["id"])
        station = setup_station(
            event["id"],
            station_type="DENTAL",
            chair_count=3,
            minutes_per_patient=30,
            requires_sterilization=True,
            service_window_open_utc="2026-10-03T11:00:00Z",
            service_window_close_utc="2026-10-03T19:00:00Z",
        )
        run_completed_cycle(event["id"], batch_size=2)
        get_success_data(api.mark_station_operational(event["id"], station["id"], SL))

        event_op = validate_success(api.get_event(event["id"], ED))
        # OPERATIONAL 3 chairs * 480 min / 30 min = 48 (full count).
        assert event_op["projected_servable_patients"] == 48

        # Backlog 7 > 6 degrades the station; the persisted figure halves.
        cycle = get_success_data(
            api.start_sterilization_cycle(
                event["id"], {"instrument_batch_size": 7}, ST
            )
        )
        event_degraded = validate_success(api.get_event(event["id"], ED))
        assert event_degraded["projected_servable_patients"] == 16

        # Completing the cycle restores OPERATIONAL and the full projection.
        get_success_data(api.complete_cycle(event["id"], cycle["id"], ST))
        event_back = validate_success(api.get_event(event["id"], ED))
        assert event_back["projected_servable_patients"] == 48


class TestHostCostShareProvisionalVsFinal:
    def test_provisional_uncapped_then_final_capped_at_confirm(self, api):
        """PRD §3.2: "On creation, the server computes a provisional
        `cost_share_cents` for display purposes using the uncapped variant of
        the cost-share formula" and "the persisted `cost_share_cents` is the
        raw share truncated at the host's `liability_cap_cents` — the cap
        always applies last."

        Design: Difficulty/dual_variant_calc/host_cost_share_provisional_uncapped_vs_final_capped
        """
        site = create_vetted_site(
            site_type="ARENA",
            state_code="KY",
            square_footage=35000,
            has_loading_dock=True,
            sterilization_capable=True,
        )
        event = create_event(
            host_state_code="KY",
            service_date="2026-11-07",
            doors_open_utc="2026-11-07T10:00:00Z",
            total_patient_capacity=400,
        )
        agreement = create_agreement(
            {"id": event["id"], "version": event["version"]},
            site["id"],
            host_org_name="Arena Board",
            liability_cap_cents=900_000,
            insurance_certificate_ref="CERT-2",
        )
        # Uncapped provisional: 800000 base + 800000 * (0.15*1 + 0.25*1)
        # = 800000 + 320000 = 1120000.
        assert agreement["cost_share_cents"] == 1_120_000

        submit_agreement(event["id"], agreement["id"])
        confirmed = confirm_agreement(event["id"], agreement["id"])
        # Final capped: min(1120000, 900000) = 900000.
        assert confirmed["cost_share_cents"] == 900_000

        event_now = validate_success(api.get_event(event["id"], ED))
        assert event_now["posture"] == "SITE_LOCKED"

    def test_cap_not_binding_persists_raw_share(self, api):
        """PRD §3.2: "The provisional value shown at draft time skips that
        truncation, so the provisional figure is always greater than or equal
        to the final confirmed figure." With a cap above the raw share the
        provisional and final figures are equal.

        Design: Difficulty/dual_variant_calc/host_cost_share_provisional_uncapped_vs_final_capped
        """
        site = create_vetted_site(
            site_type="SCHOOL", state_code="TN", square_footage=9000
        )
        event = create_event(
            host_state_code="TN",
            service_date="2026-11-07",
            doors_open_utc="2026-11-07T10:00:00Z",
            total_patient_capacity=100,
        )
        agreement = create_agreement(
            {"id": event["id"], "version": event["version"]},
            site["id"],
            liability_cap_cents=3_000_000,
        )
        # SCHOOL base 300000, no surcharge below 10000 sqft, cap not binding.
        assert agreement["cost_share_cents"] == 300_000
        submit_agreement(event["id"], agreement["id"])
        confirmed = confirm_agreement(event["id"], agreement["id"])
        assert confirmed["cost_share_cents"] == 300_000
