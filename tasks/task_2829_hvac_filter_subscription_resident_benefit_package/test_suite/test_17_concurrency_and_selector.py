"""
The two optimistic-concurrency guards — one on a create, one on a child-driven
parent bump — and the eligibility half of the SKU selector together with its
creation-order tie-break.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_SUBSCRIPTION_VERSION,
    ERR_STALE_UNIT_VERSION,
)
from test_helpers.test_users import OPERATOR


class TestTransferCreateConcurrency:
    """The client's token is the parent subscription's version."""

    def test_a_stale_subscription_token_is_refused_and_consumed_by_nothing(self, api):
        """
        An unrelated write advances the subscription past the version the client
        recorded at activation, so the transfer create carrying the old token is
        refused with 412, creates no transfer record and bumps nothing — and once
        the fresh token is used the successful create advances the version past it
        again, so an immediate replay of the identical request is refused too.

        PRD §2.7: "If that value does not equal the subscription's current `version`, the request is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_subscription_version_on_transfer_create_returns_412
        """
        env = fx.build_base_env(api)
        destination = fx.create_unit(api, env.property_id, unit_label="A-201")
        stale_version = fx.read_subscription(api, env.subscription_id)["version"]
        assert stale_version == 2

        validate_success(
            api.create_shipment(
                env.subscription_id, f.shipment_payload("2026-10-19"), OPERATOR
            ),
            201,
        )
        fresh_version = fx.read_subscription(api, env.subscription_id)["version"]
        assert fresh_version == 3

        validate_error(
            api.create_subscription_transfer(
                f.transfer_payload(
                    env.subscription_id, destination["id"], "2026-08-05", stale_version
                ),
                OPERATOR,
            ),
            ERR_STALE_SUBSCRIPTION_VERSION,
            412,
        )
        _rows, meta = validate_paginated(api.list_subscription_transfers(OPERATOR))
        assert meta["total_count"] == 0
        refused = fx.read_subscription(api, env.subscription_id)
        assert refused["version"] == 3
        assert refused["status"] == "ACTIVE"

        opened = validate_success(
            api.create_subscription_transfer(
                f.transfer_payload(
                    env.subscription_id, destination["id"], "2026-08-05", fresh_version
                ),
                OPERATOR,
            ),
            201,
        )
        assert opened["status"] == "REQUESTED"
        pending = fx.read_subscription(api, env.subscription_id)
        assert pending["status"] == "TRANSFER_PENDING"
        assert pending["version"] == 4

        validate_error(
            api.create_subscription_transfer(
                f.transfer_payload(
                    env.subscription_id, destination["id"], "2026-08-05", fresh_version
                ),
                OPERATOR,
            ),
            ERR_STALE_SUBSCRIPTION_VERSION,
            412,
        )


class TestSizeCaptureConcurrency:
    """A different parent, a different token field, a different error code."""

    def test_a_unit_token_goes_stale_because_a_child_write_bumped_the_unit(self, api):
        """
        Activating a subscription flips the unit to OCCUPIED and bumps its version
        without the client touching the unit, so the capture carrying the recorded
        token is refused with its own 412 and writes nothing — and the capture that
        carries the current token remaps the live subscription onto the newly
        measured size.

        PRD §2.7: "If that value does not equal the unit's current `version`, the request is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_unit_version_on_size_capture_returns_412
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        sku_16 = fx.create_sku(api)
        sku_20 = fx.create_sku(
            api,
            sku_code="SKU-20251-M8",
            size_code="20x25x1",
            thickness_inches=1,
            merv_rating=8,
            unit_cost_cents=810,
            ship_weight_oz=17,
            pack_quantity=1,
        )
        prop = fx.create_property(api)
        unit = fx.create_unit(api, prop["id"], unit_label="A-101")
        assert validate_success(api.get_unit(unit["id"], OPERATOR))["version"] == 1
        stale_unit_version = 1

        fx.activate_property(api, prop["id"])
        resident = fx.create_resident(api)
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        subscription = fx.create_subscription(api, resident["id"], unit["id"])
        assert subscription["assigned_sku_id"] == sku_16["id"]
        fx.activate_subscription(api, subscription["id"])

        occupied = validate_success(api.get_unit(unit["id"], OPERATOR))
        assert occupied["status"] == "OCCUPIED"
        assert occupied["version"] == 2
        fresh_unit_version = occupied["version"]

        validate_error(
            api.capture_filter_size(
                unit["id"], f.size_capture_payload("20x25x1", stale_unit_version), OPERATOR
            ),
            ERR_STALE_UNIT_VERSION,
            412,
        )
        untouched = validate_success(api.get_unit(unit["id"], OPERATOR))
        assert untouched["actual_measured_size_code"] is None
        assert untouched["size_capture_count"] == 0
        assert untouched["version"] == 2
        assert (
            fx.read_subscription(api, subscription["id"])["assigned_sku_id"] == sku_16["id"]
        )

        # The PRD lists no FilterSizeCapture record type (§2.4 enumerates every
        # persisted type), so whether this call is a "create" answering 201 or a
        # unit mutation answering 200 is not pinned; any 2xx is accepted here and
        # the capture's observable effects are asserted below.
        get_success_data(
            api.capture_filter_size(
                unit["id"], f.size_capture_payload("20x25x1", fresh_unit_version), OPERATOR
            )
        )
        captured = validate_success(api.get_unit(unit["id"], OPERATOR))
        assert captured["actual_measured_size_code"] == "20x25x1"
        assert captured["size_capture_count"] == 1
        assert captured["version"] == 3
        assert (
            fx.read_subscription(api, subscription["id"])["assigned_sku_id"] == sku_20["id"]
        )


class TestSelectorEligibility:
    """Which catalog rows even enter the pool, and how an exact tie is broken."""

    def _five_sku_catalog(self, api):
        """
        Five 16x25x1 candidates registered on five successive clock days so that
        creation order is observable, plus three racks and three households.
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        s1 = fx.create_sku(
            api, sku_code="SKU-16251-S1", merv_rating=8, unit_cost_cents=700, pack_quantity=1
        )
        fx.set_clock(api, "2026-08-02T00:00:00Z")
        s2 = fx.create_sku(
            api, sku_code="SKU-16251-S2", merv_rating=8, unit_cost_cents=700, pack_quantity=1
        )
        fx.set_clock(api, "2026-08-03T00:00:00Z")
        s3 = fx.create_sku(
            api, sku_code="SKU-16251-S3", merv_rating=8, unit_cost_cents=300, pack_quantity=5
        )
        s4 = fx.create_sku(
            api, sku_code="SKU-16251-S4", merv_rating=11, unit_cost_cents=900, pack_quantity=1
        )
        s5 = fx.create_sku(
            api, sku_code="SKU-16251-S5", merv_rating=13, unit_cost_cents=500, pack_quantity=1
        )

        prop = fx.create_property(api)
        unit_two_slot = fx.create_unit(api, prop["id"], unit_label="A-101", filter_slot_count=2)
        fx.activate_property(api, prop["id"])
        unit_allergy = fx.create_unit(api, prop["id"], unit_label="A-201", filter_slot_count=2)
        unit_three_slot = fx.create_unit(
            api, prop["id"], unit_label="A-301", filter_slot_count=3
        )

        resident_x = fx.create_resident(
            api, full_name="Xan Diaz", email="xan.diaz@example.com", allergy_flag=False
        )
        resident_y = fx.create_resident(
            api, full_name="Yuki Tan", email="yuki.tan@example.com", allergy_flag=True
        )
        resident_z = fx.create_resident(
            api, full_name="Zoe Park", email="zoe.park@example.com", allergy_flag=False
        )
        fx.set_clock(api, "2026-08-05T00:00:00Z")

        def enrol(resident, unit):
            return validate_success(
                api.create_subscription(
                    f.subscription_payload(resident["id"], unit["id"]), OPERATOR
                ),
                201,
            )

        return {
            "s1": s1["id"],
            "s2": s2["id"],
            "s3": s3["id"],
            "s4": s4["id"],
            "s5": s5["id"],
            "x": enrol(resident_x, unit_two_slot),
            "y": enrol(resident_y, unit_allergy),
            "z": enrol(resident_z, unit_three_slot),
        }

    def test_the_pack_slack_and_the_merv_floor_decide_who_enters_the_pool(self, api):
        """
        On a two-slot rack the five-pack candidate is outside the slack and cannot
        win despite being cheapest; on a three-slot rack the same candidate sits
        exactly on the inclusive boundary and does win; and the allergy household's
        floor of 11 empties every MERV 8 row from the pool, handing the win to the
        dearer of the two remaining rows because filtration ranks before price.

        PRD §3.3: "From those two inputs the candidate set is every catalog entry whose `status` is `ACTIVE`, whose `size_code` matches the searched size exactly, whose `merv_rating` is greater than or equal to that floor, and whose `pack_quantity` is less than or equal to the unit's `filter_slot_count` plus a slack allowance of two packs."

        Design: Corner/cross_cutting_complexity_layers/selector_eligibility_predicate_and_created_at_tie_break
        """
        env = self._five_sku_catalog(api)

        assert env["x"]["assigned_sku_id"] == env["s1"]
        assert env["x"]["assigned_sku_id"] != env["s3"]
        assert env["z"]["assigned_sku_id"] == env["s3"]
        assert env["y"]["assigned_sku_id"] == env["s4"]
        assert env["y"]["assigned_sku_id"] != env["s5"]

    def test_an_exact_rank_tie_is_settled_by_creation_order(self, api):
        """
        Two candidates identical on both ranking keys — same MERV 8, same 700 cents
        — are separated only by when they were registered, and the earlier row wins
        on every household that can see both.

        PRD §3.3: "Candidates are then ranked cheapest-adequate-filtration-first: the lowest `merv_rating` wins, ties among equal ratings go to the lowest `unit_cost_cents`, and any remaining tie goes to the entry with the earliest `created_at`."

        Design: Corner/cross_cutting_complexity_layers/selector_eligibility_predicate_and_created_at_tie_break
        """
        env = self._five_sku_catalog(api)

        assert env["x"]["assigned_sku_id"] == env["s1"]
        assert env["x"]["assigned_sku_id"] != env["s2"]
        assert env["z"]["assigned_sku_id"] == env["s3"]
