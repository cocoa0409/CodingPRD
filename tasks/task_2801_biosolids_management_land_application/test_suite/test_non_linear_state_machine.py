"""Cyclic and parallel-dimension lifecycles: the bounded agreement negotiation
cycle, and the batch quality dimension re-opening twice before it locks.
"""

from test_helpers import constants as C
from test_helpers.api_errors import (
    ERR_AGREEMENT_ROUND_LIMIT,
    ERR_RETEST_LIMIT_REACHED,
)
from test_helpers.assertions import assert_dry_tons
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    OFFICER_HEADERS,
    make_farmer_headers,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

FARMER = "farmer-jones"


class TestAgreementNegotiationCycle:
    @staticmethod
    def _drafted_agreement(build, facility):
        site = build.permitted_site(facility["id"])
        return build.agreement(site["id"], site["version"])

    @staticmethod
    def _propose(api, agreement_id, **overrides):
        return validate_success(
            api.propose_agreement(agreement_id, AGRONOMIST_HEADERS, overrides or {})
        )

    @staticmethod
    def _counter(api, agreement_id, **overrides):
        return validate_success(
            api.counter_agreement(agreement_id, overrides, make_farmer_headers(FARMER))
        )

    def test_three_laps_of_the_cycle_count_only_the_farmer_counters(
        self, api, build, facility
    ):
        """PRD §3.6: "It is bounded: `round_index` must be strictly less than 3, so the propose-and-counter cycle can turn at most three times and a fourth counter attempt is `ERR_AGREEMENT_ROUND_LIMIT`."

        The row re-enters PROPOSED four times and COUNTERED three times while the
        offered rate changes on every lap. Only the farmer's counter advances
        round_index, so after three counters and four proposals the counter reads 3,
        the row sits at PROPOSED with last_proposed_by_role Agronomist, the standing
        offer is the agronomist's 16.0, and the version has been stamped eight times.

        Design: Difficulty/non_linear_state_machine/agreement_propose_counter_cycle_bounded_at_three_rounds
        """
        agreement = self._drafted_agreement(build, facility)
        agreement_id = agreement["id"]
        assert agreement["round_index"] == 0
        assert agreement["last_proposed_by_role"] == "NONE"
        assert agreement["version"] == 1

        first = self._propose(api, agreement_id, max_dry_tons_per_acre=20.0, notice_days=3)
        assert first["status"] == C.AGREEMENT_PROPOSED
        assert first["round_index"] == 0

        lap_one = self._counter(api, agreement_id, max_dry_tons_per_acre=18.0)
        assert lap_one["status"] == C.AGREEMENT_COUNTERED
        assert lap_one["round_index"] == 1
        assert lap_one["last_proposed_by_role"] == "Farmer"

        second = self._propose(api, agreement_id, max_dry_tons_per_acre=19.0)
        assert second["status"] == C.AGREEMENT_PROPOSED
        assert second["round_index"] == 1

        self._counter(api, agreement_id, max_dry_tons_per_acre=16.0)
        self._propose(api, agreement_id, max_dry_tons_per_acre=17.0)
        self._counter(api, agreement_id, max_dry_tons_per_acre=15.0)
        final = self._propose(api, agreement_id, max_dry_tons_per_acre=16.0)

        assert final["status"] == C.AGREEMENT_PROPOSED
        assert final["round_index"] == 3
        assert final["last_proposed_by_role"] == "Agronomist"
        assert final["max_dry_tons_per_acre"] == 16.0
        assert final["version"] == 8

    def test_fourth_counter_is_refused_and_leaves_the_row_untouched(
        self, api, build, facility
    ):
        """PRD §2.7: "**Priority 22 — negotiation bound.** `round_index` is strictly less than 3 before a counter-offer is accepted, otherwise `ERR_AGREEMENT_ROUND_LIMIT` (409)."

        With round_index already at 3 the bound is exhausted: a fourth counter is
        refused with ERR_AGREEMENT_ROUND_LIMIT and the agreement remains PROPOSED at
        round_index 3, version 8 and the agronomist's standing 16.0.

        Design: Difficulty/non_linear_state_machine/agreement_propose_counter_cycle_bounded_at_three_rounds
        """
        agreement = self._drafted_agreement(build, facility)
        agreement_id = agreement["id"]
        self._propose(api, agreement_id, max_dry_tons_per_acre=20.0, notice_days=3)
        self._counter(api, agreement_id, max_dry_tons_per_acre=18.0)
        self._propose(api, agreement_id, max_dry_tons_per_acre=19.0)
        self._counter(api, agreement_id, max_dry_tons_per_acre=16.0)
        self._propose(api, agreement_id, max_dry_tons_per_acre=17.0)
        self._counter(api, agreement_id, max_dry_tons_per_acre=15.0)
        self._propose(api, agreement_id, max_dry_tons_per_acre=16.0)

        refused = api.counter_agreement(
            agreement_id, {"max_dry_tons_per_acre": 14.0}, make_farmer_headers(FARMER)
        )
        validate_error(refused, ERR_AGREEMENT_ROUND_LIMIT)

        after = build.read_agreement(agreement_id)
        assert after["status"] == C.AGREEMENT_PROPOSED
        assert after["round_index"] == 3
        assert after["last_proposed_by_role"] == "Agronomist"
        assert after["max_dry_tons_per_acre"] == 16.0
        assert after["version"] == 8


class TestBatchQualityDimensionBoundedLoop:
    @staticmethod
    def _three_failing_rounds(build, batch_id):
        build.lab_result(
            batch_id,
            concentration_mg_kg=90.0,
            sampling_event_index=0,
            analyzed_at="2026-08-02T00:00:00Z",
        )
        build.retest(batch_id)
        build.lab_result(
            batch_id,
            concentration_mg_kg=95.0,
            sampling_event_index=1,
            analyzed_at="2026-08-05T00:00:00Z",
        )
        build.retest(batch_id)
        build.lab_result(
            batch_id,
            concentration_mg_kg=99.0,
            sampling_event_index=2,
            analyzed_at="2026-08-08T00:00:00Z",
        )

    def test_third_retest_request_is_refused_while_the_process_dimension_holds(
        self, build, facility, cadmium_limit
    ):
        """PRD §2.7: "**Priority 23 — resampling bound.** `retest_round` is strictly less than 2 before a retest is accepted, otherwise `ERR_RETEST_LIMIT_REACHED` (409)."

        Two ceiling failures each re-open the quality dimension, and the third
        request is refused with ERR_RETEST_LIMIT_REACHED because retest_round has
        reached 2. Through all six quality transitions the process dimension never
        moves off DEWATERED, and the batch's produced and unallocated tonnage is
        untouched by the quality loop.

        Design: Difficulty/non_linear_state_machine/batch_quality_dimension_reopens_twice_then_locks
        """
        batch = build.dewatered_batch(facility["id"])
        self._three_failing_rounds(build, batch["id"])

        refused = build.api.request_retest(batch["id"], OFFICER_HEADERS)
        validate_error(refused, ERR_RETEST_LIMIT_REACHED)

        after = build.read_batch(batch["id"])
        assert after["retest_round"] == 2
        assert after["quality_status"] == C.QUALITY_REJECTED
        assert after["rejection_reason"] == "CEILING_EXCEEDED"
        assert after["ceiling_exceedance_flag"] is True
        assert after["process_status"] == C.PROCESS_DEWATERED
        assert_dry_tons(after["dry_tons_produced"], 160.000)
        assert_dry_tons(after["unallocated_dry_tons"], 160.000)

    def test_every_round_leaves_its_own_exceeding_result_and_freezes_the_facility(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §3.4: "Prior-round results are retained for the audit trail but are excluded from every subsequent check."

        Each of the three sampling rounds keeps its own result row, all three marked
        as exceeding the ceiling, and the facility is left FROZEN with exactly one open
        ceiling exceedance once the loop locks.

        Design: Difficulty/non_linear_state_machine/batch_quality_dimension_reopens_twice_then_locks
        """
        batch = build.dewatered_batch(facility["id"])
        self._three_failing_rounds(build, batch["id"])

        rows, meta = validate_paginated(
            api.list_lab_results(OFFICER_HEADERS, {"batch_id": batch["id"]})
        )
        assert meta["total_count"] == 3
        assert sorted(row["sampling_event_index"] for row in rows) == [0, 1, 2]
        assert all(row["exceeds_ceiling"] is True for row in rows)

        current_facility = build.read_facility(facility["id"])
        assert current_facility["posture"] == C.POSTURE_FROZEN
        assert current_facility["open_ceiling_exceedance_count"] == 1
