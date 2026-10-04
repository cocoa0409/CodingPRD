"""Lot test threshold conventions: over-limit vs action-level semantics."""
from test_helpers import (
    create_supplier, create_received_lot, post_test, get_lot,
)


class TestMicroAndMoistureOverLimit:
    def test_micro_and_moisture_at_limit_pass_over_limit_fails(self, api):
        """PRD §3.2: "A `MICRO` test, measured in colony-forming units per
        gram, fails only when `measured_value` is strictly greater than
        100000 — a reading of exactly 100000 is a `PASS`. A `MOISTURE` test,
        measured in percent, fails only when `measured_value` is strictly
        greater than 12.0 — exactly 12.0 is a `PASS`." PRD §3.2: "the moment
        an `ADULTERANT_SCREEN` test computes `FAIL`, the lot is
        auto-quarantined" (only that type does).

        At-limit values PASS, one unit over FAILs, and non-adulterant FAILs
        never auto-quarantine — the lot stays IN_TEST.

        Design: Corner/calculations/micro_and_moisture_at_limit_pass_over_limit_fails
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="OREGANO",
                                  origin_region="Lesvos", quantity_kg=40,
                                  flavor_intensity_units=60.0,
                                  moisture_pct=9.0, cost_per_kg_cents=150)
        assert post_test(lot["id"], "MICRO", 100000)["result"] == "PASS"
        assert post_test(lot["id"], "MICRO", 100001)["result"] == "FAIL"
        assert post_test(lot["id"], "MOISTURE", 12.0)["result"] == "PASS"
        assert post_test(lot["id"], "MOISTURE", 12.01)["result"] == "FAIL"
        assert get_lot(lot["id"])["status"] == "IN_TEST"


class TestPesticideActionLevel:
    def test_pesticide_action_level_at_limit_fails(self, api):
        """PRD §3.2: "A `PESTICIDE` test, also in parts per million, fails
        when `measured_value` is greater than or equal to 0.10, so exactly
        0.10 is a `FAIL`."

        0.09 ppm PASSes; exactly 0.10 ppm FAILs under >= action-level
        semantics.

        Design: Corner/calculations/pesticide_action_level_at_limit_fails
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="CUMIN",
                                  origin_region="Aleppo", quantity_kg=40,
                                  flavor_intensity_units=60.0,
                                  moisture_pct=9.0, cost_per_kg_cents=150)
        assert post_test(lot["id"], "PESTICIDE", 0.09)["result"] == "PASS"
        assert post_test(lot["id"], "PESTICIDE", 0.10)["result"] == "FAIL"
