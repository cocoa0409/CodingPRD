"""
Marked fish, tag loss, and the two contribution measures a single recovery produces.

A recovery is meaningless before the fish are in the water, so a trip that has not
been released refuses one outright. Once it has, one report of 57 fish yields two
indices side by side: the cohort measure divides by the marks that survived tagging,
while the harvest measure expands the creel census over every fish released.
"""

from test_helpers import (
    BIO_CARLA_HEADERS,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

# 2000 fish are handled for coded wire tags; 5 percent of the tags will be lost.
CWT_PROGRAMME = {"mark_type": k.MARK_CWT, "marked_count": 2000}

# 57 recoveries out of a creel survey that covered a quarter of the catch.
RECOVERY = (57, 0.25)


def test_recoveries_against_a_trip_that_never_shipped_are_refused(api):
    """
    The trip is still `SCHEDULED`: the fish are reserved in the raceway, so no tag can
    have been recovered from the fishery. The report is refused on the trip's own state
    and neither index is written, so no contribution is ever attributed to fish that
    never entered the water.

    PRD 3.9: "Recoveries can only be reported against a trip that has reached `RELEASED`
    — a trip still `SCHEDULED`, `IN_TRANSIT` or `ABORTED` answers `ERR_INVALID_STATE`, an
    unknown trip answers `ERR_EVENT_NOT_FOUND`, and a malformed or out-of-range body
    answers `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/recoveries_on_a_scheduled_event_are_refused
    """
    ctx = fx.scheduled_trip(api, event_overrides=dict(CWT_PROGRAMME))
    assert ctx["event"]["status"] == k.EVENT_SCHEDULED, ctx["event"]["status"]

    response = api.record_event_recoveries(
        ctx["event"]["id"], f.recoveries_payload(*RECOVERY), BIO_CARLA_HEADERS
    )

    validate_error(response, err.ERR_INVALID_STATE, 409)

    event = fx.read_event(api, ctx["event"]["id"])
    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    assert_is_none(event["contribution_index_cohort"], "contribution_index_cohort")
    assert_is_none(event["contribution_index_harvest"], "contribution_index_harvest")


def test_the_cohort_index_divides_recoveries_by_the_marks_that_survived(api):
    """
    Coded wire tags are the least durable of the three methods, so the 2000 fish handled
    for marking are worth only 1900 identifiable fish at recovery. The cohort measure
    divides the 57 recoveries by that survivor count, not by the declared programme and
    not by the number of fish released.

    PRD 3.9: "The system therefore derives the trip's `effective_marked_count` by
    discounting the declared `marked_count` by a method-specific tag-loss rate: 2 percent
    for `AD_CLIP`, 5 percent for `CWT`, and 1 percent for `PIT`, with the survivor count
    rounded to a whole fish."

    PRD 3.9: "The cohort measure, `contribution_index_cohort`, is the `recovered_count`
    divided by the trip's `effective_marked_count`, rounded to four decimal places: it
    answers what fraction of the durably marked fish came back, and it is the measure a
    hatchery evaluator cares about."

    Design: Difficulty/dual_variant_calc/contribution_cohort_vs_harvest_diverge_on_same_release
    """
    ctx = fx.released_trip(api, event_overrides=dict(CWT_PROGRAMME))
    assert_integer_equals(ctx["event"]["released_count"], 2380, "released_count")

    reported = validate_success(
        api.record_event_recoveries(
            ctx["event"]["id"], f.recoveries_payload(*RECOVERY), BIO_CARLA_HEADERS
        ),
        200,
    )

    assert reported["mark_type"] == k.MARK_CWT, reported["mark_type"]
    assert_integer_equals(reported["marked_count"], 2000, "marked_count")
    assert_integer_equals(
        reported["effective_marked_count"], 1900, "effective_marked_count"
    )
    assert_integer_equals(reported["recovered_count"], 57, "recovered_count")
    # 57 / 1900 = 0.0300 exactly.
    assert_number_equals(
        reported["contribution_index_cohort"],
        0.03,
        4,
        "contribution_index_cohort",
    )


def test_the_harvest_index_expands_the_creel_survey_and_diverges_from_the_cohort(api):
    """
    The same single report answers a second, different question: expanding 57 recoveries
    over a survey that saw a quarter of the catch gives 228 estimated fish, and dividing
    that by the 2380 actually released gives 0.0958 — three times the cohort figure from
    the identical observation, with no selector deciding between them.

    PRD 3.9: "The harvest measure, `contribution_index_harvest`, first expands the
    observed recoveries to the whole fishery by dividing the `recovered_count` by the
    `creel_sample_fraction`, then divides that expanded figure by the trip's
    `released_count`, again rounded to four decimal places: it answers what fraction of
    everything released is estimated to have entered the harvest, and it is the measure a
    fishery manager cares about."

    PRD 3.9: "Reporting a recovery computes two different contribution measures, and the
    system computes and stores **both** of them side by side on every recovery, always,
    with no mode flag and no selector deciding between them."

    Design: Difficulty/dual_variant_calc/contribution_cohort_vs_harvest_diverge_on_same_release
    """
    ctx = fx.released_trip(api, event_overrides=dict(CWT_PROGRAMME))

    reported = validate_success(
        api.record_event_recoveries(
            ctx["event"]["id"], f.recoveries_payload(*RECOVERY), BIO_CARLA_HEADERS
        ),
        200,
    )

    assert reported["status"] == k.EVENT_RELEASED, reported["status"]
    assert_number_equals(reported["creel_sample_fraction"], 0.25, 2, "creel_sample_fraction")
    # (57 / 0.25) / 2380 = 228 / 2380 = 0.09579... -> 0.0958.
    assert_number_equals(
        reported["contribution_index_harvest"],
        0.0958,
        4,
        "contribution_index_harvest",
    )
    assert_number_equals(
        reported["contribution_index_cohort"],
        0.03,
        4,
        "contribution_index_cohort",
    )
    assert (
        reported["contribution_index_harvest"] != reported["contribution_index_cohort"]
    ), reported
