"""Inclusive comparisons and shrinking eligibility pools.

Three boundaries are pinned here: the vintage-year comparison against a plan's base
year, the eligibility pool of the server-side preferred-alternative selector as it
empties, and the on-track comparison of a monitoring reading against its target.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVENTORY_VINTAGE_TOO_LATE,
    ERR_NO_ELIGIBLE_ALTERNATIVE,
)
from test_helpers.test_users import CONSULTANT, STAFF


# ------------------------------------------------------------- vintage year
def test_a_vintage_year_equal_to_the_base_year_is_accepted(api):
    """A dataset collected in the base year describes exactly the right picture.

    PRD: "Every dataset also carries a `vintage_year` between 2000 and 2100 recording
    when the underlying data was collected, and it may not be newer than the picture it
    claims to describe: a `vintage_year` later than the plan's `base_year` is refused
    with `ERR_INVENTORY_VINTAGE_TOO_LATE`."

    Design: Difficulty/boundary_precision_check/inventory_vintage_year_equal_to_base_year_is_accepted
    """
    plan = fx.create_plan(api)
    assert plan["base_year"] == f.REF_BASE_YEAR

    dataset = validate_success(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                plan["id"],
                C.INVENTORY_DEMOGRAPHIC,
                record_count=4200,
                vintage_year=f.REF_BASE_YEAR,
            ),
            STAFF,
        ),
        201,
    )

    assert dataset["vintage_year"] == f.REF_BASE_YEAR
    assert dataset["status"] == C.INVENTORY_STATUS_DRAFT
    assert dataset["referencing_scenario_count"] == 0


def test_a_vintage_year_one_past_the_base_year_is_refused(api):
    """Data collected the year after the base year is newer than the picture.

    PRD: "creating an inventory requires its `vintage_year` not to be later than the
    plan's `base_year` (`ERR_INVENTORY_VINTAGE_TOO_LATE`)."

    Design: Difficulty/boundary_precision_check/inventory_vintage_year_equal_to_base_year_is_accepted
    """
    plan = fx.create_plan(api)

    response = api.create_inventory_dataset(
        f.tabular_inventory_payload(
            plan["id"],
            C.INVENTORY_EMPLOYMENT,
            record_count=2600,
            vintage_year=f.REF_BASE_YEAR + 1,
        ),
        STAFF,
    )

    validate_error(response, ERR_INVENTORY_VINTAGE_TOO_LATE)

    rows, meta = validate_paginated(api.list_plan_inventory_datasets(plan["id"], STAFF))
    assert meta["total_count"] == 0
    assert rows == []


def test_the_vintage_boundary_is_inclusive_on_the_upper_side(api):
    """Base year and earlier are both stored; only later is refused.

    PRD: "A new dataset enters `DRAFT` with `referencing_scenario_count` at zero, and
    the caller's `X-User-ID` is stamped into `authored_by_user_id`."

    Design: Difficulty/boundary_precision_check/inventory_vintage_year_equal_to_base_year_is_accepted
    """
    plan = fx.create_plan(api)

    at_base = validate_success(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                plan["id"],
                C.INVENTORY_DEMOGRAPHIC,
                record_count=4200,
                vintage_year=f.REF_BASE_YEAR,
            ),
            STAFF,
        ),
        201,
    )
    validate_error(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                plan["id"],
                C.INVENTORY_EMPLOYMENT,
                record_count=2600,
                vintage_year=f.REF_BASE_YEAR + 1,
            ),
            STAFF,
        ),
        ERR_INVENTORY_VINTAGE_TOO_LATE,
    )
    before_base = validate_success(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                plan["id"],
                C.INVENTORY_EMPLOYMENT,
                record_count=2600,
                vintage_year=f.REF_BASE_YEAR - 1,
            ),
            STAFF,
        ),
        201,
    )

    assert at_base["vintage_year"] == f.REF_BASE_YEAR
    assert before_base["vintage_year"] == f.REF_BASE_YEAR - 1

    rows, meta = validate_paginated(api.list_plan_inventory_datasets(plan["id"], STAFF))
    assert meta["total_count"] == 2
    assert sorted(row["vintage_year"] for row in rows) == [
        f.REF_BASE_YEAR - 1,
        f.REF_BASE_YEAR,
    ]

    plan_after = fx.read_plan(api, plan["id"])
    assert plan_after["compliance_posture"] == C.POSTURE_CAPACITY_HOLD


# ------------------------------------------- the preferred-alternative selector
SELECTOR_ALTERNATIVES = [
    {"label": "Transit-Focused Alternative", "traffic_vmt_index": 49,
     "ghg_index": 49, "habitat_index": 49, "water_index": 49},
    {"label": "Auto-Oriented Alternative", "traffic_vmt_index": 70,
     "ghg_index": 70, "habitat_index": 70, "water_index": 70},
]


def _circulated_review_with_two_alternatives(api):
    """A circulated document carrying a 49.00-net and a 59.50-net alternative."""
    plan = fx.create_plan(api)
    ctx = fx.circulated_review(
        api, plan["id"], C.DOC_EIR, alternatives=SELECTOR_ALTERNATIVES
    )
    ctx["plan_id"] = plan["id"]
    ctx["low"], ctx["high"] = ctx["alternatives"]
    return ctx


def _alternatives_by_id(api, review_id):
    rows, _meta = validate_paginated(api.list_review_alternatives(review_id, CONSULTANT))
    return {row["id"]: row for row in rows}


def test_the_selector_picks_the_lowest_net_impact_score_first(api):
    """With two evaluated candidates the 49.00-net document wins over the 59.50-net one.

    PRD: "Otherwise the candidates are ordered by `net_impact_score` ascending, because
    the lowest environmental impact wins; ties are broken by `raw_impact_score`
    ascending; and any remaining tie is broken by `created_at` ascending, the
    earliest-created alternative winning."

    Design: Difficulty/boundary_precision_check/preferred_alternative_selector_pool_shrinks_to_empty
    """
    ctx = _circulated_review_with_two_alternatives(api)
    assert ctx["review"]["status"] == C.REVIEW_STATUS_CIRCULATED
    assert ctx["low"]["net_impact_score"] == 49.00
    assert ctx["high"]["net_impact_score"] == 59.50

    winner = fx.select_preferred(api, ctx["review_id"])

    assert winner["id"] == ctx["low"]["id"]
    assert winner["status"] == C.ALTERNATIVE_STATUS_PREFERRED
    assert winner["net_impact_score"] == 49.00

    review = validate_success(api.get_environmental_review(ctx["review_id"], CONSULTANT))
    assert review["preferred_alternative_id"] == ctx["low"]["id"]

    rows = _alternatives_by_id(api, ctx["review_id"])
    assert rows[ctx["high"]["id"]]["status"] == C.ALTERNATIVE_STATUS_EVALUATED


def test_a_second_selection_takes_the_last_candidate_and_demotes_the_incumbent(api):
    """The pool shrinks to one, and the sitting preferred document is superseded.

    PRD: "The winner moves `EVALUATED → PREFERRED` with its `version` incremented, any
    incumbent alternative in `PREFERRED` moves `PREFERRED → SUPERSEDED` with its
    `version` incremented, and the review's `preferred_alternative_id` is pointed at the
    winner while the review's `version` is incremented by one."

    Design: Difficulty/boundary_precision_check/preferred_alternative_selector_pool_shrinks_to_empty
    """
    ctx = _circulated_review_with_two_alternatives(api)
    fx.select_preferred(api, ctx["review_id"])

    second = fx.select_preferred(api, ctx["review_id"])

    assert second["id"] == ctx["high"]["id"]
    assert second["status"] == C.ALTERNATIVE_STATUS_PREFERRED
    assert second["net_impact_score"] == 59.50

    rows = _alternatives_by_id(api, ctx["review_id"])
    assert rows[ctx["low"]["id"]]["status"] == C.ALTERNATIVE_STATUS_SUPERSEDED

    review = validate_success(api.get_environmental_review(ctx["review_id"], CONSULTANT))
    assert review["preferred_alternative_id"] == ctx["high"]["id"]
    assert review["alternative_count"] == 2


def test_an_empty_candidate_pool_is_refused_and_mutates_nothing(api):
    """A third selection finds no EVALUATED row left and leaves the record untouched.

    PRD: "If the candidate pool is empty the request is refused with
    `ERR_NO_ELIGIBLE_ALTERNATIVE` and nothing whatsoever is mutated."

    Design: Difficulty/boundary_precision_check/preferred_alternative_selector_pool_shrinks_to_empty
    """
    ctx = _circulated_review_with_two_alternatives(api)
    fx.select_preferred(api, ctx["review_id"])
    fx.select_preferred(api, ctx["review_id"])
    before = validate_success(
        api.get_environmental_review(ctx["review_id"], CONSULTANT)
    )

    validate_error(
        api.select_preferred_alternative(ctx["review_id"], {}, CONSULTANT),
        ERR_NO_ELIGIBLE_ALTERNATIVE,
    )

    after = validate_success(api.get_environmental_review(ctx["review_id"], CONSULTANT))
    assert after["preferred_alternative_id"] == ctx["high"]["id"]
    a.assert_unchanged(before, after, ["version", "status", "preferred_alternative_id"])

    rows = _alternatives_by_id(api, ctx["review_id"])
    assert rows[ctx["high"]["id"]]["status"] == C.ALTERNATIVE_STATUS_PREFERRED
    assert rows[ctx["low"]["id"]]["status"] == C.ALTERNATIVE_STATUS_SUPERSEDED


# ------------------------------------------------- monitoring indicator readings
def _pending_decrease_action(api):
    """A plan, one drafted element and one MONITORING action targeting 12.5 downward."""
    plan = fx.create_plan(api)
    element = fx.create_element(api, plan["id"], C.ELEMENT_TRANSPORTATION)
    action = fx.create_action(
        api,
        plan["id"],
        element["id"],
        action_type=C.ACTION_MONITORING,
        title="VMT per capita monitoring",
        indicator_name="vmt_per_capita",
        indicator_direction=C.DIRECTION_DECREASE,
        baseline_value=18.0,
        target_value=12.5,
    )
    return plan, action


def test_a_new_action_starts_off_track_with_no_reading(api):
    """Before any reading the indicator is unmeasured, not healthy.

    PRD: "A new action enters `PENDING` with `reading_count` at zero, `on_track` false,
    and `latest_reading_value`, `latest_reading_at` and `due_at` all null."

    Design: Difficulty/boundary_precision_check/indicator_reading_exactly_equal_to_target_is_on_track
    """
    plan, action = _pending_decrease_action(api)

    assert action["status"] == C.ACTION_STATUS_PENDING
    assert action["indicator_direction"] == C.DIRECTION_DECREASE
    assert action["target_value"] == 12.5
    assert action["on_track"] is False
    assert action["reading_count"] == 0
    assert action["latest_reading_value"] is None
    assert action["latest_reading_at"] is None
    assert action["due_at"] is None

    assert fx.read_plan(api, plan["id"])["monitoring_on_track_count"] == 0


def test_a_reading_exactly_equal_to_the_target_counts_as_on_track(api):
    """12.5 against a target of 12.5 satisfies the DECREASE comparison inclusively.

    PRD: "The action's `on_track` flag is then recomputed inclusively against the
    target: for an `INCREASE` indicator the action is on track when
    `latest_reading_value` is greater than or equal to `target_value`; for a `DECREASE`
    indicator it is on track when `latest_reading_value` is less than or equal to
    `target_value`. A reading exactly equal to the target therefore counts as on track."

    Design: Difficulty/boundary_precision_check/indicator_reading_exactly_equal_to_target_is_on_track
    """
    plan, action = _pending_decrease_action(api)

    updated = fx.record_reading(api, action["id"], 12.5)

    assert updated["latest_reading_value"] == 12.5
    assert updated["on_track"] is True
    assert updated["reading_count"] == 1
    a.assert_instant_equals(
        updated["latest_reading_at"], C.CLOCK_STARTUP, "latest_reading_at"
    )
    a.assert_three_digit_instant(updated["latest_reading_at"], "latest_reading_at")

    assert fx.read_plan(api, plan["id"])["monitoring_on_track_count"] == 1


def test_the_newest_reading_one_tenth_above_target_flips_the_flag_back(api):
    """12.6 replaces 12.5 outright, so the action leaves the on-track count.

    PRD: "The newest reading always wins outright: `latest_reading_value` is replaced
    with the supplied value, `latest_reading_at` is stamped with the logical clock
    instant, `reading_count` is incremented by one, and earlier readings are neither
    averaged nor retained as rows."

    Design: Difficulty/boundary_precision_check/indicator_reading_exactly_equal_to_target_is_on_track
    """
    plan, action = _pending_decrease_action(api)
    fx.record_reading(api, action["id"], 12.5)

    updated = fx.record_reading(api, action["id"], 12.6)

    assert updated["latest_reading_value"] == 12.6
    assert updated["on_track"] is False
    assert updated["reading_count"] == 2
    # An average of 12.5 and 12.6 would still sit above the target, but no averaging
    # takes place at all: the stored value is the newest one.
    assert updated["latest_reading_value"] != 12.55
    # Recording a reading is not a state transition.
    assert updated["status"] == C.ACTION_STATUS_PENDING

    assert fx.read_plan(api, plan["id"])["monitoring_on_track_count"] == 0
