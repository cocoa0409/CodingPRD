"""Par-level policies, physical/prospective posture ladders, wastage rates."""
from test_helpers import (
    ApiErrorId,
    assert_par_level_policy,
    assert_posture_read,
    create_draft_order,
    find_unit_by_number,
    get_policy,
    get_posture,
    get_success_data,
    list_wastage,
    make_policy,
    make_stock,
    make_supplier,
    receive_order_units,
    receive_unit_descriptor,
    receive_units,
    release_unit,
    run_sweep,
    set_clock,
    submit_order,
    acknowledge_order,
    supplier_order_line,
    update_par_level_policy_payload,
    validate_error,
    validate_success,
    SUPERVISOR,
    COORDINATOR,
    TECH_A,
    QO_1,
    api_client,
)


def _stock_units(count, numbers, product_type="RBC", abo_type="O", rh_type="NEG"):
    descriptors = [
        receive_unit_descriptor(number, product_type=product_type,
                                abo_type=abo_type, rh_type=rh_type,
                                donor_id="D-8%03d" % i)
        for i, number in enumerate(numbers)
    ]
    return make_stock(descriptors, release=True)


class TestPhysicalVsProspectivePosture:
    def _setup_dual_posture_bucket(self, api):
        """RBC:O:NEG policy (watch 6, shortage 4, critical 2); one usable unit
        on the shelf; six inbound units acknowledged within the 24h horizon."""
        set_clock("2026-08-10T09:00:00Z")
        supplier = make_supplier()
        policy = make_policy(watch_threshold=6, shortage_threshold=4,
                             critical_threshold=2)
        _order1, units = receive_order_units(
            supplier["id"], [supplier_order_line(quantity=1)],
            [receive_unit_descriptor("U-100")])
        release_unit(units["U-100"]["id"])
        order2 = create_draft_order(
            supplier["id"], [supplier_order_line(quantity=6)],
            expected_delivery_at="2026-08-10T20:00:00Z")
        submit_order(order2["id"])
        acknowledge_order(order2["id"])
        return policy

    def test_bucket_physical_posture_critical_side(self, api):
        """PRD §2.10: "If that count is at or below the bucket's
        `critical_threshold` the posture is `CRITICAL`"
        PRD §2.10: "The **physical posture** counts only stock on the shelf, as
        above, and it is the flavor that gates order verification."

        Design: Difficulty/dual_variant_calc/bucket_physical_vs_prospective_posture
        """
        policy = self._setup_dual_posture_bucket(api)
        posture = get_posture(policy["id"])
        assert_posture_read(posture)
        assert posture["usable_units"] == 1
        assert posture["physical_posture"] == "CRITICAL", (
            "one usable unit sits at-or-below the critical threshold of 2"
        )

    def test_bucket_prospective_posture_normal_side(self, api):
        """PRD §2.10: "The **prospective posture** adds inbound supply: undelivered
        line remainders (ordered quantity minus received quantity) on supplier
        orders in `SUBMITTED`, `ACKNOWLEDGED`, or `RECEIVING` status whose
        `expected_delivery_at` is set and falls within the next twenty-four hours,
        counted for lines matching the bucket."
        PRD §2.10: "a bucket with one usable unit and four inbound units can be
        physically `CRITICAL` yet prospectively `NORMAL` on identical shelf data."

        Design: Difficulty/dual_variant_calc/bucket_physical_vs_prospective_posture
        """
        policy = self._setup_dual_posture_bucket(api)
        posture = get_posture(policy["id"])
        assert posture["inbound_units_24h"] == 6, (
            "the acknowledged order due in 11h counts its full remainder"
        )
        assert posture["prospective_posture"] == "NORMAL", (
            "1 usable + 6 inbound = 7 clears the watch threshold of 6"
        )
        assert posture["physical_posture"] != posture["prospective_posture"], (
            "the two variants diverge on identical on-shelf stock"
        )


class TestPostureBoundaryInclusive:
    def _setup_boundary_bucket(self, api):
        set_clock("2026-08-10T09:00:00Z")
        supplier = make_supplier()
        policy = make_policy(watch_threshold=6, shortage_threshold=4,
                             critical_threshold=2)
        order = create_draft_order(supplier["id"], [supplier_order_line(quantity=3)])
        submit_order(order["id"])
        acknowledge_order(order["id"])
        return policy, order

    def test_posture_critical_threshold_inclusive_at(self, api):
        """PRD §2.10: "The boundary is inclusive — a count exactly equal to the
        critical threshold grades `CRITICAL`."

        Design: Difficulty/boundary_precision_check/posture_critical_threshold_inclusive
        """
        policy, order = self._setup_boundary_bucket(api)

        receive_units(order["id"], [receive_unit_descriptor("U-601",
                                                            donor_id="D-840"),
                                    receive_unit_descriptor("U-602",
                                                            donor_id="D-841")])
        release_unit(find_unit_by_number(order["id"], "U-601")["id"])
        release_unit(find_unit_by_number(order["id"], "U-602")["id"])

        posture = get_posture(policy["id"])
        assert posture["usable_units"] == 2
        assert posture["physical_posture"] == "CRITICAL", (
            "usable == critical_threshold grades CRITICAL (inclusive <=)"
        )

    def test_posture_one_above_critical_reads_shortage(self, api):
        """PRD §2.10: "otherwise, if at or below the `shortage_threshold`,
        `SHORTAGE`"
        PRD §3.2: "when every line stands fully received the order auto-closes to
        `CLOSED` within the same call."

        Design: Difficulty/boundary_precision_check/posture_critical_threshold_inclusive
        """
        policy, order = self._setup_boundary_bucket(api)

        receive_units(order["id"], [receive_unit_descriptor("U-601",
                                                            donor_id="D-840"),
                                    receive_unit_descriptor("U-602",
                                                            donor_id="D-841")])
        release_unit(find_unit_by_number(order["id"], "U-601")["id"])
        release_unit(find_unit_by_number(order["id"], "U-602")["id"])
        order = receive_units(order["id"], [receive_unit_descriptor("U-603",
                                                                    donor_id="D-842")])
        assert order["status"] == "CLOSED", "the final receipt auto-closes the order"
        release_unit(find_unit_by_number(order["id"], "U-603")["id"])

        posture = get_posture(policy["id"])
        assert posture["usable_units"] == 3
        assert posture["physical_posture"] == "SHORTAGE", (
            "3 > critical 2 escapes CRITICAL; 3 <= shortage 4 is SHORTAGE"
        )


class TestWastageRateEdgeCases:
    def test_wastage_rate_empty_denominator_does_not_error(self, api):
        """PRD §3.8: "the numerator is the sum of `quantity_units` across the
        bucket's records in the window, the denominator is the count of the
        bucket's blood units created in the window, and the rate is their quotient
        rounded half-up to four decimal places — or exactly 0.0000 when nothing was
        received."
        PRD §2.4: "The sweep's response tallies its work in five counters:
        `ts_expired_count`, `crossmatches_expired_count`, `units_expired_count`,
        `coolers_restocked_count`, and `orders_held_count`."

        Design: Difficulty/boundary_precision_check/wastage_rate_empty_denominator
        """
        stock = make_stock([receive_unit_descriptor(
            "U-801", product_type="PLT_POOL", volume_ml=200,
            collected_at="2026-08-06T00:00:00Z", donor_id="D-860",
            lot_number="LOT-8D")], release=False)
        unit = stock["units"]["U-801"]
        # PLT_POOL expires at collected + 120h = 2026-08-11T00:00:00Z; jump past it
        # AND past the 30-day window edge so the receipt falls outside the window.
        set_clock("2026-09-15T00:00:00Z")
        sweep = run_sweep()
        assert sweep["units_expired_count"] == 1


        records = list_wastage({"unit_id": unit["id"]})
        assert len(records) == 1 and records[0]["reason"] == "EXPIRED"

        summary = validate_success(api.get_wastage_summary(
            SUPERVISOR, params={"product_type": "PLT_POOL"}))
        for key in ("as_of_utc", "window_days", "buckets"):
            assert key in summary, f"the wastage summary carries {key}"
        assert summary["window_days"] == 30, "the default window is thirty days"
        assert isinstance(summary["buckets"], list), (
            "an empty denominator yields a normal summary, not an error"
        )

    def test_wastage_summary_window_days_override_echoed(self, api):
        """PRD §3.8: "A computed wastage summary endpoint reports `as_of_utc`, the
        `window_days` in effect (an optional query parameter overriding the default
        thirty days), and a `buckets` array of per-bucket rates, optionally
        narrowed by `product_type`."

        Design: Difficulty/boundary_precision_check/wastage_rate_empty_denominator
        """
        make_stock([receive_unit_descriptor(
            "U-801", product_type="PLT_POOL", volume_ml=200,
            collected_at="2026-08-06T00:00:00Z", donor_id="D-860",
            lot_number="LOT-8D")], release=False)
        set_clock("2026-09-15T00:00:00Z")
        run_sweep()

        summary = validate_success(api.get_wastage_summary(
            SUPERVISOR, params={"product_type": "PLT_POOL", "window_days": 7}))
        assert summary["window_days"] == 7, (
            "the override is echoed as the window in effect"
        )


class TestPostureReads:
    def test_posture_read_shape_and_normal_ladder(self, api):
        """PRD §3.8: "The posture read for a bucket returns its `product_type`,
        `abo_type`, and `rh_type`, the current `usable_units` count, the
        `inbound_units_24h` count (undelivered line remainders due within the next
        day on `SUBMITTED`, `ACKNOWLEDGED`, or `RECEIVING` orders), the
        `physical_posture` and `prospective_posture` per the ladders of §2.10, and
        the `excessive_wastage` flag."

        Design: Corner/endpoints/posture_read_shape_and_normal_ladder
        """
        set_clock("2026-08-10T09:00:00Z")
        policy = make_policy(watch_threshold=0, shortage_threshold=0,
                             critical_threshold=0)
        make_stock([receive_unit_descriptor("U-100")])
        posture = get_posture(policy["id"])
        assert_posture_read(posture)
        assert posture["usable_units"] == 1
        assert posture["inbound_units_24h"] == 0
        assert posture["physical_posture"] == "NORMAL"
        assert posture["prospective_posture"] == "NORMAL"
        assert posture["excessive_wastage"] is False

    def test_posture_normal_when_stock_above_watch(self, api):
        """PRD §2.10: "otherwise, if at or below the `watch_threshold`, `WATCH`;
        otherwise `NORMAL`."

        Design: Corner/calculations/posture_normal_when_stock_above_watch
        """
        set_clock("2026-08-10T09:00:00Z")
        policy = make_policy(watch_threshold=1, shortage_threshold=0,
                             critical_threshold=0)
        _stock_units(2, ["U-100", "U-101"])
        posture = get_posture(policy["id"])
        assert posture["usable_units"] == 2
        assert posture["physical_posture"] == "NORMAL", (
            "2 > watch 1 clears every rung of the ladder"
        )

    def test_prospective_inbound_beyond_24h_excluded(self, api):
        """PRD §2.10: "undelivered line remainders (ordered quantity minus received
        quantity) on supplier orders in `SUBMITTED`, `ACKNOWLEDGED`, or `RECEIVING`
        status whose `expected_delivery_at` is set and falls within the next
        twenty-four hours, counted for lines matching the bucket."

        Design: Corner/calculations/prospective_inbound_beyond_24h_excluded
        """
        set_clock("2026-08-10T09:00:00Z")
        supplier = make_supplier()
        policy = make_policy(watch_threshold=6, shortage_threshold=4,
                             critical_threshold=2)
        order = create_draft_order(
            supplier["id"], [supplier_order_line(quantity=6)],
            expected_delivery_at="2026-08-12T09:00:00Z")
        submit_order(order["id"])
        acknowledge_order(order["id"])

        posture = get_posture(policy["id"])
        assert posture["inbound_units_24h"] == 0, (
            "a delivery 48h out lies beyond the 24h horizon"
        )
        assert posture["physical_posture"] == "CRITICAL"
        assert posture["prospective_posture"] == "CRITICAL", (
            "no inbound rescue when the horizon excludes the order"
        )

    def test_wastage_rate_rounding_and_excessive_flag(self, api):
        """PRD §3.8: "the rate is their quotient rounded half-up to four decimal
        places — or exactly 0.0000 when nothing was received."
        PRD §3.8: "A bucket whose rate reaches or exceeds 0.05 — the boundary is
        inclusive — is flagged `excessive_wastage`"

        Design: Corner/calculations/wastage_rate_rounding_4dp_and_excessive_flag
        """
        set_clock("2026-08-10T09:00:00Z")
        policy = make_policy(watch_threshold=99, shortage_threshold=50,
                             critical_threshold=10)
        stock = make_stock([receive_unit_descriptor("U-100", donor_id="D-500"),
                            receive_unit_descriptor("U-101", donor_id="D-501"),
                            receive_unit_descriptor("U-102", donor_id="D-502")],
                           release=False)
        get_success_data(api_client.discard_unit(stock["units"]["U-100"]["id"],
                                                 {"note": "qc sample lost"},
                                                 SUPERVISOR))
        # 1 wasted / 3 received in-window -> 0.3333 (half-up at 4dp) >= 0.05.
        posture = get_posture(policy["id"])
        assert posture["excessive_wastage"] is True, (
            "a 1/3 in-window wastage rate crosses the inclusive 0.05 flag"
        )
        summary = validate_success(api.get_wastage_summary(
            QO_1, params={"product_type": "RBC"}))
        for key in ("as_of_utc", "window_days", "buckets"):
            assert key in summary


class TestPolicyLifecycle:
    def test_policy_threshold_order_invalid_returns_400(self, api):
        """PRD §3.8: "each at least zero and satisfying the ordering that
        `watch_threshold` must be at least `shortage_threshold`, which must be at
        least `critical_threshold` — violations rejected as
        `ERR_THRESHOLD_ORDER_INVALID` (HTTP 400)"

        Design: Corner/entities/policy_threshold_order_invalid_returns_400
        """
        resp = api.create_par_level_policy(
            {"product_type": "RBC", "abo_type": "O", "rh_type": "NEG",
             "watch_threshold": 1, "shortage_threshold": 3, "critical_threshold": 2},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_THRESHOLD_ORDER_INVALID)

    def test_duplicate_active_policy_returns_409(self, api):
        """PRD §3.8: "At most one `ACTIVE` policy may exist per bucket — a
        duplicate meets `ERR_POLICY_BUCKET_DUPLICATE` (HTTP 409)"
        PRD §3.8: "Retiring moves the policy to terminal `RETIRED`; while no
        `ACTIVE` policy exists for a bucket, the bucket is ungated and treated as
        `NORMAL` everywhere."

        Design: Corner/validations/duplicate_active_policy_returns_409
        """
        policy = make_policy(watch_threshold=6, shortage_threshold=4,
                             critical_threshold=2)
        resp = api.create_par_level_policy(
            {"product_type": "RBC", "abo_type": "O", "rh_type": "NEG",
             "watch_threshold": 9, "shortage_threshold": 9,
             "critical_threshold": 9},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_POLICY_BUCKET_DUPLICATE)

        retired = validate_success(api.retire_policy(policy["id"], SUPERVISOR))
        assert retired["status"] == "RETIRED"
        replacement = validate_success(api.create_par_level_policy(
            {"product_type": "RBC", "abo_type": "O", "rh_type": "NEG",
             "watch_threshold": 9, "shortage_threshold": 9,
             "critical_threshold": 9},
            SUPERVISOR), 201)
        assert replacement["status"] == "ACTIVE", (
            "retiring the first policy frees the bucket"
        )

    def test_occ_policy_update_stale_version(self, api):
        """PRD §2.8: "Updating a par-level policy requires
        `expected_policy_version`, the policy's `version` as last observed; if
        another supervisor has tightened or loosened the same bucket's thresholds
        in the meantime, the update is rejected with `ERR_STALE_VERSION` (HTTP 412)
        so a stale threshold set cannot silently overwrite a newer configuration."
        PRD §3.8: "incrementing the policy's `version` by one, and recomputing
        posture."

        Design: Corner/cross_cutting_layers/occ_policy_update_stale_version
        """
        policy = make_policy(watch_threshold=6, shortage_threshold=4,
                             critical_threshold=2)
        stale = policy["version"]
        updated = validate_success(api.update_par_level_policy(
            policy["id"],
            update_par_level_policy_payload(stale, watch_threshold=8),
            SUPERVISOR))
        assert updated["version"] == stale + 1
        assert updated["watch_threshold"] == 8

        resp = api.update_par_level_policy(
            policy["id"],
            update_par_level_policy_payload(stale, watch_threshold=9),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_policy(policy["id"])["watch_threshold"] == 8, (
            "the stale write changed nothing"
        )
