"""Endpoint corners: plain CRUD, the one partial update, derived links and lazy expiry."""
from test_helpers import (
    ENFORCEMENT_OFFICER,
    NON_EXISTENT_UUID,
    PROGRAM_ADMIN,
    ApiErrorId,
    api_client,
    assert_detection_report,
    assert_instant_equals,
    assert_reciprocity_agreement,
    assert_seal_inventory_conserved,
    assert_station_fee_ledger,
    breach_report_payload,
    create_water_body,
    detection_report_payload,
    dispose_record,
    draft_detection_report,
    fetch_decon_order,
    fetch_detection_report,
    fetch_inspector,
    fetch_quarantine_order,
    fetch_record,
    fetch_station,
    fetch_water_body,
    fetch_watercraft,
    issue_quarantine,
    make_decon_technician_headers,
    make_inspector_headers,
    move_inspector,
    reciprocity_agreement_payload,
    report_breach,
    request_release,
    set_clock,
    setup_decon_order,
    setup_inspection,
    setup_program,
    submission_payload,
    treatment_payload,
    validate_error,
    validate_paginated,
    validate_success,
    water_body_patch_payload,
)

CLOCK = "2026-08-01T00:00:00Z"
ARRIVAL = "2026-08-05T09:00:00Z"
SECOND_ARRIVAL = "2026-08-05T09:30:00Z"


def _create_idaho_agreement():
    """The interstate registry's whole write surface in one call."""
    set_clock(CLOCK)
    return api_client.create_reciprocity_agreement(
        reciprocity_agreement_payload(
            partner_state_code="ID", accepted_seal_prefix="ID-",
            honors_our_seals=True, max_seal_age_hours=72, fee_waiver=False,
        ),
        PROGRAM_ADMIN,
    )


class TestReciprocityAgreementRoundTrip:
    """Create, read and list are the agreement's entire surface."""

    def test_creation_echoes_every_negotiated_term_and_defaults_the_status(self):
        """The five supplied terms come back and `status` opens ACTIVE.

        PRD: "An agreement's `status` begins `ACTIVE`, and a `ProgramAdmin` may
        move it between `ACTIVE` and `SUSPENDED` by supplying a `target_status`
        with an optional `reason`."

        Design: Corner/endpoints/standard_crud_reciprocity_agreement_create_read_list_round_trip
        """
        agreement = validate_success(_create_idaho_agreement(), 201)

        assert_reciprocity_agreement(agreement)
        assert agreement["partner_state_code"] == "ID"
        assert agreement["accepted_seal_prefix"] == "ID-"
        assert agreement["max_seal_age_hours"] == 72
        assert agreement["honors_our_seals"] is True
        assert agreement["fee_waiver"] is False
        assert agreement["status"] == "ACTIVE"

    def test_the_single_read_returns_the_creation_response_field_for_field(self):
        """The read is not a projection: every value and the version match.

        PRD: "An agreement is created with the partner's two-letter
        `partner_state_code`, unique across agreements and likewise guarded by
        `ERR_DUPLICATE_IDENTIFIER`, and the `accepted_seal_prefix` (non-empty, at
        most 8 characters) that a seal number from that state must begin with
        before this program will look at it."

        Design: Corner/endpoints/standard_crud_reciprocity_agreement_create_read_list_round_trip
        """
        created = validate_success(_create_idaho_agreement(), 201)

        read = validate_success(
            api_client.get_reciprocity_agreement(created["id"], PROGRAM_ADMIN), 200
        )

        assert read["id"] == created["id"]
        assert read["version"] == created["version"]
        for field in ("partner_state_code", "accepted_seal_prefix",
                      "max_seal_age_hours", "honors_our_seals", "fee_waiver",
                      "status"):
            assert read[field] == created[field]
        assert_instant_equals(read["created_at"], created["created_at"], "created_at")

    def test_a_non_matching_filter_returns_an_empty_page_rather_than_a_404(self):
        """Both declared filters narrow the set before total_count is computed.

        PRD: "Agreement listings may be narrowed by `partner_state_code` and
        `status`."

        Design: Corner/endpoints/standard_crud_reciprocity_agreement_create_read_list_round_trip
        """
        created = validate_success(_create_idaho_agreement(), 201)

        rows, meta = validate_paginated(
            api_client.list_reciprocity_agreements(
                PROGRAM_ADMIN, params={"partner_state_code": "ID"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == created["id"]

        empty_rows, empty_meta = validate_paginated(
            api_client.list_reciprocity_agreements(
                PROGRAM_ADMIN, params={"partner_state_code": "WY"}
            )
        )
        assert empty_meta["total_count"] == 0
        assert empty_rows == []

        _suspended, suspended_meta = validate_paginated(
            api_client.list_reciprocity_agreements(
                PROGRAM_ADMIN, params={"status": "SUSPENDED"}
            )
        )
        assert suspended_meta["total_count"] == 0


def _river_downstream_of_a_lake():
    """A SUSPECT river carrying a real drainage parent worth preserving."""
    set_clock(CLOCK)
    upstream = create_water_body(
        name="Upper Whitefish", water_body_class="LAKE", risk_tier="MODERATE"
    )
    downstream = create_water_body(
        name="Whitefish Outlet", water_body_class="RIVER", risk_tier="LOW",
        infestation_status="SUSPECT", downstream_of_water_body_id=upstream["id"],
    )
    return upstream, downstream


class TestWaterBodyPatchIsANarrowPartialUpdate:
    """The only update endpoint moves what it is given and nothing else."""

    def test_a_patch_carrying_only_the_risk_tier_leaves_the_drainage_parent_alone(self):
        """risk_tier moves, the omitted parent is preserved and version steps once.

        PRD: "Correction after a survey is deliberately narrow: only
        `downstream_of_water_body_id` and `risk_tier` may be changed once the row
        exists, the drainage cycle check is re-run from the corrected water body,
        and the correction leaves `detection_count`, `live_detection_count` and
        `infestation_status` untouched while advancing the water body's `version`
        by 1."

        Design: Corner/endpoints/standard_crud_water_body_patch_updates_only_the_supplied_field
        """
        upstream, downstream = _river_downstream_of_a_lake()

        patched = validate_success(
            api_client.patch_water_body(
                downstream["id"], water_body_patch_payload(risk_tier="HIGH"),
                PROGRAM_ADMIN,
            ),
            200,
        )

        assert patched["risk_tier"] == "HIGH"
        assert patched["downstream_of_water_body_id"] == upstream["id"]
        assert patched["infestation_status"] == "SUSPECT"
        assert patched["detection_count"] == 0
        assert patched["live_detection_count"] == 0
        assert patched["version"] == downstream["version"] + 1

    def test_the_patched_row_re_reads_the_same_values(self):
        """The response was saved state, not a projection over the request.

        PRD: "Infestation posture is not correctable by hand at all — the
        detection-report acknowledgement described in §3.8 is its single writer."

        Design: Corner/endpoints/standard_crud_water_body_patch_updates_only_the_supplied_field
        """
        upstream, downstream = _river_downstream_of_a_lake()
        patched = validate_success(
            api_client.patch_water_body(
                downstream["id"], water_body_patch_payload(risk_tier="HIGH"),
                PROGRAM_ADMIN,
            ),
            200,
        )

        stored = fetch_water_body(downstream["id"])

        assert stored["risk_tier"] == "HIGH"
        assert stored["downstream_of_water_body_id"] == upstream["id"]
        assert stored["infestation_status"] == "SUSPECT"
        assert stored["version"] == patched["version"]

    def test_a_patch_that_supplies_neither_correctable_field_changes_nothing(self):
        """An empty correction is accepted and leaves both values where they were.

        PRD: "only `downstream_of_water_body_id` and `risk_tier` may be changed
        once the row exists"

        Design: Corner/endpoints/standard_crud_water_body_patch_updates_only_the_supplied_field
        """
        upstream, downstream = _river_downstream_of_a_lake()
        first = validate_success(
            api_client.patch_water_body(
                downstream["id"], water_body_patch_payload(risk_tier="HIGH"),
                PROGRAM_ADMIN,
            ),
            200,
        )

        again = validate_success(
            api_client.patch_water_body(
                downstream["id"], water_body_patch_payload(), PROGRAM_ADMIN
            ),
            200,
        )

        assert again["risk_tier"] == "HIGH"
        assert again["downstream_of_water_body_id"] == upstream["id"]
        assert again["infestation_status"] == "SUSPECT"
        assert again["version"] == first["version"] + 1


def _screened_record_off_another_lake(*, prior_infestation="CLEAN"):
    """A screened record whose prior water body is a second, separate lake."""
    ctx = setup_program(risk_tier="HIGH", infestation_status="CLEAN",
                        mandatory_inspection=True)
    ctx["prior"] = create_water_body(
        name="Swan Lake", water_body_class="LAKE", risk_tier="LOW",
        infestation_status=prior_infestation,
    )
    ctx = setup_inspection(
        ctx, arrived_at=ARRIVAL, screen_at=ARRIVAL,
        last_water_body_id=ctx["prior"]["id"],
        prior_water_body_id=ctx["prior"]["id"],
    )
    return ctx


class TestReportSubmissionMovesDraftToSubmitted:
    """One call flips the status, counts the attempt and clears the old verdict."""

    def test_the_submission_flips_the_status_and_counts_the_attempt(self):
        """DRAFT becomes SUBMITTED with submission_count 1 and no acknowledgement.

        PRD: "Submission moves the report `DRAFT → SUBMITTED`, or `REJECTED →
        SUBMITTED` on a resubmission, incrementing `submission_count` by 1 and
        clearing any `rejection_reason` left over from a previous verdict, then
        advancing the report's `version` by 1."

        Design: Corner/endpoints/action_endpoint_report_submission_moves_draft_to_submitted_and_counts
        """
        ctx = _screened_record_off_another_lake(prior_infestation="CONFIRMED_INFESTED")
        report = draft_detection_report(
            ctx["record"]["id"], ctx["inspector_a"]["id"], "LIVE_ORGANISM",
            species_code="DREISSENA_BUGENSIS",
        )
        assert report["status"] == "DRAFT"
        assert report["submission_count"] == 0

        submitted = validate_success(
            api_client.submit_detection_report(
                report["id"], submission_payload(notes="adult mussels, bagged"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            200,
        )

        assert_detection_report(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_count"] == 1
        assert submitted["rejection_reason"] is None
        assert submitted["state_db_ack_id"] is None
        assert submitted["version"] == report["version"] + 1

    def test_submission_alone_reports_nothing_to_the_state_register(self):
        """Neither water body counter moves until a steward accepts.

        PRD: "Both detection counters, `detection_count` and
        `live_detection_count`, start at 0 and are never written by a client."

        Design: Corner/endpoints/action_endpoint_report_submission_moves_draft_to_submitted_and_counts
        """
        ctx = _screened_record_off_another_lake(prior_infestation="CONFIRMED_INFESTED")
        report = draft_detection_report(
            ctx["record"]["id"], ctx["inspector_a"]["id"], "LIVE_ORGANISM"
        )

        validate_success(
            api_client.submit_detection_report(
                report["id"], submission_payload(),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            200,
        )

        prior = fetch_water_body(ctx["prior"]["id"])
        assert prior["detection_count"] == 0
        assert prior["live_detection_count"] == 0
        assert prior["infestation_status"] == "CONFIRMED_INFESTED"

    def test_a_second_submission_of_a_submitted_report_is_refused(self):
        """The precondition is the report's own status, and the count does not move.

        PRD: "A submission aimed at a report that is neither `DRAFT` nor
        `REJECTED` is rejected with `ERR_REPORT_INVALID_STATE`."

        Design: Corner/endpoints/action_endpoint_report_submission_moves_draft_to_submitted_and_counts
        """
        ctx = _screened_record_off_another_lake(prior_infestation="CONFIRMED_INFESTED")
        report = draft_detection_report(
            ctx["record"]["id"], ctx["inspector_a"]["id"], "LIVE_ORGANISM"
        )
        headers = make_inspector_headers(ctx["inspector_a"]["id"])
        submitted = validate_success(
            api_client.submit_detection_report(report["id"], submission_payload(),
                                               headers),
            200,
        )

        response = api_client.submit_detection_report(
            report["id"], submission_payload(), headers
        )

        validate_error(response, ApiErrorId.ERR_REPORT_INVALID_STATE, 409)
        after = fetch_detection_report(report["id"])
        assert after["status"] == "SUBMITTED"
        assert after["submission_count"] == 1
        assert after["version"] == submitted["version"]


class TestDetectionReportInheritsThePriorWaterBody:
    """The report's water body is derived from the parent record, never supplied."""

    def test_the_report_names_the_water_the_boat_came_from(self):
        """water_body_id is the record's prior lake, not the lake the station guards.

        PRD: "Drafting copies `water_body_id` from the parent record's
        `prior_water_body_id` — the water the boat came from, which is the water
        at risk — and takes `reported_by_inspector_id` from `X-User-ID`."

        Design: Corner/endpoints/cross_reference_link_detection_report_inherits_the_records_prior_water_body
        """
        ctx = _screened_record_off_another_lake()

        report = validate_success(
            api_client.create_detection_report(
                detection_report_payload(
                    ctx["record"]["id"], "PLANT_FRAGMENT",
                    species_code="HYDRILLA_VERTICILLATA",
                    observed_at="2026-08-05T09:05:00Z",
                ),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            201,
        )

        assert_detection_report(report)
        assert report["inspection_record_id"] == ctx["record"]["id"]
        assert report["water_body_id"] == ctx["prior"]["id"]
        assert report["water_body_id"] != ctx["water_body"]["id"]
        assert report["reported_by_inspector_id"] == ctx["inspector_a"]["id"]
        assert report["status"] == "DRAFT"
        assert report["submission_count"] == 0
        assert report["state_db_ack_id"] is None
        assert report["rejection_reason"] is None

    def test_the_derived_association_is_queryable_in_both_directions(self):
        """The prior lake finds the report and the guarded lake does not.

        PRD: "Report listings may be narrowed by `inspection_record_id`,
        `water_body_id`, `reported_by_inspector_id`, `status` and
        `detection_class`."

        Design: Corner/endpoints/cross_reference_link_detection_report_inherits_the_records_prior_water_body
        """
        ctx = _screened_record_off_another_lake()
        report = draft_detection_report(
            ctx["record"]["id"], ctx["inspector_a"]["id"], "PLANT_FRAGMENT"
        )

        rows, meta = validate_paginated(
            api_client.list_detection_reports(
                PROGRAM_ADMIN, params={"water_body_id": ctx["prior"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == report["id"]

        _guarded, guarded_meta = validate_paginated(
            api_client.list_detection_reports(
                PROGRAM_ADMIN, params={"water_body_id": ctx["water_body"]["id"]}
            )
        )
        assert guarded_meta["total_count"] == 0

    def test_the_link_cannot_be_forged_against_a_missing_parent(self):
        """An unknown inspection_record_id is a 404 and writes no report.

        PRD: "Every foreign key supplied in a request body must resolve to an
        existing row before any business rule is evaluated: `station_id`,
        `watercraft_id`, `prior_water_body_id`, `home_station_id`,
        `last_water_body_id`, `target_water_body_id`, `inspection_record_id`,
        `downstream_of_water_body_id` and `water_body_id` are all checked this
        way"

        Design: Corner/endpoints/cross_reference_link_detection_report_inherits_the_records_prior_water_body
        """
        ctx = _screened_record_off_another_lake()

        response = api_client.create_detection_report(
            detection_report_payload(NON_EXISTENT_UUID, "PLANT_FRAGMENT"),
            make_inspector_headers(ctx["inspector_a"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_INSPECTION_RECORD_NOT_FOUND, 404)
        _rows, meta = validate_paginated(
            api_client.list_detection_reports(PROGRAM_ADMIN)
        )
        assert meta["total_count"] == 0


def _two_screened_low_risk_records():
    """Two vessels screened clean at one station on a LOW, CLEAN water body."""
    ctx = setup_program(risk_tier="LOW", infestation_status="CLEAN",
                        mandatory_inspection=True)
    ctx = setup_inspection(ctx, arrived_at=ARRIVAL, screen_at=ARRIVAL)
    first = ctx["record"]
    ctx = setup_inspection(ctx, arrived_at=SECOND_ARRIVAL, screen_at=SECOND_ARRIVAL)
    second = ctx["record"]
    return ctx, first, second


class TestStationFeeLedgerAggregatesTwoDispositions:
    """The station read exposes a running ledger, not a stored input."""

    def test_two_passes_leave_the_ledger_at_twice_the_base_fee(self):
        """collected_fees_cents is 5000 and each ledger write stepped the version.

        PRD: "For every station, `collected_fees_cents` equals the sum over that
        station's inspection records of `total_fee_cents` minus
        `fee_refunded_cents`, and `refunded_fees_cents` equals the sum of
        `fee_refunded_cents` over the same records."

        Design: Corner/endpoints/computed_read_station_fee_ledger_aggregates_two_dispositions
        """
        ctx, first, second = _two_screened_low_risk_records()
        before = fetch_station(ctx["station"]["id"])
        assert before["collected_fees_cents"] == 0
        inspector_id = ctx["inspector_a"]["id"]

        passed_first = dispose_record(first["id"], inspector_id, "PASS")
        passed_second = dispose_record(second["id"], inspector_id, "PASS")

        station = validate_success(
            api_client.get_station(ctx["station"]["id"], PROGRAM_ADMIN), 200
        )
        assert station["collected_fees_cents"] == 5000
        assert station["refunded_fees_cents"] == 0
        assert station["campaign_allocated_cents"] == 0
        assert station["version"] == before["version"] + 2
        assert_station_fee_ledger(station, [passed_first, passed_second])

    def test_each_record_independently_reports_its_own_uncharged_components(self):
        """Both records carry 2500 with no decontamination and no surcharge.

        PRD: "Third the subtotal is formed as `inspection_fee_cents` plus
        `decon_fee_cents`. Fourth the surcharge rate is selected **from that
        pre-surcharge subtotal**: no surcharge at all when the subtotal is below
        10,000 cents, 5 percent when the subtotal is from 10,000 cents up to but
        not including 25,000 cents, and 10 percent from 25,000 cents upward."

        Design: Corner/endpoints/computed_read_station_fee_ledger_aggregates_two_dispositions
        """
        ctx, first, second = _two_screened_low_risk_records()
        inspector_id = ctx["inspector_a"]["id"]
        dispose_record(first["id"], inspector_id, "PASS")
        dispose_record(second["id"], inspector_id, "PASS")

        for record_id in (first["id"], second["id"]):
            record = fetch_record(record_id)
            assert record["inspection_status"] == "PASSED"
            assert record["inspection_fee_cents"] == 2500
            assert record["decon_fee_cents"] == 0
            assert record["surcharge_cents"] == 0
            assert record["total_fee_cents"] == 2500
            assert record["fee_refunded_cents"] == 0

    def test_both_vessels_scored_five_which_is_why_the_pass_was_legal(self):
        """A LOW, CLEAN prior water body with no water scores 5 in the LOW band.

        PRD: "A pass is refused when the record's `decon_mandatory` is true, and
        equally when the vessel carries `mandatory_decon_flag` true, unless some
        decontamination order belonging to this record has already reached
        `VERIFIED`; the rejection is `ERR_DECON_REQUIRED_BEFORE_PASS`."

        Design: Corner/endpoints/computed_read_station_fee_ledger_aggregates_two_dispositions
        """
        _ctx, first, second = _two_screened_low_risk_records()

        for record in (fetch_record(first["id"]), fetch_record(second["id"])):
            assert record["risk_score"] == 5
            assert record["risk_band"] == "LOW"
            assert record["decon_mandatory"] is False


def _two_sealed_vessels():
    """Two vessels off a confirmed-infested lake, each sealed under its own order."""
    ctx = setup_program(risk_tier="HIGH", infestation_status="CLEAN",
                        mandatory_inspection=True, seal_stock_initial_count=5)
    ctx["prior"] = create_water_body(
        name="Swan Lake", water_body_class="LAKE", risk_tier="LOW",
        infestation_status="CONFIRMED_INFESTED",
    )
    orders = []
    for arrived_at, seal_number in ((ARRIVAL, "MT-SEAL-0001"),
                                    (SECOND_ARRIVAL, "MT-SEAL-0002")):
        ctx = setup_inspection(
            ctx, arrived_at=arrived_at, screen_at=arrived_at,
            last_water_body_id=ctx["prior"]["id"],
            prior_water_body_id=ctx["prior"]["id"], disposition="DECON",
        )
        assert ctx["record"]["risk_score"] == 35
        assert ctx["record"]["risk_band"] == "MODERATE"
        assert ctx["record"]["quarantine_warranted"] is True
        order = issue_quarantine(
            ctx["record"]["id"], ctx["inspector_a"]["id"], seal_number
        )
        assert order["status"] == "SEALED"
        orders.append({"order": order, "record": ctx["record"],
                       "watercraft": ctx["watercraft"]})
    return ctx, orders[0], orders[1]


class TestBreachReportHasTwoLegalSourceStates:
    """SEALED and RELEASE_REQUESTED both void, and the seal is forfeited either way."""

    def test_a_breach_reported_from_sealed_voids_and_refers(self):
        """VOIDED_BREACH, a SEAL_TAMPER referral and a cleared vessel hold.

        PRD: "A breach report voids the order from either `SEALED` or
        `RELEASE_REQUESTED`, setting `status` to `VOIDED_BREACH`. The side effects
        are identical from both origins: the station's `seals_in_circulation_count`
        is decremented by 1 and `seals_retired_count` incremented by 1, because a
        breached seal is forfeited rather than returned; the vessel's
        `quarantine_hold_until` is cleared, since a voided order is no longer in
        `SEALED` or `RELEASE_REQUESTED` and therefore holds nothing; and the parent
        record's enforcement dimension is driven `NONE → REFERRED` with
        `referral_reason` set to `SEAL_TAMPER`, but only when that record's
        `enforcement_status` is still `NONE`."

        Design: Corner/endpoints/conditional_action_breach_report_legal_from_sealed_and_release_requested
        """
        _ctx, first, _second = _two_sealed_vessels()

        voided = report_breach(first["order"]["id"])

        assert voided["status"] == "VOIDED_BREACH"
        record = fetch_record(first["record"]["id"])
        assert record["enforcement_status"] == "REFERRED"
        assert record["referral_reason"] == "SEAL_TAMPER"
        assert fetch_watercraft(first["watercraft"]["id"])["quarantine_hold_until"] is None

    def test_a_breach_reported_from_release_requested_voids_identically(self):
        """The second origin state reaches the same terminal status.

        PRD: "A tampered or broken seal is reported separately, and either a
        `ReleaseVerifier` or an `EnforcementOfficer` may report it, optionally
        with `notes`."

        Design: Corner/endpoints/conditional_action_breach_report_legal_from_sealed_and_release_requested
        """
        ctx, _first, second = _two_sealed_vessels()
        set_clock("2026-08-10T09:00:00Z")
        requested = request_release(second["order"]["id"], ctx["inspector_a"]["id"])
        assert requested["status"] == "RELEASE_REQUESTED"

        voided = report_breach(second["order"]["id"])

        assert voided["status"] == "VOIDED_BREACH"
        assert fetch_record(second["record"]["id"])["referral_reason"] == "SEAL_TAMPER"

    def test_a_repeat_breach_is_refused_and_both_seals_stay_retired(self):
        """VOIDED_BREACH is terminal, and 3 + 0 + 2 still equals the initial 5.

        PRD: "`ERR_QUARANTINE_NOT_SEALED` when a release request or a breach
        report targets an order in a state that does not permit it"  PRD: "For any
        station whose lifecycle has ever left the planning stage,
        `seal_stock_count` plus `seals_in_circulation_count` plus
        `seals_retired_count` always equals `seal_stock_initial_count`."

        Design: Corner/endpoints/conditional_action_breach_report_legal_from_sealed_and_release_requested
        """
        ctx, first, second = _two_sealed_vessels()
        report_breach(first["order"]["id"])
        report_breach(second["order"]["id"])
        before = fetch_station(ctx["station"]["id"])

        response = api_client.report_quarantine_breach(
            first["order"]["id"], breach_report_payload(), ENFORCEMENT_OFFICER
        )

        validate_error(response, ApiErrorId.ERR_QUARANTINE_NOT_SEALED, 409)
        assert fetch_quarantine_order(first["order"]["id"])["status"] == "VOIDED_BREACH"
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 3
        assert station["seals_in_circulation_count"] == 0
        assert station["seals_retired_count"] == 2
        assert station["version"] == before["version"]
        assert_seal_inventory_conserved(station)


def _two_orders_and_a_technician_about_to_lapse():
    """Two ORDERED decon orders and a technician whose certification ends 2027-08-01."""
    ctx = setup_decon_order(decon_bay_count=2, arrived_at=ARRIVAL, screen_at=ARRIVAL)
    first = ctx["decon_order"]
    ctx = setup_decon_order(ctx, arrived_at=SECOND_ARRIVAL, screen_at=SECOND_ARRIVAL)
    second = ctx["decon_order"]
    technician = ctx["inspector_b"]
    assert technician["certification_level"] == "DECON_CERTIFIED"
    assert_instant_equals(
        technician["certification_expires_at"], "2027-08-01T00:00:00Z",
        "certification_expires_at",
    )
    return ctx, first, second


def _treat(order_id, technician_id):
    return api_client.treat_decon_order(
        order_id, treatment_payload(140, 3000, 120),
        make_decon_technician_headers(technician_id),
    )


class TestExpiredCertificationBlocksTreatmentLazily:
    """The boundary is evaluated against the logical clock, one second at a time."""

    def test_one_second_before_the_expiry_the_treatment_is_legal(self):
        """At 2027-07-31T23:59:59Z the same technician records a full treatment.

        PRD: "There is no sweep and no background job: the `ACTIVE → EXPIRED`
        transition fires the next time the inspector is referenced, either as the
        acting principal or as the subject of a treatment or verification, and
        only when the current logical time has reached or passed their
        `certification_expires_at`."

        Design: Corner/endpoints/conditional_action_expired_certification_blocks_treatment_without_mutating_on_clock_advance
        """
        ctx, first, _second = _two_orders_and_a_technician_about_to_lapse()
        set_clock("2027-07-31T23:59:59Z")

        order = validate_success(_treat(first["id"], ctx["inspector_b"]["id"]), 200)

        assert order["status"] == "TREATED"
        assert order["treated_by_inspector_id"] == ctx["inspector_b"]["id"]
        assert float(order["treatment_effectiveness_pct"]) == 100.00
        assert order["base_dry_hours"] == 72
        assert order["required_dry_hours"] == 18
        assert_instant_equals(order["treated_at"], "2027-08-01T00:01:59Z", "treated_at")
        assert_instant_equals(order["dry_until"], "2027-08-01T18:01:59Z", "dry_until")

    def test_at_the_expiry_instant_the_identical_call_is_refused_and_persists_the_lapse(self):
        """The clock call mutates nothing; the treatment attempt flips the standing.

        PRD: "When it fires, the inspector's standing is set to `EXPIRED`, the home
        station's `certified_inspector_count` is decremented if they held `LEVEL_2`
        or `DECON_CERTIFIED`, `decon_service_available` is recomputed, and the
        inspector's `version` advances by 1 — and *then* the triggering request
        itself is rejected with `ERR_INSPECTOR_NOT_ACTIVE`."

        Design: Corner/endpoints/conditional_action_expired_certification_blocks_treatment_without_mutating_on_clock_advance
        """
        ctx, first, second = _two_orders_and_a_technician_about_to_lapse()
        set_clock("2027-07-31T23:59:59Z")
        validate_success(_treat(first["id"], ctx["inspector_b"]["id"]), 200)
        clock = set_clock("2027-08-01T00:00:00Z")
        assert_instant_equals(clock["current_utc"], "2027-08-01T00:00:00Z", "current_utc")

        response = _treat(second["id"], ctx["inspector_b"]["id"])

        validate_error(response, ApiErrorId.ERR_INSPECTOR_NOT_ACTIVE, 409)
        blocked = fetch_decon_order(second["id"])
        assert blocked["status"] == "ORDERED"
        assert blocked["attempt_count"] == 0
        assert blocked["treated_by_inspector_id"] is None
        assert blocked["treated_at"] is None
        technician = fetch_inspector(ctx["inspector_b"]["id"])
        assert technician["status"] == "EXPIRED"
        assert technician["certification_level"] == "DECON_CERTIFIED"
        assert_instant_equals(
            technician["certification_expires_at"], "2027-08-01T00:00:00Z",
            "certification_expires_at",
        )

    def test_the_administrative_renewal_re_stamps_the_expiry_and_unblocks_the_bay(self):
        """Reinstatement moves the boundary a year out and the same treatment passes.

        PRD: "The administrative route, `EXPIRED → ACTIVE` by a `ProgramAdmin`,
        requires only that the inspector's `certification_level` is not `TRAINEE` —
        it carries no requirement that the certification still be unexpired, since
        the entire point of the renewal is that it has already lapsed — and it
        re-stamps `certification_expires_at` at the current logical time plus 8,760
        hours, re-runs the station staffing cascade, and advances `version` by 1."

        Design: Corner/endpoints/conditional_action_expired_certification_blocks_treatment_without_mutating_on_clock_advance
        """
        ctx, first, second = _two_orders_and_a_technician_about_to_lapse()
        set_clock("2027-07-31T23:59:59Z")
        validate_success(_treat(first["id"], ctx["inspector_b"]["id"]), 200)
        set_clock("2027-08-01T00:00:00Z")
        validate_error(
            _treat(second["id"], ctx["inspector_b"]["id"]),
            ApiErrorId.ERR_INSPECTOR_NOT_ACTIVE, 409,
        )

        renewed = move_inspector(ctx["inspector_b"]["id"], "ACTIVE")

        assert renewed["status"] == "ACTIVE"
        assert_instant_equals(
            renewed["certification_expires_at"], "2028-07-31T00:00:00Z",
            "certification_expires_at",
        )
        order = validate_success(_treat(second["id"], ctx["inspector_b"]["id"]), 200)
        assert order["status"] == "TREATED"
        assert order["treated_by_inspector_id"] == ctx["inspector_b"]["id"]
