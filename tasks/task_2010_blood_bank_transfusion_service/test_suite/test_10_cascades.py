"""Transitive cascades: recall quarantine, T&S-expiry sweep, supplier suspension."""
from test_helpers import (
    ApiErrorId,
    expire_patient_typing,
    get_crossmatch,
    get_order,
    get_posture,
    get_success_data,
    get_unit,
    identify_recall,
    make_compatible_crossmatch,
    make_donor_recall,
    make_policy,
    make_stock,
    make_typed_patient,
    make_verified_order,
    quarantine_recall,
    receive_unit_descriptor,
    run_sweep,
    set_clock,
    setup_order_with_reserved_units,
    validate_success,
    SUPERVISOR,
    TECH_A,
    api_client,
)

TS1_EXPIRY = "2026-08-13T08:00:00Z"


class TestRecallQuarantineCascade:
    def _setup_donor_recall_identified(self, api):
        stock = make_stock([
            receive_unit_descriptor("U-201", donor_id="D-900", lot_number="LOT-9"),
            receive_unit_descriptor("U-202", donor_id="D-900", lot_number="LOT-9"),
        ])
        patient, _ts = make_typed_patient(mrn="M-9013", full_name="Pat Thirteen",
                                          date_of_birth="1975-03-03")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        xm = make_compatible_crossmatch(order["id"], stock["units"]["U-202"]["id"])
        recall = make_donor_recall("D-900",
                                   reason="donor post-donation hepatitis marker")
        recall = identify_recall(recall["id"])
        return stock, order, xm, recall

    def test_execute_quarantine_holds_implicated_units(self, api):
        """PRD §3.7: "Executing quarantine — from `UNITS_IDENTIFIED` only
        (`ERR_RECALL_NOT_QUARANTINABLE`) — moves every implicated unit in
        `QUARANTINED`, `AVAILABLE`, or `RESERVED` to `QUARANTINED_HOLD` with
        `hold_reason` of `RECALL` and its prior state in `hold_origin_state`"
        PRD §3.7: "The tally lands in `quarantined_count` and the case moves to
        `QUARANTINE_COMPLETE`."

        Design: Difficulty/transitive_cascade/recall_quarantine_cascade
        """
        stock, _order, _xm, recall = self._setup_donor_recall_identified(api)
        recall = quarantine_recall(recall["id"])
        assert recall["status"] == "QUARANTINE_COMPLETE"
        assert recall["quarantined_count"] == 2

        u1 = get_unit(stock["units"]["U-201"]["id"])
        assert u1["status"] == "QUARANTINED_HOLD"
        assert u1["hold_origin_state"] == "AVAILABLE"
        assert u1["hold_reason"] == "RECALL"
        u2 = get_unit(stock["units"]["U-202"]["id"])
        assert u2["status"] == "QUARANTINED_HOLD"
        assert u2["hold_origin_state"] == "RESERVED"

    def test_execute_quarantine_cancels_crossmatch_and_reverts_order(self, api):
        """PRD §3.7: "each `RESERVED` unit's `COMPATIBLE` crossmatch is cancelled
        and its order recomputed (a `READY` order whose fulfillment drops below
        `units_requested` reverts to `AWAITING_CROSSMATCH`)."

        Design: Difficulty/transitive_cascade/recall_quarantine_cascade
        """
        _stock, order, xm, recall = self._setup_donor_recall_identified(api)
        assert get_order(order["id"])["status"] == "READY"
        quarantine_recall(recall["id"])

        assert get_crossmatch(xm["id"])["status"] == "CANCELLED", (
            "the hold on the reserved unit cancels its crossmatch"
        )
        assert get_order(order["id"])["status"] == "AWAITING_CROSSMATCH", (
            "fulfillment fell below units_requested"
        )


class TestTsExpirySweepCascade:
    def _setup_reserved_ready(self, api):
        set_clock("2026-08-10T09:00:00Z")
        policy = make_policy(watch_threshold=3, shortage_threshold=1,
                             critical_threshold=0)
        ctx = setup_order_with_reserved_units(mrn="M-9014",
                                              unit_numbers=["U-100"], clock=None)
        return policy, ctx

    def test_sweep_expiry_chain_states(self, api):
        """PRD §2.4: "The sweep's response tallies its work in five counters:
        `ts_expired_count`, `crossmatches_expired_count`, `units_expired_count`,
        `coolers_restocked_count`, and `orders_held_count`."
        PRD §3.1: "every `COMPATIBLE` crossmatch on the patient's orders moves to
        `EXPIRED`, each releasing its `RESERVED` unit back to `AVAILABLE`"

        Design: Difficulty/transitive_cascade/ts_expiry_sweep_cascade
        """
        _policy, ctx = self._setup_reserved_ready(api)
        set_clock(TS1_EXPIRY)
        sweep = run_sweep()
        assert sweep["ts_expired_count"] == 1
        assert sweep["crossmatches_expired_count"] == 1, (
            "reserved_until equals the T&S expiry, so both rules fire at once"
        )
        assert sweep["orders_held_count"] == 1

        assert get_success_data(api.get_type_and_screen(ctx["ts"]["id"], TECH_A)
                              )["status"] == "EXPIRED"
        assert get_crossmatch(ctx["crossmatches"]["U-100"]["id"])[
            "status"] == "EXPIRED"
        assert get_unit(ctx["units"]["U-100"]["id"])["status"] == "AVAILABLE", (
            "the expired reservation releases its unit"
        )
        assert get_order(ctx["order"]["id"])["status"] == "ON_HOLD"

    def test_sweep_expiry_recomputes_bucket_posture(self, api):
        """PRD §2.10: "If that count is at or below the bucket's
        `critical_threshold` the posture is `CRITICAL`; otherwise, if at or below
        the `shortage_threshold`, `SHORTAGE`"
        PRD §3.1: "every `COMPATIBLE` crossmatch on the patient's orders moves to
        `EXPIRED`, each releasing its `RESERVED` unit back to `AVAILABLE`"

        Design: Difficulty/transitive_cascade/ts_expiry_sweep_cascade
        """
        policy, ctx = self._setup_reserved_ready(api)
        before = get_posture(policy["id"])
        assert before["usable_units"] == 0, "the only unit sits RESERVED"
        assert before["physical_posture"] == "CRITICAL", "0 <= critical 0"

        set_clock(TS1_EXPIRY)
        run_sweep()
        after = get_posture(policy["id"])
        assert after["usable_units"] == 1, "the released unit is usable again"
        assert after["physical_posture"] == "SHORTAGE", "1 <= shortage 1"


class TestSupplierSuspensionCascade:
    def _setup_supplier_with_reserved_unit(self, api):
        stock = make_stock([
            receive_unit_descriptor("U-301", donor_id="D-700", lot_number="LOT-7"),
            receive_unit_descriptor("U-302", donor_id="D-701", lot_number="LOT-7"),
        ])
        patient, _ts = make_typed_patient(mrn="M-9015", full_name="Pat Fifteen",
                                          date_of_birth="1971-09-19")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        xm = make_compatible_crossmatch(order["id"], stock["units"]["U-302"]["id"])
        return stock, order, xm

    def test_suspend_holds_units_and_cancels_crossmatch(self, api):
        """PRD §3.2: "Suspending an `ACTIVE` supplier — any other from-state draws
        `ERR_SUPPLIER_SUSPENDED` — stamps `suspended_at`, records the supplied
        `reason` in `suspend_reason`, moves the supplier to `SUSPENDED`, and
        cascade-holds every one of its blood units in `QUARANTINED`, `AVAILABLE`,
        or `RESERVED`: each goes to `QUARANTINED_HOLD` with `hold_reason` of
        `SUPPLIER_SUSPENSION` and its prior state preserved in `hold_origin_state`."

        Design: Difficulty/transitive_cascade/supplier_suspension_cascade
        """
        stock, order, xm = self._setup_supplier_with_reserved_unit(api)
        supplier = validate_success(api.suspend_supplier(
            stock["supplier"]["id"], {"reason": "FDA audit hold"}, SUPERVISOR))
        assert supplier["status"] == "SUSPENDED"

        u1 = get_unit(stock["units"]["U-301"]["id"])
        assert u1["status"] == "QUARANTINED_HOLD"
        assert u1["hold_origin_state"] == "AVAILABLE"
        assert u1["hold_reason"] == "SUPPLIER_SUSPENSION"
        u2 = get_unit(stock["units"]["U-302"]["id"])
        assert u2["status"] == "QUARANTINED_HOLD"
        assert u2["hold_origin_state"] == "RESERVED"
        assert get_crossmatch(xm["id"])["status"] == "CANCELLED"
        assert get_order(order["id"])["status"] == "AWAITING_CROSSMATCH"

    def test_reinstate_releases_holds_but_resurrects_nothing(self, api):
        """PRD §3.2: "Reinstating a `SUSPENDED` supplier (again, any other
        from-state draws `ERR_SUPPLIER_SUSPENDED`) releases exactly those holds:
        every `QUARANTINED_HOLD` unit whose `hold_reason` is `SUPPLIER_SUSPENSION`
        returns to `AVAILABLE` — always `AVAILABLE`, even for a unit that was
        `RESERVED` when held, because its crossmatch was already cancelled at hold
        time — the hold origin is cleared, `suspended_at` returns to null, and
        bucket postures are recomputed."

        Design: Difficulty/transitive_cascade/supplier_suspension_cascade
        """
        stock, order, xm = self._setup_supplier_with_reserved_unit(api)
        get_success_data(api.suspend_supplier(stock["supplier"]["id"],
                                              {"reason": "FDA audit hold"},
                                              SUPERVISOR))
        supplier = validate_success(
            api.reinstate_supplier(stock["supplier"]["id"], SUPERVISOR))
        assert supplier["status"] == "ACTIVE"
        assert supplier["suspended_at"] is None

        assert get_unit(stock["units"]["U-301"]["id"])["status"] == "AVAILABLE"
        assert get_unit(stock["units"]["U-302"]["id"])["status"] == "AVAILABLE", (
            "even the unit held from RESERVED lands on AVAILABLE"
        )
        assert get_crossmatch(xm["id"])["status"] == "CANCELLED", (
            "reinstatement resurrects nothing downstream"
        )
        assert get_order(order["id"])["status"] == "AWAITING_CROSSMATCH"
