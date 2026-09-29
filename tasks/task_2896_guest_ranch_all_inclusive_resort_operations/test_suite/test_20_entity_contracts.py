"""Entity contracts: what each ranch row echoes, derives and defaults on creation.

This module exercises the stored shape of the season, cabin, guest, booking,
horse, herd-health and activity-slot rows: the fields a creation echoes, the
fields the server derives instead of accepting, the system identity and version
fields, list pagination, and the refusals that leave nothing stored at all.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions, constants
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_activity_slot_payload,
    create_booking_payload,
    create_cabin_payload,
    create_guest_payload,
    create_horse_payload,
    create_season_payload,
    health_event_payload,
    party_member,
    waiver_signature_payload,
)
from test_helpers.fixtures import (
    build_cabin,
    build_guest,
    build_horse,
    build_open_season,
    build_season,
    set_clock_to,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
)


class TestSeasonEntityContract:
    """The fiscal envelope: what a fresh season stores and reports."""

    def test_season_creation_returns_201_with_every_declared_field(self, client):
        """A season created with all twelve inputs echoes them and opens its books at zero.

        PRD: "A season is created in `PLANNING` with every rollup counter — `gross_package_revenue_cents`, `retention_bonus_liability_cents`, `net_surplus_cents`, `capital_reserve_cents`, `capital_committed_cents`, `bed_nights_sold` and `in_house_guest_count` — initialised to 0."

        Design: Corner/entities/season_creation_returns_201_with_every_declared_field
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)

        response = client.create_season(create_season_payload(), RANCH_MANAGER)
        season = validate_success(response, 201)
        envelope = response.json()

        assert envelope["response_type"] == "object"
        assert isinstance(envelope["meta"]["api_request_id"], str)
        assert envelope["meta"]["api_request_id"] != ""
        assert isinstance(envelope["meta"]["api_request_timestamp"], str)
        assert envelope["meta"]["api_request_timestamp"] != ""

        assertions.assert_season(season)
        assertions.assert_identity_fields(season)
        assert season["version"] == 1

        # every declared input is echoed back
        assert season["name"] == constants.SEASON_NAME
        assert season["arrival_weekday"] == "SUNDAY"
        assert season["season_start_date"] == constants.SEASON_START_DATE
        assert season["season_end_date"] == constants.SEASON_END_DATE
        assert season["min_stay_nights"] == 7
        assert season["max_stay_nights"] == 21
        assert float(season["deposit_pct"]) == 0.30
        assert float(season["buyout_premium_pct"]) == 0.15
        assert season["no_show_penalty_cents"] == 4500
        assert season["retention_bonus_cents"] == 120000
        assert season["dining_seat_capacity"] == 8
        assert len(season["package_tiers"]) == 1
        tier = season["package_tiers"][0]
        assert tier["code"] == "CLASSIC"
        assert tier["adult_nightly_rate_cents"] == 68500
        assert float(tier["child_discount_pct"]) == 0.375
        assert tier["included_activity_credit_cents"] == 15000

        # the lifecycle and every rollup counter are server-initialised
        assert season["season_status"] == "PLANNING"
        assert season["gross_package_revenue_cents"] == 0
        assert season["retention_bonus_liability_cents"] == 0
        assert season["net_surplus_cents"] == 0
        assert season["capital_reserve_cents"] == 0
        assert season["capital_committed_cents"] == 0
        assert season["bed_nights_sold"] == 0
        assert season["in_house_guest_count"] == 0


class TestCabinEntityContract:
    """Cabins outlive seasons: their stored row and their required inputs."""

    def test_cabin_detail_get_returns_the_stored_row(self, client):
        """Reading a cabin back returns the posted name and capacity, ready and un-turned.

        PRD: "A new cabin starts `READY`, holds no project — `maintenance_project_code` is null and `maintenance_capital_cost_cents` is 0 — and has never had a turnover, so `last_turnover_completed_at` is null."

        Design: Corner/entities/cabin_detail_get_returns_the_stored_row
        """
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)

        fetched = validate_success(client.get_cabin(cabin["id"], RESERVATIONS_AGENT))

        assertions.assert_cabin(fetched)
        assert fetched["id"] == cabin["id"]
        assert fetched["name"] == "Aspen"
        assert fetched["bed_capacity"] == 4
        assert fetched["cabin_status"] == "READY"
        assert fetched["last_turnover_completed_at"] is None
        assert fetched["maintenance_project_code"] is None
        assert fetched["maintenance_capital_cost_cents"] == 0

    def test_cabin_create_without_bed_capacity_is_rejected(self, client):
        """A cabin registration that omits its bed capacity is refused and stores nothing.

        PRD: "Every field an endpoint declares as required must be present, or the request fails with `ERR_MISSING_REQUIRED_FIELD` (HTTP 400)."

        Design: Corner/entities/cabin_create_missing_required_bed_capacity_rejected
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)

        payload = create_cabin_payload(name="Aspen")
        payload.pop("bed_capacity")

        validate_error(
            client.create_cabin(payload, RANCH_MANAGER),
            ApiErrorId.ERR_MISSING_REQUIRED_FIELD.value,
            400,
        )

        rows, meta = validate_paginated(client.list_cabins(RANCH_MANAGER))
        assert meta["total_count"] == 0
        assert rows == []


class TestGuestEntityContract:
    """Guest rows: their listing envelope, their derived age and their version trail."""

    def test_guest_list_paginates_with_total_count_and_has_more(self, client):
        """Three stored guests page two at a time, oldest first, with an honest total.

        PRD: "List responses carry `response_type` of `"array"`, and their `meta` object additionally contains `limit` (the effective page size), `offset` (the effective skip), `total_count` (the number of rows matching the filters before pagination), and `has_more` (true when rows remain beyond the current page)."

        Design: Corner/entities/guest_list_paginates_with_total_count_and_has_more
        """
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
        cal = build_guest(client, "Cal Child", "2016-05-20", 95)

        first_response = client.list_guests(RESERVATIONS_AGENT, {"limit": 2, "offset": 0})
        page_one, meta_one = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert page_one[0]["full_name"] == "Ann Adult"

        second_response = client.list_guests(RESERVATIONS_AGENT, {"limit": 2, "offset": 2})
        page_two, meta_two = validate_paginated(second_response)
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2
        assert page_two[0]["full_name"] == "Cal Child"

        paged_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert len(paged_ids) == 3
        assert set(paged_ids) == {ann["id"], ben["id"], cal["id"]}

    def test_guest_age_years_is_derived_from_the_birth_date_and_the_clock(self, client):
        """Age is computed against the logical clock date, not supplied by the desk.

        PRD: "From `birth_date` the system derives `age_years`, the whole number of years between the birth date and the current clock date with any part-year discarded, and that number decides whether the guest is a minor for waiver purposes, whether they may be listed as an adult on a booking roster, and whether their presence on a ride raises the guide requirement."

        Design: Corner/entities/guest_age_and_booking_party_counts_are_computed_not_supplied
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)

        ann = validate_success(
            client.create_guest(
                create_guest_payload("Ann Adult", "1985-04-02", 165), RESERVATIONS_AGENT
            ),
            201,
        )
        ben = validate_success(
            client.create_guest(
                create_guest_payload("Ben Adult", "1983-07-11", 190), RESERVATIONS_AGENT
            ),
            201,
        )
        cal = validate_success(
            client.create_guest(
                create_guest_payload("Cal Child", "2016-05-20", 95), RESERVATIONS_AGENT
            ),
            201,
        )

        assert ann["age_years"] == 41
        assert ben["age_years"] == 43
        assert cal["age_years"] == 10

        assertions.assert_guest(ann)
        assert ann["waiver_status"] == "NONE"
        assert ann["effective_ability_rank"] == "UNASSESSED"

    def test_booking_party_counts_are_derived_from_the_roster(self, client):
        """Party size, adult and child counts and nights all come off the roster and window.

        PRD: "From the roster the system computes `party_size` as the number of elements, `adult_count` as the number of elements whose `member_type` is `ADULT`, and `child_count` as the number whose `member_type` is `CHILD`; from the window it computes `nights` as the whole number of days from `arrival_date` to `departure_date`."

        Design: Corner/entities/guest_age_and_booking_party_counts_are_computed_not_supplied
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
        cal = build_guest(client, "Cal Child", "2016-05-20", 95)

        booking = validate_success(
            client.create_booking(
                create_booking_payload(
                    season["id"],
                    cabin["id"],
                    ann["id"],
                    [
                        party_member(ann["id"], "ADULT"),
                        party_member(ben["id"], "ADULT"),
                        party_member(cal["id"], "CHILD"),
                    ],
                    "CLASSIC",
                    constants.ARRIVAL_DATE,
                    constants.DEPARTURE_DATE,
                ),
                RESERVATIONS_AGENT,
            ),
            201,
        )

        assertions.assert_booking(booking)
        assert booking["party_size"] == 3
        assert booking["adult_count"] == 2
        assert booking["child_count"] == 1
        assert booking["nights"] == 7
        assert booking["provisional_package_total_cents"] == 1258691

    def test_guest_version_advances_by_one_on_every_write(self, client):
        """The waiver write keeps id and created_at and raises version by exactly one.

        PRD: "Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation."

        Design: Corner/entities/guest_version_advances_by_one_on_every_write
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        created = validate_success(
            client.create_guest(
                create_guest_payload("Ann Adult", "1985-04-02", 165), RESERVATIONS_AGENT
            ),
            201,
        )
        assertions.assert_identity_fields(created)
        assert created["version"] == 1

        set_clock_to(client, "2026-08-02T09:00:00Z")

        signed = validate_success(
            client.sign_waiver(
                created["id"],
                waiver_signature_payload(signed_on="2026-08-02", equine_statute_ack=True),
                RESERVATIONS_AGENT,
            )
        )

        assert signed["id"] == created["id"]
        assert signed["version"] == created["version"] + 1
        assertions.assert_instant_equals(signed["created_at"], created["created_at"], "created_at")
        assert signed["updated_at"] != signed["created_at"]

        fetched = validate_success(client.get_guest(created["id"], RESERVATIONS_AGENT))
        assert fetched["waiver_status"] == "SIGNED"
        assert fetched["waiver_expires_on"] == "2027-08-02"
        assert fetched["version"] == created["version"] + 1


class TestHerdEntityContract:
    """The herd registry and its immutable care record."""

    def test_horse_creation_applies_declared_field_defaults(self, client):
        """A new horse arrives in service with an empty load ledger and no duty history.

        PRD: "A new horse is `IN_SERVICE` with `scheduled_load_hours`, `realized_load_hours` and `consecutive_duty_days` all at 0, and `last_duty_date` and `last_rest_started_on` both null."

        Design: Corner/entities/horse_creation_applies_declared_field_defaults
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)

        horse_row = validate_success(
            client.create_horse(
                create_horse_payload("Comet", "BEGINNER", "ADVANCED", 240),
                HORSE_PROGRAM_DIRECTOR,
            ),
            201,
        )

        assertions.assert_horse(horse_row)
        assert horse_row["horse_status"] == "IN_SERVICE"
        assertions.assert_horse_load(
            horse_row,
            scheduled_load_hours=0.0,
            realized_load_hours=0.0,
            consecutive_duty_days=0,
        )
        assert horse_row["last_duty_date"] is None
        assert horse_row["last_rest_started_on"] is None

    def test_horse_health_event_rows_are_immutable_and_carry_no_version(self, client):
        """A filed care record reads back with an identifier and a creation instant only.

        PRD: "It has no `updated_at` field and no `version` field at all, and neither field appears in its response payload."

        Design: Corner/entities/horse_health_event_rows_are_immutable_and_carry_no_version
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        horse_row = build_horse(client, "Comet", "BEGINNER", "ADVANCED", 240)

        filed = validate_success(
            client.create_health_event(
                horse_row["id"],
                health_event_payload("REST_START", "2026-08-01", "scheduled rest day"),
                HORSE_PROGRAM_DIRECTOR,
            ),
            201,
        )

        fetched = validate_success(
            client.get_health_event(filed["id"], HORSE_PROGRAM_DIRECTOR)
        )

        assertions.assert_horse_health_event(fetched)
        assert fetched["id"] == filed["id"]
        assert fetched["horse_id"] == horse_row["id"]
        assert fetched["event_type"] == "REST_START"
        assert fetched["resulting_horse_status"] == "REST"
        assertions.assert_no_version_fields(fetched)
        assertions.assert_no_version_fields(filed)

        after = validate_success(client.get_horse(horse_row["id"], HORSE_PROGRAM_DIRECTOR))
        assert after["horse_status"] == "REST"
        assert after["consecutive_duty_days"] == 0
        assert after["last_rest_started_on"] == "2026-08-01"


class TestActivitySlotEntityContract:
    """Slots hang off a season parent, and their enums are closed."""

    def test_activity_slot_create_with_unknown_terrain_grade_rejected(self, client):
        """A terrain grade outside the declared set is refused and no slot is stored.

        PRD: "Every field that is present must satisfy its declared type, its enum membership and its numeric range — dates in ISO 8601 form, cents as non-negative integers, percentages between 0 and 1 — or the request fails with `ERR_INVALID_FIELD_VALUE` (HTTP 422)."

        Design: Corner/entities/activity_slot_create_with_unknown_terrain_grade_rejected
        """
        season = build_open_season(client)

        validate_error(
            client.create_activity_slot(
                season["id"],
                create_activity_slot_payload(terrain_grade="CANYON"),
                RANCH_MANAGER,
            ),
            ApiErrorId.ERR_INVALID_FIELD_VALUE.value,
            422,
        )

        rows, meta = validate_paginated(
            client.list_activity_slots(RANCH_MANAGER, {"season_id": season["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_activity_slot_create_under_unknown_season_parent_not_found(self, client):
        """An unstored season in the path decides the answer before any field is read.

        PRD: "A request addressing an activity slot under a season, for instance, fails with `ERR_SEASON_NOT_FOUND` before the slot is even looked for."

        Design: Corner/entities/activity_slot_create_under_unknown_season_parent_not_found
        """
        season = build_open_season(client)

        validate_error(
            client.create_activity_slot(
                NON_EXISTENT_UUID, create_activity_slot_payload(), RANCH_MANAGER
            ),
            ApiErrorId.ERR_SEASON_NOT_FOUND.value,
            404,
        )

        rows, meta = validate_paginated(
            client.list_activity_slots(RANCH_MANAGER, {"season_id": season["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestBookingEntityContract:
    """Reading a stay that was never held."""

    def test_booking_detail_get_with_unknown_id_returns_not_found(self, client):
        """A well-formed but unstored booking id answers 404, never an empty success body.

        PRD: "Path identifiers are resolved strictly left to right, and the first identifier that resolves to nothing decides the response with HTTP 404."

        Design: Corner/entities/booking_detail_get_with_unknown_id_returns_not_found
        """
        build_season(client)

        error = validate_error(
            client.get_booking(NON_EXISTENT_UUID, RESERVATIONS_AGENT),
            ApiErrorId.ERR_BOOKING_NOT_FOUND.value,
            404,
        )
        assert error["message"].strip() != ""
