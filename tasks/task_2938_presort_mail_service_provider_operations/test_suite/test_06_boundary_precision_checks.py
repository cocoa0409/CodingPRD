"""Thresholds tested on the exact instant either side of the line.

Three gates in this contract are inclusive and one is a zero-count rejection. The
tests below sit a single day, a single piece and a single container away from
each boundary, because an implementation using the wrong comparison operator
still passes any test placed comfortably inside the accepted range.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_pricing,
    assert_container_state,
    assert_field_values,
    assert_job_state,
    assert_member_allocation,
    assert_pct_2dp,
)
from test_helpers.test_users import PRESORT_OPERATOR

# A thousand submitted pieces, 990 matched and 40 suppressed, so the quality and
# the net volume are identical on both jobs and only the age differs.
HYGIENE_SUBMITTED = 1000
HYGIENE_CASS_MATCHED = 990
HYGIENE_NCOA_UPDATED = 30
HYGIENE_UNDELIVERABLE = 40
HYGIENE_NET = 960
HYGIENE_QUALITY_PCT = 99.00

# A lone 1200-piece MARKETING_MAIL pool at the 300 bp SCF: BASIC, so 32000 mills
# less the 800 bp tier factor and the 300 bp entry factor, floored once.
SOLO_BASIC_RATE_MILLS = 28556
SOLO_BASIC_POSTAGE_CENTS = 34267


def _hygiene_run(api, mail_job_id, move_update_age_days):
    """Record one hygiene pass whose only variable is the move-update age."""
    return validate_success(
        api.create_hygiene_run(
            mail_job_id,
            f.hygiene_run_payload(
                submitted_piece_count=HYGIENE_SUBMITTED,
                cass_matched_count=HYGIENE_CASS_MATCHED,
                ncoa_move_updated_count=HYGIENE_NCOA_UPDATED,
                undeliverable_removed_count=HYGIENE_UNDELIVERABLE,
                move_update_age_days=move_update_age_days,
            ),
            PRESORT_OPERATOR,
        ),
        expected_status=201,
    )


class TestMoveUpdateAgeBoundary:
    """Ninety-five days against ninety-six, on two identical jobs."""

    @pytest.mark.parametrize(
        "move_update_age_days, expected_compliant",
        [(95, True), (96, False)],
        ids=["at-the-maximum", "one-day-past"],
    )
    def test_the_ninety_five_day_maximum_is_inclusive(
        self, api, move_update_age_days, expected_compliant
    ):
        """The comparison is at most, not less than.

        "Its `move_update_compliant` is true when `move_update_age_days` is less than
        or equal to the maximum permitted age of 95 days, so a data set exactly 95 days
        old is compliant while one 96 days old is not."

        Design: Difficulty/boundary_precision_check/move_update_age_exactly_ninety_five_days_is_compliant
        """
        world = fx.build_two_untouched_jobs_world(api)

        run = _hygiene_run(api, world.job_p_id, move_update_age_days)
        assert_field_values(
            run,
            {
                "move_update_age_days": move_update_age_days,
                "move_update_compliant": expected_compliant,
            },
        )

    def test_both_runs_are_the_first_pass_on_their_job(self, api):
        """The ordinal counts the runs before this one, not including it.

        "Its `run_index` is a zero-based ordinal equal to the job's
        `hygiene_run_count` as it stood immediately *before* this run was counted, so a
        job's very first pass carries `run_index` 0; the job's `hygiene_run_count` is
        then incremented by one."

        Design: Difficulty/boundary_precision_check/move_update_age_exactly_ninety_five_days_is_compliant
        """
        world = fx.build_two_untouched_jobs_world(api)

        run_p = _hygiene_run(api, world.job_p_id, 95)
        run_q = _hygiene_run(api, world.job_q_id, 96)
        assert run_p["run_index"] == 0
        assert run_q["run_index"] == 0

    def test_the_net_volume_subtracts_only_the_undeliverable_pieces(self, api):
        """Move-updated pieces are corrected, not suppressed.

        "Its `net_piece_count` is the `submitted_piece_count` less the
        `undeliverable_removed_count`. Its `address_quality_pct` is the
        `cass_matched_count` multiplied by one hundred and divided by the
        `submitted_piece_count`, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/move_update_age_exactly_ninety_five_days_is_compliant
        """
        world = fx.build_two_untouched_jobs_world(api)

        for job_id, age in ((world.job_p_id, 95), (world.job_q_id, 96)):
            run = _hygiene_run(api, job_id, age)
            # 1000 - 40 = 960; subtracting the 30 move-updated pieces as well would
            # give 930.
            assert run["net_piece_count"] == HYGIENE_NET
            assert_pct_2dp(run, "address_quality_pct", HYGIENE_QUALITY_PCT)

    def test_the_newest_run_is_mirrored_onto_each_job(self, api):
        """The verdict is carried up to the job, either way.

        "The job's `accepted_piece_count` is set to that run's `net_piece_count`, its
        `address_quality_pct` to that run's `address_quality_pct`, and its
        `move_update_compliant` to that run's `move_update_compliant`."

        Design: Difficulty/boundary_precision_check/move_update_age_exactly_ninety_five_days_is_compliant
        """
        world = fx.build_two_untouched_jobs_world(api)
        _hygiene_run(api, world.job_p_id, 95)
        _hygiene_run(api, world.job_q_id, 96)

        job_p = validate_success(api.get_mail_job(world.job_p_id, PRESORT_OPERATOR))
        assert_job_state(job_p, "HYGIENE_CLEARED", accepted_piece_count=HYGIENE_NET)
        assert_field_values(
            job_p, {"hygiene_run_count": 1, "move_update_compliant": True}
        )
        assert_pct_2dp(job_p, "address_quality_pct", HYGIENE_QUALITY_PCT)

        job_q = validate_success(api.get_mail_job(world.job_q_id, PRESORT_OPERATOR))
        assert_job_state(job_q, "HYGIENE_CLEARED", accepted_piece_count=HYGIENE_NET)
        assert_field_values(
            job_q, {"hygiene_run_count": 1, "move_update_compliant": False}
        )

    def test_the_non_compliant_run_is_still_accepted_as_a_run(self, api):
        """The staleness gate lives at pooling, not at the hygiene pass.

        "Recording a pass on a job in `RECEIVED` drives it
        `RECEIVED → HYGIENE_CLEARED`". The compliance flag is only consulted later: "23.
        **Move update currency** — the job's `move_update_compliant` is true. Violation:
        `ERR_MOVE_UPDATE_STALE` (422). Applies to
        `POST /commingle-batches/{id}/members`."

        Design: Difficulty/boundary_precision_check/move_update_age_exactly_ninety_five_days_is_compliant
        """
        world = fx.build_two_untouched_jobs_world(api)

        # A 201 on a run whose data is 96 days old is the point: the run is a record,
        # not a permission.
        run_q = _hygiene_run(api, world.job_q_id, 96)
        assert run_q["move_update_compliant"] is False

        runs, meta = validate_paginated(
            api.list_hygiene_runs(world.job_q_id, PRESORT_OPERATOR)
        )
        assert meta["total_count"] == 1 and runs[0]["id"] == run_q["id"]


class TestContainerMinimumPieceBoundary:
    """One piece either side of the tray and pallet minima."""

    @pytest.mark.parametrize(
        "container_type, sort_level, piece_count, expected_qualifies, sequence_index",
        [
            ("TRAY", "FIVE_DIGIT", 150, True, 0),
            ("TRAY", "FIVE_DIGIT", 149, False, 1),
            ("PALLET", "THREE_DIGIT", 249, False, 2),
            ("PALLET", "THREE_DIGIT", 250, True, 3),
        ],
        ids=[
            "deep-tray-at-150",
            "deep-tray-at-149",
            "pallet-at-249",
            "pallet-at-250",
        ],
    )
    def test_each_minimum_is_inclusive_and_type_specific(
        self,
        api,
        container_type,
        sort_level,
        piece_count,
        expected_qualifies,
        sequence_index,
    ):
        """A pallet is held to 250 even at a depth where a tray needs 150.

        "A `PALLET` must hold at least 250 pieces regardless of sort level. A `TRAY`
        built at the deep levels `THREE_DIGIT` or `FIVE_DIGIT` must hold at least 150
        pieces." "The comparison is inclusive: a `TRAY` at `FIVE_DIGIT` holding exactly
        150 pieces qualifies, one holding 149 does not." The ordinal is positional: "The
        container's `sequence_index` is a zero-based ordinal equal to the number of
        containers already attached to the batch, assigned in creation order".

        Design: Difficulty/boundary_precision_check/tray_five_digit_at_exactly_one_hundred_fifty_pieces_qualifies
        """
        world = fx.build_empty_batch_world(api)
        # The four containers are attached in the fixed order below, so each case's
        # expected sequence_index is the count of containers before it.
        attached = [
            ("TRAY", "FIVE_DIGIT", "021", 150),
            ("TRAY", "FIVE_DIGIT", "022", 149),
            ("PALLET", "THREE_DIGIT", "021", 249),
            ("PALLET", "THREE_DIGIT", "022", 250),
        ]
        created = []
        for kind, level, zip3, pieces in attached:
            created.append(
                validate_success(
                    api.add_sort_container(
                        world.batch_id,
                        f.sort_container_payload(kind, zip3, level, pieces),
                        PRESORT_OPERATOR,
                    ),
                    expected_status=201,
                )
            )

        container = created[sequence_index]
        assert_field_values(
            container,
            {
                "container_type": container_type,
                "sort_level": sort_level,
                "piece_count": piece_count,
            },
        )
        assert_container_state(
            container,
            status="STAGED",
            qualifies=expected_qualifies,
            placard_id=None,
            sequence_index=sequence_index,
        )

    def test_a_container_below_its_minimum_is_recorded_not_refused(self, api):
        """Qualification is a flag, and the placard comes later.

        "Whether a container earns its keep is decided at once, and written to
        `qualifies`." "The container's `placard_id` starts null — documentation placards
        are stamped only at sortation — and its `status` starts at `STAGED`."

        Design: Difficulty/boundary_precision_check/tray_five_digit_at_exactly_one_hundred_fifty_pieces_qualifies
        """
        world = fx.build_empty_batch_world(api)

        short_tray = validate_success(
            api.add_sort_container(
                world.batch_id,
                f.sort_container_payload("TRAY", "022", "FIVE_DIGIT", 149),
                PRESORT_OPERATOR,
            ),
            expected_status=201,
        )
        assert_container_state(
            short_tray, status="STAGED", qualifies=False, placard_id=None
        )

    def test_the_container_count_grows_while_the_piece_ledger_does_not(self, api):
        """Containers are the physical side; pieces come from the members.

        "the batch's `container_count` is then incremented by one." The pooled ledger has
        another source entirely: "On the batch side, `total_piece_count` grows by the new
        member's `contributed_piece_count` and `member_job_count` grows by one."

        Design: Difficulty/boundary_precision_check/tray_five_digit_at_exactly_one_hundred_fifty_pieces_qualifies
        """
        world = fx.build_empty_batch_world(api)
        for kind, level, zip3, pieces in (
            ("TRAY", "FIVE_DIGIT", "021", 150),
            ("TRAY", "FIVE_DIGIT", "022", 149),
            ("PALLET", "THREE_DIGIT", "021", 249),
            ("PALLET", "THREE_DIGIT", "022", 250),
        ):
            api.add_sort_container(
                world.batch_id,
                f.sort_container_payload(kind, zip3, level, pieces),
                PRESORT_OPERATOR,
            )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_field_values(batch, {"container_count": 4, "total_piece_count": 0})

        containers, meta = validate_paginated(
            api.list_batch_containers(world.batch_id, PRESORT_OPERATOR)
        )
        assert meta["total_count"] == 4
        assert [c["sequence_index"] for c in containers] == [0, 1, 2, 3]


class TestSortWithZeroContainers:
    """A pool with mail on its ledger and nothing on the floor."""

    def test_sorting_a_batch_with_no_containers_is_refused(self, api):
        """The member side of the gate is satisfied, so the containers must answer.

        "32. **Non-empty batch** — the batch has at least one `SortContainer` and at
        least one `BatchMember`, that is `container_count` is at least 1 and
        `member_job_count` is at least 1. Violation: `ERR_BATCH_HAS_NO_CONTAINERS`
        (422)."

        Design: Difficulty/boundary_precision_check/sort_rejects_batch_with_zero_containers
        """
        world = fx.build_single_member_no_container_world(api)

        validate_error(
            api.sort_batch(world.batch_id, PRESORT_OPERATOR),
            e.ERR_BATCH_HAS_NO_CONTAINERS,
            expected_status=422,
        )

    def test_the_rejected_batch_shows_one_member_and_no_container(self, api):
        """Exactly one half of the zero-count boundary is crossed.

        "The batch must have at least one member and at least one container — a batch
        whose `member_job_count` or `container_count` is 0 is refused with
        `ERR_BATCH_HAS_NO_CONTAINERS`."

        Design: Difficulty/boundary_precision_check/sort_rejects_batch_with_zero_containers
        """
        world = fx.build_single_member_no_container_world(api)
        validate_error(
            api.sort_batch(world.batch_id, PRESORT_OPERATOR),
            e.ERR_BATCH_HAS_NO_CONTAINERS,
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_field_values(
            batch,
            {"container_count": 0, "member_job_count": 1, "total_piece_count": 1200},
        )

    def test_the_refused_sort_left_the_provisional_pricing_unfrozen(self, api):
        """The pool keeps the price membership derived, and stays OPEN.

        The membership-time derivation already ran: "Every change of membership
        immediately re-derives the batch's price, in a pinned three-stage order: first the
        tier, then the rate and batch postage, then the per-member allocation." What the
        refused sort withholds is the freeze: "When those gates pass, the batch moves
        `OPEN → SORTED` and the whole three-stage derivation of §3.4 runs one final time
        and is then frozen".

        Design: Difficulty/boundary_precision_check/sort_rejects_batch_with_zero_containers
        """
        world = fx.build_single_member_no_container_world(api)
        validate_error(
            api.sort_batch(world.batch_id, PRESORT_OPERATOR),
            e.ERR_BATCH_HAS_NO_CONTAINERS,
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        # 1200 pieces reach BASIC alone; 32000 mills over the 800 bp tier factor and the
        # 300 bp entry factor floor to 28556, and 1200 of those round to 34267 cents.
        assert_batch_pricing(
            batch,
            status="OPEN",
            achieved_tier="BASIC",
            rate_mills=SOLO_BASIC_RATE_MILLS,
            postage_cents=SOLO_BASIC_POSTAGE_CENTS,
        )

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, PRESORT_OPERATOR)
        )
        assert_member_allocation(
            members[0],
            contributed_piece_count=1200,
            share_basis_pct=100.0000,
            allocated_postage_cents=SOLO_BASIC_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )

        job = validate_success(api.get_mail_job(world.job_s_id, PRESORT_OPERATOR))
        assert_job_state(job, "POOLED", commingle_batch_id=world.batch_id)
