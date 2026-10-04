"""Performance ingestion: computed fields, referential guards, temporal windows."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_publisher_headers,
    make_songwriter_headers,
    make_finance_officer_headers,
    validate_error,
    validate_success,
    create_performance_payload,
    create_licensee_payload,
    create_adjustment_payload,
    create_audit_payload,
    create_publisher_affiliate,
    create_confirmed_work,
    setup_performance_ready,
    setup_with_performance,
    setup_distributed_cycle,
    _create_work,
    _create_claim,
    _confirm_work,
    _create_licensee,
    _issue_license,
    _ingest_performance,
    _create_cycle,
    _close_collection,
    _list_cycle_statements,
)

REGISTRAR = TEST_USERS["pro_registrar_headers"]
LIC_ADMIN = TEST_USERS["pro_licensing_admin_headers"]
DISTRIBUTOR = TEST_USERS["royalty_distributor_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
SYSADMIN = TEST_USERS["pro_system_admin_headers"]


class TestDifficultySampledVsCensus:
    def test_sample_expands_and_census_reports_raw_for_identical_play_count(self, api):
        """PRD §3.7: "For the census sources — MONITORING, CUE_SHEET, and
        DIGITAL_REPORT — the universe equals the reported play_count exactly. For a
        SAMPLE row, the system expands the sample to a universe estimate: the reported
        count is multiplied by 52 (the number of sampling frame units in a full frame)
        divided by frame_units_reported, rounded to the nearest integer with
        round-half-up, and the result is floored at the reported play_count itself so a
        projection never falls below what was actually observed."

        Design: Difficulty/dual_variant_calc/sampled_vs_census_play_estimation
        """
        ctx = setup_performance_ready()
        sample = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-03-10", source="SAMPLE",
                    play_count=7, frame_units_reported=13,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        # round_half_up(7 * 52 / 13) = 28
        assert sample["universe_estimated_plays"] == 28

        census = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-03-11", source="MONITORING", play_count=7,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        assert census["universe_estimated_plays"] == 7
        assert sample["universe_estimated_plays"] != census["universe_estimated_plays"]

    def test_sample_expansion_scales_credit_units(self, api):
        """PRD §3.7: "The final credit_units is the base times the
        universe_estimated_plays, rounded half-up to four decimal places, and that
        per-event rounded value is what cycle-level summations later add together."
        PRD §3.7: "For the census sources — MONITORING, CUE_SHEET, and DIGITAL_REPORT —
        the universe equals the reported play_count exactly. For a SAMPLE row, the
        system expands the sample to a universe estimate: the reported count is
        multiplied by 52 (the number of sampling frame units in a full frame) divided by
        frame_units_reported, rounded to the nearest integer with round-half-up".

        Design: Difficulty/dual_variant_calc/sampled_vs_census_play_estimation
        """
        ctx = setup_performance_ready()
        sample = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-03-10", source="SAMPLE",
                    play_count=7, frame_units_reported=13,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        census = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-03-11", source="MONITORING", play_count=7,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        # TERRESTRIAL_RADIO (1.0) * DAY (1.0) * universe; one writer-claim count 0 (only
        # a publisher claim) so no feature bonus.
        assert sample["credit_units"] == pytest.approx(28.0, abs=1e-9)
        assert census["credit_units"] == pytest.approx(7.0, abs=1e-9)


class TestCornerComputedPerformanceFields:
    def test_census_network_tv_prime_credit_units(self, api):
        """PRD §3.7: "For the census sources — MONITORING, CUE_SHEET, and
        DIGITAL_REPORT — the universe equals the reported play_count exactly."
        PRD §3.7: "Each medium carries a factor — 1.0 for TERRESTRIAL_RADIO, 2.5 for
        NETWORK_TV, 1.5 for CABLE_TV, 0.6 for DIGITAL_STREAMING, and 1.2 for LIVE_VENUE
        — and each daypart carries its own: 2.0 for PRIME, 1.0 for DAY, 0.7 for
        LATE_NIGHT, and 0.4 for OVERNIGHT."

        Design: Corner/entities/performance_event_computed_fields_ignore_input
        """
        ctx = setup_performance_ready()
        event = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-03-01", medium="NETWORK_TV", daypart="PRIME",
                    source="MONITORING", play_count=100,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        assert event["universe_estimated_plays"] == 100
        # 2.5 * 2.0 * 100; the work has zero ACCEPTED writer claims -> no feature bonus
        assert event["credit_units"] == pytest.approx(500.0, abs=1e-9)

    def test_feature_bonus_applies_with_three_writer_claims(self, api):
        """PRD §3.7: "A feature bonus then recognizes densely-written works: when the
        performed work has more than two ACCEPTED writer claims, the base is multiplied
        by 1.1 before being scaled by the universe."

        Design: Corner/entities/feature_bonus_applies_with_three_writer_claims
        """
        pub = create_publisher_affiliate(legal_name="FB Pub", affiliation_code="FBP")
        writers = [
            create_publisher_affiliate(
                legal_name=f"FB W{i}", affiliation_code=f"FBW{i}", party_type="SONGWRITER"
            )
            for i in (1, 2, 3)
        ]
        work = _create_work(pub["id"], title="FB Song")
        for w in writers:
            _create_claim(work["id"], w["id"], "WRITER", 2000)
        _create_claim(work["id"], pub["id"], "PUBLISHER", 4000)
        _confirm_work(work["id"])
        licensee = _create_licensee(legal_name="FB Net")
        license_ = _issue_license(licensee)
        event = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    work["id"], license_["id"],
                    performance_date="2026-03-01", medium="NETWORK_TV", daypart="PRIME",
                    source="MONITORING", play_count=100,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        # 2.5 * 2.0 * 1.1 * 100 with three ACCEPTED writer claims
        assert event["credit_units"] == pytest.approx(550.0, abs=1e-9)


class TestCornerSampledProjectionFloor:
    def test_projection_never_falls_below_observed_plays(self, api):
        """PRD §3.7: "For a SAMPLE row, the system expands the sample to a universe
        estimate: the reported count is multiplied by 52 (the number of sampling frame
        units in a full frame) divided by frame_units_reported, rounded to the nearest
        integer with round-half-up, and the result is floored at the reported play_count
        itself so a projection never falls below what was actually observed."

        Design: Corner/calculations/sampled_projection_floor_at_play_count
        """
        ctx = setup_performance_ready()
        event = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-03-01", medium="CABLE_TV", daypart="LATE_NIGHT",
                    source="SAMPLE", play_count=5, frame_units_reported=200,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        # round_half_up(5 * 52 / 200) = 1, floored up to the observed 5
        assert event["universe_estimated_plays"] == 5


class TestDifficultyWorkStatusGate:
    def test_ingest_rejected_until_work_confirmed(self, api):
        """PRD §3.7: "The referenced work must be CONFIRMED; ingestion against any
        other work status is rejected with ERR_WORK_NOT_CONFIRMED."

        Design: Difficulty/cross_entity_state_dependency/performance_ingest_gated_by_work_status
        """
        pub = create_publisher_affiliate(legal_name="Pub G", affiliation_code="PUBG")
        work = _create_work(pub["id"], title="Song G")
        _create_claim(work["id"], pub["id"], "PUBLISHER", 10000)
        licensee = _create_licensee(legal_name="Gate Radio")
        license_ = _issue_license(licensee)

        resp = api.ingest_performance(
            create_performance_payload(work["id"], license_["id"], play_count=10),
            DISTRIBUTOR,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_CONFIRMED)

        _confirm_work(work["id"])
        ok = validate_success(
            api.ingest_performance(
                create_performance_payload(work["id"], license_["id"], play_count=10),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        assert ok["status"] == "ACCEPTED"

    def test_ingest_against_in_conflict_work_rejected(self, api):
        """PRD §3.7: "The referenced work must be CONFIRMED; ingestion against any
        other work status is rejected with ERR_WORK_NOT_CONFIRMED."

        Design: Difficulty/cross_entity_state_dependency/performance_ingest_gated_by_work_status
        """
        pub_a = create_publisher_affiliate(legal_name="Pub GA", affiliation_code="PUBGA")
        pub_b = create_publisher_affiliate(legal_name="Pub GB", affiliation_code="PUBGB")
        work = _create_work(pub_a["id"], title="Song G2")
        _create_claim(work["id"], pub_a["id"], "PUBLISHER", 6000)
        _create_claim(work["id"], pub_b["id"], "PUBLISHER", 5000)  # over-claim
        assert validate_success(api.get_work(work["id"], REGISTRAR))["status"] == "IN_CONFLICT"
        licensee = _create_licensee(legal_name="Gate Radio 2")
        license_ = _issue_license(licensee)
        resp = api.ingest_performance(
            create_performance_payload(work["id"], license_["id"], play_count=10),
            DISTRIBUTOR,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_CONFIRMED)


class TestDifficultyLicenseWindow:
    def test_expiry_date_inclusive_and_one_day_after_rejected(self, api):
        """PRD §3.7: "The performance_date must fall within the referenced license's
        covered window from effective_date through expiry_date inclusive; a date outside
        the window is rejected with ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW."

        Design: Difficulty/resource_temporal_overlap/performance_outside_closed_license_window
        """
        # Move the logical clock inside the license window before any lazy expiry
        # evaluation (the boot clock is 2026-09-01, past the window's expiry_date).
        validate_success(api.set_clock({"to_iso8601": "2026-03-01T00:00:00Z"}, SYSADMIN))
        ctx = setup_performance_ready(
            license_overrides={"effective_date": "2026-01-01", "expiry_date": "2026-06-30"}
        )
        last_day = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-06-30", play_count=5,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        assert last_day["status"] == "ACCEPTED"

        resp = api.ingest_performance(
            create_performance_payload(
                ctx["work"]["id"], ctx["license"]["id"],
                performance_date="2026-07-01", play_count=5,
            ),
            DISTRIBUTOR,
        )
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW)

    def test_day_before_effective_date_rejected(self, api):
        """PRD §3.7: "The performance_date must fall within the referenced license's
        covered window from effective_date through expiry_date inclusive; a date outside
        the window is rejected with ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW."

        Design: Difficulty/resource_temporal_overlap/performance_outside_closed_license_window
        """
        # Move the logical clock inside the license window before any lazy expiry
        # evaluation (the boot clock is 2026-09-01, past the window's expiry_date).
        validate_success(api.set_clock({"to_iso8601": "2026-03-01T00:00:00Z"}, SYSADMIN))
        ctx = setup_performance_ready(
            license_overrides={"effective_date": "2026-02-01", "expiry_date": "2026-06-30"}
        )
        first_day = validate_success(
            api.ingest_performance(
                create_performance_payload(
                    ctx["work"]["id"], ctx["license"]["id"],
                    performance_date="2026-02-01", play_count=5,
                ),
                DISTRIBUTOR,
            ),
            expected_status=201,
        )
        assert first_day["status"] == "ACCEPTED"
        resp = api.ingest_performance(
            create_performance_payload(
                ctx["work"]["id"], ctx["license"]["id"],
                performance_date="2026-01-31", play_count=5,
            ),
            DISTRIBUTOR,
        )
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW)


class TestCornerBulkIngest:
    def test_bulk_partial_failure_persists_rejected_row(self, api):
        """PRD §3.7: "Bulk ingestion accepts a list of events, each carrying the same
        fields as a single ingest, and processes rows independently: valid rows are
        accepted with their computed fields, while rows failing validation are persisted
        directly in the terminal REJECTED status with the failing error's identifier
        recorded in rejection_error_id (for example ERR_WORK_NOT_CONFIRMED), never
        consuming credit."

        Design: Corner/endpoints/bulk_ingest_partial_failure_marks_rejected_rows
        """
        pub = create_publisher_affiliate(legal_name="BK Pub", affiliation_code="BKP")
        work_ok = _create_work(pub["id"], title="OK Song")
        work_bad = _create_work(pub["id"], title="Bad Song")
        _create_claim(work_ok["id"], pub["id"], "PUBLISHER", 10000)
        _create_claim(work_bad["id"], pub["id"], "PUBLISHER", 10000)
        _confirm_work(work_ok["id"])
        licensee = _create_licensee(legal_name="BK Net")
        license_ = _issue_license(licensee)

        resp = api.ingest_performances_bulk(
            {
                "events": [
                    create_performance_payload(work_ok["id"], license_["id"], play_count=10),
                    create_performance_payload(work_bad["id"], license_["id"], play_count=10),
                ]
            },
            DISTRIBUTOR,
        )
        data = validate_success(resp)
        assert len(data) == 2
        by_work = {row["work_id"]: row for row in data}
        ok_row = by_work[work_ok["id"]]
        bad_row = by_work[work_bad["id"]]
        assert ok_row["status"] == "ACCEPTED"
        # TERRESTRIAL_RADIO (1.0) * DAY (1.0) * 10 plays
        assert ok_row["credit_units"] == pytest.approx(10.0, abs=1e-9)
        assert bad_row["status"] == "REJECTED"
        assert bad_row["rejection_error_id"] == "ERR_WORK_NOT_CONFIRMED"


class TestCornerPlayCountValidation:
    def test_play_count_zero_rejected(self, api):
        """PRD §2.5: "Field-shape problems — an invalid enum member, a malformed ISO
        date, an effective_date that is not strictly earlier than the expiry_date, a
        period_start later than the period_end, a play_count below 1, a negative
        disputed_fee_cents — are rejected with ERR_VALIDATION."

        Design: Corner/validations/play_count_zero_rejected
        """
        ctx = setup_performance_ready()
        resp = api.ingest_performance(
            create_performance_payload(
                ctx["work"]["id"], ctx["license"]["id"], play_count=0
            ),
            DISTRIBUTOR,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestCornerPerformanceVoidLocked:
    def test_void_after_cycle_calculating_rejected(self, api):
        """PRD §3.7: "A distributor may void an ACCEPTED event while it is still free
        (cycle_id null) or while the cycle holding it is still COLLECTING; a voided
        event moves to VOIDED".
        PRD §2.5: "State checks come after existence: an operation that the target's
        current state does not permit is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/performance_void_after_cycle_calculating_rejected
        """
        ctx = setup_with_performance()
        cycle = _create_cycle(label="VD1")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [ctx["event"]["id"]]}, DISTRIBUTOR
            )
        )
        _close_collection(cycle["id"])
        resp = api.void_performance(ctx["event"]["id"], DISTRIBUTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCornerSuspendedLicenseIngest:
    def test_performance_under_suspended_license_rejected(self, api):
        """PRD §3.7: "The referenced license must be ACTIVE or DISPUTED — performances
        continue to accrue during a good-faith dispute — while SUSPENDED, EXPIRED, or
        TERMINATED licenses reject ingestion with ERR_LICENSE_SUSPENDED."
        PRD §3.5: "while suspended, new performance ingestion under the license is
        rejected with ERR_LICENSE_SUSPENDED."

        Design: Corner/errors/performance_under_suspended_license_rejected
        """
        ctx = setup_distributed_cycle()
        licensee = ctx["licensee"]
        license_ = ctx["license"]
        stmt = ctx["statements"][0]

        # Audit with findings strictly above the 1,000,000-cent threshold.
        audit = validate_success(
            api.create_audit(
                licensee["id"],
                create_audit_payload(),
                FINANCE,
            ),
            expected_status=201,
        )
        validate_success(api.file_findings(audit["id"], {"findings_delta_cents": 2000000}, FINANCE))
        # The audit-close gate needs a non-REJECTED AUDIT_FINDING adjustment.
        validate_success(
            api.create_adjustment(
                stmt["id"],
                create_adjustment_payload(
                    delta_cents=2000000, reason="AUDIT_FINDING", audit_id=audit["id"]
                ),
                make_finance_officer_headers("fin-9"),
            ),
            expected_status=201,
        )
        validate_success(api.close_audit(audit["id"], FINANCE))
        licensee_after = validate_success(api.get_licensee(licensee["id"], LIC_ADMIN))
        assert licensee_after["credit_standing"] == "DELINQUENT"

        validate_success(api.suspend_license(license_["id"], LIC_ADMIN))
        resp = api.ingest_performance(
            create_performance_payload(
                ctx["work"]["id"], license_["id"], performance_date="2026-03-01", play_count=10
            ),
            DISTRIBUTOR,
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_SUSPENDED)
