"""The temporal guard that no other scenario reaches.

Three separate facts about a pair of instants are folded into one catalogue
entry, and the shape rule that reads the same fields sits ahead of all three.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_id_set, assert_instants_equal
from test_helpers.constants import (
    CLAIMANT_TYPE_PROPERTY,
    CLOCK_EPOCH,
    ROUTE_CLASS_LINEHAUL,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    AUDITOR,
    CLAIMS_ADJUSTER,
    DISPATCHER,
    build_claim,
    build_crash,
    build_driver,
    build_terminal,
)

LIMA_MILES = 4.0
ONE_SECOND_PAST_THE_CLOCK = "2026-08-01T00:00:01Z"
DATE_ONLY_INSTANT = "2026-08-01"
DEMAND_AMOUNT_CENTS = 400_000


def _lima_terminal_and_driver(api: ApiClient) -> dict:
    """One terminal and one driver, with no crash recorded yet."""
    terminal = build_terminal(
        api,
        name="Lima Terminal",
        terminal_code="LIM03",
        region_code="OH",
        annual_miles_millions=LIMA_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-6101",
        full_name="Hanne Broekhuis",
        cdl_number="OH-CDL-6101",
        hire_date="2014-08-08",
    )
    return {"terminal": terminal, "driver": driver}


def _crash_payload(context: dict, **overrides: object) -> dict:
    """A well-formed intake body for the Lima driver, before any overriding."""
    fields: dict = {
        "location_text": "I-75 MM 125",
        "severity": SEVERITY_MINOR,
        "route_class": ROUTE_CLASS_LINEHAUL,
        "tow_away": False,
        "tow_reason": TOW_REASON_NONE,
    }
    # An override always wins, including one aimed at a field this helper
    # already names; passing both through as keywords would be a duplicate.
    fields.update(overrides)
    return factories.crash_payload(
        context["driver"]["id"],
        context["terminal"]["id"],
        **fields,
    )


class TestTheFutureTimestampGuard:
    """One catalogue entry covers a ceiling and an ordering rule at once."""

    def test_an_instant_one_second_past_the_clock_is_already_the_future(
        self, api: ApiClient
    ):
        """The bound is the logical instant, not the wall clock of the request.

        PRD: "Three temporal facts are checked before anything is created:
        `occurred_at` must not be after the current instant, `notified_at` must not
        be after the current instant, and `notified_at` must not precede
        `occurred_at`. Any of those three failing is `ERR_FUTURE_TIMESTAMP`."

        Design: Corner/errors/every_catalog_error_has_a_trigger_including_the_timestamp_guard
        """
        context = _lima_terminal_and_driver(api)

        validate_error(
            api.create_crash(
                _crash_payload(
                    context,
                    occurred_at=ONE_SECOND_PAST_THE_CLOCK,
                    notified_at=ONE_SECOND_PAST_THE_CLOCK,
                ),
                DISPATCHER,
            ),
            ApiErrorId.FUTURE_TIMESTAMP.value,
            409,
        )

    def test_a_notification_that_precedes_its_own_crash_reports_the_same_error(
        self, api: ApiClient
    ):
        """Both instants are in the past, and the ordering alone is the fault.

        PRD: "`notified_at` must not precede `occurred_at`. Any of those three
        failing is `ERR_FUTURE_TIMESTAMP`."

        Design: Corner/errors/every_catalog_error_has_a_trigger_including_the_timestamp_guard
        """
        context = _lima_terminal_and_driver(api)

        validate_error(
            api.create_crash(
                _crash_payload(
                    context,
                    occurred_at="2026-07-31T06:00:00Z",
                    notified_at="2026-07-31T05:59:59Z",
                    location_text="I-75 MM 126",
                ),
                DISPATCHER,
            ),
            ApiErrorId.FUTURE_TIMESTAMP.value,
            409,
        )

    def test_a_date_only_instant_loses_to_the_request_shape_rule(self, api: ApiClient):
        """The shape band runs first even when the temporal fault is also present.

        PRD: "**Request shape.** The body parses as JSON, contains no unknown fields,
        contains every required input, and every present value matches its declared
        type, enum domain and range constraint ... Any violation is
        `ERR_INVALID_REQUEST`."

        Design: Corner/errors/every_catalog_error_has_a_trigger_including_the_timestamp_guard
        """
        context = _lima_terminal_and_driver(api)

        validate_error(
            api.create_crash(
                _crash_payload(
                    context,
                    occurred_at=DATE_ONLY_INSTANT,
                    notified_at=ONE_SECOND_PAST_THE_CLOCK,
                    location_text="I-75 MM 127",
                ),
                DISPATCHER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_the_current_instant_itself_is_accepted_on_both_endpoints(
        self, api: ApiClient
    ):
        """The ceiling is inclusive for a crash intake and for a demand alike.

        PRD: "`demand_received_at`, the instant the written demand arrived, which may
        not be later than the current logical instant — a future-dated demand is
        `ERR_FUTURE_TIMESTAMP`."

        Design: Corner/errors/every_catalog_error_has_a_trigger_including_the_timestamp_guard
        """
        context = _lima_terminal_and_driver(api)

        crash = build_crash(
            api,
            context["driver"]["id"],
            context["terminal"]["id"],
            occurred_at=CLOCK_EPOCH,
            notified_at=CLOCK_EPOCH,
            location_text="I-75 MM 128",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_LINEHAUL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
        )
        assert_instants_equal(crash["occurred_at"], CLOCK_EPOCH, "occurred_at")
        assert_instants_equal(crash["notified_at"], CLOCK_EPOCH, "notified_at")

        claim = build_claim(api, crash["id"], claimant_notice_date="2026-08-01")

        validate_error(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Ivo Marchetti",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=DEMAND_AMOUNT_CENTS,
                    represented_by_counsel=False,
                    demand_received_at=ONE_SECOND_PAST_THE_CLOCK,
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.FUTURE_TIMESTAMP.value,
            409,
        )

        accepted = validate_success(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Ivo Marchetti",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=DEMAND_AMOUNT_CENTS,
                    represented_by_counsel=False,
                    demand_received_at=CLOCK_EPOCH,
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )
        assert_instants_equal(
            accepted["demand_received_at"], CLOCK_EPOCH, "demand_received_at"
        )
        assert_cents(
            accepted["demand_amount_cents"], DEMAND_AMOUNT_CENTS, "demand_amount_cents"
        )

    def test_every_refused_body_leaves_no_row_behind(self, api: ApiClient):
        """A rejected request writes nothing, so both listings hold one row.

        PRD: "No side effect of any kind is applied when a rule fails, and no later
        rule is consulted."

        Design: Corner/errors/every_catalog_error_has_a_trigger_including_the_timestamp_guard
        """
        context = _lima_terminal_and_driver(api)
        for overrides in (
            {
                "occurred_at": ONE_SECOND_PAST_THE_CLOCK,
                "notified_at": ONE_SECOND_PAST_THE_CLOCK,
            },
            {"occurred_at": "2026-07-31T06:00:00Z", "notified_at": "2026-07-31T05:59:59Z"},
        ):
            validate_error(
                api.create_crash(_crash_payload(context, **overrides), DISPATCHER),
                ApiErrorId.FUTURE_TIMESTAMP.value,
                409,
            )
        validate_error(
            api.create_crash(
                _crash_payload(
                    context,
                    occurred_at=DATE_ONLY_INSTANT,
                    notified_at=ONE_SECOND_PAST_THE_CLOCK,
                ),
                DISPATCHER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        crash = build_crash(
            api,
            context["driver"]["id"],
            context["terminal"]["id"],
            occurred_at=CLOCK_EPOCH,
            notified_at=CLOCK_EPOCH,
            location_text="I-75 MM 128",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_LINEHAUL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
        )
        claim = build_claim(api, crash["id"], claimant_notice_date="2026-08-01")
        validate_error(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Ivo Marchetti",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=DEMAND_AMOUNT_CENTS,
                    demand_received_at=ONE_SECOND_PAST_THE_CLOCK,
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.FUTURE_TIMESTAMP.value,
            409,
        )
        demand = validate_success(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Ivo Marchetti",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=DEMAND_AMOUNT_CENTS,
                    demand_received_at=CLOCK_EPOCH,
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )

        crashes, crash_meta = validate_paginated(
            api.list_crashes(
                AUDITOR,
                {"terminal_id": context["terminal"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert crash_meta["total_count"] == 1
        assert_id_set(crashes, [crash["id"]])

        demands, demand_meta = validate_paginated(
            api.list_claim_demands(claim["id"], AUDITOR, {"limit": 10, "offset": 0})
        )
        assert demand_meta["total_count"] == 1
        assert_id_set(demands, [demand["id"]])
