"""
Entity-level breadth: declared field sets, server-owned defaults, the success and
error envelopes, paging metadata, and the entity-specific 404 codes.
"""

from test_helpers import (
    HTTP_BAD_REQUEST,
    HTTP_NOT_FOUND,
    NON_EXISTENT_UUID,
    ObservationApiClient,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_absent,
    assert_common_fields,
    assert_envelope_meta,
    assert_fields,
    assert_instant,
    assert_reassessment_common_fields,
    assert_row_count,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_BASIC,
    ERR_INVALID_REQUEST,
    ERR_STAFF_NOT_FOUND,
    MODALITY_ONE_TO_ONE_SITTER,
    ORDER_ACTIVE,
    PATIENT_ADMITTED,
    POOL_VOLUNTEER,
    RISK_ELOPEMENT,
    RISK_FALL,
    STAFF_AVAILABLE,
    UNIT_OPEN,
)
from test_helpers.factories import (
    assignment_payload,
    order_payload,
    patient_payload,
    staff_payload,
    unit_payload,
)
from test_helpers.fixtures import (
    make_order,
    make_patient,
    make_reassessment,
    make_unit,
    order_reassessments,
    patient_orders,
    read_order,
    read_reassessment,
    read_unit,
    unit_head,
)
from test_helpers.test_users import (
    COORDINATOR,
    MANAGER,
    PROVIDER_1,
    PROVIDER_3,
    READER_AS_SITTER,
)


class TestUnitAndPatientCreationShapes:
    """What a create returns, and what a subsequent read must return unchanged."""

    def test_unit_creation_returns_its_declared_fields_inside_the_success_envelope(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.1: "A freshly registered unit opens in posture `OPEN` with
        `restriction_reason` null, an `observed_cost_to_date_cents` ledger head of 0,
        and an `open_order_count` of 0."

        The four declared inputs come back verbatim, the computed and system fields
        come back at their declared initial values, and the whole thing arrives inside
        the object-shaped success envelope.

        Design: Corner/entities/unit_creation_returns_declared_fields_and_success_envelope
        """
        response = api.create_unit(
            unit_payload(
                unit_code="UNIT-C01",
                name="Corner Unit One",
                observation_cost_budget_cents=250000,
                video_monitoring_enabled=True,
            ),
            MANAGER,
        )
        body = response.json()
        assert_envelope_meta(body)
        assert body["response_type"] == "object", body
        created = validate_success(response, 201)

        assert_fields(
            created,
            label="the created unit",
            unit_code="UNIT-C01",
            name="Corner Unit One",
            observation_cost_budget_cents=250000,
            video_monitoring_enabled=True,
            status=UNIT_OPEN,
            restriction_reason=None,
            observed_cost_to_date_cents=0,
            version=1,
        )
        assert_common_fields(created, "the created unit")
        assert_instant(created["created_at"], CLOCK_START, "unit.created_at")
        assert_instant(created["updated_at"], CLOCK_START, "unit.updated_at")

    def test_unit_creation_sources_every_system_field_itself(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        instant refreshed on every mutation, and `version`, an integer that starts at 1
        on creation and increments by exactly 1 on every mutation of that resource —
        including mutations the server performs on its own initiative as part of a
        cascade, and including mutations that only touch a derived field such as a
        recomputed ledger head or feed count."

        The request body carries only the four declared inputs, so the id, the two
        timestamps, the version, the posture, the restriction reason, the ledger head
        and the open-order count are all server-sourced — and a read has to agree with
        the create on every one of them.

        Design: Corner/entities/unit_create_sets_every_system_field_itself
        """
        payload = unit_payload(
            unit_code="UNIT-C07",
            name="Corner Unit Seven",
            observation_cost_budget_cents=250000,
            video_monitoring_enabled=False,
        )
        created = validate_success(api.create_unit(payload, MANAGER), 201)

        assert set(payload) == {
            "unit_code",
            "name",
            "observation_cost_budget_cents",
            "video_monitoring_enabled",
        }, payload
        assert created["id"] not in payload.values(), "the id must be server-minted"
        assert_common_fields(created, "the created unit")
        assert_fields(
            created,
            label="the created unit",
            version=1,
            status=UNIT_OPEN,
            restriction_reason=None,
            observed_cost_to_date_cents=0,
            open_order_count=0,
        )
        assert_instant(created["created_at"], CLOCK_START, "unit.created_at")
        assert created["updated_at"] == created["created_at"]

        reread = read_unit(api, created["id"])
        for field in (
            "id",
            "unit_code",
            "name",
            "observation_cost_budget_cents",
            "video_monitoring_enabled",
            "status",
            "restriction_reason",
            "observed_cost_to_date_cents",
            "open_order_count",
            "version",
            "created_at",
            "updated_at",
        ):
            assert reread[field] == created[field], f"{field} drifted between create and read"

    def test_patient_retrieval_returns_the_stored_row(self, api: ObservationApiClient):
        """
        PRD 3.1: "An admitted patient's `status` is `ADMITTED` and `discharged_at` is
        null."

        The read echoes exactly what the create stored, including the foreign key to
        the occupied unit and the age that later feeds the risk-score adjustment, with
        no field drift.

        Design: Corner/entities/patient_retrieval_returns_the_stored_row
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C02",
            name="Corner Unit Two",
            budget_cents=250000,
            video_monitoring_enabled=False,
        )
        created = validate_success(
            api.create_patient(
                patient_payload(
                    unit["id"],
                    mrn="MRN-C0201",
                    full_name="Corner Patient Two",
                    age_years=71,
                ),
                MANAGER,
            ),
            201,
        )

        response = api.get_patient(created["id"], READER_AS_SITTER)
        assert response.json()["response_type"] == "object", response.json()
        fetched = validate_success(response)

        assert_fields(
            fetched,
            label="the stored patient",
            id=created["id"],
            unit_id=unit["id"],
            mrn="MRN-C0201",
            full_name="Corner Patient Two",
            age_years=71,
            status=PATIENT_ADMITTED,
            discharged_at=None,
            version=1,
        )


class TestListingAndLookupSurfaces:
    """Paging metadata on a collection, and the 404 code of a single read."""

    def test_the_order_listing_pages_with_total_count_and_has_more(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, alongside `api_request_id` and
        `api_request_timestamp`."

        Three orders exist, so a two-row page reports the full count and more to come,
        and the following page returns the remainder with nothing left after it. The
        union of both pages is the whole set, with no row served twice.

        Design: Corner/entities/orders_list_paginates_with_total_count_and_has_more
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C03",
            name="Corner Unit Three",
            budget_cents=250000,
            video_monitoring_enabled=False,
        )
        expected = set()
        for mrn, full_name, rationale in (
            ("MRN-C0301", "Corner Patient A", "Order A"),
            ("MRN-C0302", "Corner Patient B", "Order B"),
            ("MRN-C0303", "Corner Patient C", "Order C"),
        ):
            patient = make_patient(api, unit["id"], mrn=mrn, full_name=full_name, age_years=60)
            expected.add(
                make_order(
                    api,
                    patient["id"],
                    risk_categories=[RISK_FALL],
                    required_modality=MODALITY_ONE_TO_ONE_SITTER,
                    clinical_rationale=rationale,
                )["id"]
            )

        first_response = api.list_orders(MANAGER, {"limit": 2, "offset": 0})
        assert first_response.json()["response_type"] == "array", first_response.json()
        first_rows, first_meta = validate_paginated(first_response)
        assert_row_count(first_rows, 2, "rows on the first page")
        assert_fields(
            first_meta,
            label="first page meta",
            total_count=3,
            limit=2,
            offset=0,
            has_more=True,
        )

        second_rows, second_meta = validate_paginated(
            api.list_orders(MANAGER, {"limit": 2, "offset": 2})
        )
        assert_row_count(second_rows, 1, "rows on the second page")
        assert_fields(
            second_meta,
            label="second page meta",
            total_count=3,
            offset=2,
            has_more=False,
        )

        served = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
        assert len(served) == len(set(served)), f"a row was served twice: {served}"
        assert set(served) == expected, "the two pages must cover exactly the three orders"

    def test_an_unknown_staff_id_returns_the_staff_specific_not_found(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.5: "The first path segment whose identifier names no existing row
        terminates the request with the 404 belonging to that segment's entity type:
        `ERR_UNIT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_FEED_NOT_FOUND`, `ERR_HANDOFF_NOT_FOUND`, `ERR_SAFETY_EVENT_NOT_FOUND`,
        `ERR_REASSESSMENT_NOT_FOUND`, or `ERR_COST_ENTRY_NOT_FOUND`."

        A syntactically valid identifier that names no row must produce the code that
        belongs to that entity type, and the error envelope that carries it.

        Design: Corner/entities/staff_retrieval_with_unknown_id_returns_staff_not_found
        """
        response = api.get_staff(NON_EXISTENT_UUID, COORDINATOR)
        assert response.json()["response_type"] == "error", response.json()
        validate_error(response, ERR_STAFF_NOT_FOUND, HTTP_NOT_FOUND)


class TestStaffDefaultsAndOrderInputConstraints:
    """Server-owned defaults on one create, and the shape gate on another."""

    def test_a_new_observer_takes_the_declared_duty_defaults(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.1: "Registration leaves the observer's duty posture `status` at
        `AVAILABLE`, `suspension_reason` null, `last_shift_end_at` null and
        `total_watch_minutes` at 0."

        The client supplies none of those four, and a volunteer at a zero rate is
        still a perfectly ordinary registration as far as the defaults are concerned.

        Design: Corner/entities/staff_create_defaults_to_available_with_null_suspension_reason
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C06",
            name="Corner Unit Six",
            budget_cents=250000,
            video_monitoring_enabled=False,
        )
        payload = staff_payload(
            unit["id"],
            full_name="Corner Sitter Six",
            source_pool=POOL_VOLUNTEER,
            hourly_rate_cents=0,
            competency_level=COMPETENCY_BASIC,
            deescalation_cert_expires_on="2027-01-01T00:00:00Z",
        )
        created = validate_success(api.create_staff(payload, COORDINATOR), 201)

        assert "status" not in payload and "suspension_reason" not in payload, payload
        assert_fields(
            created,
            label="the registered observer",
            status=STAFF_AVAILABLE,
            suspension_reason=None,
            last_shift_end_at=None,
            total_watch_minutes=0,
            source_pool=POOL_VOLUNTEER,
            hourly_rate_cents=0,
            competency_level=COMPETENCY_BASIC,
            home_unit_id=unit["id"],
            version=1,
        )

    def test_an_order_without_risk_categories_fails_the_shape_gate(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.6: "Request-body shape: every required input field present, every
        enumerated value a declared member, every integer inside its declared range,
        every array non-empty and duplicate-free where declared so, every ISO 8601
        instant parseable — `ERR_INVALID_REQUEST`."

        `risk_categories` has no default, so omitting it fails at the shape rung —
        ahead of any foreign-key resolution — and the patient named in the body, which
        does exist, gains no order at all.

        Design: Corner/entities/order_create_without_risk_categories_is_rejected
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C05",
            name="Corner Unit Five",
            budget_cents=250000,
            video_monitoring_enabled=False,
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C0501", full_name="Corner Patient Five", age_years=60
        )
        payload = order_payload(
            patient["id"],
            PROVIDER_1["X-User-ID"],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Missing risk categories",
        )
        payload.pop("risk_categories")

        validate_error(
            api.create_order(payload, PROVIDER_1), ERR_INVALID_REQUEST, HTTP_BAD_REQUEST
        )
        assert_row_count(patient_orders(api, patient["id"]), 0, "orders on the patient")

    def test_an_order_with_a_duplicated_risk_category_is_rejected(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.2: "The payload names the `patient_id`, pins the writing provider's own
        identity in `ordering_provider_user_id`, declares the `risk_categories` the
        patient meets — a non-empty, duplicate-free subset of `FALL`, `ELOPEMENT` and
        `SELF_HARM` — selects the `required_modality` in force, either
        `ONE_TO_ONE_SITTER` or `VIDEO_MONITORING`, and documents a `clinical_rationale`
        of 1 to 500 characters."

        A duplicated member would silently double that category's score weight, so the
        array is rejected at the shape gate rather than scored — no order exists
        afterwards at any score.

        Design: Corner/entities/order_create_with_duplicate_risk_category_is_rejected
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C08",
            name="Corner Unit Eight",
            budget_cents=250000,
            video_monitoring_enabled=False,
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C0801", full_name="Corner Patient Eight", age_years=60
        )

        validate_error(
            api.create_order(
                order_payload(
                    patient["id"],
                    PROVIDER_1["X-User-ID"],
                    risk_categories=[RISK_FALL, RISK_FALL],
                    required_modality=MODALITY_ONE_TO_ONE_SITTER,
                    clinical_rationale="Duplicated category",
                ),
                PROVIDER_1,
            ),
            ERR_INVALID_REQUEST,
            HTTP_BAD_REQUEST,
        )
        assert_row_count(patient_orders(api, patient["id"]), 0, "orders on the patient")


class TestAppendOnlyRecordsAndBodyForeignKeys:
    """The one entity without common fields, and the rung that resolves body FKs."""

    def test_a_second_reassessment_adds_a_row_and_never_edits_the_first(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.4: "A `Reassessment` is an immutable, append-only clinical artifact: it
        carries only `id` and `created_at`."

        The audit trail grows by one row per reassessment: the first row still reports
        the score and cadence that were in force when it was written, and it exposes
        neither `updated_at` nor `version` for anything to have been written onto.

        Design: Corner/entities/reassessment_rows_are_immutable_and_carry_no_version
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C09",
            name="Corner Unit Nine",
            budget_cents=250000,
            video_monitoring_enabled=False,
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C0901", full_name="Corner Patient Nine", age_years=60
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Baseline fall risk",
        )
        first = make_reassessment(api, order["id"], [RISK_FALL], provider_headers=PROVIDER_1)
        second = make_reassessment(
            api, order["id"], [RISK_FALL, RISK_ELOPEMENT], provider_headers=PROVIDER_3
        )

        untouched = read_reassessment(api, first["id"])
        assert_fields(
            untouched,
            label="the first reassessment",
            score_before=1.5,
            score_after=1.5,
            interval_hours_after=24,
            performed_by_user_id=PROVIDER_1["X-User-ID"],
        )
        assert_reassessment_common_fields(untouched)
        assert_absent(untouched, "updated_at", "version", label="a Reassessment")

        assert_fields(
            read_reassessment(api, second["id"]),
            label="the second reassessment",
            score_before=1.5,
            score_after=4.0,
            interval_hours_after=12,
            performed_by_user_id=PROVIDER_3["X-User-ID"],
        )

        rows = order_reassessments(api, order["id"])
        assert_row_count(rows, 2, "reassessments on the order")
        assert [row["id"] for row in rows] == [first["id"], second["id"]], (
            "the history reads in ascending reassessed_at order"
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the reassessed order",
            reassessment_count=2,
            elopement_risk_score=4.0,
            risk_categories=[RISK_FALL, RISK_ELOPEMENT],
            status=ORDER_ACTIVE,
        )

    def test_an_unknown_staff_id_in_the_body_beats_the_stale_order_version(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.6: "Existence of body foreign-key references, in the endpoint's declared
        field order — the corresponding 404."

        The request both names a staff id that was never created and replays an order
        version that a reassessment has already superseded. Body foreign keys are
        resolved at rung 5 and the concurrency check sits at rung 7, so the answer is
        the staff-specific 404 and nothing about the order moves.

        Design: Corner/entities/sitter_assignment_create_with_unknown_staff_id_returns_staff_not_found
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C10",
            name="Corner Unit Ten",
            budget_cents=250000,
            video_monitoring_enabled=False,
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C1001", full_name="Corner Patient Ten", age_years=60
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Fall precautions",
        )
        stale_version = order["version"]
        make_reassessment(api, order["id"], [RISK_FALL], provider_headers=PROVIDER_1)
        current_version = read_order(api, order["id"])["version"]
        assert current_version > stale_version, "the reassessment must have bumped the order"

        validate_error(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    NON_EXISTENT_UUID,
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                    expected_order_version=stale_version,
                ),
                COORDINATOR,
            ),
            ERR_STAFF_NOT_FOUND,
            HTTP_NOT_FOUND,
        )
        assert read_order(api, order["id"])["version"] == current_version, (
            "the rejected create bumped nothing"
        )
        assert unit_head(api, unit["id"]) == 0
