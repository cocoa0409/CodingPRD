"""Figures the server derives rather than accepts: container zones and service
commitments, the presort tier ladder, the two hygiene denominators, and the two
service-level indices over a scanned population.

Every figure here has exactly one producer and exactly one rounding step, so a
test that fixes the inputs fixes the output to the digit. The worlds are built
from scratch in each test because the harness empties the database first.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_PIECE_COUNT
from test_helpers.assertions import (
    assert_container_state,
    assert_field_values,
    assert_pct_2dp,
    assert_service_level_index,
)
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)


def _deposit_the_canonical_batch(api):
    """The canonical two-client batch deposited at 14:00 on 12 August.

    The deposit opens exactly one service-level record per container; both are
    read straight back and kept on the world as ``slr_1`` and ``slr_2`` so a
    test never has to walk from the containers itself. Neither record has been
    delivery-scanned yet.
    """
    world = fx.build_departed_world(api)
    validate_success(api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK))
    records_1, _meta_1 = validate_paginated(
        api.list_container_service_level_records(world.container_1_id, ACCEPTANCE_CLERK)
    )
    records_2, _meta_2 = validate_paginated(
        api.list_container_service_level_records(world.container_2_id, ACCEPTANCE_CLERK)
    )
    assert len(records_1) == 1 and len(records_2) == 1, (
        "the deposit must open exactly one service-level record per container"
    )
    world.slr_1 = records_1[0]
    world.slr_1_id = records_1[0]["id"]
    world.slr_2 = records_2[0]
    world.slr_2_id = records_2[0]["id"]
    return world


class TestZoneAndCommittedDaysFromTheFacility:
    """One DDU entry point, one served destination and one that is not."""

    def test_a_served_destination_takes_the_facility_zone_and_an_unserved_one_falls_to_eight(
        self, api
    ):
        """The served list is consulted by exact string membership.

        "If the container's `destination_zip3` appears as an exact member of that
        facility's `served_zip3_list` — plain string membership, with no prefix or
        range logic — then the facility type decides both figures: a `DDU` gives
        `zone` 1 and a base of 1 day, an `SCF` gives `zone` 2 and a base of 2 days,
        and an `NDC` gives `zone` 4 and a base of 3 days. If the destination is not
        in the served list, the container falls to `zone` 8 with a base of 5 days."
        For a `FIRST_CLASS` pool the class adder is nil, because "`FIRST_CLASS` adds
        0 days", so the base is the whole commitment.

        Design: Corner/calculations/correct_result_zone_and_committed_days_from_facility_and_zip3
        """
        facility = fx.setup_facility(
            api,
            facility_code="DDU-021",
            facility_type="DDU",
            zip3="021",
            dock_capacity_pallets_per_slot=6,
            drop_ship_discount_bp=500,
            served_zip3_list=["021"],
        )
        batch = fx.create_batch(
            api,
            f.commingle_batch_payload(
                facility["id"], mail_class="FIRST_CLASS", processing_category="LETTERS"
            ),
        )

        served = fx.add_container(
            api,
            batch["id"],
            f.sort_container_payload(
                container_type="TRAY",
                destination_zip3="021",
                sort_level="FIVE_DIGIT",
                piece_count=200,
            ),
        )
        unserved = fx.add_container(
            api,
            batch["id"],
            f.sort_container_payload(
                container_type="TRAY",
                destination_zip3="941",
                sort_level="THREE_DIGIT",
                piece_count=200,
            ),
        )

        assert_field_values(served, {"zone": 1, "committed_days": 1})
        assert_field_values(unserved, {"zone": 8, "committed_days": 5})

    def test_the_unserved_tray_is_not_quietly_given_the_facility_zone(self, api):
        """A 941 tray at an 021-only deep dock is a long haul, not a local drop.

        "`zone` is therefore always one of 1, 2, 4 or 8." A `DDU` serving only 021
        cannot lend its own `zone` 1 to a destination it does not serve: "If the
        destination is not in the served list, the container falls to `zone` 8 with a
        base of 5 days."

        Design: Corner/calculations/correct_result_zone_and_committed_days_from_facility_and_zip3
        """
        facility = fx.setup_facility(
            api,
            facility_code="DDU-021",
            facility_type="DDU",
            zip3="021",
            dock_capacity_pallets_per_slot=6,
            drop_ship_discount_bp=500,
            served_zip3_list=["021"],
        )
        batch = fx.create_batch(
            api, f.commingle_batch_payload(facility["id"], mail_class="FIRST_CLASS")
        )

        served = fx.add_container(
            api,
            batch["id"],
            f.sort_container_payload("TRAY", "021", "FIVE_DIGIT", 200),
        )
        unserved = fx.add_container(
            api,
            batch["id"],
            f.sort_container_payload("TRAY", "941", "THREE_DIGIT", 200),
        )

        assert unserved["zone"] != served["zone"], (
            "an unserved destination must not inherit the facility's own zone"
        )
        assert unserved["committed_days"] > served["committed_days"]
        assert served["zone"] in (1, 2, 4, 8) and unserved["zone"] in (1, 2, 4, 8)
        # Both trays are deep-sorted and well over the 150-piece tray minimum, so
        # the zone split is the only difference between them.
        assert_container_state(
            served, status="STAGED", qualifies=True, placard_id=None, sequence_index=0
        )
        assert_container_state(
            unserved, status="STAGED", qualifies=True, placard_id=None, sequence_index=1
        )


class TestClassDayAdderAcrossMailClasses:
    """The same served tray at the same SCF, priced for three mail classes."""

    def test_each_mail_class_adds_its_own_number_of_days(self, api):
        """One base of two days, three different commitments.

        "The container's `committed_days` is that base plus a class adder taken from
        the batch's mail class: `FIRST_CLASS` adds 0 days, `PERIODICALS` adds 1 day,
        and `MARKETING_MAIL` adds 2 days." The base is the entry point's: "an `SCF`
        gives `zone` 2 and a base of 2 days".

        Design: Corner/calculations/constants_applied_class_day_adder_across_three_mail_classes
        """
        facility = fx.setup_facility(api, served_zip3_list=["021", "022"])

        committed = {}
        for mail_class in ("FIRST_CLASS", "PERIODICALS", "MARKETING_MAIL"):
            batch = fx.create_batch(
                api,
                f.commingle_batch_payload(
                    facility["id"],
                    mail_class=mail_class,
                    processing_category="LETTERS",
                ),
            )
            container = fx.add_container(
                api,
                batch["id"],
                f.sort_container_payload("TRAY", "022", "FIVE_DIGIT", 300),
            )
            committed[mail_class] = container["committed_days"]

        assert committed["FIRST_CLASS"] == 2
        assert committed["PERIODICALS"] == 3
        assert committed["MARKETING_MAIL"] == 4

    def test_the_mail_class_moves_the_commitment_but_never_the_zone(self, api):
        """Geography sets the zone; the class of mail only sets the pace.

        "If the container's `destination_zip3` appears as an exact member of that
        facility's `served_zip3_list` — plain string membership, with no prefix or
        range logic — then the facility type decides both figures: a `DDU` gives
        `zone` 1 and a base of 1 day, an `SCF` gives `zone` 2 and a base of 2 days,
        and an `NDC` gives `zone` 4 and a base of 3 days."

        Design: Corner/calculations/constants_applied_class_day_adder_across_three_mail_classes
        """
        facility = fx.setup_facility(api, served_zip3_list=["021", "022"])

        zones = []
        for mail_class in ("FIRST_CLASS", "PERIODICALS", "MARKETING_MAIL"):
            batch = fx.create_batch(
                api, f.commingle_batch_payload(facility["id"], mail_class=mail_class)
            )
            container = fx.add_container(
                api,
                batch["id"],
                f.sort_container_payload("TRAY", "022", "FIVE_DIGIT", 300),
            )
            zones.append(container["zone"])

        assert zones == [2, 2, 2], (
            "the 022 tray is served by the SCF in every class, so the zone is fixed"
        )


class TestTierLadderAtItsThresholds:
    """A pool walked to 499, then 2999, then exactly 3000 pieces."""

    def _three_cleared_jobs(self, api):
        """A client with three cleared jobs of 499, 2500 and 1 accepted pieces."""
        owner = fx.setup_client_with_permit(
            api,
            name="Tiernan Mailings",
            client_code="TIERS",
            permit_number="PI-500500",
            payment_method="METER",
        )
        facility = fx.setup_facility(api)
        job_499 = fx.setup_cleared_job(
            api,
            owner.client_id,
            owner.permit_id,
            declared_piece_count=500,
            submitted_piece_count=500,
            cass_matched_count=500,
            ncoa_move_updated_count=10,
            undeliverable_removed_count=1,
            move_update_age_days=10,
        )
        job_2500 = fx.setup_cleared_job(
            api,
            owner.client_id,
            owner.permit_id,
            declared_piece_count=2500,
            submitted_piece_count=2500,
            cass_matched_count=2480,
            ncoa_move_updated_count=60,
            undeliverable_removed_count=0,
            move_update_age_days=10,
        )
        job_1 = fx.setup_cleared_job(
            api,
            owner.client_id,
            owner.permit_id,
            declared_piece_count=1,
            submitted_piece_count=1,
            cass_matched_count=1,
            ncoa_move_updated_count=0,
            undeliverable_removed_count=0,
            move_update_age_days=10,
        )
        assert job_499.job["accepted_piece_count"] == 499
        assert job_2500.job["accepted_piece_count"] == 2500
        assert job_1.job["accepted_piece_count"] == 1
        batch = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        return batch, job_499, job_2500, job_1

    def test_every_member_add_re_derives_the_tier_from_the_pooled_volume(self, api):
        """The ladder is climbed one pooling at a time.

        "Every change of membership immediately re-derives the batch's price, in a
        pinned three-stage order: first the tier, then the rate and batch postage,
        then the per-member allocation." The tier itself follows the volume: "A pool
        of at least 15000 pieces qualifies `FIVE_DIGIT`; failing that, a pool of at
        least 3000 pieces qualifies `THREE_DIGIT`; failing that, a pool of at least
        500 pieces qualifies `BASIC`; a pool below 500 pieces achieves `NONE`."

        Design: Corner/calculations/threshold_batch_tier_at_499_2999_and_3000_pieces
        """
        batch, job_499, job_2500, job_1 = self._three_cleared_jobs(api)

        fx.add_member(api, batch["id"], job_499.job_id)
        after_499 = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert after_499["total_piece_count"] == 499
        assert after_499["achieved_tier"] == "NONE"

        fx.add_member(api, batch["id"], job_2500.job_id)
        after_2999 = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert after_2999["total_piece_count"] == 2999
        assert after_2999["achieved_tier"] == "BASIC"

        fx.add_member(api, batch["id"], job_1.job_id)
        after_3000 = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert after_3000["total_piece_count"] == 3000
        assert after_3000["achieved_tier"] == "THREE_DIGIT"

    def test_one_more_piece_at_2999_crosses_the_three_digit_threshold(self, api):
        """The thresholds are inclusive, so 3000 qualifies and 2999 does not.

        "The comparisons are inclusive at every step, so exactly 3000 pieces
        qualifies `THREE_DIGIT` while 2999 pieces qualifies only `BASIC`." The volume
        compared is the pool's own: "The piece count used is the batch's
        `total_piece_count`, that is the sum of `contributed_piece_count` over the
        batch's *currently attached* members; a member that has been withdrawn
        contributes nothing."

        Design: Corner/calculations/threshold_batch_tier_at_499_2999_and_3000_pieces
        """
        batch, job_499, job_2500, job_1 = self._three_cleared_jobs(api)

        fx.add_member(api, batch["id"], job_499.job_id)
        fx.add_member(api, batch["id"], job_2500.job_id)
        just_below = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_field_values(
            just_below,
            {"total_piece_count": 2999, "achieved_tier": "BASIC", "member_job_count": 2},
        )

        fx.add_member(api, batch["id"], job_1.job_id)
        exactly_at = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_field_values(
            exactly_at,
            {
                "total_piece_count": 3000,
                "achieved_tier": "THREE_DIGIT",
                "member_job_count": 3,
            },
        )
        assert exactly_at["total_piece_count"] - just_below["total_piece_count"] == 1, (
            "a single piece is what separates BASIC from THREE_DIGIT here"
        )


class TestHygieneRunDerivations:
    """One 1250-piece pass whose quality denominator is the submitted volume."""

    def _job_in_received(self, api):
        owner = fx.setup_client_with_permit(
            api,
            name="Hygienic Data Co",
            client_code="HYG",
            permit_number="PI-600600",
            payment_method="METER",
        )
        job = fx.create_mail_job(
            api,
            f.mail_job_payload(
                owner.client_id,
                owner.permit_id,
                declared_piece_count=1250,
                declared_weight_oz_per_piece=1.2,
            ),
        )
        assert job["status"] == "RECEIVED"
        return owner, job

    def test_the_quality_percentage_divides_by_the_submitted_count(self, api):
        """1235 of 1250 submitted is 98.80 percent, not 1235 of the 1200 that survived.

        "Its `net_piece_count` is the `submitted_piece_count` less the
        `undeliverable_removed_count`. Its `address_quality_pct` is the
        `cass_matched_count` multiplied by one hundred and divided by the
        `submitted_piece_count`, rounded half up to two decimal places." The run also
        carries its own ordinal and verdict: "Its `run_index` is a zero-based ordinal
        equal to the job's `hygiene_run_count` as it stood immediately *before* this
        run was counted, so a job's very first pass carries `run_index` 0" and "Its
        `move_update_compliant` is true when `move_update_age_days` is less than or
        equal to the maximum permitted age of 95 days".

        Design: Corner/calculations/aggregation_hygiene_quality_denominator_is_submitted_not_net
        """
        _owner, job = self._job_in_received(api)

        run = validate_success(
            api.create_hygiene_run(
                job["id"],
                f.hygiene_run_payload(
                    submitted_piece_count=1250,
                    cass_matched_count=1235,
                    ncoa_move_updated_count=40,
                    undeliverable_removed_count=50,
                    move_update_age_days=30,
                ),
                PRESORT_OPERATOR,
            ),
            201,
        )

        assert_field_values(
            run,
            {
                "run_index": 0,
                "net_piece_count": 1200,
                "move_update_compliant": True,
            },
        )
        assert_pct_2dp(run, "address_quality_pct", 98.80)
        assert run["address_quality_pct"] != 102.92, (
            "dividing by the net 1200 would report an impossible quality above 100"
        )

    def test_the_newest_run_mirrors_its_three_measures_onto_the_job(self, api):
        """The job takes the run's net volume, quality and move-update verdict.

        "The job's `accepted_piece_count` is set to that run's `net_piece_count`, its
        `address_quality_pct` to that run's `address_quality_pct`, and its
        `move_update_compliant` to that run's `move_update_compliant`." The pass also
        clears the job: "Recording a pass on a job in `RECEIVED` drives it
        `RECEIVED → HYGIENE_CLEARED`".

        Design: Corner/calculations/aggregation_hygiene_quality_denominator_is_submitted_not_net
        """
        _owner, job = self._job_in_received(api)

        fx.create_hygiene_run(
            api, job["id"], f.hygiene_run_payload(1250, 1235, 40, 50, 30)
        )

        mirrored = validate_success(api.get_mail_job(job["id"], PRESORT_OPERATOR))
        assert_field_values(
            mirrored,
            {
                "status": "HYGIENE_CLEARED",
                "accepted_piece_count": 1200,
                "hygiene_run_count": 1,
                "move_update_compliant": True,
            },
        )
        assert_pct_2dp(mirrored, "address_quality_pct", 98.80)

    def test_a_pass_that_would_empty_the_mailing_is_refused_outright(self, api):
        """Suppressing every submitted piece is not a hygiene result.

        The bound is part of the pass definition: "the
        `undeliverable_removed_count` of pieces suppressed as undeliverable, which
        must be strictly less than `submitted_piece_count` so that a pass can never
        empty the mailing". "Any of those bounds being broken is rejected with
        `ERR_INVALID_PIECE_COUNT`."

        Design: Corner/calculations/aggregation_hygiene_quality_denominator_is_submitted_not_net
        """
        _owner, job = self._job_in_received(api)
        fx.create_hygiene_run(
            api, job["id"], f.hygiene_run_payload(1250, 1235, 40, 50, 30)
        )

        validate_error(
            api.create_hygiene_run(
                job["id"],
                f.hygiene_run_payload(
                    submitted_piece_count=1250,
                    cass_matched_count=1250,
                    ncoa_move_updated_count=40,
                    undeliverable_removed_count=1250,
                    move_update_age_days=30,
                ),
                PRESORT_OPERATOR,
            ),
            ERR_INVALID_PIECE_COUNT,
            400,
        )

        untouched = validate_success(api.get_mail_job(job["id"], PRESORT_OPERATOR))
        assert_field_values(
            untouched,
            {
                "status": "HYGIENE_CLEARED",
                "accepted_piece_count": 1200,
                "hygiene_run_count": 1,
            },
        )
        assert_pct_2dp(untouched, "address_quality_pct", 98.80)


class TestServiceIndexPopulationIsScannedRecordsOnly:
    """Two deposited containers, only one of them ever delivery-scanned."""

    def test_an_unscanned_population_reports_both_indexes_as_null(self, api):
        """A deposit alone proves nothing about delivery.

        "The population is every service-level record that has actually been
        delivery-scanned — that is, whose `actual_delivery_days` is not null — whose
        container belongs to a batch that has at least one member whose job's
        `client_id` is the client being asked about." "If the population is empty,
        both indexes are reported as null and `record_count` is 0."

        Design: Corner/calculations/input_set_filtering_service_index_counts_only_scanned_records
        """
        world = _deposit_the_canonical_batch(api)

        index = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        assert_service_level_index(
            index,
            record_count=0,
            on_time_count=0,
            zone_weighted_index=None,
            piece_weighted_index=None,
        )

    def test_the_unscanned_record_is_left_out_of_both_numerator_and_denominator(
        self, api
    ):
        """One on-time scan out of two records reads as a perfect record.

        "Unscanned records are excluded from both numerator and denominator
        entirely." The scanned tray is on time because "delivering in exactly the
        committed number of days counts as on time", so with a population of one both
        weightings sit at the top of the scale.

        Design: Corner/calculations/input_set_filtering_service_index_counts_only_scanned_records
        """
        world = _deposit_the_canonical_batch(api)

        scanned = fx.record_delivery_scan(
            api, world.slr_1_id, 4, fx.SCAN_CLOCK_ON_TIME
        )
        assert_field_values(
            scanned, {"committed_days": 4, "actual_delivery_days": 4, "on_time": True}
        )

        index = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        assert_service_level_index(
            index,
            record_count=1,
            on_time_count=1,
            zone_weighted_index=100.00,
            piece_weighted_index=100.00,
        )

    def test_both_mailers_in_the_pool_read_the_same_population(self, api):
        """The scanned tray belongs to both clients' index at once.

        "One commingled container therefore counts once for every client with mail in
        that batch."

        Design: Corner/calculations/input_set_filtering_service_index_counts_only_scanned_records
        """
        world = _deposit_the_canonical_batch(api)
        fx.record_delivery_scan(api, world.slr_1_id, 4, fx.SCAN_CLOCK_ON_TIME)

        acme_index = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        bore_index = validate_success(
            api.get_client_service_level(world.bore_id, POSTAGE_MANAGER)
        )
        assert_service_level_index(
            bore_index,
            record_count=1,
            on_time_count=1,
            zone_weighted_index=100.00,
            piece_weighted_index=100.00,
        )
        assert acme_index["record_count"] == bore_index["record_count"]
        assert acme_index["zone_weighted_index"] == bore_index["zone_weighted_index"]
        assert acme_index["piece_weighted_index"] == bore_index["piece_weighted_index"]


class TestServiceIndexRoundsHalfUpToTwoDecimals:
    """A late local tray and an on-time long-haul tray, both scanned."""

    def _scanned_late_local_and_on_time_haul(self, api):
        world = _deposit_the_canonical_batch(api)
        local = fx.record_delivery_scan(api, world.slr_1_id, 5, fx.SCAN_CLOCK_ON_TIME)
        haul = fx.record_delivery_scan(api, world.slr_2_id, 7, fx.SCAN_CLOCK_LATE)
        return world, local, haul

    def test_the_committed_day_boundary_decides_each_verdict(self, api):
        """Five days against four is late; seven against seven is on time.

        "The record's `on_time` is then set to true when `actual_delivery_days` is
        less than or equal to the record's `committed_days`, and false otherwise;
        delivering in exactly the committed number of days counts as on time."

        Design: Corner/calculations/precision_service_index_rounds_half_up_to_two_decimals
        """
        _world, local, haul = self._scanned_late_local_and_on_time_haul(api)

        assert_field_values(
            local,
            {
                "zone": 2,
                "committed_days": 4,
                "actual_delivery_days": 5,
                "on_time": False,
            },
        )
        assert_field_values(
            haul,
            {
                "zone": 8,
                "committed_days": 7,
                "actual_delivery_days": 7,
                "on_time": True,
            },
        )

    def test_the_two_indexes_round_half_up_to_seventy_one_forty_three_and_sixty_six_sixty_seven(
        self, api
    ):
        """The same two records, weighted by zone and then by volume.

        The contractual metric weights the haul more heavily: "each record
        contributes a weight determined by its `zone` — `zone` 1 weighs 1, `zone` 2
        weighs 2, `zone` 4 weighs 3, and `zone` 8 weighs 5 — the numerator is the sum
        of those weights over records whose `on_time` is true, the denominator is the
        sum of those weights over all records in the population, and the index is the
        numerator multiplied by one hundred, divided by the denominator, rounded half
        up to two decimal places." The volume-fair metric counts pieces instead: "the
        numerator is the sum of `piece_count` over records whose `on_time` is true,
        the denominator is the sum of `piece_count` over the whole population, and the
        result is again multiplied by one hundred and rounded half up to two decimal
        places."

        Design: Corner/calculations/precision_service_index_rounds_half_up_to_two_decimals
        """
        world, _local, _haul = self._scanned_late_local_and_on_time_haul(api)

        index = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        assert_service_level_index(
            index,
            record_count=2,
            on_time_count=1,
            zone_weighted_index=71.43,
            piece_weighted_index=66.67,
        )
        # 5 of 7 zone weights and 2000 of 3000 pieces: both quotients recur, so both
        # are settled by the same half-up rule at the second decimal place.
        assert index["zone_weighted_index"] != index["piece_weighted_index"]
