"""Member-agency registration, statutory recorder retention, and the clock.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_DUPLICATE_TALKGROUP_ID,
    ERR_INVALID_REQUEST,
    ERR_RECORDER_RETENTION_BELOW_MINIMUM,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_pagination_meta,
)
from test_helpers.constants import (
    AGENCY_TYPE_FIRE,
    AGENCY_TYPE_LAW,
    BILLING_CURRENT,
    CAUSE_LINK_FAILURE,
    EVENT_OPEN,
    EVENT_UNPLANNED_OUTAGE,
    SITE_IN_SERVICE,
)
from test_helpers.test_users import SYSTEM_ADMIN, make_agency_radio_manager_headers


def test_agency_creation_rejects_missing_agency_type(api: ApiClient, clock_at_start: str):
    """Registration without `agency_type` is a malformed body, not a default.

    PRD 3.1: "Registration takes the agency's legal `name`, between 1 and 120
    characters; its `agency_code`, a short radio-system code of between 4 and 6
    characters drawn only from uppercase letters `A` through `Z` and the digits
    `0` through `9`; and its `agency_type`, which is one of `LAW`, `FIRE`,
    `EMS`, `PUBLIC_WORKS`, or `REGIONAL_AUTHORITY`."

    PRD 2.4 check 7: "The body parses, required fields are present, enum values
    are members of their declared sets, integers lie inside their declared
    ranges, and datetime fields are ISO-8601 UTC instants ending in `Z` —
    otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/agency_creation_rejects_missing_agency_type
    """
    response = api.create_agency(
        {"name": "Missing Type Agency", "agency_code": "MISS1"}, SYSTEM_ADMIN
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    # The rejected registration left the register empty: PRD 3.1 makes
    # `agency_type` an input of registration itself, so nothing was persisted.
    rows, meta = validate_paginated(api.list_agencies(SYSTEM_ADMIN))
    assert_pagination_meta(meta, total_count=0)
    assert rows == [], f"no agency may have been registered, got {rows}"


def test_duplicate_agency_code_rejected(api: ApiClient, clock_at_start: str):
    """A second registration reusing an `agency_code` is a registry collision.

    PRD 3.1: "The code must be unique across the whole register, and a
    collision is rejected with `ERR_DUPLICATE_TALKGROUP_ID` — the same conflict
    code the system uses for every registry-level identifier collision."

    Design: Corner/validations/duplicate_agency_code_rejected
    """
    first = fx.register_agency(
        api, name="Duplicate Code One", agency_code="DUP01", agency_type=AGENCY_TYPE_LAW
    )
    assert_common_fields(first, expected_version=1)

    response = api.create_agency(
        f.agency_payload(
            name="Duplicate Code Two",
            agency_code="DUP01",
            agency_type=AGENCY_TYPE_FIRE,
        ),
        SYSTEM_ADMIN,
    )
    validate_error(response, ERR_DUPLICATE_TALKGROUP_ID, 409)

    rows, meta = validate_paginated(api.list_agencies(SYSTEM_ADMIN))
    assert_pagination_meta(meta, total_count=1)
    assert [r["id"] for r in rows] == [first["id"]], (
        "only the first registration of the code may survive"
    )


def test_console_config_retention_below_statutory_minimum_rejected(
    api: ApiClient, clock_at_start: str
):
    """The retention floor is selected by `agency_type`, so the same requested
    value is legal for one discipline and illegal for another.

    PRD 2.10: "A `LAW` agency must retain at least 180 days; a `FIRE` agency at
    least 90 days; an `EMS` agency at least 90 days; a `PUBLIC_WORKS` agency at
    least 30 days; and the `REGIONAL_AUTHORITY` itself at least 365 days."

    PRD 2.10: "A configuration change that would place
    `recorder_retention_days` below the applicable floor is rejected with
    `ERR_RECORDER_RETENTION_BELOW_MINIMUM` at HTTP 422, and so is a patch
    request or patch activation by an agency whose retention is below 180 days."

    Design: Corner/validations/console_config_retention_below_statutory_minimum_rejected
    """
    law = fx.register_agency(
        api,
        name="Statutory Law Agency",
        agency_code="STA01",
        agency_type=AGENCY_TYPE_LAW,
        recorder_retention_days=180,
    )
    fire = fx.register_agency(
        api,
        name="Statutory Fire Agency",
        agency_code="STA02",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=180,
    )

    # 120 days is below the LAW floor of 180.
    rejected = api.update_console_config(
        law["id"],
        f.console_config_payload(recorder_retention_days=120),
        make_agency_radio_manager_headers(law["id"]),
    )
    validate_error(rejected, ERR_RECORDER_RETENTION_BELOW_MINIMUM, 422)
    assert_fields(
        fx.read_agency(api, law["id"]),
        recorder_retention_days=180,
        version=law["version"],
    )

    # The identical value clears the FIRE floor of 90.
    accepted = validate_success(
        api.update_console_config(
            fire["id"],
            f.console_config_payload(recorder_retention_days=120),
            make_agency_radio_manager_headers(fire["id"]),
        ),
        200,
    )
    assert_fields(accepted, recorder_retention_days=120)


def test_console_config_retention_at_statutory_minimum_accepted(
    api: ApiClient, clock_at_start: str
):
    """Exactly the floor is inside the floor, and the change bumps `version`.

    PRD 2.8: "Every threshold comparison in this document that is written as
    "at least" or "at most" is inclusive of the stated boundary value, and every
    comparison written as "more than", "greater than", "fewer than", or
    "strictly after" excludes it."

    PRD 2.10: "A successful console-configuration change increments the agency's
    `version` by one."

    Design: Corner/validations/console_config_retention_at_statutory_minimum_accepted
    """
    agency = fx.register_agency(
        api,
        name="Exactly At Floor Agency",
        agency_code="EXM01",
        agency_type=AGENCY_TYPE_LAW,
        recorder_retention_days=365,
    )
    assert_common_fields(agency, expected_version=1)

    updated = validate_success(
        api.update_console_config(
            agency["id"],
            f.console_config_payload(console_position_count=6, recorder_retention_days=180),
            make_agency_radio_manager_headers(agency["id"]),
        ),
        200,
    )
    assert_fields(
        updated,
        recorder_retention_days=180,
        console_position_count=6,
        version=agency["version"] + 1,
        billing_status=BILLING_CURRENT,
    )


def test_clock_set_endpoint_moves_logical_time_and_stamps_new_rows(
    api: ApiClient, clock_at_start: str
):
    """Moving the clock mutates nothing, but every later write reads the new now.

    PRD 2.5: "A `SystemAdmin` moves the clock by supplying `to_iso8601`, an
    ISO-8601 UTC instant; the response reports the new instant as `current_utc`."

    PRD 3.7: "A newly opened event sits in `OPEN` with `detected_at` stamped at
    the current logical clock instant, `escalation_tier` 0,
    `backup_minutes_remaining` null, `restored_at` null, and
    `preempted_talkpath_count` 0."

    Design: Corner/endpoints/clock_set_endpoint_moves_logical_time_and_stamps_new_rows
    """
    site = fx.register_site(api, site_code="CLK-1", name="Clock Ridge", channel_capacity=6)

    moved = validate_success(
        api.set_clock(f.clock_payload("2026-09-15T12:34:56Z"), SYSTEM_ADMIN), 200
    )
    assert_instant_equals(moved["current_utc"], "2026-09-15T12:34:56Z", "current_utc")

    event = fx.open_site_event(
        api,
        site["id"],
        event_class=EVENT_UNPLANNED_OUTAGE,
        cause=CAUSE_LINK_FAILURE,
    )
    assert_instant_equals(event["detected_at"], "2026-09-15T12:34:56Z", "detected_at")
    assert_fields(event, status=EVENT_OPEN)

    # PRD 3.7: "opening an event changes nothing about the parent site".
    assert_fields(fx.read_site(api, site["id"]), status=SITE_IN_SERVICE)
