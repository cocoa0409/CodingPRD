"""Breadth coverage of three endpoint contracts on the process side of the plant: the
reconciliation walk an unblocked clinker silo runs, the polymorphic subject a laboratory result
must name, and the two independent state dimensions a kiln-run list filters on.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_int
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    LAB_HEADERS,
    OPERATOR_HEADERS,
)


def _released_clinker_with_one_planned_batch(api):
    """583.78 released tonnes in SC1 and one 500.00 tonne batch planned against them, which
    leaves 83.78 tonnes unreserved."""
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    batch = fx.create_planned_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    assert batch["status"] == "PLANNED"
    assert batch["feed_state"] == "FEED_READY"
    assert_amount(batch["clinker_tonnes_drawn"], 500.00, "clinker_tonnes_drawn")

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(silo["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 83.78, "available_tonnes")
    env["batch"] = batch
    env["silo"] = silo
    return env


# ---------------------------------------------------------------------------
# endpoints: the clinker a second batch would need is already promised away
# ---------------------------------------------------------------------------
def test_a_second_draw_the_remaining_clinker_cannot_cover_is_refused(api):
    """The 583.78 tonnes are physically there but 500.00 of them are already reserved, so a
    200.00 tonne draw is refused against the 83.78 that remain — availability, not stock, is
    what the gate reads, and exactly one planned batch survives the attempt.

    PRD: "The clinker silo's `available_tonnes` must cover the draw — `clinker_tonnes_drawn` no
    greater than that availability, with equality allowed — else `ERR_INSUFFICIENT_CLINKER`."

    Design: Corner/endpoints/unblocking_a_clinker_silo_restores_only_the_batches_it_can_cover
    """
    env = _released_clinker_with_one_planned_batch(api)

    validate_error(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"],
                env["clinker_silo"]["id"],
                env["cement_silo"]["id"],
                env["silo"]["version"],
                clinker_tonnes_drawn=200.00,
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_INSUFFICIENT_CLINKER.value,
        422,
    )

    rows, meta = validate_paginated(
        api.list_cement_batches(ENGINEER_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [env["batch"]["id"]]

    unchanged = validate_success(
        api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS)
    )
    assert_amount(unchanged["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(unchanged["available_tonnes"], 83.78, "available_tonnes")

    plant = validate_success(api.get_plant(env["plant_id"], ENGINEER_HEADERS))
    assert plant["production_posture"] == "NORMAL"


def test_unblocking_restores_the_batch_whose_draw_the_stock_still_covers(api):
    """Blocking the silo releases the reservation and drops the batch to `FEED_SHORT`, which
    puts the whole plant on a constrained posture; unblocking walks the short batches, finds the
    500.00 tonne draw covered by the 583.78 available again, re-takes the reservation and lets
    the grind start.

    PRD: "Unblocking then runs exactly the feed reconciliation of hops two and three of the
    release cascade in §3.6: the `FEED_SHORT` batches on that silo are walked in `created_at`
    ascending order and each one whose `clinker_tonnes_drawn` is covered by the silo's
    then-current `available_tonnes` is restored to `FEED_READY` with its reservation re-taken,
    and once no batch of the plant remains `FEED_SHORT` the plant's `production_posture` returns
    to `NORMAL`."

    Design: Corner/endpoints/unblocking_a_clinker_silo_restores_only_the_batches_it_can_cover
    """
    env = _released_clinker_with_one_planned_batch(api)
    silo_id = env["clinker_silo"]["id"]

    blocked = validate_success(
        api.patch_silo(
            silo_id, {"status": "BLOCKED", "block_reason": "SILO_INSPECTION"},
            ADMIN_HEADERS,
        )
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["block_reason"] == "SILO_INSPECTION"
    assert_amount(blocked["reserved_tonnes"], 0.00, "reserved_tonnes")

    starved = validate_success(
        api.get_cement_batch(env["batch"]["id"], ENGINEER_HEADERS)
    )
    assert starved["status"] == "PLANNED"
    assert starved["feed_state"] == "FEED_SHORT"
    constrained = validate_success(api.get_plant(env["plant_id"], ENGINEER_HEADERS))
    assert constrained["production_posture"] == "CONSTRAINED"

    opened = validate_success(
        api.patch_silo(silo_id, {"status": "OPEN"}, ADMIN_HEADERS)
    )
    assert opened["status"] == "OPEN"
    assert opened["block_reason"] is None
    assert_amount(opened["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(opened["available_tonnes"], 83.78, "available_tonnes")
    assert_amount(opened["tonnes_on_hand"], 583.78, "tonnes_on_hand")

    restored = validate_success(
        api.get_cement_batch(env["batch"]["id"], ENGINEER_HEADERS)
    )
    assert restored["feed_state"] == "FEED_READY"
    assert restored["status"] == "PLANNED"
    assert_amount(restored["clinker_tonnes_drawn"], 500.00, "clinker_tonnes_drawn")

    normal = validate_success(api.get_plant(env["plant_id"], ENGINEER_HEADERS))
    assert normal["production_posture"] == "NORMAL"

    grinding = validate_success(
        api.start_grinding(env["batch"]["id"], OPERATOR_HEADERS)
    )
    assert grinding["status"] == "GRINDING"


# ---------------------------------------------------------------------------
# endpoints: the laboratory subject is polymorphic and singular
# ---------------------------------------------------------------------------
def _run_and_ground_batch(api):
    """A released run — so its process dimension is `COMPLETED` — and a `GROUND` batch, one
    testable subject of each kind."""
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    env["batch"] = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    assert env["batch"]["status"] == "GROUND"
    run = validate_success(api.get_kiln_run(env["run"]["id"], LAB_HEADERS))
    assert run["process_state"] == "COMPLETED"
    assert run["quality_state"] == "RELEASED"
    return env


def test_a_laboratory_result_naming_neither_or_both_subjects_is_refused(api):
    """Both subject slots empty and both subject slots filled fail the identical way, because
    the rule is exactly-one and not at-least-one; neither attempt leaves a row behind.

    PRD: "Supplying neither subject, supplying both, or supplying the wrong kind for the test
    type is refused with `ERR_TEST_SUBJECT_INVALID`."

    Design: Corner/endpoints/lab_test_needs_exactly_one_subject_of_the_right_kind
    """
    env = _run_and_ground_batch(api)

    validate_error(
        api.create_lab_test(f.lab_test_payload("FREE_LIME", 1.20), LAB_HEADERS),
        ApiErrorId.ERR_TEST_SUBJECT_INVALID.value,
        422,
    )
    validate_error(
        api.create_lab_test(
            f.lab_test_payload(
                "FREE_LIME",
                1.20,
                kiln_run_id=env["run"]["id"],
                cement_batch_id=env["batch"]["id"],
            ),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_TEST_SUBJECT_INVALID.value,
        422,
    )

    # Only the single free-lime reading that released the run exists.
    _rows, meta = validate_paginated(
        api.list_lab_tests(LAB_HEADERS, params={"kiln_run_id": env["run"]["id"]})
    )
    assert meta["total_count"] == 1
    _batch_rows, batch_meta = validate_paginated(
        api.list_lab_tests(LAB_HEADERS, params={"cement_batch_id": env["batch"]["id"]})
    )
    assert batch_meta["total_count"] == 0


def test_each_test_type_admits_only_its_own_kind_of_subject(api):
    """Free lime is a clinker measurement and Blaine a cement one, so crossing them over is
    refused even though both subjects exist and are testable; the correct pairing then derives
    its one-sided ceiling from the run's plant.

    PRD: "The subject is polymorphic and must match the test type: `FREE_LIME` is a clinker
    measurement and requires a `kiln_run_id` with `cement_batch_id` left null, while `BLAINE`
    and `COMPRESSIVE_STRENGTH_28D` are cement measurements and require a `cement_batch_id` with
    `kiln_run_id` left null."

    Design: Corner/endpoints/lab_test_needs_exactly_one_subject_of_the_right_kind
    """
    env = _run_and_ground_batch(api)

    validate_error(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.20, cement_batch_id=env["batch"]["id"]),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_TEST_SUBJECT_INVALID.value,
        422,
    )
    validate_error(
        api.create_lab_test(
            f.lab_test_payload("BLAINE", 400, kiln_run_id=env["run"]["id"]),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_TEST_SUBJECT_INVALID.value,
        422,
    )

    accepted = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.20, kiln_run_id=env["run"]["id"]),
            LAB_HEADERS,
        ),
        201,
    )
    assert accepted["test_type"] == "FREE_LIME"
    assert accepted["unit"] == "PCT"
    assert accepted["spec_min"] is None
    assert_amount(accepted["spec_max"], 1.50, "spec_max")
    assert accepted["in_spec"] is True
    assert accepted["cement_batch_id"] is None
    assert accepted["kiln_run_id"] == env["run"]["id"]

    blaine = validate_success(
        api.create_lab_test(
            f.lab_test_payload("BLAINE", 400, cement_batch_id=env["batch"]["id"]),
            LAB_HEADERS,
        ),
        201,
    )
    assert blaine["unit"] == "M2_PER_KG"
    assert blaine["in_spec"] is True
    assert blaine["kiln_run_id"] is None


def test_an_unresolvable_subject_identifier_answers_before_the_kind_check(api):
    """A subject id that names no row is a foreign-key failure, so the answer is that entity's
    own 404 rather than the 422 the kind gate would have given — and it is the wrong-kind
    pairing that proves the ordering, since a bogus batch id on a free-lime test is caught by
    the earlier rung.

    PRD: "On every endpoint whose body carries a foreign key: every such key resolves to an
    existing row of its target entity, else that referenced entity's own not-found error (404)."

    Design: Corner/endpoints/lab_test_needs_exactly_one_subject_of_the_right_kind
    """
    env = _run_and_ground_batch(api)

    validate_error(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.20, kiln_run_id=NON_EXISTENT_UUID),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_KILN_RUN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.20, cement_batch_id=NON_EXISTENT_UUID),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_BATCH_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_lab_test(
            f.lab_test_payload("BLAINE", 400, kiln_run_id=NON_EXISTENT_UUID),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_KILN_RUN_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_lab_tests(LAB_HEADERS, params={"cement_batch_id": env["batch"]["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# endpoints: the run list filters on two independent state dimensions
# ---------------------------------------------------------------------------
def test_the_two_state_dimensions_and_together_with_the_foreign_key_filters(api):
    """One run, four questions. `COMPLETED` plus `RELEASED` finds it; `COMPLETED` plus
    `QUARANTINED` finds nothing, which is only possible if the two dimensions are separate
    columns conjoined; a correct kiln with the wrong silo finds nothing; and the pile it was fed
    from finds it again.

    PRD: "Runs can be listed with optional filters on `kiln_id`, `blended_pile_id`,
    `clinker_silo_id`, `process_state` and `quality_state`."

    Design: Corner/endpoints/kiln_run_list_filters_compose_across_both_state_dimensions
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    run_id = env["run"]["id"]

    rows, meta = validate_paginated(
        api.list_kiln_runs(
            OPERATOR_HEADERS,
            params={
                "process_state": "COMPLETED",
                "quality_state": "RELEASED",
                "limit": 50,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [run_id]

    crossed, crossed_meta = validate_paginated(
        api.list_kiln_runs(
            OPERATOR_HEADERS,
            params={"process_state": "COMPLETED", "quality_state": "QUARANTINED"},
        )
    )
    assert crossed_meta["total_count"] == 0
    assert crossed == []
    assert crossed_meta["has_more"] is False

    wrong_silo, wrong_silo_meta = validate_paginated(
        api.list_kiln_runs(
            OPERATOR_HEADERS,
            params={
                "kiln_id": env["kiln"]["id"],
                "clinker_silo_id": env["cement_silo"]["id"],
            },
        )
    )
    assert wrong_silo_meta["total_count"] == 0
    assert wrong_silo == []

    by_pile, by_pile_meta = validate_paginated(
        api.list_kiln_runs(
            OPERATOR_HEADERS, params={"blended_pile_id": env["pile"]["id"]}
        )
    )
    assert by_pile_meta["total_count"] == 1
    assert [row["id"] for row in by_pile] == [run_id]


def test_an_offset_past_the_only_matching_row_still_reports_the_filtered_total(api):
    """`total_count` counts the matches, not the rows on the page, so skipping the single run
    leaves the count at 1 with an empty page and nothing further to fetch.

    PRD: "`total_count` is the number of rows matching the request's filters before pagination is
    applied, and `has_more` is true when rows remain beyond the current page."

    Design: Corner/endpoints/kiln_run_list_filters_compose_across_both_state_dimensions
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)

    first_page, first_meta = validate_paginated(
        api.list_kiln_runs(OPERATOR_HEADERS, params={"limit": 50, "offset": 0})
    )
    assert first_meta["total_count"] == 1
    assert first_meta["has_more"] is False
    assert [row["id"] for row in first_page] == [env["run"]["id"]]

    past_the_end, past_meta = validate_paginated(
        api.list_kiln_runs(OPERATOR_HEADERS, params={"limit": 50, "offset": 1})
    )
    assert past_meta["total_count"] == 1
    assert past_the_end == []
    assert past_meta["has_more"] is False
    assert_int(past_meta["offset"], 1, "offset")
    assert_int(past_meta["limit"], 50, "limit")
