"""Error and RBAC corners: the remaining 404 codes, 401 triggers and the role matrix."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PROGRAM_ADMIN,
    STATE_DATA_STEWARD,
    TRAINING_OFFICER,
    ApiErrorId,
    acknowledgement_payload,
    api_client,
    campaign_status_payload,
    clock_payload,
    create_water_body,
    draft_detection_report,
    dry_verification_payload,
    fetch_detection_report,
    fetch_inspector,
    fetch_station,
    fetch_water_body,
    inspector_payload,
    make_decon_technician_headers,
    make_enforcement_officer_headers,
    make_inspector_headers,
    make_program_admin_headers,
    make_release_verifier_headers,
    make_state_data_steward_headers,
    make_training_officer_headers,
    quarantine_order_payload,
    raw_headers,
    register_watercraft,
    reciprocity_agreement_payload,
    set_clock,
    setup_inspection,
    setup_program,
    station_hours_payload,
    station_payload,
    station_status_payload,
    submit_detection_report,
    training_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
    water_body_patch_payload,
    water_body_payload,
    watercraft_payload,
)

CLOCK = "2026-08-01T00:00:00Z"
ARRIVAL = "2026-08-05T09:00:00Z"


class TestTheFourRemainingNotFoundCodes:
    """Each workflow entity answers with its own 404, and existence beats state."""

    def test_each_missing_workflow_entity_returns_its_own_not_found_code(self):
        """Four reads on an empty store give four distinct 404 identifiers.

        PRD: "The identifier reported names the *kind* of thing that was missing:
        `ERR_WATER_BODY_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_INSPECTOR_NOT_FOUND`, `ERR_WATERCRAFT_NOT_FOUND`,
        `ERR_INSPECTION_RECORD_NOT_FOUND`, `ERR_DECON_ORDER_NOT_FOUND`,
        `ERR_QUARANTINE_ORDER_NOT_FOUND`, `ERR_DETECTION_REPORT_NOT_FOUND`,
        `ERR_CAMPAIGN_NOT_FOUND` and `ERR_RECIPROCITY_AGREEMENT_NOT_FOUND` — each
        HTTP 404."

        Design: Corner/errors/triggerable_the_four_remaining_not_found_codes
        """
        set_clock(CLOCK)

        error = validate_error(
            api_client.get_decon_order(NON_EXISTENT_UUID, PROGRAM_ADMIN),
            ApiErrorId.ERR_DECON_ORDER_NOT_FOUND, 404,
        )
        assert "id" not in error
        assert "status" not in error

        validate_error(
            api_client.get_quarantine_order(NON_EXISTENT_UUID, PROGRAM_ADMIN),
            ApiErrorId.ERR_QUARANTINE_ORDER_NOT_FOUND, 404,
        )
        validate_error(
            api_client.get_detection_report(NON_EXISTENT_UUID, PROGRAM_ADMIN),
            ApiErrorId.ERR_DETECTION_REPORT_NOT_FOUND, 404,
        )
        validate_error(
            api_client.get_campaign(NON_EXISTENT_UUID, PROGRAM_ADMIN),
            ApiErrorId.ERR_CAMPAIGN_NOT_FOUND, 404,
        )

    def test_an_action_on_a_missing_id_is_a_404_rather_than_a_state_conflict(self):
        """Path existence is settled before any transition precondition runs.

        PRD: "7. Every resource named in the path exists, resolved left to right —
        otherwise the matching 404 from the family listed in §2.6."

        Design: Corner/errors/triggerable_the_four_remaining_not_found_codes
        """
        ctx = setup_program(clock=CLOCK)

        validate_error(
            api_client.set_campaign_status(
                NON_EXISTENT_UUID, campaign_status_payload("RUNNING"), PROGRAM_ADMIN
            ),
            ApiErrorId.ERR_CAMPAIGN_NOT_FOUND, 404,
        )
        # The acting verifier must resolve to a real inspector row: §2.11 settles
        # the entity-backed X-User-ID at step 4, ahead of path existence at step 7,
        # so an unresolvable id would answer ERR_INSPECTOR_NOT_FOUND instead.
        validate_error(
            api_client.verify_decon_dry_time(
                NON_EXISTENT_UUID, dry_verification_payload("VERIFIED"),
                make_release_verifier_headers(ctx["inspector_c"]["id"]),
            ),
            ApiErrorId.ERR_DECON_ORDER_NOT_FOUND, 404,
        )

    def test_the_four_collections_really_are_empty(self):
        """Every listing reports zero rows, so the 404s were the not-found path.

        PRD: "`total_count` (the number of rows matching the filter before
        pagination is applied)"

        Design: Corner/errors/triggerable_the_four_remaining_not_found_codes
        """
        set_clock(CLOCK)

        for response in (
            api_client.list_decon_orders(PROGRAM_ADMIN),
            api_client.list_quarantine_orders(PROGRAM_ADMIN),
            api_client.list_detection_reports(PROGRAM_ADMIN),
            api_client.list_campaigns(PROGRAM_ADMIN),
        ):
            rows, meta = validate_paginated(response)
            assert rows == []
            assert meta["total_count"] == 0


def _one_readable_water_body():
    """A water body that any properly authenticated caller could read."""
    set_clock(CLOCK)
    return create_water_body(name="Flathead Lake", risk_tier="HIGH")


class TestUnauthenticatedCoversEveryHeaderDefect:
    """The 401 covers absent, empty and undeclared identity headers alike."""

    def test_a_request_with_no_role_header_at_all_is_a_401(self):
        """Priority 1 fires before anything else the request would touch.

        PRD: "1. Both authentication headers are present and non-empty,
        whitespace-only counting as absent — otherwise `ERR_UNAUTHENTICATED` (401).
        Applies to every operation."

        Design: Corner/errors/triggerable_unauthenticated_covers_missing_empty_and_unknown_role
        """
        water_body = _one_readable_water_body()

        response = api_client.get_water_body(
            water_body["id"], raw_headers("admin-1", None)
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_an_empty_role_and_an_undeclared_role_are_both_401_not_403(self):
        """403 is reserved for a real role outside its matrix row.

        PRD: "2. `X-User-Role` names one of the seven declared roles — otherwise
        `ERR_UNAUTHENTICATED` (401). Applies to every operation."

        Design: Corner/errors/triggerable_unauthenticated_covers_missing_empty_and_unknown_role
        """
        water_body = _one_readable_water_body()

        validate_error(
            api_client.get_water_body(water_body["id"], raw_headers("admin-1", "")),
            ApiErrorId.ERR_UNAUTHENTICATED, 401,
        )
        validate_error(
            api_client.get_water_body(water_body["id"],
                                      raw_headers("admin-1", "Auditor")),
            ApiErrorId.ERR_UNAUTHENTICATED, 401,
        )

    def test_the_identity_header_is_mandatory_even_for_an_opaque_role(self):
        """A missing X-User-ID is a 401, and supplying both reads the row.

        PRD: "The remaining four roles are opaque. When `X-User-Role` is
        `ProgramAdmin`, `EnforcementOfficer`, `StateDataSteward`, or
        `TrainingOfficer`, `X-User-ID` is an opaque operator identifier not tied to
        any persisted entity; the server may record it for audit purposes but never
        compares it to any entity's `id` and never resolves it to a row."

        Design: Corner/errors/triggerable_unauthenticated_covers_missing_empty_and_unknown_role
        """
        water_body = _one_readable_water_body()

        validate_error(
            api_client.get_water_body(water_body["id"],
                                      raw_headers(None, "ProgramAdmin")),
            ApiErrorId.ERR_UNAUTHENTICATED, 401,
        )
        validate_error(
            api_client.get_water_body(water_body["id"], raw_headers("", "ProgramAdmin")),
            ApiErrorId.ERR_UNAUTHENTICATED, 401,
        )

        readable = validate_success(
            api_client.get_water_body(water_body["id"],
                                      raw_headers("clerk-42", "ProgramAdmin")),
            200,
        )
        assert readable["id"] == water_body["id"]


def _program_admin_builds_the_program(admin):
    """Run every ProgramAdmin-exclusive write with one opaque operator identity."""
    clock = validate_success(api_client.set_clock(clock_payload(CLOCK), admin), 200)
    water_body = validate_success(
        api_client.create_water_body(
            water_body_payload(name="Flathead Lake", risk_tier="HIGH"), admin
        ),
        201,
    )
    patched = validate_success(
        api_client.patch_water_body(
            water_body["id"], water_body_patch_payload(risk_tier="MODERATE"), admin
        ),
        200,
    )
    station = validate_success(
        api_client.create_station(
            station_payload(name="Polson Access", water_body_id=water_body["id"],
                            mandatory_inspection=True, seal_stock_initial_count=5),
            admin,
        ),
        201,
    )
    hours = validate_success(
        api_client.create_station_hours(
            station["id"],
            station_hours_payload(opens_at="2026-07-01T00:00:00Z",
                                  closes_at="2026-10-01T00:00:00Z",
                                  staffing_level="SINGLE"),
            admin,
        ),
        201,
    )
    opened = validate_success(
        api_client.set_station_status(
            station["id"], station_status_payload("OPEN"), admin
        ),
        200,
    )
    inspector = validate_success(
        api_client.create_inspector(
            inspector_payload(station["id"], full_name="Ada Field"), admin
        ),
        201,
    )
    return {"clock": clock, "water_body": water_body, "patched": patched,
            "station": station, "hours": hours, "opened": opened,
            "inspector": inspector}


class TestProgramAdminSitesAndOperatesTheProgram:
    """Every operation the matrix reserves to the program office succeeds for it."""

    def test_the_eight_exclusive_operations_all_succeed_for_the_program_office(self):
        """Clock, registry, PATCH, siting, hours, transition, enrollment, agreement.

        PRD: "A `ProgramAdmin` is the state program office. It builds the inventory
        of water bodies, sites and operates stations, enrolls inspectors, negotiates
        interstate reciprocity, plans and launches education campaigns, and controls
        the logical clock."

        Design: Corner/rbac/exclusive_operations_program_admin_sites_and_operates_the_program
        """
        admin = make_program_admin_headers("audit-clerk-9")
        built = _program_admin_builds_the_program(admin)

        agreement = validate_success(
            api_client.create_reciprocity_agreement(
                reciprocity_agreement_payload(partner_state_code="WY",
                                              accepted_seal_prefix="WY-"),
                admin,
            ),
            201,
        )

        assert agreement["partner_state_code"] == "WY"
        assert built["clock"]["current_utc"] is not None
        assert built["hours"]["station_id"] == built["station"]["id"]
        assert built["inspector"]["home_station_id"] == built["station"]["id"]

    def test_the_exclusive_transitions_really_executed_their_side_effects(self):
        """The station opened with its seal shelf stocked and the PATCH landed.

        PRD: "`PLANNED → OPEN` opens the station for the season and is permitted
        only when at least one hours window has already been declared for it; an
        attempt to open a station with no declared hours is rejected with
        `ERR_INVALID_STATION_STATE`."

        Design: Corner/rbac/exclusive_operations_program_admin_sites_and_operates_the_program
        """
        admin = make_program_admin_headers("audit-clerk-9")
        built = _program_admin_builds_the_program(admin)

        station = fetch_station(built["station"]["id"])
        assert station["status"] == "OPEN"
        assert station["seal_stock_count"] == 5
        assert fetch_water_body(built["water_body"]["id"])["risk_tier"] == "MODERATE"


class TestEachRoleIsBarredFromTheOthersExclusiveOperations:
    """The role check sits ahead of every body, foreign-key and state check."""

    def test_an_inspector_may_not_raise_its_own_certification(self):
        """Logging training is the TrainingOfficer's alone, and nothing is written.

        PRD: "3. The named role appears among the roles permitted on the addressed
        operation — otherwise `ERR_UNAUTHORIZED` (403). Applies to every operation."

        Design: Corner/rbac/cross_role_denied_each_role_is_barred_from_the_others_exclusive_operations
        """
        ctx = setup_program(mandatory_inspection=True, inspector_a_hours=8)
        inspector_id = ctx["inspector_a"]["id"]

        response = api_client.create_training_record(
            inspector_id, training_record_payload(8, True, module_code="AIS-102"),
            make_inspector_headers(inspector_id),
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        inspector = fetch_inspector(inspector_id)
        assert float(inspector["training_hours_total"]) == 8.00
        assert inspector["certification_level"] == "LEVEL_1"

    def test_the_role_check_precedes_the_required_field_check(self):
        """A TrainingOfficer opening an inspection with no body at all is a 403.

        PRD: "6. On every creating or modifying operation, the body is structurally
        sound — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/rbac/cross_role_denied_each_role_is_barred_from_the_others_exclusive_operations
        """
        ctx = setup_program(mandatory_inspection=True)

        validate_error(
            api_client.create_inspection_record({}, TRAINING_OFFICER),
            ApiErrorId.ERR_UNAUTHORIZED, 403,
        )
        validate_error(
            api_client.create_water_body(
                water_body_payload(name="Rogue Lake"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED, 403,
        )

    def test_there_is_no_hierarchical_override_in_the_matrix(self):
        """The program office may not seal a vessel and a steward may not negotiate.

        PRD: "An `Inspector` is a field inspector at a station: opening inspections,
        performing risk screening including reciprocity seal checks, dispositioning
        inspections, ordering decontamination, sealing vessels under quarantine,
        requesting their release, and filing detection reports."

        Design: Corner/rbac/cross_role_denied_each_role_is_barred_from_the_others_exclusive_operations
        """
        setup_program(mandatory_inspection=True)

        validate_error(
            api_client.create_reciprocity_agreement(
                reciprocity_agreement_payload(partner_state_code="WY",
                                              accepted_seal_prefix="WY-"),
                STATE_DATA_STEWARD,
            ),
            ApiErrorId.ERR_UNAUTHORIZED, 403,
        )
        validate_error(
            api_client.create_quarantine_order(
                quarantine_order_payload(NON_EXISTENT_UUID, "MT-SEAL-9999"),
                PROGRAM_ADMIN,
            ),
            ApiErrorId.ERR_UNAUTHORIZED, 403,
        )


class TestWatercraftRegistrationAndReadsAreOpenToBothIdentities:
    """The one shared write and the read surface both roles reach."""

    def test_the_shared_write_is_open_to_the_entity_backed_inspector(self):
        """An Inspector registers a vessel next to one the program office created.

        PRD: "| POST | `/watercraft` | Register a vessel in the watercraft registry
        with its declared last water body and removal time. | `ProgramAdmin`,
        `Inspector` |"

        Design: Corner/rbac/shared_operations_watercraft_registration_and_reads_open_to_both_identities
        """
        ctx = setup_program(mandatory_inspection=True)
        admin_vessel = register_watercraft(registration_number="MT-7001")

        vessel = validate_success(
            api_client.create_watercraft(
                watercraft_payload(registration_number="MT-7002"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            201,
        )

        assert vessel["registration_number"] == "MT-7002"
        assert vessel["id"] != admin_vessel["id"]
        assert vessel["compliance_strikes"] == 0
        assert vessel["watchlist_status"] == "CLEAR"

    def test_the_shared_registry_is_not_scoped_to_its_creator(self):
        """Both vessels are visible to the program office and to the inspector.

        PRD: "| GET | `/watercraft` | List vessels, filterable by declared last
        water body, watchlist status and vessel type. | All seven roles |"

        Design: Corner/rbac/shared_operations_watercraft_registration_and_reads_open_to_both_identities
        """
        ctx = setup_program(mandatory_inspection=True)
        inspector = make_inspector_headers(ctx["inspector_a"]["id"])
        register_watercraft(registration_number="MT-7001")
        validate_success(
            api_client.create_watercraft(
                watercraft_payload(registration_number="MT-7002"), inspector
            ),
            201,
        )

        admin_rows, admin_meta = validate_paginated(
            api_client.list_watercraft(PROGRAM_ADMIN)
        )
        inspector_rows, inspector_meta = validate_paginated(
            api_client.list_watercraft(inspector)
        )

        assert admin_meta["total_count"] == 2
        assert inspector_meta["total_count"] == 2
        assert {row["registration_number"] for row in admin_rows} == {"MT-7001", "MT-7002"}
        assert {row["id"] for row in inspector_rows} == {row["id"] for row in admin_rows}

    def test_an_entity_backed_role_must_resolve_even_on_a_shared_read(self):
        """All seven roles read the vessel; an unresolvable technician gets 404.

        PRD: "On any operation whose permitted roles include `Inspector`,
        `DeconTechnician`, or `ReleaseVerifier`, an `X-User-ID` that resolves to no
        `Inspector` row is rejected with `ERR_INSPECTOR_NOT_FOUND` (HTTP 404)."

        Design: Corner/rbac/shared_operations_watercraft_registration_and_reads_open_to_both_identities
        """
        ctx = setup_program(mandatory_inspection=True)
        inspector_id = ctx["inspector_a"]["id"]
        vessel = validate_success(
            api_client.create_watercraft(
                watercraft_payload(registration_number="MT-7002"),
                make_inspector_headers(inspector_id),
            ),
            201,
        )
        readers = [
            PROGRAM_ADMIN,
            make_inspector_headers(inspector_id),
            make_decon_technician_headers(inspector_id),
            make_release_verifier_headers(inspector_id),
            make_enforcement_officer_headers("eo-9"),
            make_state_data_steward_headers("sds-9"),
            make_training_officer_headers("to-9"),
        ]

        for headers in readers:
            row = validate_success(api_client.get_watercraft(vessel["id"], headers), 200)
            assert row["id"] == vessel["id"]

        validate_error(
            api_client.get_watercraft(
                vessel["id"], make_decon_technician_headers(NON_EXISTENT_UUID)
            ),
            ApiErrorId.ERR_INSPECTOR_NOT_FOUND, 404,
        )


def _submitted_report_filed_by_inspector_a():
    """A SUBMITTED LIVE_ORGANISM report filed by insp_a on a vessel off Swan Lake."""
    ctx = setup_program(clock=CLOCK, mandatory_inspection=True)
    prior = create_water_body(name="Swan Lake", risk_tier="LOW")
    inspection = setup_inspection(
        ctx, arrived_at=ARRIVAL, vessel_type="OPEN_HULL",
        last_removed_at="2026-08-04T09:00:00Z",
        last_water_body_id=prior["id"], prior_water_body_id=prior["id"],
        standing_water_ml=0,
    )
    report = draft_detection_report(
        inspection["record"]["id"], ctx["inspector_a"]["id"],
        species_code="DREISSENA_POLYMORPHA", detection_class="LIVE_ORGANISM",
    )
    submitted = submit_detection_report(report["id"], ctx["inspector_a"]["id"])
    return {"inspector_id": ctx["inspector_a"]["id"], "prior": prior,
            "record": inspection["record"], "report": submitted}


class TestTheReportFilerCannotAcknowledgeItsOwnReport:
    """The steward role clears priority 2 and is still refused on identity."""

    def test_the_filing_identity_is_refused_with_the_segregation_error(self):
        """Acting as StateDataSteward under the reporting inspector's id is a 403.

        PRD: "The report must be in `SUBMITTED`, or the call is
        `ERR_REPORT_INVALID_STATE`, and the acknowledging steward may not be the
        inspector who filed the report — a collision is
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_report_filer_cannot_acknowledge_its_own_report
        """
        ctx = _submitted_report_filed_by_inspector_a()
        assert ctx["report"]["status"] == "SUBMITTED"
        assert ctx["report"]["reported_by_inspector_id"] == ctx["inspector_id"]

        response = api_client.acknowledge_detection_report(
            ctx["report"]["id"],
            acknowledgement_payload("ACCEPTED", state_db_ack_id="AIS-2026-000441"),
            make_state_data_steward_headers(ctx["inspector_id"]),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        report = fetch_detection_report(ctx["report"]["id"])
        assert report["status"] == "SUBMITTED"
        assert report["state_db_ack_id"] is None

    def test_the_refused_acknowledgement_fires_none_of_the_cascade_hops(self):
        """The prior water body's detection counters are untouched by the 403.

        PRD: "In the second hop, the water body's `detection_count` is incremented
        by 1, and its `live_detection_count` is incremented by 1 as well when the
        report's `detection_class` is `LIVE_ORGANISM`; the escalation rule then runs
        **on the counters as they stand after those increments**."

        Design: Corner/rbac/segregation_of_duties_report_filer_cannot_acknowledge_its_own_report
        """
        ctx = _submitted_report_filed_by_inspector_a()

        api_client.acknowledge_detection_report(
            ctx["report"]["id"],
            acknowledgement_payload("ACCEPTED", state_db_ack_id="AIS-2026-000441"),
            make_state_data_steward_headers(ctx["inspector_id"]),
        )

        prior = fetch_water_body(ctx["prior"]["id"])
        assert prior["detection_count"] == 0
        assert prior["live_detection_count"] == 0
        assert prior["infestation_status"] == "CLEAN"
        assert prior["risk_tier"] == "LOW"

    def test_a_different_steward_identity_accepts_the_identical_body(self):
        """steward-77 sends the same payload and the four-hop cascade runs.

        PRD: "a `StateDataSteward` acknowledging a detection report is subject to
        the segregation-of-duties comparison only in the sense that its opaque
        identifier must differ from the inspector identifier already stored on the
        report."  PRD: "Otherwise, when `detection_count` has reached 1 and the
        water body's `infestation_status` is still `CLEAN`, `infestation_status` is
        set to `SUSPECT` and `risk_tier` is left as it was."

        Design: Corner/rbac/segregation_of_duties_report_filer_cannot_acknowledge_its_own_report
        """
        ctx = _submitted_report_filed_by_inspector_a()

        report = validate_success(
            api_client.acknowledge_detection_report(
                ctx["report"]["id"],
                acknowledgement_payload("ACCEPTED", state_db_ack_id="AIS-2026-000441"),
                make_state_data_steward_headers("steward-77"),
            ),
            200,
        )

        assert report["status"] == "ACCEPTED"
        assert report["state_db_ack_id"] == "AIS-2026-000441"
        prior = fetch_water_body(ctx["prior"]["id"])
        assert prior["detection_count"] == 1
        assert prior["live_detection_count"] == 1
        assert prior["infestation_status"] == "SUSPECT"
        assert prior["risk_tier"] == "LOW"
