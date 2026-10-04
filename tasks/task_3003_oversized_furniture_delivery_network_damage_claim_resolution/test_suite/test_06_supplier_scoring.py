"""Supplier scoring: rolling-vs-lifetime scorecard variants and the
chargeback-settle cascade into compliance score and automatic probation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    create_supplier,
    setup_determined_claim,
    setup_drop_ship_supplier,
    place_drop_ship_order,
    deliver_drop_ship_shipment,
    settle_claim_chargeback_for_shipment,
    api_client,
    TEST_USERS,
    make_supplier_rep_headers,
    SETUP_CLOCK,
)

ADMIN = TEST_USERS["network_admin_headers"]
CARRIER = TEST_USERS["carrier_rep_headers"]


class TestSupplierScorecardRollingVsLifetimeWindow:
    def _setup_six_shipments(self, api):
        """Drop-ship supplier with 6 closed shipments: S1 late, S2..S6 on
        time, plus one settled chargeback from a claim on S6.

        PRD §3.7 interplay drives the ordering: closing the late shipment
        while it is inside the 5-most-recent window would drop compliance to
        40.00, move the supplier to PROBATION, and remove drop-ship routing
        eligibility (§3.3 branch three requires an ACTIVE supplier) —
        bricking every later order. So the late shipment must be the OLDEST
        close under the PRD's window ordering (delivered_at DESC, ties by
        created_at ASC): it is delivered at the earliest clock instant of the
        six, and the five on-time shipments close at strictly later instants.
        All six orders are created at SETUP_CLOCK (2026-09-05), so PRD §3.3
        fixes every promised_ship_date at 2026-09-08; the late shipment
        departs on 2026-09-10 (past the promise) and its delivered_at stays
        the earliest close because delivered_at is stamped at delivery time.
        """
        refs = setup_drop_ship_supplier(supplier_code="SUP-D", zone="ZONE_MA")
        placed = [place_drop_ship_order(refs) for _ in range(6)]
        late_id = placed[0]["shipment"]["id"]                   # S1
        on_time_ids = [p["shipment"]["id"] for p in placed[1:]] # S2..S6
        rep = make_supplier_rep_headers(refs["supplier"]["id"])
        # S1 departs late but is delivered first, at the earliest instant.
        set_clock("2026-09-10T00:00:00Z")
        validate_success(api.depart_shipment(late_id, rep), 200)
        set_clock("2026-09-05T00:00:01Z")
        validate_success(api.deliver_shipment(late_id, rep), 200)
        # S2..S6 close on time at strictly later instants, pushing S1 out of
        # the rolling window; each close keeps compliance at 100.00.
        for i, sid in enumerate(on_time_ids, start=2):
            set_clock(f"2026-09-05T00:00:{i:02d}Z")
            deliver_drop_ship_shipment(refs, sid)
        set_clock(SETUP_CLOCK)
        # One CONCEALED claim on the most recent close (S6), determined
        # supplier-liable, settled.
        settle_claim_chargeback_for_shipment(
            refs, on_time_ids[-1], repair_cost_cents=5000, damage_pct=10
        )
        return refs

    def test_rolling_window_excludes_aged_out_late_shipment(self, api):
        """PRD §3.7: "The `on_time_ship_rate` is the percentage, rounded
        half-up to 2 decimal places, of the supplier's 5 most recently closed
        — that is, `DELIVERED` — drop-ship shipments that departed on time
        (`actual_ship_date` on or before `promised_ship_date`); the window is
        ordered by `delivered_at` descending with ties broken by the
        shipment's `created_at` ascending, and a supplier with no closed
        shipments in the window holds 100.00."

        Design: Difficulty/dual_variant_calc/supplier_scorecard_rolling_vs_lifetime_window
        """
        refs = self._setup_six_shipments(api)
        data = validate_success(
            api.get_supplier_scorecard(
                refs["supplier"]["id"], ADMIN, params={"window": "rolling"}
            )
        )
        assert data["on_time_ship_rate"] == pytest.approx(100.00, abs=0.001), (
            "rolling window of the 5 most recent closes excludes the late S1"
        )
        # chargeback_rate: 1 settled / 6 non-EXCEPTION shipments = 16.67
        # compliance: 0.60*100.00 + 0.40*(100 - 16.67) = 93.33
        assert data["chargeback_rate"] == pytest.approx(16.67, abs=0.001)
        assert data["compliance_score"] == pytest.approx(93.33, abs=0.001)

    def test_lifetime_window_counts_all_closed_shipments(self, api):
        """PRD §3.7: "The default window is `rolling` — the 5-shipment window
        above — while a `lifetime` window counts all closed drop-ship
        shipments; the two variants can therefore report different compliance
        scores for the same supplier once more than 5 shipments have closed,
        even with identical chargebacks."

        Design: Difficulty/dual_variant_calc/supplier_scorecard_rolling_vs_lifetime_window
        """
        refs = self._setup_six_shipments(api)
        data = validate_success(
            api.get_supplier_scorecard(
                refs["supplier"]["id"], ADMIN, params={"window": "lifetime"}
            )
        )
        # 5 on-time of 6 lifetime closes -> 83.33
        assert data["on_time_ship_rate"] == pytest.approx(83.33, abs=0.001)
        # 0.60*83.33 + 0.40*(100 - 16.67) = 83.33
        assert data["compliance_score"] == pytest.approx(83.33, abs=0.001)

    def test_stored_compliance_score_is_the_rolling_variant(self, api):
        """PRD §3.7: "The default window is `rolling` — the 5-shipment window
        above — while a `lifetime` window counts all closed drop-ship
        shipments"

        Design: Difficulty/dual_variant_calc/supplier_scorecard_rolling_vs_lifetime_window
        """
        refs = self._setup_six_shipments(api)
        supplier = validate_success(
            api.get_supplier(refs["supplier"]["id"], ADMIN)
        )
        assert supplier["compliance_score"] == pytest.approx(93.33, abs=0.001)


class TestChargebackSettleRecascadesSupplierStatus:
    def _setup_one_shipment_pending_chargeback(self, api):
        """Drop-ship supplier with exactly one delivered (on-time) shipment
        and one determined CONCEALED claim whose chargeback is PENDING."""
        refs = setup_drop_ship_supplier(supplier_code="SUP-D2", zone="ZONE_MA")
        placed = place_drop_ship_order(refs)
        deliver_drop_ship_shipment(refs, placed["shipment"]["id"])
        from test_helpers import open_claim
        claim = open_claim(
            placed["shipment"]["id"], refs["customer"], concealment="CONCEALED"
        )
        validate_success(
            api.inspect_damage_claim(
                claim["id"],
                {"damage_pct": 10, "is_structural": False,
                 "repair_cost_cents": 5000},
                TEST_USERS["hub_operator_headers"],
            ),
            200,
        )
        validate_success(
            api.determine_damage_claim(
                claim["id"], TEST_USERS["claims_adjuster_headers"]
            ),
            200,
        )
        from test_helpers import validate_paginated
        rows, _meta = validate_paginated(
            api.list_chargebacks(ADMIN, params={"damage_claim_id": claim["id"]})
        )
        refs["chargeback"] = rows[0]
        return refs

    def test_settle_recomputes_rate_and_score(self, api):
        """PRD §3.7: "The `chargeback_rate` is the percentage, also 2-decimal
        round-half-up, of `SETTLED` chargebacks attributed to the supplier
        over the count of the supplier's shipments whose state is not
        `EXCEPTION`; when the denominator is zero the rate is 0.00."
        PRD §3.7: "The `compliance_score` blends the two: 0.60 times the
        on-time rate plus 0.40 times the complement of the chargeback rate
        (100 minus the chargeback rate), with the sum consuming the
        already-rounded 2-decimal rates and itself rounded half-up to 2
        decimals."

        Design: Difficulty/transitive_cascade/chargeback_settle_recascades_supplier_status
        """
        refs = self._setup_one_shipment_pending_chargeback(api)
        settled = validate_success(
            api.settle_chargeback(refs["chargeback"]["id"], ADMIN), 200
        )
        assert settled["status"] == "SETTLED"
        supplier = validate_success(api.get_supplier(refs["supplier"]["id"], ADMIN))
        assert supplier["chargeback_rate"] == pytest.approx(100.00, abs=0.001), (
            "1 settled chargeback / 1 non-EXCEPTION shipment"
        )
        assert supplier["compliance_score"] == pytest.approx(60.00, abs=0.001), (
            "0.60 * 100.00 + 0.40 * (100 - 100.00)"
        )

    def test_settle_triggers_automatic_probation(self, api):
        """PRD §3.7: "After any recomputation, a supplier in `ACTIVE` whose
        score falls below 70.00 moves to `PROBATION`, which removes its
        drop-ship routing eligibility (routing branch three requires an
        `ACTIVE` supplier)."

        Design: Difficulty/transitive_cascade/chargeback_settle_recascades_supplier_status
        """
        refs = self._setup_one_shipment_pending_chargeback(api)
        validate_success(
            api.settle_chargeback(refs["chargeback"]["id"], ADMIN), 200
        )
        supplier = validate_success(api.get_supplier(refs["supplier"]["id"], ADMIN))
        assert supplier["status"] == "PROBATION", (
            "score 60.00 < 70.00 triggers the automatic ACTIVE → PROBATION transition"
        )


class TestScorecardDefaultsToRolling:
    def test_scorecard_defaults_to_rolling_window_when_param_omitted(self, api):
        """PRD §3.7: "For reporting, a scorecard view exposes
        `on_time_ship_rate`, `chargeback_rate`, and `compliance_score`
        together with the `window` applied. The default window is `rolling`"
        PRD §3.1: "A newly registered supplier starts with its `status` field
        at `ACTIVE`, a `compliance_score` of 100.00, an `on_time_ship_rate` of
        100.00, and a `chargeback_rate` of 0.00"

        Design: Corner/endpoints/scorecard_defaults_to_rolling_window_when_param_omitted
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        data = validate_success(api.get_supplier_scorecard(supplier["id"], ADMIN))
        assert data["window"] == "rolling"
        assert data["compliance_score"] == pytest.approx(100.00, abs=0.001)
        fresh = validate_success(api.get_supplier(supplier["id"], ADMIN))
        assert data["compliance_score"] == pytest.approx(
            fresh["compliance_score"], abs=0.001
        )
