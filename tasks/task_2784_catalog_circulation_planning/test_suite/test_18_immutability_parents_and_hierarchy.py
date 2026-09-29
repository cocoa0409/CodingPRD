"""Rows that can never be rewritten, parents that must exist, and a graph that
must not close into a loop.

The two audit entities are priced once at creation and then frozen, so their
shape is part of the contract: identity and a creation stamp, and nothing that
would imply an update path. Body-borne foreign keys are held to exactly the
standard path identifiers are held to, including inside an array. And the segment
hierarchy's cycle guard has to look past a self-edge to ancestry and to season.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    BROKER,
    CLOCK_START,
    PLANNER,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_immutable_audit_row,
    assert_postal_presort_batch,
    assert_contact_event,
    allocate,
    create_contact_event_payload,
    create_housefile_line_payload,
    create_merge_purge_run_payload,
    create_presort_batch_payload,
    create_segment_payload,
    fetch_rental,
    fetch_segment,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_rental_in_state,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _allocated_drop_ready_for_audit_rows() -> dict:
    """Season FW26 with segment S_A, plan P1 carrying a COMPLETED housefile-only
    merge-purge run, and an allocated 20000-book drop."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
    allocated = allocate(drop["id"])
    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "drop": allocated,
        "line": line,
    }


class TestImmutableAuditRows:
    def test_a_presort_batch_is_priced_once_and_carries_no_version(self, api):
        """PRD §3.7: "A batch is an immutable audit row: it has no version and no
        update path, and the only thing that ever removes one is the wholesale
        deletion described in §3.6 when a presorted drop reverts."

        Design: Corner/entities/immutable_rows_carry_no_version_and_cannot_be_updated
        """
        world = _allocated_drop_ready_for_audit_rows()
        drop_id = world["drop"]["id"]
        assert world["drop"]["planned_quantity"] == 20000

        batch = validate_success(
            api.create_presort_batch(
                drop_id, create_presort_batch_payload(20000, "FIVE_DIGIT"), PLANNER
            ),
            201,
        )

        assert_postal_presort_batch(batch)
        assert_immutable_audit_row(batch)
        assert "updated_at" not in batch
        assert "version" not in batch
        assert batch["effective_tier"] == "FIVE_DIGIT"
        assert batch["rate_cents_per_piece"] == 42
        assert batch["piece_count"] == 20000
        assert batch["is_automation_qualified"] is True

        batches, meta = validate_paginated(api.list_presort_batches(drop_id, PLANNER))
        assert meta["total_count"] == 1
        assert batches[0]["id"] == batch["id"]
        assert "version" not in batches[0]

    def test_a_contact_event_freezes_its_weighted_points_and_carries_no_version(
        self, api
    ):
        """PRD §3.8: "Each contact event row also stores its own `channel_weight`,
        `decay_factor_bps` and `weighted_points`, and those three columns are
        written exactly once, at creation, from the clock as it stood at that
        moment."

        Design: Corner/entities/immutable_rows_carry_no_version_and_cannot_be_updated
        """
        world = _allocated_drop_ready_for_audit_rows()
        segment_id = world["segment"]["id"]

        event = validate_success(
            api.create_contact_event(
                create_contact_event_payload(
                    segment_id, iso_utc("2026-08-01"), channel="EMAIL"
                ),
                ANALYST,
            ),
            201,
        )

        assert_contact_event(event)
        assert_immutable_audit_row(event)
        assert "updated_at" not in event
        assert "version" not in event
        assert event["channel"] == "EMAIL"
        assert event["channel_weight"] == 12
        assert event["decay_factor_bps"] == 10000
        assert event["weighted_points"] == 12
        assert event["source"] == "MANUAL_LOG"
        assert event["drop_id"] is None

        events, meta = validate_paginated(
            api.list_segment_contact_events(segment_id, ANALYST)
        )
        assert meta["total_count"] == 1
        assert events[0]["id"] == event["id"]
        assert "updated_at" not in events[0]


def _season_with_a_delivered_rental_and_an_empty_drop() -> dict:
    """Season FW26 with segment S_A, a DELIVERED rental of 25000 gross names,
    plan P1 at version 1 with no merge-purge run yet, and an empty drop."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A")
    rental = new_rental_in_state(
        season["id"],
        coop_model_score=640,
        delivered_gross_names=25000,
        list_source_name="COOP-A",
        requested_gross_names=25000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=2000,
        inter_list_overlap_bps=0,
    )
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    return {
        "season": season,
        "segment": segment,
        "rental": rental,
        "plan": plan,
        "drop": drop,
    }


class TestUnresolvableParents:
    def test_three_body_foreign_keys_each_answer_with_their_own_family_404(self, api):
        """PRD §2.10: "**Every body foreign key resolves**, on `POST
        /catalog-circulation/housefile-segments`, `POST
        /catalog-circulation/prospect-list-rentals`, `POST
        /catalog-circulation/circulation-plans`, `POST
        /catalog-circulation/circulation-plans/{id}/merge-purge-runs`, `POST
        /catalog-circulation/drops/{id}/circulation-lines` and `POST
        /catalog-circulation/contact-events` — otherwise the matching 404 from
        §2.8."

        Design: Corner/entities/child_creation_against_a_missing_parent_returns_404
        """
        world = _season_with_a_delivered_rental_and_an_empty_drop()
        season_id = world["season"]["id"]

        validate_error(
            api.create_segment(
                create_segment_payload(NON_EXISTENT_UUID, segment_code="S_ORPHAN"),
                PLANNER,
            ),
            ApiErrorId.ERR_SEASON_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_segment(
                create_segment_payload(
                    season_id,
                    segment_code="S_CHILD",
                    parent_segment_id=NON_EXISTENT_UUID,
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_SEGMENT_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_line(
                world["drop"]["id"],
                create_housefile_line_payload(
                    NON_EXISTENT_UUID, requested_quantity=5000
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_SEGMENT_NOT_FOUND.value,
            404,
        )

        _segments, meta = validate_paginated(
            api.list_segments(PLANNER, {"season_id": season_id})
        )
        assert meta["total_count"] == 1

    def test_one_unresolvable_element_fails_the_whole_rental_array(self, api):
        """PRD §3.2: "The final procurement step is not a broker action at all: a
        rental moves `DELIVERED → NETTED` as a consequence of a merge-purge run
        completing with that rental in its input set, at which point
        `net_names_delivered` is written as the rental's `gross_names` less its own
        housefile and inter-list duplicate removals."

        Design: Corner/entities/child_creation_against_a_missing_parent_returns_404
        """
        world = _season_with_a_delivered_rental_and_an_empty_drop()
        plan_id = world["plan"]["id"]
        rental_id = world["rental"]["id"]

        assert world["rental"]["status"] == "DELIVERED"
        assert world["plan"]["version"] == 1

        validate_error(
            api.create_merge_purge_run(
                plan_id,
                create_merge_purge_run_payload(1, [rental_id, NON_EXISTENT_UUID]),
                BROKER,
            ),
            ApiErrorId.ERR_RENTAL_NOT_FOUND.value,
            404,
        )

        _runs, meta = validate_paginated(api.list_merge_purge_runs(plan_id, BROKER))
        assert meta["total_count"] == 0

        rental = fetch_rental(rental_id)
        assert rental["status"] == "DELIVERED"
        assert rental["net_names_delivered"] == 0
        assert rental["gross_names"] == 25000


def _three_deep_chain_and_a_foreign_season() -> dict:
    """S_TOP -> S_MID -> S_LEAF inside FW26 with own counts 10000 / 20000 /
    30000, plus S_OTHER of 5000 names inside a second season SS26."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    other_season = new_season(season_code="SS26", fiscal_year=2026)

    top = new_segment(season["id"], segment_code="S_TOP", housefile_count=10000)
    mid = new_segment(
        season["id"],
        segment_code="S_MID",
        housefile_count=20000,
        parent_segment_id=top["id"],
    )
    leaf = new_segment(
        season["id"],
        segment_code="S_LEAF",
        housefile_count=30000,
        parent_segment_id=mid["id"],
    )
    other = new_segment(
        other_season["id"], segment_code="S_OTHER", housefile_count=5000
    )
    return {
        "season": season,
        "other_season": other_season,
        "top": top,
        "mid": mid,
        "leaf": leaf,
        "other": other,
    }


class TestSegmentCycleGuard:
    def test_a_self_parent_a_two_hop_loop_and_a_foreign_season_all_fail(self, api):
        """PRD §3.1: "A parent must belong to the same season as its child, a
        segment may never name itself as its own parent, and no chain of parent
        links may close into a cycle — a segment can never be its own ancestor."

        Design: Corner/entities/self_referential_segment_cycle_is_rejected
        """
        world = _three_deep_chain_and_a_foreign_season()
        mid_id = world["mid"]["id"]
        # Registering S_LEAF already rewrote is_leaf and rollup_housefile_count on
        # both ancestors, and PRD §2.4 advances a version on every mutation
        # "including mutations the row's owner did not request, such as a cascade
        # reaching it from another aggregate" — so the invariant under test is that
        # the three rejections move neither version any further.
        top_version = fetch_segment(world["top"]["id"])["version"]
        mid_version = fetch_segment(mid_id)["version"]

        validate_error(
            api.update_segment(mid_id, {"parent_segment_id": mid_id}, PLANNER),
            ApiErrorId.ERR_SEGMENT_CYCLE.value,
            422,
        )

        validate_error(
            api.update_segment(
                world["top"]["id"],
                {"parent_segment_id": world["leaf"]["id"]},
                PLANNER,
            ),
            ApiErrorId.ERR_SEGMENT_CYCLE.value,
            422,
        )

        validate_error(
            api.update_segment(
                mid_id, {"parent_segment_id": world["other"]["id"]}, PLANNER
            ),
            ApiErrorId.ERR_SEGMENT_CYCLE.value,
            422,
        )

        mid = fetch_segment(mid_id)
        top = fetch_segment(world["top"]["id"])
        assert mid["parent_segment_id"] == top["id"]
        assert top["parent_segment_id"] is None
        assert top["version"] == top_version
        assert mid["version"] == mid_version

    def test_the_rollups_and_leaf_flags_survive_the_three_rejections(self, api):
        """PRD §3.1: "`rollup_housefile_count` is a segment's own `housefile_count`
        plus the transitive sum of every descendant segment's `housefile_count`, so
        it is recomputed for a parent whenever a descendant is added, re-parented,
        or has its own count amended."

        Design: Corner/entities/self_referential_segment_cycle_is_rejected
        """
        world = _three_deep_chain_and_a_foreign_season()
        mid_id = world["mid"]["id"]

        for target_id, parent_id in (
            (mid_id, mid_id),
            (world["top"]["id"], world["leaf"]["id"]),
            (mid_id, world["other"]["id"]),
        ):
            validate_error(
                api.update_segment(
                    target_id, {"parent_segment_id": parent_id}, PLANNER
                ),
                ApiErrorId.ERR_SEGMENT_CYCLE.value,
                422,
            )

        top = fetch_segment(world["top"]["id"], ADMIN)
        mid = fetch_segment(mid_id, ADMIN)
        leaf = fetch_segment(world["leaf"]["id"], ADMIN)

        assert top["rollup_housefile_count"] == 60000
        assert top["is_leaf"] is False
        assert mid["rollup_housefile_count"] == 50000
        assert mid["is_leaf"] is False
        assert leaf["rollup_housefile_count"] == 30000
        assert leaf["is_leaf"] is True

        other = fetch_segment(world["other"]["id"], ADMIN)
        assert other["rollup_housefile_count"] == 5000
        assert other["parent_segment_id"] is None
