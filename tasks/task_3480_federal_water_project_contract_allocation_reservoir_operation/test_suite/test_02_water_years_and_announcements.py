"""Water-year lifecycle, announcement publishing, and the OCC guard.

Covers the finalize precondition, revision supersession and year repointing,
the double-publish rejection, duplicate year labels, closed-year data intake,
the immediate visibility of publish effects, the optimistic-concurrency rule
on draft creation, and the publish role restriction - PRD §2.1, §2.7, §3.2
and §3.3.
"""

from test_helpers import (
    ApiErrorId,
    RECLAMATION_OPERATOR_HEADERS,
    REGIONAL_DIRECTOR_HEADERS,
    assert_instant,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

OPERATOR = RECLAMATION_OPERATOR_HEADERS
DIRECTOR = REGIONAL_DIRECTOR_HEADERS


def test_finalize_without_published_announcement_rejected(api):
    """Finalizing an OPEN year (no published announcement) fails 409
    ERR_NO_PUBLISHED_ANNOUNCEMENT and the year stays OPEN.

    PRD §3.3: "Finalization requires that the year actually has a published
    announcement — that `current_announcement_id` is non-null — otherwise it
    is refused with `ERR_NO_PUBLISHED_ANNOUNCEMENT`."

    Design: Corner/state_machines/finalize_without_published_announcement_rejected
    """
    world = fixtures.setup_open_year(api)
    year_id = world["year"]["id"]

    validate_error(api.finalize_water_year(year_id, OPERATOR), ApiErrorId.ERR_NO_PUBLISHED_ANNOUNCEMENT)

    year = fixtures.get_water_year(api, year_id)
    assert year["status"] == "OPEN", f"rejected finalize must leave the year OPEN, got {year['status']}"


def test_publish_supersedes_prior_announcement_and_repoints_year(api):
    """A revision publish flips the previously PUBLISHED announcement to
    SUPERSEDED, repoints the year's current_announcement_id, keeps the year
    ANNOUNCED, and stamps published_at from the logical clock.

    PRD §3.3: "Every other announcement of the same year, whether `DRAFT` or
    `PUBLISHED`, moves to `SUPERSEDED`; a superseded announcement's lines are
    retained as historical record."
    PRD §3.3: "The year itself moves from `OPEN` to `ANNOUNCED` on the first
    publish (a later revision is an `ANNOUNCED`-to-`ANNOUNCED` transition),
    its `current_announcement_id` is repointed at the newly published
    announcement, and its `version` increments by one. The new announcement's
    `published_at` takes the logical-clock timestamp."

    Design: Corner/state_machines/publish_supersedes_prior_announcement_and_repoints_year
    """
    world = fixtures.setup_announced_year(api)
    year_id = world["year"]["id"]
    first_id = world["announcement"]["id"]

    revision = fixtures.publish_revision(api, world, runoff=4_999)

    first = fixtures.find_announcement(api, year_id, first_id)
    assert first["status"] == "SUPERSEDED"
    assert revision["status"] == "PUBLISHED"
    assert revision["sequence_number"] == 2, "sequence is monotonic per water year"
    assert_instant(revision["published_at"], "2027-01-20T00:00:00Z", "revision.published_at")

    year = world["year"]
    assert year["current_announcement_id"] == revision["id"]
    assert year["status"] == "ANNOUNCED"


def test_double_publish_returns_invalid_state(api):
    """Publishing an already-PUBLISHED announcement fails 409 ERR_INVALID_STATE.

    PRD §3.3: "A `ReclamationOperator` publishes a draft announcement —
    publishing anything not in `DRAFT` fails with `ERR_INVALID_STATE`, and
    publishing into a `CLOSED` year fails with `ERR_YEAR_CLOSED`."

    Design: Corner/state_machines/double_publish_returns_invalid_state
    """
    world = fixtures.setup_announced_year(api)
    announcement_id = world["announcement"]["id"]

    validate_error(
        api.publish_allocation_announcement(announcement_id, OPERATOR),
        ApiErrorId.ERR_INVALID_STATE,
    )

    announcement = fixtures.find_announcement(api, world["year"]["id"], announcement_id)
    assert announcement["status"] == "PUBLISHED"


def test_duplicate_water_year_label_rejected(api):
    """Water-year labels are unique; a second 2027 fails 409.

    PRD §3.2: "A `ReclamationOperator` opens a year with an integer `label`
    such as 2027 (labels are unique; a duplicate is refused with
    `ERR_DUPLICATE_WATER_YEAR`), a `season_start`, and a `season_end` that
    the start must strictly precede."

    Design: Corner/validations/duplicate_water_year_label_rejected
    """
    fixtures.setup_project(api, reservoir_profile=None, contract_plan=None)
    fixtures.create_water_year(api)

    validate_error(
        api.create_water_year(factories.water_year_payload(), OPERATOR),
        ApiErrorId.ERR_DUPLICATE_WATER_YEAR,
    )


def test_observation_on_closed_year_rejected(api):
    """Posting an observation into a CLOSED year fails 409 ERR_YEAR_CLOSED
    and the hydrologic record is unchanged.

    PRD §3.2: "No observation of any type may be posted into a year whose
    `status` is `CLOSED`; the attempt is rejected with `ERR_YEAR_CLOSED`."

    Design: Corner/validations/observation_on_closed_year_rejected
    """
    world = fixtures.setup_closed_year(api)
    year_id = world["year"]["id"]

    validate_error(
        api.create_hydrology_observation(
            year_id,
            factories.snowpack_payload(90, "2027-02-01T00:00:00Z"),
            fixtures.HYDROLOGY_OFFICER_HEADERS,
        ),
        ApiErrorId.ERR_YEAR_CLOSED,
    )

    observations, meta = validate_paginated(
        api.list_hydrology_observations(year_id, fixtures.READ_HEADERS)
    )
    assert meta["total_count"] == 2, f"the closed year keeps its two observations, got {meta['total_count']}"


def test_publish_effects_visible_in_same_response_and_followup_get(api):
    """Consistency is immediate: the publish response carries the computed
    declared supply and tier, and a follow-up GET already shows the year
    repointed at the new announcement.

    PRD §4: "operations that modify an existing resource — transitions,
    executions, decisions, recordings, settlements — return `200 OK`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.3: "its `current_announcement_id` is repointed at the newly
    published announcement, and its `version` increments by one."

    Design: Corner/consistency_model/publish_effects_visible_in_same_response_and_followup_get
    """
    world = fixtures.setup_open_year(api)
    year = fixtures.refresh_year(api, world)
    draft = fixtures.create_announcement(api, year["id"], year["version"])

    published = validate_success(api.publish_allocation_announcement(draft["id"], OPERATOR))
    # snowpack 80, runoff 5,000 on the small reservoir published in January:
    # usable 5,500 + round(5,000*80/100) - holdback 2,000.
    assert published["declared_supply_af"] == 7_500
    assert published["shortage_tier"] == "NONE"

    year_after = fixtures.get_water_year(api, year["id"])
    assert year_after["current_announcement_id"] == published["id"]
    assert year_after["status"] == "ANNOUNCED"


def test_occ_stale_water_year_version_returns_412(api):
    """Draft creation carries the year's last-observed version; after the
    first create advanced the year, replaying the old version is a 412.

    PRD §2.7: "If the supplied value does not match the water year's current
    `version` — because, for example, another writer has already advanced the
    year by creating the next draft announcement — the creation is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_water_year_version_returns_412
    """
    world = fixtures.setup_open_year(api)
    year_id = world["year"]["id"]
    observed_version = world["year"]["version"]

    fixtures.create_announcement(api, year_id, observed_version)

    validate_error(
        api.create_allocation_announcement(
            year_id, factories.announcement_payload(observed_version), OPERATOR
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )

    announcements, meta = validate_paginated(
        api.list_allocation_announcements(year_id, fixtures.READ_HEADERS)
    )
    assert meta["total_count"] == 1 and len(announcements) == 1


def test_occ_current_version_succeeds_and_version_increments(api):
    """Creating with the year's current version succeeds, stamps the next
    sequence number, and advances the year's version by exactly one.

    PRD §2.7: "That request must carry `expected_water_year_version`, a
    non-optional field holding the `version` of the water year as the client
    last observed it."
    PRD §3.3: "Each successful creation increments the year's `version` by
    one and stamps the draft with a `sequence_number` that is monotonic per
    water year, starting at 1 and continuing at one more than the prior maximum."

    Design: Corner/cross_cutting_complexity_layers/occ_current_version_succeeds_and_version_increments
    """
    world = fixtures.setup_open_year(api)
    year_id = world["year"]["id"]
    fixtures.create_announcement(api, year_id, world["year"]["version"])

    year = fixtures.refresh_year(api, world)
    assert year["version"] == 2, "the first create advanced the year from 1 to 2"

    draft = validate_success(
        api.create_allocation_announcement(
            year_id, factories.announcement_payload(year["version"]), OPERATOR
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    assert draft["sequence_number"] == 2

    year_after = fixtures.get_water_year(api, year_id)
    assert year_after["version"] == 3, (
        f"each create increments the year version by exactly one, got {year_after['version']}"
    )


def test_district_manager_cannot_publish_announcement_returns_forbidden(api):
    """Publish is exclusive to ReclamationOperator; a DistrictManager caller
    is rejected 403 ERR_FORBIDDEN before the announcement is touched.

    PRD §2.1: "A request whose role is authenticated but not listed among the
    roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "`ReclamationOperator` (the river operations desk that runs
    water years, announcements, releases, delivery recording, and transfer
    execution)"

    Design: Corner/rbac/district_manager_cannot_publish_announcement_returns_forbidden
    """
    world = fixtures.setup_open_year(api)
    year = fixtures.refresh_year(api, world)
    draft = fixtures.create_announcement(api, year["id"], year["version"])

    validate_error(
        api.publish_allocation_announcement(draft["id"], world["mgr_sr_headers"]),
        ApiErrorId.ERR_FORBIDDEN,
    )

    announcement = fixtures.find_announcement(api, year["id"], draft["id"])
    assert announcement["status"] == "DRAFT", "the forbidden publish must not advance the draft"
