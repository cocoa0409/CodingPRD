"""Entity shape compliance: declared fields, defaults, system-assigned values.

Every test here reads the persisted shape of one entity of the Comprehensive Plan
Update API through the public endpoints only: what a creation response is obliged
to carry, which values the server assigns rather than echoing, which optional
inputs take a declared default, and which rows are configuration rows without
version machinery.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTIVITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PLAN_UPDATE_NOT_FOUND,
    ERR_VENUE_NOT_EQUITY_ELIGIBLE,
    ERR_VENUE_NOT_FOUND,
)
from test_helpers.test_users import ALL_ROLE_HEADERS, DIRECTOR, STAFF


# --------------------------------------------------------------------- creation
def test_plan_update_creation_returns_its_declared_inputs_and_system_status(api):
    """Opening a cycle echoes the four inputs and adds the server-decided status.

    PRD: "The opening payload carries a public `title` of 1 to 160 non-blank
    characters (for example, "Horizon 2045"), a `jurisdiction_code` of 2 to 12
    uppercase alphanumeric characters — the identifier the state expects on every
    mandate filing — and the two years that frame the analysis: `base_year`, the
    year the existing-conditions picture describes, and `horizon_year`, the
    statutory planning horizon."

    Design: Corner/entities/plan_update_creation_returns_every_declared_field
    """
    payload = f.plan_update_payload(title="Horizon 2045")
    plan = validate_success(api.create_plan_update(payload, DIRECTOR), 201)

    assert is_valid_uuid(plan["id"]), f"id must be a bare UUID, got {plan['id']!r}"
    assert plan["title"] == "Horizon 2045"
    assert plan["jurisdiction_code"] == f.REF_JURISDICTION
    assert plan["base_year"] == f.REF_BASE_YEAR
    assert plan["horizon_year"] == f.REF_HORIZON_YEAR

    assert plan["status"] == C.PLAN_STATUS_DRAFTING
    assert plan["state_review_status"] == C.STATE_REVIEW_NOT_SUBMITTED
    assert plan["state_findings"] is None
    assert plan["compliance_posture"] == C.POSTURE_CAPACITY_HOLD

    a.assert_versioned_row(plan, expected_version=1)
    a.assert_created_equals_updated(plan)


def test_plan_update_creation_reports_every_derived_counter_at_zero(api):
    """A brand-new plan carries all of its derived counters at their opening values.

    PRD: "A freshly opened plan starts in `DRAFTING` with `state_review_status` at
    `NOT_SUBMITTED`, `state_findings` and `adopted_scenario_id` and `adopted_at` all
    null, `resubmission_count`, `open_consistency_link_count`,
    `required_elements_complete_count`, `housing_shortfall_total` and
    `monitoring_on_track_count` all zero, and `equity_share_pct`,
    `participation_weight_total` and `underrepresented_weight_total` all 0.0."

    Design: Corner/entities/plan_update_creation_returns_every_declared_field
    """
    plan = validate_success(
        api.create_plan_update(f.plan_update_payload(), DIRECTOR), 201
    )

    assert plan["adopted_scenario_id"] is None
    assert plan["adopted_at"] is None
    assert plan["resubmission_count"] == 0
    assert plan["open_consistency_link_count"] == 0
    assert plan["required_elements_complete_count"] == 0
    assert plan["housing_shortfall_total"] == 0
    assert plan["monitoring_on_track_count"] == 0
    assert plan["equity_share_pct"] == 0.0
    assert plan["participation_weight_total"] == 0.0
    assert plan["underrepresented_weight_total"] == 0.0
    a.assert_one_decimal(plan["equity_share_pct"], "equity_share_pct")
    a.assert_one_decimal(plan["participation_weight_total"], "participation_weight_total")
    a.assert_one_decimal(
        plan["underrepresented_weight_total"], "underrepresented_weight_total"
    )
    a.assert_posture_consistent(plan)


# -------------------------------------------------------------------- retrieval
def test_plan_update_read_round_trips_and_never_refreshes_updated_at(api):
    """Reading a plan returns the stored row and leaves version and updated_at alone.

    PRD: "Most rows additionally carry `updated_at`, an ISO 8601 UTC timestamp with
    three fractional digits refreshed on every mutation of that row, and `version`,
    an integer that starts at 1 on creation and increments by exactly 1 on every
    mutation of that row"

    Design: Corner/entities/plan_update_retrieval_round_trips_stored_values
    """
    created = validate_success(
        api.create_plan_update(f.plan_update_payload(title="Horizon 2045"), DIRECTOR), 201
    )
    fx.set_clock(api, "2026-08-05T12:00:00.000Z")

    fetched = validate_success(api.get_plan_update(created["id"], STAFF))

    assert fetched["id"] == created["id"]
    assert fetched["title"] == "Horizon 2045"
    assert fetched["status"] == C.PLAN_STATUS_DRAFTING
    assert fetched["version"] == 1
    # A read is not a mutation, so neither stamp may move.
    a.assert_instant_equals(fetched["created_at"], created["created_at"], "created_at")
    a.assert_instant_equals(fetched["updated_at"], created["updated_at"], "updated_at")
    a.assert_fields_equal(fetched, created)


def test_plan_update_read_is_identical_for_every_declared_role(api):
    """All five roles read the same stored plan row.

    PRD: "All five roles may read every single-resource read, list and computed-read
    endpoint under `/planning`, and all five may drive the logical clock."

    Design: Corner/entities/plan_update_retrieval_round_trips_stored_values
    """
    created = fx.create_plan(api, title="Horizon 2045")

    baseline = None
    for role, headers in ALL_ROLE_HEADERS.items():
        row = validate_success(api.get_plan_update(created["id"], headers))
        if baseline is None:
            baseline = row
        else:
            assert row == baseline, f"{role} read a different row: {row} != {baseline}"
    assert baseline["id"] == created["id"]
    assert baseline["version"] == 1


# ---------------------------------------------------------------------- listing
def test_plan_update_listing_honours_limit_offset_and_their_defaults(api):
    """The collection endpoint windows the rows and reports the unwindowed total.

    PRD: "Every list endpoint accepts two optional query parameters. `limit` defaults
    to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a
    minimum of 0."

    Design: Corner/entities/plan_update_listing_paginates_and_filters
    """
    fx.create_plan(api, title="Horizon 2045", horizon_year=2045)
    fx.create_plan(api, title="Horizon 2050", horizon_year=2050)
    third = fx.create_plan(
        api, title="Rivertown General Plan", jurisdiction_code="CA0999"
    )

    rows, meta = validate_paginated(api.list_plan_updates(STAFF, limit=2, offset=0))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    a.assert_created_at_ascending(rows)

    rows, meta = validate_paginated(api.list_plan_updates(STAFF, limit=2, offset=2))
    assert len(rows) == 1
    assert rows[0]["id"] == third["id"]
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(api.list_plan_updates(STAFF))
    assert len(rows) == 3
    assert meta["limit"] == C.DEFAULT_LIMIT
    assert meta["offset"] == C.DEFAULT_OFFSET
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_plan_update_listing_filters_narrow_the_reported_total(api):
    """A jurisdiction or status filter narrows total_count, not just the page.

    PRD: "Where a list endpoint also accepts filters, the filters narrow the result
    set before pagination is applied, so `total_count` reports the number of rows
    matching the filters, not the number of rows in the collection."

    Design: Corner/entities/plan_update_listing_paginates_and_filters
    """
    fx.create_plan(api, title="Horizon 2045", horizon_year=2045)
    fx.create_plan(api, title="Horizon 2050", horizon_year=2050)
    third = fx.create_plan(
        api, title="Rivertown General Plan", jurisdiction_code="CA0999"
    )

    rows, meta = validate_paginated(
        api.list_plan_updates(STAFF, params={"jurisdiction_code": "CA0999"})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == third["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_plan_updates(STAFF, params={"jurisdiction_code": f.REF_JURISDICTION})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_plan_updates(
            STAFF, params={"status": C.PLAN_STATUS_STATE_SUBMITTED}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# -------------------------------------------------------------------- not found
def test_unknown_plan_update_id_on_a_read_returns_the_plan_not_found_code(api):
    """An unknown but well-formed plan id is a 404 with the plan's own error id.

    PRD: "Every id embedded in the URL path resolves to an existing row, validated
    left to right — the plan update id in a nested path is checked before the child
    id that follows it. The failing id determines the code:
    `ERR_PLAN_UPDATE_NOT_FOUND`"

    Design: Corner/entities/plan_update_not_found_returns_plan_update_not_found
    """
    fx.create_plan(api)

    error = validate_error(
        api.get_plan_update(C.BOGUS_UUID, STAFF), ERR_PLAN_UPDATE_NOT_FOUND
    )
    assert error["message"].strip(), "the error envelope must carry a message"

    rows, meta = validate_paginated(api.list_plan_updates(STAFF))
    assert meta["total_count"] == 1, "a failed lookup must not create a row"
    assert len(rows) == 1


# --------------------------------------------------------------- required fields
@pytest.mark.parametrize(
    "omitted", ["title", "jurisdiction_code", "base_year", "horizon_year"]
)
def test_plan_update_creation_rejects_an_omitted_required_input(api, omitted):
    """Each of the four opening inputs is mandatory and its omission writes nothing.

    PRD: "**Request shape.** The body conforms to the endpoint's input schema:
    required fields present, enum members recognised, numbers inside their declared
    ranges"

    Design: Corner/entities/plan_update_missing_required_field_is_rejected
    """
    payload = f.plan_update_payload()
    payload.pop(omitted)

    validate_error(api.create_plan_update(payload, DIRECTOR), ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(api.list_plan_updates(STAFF))
    assert meta["total_count"] == 0, "a rejected opening must not persist a plan"


def test_plan_update_creation_persists_only_the_complete_body(api):
    """The same body minus jurisdiction_code fails and with it succeeds.

    PRD: "a `jurisdiction_code` of 2 to 12 uppercase alphanumeric characters — the
    identifier the state expects on every mandate filing"

    Design: Corner/entities/plan_update_missing_required_field_is_rejected
    """
    incomplete = f.plan_update_payload()
    incomplete.pop("jurisdiction_code")
    validate_error(api.create_plan_update(incomplete, DIRECTOR), ERR_INVALID_REQUEST)

    accepted = validate_success(
        api.create_plan_update(f.plan_update_payload(), DIRECTOR), 201
    )

    rows, meta = validate_paginated(api.list_plan_updates(STAFF))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted["id"]]


# ----------------------------------------------------------------- venue defaults
def test_venue_omitted_optional_inputs_take_their_declared_defaults(api):
    """A venue registered with only its mandatory inputs reports the three defaults.

    PRD: "A venue carries a public `name` of 1 to 120 characters, a `seated_capacity`
    greater than zero, a `turnover_buffer_minutes` value between 0 and 240 inclusive
    that defaults to 0 and represents the setup and teardown time the room needs on
    both sides of every booking, an `ada_accessible` flag that defaults to true and
    records whether the facility is step-free, and a `transit_served` flag that
    defaults to false and records whether the facility sits within 400 metres of a
    transit stop."

    Design: Corner/entities/venue_optional_fields_take_declared_defaults
    """
    venue = validate_success(
        api.create_venue(
            f.venue_payload(name="Northgate Rec Center", seated_capacity=90), STAFF
        ),
        201,
    )

    assert venue["name"] == "Northgate Rec Center"
    assert venue["seated_capacity"] == 90
    assert venue["turnover_buffer_minutes"] == 0
    assert venue["ada_accessible"] is True
    assert venue["transit_served"] is False
    a.assert_config_row(venue)


def test_defaulted_venue_cannot_host_targeted_outreach_but_can_host_a_workshop(api):
    """The transit_served default of false is what refuses the outreach booking.

    PRD: "A targeted-outreach session carries an additional equity requirement: its
    venue must be both `transit_served` and `ada_accessible`, and a booking at a venue
    failing either test is refused with `ERR_VENUE_NOT_EQUITY_ELIGIBLE`."

    Design: Corner/entities/venue_optional_fields_take_declared_defaults
    """
    plan = fx.create_plan(api)
    venue = fx.create_venue(api, name="Northgate Rec Center", seated_capacity=90)
    assert venue["transit_served"] is False
    assert venue["ada_accessible"] is True

    validate_error(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_TARGETED_OUTREACH,
                title="Youth Outreach",
                venue_id=venue["id"],
                start_at="2026-08-20T18:00:00.000Z",
                end_at="2026-08-20T20:00:00.000Z",
            ),
            STAFF,
        ),
        ERR_VENUE_NOT_EQUITY_ELIGIBLE,
    )

    workshop = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Northgate Workshop",
                venue_id=venue["id"],
                start_at="2026-08-20T18:00:00.000Z",
                end_at="2026-08-20T20:00:00.000Z",
            ),
            STAFF,
        ),
        201,
    )
    assert workshop["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert workshop["weighting_variant"] == C.VARIANT_STANDARD


# ---------------------------------------------------------------- computed fields
def test_participation_records_are_scored_from_the_respondents_own_attributes(api):
    """Each captured record carries the server's own flag and weight.

    PRD: "Its `is_underrepresented` flag is derived by the server and any
    client-supplied value is ignored: it is true when the respondent's
    `demographic_group` is `LOW_INCOME`, `LIMITED_ENGLISH`, `YOUTH`, `DISABILITY` or
    `RENTER`."

    Design: Corner/entities/activity_participation_counters_are_computed_not_supplied
    """
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api)
    activity = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Eastside Workshop",
                venue_id=venue["id"],
            ),
            STAFF,
        ),
        201,
    )
    assert activity["weighting_variant"] == C.VARIANT_STANDARD
    assert activity["record_count"] == 0
    assert activity["total_weighted_count"] == 0.0

    renter = validate_success(
        api.create_participation_record(
            f.participation_record_payload(
                activity["id"],
                respondent_ref="R-001",
                demographic_group=C.GROUP_RENTER,
                census_tract="060014001",
                interpreter_used=True,
            ),
            STAFF,
        ),
        201,
    )
    assert renter["is_underrepresented"] is True
    assert renter["weight"] == C.WEIGHT_STANDARD

    general = validate_success(
        api.create_participation_record(
            f.participation_record_payload(
                activity["id"],
                respondent_ref="R-002",
                demographic_group=C.GROUP_GENERAL,
                census_tract="060014002",
            ),
            STAFF,
        ),
        201,
    )
    assert general["is_underrepresented"] is False
    assert general["weight"] == C.WEIGHT_STANDARD


def test_activity_counters_are_folded_from_the_attached_records_alone(api):
    """The four activity counters follow the captured records, and its share waits.

    PRD: "Capturing the record then updates the activity in one step: `record_count`
    rises by one, `underrepresented_record_count` rises by one if the record is flagged
    as underrepresented, `total_weighted_count` rises by the record's weight,
    `underrepresented_weighted_count` rises by that same weight if the record is
    flagged, and the activity's `version` is incremented by one."

    Design: Corner/entities/activity_participation_counters_are_computed_not_supplied
    """
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api)
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Eastside Workshop",
        venue_id=venue["id"],
    )
    fx.add_participation(
        api,
        activity["id"],
        respondent_ref="R-001",
        demographic_group=C.GROUP_RENTER,
        interpreter_used=True,
    )
    fx.add_participation(
        api,
        activity["id"],
        respondent_ref="R-002",
        demographic_group=C.GROUP_GENERAL,
        census_tract="060014002",
    )

    fetched = validate_success(api.get_engagement_activity(activity["id"], STAFF))
    expected = a.expected_activity_totals(
        [
            {"demographic_group": C.GROUP_RENTER, "interpreter_used": True},
            {"demographic_group": C.GROUP_GENERAL},
        ],
        C.VARIANT_STANDARD,
    )
    assert fetched["record_count"] == expected["record_count"] == 2
    assert fetched["underrepresented_record_count"] == 1
    assert fetched["total_weighted_count"] == expected["total_weighted_count"] == 2.0
    assert fetched["underrepresented_weighted_count"] == 1.0
    assert fetched["equity_share_pct"] == 0.0, (
        "an activity's own share is computed by the completion, not by a capture"
    )
    assert fetched["version"] == 3

    plan_row = fx.read_plan(api, plan["id"])
    assert plan_row["participation_weight_total"] == 0.0
    assert plan_row["equity_share_pct"] == 0.0


def test_supplied_counter_and_flag_values_are_ignored_on_the_way_in(api):
    """A caller-supplied counter or equity flag never reaches the stored row.

    PRD: "If a caller supplies such a field in a request body, the value is ignored;
    the same is true of `is_underrepresented` on a participation record, which the
    server always derives from the respondent's demographic group."

    Design: Corner/entities/activity_participation_counters_are_computed_not_supplied
    """
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api)
    activity = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Eastside Workshop",
                venue_id=venue["id"],
                record_count=99,
                total_weighted_count=99.0,
            ),
            STAFF,
        ),
        201,
    )
    assert activity["record_count"] == 0
    assert activity["total_weighted_count"] == 0.0

    record = validate_success(
        api.create_participation_record(
            f.participation_record_payload(
                activity["id"],
                respondent_ref="R-001",
                demographic_group=C.GROUP_GENERAL,
                is_underrepresented=True,
            ),
            STAFF,
        ),
        201,
    )
    assert record["is_underrepresented"] is False
    assert record["weight"] == C.WEIGHT_STANDARD

    fetched = validate_success(api.get_engagement_activity(activity["id"], STAFF))
    assert fetched["record_count"] == 1
    assert fetched["underrepresented_record_count"] == 0
    assert fetched["total_weighted_count"] == 1.0


# ------------------------------------------------------------------ system fields
def test_element_creation_stamps_the_author_and_the_opening_workflow_fields(api):
    """The element's author, status, consistency status and round come from the server.

    PRD: "A new element is stamped with the author's `X-User-ID` in
    `authored_by_user_id` and starts in `DRAFT` with `consistency_status` at `PENDING`
    and `revision_round` at zero."

    Design: Corner/entities/element_system_fields_are_server_assigned
    """
    plan = fx.create_plan(api)

    element = validate_success(
        api.create_plan_element(
            f.plan_element_payload(
                plan["id"],
                element_type=C.ELEMENT_PARKS,
                title="Parks and Recreation",
                draft_body="Draft parks element text.",
                policy_count=6,
            ),
            STAFF,
        ),
        201,
    )

    assert element["status"] == C.ELEMENT_STATUS_DRAFT
    assert element["consistency_status"] == C.CONSISTENCY_PENDING
    assert element["revision_round"] == 0
    assert element["authored_by_user_id"] == STAFF["X-User-ID"], (
        "authored_by_user_id is taken from the header, never from the body"
    )
    a.assert_versioned_row(element, expected_version=1)
    a.assert_created_equals_updated(element)


def test_element_revision_advances_version_and_leaves_the_stamped_fields_frozen(api):
    """A content revision moves version and updated_at only.

    PRD: "Element content is revised in place. A revision may replace the `title`, the
    `draft_body` and the `policy_count`, in any combination, and each revision
    increments the element's `version`. Revising an element that is already in `DRAFT`
    is a self-loop that changes nothing but content"

    Design: Corner/entities/element_system_fields_are_server_assigned
    """
    plan = fx.create_plan(api)
    element = fx.create_element(
        api, plan["id"], C.ELEMENT_PARKS, policy_count=6,
        draft_body="Draft parks element text.",
    )

    fx.set_clock(api, "2026-08-03T09:30:00.000Z")
    revised = validate_success(
        api.patch_plan_element(
            element["id"], {"draft_body": "Revised parks element text."}, STAFF
        )
    )

    assert revised["version"] == 2
    # "updated_at ... refreshed on every mutation of that row"; created_at is
    # "stamped once at creation and never modified".
    a.assert_three_digit_instant(revised["updated_at"], "updated_at")
    assert revised["updated_at"] != element["updated_at"], (
        "updated_at must be refreshed on every mutation of the row"
    )
    a.assert_instant_equals(revised["created_at"], element["created_at"], "created_at")
    assert revised["authored_by_user_id"] == STAFF["X-User-ID"]
    assert revised["status"] == C.ELEMENT_STATUS_DRAFT
    assert revised["draft_body"] == "Revised parks element text."
    assert revised["policy_count"] == 6, (
        "a revision that omits policy_count leaves the policy inventory alone"
    )


# ------------------------------------------------------------------ immutability
def test_venue_row_carries_no_version_machinery(api):
    """A registered venue exposes its own inputs plus id and created_at, nothing more.

    PRD: "A `Venue` carries only `id` and `created_at`: it has no `updated_at` and no
    `version`, and there is no endpoint that modifies one."

    Design: Corner/entities/venue_and_participation_record_are_immutable_rows
    """
    venue = validate_success(
        api.create_venue(
            f.venue_payload(
                name="Eastside Community Room",
                seated_capacity=120,
                turnover_buffer_minutes=0,
                ada_accessible=True,
                transit_served=True,
            ),
            STAFF,
        ),
        201,
    )

    for field in (
        "name",
        "seated_capacity",
        "turnover_buffer_minutes",
        "ada_accessible",
        "transit_served",
        "id",
        "created_at",
    ):
        assert field in venue, f"a venue row must expose {field!r}"
    a.assert_config_row(venue)
    a.assert_no_such_key(venue, "updated_at")
    a.assert_no_such_key(venue, "version")


def test_participation_record_row_carries_no_version_machinery(api):
    """A captured record exposes its scored fields, id and created_at, and stays put.

    PRD: "A `ParticipationRecord` likewise carries only `id` and `created_at`:
    participation cannot be edited, re-weighted or deleted once captured, so neither
    `updated_at` nor `version` exists on it."

    Design: Corner/entities/venue_and_participation_record_are_immutable_rows
    """
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api)
    activity = fx.create_activity(
        api, plan["id"], activity_type=C.ACTIVITY_WORKSHOP, venue_id=venue["id"]
    )

    record = validate_success(
        api.create_participation_record(
            f.participation_record_payload(
                activity["id"],
                respondent_ref="R-001",
                demographic_group=C.GROUP_YOUTH,
                census_tract="060014001",
            ),
            STAFF,
        ),
        201,
    )

    for field in (
        "activity_id",
        "respondent_ref",
        "demographic_group",
        "census_tract",
        "interpreter_used",
        "comment_text",
        "is_underrepresented",
        "weight",
        "id",
        "created_at",
    ):
        assert field in record, f"a participation record must expose {field!r}"
    assert record["interpreter_used"] is False
    assert record["comment_text"] is None
    assert record["is_underrepresented"] is True
    assert record["weight"] == C.WEIGHT_STANDARD
    a.assert_config_row(record)
    a.assert_no_such_key(record, "updated_at")
    a.assert_no_such_key(record, "version")

    rows, meta = validate_paginated(
        api.list_activity_participation_records(activity["id"], STAFF)
    )
    assert meta["total_count"] == 1
    assert rows[0] == record, "the captured record is never rewritten"


# ----------------------------------------------------------- parent relationships
def test_each_unresolved_body_foreign_key_returns_its_own_not_found_code(api):
    """One rule, three codes: the unresolved field decides which 404 comes back.

    PRD: "**Body foreign keys.** Every foreign key supplied in the body resolves to an
    existing row, otherwise `ERR_PLAN_UPDATE_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`,
    `ERR_ELEMENT_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND` or `ERR_ACTIVITY_NOT_FOUND` (404)."

    Design: Corner/entities/child_creation_requires_resolvable_parent_ids
    """
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api)

    validate_error(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                NON_EXISTENT_UUID,
                inventory_type=C.INVENTORY_DEMOGRAPHIC,
                record_count=4200,
            ),
            STAFF,
        ),
        ERR_PLAN_UPDATE_NOT_FOUND,
    )

    validate_error(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Ghost Venue Workshop",
                venue_id=NON_EXISTENT_UUID,
            ),
            STAFF,
        ),
        ERR_VENUE_NOT_FOUND,
    )

    validate_error(
        api.create_participation_record(
            f.participation_record_payload(
                NON_EXISTENT_UUID,
                respondent_ref="R-001",
                demographic_group=C.GROUP_YOUTH,
            ),
            STAFF,
        ),
        ERR_ACTIVITY_NOT_FOUND,
    )

    _rows, meta = validate_paginated(
        api.list_plan_inventory_datasets(plan["id"], STAFF)
    )
    assert meta["total_count"] == 0
    _rows, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"plan_update_id": plan["id"]})
    )
    assert meta["total_count"] == 0
    assert venue["id"], "the real venue was never used by a successful booking"


# --------------------------------------------------------------- type constraints
def test_schema_violations_are_refused_and_leave_nothing_behind(api):
    """An unknown enum member, a too-short horizon and a backwards interval all fail.

    PRD: "**Request shape.** The body conforms to the endpoint's input schema:
    required fields present, enum members recognised, numbers inside their declared
    ranges, datetimes ISO 8601 UTC with three fractional digits, an activity's
    `end_at` strictly after its `start_at`"

    Design: Corner/entities/type_constraint_violations_are_rejected_before_any_write
    """
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api)

    validate_error(
        api.create_plan_element(
            f.plan_element_payload(
                plan["id"],
                element_type="ECONOMIC_DEVELOPMENT",
                title="Economic Development",
                draft_body="Not a statutory element.",
                policy_count=4,
            ),
            STAFF,
        ),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_plan_update(
            f.plan_update_payload(
                title="Short Horizon Plan",
                jurisdiction_code="CA0452",
                base_year=2025,
                horizon_year=2030,
            ),
            DIRECTOR,
        ),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Backwards Workshop",
                venue_id=venue["id"],
                start_at="2026-07-10T20:00:00.000Z",
                end_at="2026-07-10T18:00:00.000Z",
            ),
            STAFF,
        ),
        ERR_INVALID_REQUEST,
    )

    _rows, meta = validate_paginated(api.list_plan_updates(STAFF))
    assert meta["total_count"] == 1, "the rejected cycle must not have been opened"
    _rows, meta = validate_paginated(api.list_plan_elements(plan["id"], STAFF))
    assert meta["total_count"] == 0, "the rejected element must not have been drafted"
    _rows, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"plan_update_id": plan["id"]})
    )
    assert meta["total_count"] == 0, "the rejected booking must not have been made"


def test_pagination_limit_outside_its_declared_range_is_refused(api):
    """A limit above the declared maximum is a schema violation, not a clamp.

    PRD: "A `limit` below 1 or above 100, or a negative `offset`, is a schema violation
    and is rejected with `ERR_INVALID_REQUEST` (HTTP 422) rather than being silently
    clamped."

    Design: Corner/entities/type_constraint_violations_are_rejected_before_any_write
    """
    fx.create_plan(api)

    validate_error(
        api.list_plan_updates(STAFF, limit=C.MAX_LIMIT + 1), ERR_INVALID_REQUEST
    )

    _rows, meta = validate_paginated(api.list_plan_updates(STAFF, limit=C.MAX_LIMIT))
    assert meta["limit"] == C.MAX_LIMIT
    assert meta["total_count"] == 1
