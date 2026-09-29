"""Cross-cutting layers: the two optimistic-concurrency anchors, the staffing cascade
and the immediate consistency model."""
from test_helpers import (
    PROGRAM_ADMIN,
    ApiErrorId,
    acknowledgement_payload,
    api_client,
    assert_instant_equals,
    create_water_body,
    decon_order_payload,
    dispose_record,
    draft_detection_report,
    fetch_detection_report,
    fetch_record,
    fetch_station,
    fetch_water_body,
    fetch_watercraft,
    make_inspector_headers,
    make_state_data_steward_headers,
    move_inspector,
    open_record,
    order_decon,
    register_watercraft,
    screen_record,
    screening_payload,
    set_clock,
    setup_program,
    submit_detection_report,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
ARRIVAL = "2026-08-05T09:00:00Z"


def _record_screened_once():
    """A LOW CLEAN reservoir, one vessel, one record already screened at arrival.

    The returned `wc_v1` is the vessel version as created, which is also the
    version the accepted first screening echoed; `wc_v2` is the version the
    vessel carries afterwards.
    """
    ctx = setup_program(clock=CLOCK, risk_tier="LOW", infestation_status="CLEAN",
                        mandatory_inspection=True)
    vessel = register_watercraft(registration_number="MT-9001",
                                 last_water_body_id=ctx["water_body"]["id"],
                                 hull_length_ft=16)
    wc_v1 = vessel["version"]
    set_clock(ARRIVAL)
    record = open_record(ctx["station"]["id"], vessel["id"], ARRIVAL,
                         ctx["inspector_a"]["id"])
    screened = screen_record(record["id"], ctx["inspector_a"]["id"], wc_v1,
                            residual_water_present=False, standing_water_ml=0)
    assert screened["inspection_status"] == "SCREENED"
    assert screened["risk_score"] == 5
    wc_v2 = fetch_watercraft(vessel["id"])["version"]
    return {"inspector_id": ctx["inspector_a"]["id"], "vessel": vessel,
            "record": screened, "wc_v1": wc_v1, "wc_v2": wc_v2}


def _rescreen(record_id, inspector_id, version):
    return api_client.screen_inspection_record(
        record_id,
        screening_payload(version, residual_water_present=True, standing_water_ml=500),
        make_inspector_headers(inspector_id),
    )


class TestStaleWatercraftVersionBlocksARescreen:
    """The vessel row, not the record, is the concurrency anchor on screening."""

    def test_replaying_the_pre_screening_version_is_refused_with_412(self):
        """The version read before the first screening is stale for the second.

        PRD: "A `POST /inspection-records/{id}/screening` request must carry
        `expected_watercraft_version`, a non-optional body field holding the
        client's last observed `version` of the `Watercraft` being screened. If
        that value does not equal the vessel's current `version`, the screening is
        rejected with `ERR_STALE_WATERCRAFT_VERSION` (HTTP 412) and nothing is
        written."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_watercraft_version_blocks_a_rescreen
        """
        ctx = _record_screened_once()
        assert ctx["wc_v2"] == ctx["wc_v1"] + 1

        response = _rescreen(ctx["record"]["id"], ctx["inspector_id"], ctx["wc_v1"])

        validate_error(response, ApiErrorId.ERR_STALE_WATERCRAFT_VERSION, 412)

    def test_the_refused_rescreen_wrote_nothing_and_consumed_no_version(self):
        """The observation, the volume, the score and the vessel version all hold.

        PRD: "A re-screen overwrites `residual_water_present` and
        `standing_water_ml` with whatever the new payload supplies, re-runs the
        seal decision and both scoring variants, and overwrites `risk_score`,
        `advisory_risk_score`, `risk_band`, `decon_mandatory` and
        `quarantine_warranted`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_watercraft_version_blocks_a_rescreen
        """
        ctx = _record_screened_once()

        _rescreen(ctx["record"]["id"], ctx["inspector_id"], ctx["wc_v1"])

        record = fetch_record(ctx["record"]["id"])
        assert record["residual_water_present"] is False
        assert record["standing_water_ml"] == 0
        assert record["risk_score"] == 5
        assert record["risk_band"] == "LOW"
        assert record["inspection_status"] == "SCREENED"
        assert fetch_watercraft(ctx["vessel"]["id"])["version"] == ctx["wc_v2"]

    def test_the_identical_body_with_the_fresh_version_is_accepted(self):
        """A legal SCREENED to SCREENED supersede, so only the version differed.

        PRD: "Every screening, first or repeat, sets `screening_completed_at` to
        the current logical time, writes the screened prior water body back onto
        the vessel's `last_water_body_id`, and advances both the vessel's `version`
        and the record's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_watercraft_version_blocks_a_rescreen
        """
        ctx = _record_screened_once()

        record = validate_success(
            _rescreen(ctx["record"]["id"], ctx["inspector_id"], ctx["wc_v2"]), 200
        )

        assert record["inspection_status"] == "SCREENED"
        assert record["residual_water_present"] is True
        assert record["standing_water_ml"] == 500
        assert record["risk_score"] == 30
        assert record["risk_band"] == "MODERATE"
        assert fetch_watercraft(ctx["vessel"]["id"])["version"] == ctx["wc_v2"] + 1


def _record_with_one_decon_order():
    """A DECON_REQUIRED record on a two-bay hot-water station with one order open.

    `rec_v1` is the version the disposition returned — the version the accepted
    first order was written against — and `rec_v2` the version afterwards.
    """
    ctx = setup_program(clock=CLOCK, risk_tier="LOW", infestation_status="CLEAN",
                        mandatory_inspection=True, decon_bay_count=2)
    vessel = register_watercraft(registration_number="MT-9101",
                                 last_water_body_id=ctx["water_body"]["id"],
                                 hull_length_ft=16)
    set_clock(ARRIVAL)
    record = open_record(ctx["station"]["id"], vessel["id"], ARRIVAL,
                         ctx["inspector_a"]["id"])
    screen_record(record["id"], ctx["inspector_a"]["id"], vessel["version"],
                  residual_water_present=False, standing_water_ml=0)
    disposed = dispose_record(record["id"], ctx["inspector_a"]["id"], "DECON")
    rec_v1 = disposed["version"]
    first_order = order_decon(record["id"], ctx["inspector_a"]["id"], rec_v1)
    rec_v2 = fetch_record(record["id"])["version"]
    return {"inspector_id": ctx["inspector_a"]["id"], "record": disposed,
            "first_order": first_order, "rec_v1": rec_v1, "rec_v2": rec_v2}


def _order_again(record_id, inspector_id, version):
    return api_client.create_decon_order(
        decon_order_payload(record_id, version), make_inspector_headers(inspector_id)
    )


class TestStaleRecordVersionBlocksASecondDeconOrder:
    """The second anchor is the parent record, and the state check cannot stand in."""

    def test_replaying_the_pre_order_record_version_is_refused_with_412(self):
        """Creating the first order consumed the version the client had read.

        PRD: "A `POST /decon-orders` request must carry
        `expected_inspection_record_version`, a non-optional body field holding the
        client's last observed `version` of the `InspectionRecord` named by
        `inspection_record_id`. If that value does not equal the record's current
        `version`, the create is rejected with
        `ERR_STALE_INSPECTION_RECORD_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_record_version_blocks_a_second_decon_order
        """
        ctx = _record_with_one_decon_order()
        assert ctx["rec_v2"] == ctx["rec_v1"] + 1

        response = _order_again(ctx["record"]["id"], ctx["inspector_id"], ctx["rec_v1"])

        validate_error(response, ApiErrorId.ERR_STALE_INSPECTION_RECORD_VERSION, 412)
        record = fetch_record(ctx["record"]["id"])
        assert record["version"] == ctx["rec_v2"]
        assert record["inspection_status"] == "DECON_REQUIRED"

    def test_the_refused_create_left_no_second_order_behind(self):
        """Only the first order exists after the 412.

        PRD: "Order listings may be narrowed by `inspection_record_id`,
        `station_id`, `treated_by_inspector_id`, `verified_by_inspector_id` and
        `status`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_record_version_blocks_a_second_decon_order
        """
        ctx = _record_with_one_decon_order()

        _order_again(ctx["record"]["id"], ctx["inspector_id"], ctx["rec_v1"])

        rows, meta = validate_paginated(
            api_client.list_decon_orders(
                PROGRAM_ADMIN, params={"inspection_record_id": ctx["record"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["first_order"]["id"]

    def test_the_identical_body_with_the_fresh_version_rebooks_the_vessel(self):
        """A record may legitimately carry a second order; only the version gated it.

        PRD: "A record awaiting decontamination may legitimately carry more than
        one decontamination order — a fresh order re-books the vessel for a new
        treatment cycle and supersedes the earlier one — so a second sequential
        create observes exactly the same inspection status as the first and would
        otherwise succeed. The stale-version check is what pins which view of the
        record the new order was written against."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_record_version_blocks_a_second_decon_order
        """
        ctx = _record_with_one_decon_order()

        second = validate_success(
            _order_again(ctx["record"]["id"], ctx["inspector_id"], ctx["rec_v2"]), 201
        )

        assert second["id"] != ctx["first_order"]["id"]
        assert second["status"] == "ORDERED"
        _, meta = validate_paginated(
            api_client.list_decon_orders(
                PROGRAM_ADMIN, params={"inspection_record_id": ctx["record"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        record = fetch_record(ctx["record"]["id"])
        assert record["version"] == ctx["rec_v2"] + 1
        assert record["inspection_status"] == "DECON_REQUIRED"


def _station_with_two_certified_inspectors():
    """A hot-water station staffed by a DECON_CERTIFIED, a LEVEL_2 and a LEVEL_1."""
    ctx = setup_program(clock=CLOCK, mandatory_inspection=True, decon_bay_count=2,
                        hot_water_capable=True)
    assert ctx["inspector_b"]["certification_level"] == "DECON_CERTIFIED"
    assert ctx["inspector_c"]["certification_level"] == "LEVEL_2"
    assert ctx["inspector_a"]["certification_level"] == "LEVEL_1"
    station = fetch_station(ctx["station"]["id"])
    assert station["certified_inspector_count"] == 2
    assert station["decon_service_available"] is True
    return ctx


class TestSuspendingACertifiedInspectorClosesDeconService:
    """The staffing cascade runs subtractively and only for the certified levels."""

    def test_the_suspension_drops_the_count_and_the_derived_flag(self):
        """One of two certified inspectors leaves and decon service closes.

        PRD: "An inspector in either `PROBATIONARY` or `ACTIVE` standing may be
        moved to `SUSPENDED`; when the suspended inspector held `LEVEL_2` or
        `DECON_CERTIFIED`, the home station's `certified_inspector_count` is
        decremented and `decon_service_available` recomputed."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_suspending_a_certified_inspector_closes_decon_service
        """
        ctx = _station_with_two_certified_inspectors()

        inspector = move_inspector(ctx["inspector_c"]["id"], "SUSPENDED")

        assert inspector["status"] == "SUSPENDED"
        assert inspector["certification_level"] == "LEVEL_2"
        station = fetch_station(ctx["station"]["id"])
        assert station["certified_inspector_count"] == 1
        assert station["decon_service_available"] is False
        assert station["hot_water_capable"] is True

    def test_suspending_an_uncertified_inspector_moves_neither_field(self):
        """A LEVEL_1 was never counted, so the cascade is keyed on level not headcount.

        PRD: "`certified_inspector_count` — the number of that station's inspectors
        who are simultaneously in `ACTIVE` standing and at level `LEVEL_2` or
        `DECON_CERTIFIED` — is recomputed, and `decon_service_available` is
        recomputed from the new count."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_suspending_a_certified_inspector_closes_decon_service
        """
        ctx = _station_with_two_certified_inspectors()
        move_inspector(ctx["inspector_c"]["id"], "SUSPENDED")

        inspector = move_inspector(ctx["inspector_a"]["id"], "SUSPENDED")

        assert inspector["status"] == "SUSPENDED"
        assert inspector["certification_level"] == "LEVEL_1"
        station = fetch_station(ctx["station"]["id"])
        assert station["certified_inspector_count"] == 1
        assert station["decon_service_available"] is False

    def test_reinstatement_restores_both_fields_and_closes_the_loop(self):
        """SUSPENDED back to ACTIVE re-runs the staffing cascade upward.

        PRD: "Reinstatement `SUSPENDED → ACTIVE` requires two things: the
        inspector's `certification_level` must not be `TRAINEE`, and the current
        logical time must be strictly before their `certification_expires_at`.
        Reinstatement re-runs the station staffing cascade and advances the
        inspector's `version` by 1, closing the `ACTIVE → SUSPENDED → ACTIVE` loop."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_suspending_a_certified_inspector_closes_decon_service
        """
        ctx = _station_with_two_certified_inspectors()
        suspended = move_inspector(ctx["inspector_c"]["id"], "SUSPENDED")

        reinstated = move_inspector(ctx["inspector_c"]["id"], "ACTIVE")

        assert reinstated["status"] == "ACTIVE"
        assert reinstated["version"] == suspended["version"] + 1
        station = fetch_station(ctx["station"]["id"])
        assert station["certified_inspector_count"] == 2
        assert station["decon_service_available"] is True
        assert station["hot_water_capable"] is True


DERIVED_SCREENING_FIELDS = (
    "risk_score",
    "advisory_risk_score",
    "risk_band",
    "decon_mandatory",
    "quarantine_warranted",
    "reciprocity_seal_honored",
    "dry_credit_points",
)


def _record_awaiting_screening():
    """A HIGH CLEAN lake, one 20-foot open hull, one record opened at arrival."""
    ctx = setup_program(clock=CLOCK, risk_tier="HIGH", infestation_status="CLEAN",
                        mandatory_inspection=True)
    vessel = register_watercraft(registration_number="MT-9201",
                                 last_water_body_id=ctx["water_body"]["id"],
                                 hull_length_ft=20)
    set_clock(ARRIVAL)
    record = open_record(ctx["station"]["id"], vessel["id"], ARRIVAL,
                         ctx["inspector_a"]["id"])
    return {"water_body": ctx["water_body"], "inspector_id": ctx["inspector_a"]["id"],
            "vessel": vessel, "record": record}


class TestScreeningResponseAlreadyCarriesEveryDerivedField:
    """Nothing settles after the write: the screening response is authoritative."""

    def test_the_screening_response_body_is_already_fully_derived(self):
        """One call returns both bases, the band and every gate boolean.

        PRD: "The service is immediately consistent: by the time a response is
        returned, every cascaded write has landed, every derived counter has been
        recomputed, and the `version` and `updated_at` of every touched row have
        advanced."

        Design: Corner/consistency_model/immediate_screening_response_already_carries_every_derived_field
        """
        ctx = _record_awaiting_screening()

        record = screen_record(ctx["record"]["id"], ctx["inspector_id"],
                               ctx["vessel"]["version"], residual_water_present=True,
                               standing_water_ml=500)

        assert record["risk_score"] == 65
        assert record["advisory_risk_score"] == 65
        assert record["risk_band"] == "HIGH"
        assert record["decon_mandatory"] is True
        assert record["quarantine_warranted"] is False
        assert record["reciprocity_seal_honored"] is False
        assert record["dry_credit_points"] == 0
        assert_instant_equals(record["screening_completed_at"], ARRIVAL,
                              "screening_completed_at")

    def test_the_immediate_re_read_agrees_field_for_field(self):
        """No derived field lags one request behind its write.

        PRD: "Cascades are described in full in the workflow narratives of §3; what
        matters globally is that they are not optional, not deferred, and not
        partial."

        Design: Corner/consistency_model/immediate_screening_response_already_carries_every_derived_field
        """
        ctx = _record_awaiting_screening()
        written = screen_record(ctx["record"]["id"], ctx["inspector_id"],
                                ctx["vessel"]["version"], residual_water_present=True,
                                standing_water_ml=500)

        read = fetch_record(ctx["record"]["id"])

        for field in DERIVED_SCREENING_FIELDS:
            assert read[field] == written[field], field
        assert_instant_equals(read["screening_completed_at"],
                              written["screening_completed_at"],
                              "screening_completed_at")
        assert read["version"] == written["version"]

    def test_the_cross_entity_write_is_visible_without_any_settling_delay(self):
        """The vessel already shows its new version and declared water body.

        PRD: "Every screening, first or repeat, sets `screening_completed_at` to
        the current logical time, writes the screened prior water body back onto
        the vessel's `last_water_body_id`, and advances both the vessel's `version`
        and the record's `version` by 1."

        Design: Corner/consistency_model/immediate_screening_response_already_carries_every_derived_field
        """
        ctx = _record_awaiting_screening()

        screen_record(ctx["record"]["id"], ctx["inspector_id"],
                      ctx["vessel"]["version"], residual_water_present=True,
                      standing_water_ml=500)

        vessel = fetch_watercraft(ctx["vessel"]["id"])
        assert vessel["version"] == ctx["vessel"]["version"] + 1
        assert vessel["last_water_body_id"] == ctx["water_body"]["id"]


def _submitted_live_report_off_swan_lake():
    """A SUBMITTED LIVE_ORGANISM report naming a CLEAN LOW water body upstream."""
    ctx = setup_program(clock=CLOCK, risk_tier="HIGH", infestation_status="CLEAN",
                        mandatory_inspection=True)
    prior = create_water_body(name="Swan Lake", risk_tier="LOW",
                             infestation_status="CLEAN")
    vessel = register_watercraft(registration_number="MT-9301",
                                 last_water_body_id=prior["id"], hull_length_ft=20)
    set_clock(ARRIVAL)
    record = open_record(ctx["station"]["id"], vessel["id"], ARRIVAL,
                         ctx["inspector_a"]["id"])
    screen_record(record["id"], ctx["inspector_a"]["id"], vessel["version"],
                  residual_water_present=False, standing_water_ml=0,
                  prior_water_body_id=prior["id"])
    report = draft_detection_report(
        record["id"], ctx["inspector_a"]["id"],
        species_code="DREISSENA_POLYMORPHA", detection_class="LIVE_ORGANISM",
    )
    submitted = submit_detection_report(report["id"], ctx["inspector_a"]["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["water_body_id"] == prior["id"]
    return {"prior": prior, "report": submitted}


def _acknowledge(report_id):
    return api_client.acknowledge_detection_report(
        report_id,
        acknowledgement_payload("ACCEPTED", state_db_ack_id="AIS-2026-000512"),
        make_state_data_steward_headers("steward-77"),
    )


class TestAcknowledgementCascadeIsReadableOnTheVeryNextRequest:
    """The longest cascade in the API is still immediate, hop for hop."""

    def test_the_counters_are_incremented_by_the_time_the_response_returns(self):
        """The acknowledgement answers ACCEPTED and the next read already shows 1 and 1.

        PRD: "In the second hop, the water body's `detection_count` is incremented
        by 1, and its `live_detection_count` is incremented by 1 as well when the
        report's `detection_class` is `LIVE_ORGANISM`; the escalation rule then runs
        **on the counters as they stand after those increments**."

        Design: Corner/consistency_model/immediate_acknowledgement_cascade_is_readable_on_the_very_next_request
        """
        ctx = _submitted_live_report_off_swan_lake()

        report = validate_success(_acknowledge(ctx["report"]["id"]), 200)

        assert report["status"] == "ACCEPTED"
        assert report["state_db_ack_id"] == "AIS-2026-000512"
        prior = fetch_water_body(ctx["prior"]["id"])
        assert prior["detection_count"] == 1
        assert prior["live_detection_count"] == 1

    def test_the_escalated_posture_needs_no_intervening_write(self):
        """The very same read already reports SUSPECT with the tier left alone.

        PRD: "Otherwise, when `detection_count` has reached 1 and the water body's
        `infestation_status` is still `CLEAN`, `infestation_status` is set to
        `SUSPECT` and `risk_tier` is left as it was."

        Design: Corner/consistency_model/immediate_acknowledgement_cascade_is_readable_on_the_very_next_request
        """
        ctx = _submitted_live_report_off_swan_lake()

        _acknowledge(ctx["report"]["id"])

        prior = fetch_water_body(ctx["prior"]["id"])
        assert prior["infestation_status"] == "SUSPECT"
        assert prior["risk_tier"] == "LOW"

    def test_the_list_projection_is_as_fresh_as_the_row(self):
        """A filtered listing and a repeated read both answer without a settling window.

        PRD: "Report listings may be narrowed by `inspection_record_id`,
        `water_body_id`, `reported_by_inspector_id`, `status` and
        `detection_class`."

        Design: Corner/consistency_model/immediate_acknowledgement_cascade_is_readable_on_the_very_next_request
        """
        ctx = _submitted_live_report_off_swan_lake()
        acknowledged = validate_success(_acknowledge(ctx["report"]["id"]), 200)

        rows, meta = validate_paginated(
            api_client.list_detection_reports(
                PROGRAM_ADMIN,
                params={"water_body_id": ctx["prior"]["id"], "status": "ACCEPTED"},
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["report"]["id"]
        again = fetch_detection_report(ctx["report"]["id"])
        assert again["status"] == acknowledged["status"]
        assert again["state_db_ack_id"] == acknowledged["state_db_ack_id"]
        assert again["version"] == acknowledged["version"]
        prior = fetch_water_body(ctx["prior"]["id"])
        assert prior["detection_count"] == 1
        assert prior["live_detection_count"] == 1
        assert prior["infestation_status"] == "SUSPECT"
