"""The venue survey lifecycle and the append-only camera plot beneath it.

Every test starts against an empty database with the logical clock at its
startup value and builds its own survey chain through the shared helpers.
"""

import pytest

from test_helpers import (
    assert_append_only_row,
    assert_camera_position,
    assert_created_at_ascending,
    assert_instant_equals,
    assert_labor_ledger,
    assert_pagination_meta,
    assert_readiness,
    assert_status,
    assert_two_decimal_places,
    assert_venue_survey,
    assert_versioned_row,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CANONICAL_EVENT, CLOCK_EPOCH_STAMP
from test_helpers.factories import (
    create_camera_position_payload,
    create_venue_survey_payload,
    crew_call_response_payload,
    survey_review_payload,
)
from test_helpers.fixtures import (
    SINGLE_CAMERA_PLOT,
    add_camera_position,
    create_approved_survey,
    decline_call,
    new_crew_member,
    new_production,
    new_survey,
    offer_call,
    read_crew_call,
    read_production,
    read_survey,
    review_survey,
    setup_survey_at_revision,
    submit_survey,
)
from test_helpers.test_users import (
    LEAGUE_OPERATIONS_ID,
    TECHNICAL_DIRECTOR_ID,
    make_crew_member_headers,
)


def _empty_draft_survey(api, production_id, headers, **overrides):
    """A DRAFT survey with no camera positions yet."""
    return validate_success(
        api.create_venue_survey(
            create_venue_survey_payload(production_id, **overrides), headers
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Camera positions and their derived values
# ---------------------------------------------------------------------------
def test_camera_position_derives_its_loss_and_operator_flag_from_the_declared_inputs(
    api, pm_headers, td_headers
):
    """Neither derived value is a client input: a 150 ft run yields 2.03 dB on both
    rows while the operator flag follows the position type alone.

    PRD: "Two values are derived per position and stored on it."
    PRD: "`requires_operator` is true for `HARD`, `HANDHELD` and `AERIAL` positions and false for `ROBO` positions, which are driven from inside the truck."
    PRD: "`signal_loss_db` is the cable loss on that run: the coax budget is **1.35 dB per 100 feet**, so the position's loss is its cable run in feet multiplied by 1.35, divided by 100, and rounded half up to two decimal places."
    Design: Corner/entities/camera_position_computed_fields_ignore_client_supplied_values
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)

    hard = validate_success(
        api.create_camera_position(
            survey["id"],
            create_camera_position_payload(
                label="HIGH_HOME",
                position_type="HARD",
                cable_run_feet=150,
                power_draw_amps=20,
            ),
            td_headers,
        ),
        201,
    )
    assert_camera_position(hard)
    assert hard["signal_loss_db"] == pytest.approx(2.03, abs=0.005)
    assert_two_decimal_places(hard["signal_loss_db"], "signal_loss_db")
    assert hard["requires_operator"] is True, "a HARD position needs an operator"

    robo = validate_success(
        api.create_camera_position(
            survey["id"],
            create_camera_position_payload(
                label="CENTER_FIELD",
                position_type="ROBO",
                cable_run_feet=150,
                power_draw_amps=20,
            ),
            td_headers,
        ),
        201,
    )
    assert_camera_position(robo)
    assert robo["signal_loss_db"] == pytest.approx(2.03, abs=0.005), (
        "the same cable run yields the same loss whatever the position type"
    )
    assert robo["requires_operator"] is False, "a ROBO position is driven from the truck"


def test_camera_plot_aggregates_are_recomputed_after_every_position_lands(
    api, pm_headers, td_headers
):
    """All five survey aggregates follow from the positions on the plot, with headroom
    read against the venue's declared capacity.

    PRD: "Either way, five aggregates on the survey are recomputed after the position lands: `camera_position_count` is the number of positions on the survey; `total_cable_run_feet` is the sum of their cable runs; `total_power_draw_amps` is the sum of their amp draws; `power_headroom_amps` is the production's `venue_power_capacity_amps` minus that amp total, and may be negative; and `total_signal_loss_db` is the survey's loss budget."
    PRD: "Camera positions are append-only and carry no lifecycle, so every position on the survey participates in the aggregates with no status filter."
    Design: Corner/entities/camera_position_computed_fields_ignore_client_supplied_values
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    assert survey["camera_position_count"] == 0
    assert survey["power_headroom_amps"] == CANONICAL_EVENT["venue_power_capacity_amps"]

    add_camera_position(
        api, survey["id"], headers=td_headers, label="HIGH_HOME",
        position_type="HARD", cable_run_feet=150, power_draw_amps=20,
    )
    add_camera_position(
        api, survey["id"], headers=td_headers, label="CENTER_FIELD",
        position_type="ROBO", cable_run_feet=150, power_draw_amps=20,
    )

    plotted = read_survey(api, survey["id"], td_headers)
    assert_venue_survey(plotted)
    assert plotted["camera_position_count"] == 2
    assert plotted["total_cable_run_feet"] == 300
    assert plotted["total_power_draw_amps"] == 40
    assert plotted["power_headroom_amps"] == 360, "400 A capacity less 40 A drawn"
    assert plotted["total_signal_loss_db"] == pytest.approx(4.06, abs=0.005)


# ---------------------------------------------------------------------------
# Server-minted survey fields
# ---------------------------------------------------------------------------
def test_new_survey_opens_at_draft_revision_one_with_no_operator_stamps(
    api, pm_headers, td_headers
):
    """The survey's stage, revision counter and both operator stamps are system-sourced,
    so a fresh survey reads DRAFT / 1 / null / null at version 1.

    PRD: "The new survey starts at `DRAFT` with its `revision` counter at 1, and it may not be opened at all against a production that is already `ON_AIR`, `WRAPPED` or `SETTLED` — such an attempt is refused with `ERR_PRODUCTION_STATE_INVALID`."
    PRD: "Most resources additionally carry `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row — including mutations the server performs on its own initiative as a cascade, not only those an operator requests directly."
    PRD: "Every resource carries a server-minted `id` — a UUID string with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC instant rendered with exactly three fractional-second digits."
    Design: Corner/entities/venue_survey_system_fields_are_server_minted
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)

    assert_venue_survey(survey)
    assert_versioned_row(survey, expected_version=1)
    assert_status(survey, "DRAFT", "survey status")
    assert survey["revision"] == 1, "the revision counter opens at 1"
    assert survey["submitted_by_user_id"] is None, "no submitter is stamped yet"
    assert survey["reviewed_by_user_id"] is None, "no reviewer is stamped yet"
    assert survey["production_id"] == production["id"]
    assert_instant_equals(survey["created_at"], CLOCK_EPOCH_STAMP, "survey.created_at")


def test_survey_submit_stamps_the_submitting_operator_from_the_request_header(
    api, pm_headers, td_headers
):
    """Submission is what mints `submitted_by_user_id`, and it is taken from the
    submitting operator's identity header while the reviewer stamp stays null.

    PRD: "On success the survey moves `DRAFT → SUBMITTED` and its `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
    PRD: "Either decision stamps `reviewed_by_user_id` with the reviewer's operator identifier."
    Design: Corner/entities/venue_survey_system_fields_are_server_minted
    """
    production = new_production(api, pm_headers)
    survey = new_survey(
        api, production["id"], SINGLE_CAMERA_PLOT, headers=td_headers
    )
    assert survey["submitted_by_user_id"] is None

    submitted = validate_success(api.submit_venue_survey(survey["id"], td_headers), 200)
    assert_status(submitted, "SUBMITTED", "survey status")
    assert submitted["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID
    assert submitted["reviewed_by_user_id"] is None, (
        "the reviewer stamp waits for a review decision"
    )
    assert submitted["version"] > survey["version"], (
        "submitting mutates the survey row and bumps its version"
    )


# ---------------------------------------------------------------------------
# Camera positions are append-only
# ---------------------------------------------------------------------------
def test_camera_position_row_carries_neither_version_nor_updated_at(
    api, pm_headers, td_headers
):
    """A camera position is one of the two append-only log rows, so it exposes only id
    and created_at beside its own declared and derived fields.

    PRD: "Two resources are append-only log rows and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version` field at all: `CameraPosition` and `Incident`."
    PRD: "Neither is ever modified after creation."
    Design: Corner/entities/camera_position_is_immutable_and_carries_no_version
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)

    position = validate_success(
        api.create_camera_position(
            survey["id"],
            create_camera_position_payload(
                label="HIGH_HOME", position_type="HARD",
                cable_run_feet=150, power_draw_amps=20,
            ),
            td_headers,
        ),
        201,
    )

    assert_append_only_row(position)
    assert_camera_position(position)
    assert position["survey_id"] == survey["id"]
    assert position["label"] == "HIGH_HOME"
    assert position["position_type"] == "HARD"
    assert position["cable_run_feet"] == 150
    assert position["power_draw_amps"] == 20
    assert_instant_equals(
        position["created_at"], CLOCK_EPOCH_STAMP, "camera_position.created_at"
    )


def test_camera_plot_listing_filters_by_position_type(api, pm_headers, td_headers, lo_headers):
    """The plot listing narrows to a single position type and stays ordered by creation.

    PRD: "The plot can be listed back with an optional `position_type` filter to see just the hard cameras or just the robos."
    PRD: "Child rows created beneath a parent take their parent reference from the URL, never from the body."
    Design: Corner/entities/camera_position_is_immutable_and_carries_no_version
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    hard = add_camera_position(
        api, survey["id"], headers=td_headers, label="HIGH_HOME",
        position_type="HARD", cable_run_feet=150, power_draw_amps=20,
    )
    robo = add_camera_position(
        api, survey["id"], headers=td_headers, label="CENTER_FIELD",
        position_type="ROBO", cable_run_feet=150, power_draw_amps=20,
    )

    hard_rows, hard_meta = validate_paginated(
        api.list_camera_positions(survey["id"], lo_headers, params={"position_type": "HARD"})
    )
    assert [row["id"] for row in hard_rows] == [hard["id"]]
    assert_pagination_meta(hard_meta, total_count=1, has_more=False)

    all_rows, all_meta = validate_paginated(
        api.list_camera_positions(survey["id"], lo_headers)
    )
    assert [row["id"] for row in all_rows] == [hard["id"], robo["id"]]
    assert_created_at_ascending(all_rows)
    assert_pagination_meta(all_meta, total_count=2, has_more=False)
    for row in all_rows:
        assert row["survey_id"] == survey["id"], "each child names its URL parent"


# ---------------------------------------------------------------------------
# The bounded revision loop
# ---------------------------------------------------------------------------
def test_submit_refused_once_the_revision_counter_has_passed_three(
    api, pm_headers, td_headers
):
    """Three rounds of requested changes drive the revision to 4, and the fourth
    submission is refused on the revision ceiling alone.

    PRD: "First, the loop must not have run away: submission is refused with `ERR_SURVEY_REVISION_LIMIT` once the survey's `revision` has passed 3, so at most three revisions may ever be submitted."
    PRD: "Adding a position to a survey that sits at `CHANGES_REQUESTED` is what re-opens the revision loop: the survey moves `CHANGES_REQUESTED → DRAFT`, its `revision` is incremented by 1, and its `submitted_by_user_id` is cleared back to null so that the next submission records a fresh submitter."
    Design: Corner/state_machines/survey_revision_loop_bounded_by_max_survey_revisions
    """
    production = new_production(api, pm_headers)
    survey = setup_survey_at_revision(api, production["id"], 4, SINGLE_CAMERA_PLOT)

    assert survey["revision"] == 4
    assert_status(survey, "DRAFT", "survey status")
    assert survey["camera_position_count"] == 4
    assert survey["total_signal_loss_db"] == pytest.approx(8.12, abs=0.005), (
        "four 150 ft runs stay inside the 10.13 dB budget"
    )
    assert survey["total_power_draw_amps"] == 80
    assert survey["power_headroom_amps"] == 320, "power is not what refuses the submit"

    validate_error(
        api.submit_venue_survey(survey["id"], td_headers), "ERR_SURVEY_REVISION_LIMIT"
    )

    after = read_survey(api, survey["id"], td_headers)
    assert_status(after, "DRAFT", "survey status")
    assert after["revision"] == 4, "the refused submit does not advance the counter"


def test_submit_at_revision_three_is_still_inside_the_ceiling(
    api, pm_headers, td_headers
):
    """The ceiling is on revisions past 3, so the third revision still submits.

    PRD: "First, the loop must not have run away: submission is refused with `ERR_SURVEY_REVISION_LIMIT` once the survey's `revision` has passed 3, so at most three revisions may ever be submitted."
    PRD: "On success the survey moves `DRAFT → SUBMITTED` and its `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
    Design: Corner/state_machines/survey_revision_loop_bounded_by_max_survey_revisions
    """
    production = new_production(api, pm_headers)
    survey = setup_survey_at_revision(api, production["id"], 3, SINGLE_CAMERA_PLOT)
    assert survey["revision"] == 3
    assert survey["camera_position_count"] == 3
    assert survey["total_signal_loss_db"] == pytest.approx(6.09, abs=0.005)

    submitted = validate_success(api.submit_venue_survey(survey["id"], td_headers), 200)
    assert_status(submitted, "SUBMITTED", "survey status")
    assert submitted["revision"] == 3, "submitting does not touch the counter"
    assert submitted["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID


# ---------------------------------------------------------------------------
# Terminal states are inert
# ---------------------------------------------------------------------------
def test_superseded_survey_refuses_both_submit_and_review(
    api, pm_headers, td_headers, lo_headers
):
    """Once a replacement survey has superseded it, the old survey answers every further
    lifecycle trigger with a state error and stays SUPERSEDED.

    PRD: "Submitting the survey for league review is the `TechnicalDirector`'s last act on it, and it is gated on four conditions in addition to the survey being in `DRAFT` (anything else is `ERR_SURVEY_STATE_INVALID`)."
    PRD: "Review is only possible on a `SUBMITTED` survey, and the reviewing operator's `X-User-ID` must differ from the survey's `submitted_by_user_id` or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/state_machines/superseded_survey_and_declined_call_reject_every_further_trigger
    """
    production = new_production(api, pm_headers)
    approved = create_approved_survey(api, production["id"], SINGLE_CAMERA_PLOT)
    replacement = _empty_draft_survey(
        api, production["id"], td_headers, surveyor_name="K. Ozawa",
        fiber_drops_required=3,
    )

    superseded = read_survey(api, approved["id"], td_headers)
    assert_status(superseded, "SUPERSEDED", "survey status")
    assert_status(read_survey(api, replacement["id"], td_headers), "DRAFT", "survey status")

    validate_error(
        api.submit_venue_survey(approved["id"], td_headers), "ERR_SURVEY_STATE_INVALID"
    )
    validate_error(
        api.review_venue_survey(
            approved["id"], survey_review_payload("APPROVE"), lo_headers
        ),
        "ERR_SURVEY_STATE_INVALID",
    )

    still = read_survey(api, approved["id"], td_headers)
    assert_status(still, "SUPERSEDED", "survey status")
    assert still["reviewed_by_user_id"] == LEAGUE_OPERATIONS_ID, (
        "the original approval stamp survives the refused triggers"
    )
    assert_status(read_production(api, production["id"]), "PLANNED", "production stage")


def test_declined_crew_call_refuses_both_a_second_response_and_a_cancellation(
    api, pm_headers
):
    """A declined call is terminal: responding again and cancelling both fail on the
    call's own status, and its provisional reserve stays released.

    PRD: "A `CrewMember` supplies a `decision` of `ACCEPT` or `DECLINE`; a call in any status other than `OFFERED` is refused with `ERR_CREW_CALL_STATE_INVALID`, and a responder whose `X-User-ID` is not the call's `crew_member_id` is refused with `ERR_NOT_CALL_OWNER`."
    PRD: "Cancelling a call is also a `ProductionManager` action, permitted from `OFFERED` and from `ACCEPTED` — a call already `DECLINED`, `RELEASED` or `CANCELLED` is refused with `ERR_CREW_CALL_STATE_INVALID`."
    PRD: "A decline moves the call `OFFERED → DECLINED`, at which point the call stops contributing to `labor_committed_cents` and its provisional reserve is released in full; the derivation runs again."
    Design: Corner/state_machines/superseded_survey_and_declined_call_reject_every_further_trigger
    """
    production = new_production(api, pm_headers)
    member = new_crew_member(api, pm_headers)
    call = offer_call(api, production["id"], member["id"])
    declined = decline_call(api, call["id"], member["id"])
    assert_status(declined, "DECLINED", "crew call status")

    validate_error(
        api.respond_to_crew_call(
            call["id"],
            crew_call_response_payload("ACCEPT"),
            make_crew_member_headers(member["id"]),
        ),
        "ERR_CREW_CALL_STATE_INVALID",
    )
    validate_error(
        api.cancel_crew_call(call["id"], pm_headers), "ERR_CREW_CALL_STATE_INVALID"
    )

    assert_status(read_crew_call(api, call["id"]), "DECLINED", "crew call status")
    assert_labor_ledger(
        read_production(api, production["id"]),
        committed=0,
        available=CANONICAL_EVENT["labor_budget_total_cents"],
    )


# ---------------------------------------------------------------------------
# Re-surveying a venue
# ---------------------------------------------------------------------------
def test_replacement_survey_supersedes_the_approved_one_and_reverts_the_production(
    api, pm_headers, td_headers
):
    """Opening a replacement against an approved survey is a write to a different row
    that still supersedes the old one and drops the production back to PLANNED.

    PRD: "If, however, the production's current survey has already reached `APPROVED`, opening a replacement is permitted and is the intended way to re-survey a venue: the old survey moves `APPROVED → SUPERSEDED`, which leaves the production with no approved survey at all, so the derivation drops the production `SURVEYED → PLANNED`, aborts every rehearsal of that production still in `SCHEDULED`, and sets `readiness_hold` on every show execution of that production still in `PRE_SHOW`."
    PRD: "The **survey component** is worth 40 points and is awarded in full when the production has a `VenueSurvey` in `APPROVED` status, and zero otherwise."
    Design: Corner/state_machines/new_survey_supersedes_approved_survey_and_reverts_production_to_planned
    """
    production = new_production(api, pm_headers)
    approved = create_approved_survey(api, production["id"], SINGLE_CAMERA_PLOT)
    assert_status(approved, "APPROVED", "survey status")
    assert approved["reviewed_by_user_id"] == LEAGUE_OPERATIONS_ID

    surveyed = read_production(api, production["id"])
    assert_status(surveyed, "SURVEYED", "production stage")
    assert_readiness(surveyed, preflight=40.0)

    _empty_draft_survey(
        api, production["id"], td_headers, surveyor_name="K. Ozawa",
        fiber_drops_required=4,
    )

    assert_status(
        read_survey(api, approved["id"], td_headers), "SUPERSEDED", "survey status"
    )
    reverted = read_production(api, production["id"])
    assert_status(reverted, "PLANNED", "production stage")
    assert_readiness(reverted, preflight=0.0, certified=0.0)


def test_replacement_survey_opens_its_own_revision_counter_and_both_rows_stay_auditable(
    api, pm_headers, td_headers
):
    """The revision counter belongs to the survey row, so the replacement starts at 1
    while the superseded row remains listable under the production.

    PRD: "The new survey starts at `DRAFT` with its `revision` counter at 1, and it may not be opened at all against a production that is already `ON_AIR`, `WRAPPED` or `SETTLED` — such an attempt is refused with `ERR_PRODUCTION_STATE_INVALID`."
    PRD: "A survey's full history, current and superseded alike, can be listed under its production with an optional `status` filter, so the `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED` and `SUPERSEDED` lifecycle is auditable after the fact."
    Design: Corner/state_machines/new_survey_supersedes_approved_survey_and_reverts_production_to_planned
    """
    production = new_production(api, pm_headers)
    approved = create_approved_survey(api, production["id"], SINGLE_CAMERA_PLOT)

    replacement = _empty_draft_survey(
        api, production["id"], td_headers, surveyor_name="K. Ozawa",
        fiber_drops_required=4,
    )
    assert replacement["revision"] == 1, "the counter belongs to the row, not the venue"
    assert_status(replacement, "DRAFT", "survey status")
    assert replacement["camera_position_count"] == 0
    assert replacement["submitted_by_user_id"] is None
    assert replacement["reviewed_by_user_id"] is None

    rows, meta = validate_paginated(
        api.list_production_venue_surveys(production["id"], td_headers)
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)
    assert {row["id"] for row in rows} == {approved["id"], replacement["id"]}

    old_rows, old_meta = validate_paginated(
        api.list_production_venue_surveys(
            production["id"], td_headers, params={"status": "SUPERSEDED"}
        )
    )
    assert [row["id"] for row in old_rows] == [approved["id"]]
    assert_pagination_meta(old_meta, total_count=1, has_more=False)


def test_second_submit_of_a_submitted_survey_is_refused_without_restamping_it(
    api, pm_headers, td_headers, td_alt_headers
):
    """A repeated submit is an error rather than a replay: the state error leaves both
    the submitter stamp and the row version exactly as the first submit left them.

    PRD: "Submitting the survey for league review is the `TechnicalDirector`'s last act on it, and it is gated on four conditions in addition to the survey being in `DRAFT` (anything else is `ERR_SURVEY_STATE_INVALID`)."
    PRD: "On success the survey moves `DRAFT → SUBMITTED` and its `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
    Design: Corner/state_machines/repeat_survey_submit_rejected_rather_than_replayed
    """
    production = new_production(api, pm_headers)
    survey = new_survey(api, production["id"], SINGLE_CAMERA_PLOT, headers=td_headers)
    submitted = submit_survey(api, survey["id"], td_headers)
    assert submitted["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID

    validate_error(
        api.submit_venue_survey(survey["id"], td_alt_headers),
        "ERR_SURVEY_STATE_INVALID",
    )

    after = read_survey(api, survey["id"], td_headers)
    assert_status(after, "SUBMITTED", "survey status")
    assert after["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID, (
        "the refused submit does not re-stamp the submitter"
    )
    assert after["version"] == submitted["version"], (
        "a refused submit writes nothing, so the version is unchanged"
    )


# ---------------------------------------------------------------------------
# Only one survey in flight per production
# ---------------------------------------------------------------------------
def test_second_survey_refused_while_the_first_is_still_a_draft(
    api, pm_headers, td_headers
):
    """A production may not have two surveys in flight, so a second attempt against a
    DRAFT first survey is refused and no second row is created.

    PRD: "A production may not have two surveys in flight."
    PRD: "If any existing survey of the production is in `DRAFT`, `SUBMITTED` or `CHANGES_REQUESTED`, opening another is refused with `ERR_SURVEY_ALREADY_OPEN`."
    Design: Corner/validations/second_open_survey_rejected_while_one_is_still_in_review
    """
    production = new_production(api, pm_headers)
    first = new_survey(api, production["id"], SINGLE_CAMERA_PLOT, headers=td_headers)
    assert_status(first, "DRAFT", "survey status")

    validate_error(
        api.create_venue_survey(
            create_venue_survey_payload(production["id"], surveyor_name="K. Ozawa"),
            td_headers,
        ),
        "ERR_SURVEY_ALREADY_OPEN",
    )

    rows, meta = validate_paginated(
        api.list_production_venue_surveys(production["id"], td_headers)
    )
    assert [row["id"] for row in rows] == [first["id"]]
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_second_survey_still_refused_once_the_first_has_been_submitted(
    api, pm_headers, td_headers
):
    """SUBMITTED is still an open state, so handing the survey to league review does not
    unlock a replacement.

    PRD: "If any existing survey of the production is in `DRAFT`, `SUBMITTED` or `CHANGES_REQUESTED`, opening another is refused with `ERR_SURVEY_ALREADY_OPEN`."
    PRD: "On success the survey moves `DRAFT → SUBMITTED` and its `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
    Design: Corner/validations/second_open_survey_rejected_while_one_is_still_in_review
    """
    production = new_production(api, pm_headers)
    first = new_survey(api, production["id"], SINGLE_CAMERA_PLOT, headers=td_headers)
    submitted = submit_survey(api, first["id"], td_headers)
    assert_status(submitted, "SUBMITTED", "survey status")
    assert submitted["revision"] == 1

    validate_error(
        api.create_venue_survey(
            create_venue_survey_payload(production["id"], surveyor_name="K. Ozawa"),
            td_headers,
        ),
        "ERR_SURVEY_ALREADY_OPEN",
    )

    _rows, meta = validate_paginated(
        api.list_production_venue_surveys(production["id"], td_headers)
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_production_survey_listing_returns_only_that_production_children(
    api, pm_headers, td_headers, us_headers
):
    """Two productions each hold one survey, and each parent listing returns only its
    own child even though both rows live in one collection.

    PRD: "A survey's full history, current and superseded alike, can be listed under its production with an optional `status` filter, so the `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED` and `SUPERSEDED` lifecycle is auditable after the fact."
    PRD: "A child that exists but belongs to a different parent than the one named in the path is treated as not existing under that path."
    Design: Corner/endpoints/venue_survey_subresource_listing_is_scoped_to_its_parent
    """
    production_a = new_production(api, pm_headers, venue_name="Riverside Arena")
    production_b = new_production(
        api, pm_headers, venue_name="Harbor Dome", venue_roof_type="DOMED",
        scheduled_start_utc="2026-08-19T18:00:00Z",
        scheduled_end_utc="2026-08-19T22:00:00Z",
        venue_curfew_utc="2026-08-20T06:00:00Z",
    )
    survey_a = _empty_draft_survey(api, production_a["id"], td_headers)
    survey_b = _empty_draft_survey(
        api, production_b["id"], td_headers, surveyor_name="K. Ozawa",
        fiber_drops_required=3,
    )

    a_rows, a_meta = validate_paginated(
        api.list_production_venue_surveys(production_a["id"], us_headers)
    )
    assert [row["id"] for row in a_rows] == [survey_a["id"]]
    assert_pagination_meta(a_meta, total_count=1, has_more=False)

    b_rows, b_meta = validate_paginated(
        api.list_production_venue_surveys(
            production_b["id"], us_headers, params={"status": "DRAFT"}
        )
    )
    assert [row["id"] for row in b_rows] == [survey_b["id"]]
    assert_pagination_meta(b_meta, total_count=1, has_more=False)

    read_b = validate_success(api.get_venue_survey(survey_b["id"], us_headers), 200)
    assert read_b["production_id"] == production_b["id"]
    assert read_b["fiber_drops_required"] == 3


# ---------------------------------------------------------------------------
# The backward revision edge, fired by creating a child row
# ---------------------------------------------------------------------------
def _survey_at_changes_requested(api, production_id, td_headers, lo_headers):
    """A revision-1 survey with a 150 ft HARD and a 250 ft HANDHELD position, submitted
    by td-001 and then sent back by lo-001."""
    survey = _empty_draft_survey(api, production_id, td_headers)
    add_camera_position(
        api, survey["id"], headers=td_headers, label="HIGH_HOME",
        position_type="HARD", cable_run_feet=150, power_draw_amps=20,
    )
    add_camera_position(
        api, survey["id"], headers=td_headers, label="LOW_FIRST",
        position_type="HANDHELD", cable_run_feet=250, power_draw_amps=20,
    )
    submit_survey(api, survey["id"], td_headers)
    return review_survey(api, survey["id"], "REQUEST_CHANGES", lo_headers)


def test_camera_position_on_a_changes_requested_survey_reopens_it_at_a_new_revision(
    api, pm_headers, td_headers, lo_headers
):
    """The backward edge out of CHANGES_REQUESTED is fired by creating a child camera
    position, which bumps the revision and clears the submitter stamp.

    PRD: "Adding a position to a survey that sits at `CHANGES_REQUESTED` is what re-opens the revision loop: the survey moves `CHANGES_REQUESTED → DRAFT`, its `revision` is incremented by 1, and its `submitted_by_user_id` is cleared back to null so that the next submission records a fresh submitter."
    PRD: "A request for changes moves the survey `SUBMITTED → CHANGES_REQUESTED` and leaves the production's stage exactly where it was."
    Design: Difficulty/non_linear_state_machine/venue_survey_backward_revision_edge_reopened_by_child_creation
    """
    production = new_production(api, pm_headers)
    sent_back = _survey_at_changes_requested(
        api, production["id"], td_headers, lo_headers
    )
    assert_status(sent_back, "CHANGES_REQUESTED", "survey status")
    assert sent_back["revision"] == 1
    assert sent_back["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID
    assert_status(read_production(api, production["id"]), "PLANNED", "production stage")

    third = add_camera_position(
        api, sent_back["id"], headers=td_headers, label="CENTER_FIELD",
        position_type="ROBO", cable_run_feet=100, power_draw_amps=20,
    )
    assert third["requires_operator"] is False
    assert third["signal_loss_db"] == pytest.approx(1.35, abs=0.005), (
        "100 feet at 1.35 dB per 100 feet is 1.35 dB"
    )

    reopened = read_survey(api, sent_back["id"], td_headers)
    assert_status(reopened, "DRAFT", "survey status")
    assert reopened["revision"] == 2, "crossing the edge increments the revision by 1"
    assert reopened["submitted_by_user_id"] is None, (
        "the submitter stamp is cleared so the next submission records a fresh one"
    )
    assert reopened["camera_position_count"] == 3
    assert reopened["total_signal_loss_db"] == pytest.approx(6.76, abs=0.005)
    assert reopened["total_power_draw_amps"] == 60
    assert reopened["power_headroom_amps"] == 340


def test_camera_position_on_a_draft_survey_is_a_pure_aggregate_update(
    api, pm_headers, td_headers
):
    """The very same child creation against a survey already in DRAFT touches neither the
    revision counter nor the submitter stamp, only the aggregates.

    PRD: "Adding a position to a survey already in `DRAFT` leaves both `revision` and `submitted_by_user_id` untouched."
    PRD: "Either way, five aggregates on the survey are recomputed after the position lands: `camera_position_count` is the number of positions on the survey; `total_cable_run_feet` is the sum of their cable runs; `total_power_draw_amps` is the sum of their amp draws; `power_headroom_amps` is the production's `venue_power_capacity_amps` minus that amp total, and may be negative; and `total_signal_loss_db` is the survey's loss budget."
    Design: Difficulty/non_linear_state_machine/venue_survey_backward_revision_edge_reopened_by_child_creation
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    add_camera_position(
        api, survey["id"], headers=td_headers, label="HIGH_HOME",
        position_type="HARD", cable_run_feet=150, power_draw_amps=20,
    )
    one_position = read_survey(api, survey["id"], td_headers)
    assert_status(one_position, "DRAFT", "survey status")
    assert one_position["revision"] == 1
    assert one_position["submitted_by_user_id"] is None

    add_camera_position(
        api, survey["id"], headers=td_headers, label="LOW_FIRST",
        position_type="HANDHELD", cable_run_feet=250, power_draw_amps=20,
    )

    two_positions = read_survey(api, survey["id"], td_headers)
    assert_status(two_positions, "DRAFT", "survey status")
    assert two_positions["revision"] == 1, "no backward edge was crossed"
    assert two_positions["submitted_by_user_id"] is None
    assert two_positions["camera_position_count"] == 2
    assert two_positions["total_cable_run_feet"] == 400
    assert two_positions["total_power_draw_amps"] == 40
    assert two_positions["power_headroom_amps"] == 360
    assert two_positions["total_signal_loss_db"] == pytest.approx(5.41, abs=0.005)


def test_reopened_survey_is_resubmitted_and_approved_at_its_second_revision(
    api, pm_headers, td_headers, lo_headers
):
    """After the backward edge the segregation-of-duties pairing is re-armed, so the same
    two operators can carry the second revision through to approval.

    PRD: "Adding a position to a survey that sits at `CHANGES_REQUESTED` is what re-opens the revision loop: the survey moves `CHANGES_REQUESTED → DRAFT`, its `revision` is incremented by 1, and its `submitted_by_user_id` is cleared back to null so that the next submission records a fresh submitter."
    PRD: "An approval moves the survey `SUBMITTED → APPROVED` and drives the production `PLANNED → SURVEYED` through the derivation, which — if a truck, a confirmed primary transport and enough validated preps are already in place — can carry the production straight on to `PROVISIONED` in the same request."
    Design: Difficulty/non_linear_state_machine/venue_survey_backward_revision_edge_reopened_by_child_creation
    """
    production = new_production(api, pm_headers)
    sent_back = _survey_at_changes_requested(
        api, production["id"], td_headers, lo_headers
    )
    add_camera_position(
        api, sent_back["id"], headers=td_headers, label="CENTER_FIELD",
        position_type="ROBO", cable_run_feet=100, power_draw_amps=20,
    )

    resubmitted = validate_success(
        api.submit_venue_survey(sent_back["id"], td_headers), 200
    )
    assert_status(resubmitted, "SUBMITTED", "survey status")
    assert resubmitted["revision"] == 2
    assert resubmitted["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID

    approved = validate_success(
        api.review_venue_survey(
            sent_back["id"], survey_review_payload("APPROVE"), lo_headers
        ),
        200,
    )
    assert_status(approved, "APPROVED", "survey status")
    assert approved["revision"] == 2
    assert approved["reviewed_by_user_id"] == LEAGUE_OPERATIONS_ID

    assert_status(read_production(api, production["id"]), "SURVEYED", "production stage")
