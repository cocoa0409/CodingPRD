"""Drawing the unit sample: the tier ladder, eligibility and ranking.

The tier value comes from the property's declared `total_unit_count` while the
sample size comes from the units actually on record, so the two numbers are
deliberately allowed to disagree.
"""

from test_helpers import (
    ApiErrorId,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    assert_total_count,
    constants as K,
    factories as F,
    fixtures as X,
)

ASH_UNITS = [
    {"unit_number": "101", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
    {"unit_number": "102", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
    {"unit_number": "103", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
]
MIXED_OCCUPANCY_UNITS = [
    {"unit_number": "101", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
    {"unit_number": "102", "bedroom_count": 2, "occupancy_status": "VACANT"},
    {"unit_number": "103", "bedroom_count": 2, "occupancy_status": "DOWN"},
]
ONLY_DOWN_UNITS = [
    {"unit_number": "101", "bedroom_count": 1, "occupancy_status": "DOWN"}
]
ALDER_UNITS = [
    {"unit_number": "101", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
    {"unit_number": "102", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
]
BIRCH_UNITS = [
    {"unit_number": "201", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
    {"unit_number": "202", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
]
MAPLE_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
FROZEN_CLOCK = "2026-08-04T09:00:00.001Z"
FROZEN_DRAWN_AT = "2026-08-04T10:00:00.000Z"
SWEEP_LT_OBSERVED_AT = "2026-08-03T09:00:00.000Z"


def _two_tier_properties(api):
    """Two properties straddling the 30 / 31 declared-unit tier boundary."""
    bundle = X.adopted_standard(api, ("LT_GAS",))
    alder = X.property_with_units(api, K.ALDER_COURT, ALDER_UNITS)
    birch = X.property_with_units(api, K.BIRCH_COURT, BIRCH_UNITS)
    bundle["alder"] = alder
    bundle["birch"] = birch
    bundle["inspection_a_id"] = X.scheduled_inspection(
        api, alder["property_id"], bundle["standard_id"]
    )["id"]
    bundle["inspection_b_id"] = X.scheduled_inspection(
        api, birch["property_id"], bundle["standard_id"]
    )["id"]
    return bundle


def _frozen_by_an_overdue_finding(api):
    """A property frozen by an overdue life-threatening sweep finding."""
    bundle = X.sweep_lifecycle(
        api,
        "LT_GAS",
        K.MAPLE_COURT,
        MAPLE_UNIT,
        definition_codes=("LT_GAS",),
        observed_at=SWEEP_LT_OBSERVED_AT,
    )
    bundle["inspection_id"] = X.scheduled_inspection(
        api, bundle["property_id"], bundle["standard_id"]
    )["id"]
    X.advance_clock(api, FROZEN_CLOCK)
    return bundle


class TestSampleRanking:
    """Ranking is by inspection history first, registration order second."""

    def test_the_draw_ranks_the_unit_with_history_first(self, api):
        """Unit 103's single past deficiency outranks the earlier-created 101.

        PRD: "Candidates are ordered by `prior_deficiency_count` descending -
        the units with the worst inspection history first - and ties are broken
        by `created_at` ascending, the earlier-registered unit first."

        Design: Corner/state_machines/draw_sample_ranks_slots_by_prior_deficiency_count_then_created_at
        """
        bundle = X.adopted_standard(api, ("LT_GAS", "SEV_WINDOW"))
        bundle.update(X.property_with_units(api, K.ASH_TERRACE, ASH_UNITS))
        X.inject_history(
            api,
            bundle["property_id"],
            bundle["standard_id"],
            K.HISTORY_FINALIZED_RECENT,
            [bundle["definition_ids"]["SEV_WINDOW"]],
            bundle["unit_ids"]["103"],
        )
        assert_integer(
            X.read_unit(api, bundle["unit_ids"]["103"])["prior_deficiency_count"],
            1,
            "prior_deficiency_count",
        )
        assert_integer(
            X.read_unit(api, bundle["unit_ids"]["101"])["prior_deficiency_count"],
            0,
            "prior_deficiency_count",
        )
        inspection_id = X.scheduled_inspection(
            api, bundle["property_id"], bundle["standard_id"]
        )["id"]

        response = api.draw_sample(
            inspection_id, F.draw_sample_payload(drawn_at=K.DRAWN_AT), X.INSPECTOR
        )

        drawn = assert_ok(response)
        assert_fields(drawn, status="SAMPLED", sample_tier_value=2, sample_size=2)
        assert_instant(drawn["drawn_at"], K.DRAWN_AT, "drawn_at")
        assert_total_count(
            api.list_sample_selections(X.INSPECTOR, inspection_id=inspection_id), 2
        )
        slots = X.selections_by_unit(api, inspection_id)
        assert_fields(
            slots[bundle["unit_ids"]["103"]],
            selection_rank=1,
            selection_basis="SAMPLED",
            selection_status="ACTIVE",
            access_status="NOT_NOTIFIED",
        )
        assert_fields(slots[bundle["unit_ids"]["101"]], selection_rank=2)
        assert_total_count(
            api.list_sample_selections(
                X.INSPECTOR,
                inspection_id=inspection_id,
                unit_id=bundle["unit_ids"]["102"],
            ),
            0,
        )

    def test_the_eligibility_filter_excludes_the_down_unit(self, api):
        """The declared tier stays 4 while the size clamps to the 2 candidates.

        PRD: "A unit is a candidate when its `property_id` equals the
        inspection's `property_id`, its `occupancy_status` is `OCCUPIED` or
        `VACANT` - units that are `DOWN` are excluded outright - and no
        `SampleSelection` of this same inspection already holds that unit."

        Design: Corner/calculations/sampling_eligibility_excludes_down_units_and_clamps_the_tier
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(
            X.property_with_units(api, K.MAPLE_COURT, MIXED_OCCUPANCY_UNITS)
        )
        inspection_id = X.scheduled_inspection(
            api, bundle["property_id"], bundle["standard_id"]
        )["id"]

        response = api.draw_sample(
            inspection_id, F.draw_sample_payload(drawn_at=K.DRAWN_AT), X.INSPECTOR
        )

        drawn = assert_ok(response)
        assert_fields(drawn, sample_tier_value=4, sample_size=2)
        assert_total_count(
            api.list_sample_selections(X.INSPECTOR, inspection_id=inspection_id), 2
        )
        assert_total_count(
            api.list_sample_selections(
                X.INSPECTOR,
                inspection_id=inspection_id,
                unit_id=bundle["unit_ids"]["103"],
            ),
            0,
        )
        slots = X.selections_by_unit(api, inspection_id)
        assert_fields(slots[bundle["unit_ids"]["101"]], selection_rank=1)
        assert_fields(slots[bundle["unit_ids"]["102"]], selection_rank=2)

    def test_a_property_of_only_down_units_has_no_eligible_candidate(self, api):
        """An empty candidate pool fails the draw instead of drawing zero slots.

        PRD: "If the pool is empty, the draw fails with
        `ERR_NO_ELIGIBLE_UNITS`."

        Design: Corner/errors/draw_sample_on_a_property_of_only_down_units_is_rejected
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(
            X.property_with_units(
                api, K.CEDAR_WALK, ONLY_DOWN_UNITS, total_unit_count=2
            )
        )
        inspection_id = X.scheduled_inspection(
            api, bundle["property_id"], bundle["standard_id"]
        )["id"]

        response = api.draw_sample(
            inspection_id, F.draw_sample_payload(drawn_at=K.DRAWN_AT), X.INSPECTOR
        )

        assert_error(response, ApiErrorId.NO_ELIGIBLE_UNITS)
        unchanged = X.read_inspection(api, inspection_id)
        assert_fields(
            unchanged, status="SCHEDULED", sample_size=0, sample_tier_value=0
        )
        assert_null(unchanged, "drawn_at")
        assert_total_count(
            api.list_sample_selections(X.INSPECTOR, inspection_id=inspection_id), 0
        )


class TestTierLadderBoundary:
    """Thirty declared units and thirty-one land on different tiers."""

    def test_thirty_declared_units_sit_on_the_second_tier(self, api):
        """max(5, ceil(0.20 * 30)) is 6, and the size still clamps to 2.

        PRD: "For a declared count of 5 through 30, it is the larger of 5 and
        the declared count multiplied by 0.20 then rounded up to the next whole
        number."

        Design: Difficulty/boundary_precision_check/sample_tier_boundary_thirty_versus_thirty_one_declared_units
        """
        bundle = _two_tier_properties(api)

        response = api.draw_sample(
            bundle["inspection_a_id"],
            F.draw_sample_payload(drawn_at=K.DRAWN_AT),
            X.INSPECTOR,
        )

        drawn = assert_ok(response)
        assert_fields(drawn, sample_tier_value=6, sample_size=2, status="SAMPLED")
        assert_total_count(
            api.list_sample_selections(
                X.INSPECTOR, inspection_id=bundle["inspection_a_id"]
            ),
            2,
        )

    def test_thirty_one_declared_units_cross_into_the_third_tier(self, api):
        """max(8, ceil(0.15 * 31)) is 8, so only the tier value moves.

        PRD: "For a declared count of 31 through 100, it is the larger of 8 and
        the declared count multiplied by 0.15 then rounded up to the next whole
        number."

        Design: Difficulty/boundary_precision_check/sample_tier_boundary_thirty_versus_thirty_one_declared_units
        """
        bundle = _two_tier_properties(api)
        first = assert_ok(
            api.draw_sample(
                bundle["inspection_a_id"],
                F.draw_sample_payload(drawn_at=K.DRAWN_AT),
                X.INSPECTOR,
            )
        )
        assert_integer(first["sample_tier_value"], 6, "sample_tier_value")

        response = api.draw_sample(
            bundle["inspection_b_id"],
            F.draw_sample_payload(drawn_at=K.DRAWN_AT),
            X.INSPECTOR,
        )

        drawn = assert_ok(response)
        assert_fields(drawn, sample_tier_value=8, sample_size=2, status="SAMPLED")
        slots = X.list_selections(api, bundle["inspection_b_id"])
        assert len(slots) == 2
        for slot in slots:
            assert_fields(
                slot, selection_basis="SAMPLED", access_status="NOT_NOTIFIED"
            )


class TestFrozenPropertyBlocksTheDraw:
    """The blocking state lives two aggregates away from the inspection."""

    def test_the_clock_advance_freezes_the_property(self, api):
        """One millisecond past the deadline tips the finding overdue.

        PRD: "Every `Deficiency` still in `OPEN` status whose
        `correction_due_at` lies strictly before the new clock value transitions
        to `OVERDUE`."

        Design: Difficulty/cross_entity_state_dependency/draw_sample_rejected_when_sweep_sourced_overdue_deficiency_froze_the_property
        """
        bundle = _frozen_by_an_overdue_finding(api)

        response = api.draw_sample(
            bundle["inspection_id"],
            F.draw_sample_payload(drawn_at=FROZEN_DRAWN_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.PROPERTY_FROZEN)
        assert_fields(
            X.read_deficiency(api, bundle["deficiency_id"]), status="OVERDUE"
        )
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(owning_property, readiness_posture="FROZEN")
        assert_integer(
            owning_property["overdue_life_threatening_count"],
            1,
            "overdue_life_threatening_count",
        )

    def test_the_refused_draw_leaves_the_inspection_untouched(self, api):
        """Nothing local to the inspection explains or records the refusal.

        PRD: "Three preconditions hold: the inspection's `status` is
        `SCHEDULED`; the property's `readiness_posture` is not `FROZEN`, else
        `ERR_PROPERTY_FROZEN`; and the eligibility filter below yields at least
        one candidate unit, else `ERR_NO_ELIGIBLE_UNITS` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/draw_sample_rejected_when_sweep_sourced_overdue_deficiency_froze_the_property
        """
        bundle = _frozen_by_an_overdue_finding(api)

        response = api.draw_sample(
            bundle["inspection_id"],
            F.draw_sample_payload(drawn_at=FROZEN_DRAWN_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.PROPERTY_FROZEN)
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(
            unchanged, status="SCHEDULED", sample_tier_value=0, sample_size=0
        )
        assert_null(unchanged, "drawn_at")
        assert_total_count(
            api.list_sample_selections(
                X.INSPECTOR, inspection_id=bundle["inspection_id"]
            ),
            0,
        )
