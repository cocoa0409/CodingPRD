"""Record shapes: declared fields, server-owned defaults, reads and listings."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_applicant,
    assert_application,
    assert_audit_fields,
    assert_health_service_area,
    assert_hearing_room,
    assert_instant_equals,
    assert_public_comment,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import DEFAULT_CLOCK, UNKNOWN_APPLICANT_ID, UNKNOWN_HSA_ID
from test_helpers.factories import (
    applicant_payload,
    health_service_area_payload,
    hearing_room_payload,
    letter_of_intent_payload,
    public_comment_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    INTAKE,
    PUBLIC,
    create_application,
    file_letter_of_intent,
    refresh_letter_of_intent,
    seed_applicant,
    seed_application_submitted,
    seed_batching_cycle,
    seed_second_applicant,
    set_clock,
)
from test_helpers.test_users import make_applicant_headers


class TestReferenceDataCreation:
    def test_planning_area_creation_returns_its_fields_with_zeroed_counters(self):
        """The two server-owned ledgers start at 0 and status defaults to ACTIVE.

        PRD §3.1: "A **planning area** (a health service area) is registered with
        a `code`, a human-readable `name` and a `population_projection`."
        PRD §3.1: "Registration may optionally state `existing_licensed_beds`, the
        beds or units already licensed in the area for the service type in scope,
        which defaults to 0 and may never be negative, and may optionally state
        `status`, which is either `ACTIVE` or `RETIRED` and defaults to `ACTIVE`;
        only an `ACTIVE` area is meant to host new batching cycles."
        PRD §3.1: "Two derived quantities are always initialised to 0 at
        registration and are thereafter maintained by the server alone:
        `approved_unimplemented_beds` and `capital_authorization_committed_cents`,
        whose bookkeeping §2.10 defines."

        Design: Corner/entities/health_service_area_creation_returns_declared_fields_with_zeroed_counters
        """
        set_clock(DEFAULT_CLOCK)

        hsa = get_success_data(
            api_client.create_health_service_area(
                health_service_area_payload(), ADMIN
            ),
            201,
        )

        assert_health_service_area(hsa)
        assert hsa["code"] == "HSA-NORTH"
        assert hsa["name"] == "North Planning Area"
        assert hsa["population_projection"] == 54750
        assert hsa["existing_licensed_beds"] == 70
        assert hsa["approved_unimplemented_beds"] == 0
        assert hsa["capital_authorization_committed_cents"] == 0
        assert hsa["status"] == "ACTIVE"
        assert_audit_fields(hsa, expected_version=1)
        assert_instant_equals(hsa["created_at"], DEFAULT_CLOCK)

    def test_hearing_room_defaults_the_buffer_and_the_status(self):
        """Omitting both optional inputs yields 60 minutes and AVAILABLE, not null.

        PRD §3.1: "A **hearing room** is registered with a `name` that is unique
        across all rooms, a `seating_capacity` of at least 1 seat available to the
        public, and two optional properties: `setup_buffer_minutes`, the minutes
        of exclusive room occupancy required *before* a hearing's
        `scheduled_start_at` for the setup and recording rig, which defaults to 60
        minutes and may not be negative; and `status`, either `AVAILABLE` or
        `OUT_OF_SERVICE`, defaulting to `AVAILABLE`."

        Design: Corner/entities/hearing_room_defaults_buffer_to_sixty_minutes_and_status_available
        """
        set_clock(DEFAULT_CLOCK)

        room = get_success_data(
            api_client.create_hearing_room(
                hearing_room_payload(name="BOARD-A", seating_capacity=120), ADMIN
            ),
            201,
        )

        assert_hearing_room(room)
        assert room["setup_buffer_minutes"] == 60
        assert room["status"] == "AVAILABLE"
        assert room["seating_capacity"] == 120
        assert room["version"] == 1

    def test_planning_area_creation_without_a_population_projection_is_rejected(self):
        """The demand driver has no default, so its absence is a shape defect.

        PRD §3.1: "The `population_projection` is the projected resident
        population of the area at the planning horizon and must be at least 1,
        because it is the demand driver of the need methodology."
        PRD §2.8: "**Body shape.** Every required input field is present, every
        enum value lies inside its declared set, integers constrained to be
        non-negative are non-negative, ISO 8601 instants parse, arrays required to
        be non-empty are non-empty, each of the five criterion scores lies between
        0 and 100 inclusive, and a hearing's `scheduled_end_at` is strictly after
        its `scheduled_start_at` — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/health_service_area_creation_without_population_projection_returns_invalid_request
        """
        set_clock(DEFAULT_CLOCK)

        response = api_client.create_health_service_area(
            {"code": "HSA-NORTH", "name": "North Planning Area"}, ADMIN
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        retry = get_success_data(
            api_client.create_health_service_area(
                health_service_area_payload(), ADMIN
            ),
            201,
        )
        assert retry["code"] == "HSA-NORTH"

    def test_applicant_creation_with_an_organization_type_outside_the_set(self):
        """CLINIC is not one of the four declared organisation types.

        PRD §3.1: "Finally, an **applicant** organisation is registered with a
        `legal_name` unique across all applicants, an `organization_type` of
        `HOSPITAL`, `NURSING_FACILITY`, `PHYSICIAN_GROUP` or `OTHER`, and a
        `contact_email` as the address of record."
        PRD §2.8: "**Body shape.** Every required input field is present, every
        enum value lies inside its declared set, integers constrained to be
        non-negative are non-negative, ISO 8601 instants parse, arrays required to
        be non-empty are non-empty, each of the five criterion scores lies between
        0 and 100 inclusive, and a hearing's `scheduled_end_at` is strictly after
        its `scheduled_start_at` — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/applicant_creation_with_unknown_organization_type_returns_invalid_request
        """
        set_clock(DEFAULT_CLOCK)

        response = api_client.create_applicant(
            applicant_payload(organization_type="CLINIC"), ADMIN
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        retry = get_success_data(
            api_client.create_applicant(applicant_payload(), ADMIN), 201
        )
        assert retry["organization_type"] == "HOSPITAL"


class TestApplicantReads:
    def test_reading_an_applicant_exposes_the_compliance_defaults(self):
        """A read returns the stored standing and strike count, not a recomputation.

        PRD §3.1: "`standing` starts at `GOOD` and may become `RESTRICTED` or
        `BARRED`; a `RESTRICTED` applicant is blocked from new letters of intent
        and new applications, while a `BARRED` applicant is blocked from every
        filing."
        PRD §3.1: "Reading an applicant exposes both, so staff can see why a
        filing was refused."

        Design: Corner/entities/applicant_get_returns_stored_row_with_standing_and_strike_defaults
        """
        set_clock(DEFAULT_CLOCK)
        applicant = seed_applicant()

        read = get_success_data(api_client.get_applicant(applicant["id"], INTAKE))

        assert_applicant(read)
        assert read["standing"] == "GOOD"
        assert read["compliance_strike_count"] == 0
        assert read["legal_name"] == "Northside Hospital"
        assert read["organization_type"] == "HOSPITAL"
        assert read["version"] == 1

    def test_reading_an_unknown_applicant_id_is_a_typed_not_found(self):
        """A valid but unpersisted id returns 404, never an empty 200.

        PRD §2.8: "**Path-parameter existence**, resolved left to right along the
        path: a cycle identifier that resolves to nothing yields
        `ERR_CYCLE_NOT_FOUND`, a letter-of-intent identifier `ERR_LOI_NOT_FOUND`,
        an application identifier `ERR_APPLICATION_NOT_FOUND`, a
        completeness-review identifier `ERR_COMPLETENESS_REVIEW_NOT_FOUND`, an
        intervention identifier `ERR_INTERVENTION_NOT_FOUND`, a hearing identifier
        `ERR_HEARING_NOT_FOUND`, a certificate identifier
        `ERR_CERTIFICATE_NOT_FOUND`, an appeal identifier `ERR_APPEAL_NOT_FOUND`, a
        planning-area identifier `ERR_HSA_NOT_FOUND`, a formula identifier
        `ERR_FORMULA_NOT_FOUND` and an applicant identifier
        `ERR_APPLICANT_NOT_FOUND` — all at 404."

        Design: Corner/entities/get_applicant_with_unknown_id_returns_applicant_not_found
        """
        applicant = seed_applicant()

        response = api_client.get_applicant(UNKNOWN_APPLICANT_ID, INTAKE)

        body = validate_error(response, ApiErrorId.ERR_APPLICANT_NOT_FOUND, 404)
        assert body["message"].strip()
        assert api_client.get_applicant(applicant["id"], INTAKE).status_code == 200


class TestCollectionListing:
    def test_applications_paginate_with_a_total_count_and_a_has_more_flag(self):
        """limit 1 walks a two-row collection in created_at order.

        PRD §2.3: "`limit` caps the number of rows returned; when it is omitted it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted
        value is 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope; `total_count` counts
        the rows matching the filters before pagination is applied, and `has_more`
        states whether further rows remain beyond the returned page."

        Design: Corner/entities/applications_list_paginates_with_total_count_and_has_more
        """
        world = seed_batching_cycle()
        applicant_a = seed_applicant()
        applicant_b = seed_second_applicant()
        world["applicant"] = applicant_a
        loi_a = file_letter_of_intent(world, applicant_a)
        application_a = create_application(world, applicant_a, loi_a)
        loi_b = file_letter_of_intent(
            world,
            applicant_b,
            project_description="10-bed acute care expansion",
            capital_cost_cents=700000000,
            bed_delta=10,
        )
        application_b = create_application(
            world,
            applicant_b,
            loi_b,
            requested_bed_count=10,
            projected_capital_cost_cents=700000000,
            narrative="Lakeview 10-bed acute care application",
            partial_award_acceptable=True,
        )

        first_rows, first_meta = validate_paginated(
            api_client.list_applications(
                ADMIN,
                params={
                    "batching_cycle_id": world["cycle"]["id"],
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        second_rows, second_meta = validate_paginated(
            api_client.list_applications(
                ADMIN,
                params={
                    "batching_cycle_id": world["cycle"]["id"],
                    "limit": 1,
                    "offset": 1,
                },
            )
        )

        assert first_meta["total_count"] == 2
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert [row["id"] for row in first_rows] == [application_a["id"]]

        assert second_meta["total_count"] == 2
        assert second_meta["offset"] == 1
        assert second_meta["has_more"] is False
        assert [row["id"] for row in second_rows] == [application_b["id"]]


class TestImmutableAndDerivedFields:
    def test_a_public_comment_carries_no_version_and_no_updated_at(self):
        """The one record type that is append-only reports only id and created_at.

        PRD §2.5: "The one exception is `PublicComment`. A comment is append-only:
        once entered into the public record it is never modified, so a comment row
        carries only `id` and `created_at`. Both `updated_at` and `version` are
        absent from a `PublicComment` entirely."
        PRD §3.6: "The server stamps `commenter_user_id` from the caller's
        `X-User-ID` and `filed_at` from the logical clock."

        Design: Corner/entities/public_comment_is_immutable_row_without_version_or_update_path
        """
        world = seed_application_submitted()

        comment = get_success_data(
            api_client.create_public_comment(
                world["application"]["id"],
                public_comment_payload(
                    commenter_display_name="Jane Resident",
                    stance="OPPOSE",
                    body="The community already has sufficient acute care capacity.",
                ),
                PUBLIC,
            ),
            201,
        )

        assert_public_comment(comment)
        assert comment["commenter_user_id"] == "public-1"
        assert comment["stance"] == "OPPOSE"
        assert_instant_equals(comment["filed_at"], DEFAULT_CLOCK)
        assert "version" not in comment
        assert "updated_at" not in comment

        rows, meta = validate_paginated(
            api_client.list_public_comments(world["application"]["id"], PUBLIC)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == comment["id"]
        assert "version" not in rows[0]

    def test_a_new_application_reports_every_decision_field_at_its_zero_state(self):
        """Scoring and decision fields are empty and the parents are copied over.

        PRD §3.4: "The server derives the rest. `applicant_id` and
        `batching_cycle_id` are copied from the letter of intent and are never read
        from the request body, so an applicant cannot smuggle its filing into a
        different cycle or attribute it to another organisation."
        PRD §3.4: "The letter's own `status` moves to `CONVERTED`, and the new
        application's `status` is initialised to `DRAFT`."
        PRD §3.4: "Alongside it the record carries the decision-side fields that
        stay empty until the relevant stage arrives: `comparative_score`, a number
        with 2 decimal places that is null until at least one `ACTIVE` score sheet
        exists; `score_sheet_count`, an integer that starts at 0;
        `allocated_bed_count`, an integer that starts at 0, never goes negative,
        and is 0 unless the status is `APPROVED` or `APPROVED_WITH_CONDITIONS`;
        `denial_reason`, which is null unless the status is `DENIED` and otherwise
        holds `INSUFFICIENT_NEED`, `FAILED_CRITERIA` or `APPEAL_REVERSED` (of
        these, `INSUFFICIENT_NEED` is written by the allocation waterfall and
        `APPEAL_REVERSED` by a reversal cascade, while `FAILED_CRITERIA` is
        reserved for a criteria-based denial that no operation in this
        specification writes); `completeness_round_count`, an integer starting at 0
        that counts deficiency rounds; `decision_at`, the logical-clock instant of
        the comparative decision, null before it; and `appeal_window_closes_at`,
        which is `decision_at` plus 30 days and is simultaneously the last instant
        an appeal may be filed and the earliest boundary past which a certificate
        may issue."
        PRD §3.4: "and optionally `partial_award_acceptable`, a boolean that
        defaults to false and tells the allocation waterfall whether the applicant
        would rather take fewer beds than requested than be denied outright."

        Design: Corner/entities/application_creation_leaves_scoring_and_decision_fields_at_declared_zero_state
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()
        world["applicant"] = applicant
        loi = file_letter_of_intent(world, applicant)

        application = get_success_data(
            api_client.create_application(
                {
                    "loi_id": loi["id"],
                    "requested_bed_count": 12,
                    "projected_capital_cost_cents": 800000000,
                    "narrative": "Northside 12-bed acute care application",
                },
                make_applicant_headers(applicant["id"]),
            ),
            201,
        )

        assert_application(application)
        assert application["status"] == "DRAFT"
        assert application["partial_award_acceptable"] is False
        assert application["applicant_id"] == applicant["id"]
        assert application["batching_cycle_id"] == world["cycle"]["id"]
        assert application["comparative_score"] is None
        assert application["score_sheet_count"] == 0
        assert application["allocated_bed_count"] == 0
        assert application["completeness_round_count"] == 0
        assert application["denial_reason"] is None
        assert application["decision_at"] is None
        assert application["appeal_window_closes_at"] is None
        assert refresh_letter_of_intent(loi["id"])["status"] == "CONVERTED"


class TestBodyForeignKeyResolution:
    def test_a_letter_naming_an_unknown_planning_area_is_a_typed_not_found(self):
        """The applicant resolves; the planning area does not, and it names itself.

        PRD §2.8: "**Body foreign-key existence**, resolved in the order the
        fields appear in the endpoint's input list: `applicant_id` yields
        `ERR_APPLICANT_NOT_FOUND`, `hsa_id` yields `ERR_HSA_NOT_FOUND`,
        `formula_id` yields `ERR_FORMULA_NOT_FOUND`, `batching_cycle_id` yields
        `ERR_CYCLE_NOT_FOUND`, `loi_id` yields `ERR_LOI_NOT_FOUND`,
        `application_id` yields `ERR_APPLICATION_NOT_FOUND`,
        `affected_party_applicant_id` yields `ERR_APPLICANT_NOT_FOUND`,
        `hearing_room_id` yields `ERR_HEARING_ROOM_NOT_FOUND` and
        `certificate_id` yields `ERR_CERTIFICATE_NOT_FOUND` — all at 404."

        Design: Corner/entities/letter_of_intent_with_unknown_hsa_id_returns_hsa_not_found
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()

        response = api_client.create_letter_of_intent(
            letter_of_intent_payload(
                applicant["id"], UNKNOWN_HSA_ID, world["cycle"]["id"]
            ),
            make_applicant_headers(applicant["id"]),
        )

        validate_error(response, ApiErrorId.ERR_HSA_NOT_FOUND, 404)
        _, meta = validate_paginated(
            api_client.list_letters_of_intent(
                ADMIN, params={"batching_cycle_id": world["cycle"]["id"]}
            )
        )
        assert meta["total_count"] == 0
