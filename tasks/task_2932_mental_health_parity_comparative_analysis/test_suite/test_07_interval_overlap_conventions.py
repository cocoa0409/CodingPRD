"""Two overlap rules with deliberately opposite interval conventions.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_collection,
    assert_error,
    assert_instant_equals,
    assert_score,
)
from test_helpers.constants import (
    CooperationStatus,
    NetworkTier,
    SubClassification,
    SubmissionType,
)


def _administrator_with_one_live_production_window(api):
    """One live request occupying [2026-08-01T00:00:00.000Z, 2026-09-15T00:00:00.000Z).

    The administrator keeps the default 45 contractual days, so the incumbent
    window closes exactly 45 days after the clock's start value, and it stays live
    because nothing is ever produced against it.
    """
    scenario = fx.registered_plan(api)
    request = fx.issue_vendor_request(api, scenario.admin_id, scenario.plan_year_id)
    scenario.vendor_request_id = request["id"]
    scenario.vendor_request = request
    return scenario


def _second_window_payload(scenario):
    return f.vendor_request_payload(
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=1,
        requested_submission_types=[SubmissionType.NETWORK_COMPOSITION],
    )


def test_a_production_window_collides_one_day_early_and_is_accepted_at_the_deadline_itself(api):
    """The incumbent window excludes its own `due_at`, so back-to-back issuance works.

    Issued on 2026-09-14 the new window's `issued_at` still falls strictly inside
    the incumbent, so it is refused.  Issued at exactly 2026-09-15T00:00:00.000Z it
    is accepted, and both of its deadlines are derived from that instant — 45
    contractual days to 2026-10-30 and a fixed 30 regulatory days to 2026-10-15.

    PRD: "A request issued at exactly the instant a previous window's `due_at` falls
    is therefore accepted — back-to-back production windows are legitimate — and a
    request whose predecessor has already reached `FULFILLED` never collides at all."

    Design: Difficulty/resource_temporal_overlap/production_window_is_half_open_so_adjacency_is_accepted
    """
    scenario = _administrator_with_one_live_production_window(api)
    incumbent = scenario.vendor_request
    assert_instant_equals(incumbent["issued_at"], "2026-08-01T00:00:00.000Z", "issued_at")
    assert_instant_equals(incumbent["due_at"], "2026-09-15T00:00:00.000Z", "due_at")
    assert_instant_equals(
        incumbent["regulatory_due_at"], "2026-08-31T00:00:00.000Z", "regulatory_due_at"
    )

    fx.advance_clock(api, "2026-09-14T00:00:00Z")
    assert_error(
        api.create_vendor_request(_second_window_payload(scenario), scenario.sponsor_headers),
        ApiErrorId.PRODUCTION_WINDOW_OVERLAP,
    )

    fx.advance_clock(api, "2026-09-15T00:00:00Z")
    successor = validate_success(
        api.create_vendor_request(_second_window_payload(scenario), scenario.sponsor_headers), 201
    )
    assert_instant_equals(successor["issued_at"], "2026-09-15T00:00:00.000Z", "issued_at")
    assert_instant_equals(successor["due_at"], "2026-10-30T00:00:00.000Z", "due_at")
    assert_instant_equals(
        successor["regulatory_due_at"], "2026-10-15T00:00:00.000Z", "regulatory_due_at"
    )


def test_the_adjacent_pair_of_windows_is_late_on_the_regulatory_basis_only(api):
    """Standing exactly on `due_at` the incumbent is timely, yet already reportable.

    Both windows are live, so the outstanding count reads 2.  The clock sits
    precisely on the incumbent's contractual deadline and lateness is strict, so
    nothing is late on that basis and the contractual score is untouched — while the
    incumbent's fixed 30-day regulatory deadline passed a fortnight ago, costing 15
    points on the basis the regulator reads.

    PRD: "Each score starts from a perfect 100, subtracts 15 points for every late
    request on that basis, subtracts 25 points for every declared breach, and is
    floored at 0 before rounding, so the score never goes negative however many
    breaches accumulate; the result is then rounded half up to two decimal places
    and can never exceed 100.00."

    Design: Difficulty/resource_temporal_overlap/production_window_is_half_open_so_adjacency_is_accepted
    """
    scenario = _administrator_with_one_live_production_window(api)
    fx.advance_clock(api, "2026-09-15T00:00:00Z")
    validate_success(
        api.create_vendor_request(_second_window_payload(scenario), scenario.sponsor_headers), 201
    )

    admin = fx.read_administrator(api, scenario.admin_id)
    assert admin["outstanding_request_count"] == 2
    assert admin["late_request_count"] == 0
    assert admin["regulator_reportable_late_count"] == 1
    assert_score(admin["cooperation_score"], 100.00, "cooperation_score")
    assert_score(
        admin["regulatory_basis_cooperation_score"], 85.00, "regulatory_basis_cooperation_score"
    )
    assert admin["cooperation_status"] == CooperationStatus.COOPERATIVE


OUTPATIENT_SLICE = {"sub_classification": SubClassification.ALL_OTHER_OUTPATIENT}


def _plan_year_with_a_first_half_measurement_period(api):
    """One OUTPATIENT / IN_NETWORK / ALL_OTHER_OUTPATIENT row covering 2026-01-01..2026-06-30."""
    scenario = fx.registered_plan(api)
    incumbent = fx.create_classification(api, scenario.plan_year_id, **OUTPATIENT_SLICE)
    scenario.incumbent_id = incumbent["id"]
    return scenario


def test_a_measurement_period_starting_the_next_day_is_refused_and_the_day_after_accepted(api):
    """The closed interval plus its one-day buffer rejects adjacency outright.

    A period beginning 2026-07-01 merely touches the incumbent that ended
    2026-06-30 and is refused; beginning one day later, on 2026-07-02, it clears the
    buffer and is accepted.  This is the exact opposite of the production-window
    convention, where adjacency is legitimate.

    PRD: "Two periods that merely touch are refused, and two periods exactly one day
    apart are also refused; a two-day gap is accepted."

    Design: Difficulty/resource_temporal_overlap/measurement_period_is_closed_with_a_one_day_buffer_so_adjacency_is_rejected
    """
    scenario = _plan_year_with_a_first_half_measurement_period(api)

    assert_error(
        api.create_classification(
            scenario.plan_year_id,
            f.classification_payload(
                measurement_period_start="2026-07-01",
                measurement_period_end="2026-12-31",
                **OUTPATIENT_SLICE,
            ),
            scenario.sponsor_headers,
        ),
        ApiErrorId.MEASUREMENT_PERIOD_OVERLAP,
    )

    accepted = validate_success(
        api.create_classification(
            scenario.plan_year_id,
            f.classification_payload(
                measurement_period_start="2026-07-02",
                measurement_period_end="2026-12-31",
                **OUTPATIENT_SLICE,
            ),
            scenario.sponsor_headers,
        ),
        201,
    )
    assert accepted["measurement_period_start"] == "2026-07-02"


def test_the_period_rule_is_scoped_to_the_tier_and_catches_a_single_day_inside(api):
    """The identical period on another tier coexists; a one-day period inside collides.

    Re-using 2026-01-01..2026-06-30 on OUT_OF_NETWORK is accepted because the rule
    never compares rows across tiers, leaving three rows on the plan year.  A
    one-day period sitting on the incumbent's own end date, back on IN_NETWORK, is
    refused — the interval is closed, so its endpoint is occupied.

    PRD: "Rows in a different category, a different tier, a different
    sub-classification or a different plan year never collide with each other."

    Design: Difficulty/resource_temporal_overlap/measurement_period_is_closed_with_a_one_day_buffer_so_adjacency_is_rejected
    """
    scenario = _plan_year_with_a_first_half_measurement_period(api)
    fx.create_classification(
        api,
        scenario.plan_year_id,
        measurement_period_start="2026-07-02",
        measurement_period_end="2026-12-31",
        **OUTPATIENT_SLICE,
    )

    validate_success(
        api.create_classification(
            scenario.plan_year_id,
            f.classification_payload(network_tier=NetworkTier.OUT_OF_NETWORK, **OUTPATIENT_SLICE),
            scenario.sponsor_headers,
        ),
        201,
    )
    assert_collection(
        api.list_plan_year_classifications(
            scenario.plan_year_id, None, scenario.sponsor_headers
        ),
        3,
        3,
        False,
    )

    assert_error(
        api.create_classification(
            scenario.plan_year_id,
            f.classification_payload(
                measurement_period_start="2026-06-30",
                measurement_period_end="2026-06-30",
                **OUTPATIENT_SLICE,
            ),
            scenario.sponsor_headers,
        ),
        ApiErrorId.MEASUREMENT_PERIOD_OVERLAP,
    )
