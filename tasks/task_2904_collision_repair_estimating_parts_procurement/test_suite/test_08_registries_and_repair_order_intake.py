"""Writing the vehicle up: the standing registries and the repair order at intake.

Everything in this file happens in the first hour of a collision repair. The
shop admin registers the owner, the insurer program, the parts supplier, the
stall and the calibration bay; then opens a repair order against a claim; then
the estimator tears the car down and records what was actually broken. The
tests here pin what those first writes are allowed to say and what the server
insists on owning: the money block that has not been computed yet, the
declared fallbacks for every optional input, the check-in instant read from the
logical clock, and the two child records that hang off a parent whose identity
the path — not the payload — decides.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ESTIMATOR_HEADERS,
    PARTS_MANAGER_HEADERS,
    SHOP_ADMIN_HEADERS,
    make_estimator_headers,
)

# The twenty money and count fields a fresh order carries before any pricing
# calculation has had an input to read.
_UNPRICED_MONEY_FIELDS = (
    "labor_subtotal_cents",
    "parts_gross_cents",
    "parts_discount_cents",
    "parts_subtotal_cents",
    "betterment_cents",
    "supplies_fee_cents",
    "pre_tax_total_cents",
    "insurer_authorized_cents",
    "customer_pay_cents",
    "parts_ordered_gross_cents",
    "parts_committed_cents",
    "parts_return_credit_cents",
    "parts_restocking_loss_cents",
)

_ROLLUP_COUNT_FIELDS = (
    "teardown_finding_count",
    "open_parts_delay_count",
    "qc_inspection_count",
)


class TestRepairOrderIntake:
    """Opening the order, reading it back, and the refusals at the front door."""

    def test_a_new_repair_order_answers_with_every_declared_field_at_intake_defaults(
        self, api
    ):
        """A car written up on an empty database answers with the whole order in one envelope.

        PRD: "On creation the order's `checkin_at` is stamped from the logical clock, opening the cycle-time window; `stage` is `INTAKE`, `authorization_posture` is `OPEN`, `consent_state` is `NONE`, and `version` is 1."
        PRD: "Three counters on the order are pure roll-ups and are recomputed rather than incremented: `teardown_finding_count` is the number of teardown findings on the order, `open_parts_delay_count` is the number of parts delay events on the order whose `closed_at` is still null, and `qc_inspection_count` is the number of inspections filed on the order."
        PRD: "They run at estimate lock, on every supplement decision, on price acceptance, on a parts order, on a parts return, on a consent decision, and on a total-loss declaration."
        Design: Corner/entities/create_repair_order_returns_all_declared_fields_with_intake_defaults
        """
        fx.set_clock(api, C.CLOCK_DEFAULT)
        customer = fx.create_customer(
            api, full_name="Amy Diaz", phone="555-1000", email="amy@example.com"
        )
        insurer = fx.create_insurer(
            api,
            insurer_code="CRNR-01",
            name="Cornerstone Mutual",
            rate_ceiling_cents=dict(C.CEILINGS_BELOW_POSTED),
        )

        response = api.create_repair_order(
            f.repair_order_payload(
                customer["id"],
                insurer["id"],
                claim_number="CLM-90001",
                vehicle_vin="1HGCV1F30LA090001",
                vehicle_model_year=2019,
                vehicle_make_model="Honda Accord",
                initial_authorized_cents=400000,
                deductible_cents=25000,
            ),
            SHOP_ADMIN_HEADERS,
        )
        order = validate_success(response, 201)

        body = response.json()
        A.assert_envelope_meta(body)
        assert body["response_type"] == "object"

        # The eight inputs come back verbatim.
        assert order["customer_id"] == customer["id"]
        assert order["insurer_id"] == insurer["id"]
        assert order["claim_number"] == "CLM-90001"
        assert order["vehicle_vin"] == "1HGCV1F30LA090001"
        assert order["vehicle_model_year"] == 2019
        assert order["vehicle_make_model"] == "Honda Accord"
        A.assert_cents(order["initial_authorized_cents"], 400000, "initial_authorized_cents")
        A.assert_cents(order["deductible_cents"], 25000, "deductible_cents")

        # The server-owned opening position.
        A.assert_mutable_common_fields(order, "repair order")
        A.assert_version(order, 1, "repair order")
        A.assert_stage(order, C.STAGE_INTAKE)
        A.assert_posture(order, C.POSTURE_OPEN)
        assert order["consent_state"] == "NONE"
        A.assert_instant(order["checkin_at"], C.CLOCK_DEFAULT, "checkin_at")
        A.assert_null(order["delivered_at"], "delivered_at")

        # Nothing has been torn down, priced or inspected yet.
        for field in _ROLLUP_COUNT_FIELDS:
            A.assert_count(order[field], 0, field)
        for field in _UNPRICED_MONEY_FIELDS:
            A.assert_cents(order[field], 0, field)
        A.assert_hours(order["refinish_hours_provisional"], 0.0, "refinish_hours_provisional")
        A.assert_hours(order["refinish_hours_final"], 0.0, "refinish_hours_final")
        A.assert_hours(order["approved_labor_hours"], 0.0, "approved_labor_hours")

    def test_reading_the_order_back_shows_the_teardown_consequences_not_the_create_response(
        self, api
    ):
        """After the first finding the read-back carries TEARDOWN and a bumped version.

        PRD: "The **first** finding on an order moves `stage` from `INTAKE` to `TEARDOWN`, recomputes `teardown_finding_count`, and increments the order's `version`."
        PRD: "Most resources are mutable and therefore also carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every change to the row — and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row."
        Design: Corner/entities/get_repair_order_returns_the_persisted_row_unchanged
        """
        customer = fx.create_customer(
            api, full_name="Ben Ford", phone="555-1001", email="ben@example.com"
        )
        insurer = fx.create_insurer(
            api, insurer_code="CRNR-02", name="Cornerstone Mutual"
        )
        created = fx.create_repair_order(
            api,
            customer["id"],
            insurer["id"],
            claim_number="CLM-90002",
            vehicle_vin="1HGCV1F30LA090002",
            vehicle_model_year=2019,
            vehicle_make_model="Honda Accord",
            initial_authorized_cents=400000,
            deductible_cents=25000,
        )
        fx.add_finding(
            api, created["id"], panel_code="LT-QTR", severity="SEVERE", structural=True
        )

        order = validate_success(api.get_repair_order(created["id"], SHOP_ADMIN_HEADERS))

        assert order["id"] == created["id"]
        assert order["claim_number"] == "CLM-90002"
        assert order["vehicle_vin"] == "1HGCV1F30LA090002"
        A.assert_stage(order, C.STAGE_TEARDOWN)
        A.assert_count(order["teardown_finding_count"], 1, "teardown_finding_count")
        A.assert_version(order, 2, "repair order")
        A.assert_instant(order["checkin_at"], created["checkin_at"], "checkin_at")
        A.assert_null(order["blueprint_by_user_id"], "blueprint_by_user_id")

    def test_an_unknown_repair_order_id_is_refused_on_the_order_and_on_its_findings(
        self, api
    ):
        """A well-formed identifier nobody minted is a not-found, on the order and under it.

        PRD: "Existence of everything the request names, in this order: the order identifier in the path (`ERR_REPAIR_ORDER_NOT_FOUND`), then `customer_id` (`ERR_CUSTOMER_NOT_FOUND`), then `insurer_id` (`ERR_INSURER_NOT_FOUND`), then the labor-line identifier in the path or an `estimate_line_id` filter (`ERR_ESTIMATE_LINE_NOT_FOUND`), then `damage_line_id` (`ERR_DAMAGE_LINE_NOT_FOUND`), then a supplement identifier in the path or a `supplement_id` reference (`ERR_SUPPLEMENT_NOT_FOUND`), then `vendor_id` (`ERR_PARTS_VENDOR_NOT_FOUND`), then the parts-line identifier in the path (`ERR_PARTS_LINE_NOT_FOUND`), then the procedure-record identifier in the path (`ERR_PROCEDURE_RECORD_NOT_FOUND`), then `bay_id` (`ERR_CALIBRATION_BAY_NOT_FOUND`), then `stall_id` (`ERR_STALL_NOT_FOUND`), then the stall-booking identifier in the path (`ERR_STAGE_ASSIGNMENT_NOT_FOUND`)."
        PRD: "When a path carries an identifier, that identifier is resolved before anything in the request body is examined, and nested paths are resolved strictly left to right."
        Design: Corner/entities/get_repair_order_with_unknown_id_returns_not_found
        """
        world = fx.open_order_world(
            api,
            customer_overrides={
                "full_name": "Eve Pak",
                "phone": "555-1004",
                "email": "eve@example.com",
            },
            insurer_overrides={"insurer_code": "CRNR-04", "name": "Cornerstone Mutual"},
            order_overrides={
                "claim_number": "CLM-90007",
                "vehicle_vin": "1HGCV1F30LA090007",
            },
        )

        validate_error(
            api.get_repair_order(C.ABSENT_UUID, SHOP_ADMIN_HEADERS),
            ApiErrorId.REPAIR_ORDER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.list_damage_lines(C.ABSENT_UUID, SHOP_ADMIN_HEADERS),
            ApiErrorId.REPAIR_ORDER_NOT_FOUND.value,
            404,
        )

        # The store was not disturbed by either refusal.
        survivor = validate_success(
            api.get_repair_order(world["order_id"], SHOP_ADMIN_HEADERS)
        )
        assert survivor["id"] == world["order_id"]

    def test_opening_an_order_without_a_claim_number_is_refused_and_writes_nothing(
        self, api
    ):
        """The insurer's claim number has no fallback, so an order without one is not opened.

        PRD: "Request shape: every required input field is present, non-null and of the declared JSON type, and unknown fields are rejected — otherwise `ERR_INVALID_REQUEST`."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Corner/entities/create_repair_order_rejects_a_missing_claim_number
        """
        customer = fx.create_customer(
            api, full_name="Finn Roe", phone="555-1005", email="finn@example.com"
        )
        insurer = fx.create_insurer(
            api, insurer_code="CRNR-05", name="Cornerstone Mutual"
        )
        without_claim = {
            "customer_id": customer["id"],
            "insurer_id": insurer["id"],
            "vehicle_vin": "1HGCV1F30LA090008",
            "vehicle_model_year": 2019,
            "vehicle_make_model": "Honda Accord",
            "initial_authorized_cents": 400000,
        }

        validate_error(
            api.create_repair_order(without_claim, SHOP_ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        _, meta = validate_paginated(api.list_repair_orders(SHOP_ADMIN_HEADERS))
        A.assert_page(meta, total_count=0)

        # Money carried as a string is the same rung, refused for its JSON type.
        wrong_type = dict(without_claim, claim_number="CLM-90008-STR")
        wrong_type["initial_authorized_cents"] = "400000"
        validate_error(
            api.create_repair_order(wrong_type, SHOP_ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        # The identical payload with the claim number supplied is accepted.
        accepted = validate_success(
            api.create_repair_order(
                dict(without_claim, claim_number="CLM-90008"), SHOP_ADMIN_HEADERS
            ),
            201,
        )
        assert accepted["claim_number"] == "CLM-90008"
        _, meta = validate_paginated(api.list_repair_orders(SHOP_ADMIN_HEADERS))
        A.assert_page(meta, total_count=1)


class TestRepairOrderListing:
    """Reversing the lookup from an owner back to the work in the building."""

    def test_listing_orders_by_owner_pages_the_filtered_set_with_a_total_count(self, api):
        """The owner filter narrows the total itself, and has_more says whether more is behind it.

        PRD: "`limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100."
        PRD: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object."
        Design: Corner/entities/list_repair_orders_paginates_with_total_count_and_has_more
        """
        owner_a = fx.create_customer(
            api, full_name="Cara Ng", phone="555-1002", email="cara@example.com"
        )
        owner_b = fx.create_customer(
            api, full_name="Dan Ott", phone="555-1003", email="dan@example.com"
        )
        insurer = fx.create_insurer(
            api, insurer_code="CRNR-03", name="Cornerstone Mutual"
        )
        fleet_a = [
            fx.create_repair_order(
                api,
                owner_a["id"],
                insurer["id"],
                claim_number=claim,
                vehicle_vin=vin,
                vehicle_model_year=year,
                vehicle_make_model=model,
            )
            for claim, vin, year, model in (
                ("CLM-90003", "1HGCV1F30LA090003", 2019, "Honda Accord"),
                ("CLM-90004", "1HGCV1F30LA090004", 2020, "Honda Civic"),
                ("CLM-90005", "1HGCV1F30LA090005", 2021, "Honda CR-V"),
            )
        ]
        other = fx.create_repair_order(
            api,
            owner_b["id"],
            insurer["id"],
            claim_number="CLM-90006",
            vehicle_vin="1HGCV1F30LA090006",
            vehicle_model_year=2018,
            vehicle_make_model="Honda Fit",
        )
        ids_a = {order["id"] for order in fleet_a}

        first_page, meta = validate_paginated(
            api.list_repair_orders(
                SHOP_ADMIN_HEADERS,
                {"customer_id": owner_a["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2
        A.assert_page(meta, total_count=3, has_more=True, limit=2, offset=0)
        assert all(row["customer_id"] == owner_a["id"] for row in first_page)
        assert all(row["id"] in ids_a for row in first_page)

        last_page, meta = validate_paginated(
            api.list_repair_orders(
                SHOP_ADMIN_HEADERS,
                {"customer_id": owner_a["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(last_page) == 1
        A.assert_page(meta, total_count=3, has_more=False, limit=2, offset=2)
        assert last_page[0]["id"] in ids_a

        unfiltered, meta = validate_paginated(api.list_repair_orders(SHOP_ADMIN_HEADERS))
        A.assert_page(
            meta,
            total_count=4,
            has_more=False,
            limit=C.PAGE_LIMIT_DEFAULT,
            offset=C.PAGE_OFFSET_MIN,
        )
        assert {row["id"] for row in unfiltered} == ids_a | {other["id"]}

        _, meta = validate_paginated(
            api.list_repair_orders(SHOP_ADMIN_HEADERS, {"stage": C.STAGE_INTAKE})
        )
        A.assert_page(meta, total_count=4, has_more=False)


class TestDeclaredDefaultsAndServerOwnedFields:
    """What the registries fall back to, and what a caller may never name."""

    def test_every_omitted_optional_registry_input_falls_back_to_its_declared_default(
        self, api
    ):
        """Registered with the bare minimum, every row still carries the contract's literals.

        PRD: "One optional field completes the picture: `deductible_cents`, defaulting to 50,000 cents, is the owner's deductible and is always part of the owner's share, whatever else happens."
        PRD: "Commercial terms follow: `discount_pct` is the fractional discount off the quoted unit price, at least zero and strictly below one, defaulting to zero; `core_charge_cents` is a per-unit core charge of zero or more, defaulting to zero, that exists for reconditioned cores; `restocking_fee_pct` is the fractional fee the supplier levies on returned units, between zero and one inclusive, defaulting to 0.2; and `max_qty_per_line` is the largest quantity the supplier will accept on a single line order, at least 1, defaulting to 4."
        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        customer = fx.create_customer(
            api, full_name="Gia Sol", phone="555-1006", email="gia@example.com"
        )
        insurer = fx.create_insurer(
            api, insurer_code="CRNR-06", name="Cornerstone Mutual"
        )
        vendor = get_success_data(
            api.create_parts_vendor(
                {
                    "name": "Default Parts Co",
                    "vendor_type": "OEM_DEALER",
                    "part_types_offered": ["OEM"],
                },
                PARTS_MANAGER_HEADERS,
            )
        )
        stall = fx.create_stall(api, name="Body D", stall_type="BODY")
        bay = fx.create_bay(api, name="Bay D", supported_types=["STATIC"])

        order = fx.create_repair_order(
            api,
            customer["id"],
            insurer["id"],
            claim_number="CLM-90009",
            vehicle_vin="1HGCV1F30LA090009",
            vehicle_model_year=2019,
            vehicle_make_model="Honda Accord",
            initial_authorized_cents=400000,
        )
        A.assert_cents(
            order["deductible_cents"], C.DEFAULT_DEDUCTIBLE_CENTS, "deductible_cents"
        )

        owner = get_success_data(api.get_customer(customer["id"], SHOP_ADMIN_HEADERS))
        assert owner["preferred_alternate_parts_ok"] is False

        program = get_success_data(api.get_insurer(insurer["id"], SHOP_ADMIN_HEADERS))
        assert program["aftermarket_allowed"] is C.DEFAULT_AFTERMARKET_ALLOWED
        assert program["recycled_allowed"] is C.DEFAULT_RECYCLED_ALLOWED
        assert program["reconditioned_allowed"] is C.DEFAULT_RECONDITIONED_ALLOWED
        A.assert_count(
            program["alternate_parts_min_vehicle_age_years"],
            C.DEFAULT_ALTERNATE_PARTS_MIN_VEHICLE_AGE_YEARS,
            "alternate_parts_min_vehicle_age_years",
        )
        assert program["parts_price_ceiling_pct"] == pytest.approx(
            C.DEFAULT_PARTS_PRICE_CEILING_PCT, abs=0.01
        )
        A.assert_count(
            program["supplement_round_limit"],
            C.DEFAULT_SUPPLEMENT_ROUND_LIMIT,
            "supplement_round_limit",
        )

        supplier = fx.read_vendor(api, vendor["id"])
        assert supplier["status"] == C.DEFAULT_VENDOR_STATUS
        assert supplier["discount_pct"] == pytest.approx(C.DEFAULT_DISCOUNT_PCT, abs=0.01)
        A.assert_cents(
            supplier["core_charge_cents"], C.DEFAULT_CORE_CHARGE_CENTS, "core_charge_cents"
        )
        assert supplier["restocking_fee_pct"] == pytest.approx(
            C.DEFAULT_RESTOCKING_FEE_PCT, abs=0.01
        )
        A.assert_count(
            supplier["max_qty_per_line"], C.DEFAULT_MAX_QTY_PER_LINE, "max_qty_per_line"
        )
        A.assert_count(
            supplier["order_seq_counter"],
            C.DEFAULT_ORDER_SEQ_COUNTER,
            "order_seq_counter",
        )
        A.assert_scores(supplier, C.VENDOR_SCORE_DEFAULT, C.VENDOR_SCORE_DEFAULT)

        bay_D = fx.read_bay(api, bay["id"])
        A.assert_count(
            bay_D["concurrent_capacity"],
            C.DEFAULT_CONCURRENT_CAPACITY,
            "concurrent_capacity",
        )
        A.assert_count(bay_D["scheduled_window_count"], 0, "scheduled_window_count")

        stall_D = fx.read_stall(api, stall["id"])
        A.assert_count(
            stall_D["cleanup_buffer_minutes"],
            C.DEFAULT_CLEANUP_BUFFER_MINUTES,
            "cleanup_buffer_minutes",
        )
        assert stall_D["status"] == C.DEFAULT_STALL_STATUS
        A.assert_count(stall_D["booked_minutes"], 0, "booked_minutes")

    def test_a_stall_may_not_be_created_with_booked_minutes_the_occupancy_rollup_owns(
        self, api
    ):
        """Occupancy is produced by the bookings, so naming it on registration is refused.

        PRD: "Its `booked_minutes` is derived and never supplied."
        PRD: "A successful booking is created with `status` `SCHEDULED` and an `occupied_minutes` fixed at creation as the whole minutes, floored, between its `window_start` and its `window_end`."
        Design: Corner/entities/stall_rejects_a_client_supplied_booked_minutes_value
        """
        world = fx.locked_world(
            api,
            lines=[{"labor_type": "BODY", "guide_hours": 4.5}],
            customer_overrides={
                "full_name": "Hal Tor",
                "phone": "555-1007",
                "email": "hal@example.com",
            },
            insurer_overrides={"insurer_code": "CRNR-07", "name": "Cornerstone Mutual"},
            order_overrides={
                "claim_number": "CLM-90010",
                "vehicle_vin": "1HGCV1F30LA090010",
                "deductible_cents": 25000,
            },
        )

        validate_error(
            api.create_stall(
                {"name": "Body E", "stall_type": "BODY", "booked_minutes": 999},
                SHOP_ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        stall = validate_success(
            api.create_stall({"name": "Body E", "stall_type": "BODY"}, SHOP_ADMIN_HEADERS),
            201,
        )
        A.assert_count(stall["booked_minutes"], 0, "booked_minutes")

        booking = fx.book_stall(
            api, world["order_id"], stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
        )
        A.assert_count(booking["occupied_minutes"], 240, "occupied_minutes")
        assert booking["status"] == "SCHEDULED"
        A.assert_count(
            fx.read_stall(api, stall["id"])["booked_minutes"], 240, "booked_minutes"
        )

    def test_the_shop_may_not_name_the_stage_and_the_server_stamps_the_checkin_instant(
        self, api
    ):
        """The workflow state is the server's to set, and so is the moment the keys arrived.

        PRD: "Request shape: every required input field is present, non-null and of the declared JSON type, and unknown fields are rejected — otherwise `ERR_INVALID_REQUEST`."
        PRD: "When `X-User-Role` is `Estimator`, `X-User-ID` is likewise an opaque operator identifier, but the server does record it: the estimator who publishes a blueprint has their `X-User-ID` written verbatim into that order's `blueprint_by_user_id`."
        Design: Corner/entities/repair_order_rejects_a_client_supplied_stage_and_stamps_checkin_at
        """
        checkin_instant = "2026-08-02T09:30:00Z"
        fx.set_clock(api, checkin_instant)
        customer = fx.create_customer(
            api, full_name="Ida Vu", phone="555-1008", email="ida@example.com"
        )
        insurer = fx.create_insurer(
            api, insurer_code="CRNR-08", name="Cornerstone Mutual"
        )
        payload = {
            "customer_id": customer["id"],
            "insurer_id": insurer["id"],
            "claim_number": "CLM-90011",
            "vehicle_vin": "1HGCV1F30LA090011",
            "vehicle_model_year": 2019,
            "vehicle_make_model": "Honda Accord",
            "initial_authorized_cents": 400000,
        }

        validate_error(
            api.create_repair_order(dict(payload, stage=C.STAGE_REPAIR), SHOP_ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        order = validate_success(
            api.create_repair_order(payload, SHOP_ADMIN_HEADERS), 201
        )
        A.assert_mutable_common_fields(order, "repair order")
        A.assert_version(order, 1, "repair order")
        A.assert_stage(order, C.STAGE_INTAKE)
        A.assert_instant(order["checkin_at"], checkin_instant, "checkin_at")
        A.assert_null(order["blueprint_by_user_id"], "blueprint_by_user_id")

        blueprinting_estimator = make_estimator_headers("est-100")
        get_success_data(
            api.create_teardown_finding(
                order["id"],
                f.teardown_finding_payload(panel_code="LT-DOOR", severity="MODERATE"),
                blueprinting_estimator,
            )
        )
        published = get_success_data(
            api.publish_blueprint(order["id"], None, blueprinting_estimator)
        )
        assert published["blueprint_by_user_id"] == "est-100"

    def test_a_1979_model_year_is_a_range_refusal_while_an_unknown_severity_is_an_enum_refusal(
        self, api
    ):
        """A number out of bounds and a word outside an enum are two different refusals.

        PRD: "Every enum-typed input holds one of that enum's declared members — otherwise `ERR_INVALID_ENUM_VALUE`."
        PRD: "A `ShopAdmin` opens the repair order, supplying the `customer_id` of the vehicle owner, the `insurer_id` of the paying program, the insurer's `claim_number`, the 17-character `vehicle_vin`, the `vehicle_model_year` (which must lie between 1980 and 2100 inclusive), the `vehicle_make_model` text, and `initial_authorized_cents` — the authorisation the insurer granted at first notice of loss, which must be zero or greater."
        Design: Corner/entities/repair_order_rejects_model_year_below_1980_and_unknown_severity_enum
        """
        world = fx.open_order_world(
            api,
            customer_overrides={
                "full_name": "Jon Wek",
                "phone": "555-1009",
                "email": "jon@example.com",
            },
            insurer_overrides={"insurer_code": "CRNR-09", "name": "Cornerstone Mutual"},
            order_overrides={
                "claim_number": "CLM-90012",
                "vehicle_vin": "1HGCV1F30LA090012",
            },
        )

        validate_error(
            api.create_teardown_finding(
                world["order_id"],
                {"panel_code": "LT-DOOR", "severity": "CRITICAL"},
                ESTIMATOR_HEADERS,
            ),
            ApiErrorId.INVALID_ENUM_VALUE.value,
            400,
        )
        still_at_intake = fx.read_order(api, world["order_id"])
        A.assert_stage(still_at_intake, C.STAGE_INTAKE)
        A.assert_count(
            still_at_intake["teardown_finding_count"], 0, "teardown_finding_count"
        )

        validate_error(
            api.create_repair_order(
                f.repair_order_payload(
                    world["customer_id"],
                    world["insurer_id"],
                    vehicle_model_year=C.MODEL_YEAR_MIN - 1,
                ),
                SHOP_ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api.list_repair_orders(SHOP_ADMIN_HEADERS, {"stage": "WASHING"}),
            ApiErrorId.INVALID_ENUM_VALUE.value,
            400,
        )

        accepted = validate_success(
            api.create_teardown_finding(
                world["order_id"],
                {"panel_code": "LT-DOOR", "severity": "SEVERE"},
                ESTIMATOR_HEADERS,
            ),
            201,
        )
        assert accepted["severity"] == "SEVERE"
        A.assert_stage(fx.read_order(api, world["order_id"]), C.STAGE_TEARDOWN)


class TestChildRecordsAndTheirParents:
    """The teardown log that only ever grows, and the children scoped to one order."""

    def test_a_teardown_finding_never_changes_and_carries_no_version(self, api):
        """Appending a second finding leaves the first one exactly as it was written.

        PRD: "Three record types are immutable after creation and therefore carry only `id` and `created_at`, with no `updated_at` and no `version` at all: the vehicle-owner registry row, the teardown damage finding, and the parts delay event."
        PRD: "An `Estimator` records one finding at a time, each carrying a `panel_code` such as `L_FRONT_DOOR`, a `severity` of `LIGHT`, `MODERATE` or `SEVERE`, and three booleans that all default to false: `requires_blend`, meaning an adjacent panel will need a refinish blend; `adas_component_touched`, meaning the finding disturbs a driver-assistance sensor or its bracket; and `structural`, meaning the finding is on a structural member."
        PRD: "Every finding is stamped with `discovered_at_stage`, the order's `stage` at the instant the finding was recorded, which may be any of `TEARDOWN`, `BLUEPRINTED`, `ESTIMATE_LOCKED`, `PARTS_STAGED`, `REPAIR`, `REFINISH_CALIBRATION`, `READY_FOR_QC` or `QC_FAILED`."
        Design: Corner/entities/damage_line_is_immutable_and_carries_no_version_field
        """
        customer = fx.create_customer(
            api, full_name="Kim Xu", phone="555-1010", email="kim@example.com"
        )
        insurer = fx.create_insurer(
            api, insurer_code="CRNR-10", name="Cornerstone Mutual"
        )
        order = fx.create_repair_order(
            api,
            customer["id"],
            insurer["id"],
            claim_number="CLM-90013",
            vehicle_vin="1HGCV1F30LA090013",
        )
        first = fx.add_finding(
            api, order["id"], panel_code="LT-DOOR", severity="MODERATE"
        )

        second = validate_success(
            api.create_teardown_finding(
                order["id"],
                {
                    "panel_code": "LT-QTR",
                    "severity": "SEVERE",
                    "structural": True,
                    "requires_blend": True,
                },
                ESTIMATOR_HEADERS,
            ),
            201,
        )

        # Neither finding, nor the owner registry row, carries a version.
        A.assert_append_only_common_fields(first, "first damage line")
        A.assert_append_only_common_fields(second, "second damage line")
        A.assert_append_only_common_fields(
            get_success_data(api.get_customer(customer["id"], SHOP_ADMIN_HEADERS)),
            "vehicle owner",
        )

        rows, meta = validate_paginated(
            api.list_damage_lines(order["id"], SHOP_ADMIN_HEADERS)
        )
        A.assert_page(meta, total_count=2)
        reread_first = next(row for row in rows if row["id"] == first["id"])
        assert reread_first == first
        assert reread_first["panel_code"] == "LT-DOOR"
        assert reread_first["severity"] == "MODERATE"
        assert reread_first["structural"] is False
        assert reread_first["requires_blend"] is False
        assert reread_first["adas_component_touched"] is False
        assert reread_first["discovered_at_stage"] == C.STAGE_TEARDOWN
        assert second["discovered_at_stage"] == C.STAGE_TEARDOWN

        after = fx.read_order(api, order["id"])
        A.assert_count(after["teardown_finding_count"], 2, "teardown_finding_count")
        A.assert_stage(after, C.STAGE_TEARDOWN)

    def test_a_labor_line_may_not_answer_a_finding_from_another_repair_order(self, api):
        """A real finding on the car in the next stall is as good as no finding at all.

        PRD: "A `damage_line_id` that names a finding belonging to a different order, and a `supplement_id` that names a supplement belonging to a different order, are treated as not found."
        PRD: "While the estimate is still open — the order at `BLUEPRINTED` — a new line is created with `line_status` `DRAFT` and no supplement reference."
        Design: Corner/entities/estimate_line_rejects_a_damage_line_from_another_repair_order
        """
        customer = fx.create_customer(
            api, full_name="Lee Yun", phone="555-1011", email="lee@example.com"
        )
        insurer = fx.create_insurer(
            api, insurer_code="CRNR-11", name="Cornerstone Mutual"
        )
        order_a = fx.create_repair_order(
            api,
            customer["id"],
            insurer["id"],
            claim_number="CLM-90014",
            vehicle_vin="1HGCV1F30LA090014",
        )
        order_b = fx.create_repair_order(
            api,
            customer["id"],
            insurer["id"],
            claim_number="CLM-90015",
            vehicle_vin="1HGCV1F30LA090015",
            vehicle_model_year=2020,
            vehicle_make_model="Honda Civic",
        )
        finding_a = fx.add_finding(
            api, order_a["id"], panel_code="LT-DOOR", severity="MODERATE"
        )
        finding_b = fx.add_finding(
            api, order_b["id"], panel_code="RT-DOOR", severity="MODERATE"
        )
        fx.publish_blueprint(api, order_a["id"])
        fx.publish_blueprint(api, order_b["id"])

        def line_payload(damage_line_id):
            return {
                "damage_line_id": damage_line_id,
                "operation_code": "BDY-1",
                "labor_type": "BODY",
                "guide_hours": 4.5,
            }

        validate_error(
            api.create_estimate_line(
                order_a["id"], line_payload(finding_b["id"]), ESTIMATOR_HEADERS
            ),
            ApiErrorId.DAMAGE_LINE_NOT_FOUND.value,
            404,
        )
        _, meta = validate_paginated(
            api.list_estimate_lines(
                ESTIMATOR_HEADERS, {"repair_order_id": order_a["id"]}
            )
        )
        A.assert_page(meta, total_count=0)

        validate_error(
            api.create_estimate_line(
                order_a["id"], line_payload(C.ABSENT_UUID), ESTIMATOR_HEADERS
            ),
            ApiErrorId.DAMAGE_LINE_NOT_FOUND.value,
            404,
        )

        accepted = validate_success(
            api.create_estimate_line(
                order_a["id"], line_payload(finding_a["id"]), ESTIMATOR_HEADERS
            ),
            201,
        )
        assert accepted["damage_line_id"] == finding_a["id"]
        assert accepted["repair_order_id"] == order_a["id"]
        assert accepted["line_status"] == "DRAFT"

    def test_attaching_a_part_needs_a_labor_line_that_actually_exists(self, api):
        """A part hangs off the operation that will fit it, so an unknown operation is a not-found.

        PRD: "Existence of everything the request names, in this order: the order identifier in the path (`ERR_REPAIR_ORDER_NOT_FOUND`), then `customer_id` (`ERR_CUSTOMER_NOT_FOUND`), then `insurer_id` (`ERR_INSURER_NOT_FOUND`), then the labor-line identifier in the path or an `estimate_line_id` filter (`ERR_ESTIMATE_LINE_NOT_FOUND`), then `damage_line_id` (`ERR_DAMAGE_LINE_NOT_FOUND`), then a supplement identifier in the path or a `supplement_id` reference (`ERR_SUPPLEMENT_NOT_FOUND`), then `vendor_id` (`ERR_PARTS_VENDOR_NOT_FOUND`), then the parts-line identifier in the path (`ERR_PARTS_LINE_NOT_FOUND`), then the procedure-record identifier in the path (`ERR_PROCEDURE_RECORD_NOT_FOUND`), then `bay_id` (`ERR_CALIBRATION_BAY_NOT_FOUND`), then `stall_id` (`ERR_STALL_NOT_FOUND`), then the stall-booking identifier in the path (`ERR_STAGE_ASSIGNMENT_NOT_FOUND`)."
        PRD: "An `OEM` line is always `INSURER_ALLOWED`."
        Design: Corner/entities/parts_line_creation_requires_an_existing_estimate_line_parent
        """
        world = fx.locked_world(
            api,
            lines=[{"labor_type": "BODY", "guide_hours": 4.5}],
            customer_overrides={
                "full_name": "Mia Zed",
                "phone": "555-1012",
                "email": "mia@example.com",
            },
            insurer_overrides={"insurer_code": "CRNR-12", "name": "Cornerstone Mutual"},
            order_overrides={
                "claim_number": "CLM-90016",
                "vehicle_vin": "1HGCV1F30LA090016",
                "deductible_cents": 25000,
            },
        )
        labor_line_id = world["line_ids"][0]
        part = {
            "part_number": "OEM-9001",
            "part_description": "Door shell",
            "part_type": "OEM",
            "list_price_cents": 10000,
            "qty": 1,
        }

        validate_error(
            api.create_parts_line(C.ABSENT_UUID, part, PARTS_MANAGER_HEADERS),
            ApiErrorId.ESTIMATE_LINE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.list_parts_lines(
                PARTS_MANAGER_HEADERS, {"estimate_line_id": C.ABSENT_UUID}
            ),
            ApiErrorId.ESTIMATE_LINE_NOT_FOUND.value,
            404,
        )

        created = validate_success(
            api.create_parts_line(labor_line_id, part, PARTS_MANAGER_HEADERS), 201
        )
        assert created["estimate_line_id"] == labor_line_id
        A.assert_parts_line_state(
            created,
            procurement_status="PLANNED",
            authorization_status=C.AUTH_INSURER_ALLOWED,
        )

        rows, meta = validate_paginated(
            api.list_parts_lines(
                PARTS_MANAGER_HEADERS, {"estimate_line_id": labor_line_id}
            )
        )
        A.assert_page(meta, total_count=1)
        assert rows[0]["id"] == created["id"]
