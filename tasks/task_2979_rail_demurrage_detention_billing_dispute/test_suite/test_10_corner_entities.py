"""Queue B - corner section ``entities``.

Twenty-four instances covering the shapes the reference layer must return: the
full declared field set on a create, the defaults a one-field create must
materialise, the derived and system fields a caller cannot write, the paginated
list envelope, and the eleven not-found codes of the PRD 2.8 existence bands.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AVERAGE_AGREEMENT_NOT_FOUND,
    ERR_BUNCHING_CLAIM_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_DEMURRAGE_CHARGE_NOT_FOUND,
    ERR_DEMURRAGE_DISPUTE_NOT_FOUND,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_FOUND,
    ERR_INVOICE_VERSION_STALE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PLACEMENT_CYCLE_NOT_FOUND,
    ERR_RAIL_CAR_NOT_FOUND,
    ERR_RAIL_CAR_VERSION_STALE,
    ERR_REGULATORY_COMPLAINT_NOT_FOUND,
    ERR_ROLE_FORBIDDEN,
    ERR_TARIFF_INVALID_STATE,
    ERR_TARIFF_RULE_SET_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_error_meta_is_minimal,
    assert_fields_present,
    assert_instant_eq,
    assert_light_fields,
    assert_ordered_by_created_at,
    assert_pagination_meta,
    assert_request_id_prefixed,
    assert_subset_equal,
    error_id_of,
    error_payload_of,
    ids_of,
)
from test_helpers.constants import (
    ACCESS_MODE_OPEN,
    AGREEMENT_MONTH,
    AGREEMENT_OPEN,
    BILLING_POSTURE_CURRENT,
    BILLING_UNBILLED,
    CAR_OWNERSHIP_SCOPE_ANY,
    CHANNEL_EDI,
    CLOCK_BASIS_ACTUAL,
    CLOCK_BASIS_NONE,
    CUSTOMER_STATUS_ACTIVE,
    CUSTOMER_STATUS_SUSPENDED,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_NOTICE_SENT_AT,
    DEFAULT_ADJUDICATION_DAYS_BASE,
    DEFAULT_CAPACITY_TONS,
    DEFAULT_CAR_SPOT_CAPACITY,
    DEFAULT_CAR_TYPE,
    DEFAULT_CREDIT_CAP_RATIO,
    DEFAULT_FREE_TIME_HOURS_PRIVATE,
    DEFAULT_FREE_TIME_HOURS_RAILROAD,
    DEFAULT_GATE_CLOSE_HOUR,
    DEFAULT_GATE_OPEN_HOUR,
    DEFAULT_NOTIFICATION_GRACE_HOURS,
    DEFAULT_NOTIFICATION_METHOD,
    DEFAULT_NORMAL_DAILY_PLACEMENT_CAPACITY,
    DEFAULT_OPERATES_WEEKENDS,
    DEFAULT_STORAGE_CLOCK_MODE,
    DEFAULT_STORAGE_DAILY_RATE_CENTS,
    DEFAULT_STORAGE_FREE_HOURS,
    DEFAULT_SWITCH_BUFFER_MINUTES,
    DEFAULT_TIER1_DAY_COUNT,
    DEFAULT_TIER1_RATE_PRIVATE,
    DEFAULT_TIER1_RATE_RAILROAD,
    DEFAULT_TIER2_DAY_COUNT,
    DEFAULT_TIER2_RATE_PRIVATE,
    DEFAULT_TIER2_RATE_RAILROAD,
    DEFAULT_TIER3_RATE_PRIVATE,
    DEFAULT_TIER3_RATE_RAILROAD,
    DEFAULT_WEEKEND_EXCLUDED,
    DELIVERY_DELIVERED,
    DISPUTE_POSTURE_CLEAR,
    EVIDENCE_SWITCH_LIST,
    FACILITY_KIND_INDUSTRY_TRACK,
    GROUNDS_RAILROAD_CAUSED_DELAY,
    MAX_LIMIT,
    MOVEMENT_CONSTRUCTIVELY_PLACED,
    MOVEMENT_ORDERED,
    NOTIFICATION_METHOD_EMAIL,
    OWNERSHIP_PRIVATE,
    OWNERSHIP_RAILROAD_OWNED,
    SCOPE_WHOLE_INVOICE,
    TARIFF_STATUS_DRAFT,
    TARIFF_STATUS_PUBLISHED,
)
from test_helpers.test_users import (
    ADMIN,
    AGENT,
    OFFICER,
    make_adjudicator_headers,
    make_customer_headers,
)

# --- well-formed identifiers that resolve to nothing ------------------------
ABSENT_CUSTOMER_ID = "00000000-0000-4000-8000-0000000000c1"
ABSENT_TARIFF_ID = "00000000-0000-4000-8000-0000000000c2"
ABSENT_FACILITY_ID = "00000000-0000-4000-8000-0000000000f1"
ABSENT_CAR_ID = "00000000-0000-4000-8000-0000000000a1"
ABSENT_CYCLE_ID = "00000000-0000-4000-8000-0000000000b1"
ABSENT_CHARGE_ID = "00000000-0000-4000-8000-0000000000d1"
ABSENT_INVOICE_ID = "00000000-0000-4000-8000-0000000000e1"
ABSENT_CLAIM_ID = "00000000-0000-4000-8000-0000000000b2"
ABSENT_DISPUTE_ID = "00000000-0000-4000-8000-0000000000d2"
ABSENT_AGREEMENT_ID = "00000000-0000-4000-8000-0000000000e2"
ABSENT_COMPLAINT_ID = "00000000-0000-4000-8000-0000000000f2"

# --- declared literals -----------------------------------------------------
CUSTOMER_CODE_FULL = "C9E1-CUST"
CUSTOMER_NAME_FULL = "Corner Creation Coal"
STATION_CODE_FULL = "STN30"
SUPPLIED_CAPACITY = 4

CAR_MARK_HOPPER = "C9E2-HOPX01"
CAR_TYPE_HOPPER = "HOPPER"
CAPACITY_TONS_HOPPER = 110

CUSTOMER_CODE_MISSING_FIELD = "C9E5-CUST"
TARIFF_CODE_DEFAULTS = "C9E6-6004"
FACILITY_CODE_DEFAULTS = "C9E7-TRK"
CAR_MARK_LEASED = "C9E10-LSX01"
UNKNOWN_OWNERSHIP = "LEASED"
NON_MULTIPLE_FREE_HOURS = 36
RATIO_ABOVE_ONE = 1.25
RATIO_AT_THE_BOUND = 1.00
RATIO_WITH_THREE_DECIMALS = 0.001
SECOND_AGREEMENT_MONTH = "2026-09"
THIRD_AGREEMENT_MONTH = "2026-10"

WAYBILL_ABSENT_FACILITY = "WB-C9E14-1"
WAYBILL_ABSENT_CAR = "WB-C9E15-1"
IGNORED_CHARGEABLE_DAYS = 99
IGNORED_CREDIT_BALANCE = 500000
ISSUE_CLOCK_R10I19 = "2026-08-15T00:00:00.000Z"
ADJUDICATOR_R10I20 = "adj-c9e20-a"
OBSERVED_AT_R10I21 = "2026-08-16T09:00:00.000Z"
UNKNOWN_CHANNEL = "TELEX"
CYCLES_PER_CUSTOMER = 3
PAGE_SIZE = 2
OVER_MAX_LIMIT = MAX_LIMIT + 1


# ===========================================================================
# instance: customer_create_returns_201_with_every_declared_field
# ===========================================================================
def test_the_customer_create_echoes_every_declared_field_not_only_the_inputs(api):
    """Five inputs go in; ten declared fields plus the four common ones come back.

    PRD 3.1: "A newly registered consignee has `status` `ACTIVE`,
    `billing_posture` `CURRENT`, `credit_hold_reason` null,
    `credit_balance_cents` zero and `dispute_posture` `CLEAR`."

    Design: Corner/entities/customer_create_returns_201_with_every_declared_field
    """
    created = get_success_data(
        api.create_customer(
            {
                "customer_code": CUSTOMER_CODE_FULL,
                "name": CUSTOMER_NAME_FULL,
                "serving_station_code": STATION_CODE_FULL,
                "notification_method": NOTIFICATION_METHOD_EMAIL,
                "normal_daily_placement_capacity": SUPPLIED_CAPACITY,
            },
            ADMIN,
        ),
        201,
    )

    assert_common_fields(created, expected_version=1)
    assert_subset_equal(
        created,
        {
            "customer_code": CUSTOMER_CODE_FULL,
            "name": CUSTOMER_NAME_FULL,
            "serving_station_code": STATION_CODE_FULL,
            "notification_method": NOTIFICATION_METHOD_EMAIL,
            "normal_daily_placement_capacity": SUPPLIED_CAPACITY,
            "status": CUSTOMER_STATUS_ACTIVE,
            "billing_posture": BILLING_POSTURE_CURRENT,
            "credit_hold_reason": None,
            "credit_balance_cents": 0,
            "dispute_posture": DISPUTE_POSTURE_CLEAR,
        },
    )
    # The three derived fields are present as values, not merely absent.
    assert_fields_present(
        created, ["credit_balance_cents", "dispute_posture", "billing_posture"]
    )
    assert created["created_at"] == created["updated_at"]

    # The read-back agrees with the create on every one of those fields.
    fetched = fx.get_customer(api, created["id"])
    assert fetched == created


# ===========================================================================
# instance: rail_car_get_by_id_returns_the_stored_row
# ===========================================================================
def test_the_rail_car_read_back_reproduces_the_create_and_bumps_no_version(api):
    """A GET is not a mutation, so version stays 1 and every field is unchanged.

    PRD 3.1: "A new car begins with `active_cycle_count` zero and `version` 1."

    Design: Corner/entities/rail_car_get_by_id_returns_the_stored_row
    """
    created = fx.make_rail_car(
        api,
        car_mark=CAR_MARK_HOPPER,
        ownership=OWNERSHIP_RAILROAD_OWNED,
        car_type=CAR_TYPE_HOPPER,
        capacity_tons=CAPACITY_TONS_HOPPER,
    )
    assert_common_fields(created, expected_version=1)

    fetched = get_success_data(api.get_rail_car(created["id"], AGENT))
    assert fetched == created
    assert_subset_equal(
        fetched,
        {
            "id": created["id"],
            "car_mark": CAR_MARK_HOPPER,
            "ownership": OWNERSHIP_RAILROAD_OWNED,
            "car_type": CAR_TYPE_HOPPER,
            "capacity_tons": CAPACITY_TONS_HOPPER,
            "active_cycle_count": 0,
            "version": 1,
        },
    )

    # Reading it a second time still does not write.
    again = get_success_data(api.get_rail_car(created["id"], AGENT))
    assert again["version"] == 1
    assert_instant_eq(again["updated_at"], created["updated_at"], "updated_at")


def _three_ordered_cycles_and_one_decoy(api):
    """Three ORDERED cycles for one consignee, plus a fourth for another.

    The decoy makes the whole table larger than the filtered set, so a
    ``total_count`` that counts rows rather than *matching* rows is visible.
    """
    world = fx.reference_world(api)
    mine = [fx.make_cycle(api, world) for _ in range(CYCLES_PER_CUSTOMER)]
    other = dict(world, customer_id=fx.make_customer(api)["id"])
    decoy = fx.make_cycle(api, other)
    for cycle in mine + [decoy]:
        assert cycle["movement_status"] == MOVEMENT_ORDERED
    return world, mine, decoy


# ===========================================================================
# instance: placement_cycles_list_returns_paginated_envelope_with_total_count
# ===========================================================================
def test_the_cycle_list_reports_the_filtered_total_and_pages_through_it(api):
    """total_count is 3 on both pages while the table holds 4 rows.

    PRD 2.3: "`total_count` reports the size of the full filtered result set,
    not the size of the returned page, and `has_more` is true exactly when rows
    remain beyond the current page."

    Design: Corner/entities/placement_cycles_list_returns_paginated_envelope_with_total_count
    """
    world, mine, decoy = _three_ordered_cycles_and_one_decoy(api)
    query = {
        "customer_id": world["customer_id"],
        "movement_status": MOVEMENT_ORDERED,
        "limit": PAGE_SIZE,
    }

    first = api.list_placement_cycles(ADMIN, dict(query, offset=0))
    page_one = get_success_data(first)
    assert first.status_code == 200
    assert len(page_one) == PAGE_SIZE
    assert_pagination_meta(
        first.json()["meta"],
        limit=PAGE_SIZE,
        offset=0,
        total_count=CYCLES_PER_CUSTOMER,
        has_more=True,
    )

    second = api.list_placement_cycles(ADMIN, dict(query, offset=PAGE_SIZE))
    page_two = get_success_data(second)
    assert len(page_two) == 1
    assert_pagination_meta(
        second.json()["meta"],
        limit=PAGE_SIZE,
        offset=PAGE_SIZE,
        total_count=CYCLES_PER_CUSTOMER,
        has_more=False,
    )

    # The two pages partition the filtered set, in stable order.
    walked = page_one + page_two
    assert_ordered_by_created_at(walked)
    assert len(set(ids_of(walked))) == CYCLES_PER_CUSTOMER
    assert set(ids_of(walked)) == {cycle["id"] for cycle in mine}
    for row in walked:
        assert row["movement_status"] == MOVEMENT_ORDERED
        assert row["customer_id"] == world["customer_id"]
    assert decoy["id"] not in ids_of(walked)

    # The filter really did narrow: the unfiltered table is larger.
    unfiltered = api.list_placement_cycles(ADMIN, {"limit": MAX_LIMIT})
    assert_pagination_meta(
        unfiltered.json()["meta"],
        total_count=CYCLES_PER_CUSTOMER + 1,
        has_more=False,
    )


# ===========================================================================
# instance: get_customer_unknown_id_returns_customer_not_found
# ===========================================================================
def test_an_unknown_customer_id_is_the_customer_not_found_code_and_not_a_400(api):
    """A well-formed UUID that resolves to nothing is 404, never a schema error.

    PRD 2.8: "Every identifier appearing in the URL path must resolve to a live
    row, resolved left to right along the path, or the addressed entity's own
    not-found code at HTTP 404."

    Design: Corner/entities/get_customer_unknown_id_returns_customer_not_found
    """
    missing = api.get_customer(ABSENT_CUSTOMER_ID, ADMIN)
    validate_error(missing, ERR_CUSTOMER_NOT_FOUND)
    assert missing.status_code == 404
    assert error_id_of(missing) != ERR_INVALID_REQUEST
    assert missing.status_code != 400

    # PRD 2.2: an error body carries only an error_id and a message.
    error = error_payload_of(missing)
    assert set(error.keys()) == {"error_id", "message"}
    assert isinstance(error["message"], str) and error["message"]
    assert_error_meta_is_minimal(missing)
    assert_request_id_prefixed(missing)

    # A live consignee at the same endpoint answers 200, so the path is right.
    live = fx.make_customer(api)
    assert fx.get_customer(api, live["id"])["id"] == live["id"]


# ===========================================================================
# instance: customer_create_missing_serving_station_code_returns_invalid_request
# ===========================================================================
def test_omitting_the_serving_station_code_is_a_schema_failure(api):
    """A field with no default is required; a field with one is not.

    PRD 2.8: "Field types, enum membership, string lengths and character sets,
    numeric ranges, and the required-field set must all be satisfied, or
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/customer_create_missing_serving_station_code_returns_invalid_request
    """
    refused = api.create_customer(
        {"customer_code": CUSTOMER_CODE_MISSING_FIELD, "name": "Missing Field Marl"},
        ADMIN,
    )
    validate_error(refused, ERR_INVALID_REQUEST)
    assert refused.status_code == 400
    assert_error_meta_is_minimal(refused)

    # The two genuinely optional operational parameters may still be omitted,
    # and they arrive as their declared defaults.
    accepted = get_success_data(
        api.create_customer(
            {
                "customer_code": CUSTOMER_CODE_MISSING_FIELD,
                "name": "Missing Field Marl",
                "serving_station_code": STATION_CODE_FULL,
            },
            ADMIN,
        ),
        201,
    )
    assert_subset_equal(
        accepted,
        {
            "customer_code": CUSTOMER_CODE_MISSING_FIELD,
            "serving_station_code": STATION_CODE_FULL,
            "notification_method": DEFAULT_NOTIFICATION_METHOD,
            "normal_daily_placement_capacity": (
                DEFAULT_NORMAL_DAILY_PLACEMENT_CAPACITY
            ),
        },
    )
    # The refused create reserved nothing: the same code was still free.
    assert accepted["customer_code"] == CUSTOMER_CODE_MISSING_FIELD


# ===========================================================================
# instance: tariff_rule_set_create_omitting_optionals_applies_declared_defaults
# ===========================================================================
def test_a_one_field_tariff_create_materialises_the_whole_rate_ladder(api):
    """Fifteen optional parameters, fifteen defaults - not fifteen nulls.

    PRD 3.1: "A new rule set carries a `tariff_code` of 1 to 16 characters - the
    publication code, such as 6004-C - and may specify any of fifteen further
    parameters, each of which takes a default when omitted."

    PRD 3.1: "A rule set is born `DRAFT` with `challenge_count` zero and is not
    usable until it is published."

    Design: Corner/entities/tariff_rule_set_create_omitting_optionals_applies_declared_defaults
    """
    created = get_success_data(
        api.create_tariff_rule_set({"tariff_code": TARIFF_CODE_DEFAULTS}, OFFICER), 201
    )
    assert_common_fields(created, expected_version=1)
    assert_subset_equal(
        created,
        {
            "tariff_code": TARIFF_CODE_DEFAULTS,
            "car_ownership_scope": CAR_OWNERSHIP_SCOPE_ANY,
            "free_time_hours_railroad": DEFAULT_FREE_TIME_HOURS_RAILROAD,
            "free_time_hours_private": DEFAULT_FREE_TIME_HOURS_PRIVATE,
            "tier1_day_count": DEFAULT_TIER1_DAY_COUNT,
            "tier2_day_count": DEFAULT_TIER2_DAY_COUNT,
            "tier1_rate_cents_railroad": DEFAULT_TIER1_RATE_RAILROAD,
            "tier2_rate_cents_railroad": DEFAULT_TIER2_RATE_RAILROAD,
            "tier3_rate_cents_railroad": DEFAULT_TIER3_RATE_RAILROAD,
            "tier1_rate_cents_private": DEFAULT_TIER1_RATE_PRIVATE,
            "tier2_rate_cents_private": DEFAULT_TIER2_RATE_PRIVATE,
            "tier3_rate_cents_private": DEFAULT_TIER3_RATE_PRIVATE,
            "weekend_excluded": DEFAULT_WEEKEND_EXCLUDED,
            "notification_grace_hours": DEFAULT_NOTIFICATION_GRACE_HOURS,
            "adjudication_days_base": DEFAULT_ADJUDICATION_DAYS_BASE,
            "status": TARIFF_STATUS_DRAFT,
            "challenge_count": 0,
        },
    )
    # Every rate is an integer count of cents (PRD 2.6), never a decimal.
    for field in (
        "tier1_rate_cents_railroad",
        "tier2_rate_cents_railroad",
        "tier3_rate_cents_railroad",
        "tier1_rate_cents_private",
        "tier2_rate_cents_private",
        "tier3_rate_cents_private",
    ):
        assert isinstance(created[field], int)
    assert created["weekend_excluded"] is False

    fetched = get_success_data(api.get_tariff_rule_set(created["id"], OFFICER))
    assert fetched == created


# ===========================================================================
# instance: facility_create_omitting_optionals_applies_declared_defaults
# ===========================================================================
def test_a_one_field_facility_create_carries_both_later_gates(api):
    """gate_close_hour 16 and switch_buffer_minutes 120 are present from birth.

    PRD 3.1: "The payload carries a `facility_code` of 1 to 16 characters, unique
    across facilities, and then a run of optional parameters: `kind` itself,
    defaulting to `INDUSTRY_TRACK`; `storage_clock_mode`, either
    `CALENDAR_DAY_MIDNIGHT` (the default) or `HOURLY_FROM_ARRIVAL`, and entirely
    ignored when the facility is an industry track; `gate_open_hour` and
    `gate_close_hour`, each a UTC hour from 0 to 23 and defaulting to 7 and 16
    respectively; `car_spot_capacity`, at least 1 and defaulting to 3;
    `switch_buffer_minutes`, zero or greater and defaulting to 120 - that is, two
    hours; `storage_free_hours`, a multiple of 24 between 0 and 240 and defaulting
    to 48, which is two free days; `storage_daily_rate_cents`, zero or greater and
    defaulting to 9000 cents per storage day; and `operates_weekends`, a boolean
    defaulting to false."

    PRD 3.1: "A new facility has `access_mode` `OPEN`, `access_mode_reason` null,
    `occupied_spot_count` zero and `last_switch_at` null."

    Design: Corner/entities/facility_create_omitting_optionals_applies_declared_defaults
    """
    created = get_success_data(
        api.create_facility({"facility_code": FACILITY_CODE_DEFAULTS}, ADMIN), 201
    )
    assert_common_fields(created, expected_version=1)
    assert_subset_equal(
        created,
        {
            "facility_code": FACILITY_CODE_DEFAULTS,
            "kind": FACILITY_KIND_INDUSTRY_TRACK,
            "storage_clock_mode": DEFAULT_STORAGE_CLOCK_MODE,
            "gate_open_hour": DEFAULT_GATE_OPEN_HOUR,
            "gate_close_hour": DEFAULT_GATE_CLOSE_HOUR,
            "car_spot_capacity": DEFAULT_CAR_SPOT_CAPACITY,
            "switch_buffer_minutes": DEFAULT_SWITCH_BUFFER_MINUTES,
            "storage_free_hours": DEFAULT_STORAGE_FREE_HOURS,
            "storage_daily_rate_cents": DEFAULT_STORAGE_DAILY_RATE_CENTS,
            "operates_weekends": DEFAULT_OPERATES_WEEKENDS,
            "access_mode": ACCESS_MODE_OPEN,
            "access_mode_reason": None,
            "occupied_spot_count": 0,
            "last_switch_at": None,
        },
    )
    assert created["operates_weekends"] is False
    # The posture probe of PRD 3.1 reads the same figures back.
    probed = fx.probe_facility(api, created["id"])
    assert_subset_equal(
        probed,
        {
            "gate_close_hour": DEFAULT_GATE_CLOSE_HOUR,
            "switch_buffer_minutes": DEFAULT_SWITCH_BUFFER_MINUTES,
            "occupied_spot_count": 0,
            "last_switch_at": None,
        },
    )


# ===========================================================================
# instance: placement_cycle_create_with_chargeable_days_in_body_input_ignored
# ===========================================================================
def test_the_computed_cycle_fields_ignore_whatever_the_body_supplied(api):
    """chargeable_days 99 and clock_basis ACTUAL go in; 0 and NONE come back.

    PRD 3.2: "A freshly created cycle also has `clock_basis` `NONE`,
    `refusal_count` zero, `free_days` zero, `chargeable_days` zero,
    `early_release_days` zero, and null in each of `constructive_placement_at`,
    `constructive_reason_code`, `notification_sent_at`,
    `notification_acknowledged_at`, `actual_placement_at`, `released_at`,
    `clock_start_at` and `free_time_expires_at`."

    Design: Corner/entities/placement_cycle_create_with_chargeable_days_in_body_input_ignored
    """
    world = fx.reference_world(api)
    car = fx.make_rail_car(api, ownership=OWNERSHIP_RAILROAD_OWNED)
    payload = f.placement_cycle_payload(
        world["customer_id"],
        car["id"],
        world["facility_id"],
        world["tariff_id"],
        car["version"],
        chargeable_days=IGNORED_CHARGEABLE_DAYS,
        clock_basis=CLOCK_BASIS_ACTUAL,
    )

    created = get_success_data(api.create_placement_cycle(payload, AGENT), 201)
    expected = {
        "chargeable_days": 0,
        "clock_basis": CLOCK_BASIS_NONE,
        "free_days": 0,
        "free_time_expires_at": None,
        "clock_start_at": None,
        "early_release_days": 0,
        "refusal_count": 0,
        "movement_status": MOVEMENT_ORDERED,
        "billing_status": BILLING_UNBILLED,
    }
    assert_subset_equal(created, expected)
    assert created["chargeable_days"] != IGNORED_CHARGEABLE_DAYS
    assert created["clock_basis"] != CLOCK_BASIS_ACTUAL

    # The values were ignored, not merely masked on the create response.
    assert_subset_equal(fx.get_cycle(api, created["id"]), expected)
    # No charge line exists yet either: PRD 3.2 births it at constructive placement.
    assert fx.charges_of_cycle(api, created["id"]) == []


# ===========================================================================
# instance: customer_create_with_status_in_body_input_ignored
# ===========================================================================
def test_a_consignee_cannot_self_impose_a_credit_hold_at_creation(api):
    """SUSPENDED and CREDIT_HOLD are asked for and neither is honoured.

    PRD 3.1: "The `status` field also admits the value `SUSPENDED`, but no
    operation in this service ever writes it - the member is reserved."

    Design: Corner/entities/customer_create_with_status_in_body_input_ignored
    """
    created = get_success_data(
        api.create_customer(
            {
                "customer_code": "C9E9-CUST",
                "name": "System Field Slag",
                "serving_station_code": "STN33",
                "status": CUSTOMER_STATUS_SUSPENDED,
                "billing_posture": "CREDIT_HOLD",
                "credit_balance_cents": IGNORED_CREDIT_BALANCE,
            },
            ADMIN,
        ),
        201,
    )

    assert_subset_equal(
        created,
        {
            "status": CUSTOMER_STATUS_ACTIVE,
            "billing_posture": BILLING_POSTURE_CURRENT,
            "credit_hold_reason": None,
            "credit_balance_cents": 0,
        },
    )
    assert created["status"] != CUSTOMER_STATUS_SUSPENDED
    assert created["credit_balance_cents"] != IGNORED_CREDIT_BALANCE
    # The four common fields are server-stamped, whatever the body asked for.
    assert_common_fields(created, expected_version=1)
    assert_subset_equal(fx.get_customer(api, created["id"]), {"version": 1})


# ===========================================================================
# instance: rail_car_create_with_unknown_ownership_enum_returns_invalid_request
# ===========================================================================
def test_an_unknown_ownership_member_is_refused_and_never_coerced(api):
    """LEASED is a schema failure, not a quiet synonym for PRIVATE.

    PRD 3.1: "Each carries a `car_mark`, the reporting mark plus number in 1 to 16
    characters and unique across cars, and an `ownership` value that is mandatory
    and is one of `RAILROAD_OWNED`, `PRIVATE` or `PRIVATE_ASSIGNED`."

    Design: Corner/entities/rail_car_create_with_unknown_ownership_enum_returns_invalid_request
    """
    refused = api.create_rail_car(
        {"car_mark": CAR_MARK_LEASED, "ownership": UNKNOWN_OWNERSHIP}, AGENT
    )
    validate_error(refused, ERR_INVALID_REQUEST)
    assert refused.status_code == 400
    assert_error_meta_is_minimal(refused)

    # The mandatory field is genuinely mandatory, too.
    omitted = api.create_rail_car({"car_mark": CAR_MARK_LEASED}, AGENT)
    validate_error(omitted, ERR_INVALID_REQUEST)

    # A declared member with the same car_mark is accepted, so the code was free
    # and the two refusals really did coerce nothing onto the private ladder.
    accepted = fx.make_rail_car(
        api, car_mark=CAR_MARK_LEASED, ownership=OWNERSHIP_PRIVATE
    )
    assert_subset_equal(
        accepted,
        {
            "car_mark": CAR_MARK_LEASED,
            "ownership": OWNERSHIP_PRIVATE,
            "car_type": DEFAULT_CAR_TYPE,
            "capacity_tons": DEFAULT_CAPACITY_TONS,
            "active_cycle_count": 0,
        },
    )


# ===========================================================================
# instance: tariff_free_time_hours_not_a_multiple_of_24_returns_invalid_request
# ===========================================================================
def test_free_time_hours_inside_the_range_but_off_the_divisor_is_refused(api):
    """36 is between 0 and 240 and still illegal, because 36 is not 24 times n.

    PRD 3.1: "Both must be multiples of 24 in the range 0 to 240, and the free-day
    count actually used is the hours divided by 24 with any remainder discarded - a
    division that is exact only because of the multiple-of-24 constraint."

    Design: Corner/entities/tariff_free_time_hours_not_a_multiple_of_24_returns_invalid_request
    """
    refused = api.create_tariff_rule_set(
        {
            "tariff_code": "C9E11-6004",
            "free_time_hours_railroad": NON_MULTIPLE_FREE_HOURS,
        },
        OFFICER,
    )
    validate_error(refused, ERR_INVALID_REQUEST)
    assert refused.status_code == 400
    assert_error_meta_is_minimal(refused)
    assert 0 <= NON_MULTIPLE_FREE_HOURS <= 240

    # The divisor is the rule, not the range: both neighbours on the grid pass.
    for hours in (DEFAULT_FREE_TIME_HOURS_PRIVATE, DEFAULT_FREE_TIME_HOURS_RAILROAD):
        accepted = fx.make_draft_tariff(api, free_time_hours_railroad=hours)
        assert accepted["free_time_hours_railroad"] == hours
        assert accepted["status"] == TARIFF_STATUS_DRAFT


# ===========================================================================
# instance: average_agreement_credit_cap_ratio_above_one_returns_invalid_request
# ===========================================================================
def test_the_credit_cap_ratio_is_bounded_above_by_one_and_below_by_two_decimals(api):
    """1.25 is refused, 1.00 is legal and 0.001 is refused for its third decimal.

    PRD 3.7: "A `BillingAdmin` enrols a consignee by supplying its `customer_id`,
    an `agreement_month` in `YYYY-MM` form matching the pattern
    `^[0-9]{4}-(0[1-9]|1[0-2])$`, and optionally a `credit_cap_ratio` - greater
    than 0, at most 1, carrying at most two decimal places, and defaulting to 0.30
    - which bounds the fraction of the month's invoice gross that agreement credit
    may absorb."

    Design: Corner/entities/average_agreement_credit_cap_ratio_above_one_returns_invalid_request
    """
    customer = fx.make_customer(api)
    above = api.create_average_agreement(
        {
            "customer_id": customer["id"],
            "agreement_month": AGREEMENT_MONTH,
            "credit_cap_ratio": RATIO_ABOVE_ONE,
        },
        ADMIN,
    )
    validate_error(above, ERR_INVALID_REQUEST)
    assert above.status_code == 400
    assert_error_meta_is_minimal(above)

    # 1 is inside the bound, because the upper end is inclusive.
    at_bound = fx.open_agreement(
        api,
        customer["id"],
        agreement_month=AGREEMENT_MONTH,
        credit_cap_ratio=RATIO_AT_THE_BOUND,
    )
    assert at_bound["credit_cap_ratio"] == RATIO_AT_THE_BOUND
    assert_subset_equal(
        at_bound,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": 0,
            "debit_days_incurred": 0,
            "net_days": 0,
            "agreement_credit_cents": 0,
        },
    )

    # A third decimal place is refused even though 0.001 is inside the range.
    too_precise = api.create_average_agreement(
        {
            "customer_id": customer["id"],
            "agreement_month": SECOND_AGREEMENT_MONTH,
            "credit_cap_ratio": RATIO_WITH_THREE_DECIMALS,
        },
        ADMIN,
    )
    validate_error(too_precise, ERR_INVALID_REQUEST)
    assert 0 < RATIO_WITH_THREE_DECIMALS < RATIO_AT_THE_BOUND

    # Omitting it entirely takes the declared default.
    defaulted = fx.open_agreement(
        api, customer["id"], agreement_month=THIRD_AGREEMENT_MONTH
    )
    assert defaulted["credit_cap_ratio"] == DEFAULT_CREDIT_CAP_RATIO


# ===========================================================================
# instance: car_notification_is_immutable_with_no_version_and_no_write_endpoint
# ===========================================================================
def test_the_arrival_notice_row_is_append_only_and_carries_no_version(api):
    """A notice is one of the two light resources: id and created_at, nothing more.

    PRD 2.4: "Two resources are deliberately lighter: a car notification and a
    piece of dispute evidence carry only `id` and `created_at` - neither has an
    `updated_at` and neither has a `version`, because neither is ever mutated in
    place except for the single acknowledgement transition described in §3.3."

    Design: Corner/entities/car_notification_is_immutable_with_no_version_and_no_write_endpoint
    """
    world = fx.reference_world(api)
    cycle = fx.noticed_cycle(api, world)
    assert cycle["movement_status"] == MOVEMENT_CONSTRUCTIVELY_PLACED

    listed = api.list_notifications(cycle["id"], AGENT, {"limit": 10, "offset": 0})
    rows = get_success_data(listed)
    assert_pagination_meta(
        listed.json()["meta"], limit=10, offset=0, total_count=1, has_more=False
    )
    assert len(rows) == 1

    notice = rows[0]
    assert_light_fields(notice)
    assert_fields_present(
        notice,
        [
            "id",
            "placement_cycle_id",
            "channel",
            "sent_at",
            "delivery_status",
            "acknowledged_at",
            "sequence_number",
        ],
    )
    assert_subset_equal(
        notice,
        {
            "placement_cycle_id": cycle["id"],
            "channel": CHANNEL_EDI,
            "delivery_status": DELIVERY_DELIVERED,
            "acknowledged_at": None,
            "sequence_number": 1,
        },
    )
    assert_instant_eq(notice["sent_at"], CYCLE_A_NOTICE_SENT_AT, "sent_at")
    # The mutation the domain does allow lives on the cycle, not on the row.
    assert cycle["version"] > 1


# ===========================================================================
# instance: placement_cycle_create_with_unknown_facility_id_returns_facility_not_found
# ===========================================================================
def test_an_unknown_facility_in_the_body_is_a_404_and_writes_nothing(api):
    """Every other reference resolves; the one that does not names its own code.

    PRD 2.8: "Every foreign reference in the request body must resolve, or the
    referenced entity's own not-found code at HTTP 404."

    Design: Corner/entities/placement_cycle_create_with_unknown_facility_id_returns_facility_not_found
    """
    world = fx.reference_world(api)
    car = fx.make_rail_car(api)
    payload = f.placement_cycle_payload(
        world["customer_id"],
        car["id"],
        ABSENT_FACILITY_ID,
        world["tariff_id"],
        car["version"],
        waybill_number=WAYBILL_ABSENT_FACILITY,
    )

    missing = api.create_placement_cycle(payload, AGENT)
    validate_error(missing, ERR_FACILITY_NOT_FOUND)
    assert missing.status_code == 404
    assert error_id_of(missing) != ERR_INVALID_REQUEST
    assert_error_meta_is_minimal(missing)

    # The OCC token was not consumed and the car never left the free pool.
    untouched = fx.get_car(api, car["id"])
    assert untouched["version"] == car["version"]
    assert untouched["active_cycle_count"] == 0

    # No half-built cycle is sitting behind that waybill.
    listed = get_success_data(api.list_placement_cycles(AGENT, {"limit": 10, "offset": 0}))
    assert WAYBILL_ABSENT_FACILITY not in [row["waybill_number"] for row in listed]
    assert listed == []

    # Point the same payload at the real track and it is accepted.
    payload["facility_id"] = world["facility_id"]
    created = get_success_data(api.create_placement_cycle(payload, AGENT), 201)
    assert created["facility_id"] == world["facility_id"]
    assert created["waybill_number"] == WAYBILL_ABSENT_FACILITY


# ===========================================================================
# instance: placement_cycle_create_with_unknown_rail_car_id_returns_rail_car_not_found
# ===========================================================================
def test_an_unknown_car_is_a_404_and_never_an_optimistic_concurrency_failure(api):
    """Existence is asked before the version, so a stale token cannot mask the 404.

    PRD 2.8: "Where §2.7 requires a parent version, the presented value must
    match, or the rule's 412 code. Placing this band below existence and state but
    above every business rule is deliberate: a stale reader is told its read is
    stale before it is told about a conflict it could not possibly have seen."

    Design: Corner/entities/placement_cycle_create_with_unknown_rail_car_id_returns_rail_car_not_found
    """
    world = fx.reference_world(api)
    payload = f.placement_cycle_payload(
        world["customer_id"],
        ABSENT_CAR_ID,
        world["facility_id"],
        world["tariff_id"],
        1,
        waybill_number=WAYBILL_ABSENT_CAR,
    )

    missing = api.create_placement_cycle(payload, AGENT)
    validate_error(missing, ERR_RAIL_CAR_NOT_FOUND)
    assert missing.status_code == 404
    assert error_id_of(missing) != ERR_RAIL_CAR_VERSION_STALE
    assert missing.status_code != 412

    # A deliberately wrong token on the same absent car still reports the 404.
    payload["expected_rail_car_version"] = 99
    also_missing = api.create_placement_cycle(payload, AGENT)
    validate_error(also_missing, ERR_RAIL_CAR_NOT_FOUND)
    assert error_id_of(also_missing) != ERR_RAIL_CAR_VERSION_STALE

    # On a car that does exist, the very same wrong token reaches the 412 band.
    car = fx.make_rail_car(api)
    payload["rail_car_id"] = car["id"]
    stale = api.create_placement_cycle(payload, AGENT)
    validate_error(stale, ERR_RAIL_CAR_VERSION_STALE)
    assert stale.status_code == 412

    listed = get_success_data(api.list_placement_cycles(AGENT, {"limit": 10, "offset": 0}))
    assert listed == []
    assert fx.get_car(api, car["id"])["version"] == car["version"]


# ===========================================================================
# instance: publish_unknown_tariff_rule_set_returns_tariff_rule_set_not_found
# ===========================================================================
def test_publishing_an_absent_tariff_is_a_404_and_not_a_state_conflict(api):
    """Path existence is band 6 and the state test is band 10, so the 404 wins.

    PRD 2.8: "Every identifier appearing in the URL path must resolve to a live
    row, resolved left to right along the path, or the addressed entity's own
    not-found code at HTTP 404."

    Design: Corner/entities/publish_unknown_tariff_rule_set_returns_tariff_rule_set_not_found
    """
    missing = api.publish_tariff_rule_set(ABSENT_TARIFF_ID, OFFICER)
    validate_error(missing, ERR_TARIFF_RULE_SET_NOT_FOUND)
    assert missing.status_code == 404
    assert error_id_of(missing) != ERR_TARIFF_INVALID_STATE
    assert missing.status_code != 409
    assert_error_meta_is_minimal(missing)
    assert_request_id_prefixed(missing)

    # On a row that exists, the state band is reachable - which is what proves the
    # 404 above was existence and not a disguised state refusal.
    tariff = fx.make_draft_tariff(api, tariff_code=TARIFF_CODE_DEFAULTS)
    published = get_success_data(api.publish_tariff_rule_set(tariff["id"], OFFICER))
    assert published["status"] == TARIFF_STATUS_PUBLISHED

    again = api.publish_tariff_rule_set(tariff["id"], OFFICER)
    validate_error(again, ERR_TARIFF_INVALID_STATE)
    assert again.status_code == 409


# ===========================================================================
# instance: notify_unknown_placement_cycle_returns_placement_cycle_not_found
# ===========================================================================
def test_an_absent_cycle_in_the_path_outranks_even_an_invalid_body(api):
    """The 404 is reported whether the body is well-formed or itself illegal.

    PRD 2.8: "Field types, enum membership, string lengths and character sets,
    numeric ranges, and the required-field set must all be satisfied, or
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/notify_unknown_placement_cycle_returns_placement_cycle_not_found
    """
    good_body = f.notify_payload()
    missing = api.notify(ABSENT_CYCLE_ID, good_body, AGENT)
    validate_error(missing, ERR_PLACEMENT_CYCLE_NOT_FOUND)
    assert missing.status_code == 404
    assert_error_meta_is_minimal(missing)

    # An unknown channel on the same absent path still reports the 404, because
    # path existence is asked before the schema band.
    bad_body = f.notify_payload(channel=UNKNOWN_CHANNEL)
    both_wrong = api.notify(ABSENT_CYCLE_ID, bad_body, AGENT)
    validate_error(both_wrong, ERR_PLACEMENT_CYCLE_NOT_FOUND)
    assert error_id_of(both_wrong) != ERR_INVALID_REQUEST

    # On a live cycle the same illegal channel does reach the schema band.
    world = fx.reference_world(api)
    cycle = fx.constructively_placed_cycle(api, world)
    refused = api.notify(cycle["id"], bad_body, AGENT)
    validate_error(refused, ERR_INVALID_REQUEST)
    assert refused.status_code == 400

    # Nothing was recorded against the live cycle by that refusal.
    rows = get_success_data(api.list_notifications(cycle["id"], AGENT, {"limit": 10, "offset": 0}))
    assert rows == []
    assert fx.get_cycle(api, cycle["id"])["notification_sent_at"] is None


# ===========================================================================
# instance: get_charge_unknown_id_returns_demurrage_charge_not_found
# ===========================================================================
def test_an_unknown_charge_id_reports_the_charge_specific_not_found_code(api):
    """The code names the charge, not some generic resource, and the ledger is empty.

    PRD 2.8: "Every identifier appearing in the URL path must resolve to a live
    row, resolved left to right along the path, or the addressed entity's own
    not-found code at HTTP 404."

    Design: Corner/entities/get_charge_unknown_id_returns_demurrage_charge_not_found
    """
    missing = api.get_charge(ABSENT_CHARGE_ID, ADMIN)
    validate_error(missing, ERR_DEMURRAGE_CHARGE_NOT_FOUND)
    assert missing.status_code == 404
    assert set(error_payload_of(missing).keys()) == {"error_id", "message"}
    assert error_payload_of(missing)["message"]
    assert_error_meta_is_minimal(missing)
    assert_request_id_prefixed(missing)

    # There is genuinely no charge behind that id: the whole ledger is empty.
    listed = api.list_charges(ADMIN, {"limit": 10, "offset": 0})
    assert get_success_data(listed) == []
    assert_pagination_meta(listed.json()["meta"], total_count=0, has_more=False)


# ===========================================================================
# instance: dispute_create_with_unknown_invoice_id_returns_invoice_not_found
# ===========================================================================
def test_an_unknown_invoice_in_a_dispute_body_never_reaches_the_version_band(api):
    """The token in the body is perfectly valid; there is simply no row to match it.

    PRD 2.8: "Every foreign reference in the request body must resolve, or the
    referenced entity's own not-found code at HTTP 404."

    Design: Corner/entities/dispute_create_with_unknown_invoice_id_returns_invoice_not_found
    """
    world = fx.reference_world(api)
    fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_R10I19)
    consignee = make_customer_headers(world["customer_id"])

    payload = f.dispute_payload(
        ABSENT_INVOICE_ID,
        invoice["version"],
        CYCLE_A_GROSS_CENTS,
        scope=SCOPE_WHOLE_INVOICE,
        grounds=GROUNDS_RAILROAD_CAUSED_DELAY,
    )
    missing = api.create_dispute(payload, consignee)
    validate_error(missing, ERR_INVOICE_NOT_FOUND)
    assert missing.status_code == 404
    assert error_id_of(missing) != ERR_INVOICE_VERSION_STALE
    assert missing.status_code != 412
    assert_error_meta_is_minimal(missing)

    # The real invoice was neither counted against nor bumped.
    untouched = fx.get_invoice(api, invoice["id"])
    assert untouched["dispute_count"] == 0
    assert untouched["version"] == invoice["version"]
    assert get_success_data(api.list_disputes(ADMIN, {"limit": 10, "offset": 0})) == []

    # The same body, redirected at the row that exists, is accepted - so the
    # version token really was current all along.
    payload["invoice_id"] = invoice["id"]
    filed = get_success_data(api.create_dispute(payload, consignee), 201)
    assert filed["invoice_id"] == invoice["id"]
    assert fx.get_invoice(api, invoice["id"])["dispute_count"] == 1


# ===========================================================================
# instance: analyze_unknown_bunching_claim_returns_bunching_claim_not_found
# ===========================================================================
def test_the_role_band_is_asked_before_the_claim_is_looked_up(api):
    """The adjudicator gets a 404; the agent gets a 403 on the identical path.

    PRD 2.8: "The caller's role must appear in the endpoint's authorized-role
    list, or `ERR_ROLE_FORBIDDEN`. This applies to every endpoint."

    Design: Corner/entities/analyze_unknown_bunching_claim_returns_bunching_claim_not_found
    """
    adjudicator = make_adjudicator_headers(ADJUDICATOR_R10I20)

    missing = api.analyze_bunching_claim(ABSENT_CLAIM_ID, adjudicator)
    validate_error(missing, ERR_BUNCHING_CLAIM_NOT_FOUND)
    assert missing.status_code == 404
    assert error_id_of(missing) != ERR_ROLE_FORBIDDEN
    assert_error_meta_is_minimal(missing)
    assert_request_id_prefixed(missing)

    # A role outside the permitted set never learns whether the claim exists.
    forbidden = api.analyze_bunching_claim(ABSENT_CLAIM_ID, AGENT)
    validate_error(forbidden, ERR_ROLE_FORBIDDEN)
    assert forbidden.status_code == 403
    assert error_id_of(forbidden) != ERR_BUNCHING_CLAIM_NOT_FOUND


# ===========================================================================
# instance: evidence_on_unknown_dispute_returns_demurrage_dispute_not_found
# ===========================================================================
def test_an_absent_dispute_cannot_fail_the_ownership_band_that_precedes_it(api):
    """Ownership is asked earlier, but its violation condition needs a resolved owner.

    PRD 2.8: "Every endpoint therefore evaluates its applicable checks in one
    fixed global order, and **the first check whose violation condition holds wins
    and short-circuits the rest** - no response ever reports two violations."

    Design: Corner/entities/evidence_on_unknown_dispute_returns_demurrage_dispute_not_found
    """
    customer = fx.make_customer(api)
    consignee = make_customer_headers(customer["id"])
    payload = f.evidence_payload(OBSERVED_AT_R10I21, EVIDENCE_SWITCH_LIST)

    missing = api.create_evidence(ABSENT_DISPUTE_ID, payload, consignee)
    validate_error(missing, ERR_DEMURRAGE_DISPUTE_NOT_FOUND)
    assert missing.status_code == 404
    # There is no resolved owner to compare against, so band 4 cannot fire.
    assert error_id_of(missing) != ERR_NOT_RESOURCE_OWNER
    assert missing.status_code != 403
    assert set(error_payload_of(missing).keys()) == {"error_id", "message"}
    assert_error_meta_is_minimal(missing)

    # The exhibit was not filed anywhere: the listing on the same absent id is a
    # 404 too, not an empty page.
    listed = api.list_evidence(ABSENT_DISPUTE_ID, consignee, {"limit": 10, "offset": 0})
    validate_error(listed, ERR_DEMURRAGE_DISPUTE_NOT_FOUND)
    assert listed.status_code == 404


# ===========================================================================
# instance: reconcile_unknown_average_agreement_returns_average_agreement_not_found
# ===========================================================================
def test_reconciling_an_absent_agreement_reports_the_agreement_not_found_code(api):
    """A settlement verb on a path that resolves to nothing settles nothing.

    PRD 2.8: "Every identifier appearing in the URL path must resolve to a live
    row, resolved left to right along the path, or the addressed entity's own
    not-found code at HTTP 404."

    Design: Corner/entities/reconcile_unknown_average_agreement_returns_average_agreement_not_found
    """
    missing = api.reconcile_average_agreement(ABSENT_AGREEMENT_ID, ADMIN)
    validate_error(missing, ERR_AVERAGE_AGREEMENT_NOT_FOUND)
    assert missing.status_code == 404
    assert error_payload_of(missing)["message"]
    assert_error_meta_is_minimal(missing)
    assert_request_id_prefixed(missing)

    # A live consignee has no agreement either, so nothing was created as a
    # side effect of the failed reconciliation.
    customer = fx.make_customer(api)
    assert fx.agreements_of(api, customer["id"]) == []


# ===========================================================================
# instance: answer_unknown_regulatory_complaint_returns_regulatory_complaint_not_found
# ===========================================================================
def test_answering_an_absent_complaint_reports_the_complaint_not_found_code(api):
    """The railroad's answer needs a docket to land on, and there is none.

    PRD 2.8: "Every identifier appearing in the URL path must resolve to a live
    row, resolved left to right along the path, or the addressed entity's own
    not-found code at HTTP 404."

    Design: Corner/entities/answer_unknown_regulatory_complaint_returns_regulatory_complaint_not_found
    """
    missing = api.answer_regulatory_complaint(
        ABSENT_COMPLAINT_ID, f.answer_payload(), AGENT
    )
    validate_error(missing, ERR_REGULATORY_COMPLAINT_NOT_FOUND)
    assert missing.status_code == 404
    assert error_id_of(missing) != ERR_INVALID_REQUEST
    assert_error_meta_is_minimal(missing)

    # The docket register is genuinely empty.
    listed = api.list_regulatory_complaints(OFFICER, {"limit": 10, "offset": 0})
    assert get_success_data(listed) == []
    assert_pagination_meta(listed.json()["meta"], total_count=0, has_more=False)


# ===========================================================================
# instance: placement_cycles_list_with_limit_zero_returns_invalid_pagination
# ===========================================================================
def test_the_three_illegal_pagination_arguments_are_each_refused(api):
    """0, 101 and -1 are rejected; 100 and the bare list are not.

    PRD 2.3: "A `limit` of 0, a `limit` of 101 and an `offset` of −1 are each
    rejected with `ERR_INVALID_PAGINATION` (HTTP 400); omitting both parameters
    entirely is always valid."

    Design: Corner/entities/placement_cycles_list_with_limit_zero_returns_invalid_pagination
    """
    for params in (
        {"limit": 0, "offset": 0},
        {"limit": OVER_MAX_LIMIT, "offset": 0},
        {"limit": 10, "offset": -1},
    ):
        refused = api.list_placement_cycles(AGENT, params)
        validate_error(refused, ERR_INVALID_PAGINATION)
        assert refused.status_code == 400, "params %s" % params
        assert_error_meta_is_minimal(refused)

    # The upper bound itself is legal, and so is omitting the pair entirely.
    at_bound = api.list_placement_cycles(AGENT, {"limit": MAX_LIMIT, "offset": 0})
    assert get_success_data(at_bound) == []
    assert_pagination_meta(
        at_bound.json()["meta"],
        limit=MAX_LIMIT,
        offset=0,
        total_count=0,
        has_more=False,
    )
    bare = api.list_placement_cycles(AGENT)
    assert get_success_data(bare) == []
