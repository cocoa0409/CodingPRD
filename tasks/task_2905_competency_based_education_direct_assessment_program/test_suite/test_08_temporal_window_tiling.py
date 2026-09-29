"""Half-open interval semantics on two resource timelines: mutually exclusive
subscription-term windows, and the contiguous blueprint tiling.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import (
    create_blueprint_payload,
    create_subscription_term_payload,
    rubric_dimension,
)

FIRST_TERM_END_UTC = "2026-12-01T00:00:00.000Z"
OVERLAPPING_START_UTC = "2026-11-15T00:00:00.000Z"
OVERLAPPING_END_UTC = "2027-02-15T00:00:00.000Z"
ADJACENT_END_UTC = "2027-03-01T00:00:00.000Z"

SHORT_NOTICE_UTC = "2026-09-14T00:00:00.000Z"
EXACT_NOTICE_UTC = "2026-09-15T00:00:00.000Z"

SINGLE_DIMENSION = [rubric_dimension("D1", 1.0000, 100, False)]


def _student_holding_one_active_term():
    """A student with a single ACTIVE term over [2026-09-01, 2026-12-01)."""
    ctx = fx.base_chain()
    assert ctx["term"]["status"] == "ACTIVE"
    A.assert_instant_equals(ctx["term"]["term_end_utc"], FIRST_TERM_END_UTC,
                            "term_end_utc")
    return ctx


def test_a_second_window_that_intersects_the_live_one_is_refused():
    """A window opening two weeks before the incumbent ends genuinely intersects
    it, so the create is refused and no row is written.

    PRD: "Term windows are half-open, running from `term_start_utc` inclusive to
    `term_end_utc` exclusive, and the requested window must not intersect any of the
    student's existing terms other than cancelled ones; because the windows are
    half-open, one term ending at exactly the instant the next begins is adjacency
    rather than overlap and is permitted, while any genuine intersection is refused
    with `ERR_TERM_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/term_window_overlap_half_open_adjacent_allowed
    """
    ctx = _student_holding_one_active_term()

    response = api_client.create_subscription_term(
        create_subscription_term_payload(
            ctx["student"]["id"],
            term_start_utc=OVERLAPPING_START_UTC,
            term_end_utc=OVERLAPPING_END_UTC,
        ),
        fx.REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_TERM_WINDOW_OVERLAP.value, 409)

    A.assert_page(
        api_client.list_subscription_terms(
            fx.REGISTRAR, params={"student_id": ctx["student"]["id"]}
        ),
        1,
    )


def test_a_window_opening_exactly_where_the_live_one_ends_is_adjacency_not_overlap():
    """Starting at the very instant the incumbent's exclusive end bound falls is
    permitted, because the incumbent never owned that instant.

    PRD: "because the windows are half-open, one term ending at exactly the instant
    the next begins is adjacency rather than overlap and is permitted, while any
    genuine intersection is refused with `ERR_TERM_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/term_window_overlap_half_open_adjacent_allowed
    """
    ctx = _student_holding_one_active_term()

    response = api_client.create_subscription_term(
        create_subscription_term_payload(
            ctx["student"]["id"],
            term_start_utc=FIRST_TERM_END_UTC,
            term_end_utc=ADJACENT_END_UTC,
        ),
        fx.REGISTRAR,
    )
    second = validate_success(response, 201)
    assert second["status"] == "PENDING"
    A.assert_instant_equals(second["term_start_utc"], FIRST_TERM_END_UTC,
                            "term_start_utc")

    incumbent = fx.refresh_term(ctx["term"]["id"])
    assert incumbent["status"] == "ACTIVE"
    A.assert_instant_equals(incumbent["term_end_utc"], FIRST_TERM_END_UTC,
                            "term_end_utc")

    A.assert_page(
        api_client.list_subscription_terms(
            fx.REGISTRAR, params={"student_id": ctx["student"]["id"]}
        ),
        2,
    )


def _competency_with_its_first_rubric():
    """A competency whose first blueprint takes force at 2026-09-01 — the first
    rubric is exempt from the notice period."""
    ctx = fx.base_chain(with_blueprint=True, blueprint_dimensions=SINGLE_DIMENSION)
    assert ctx["blueprint"]["status"] == "PUBLISHED"
    assert ctx["blueprint"]["effective_to_utc"] is None
    assert ctx["competency"]["effective_blueprint_id"] == ctx["blueprint"]["id"]
    return ctx


def _supersede(ctx, effective_from_utc):
    """Attempt a superseding publication, always supplying the competency's
    current version."""
    competency = fx.refresh_competency(ctx["competency"]["id"])
    return api_client.create_blueprint(
        create_blueprint_payload(
            competency["id"], competency["version"],
            dimensions=SINGLE_DIMENSION,
            effective_from_utc=effective_from_utc,
        ),
        fx.REGISTRAR,
    )


def test_a_superseding_rubric_one_day_short_of_the_notice_period_is_refused():
    """Thirteen days of runway against a fourteen-day notice period is refused, and
    the incumbent window is left wide open.

    PRD: "Only then is the notice period examined: the requested `effective_from_utc`
    must be at or after the logical clock advanced by the program's
    `blueprint_notice_days`, and a shorter runway is refused with
    `ERR_BLUEPRINT_NOTICE_TOO_SHORT`."

    Design: Difficulty/resource_temporal_overlap/blueprint_window_contiguous_tiling_with_notice
    """
    ctx = _competency_with_its_first_rubric()

    validate_error(_supersede(ctx, SHORT_NOTICE_UTC),
                   ApiErrorId.ERR_BLUEPRINT_NOTICE_TOO_SHORT.value, 422)

    incumbent = fx.refresh_blueprint(ctx["blueprint"]["id"])
    assert incumbent["status"] == "PUBLISHED"
    assert incumbent["effective_to_utc"] is None
    A.assert_page(
        api_client.list_blueprints(
            fx.REGISTRAR, params={"competency_id": ctx["competency"]["id"]}
        ),
        1,
    )


def test_exactly_fourteen_days_of_notice_closes_the_incumbent_window_on_the_boundary():
    """The notice boundary is inclusive, and a successful publication does not merely
    coexist with the incumbent: it closes the incumbent's window at exactly the new
    start instant.

    PRD: "Finally the current blueprint's `effective_to_utc` is set to exactly the
    requested `effective_from_utc` and its `status` becomes `SUPERSEDED`, and the new
    blueprint is inserted as `PUBLISHED` with `effective_to_utc` null."

    Design: Difficulty/resource_temporal_overlap/blueprint_window_contiguous_tiling_with_notice
    """
    ctx = _competency_with_its_first_rubric()

    successor = validate_success(_supersede(ctx, EXACT_NOTICE_UTC), 201)
    assert successor["status"] == "PUBLISHED"
    A.assert_instant_equals(successor["effective_from_utc"], EXACT_NOTICE_UTC,
                            "effective_from_utc")
    assert successor["effective_to_utc"] is None

    incumbent = fx.refresh_blueprint(ctx["blueprint"]["id"])
    assert incumbent["status"] == "SUPERSEDED"
    A.assert_instant_equals(incumbent["effective_to_utc"], EXACT_NOTICE_UTC,
                            "effective_to_utc")

    A.assert_page(
        api_client.list_blueprints(
            fx.REGISTRAR, params={"competency_id": ctx["competency"]["id"]}
        ),
        2,
    )


def test_the_clock_still_resolves_to_the_superseded_window_that_owns_the_instant():
    """The effective-rubric cache follows the window lookup rather than the status
    flag: at 2026-09-01 the newer window does not own the instant, so the superseded
    one is still in force.

    PRD: "The blueprint in force at some instant is the unique one whose
    `effective_from_utc` is at or before that instant and whose `effective_to_utc` is
    either null or strictly after it."

    Design: Difficulty/resource_temporal_overlap/blueprint_window_contiguous_tiling_with_notice
    """
    ctx = _competency_with_its_first_rubric()
    validate_success(_supersede(ctx, EXACT_NOTICE_UTC), 201)

    competency = fx.refresh_competency(ctx["competency"]["id"])
    assert competency["effective_blueprint_id"] == ctx["blueprint"]["id"]
    A.assert_instant_equals(fx.read_clock()["current_utc"], BASE_CLOCK_UTC,
                            "current_utc")


def test_repeating_the_incumbents_own_start_instant_is_a_contiguity_failure():
    """The strictly-later check runs before the notice check, so an instant that
    satisfies the notice period but repeats the incumbent's start is reported as a
    contiguity failure and carries the 409, not the 422.

    PRD: "Otherwise, the requested `effective_from_utc` must be strictly later than
    the current blueprint's `effective_from_utc`; an equal or earlier instant is
    refused with `ERR_BLUEPRINT_WINDOW_NOT_CONTIGUOUS`, because it would leave either
    a gap or an overlap in the tiling."

    Design: Difficulty/resource_temporal_overlap/blueprint_window_contiguous_tiling_with_notice
    """
    ctx = _competency_with_its_first_rubric()
    validate_success(_supersede(ctx, EXACT_NOTICE_UTC), 201)

    validate_error(_supersede(ctx, EXACT_NOTICE_UTC),
                   ApiErrorId.ERR_BLUEPRINT_WINDOW_NOT_CONTIGUOUS.value, 409)

    A.assert_page(
        api_client.list_blueprints(
            fx.REGISTRAR, params={"competency_id": ctx["competency"]["id"]}
        ),
        2,
    )
