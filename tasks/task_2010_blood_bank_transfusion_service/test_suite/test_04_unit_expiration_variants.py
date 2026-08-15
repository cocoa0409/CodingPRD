"""Unit expiration at intake: fixed shelf clock vs derived-product clock."""
from test_helpers import (
    assert_same_instant,
    make_stock,
    receive_unit_descriptor,
    parse_instant,
)

TWO_FFP_UNITS = [
    receive_unit_descriptor("U-FROZEN", product_type="FFP", abo_type="A",
                            rh_type="NEG", volume_ml=250, donor_id="D-600",
                            lot_number="LOT-F"),
    receive_unit_descriptor("U-THAW", product_type="FFP", abo_type="A",
                            rh_type="NEG", volume_ml=250,
                            thawed_at="2026-08-10T06:00:00Z", donor_id="D-601",
                            lot_number="LOT-F"),
]


class TestUnitExpirationDualVariant:
    def test_ffp_fixed_shelf_variant(self, api):
        """PRD §3.2: "The fixed clock adds a class shelf life to `collected_at`:
        1,008 hours (forty-two days) for `RBC`, 840 hours (thirty-five days) for
        `WHOLE_BLOOD`, 120 hours (five days) for either platelet product, and 8,760
        hours (one year) for `FFP` or `CRYO`."

        Design: Difficulty/dual_variant_calc/ffp_unit_fixed_shelf_vs_thawed_clock
        """
        stock = make_stock(TWO_FFP_UNITS, release=False)
        frozen = stock["units"]["U-FROZEN"]
        assert_same_instant(frozen["expires_at"], "2027-08-01T00:00:00Z",
                            "FFP collected 2026-08-01T00:00:00Z + 8760h")

    def test_ffp_derived_clock_variant_diverges(self, api):
        """PRD §3.2: "The derived clock runs only when a thaw or pool timestamp is
        supplied: a thawed `FFP` unit expires twenty-four hours after `thawed_at`"
        PRD §3.2: "An `FFP` unit collected on 2026-08-01 and thawed on 2026-08-10
        at 06:00 therefore expires on 2026-08-11 at 06:00 even though its frozen
        shelf life runs into 2027 — same `collected_at`, different `expires_at`."

        Design: Difficulty/dual_variant_calc/ffp_unit_fixed_shelf_vs_thawed_clock
        """
        stock = make_stock(TWO_FFP_UNITS, release=False)
        frozen = stock["units"]["U-FROZEN"]
        thawed = stock["units"]["U-THAW"]
        assert_same_instant(thawed["expires_at"], "2026-08-11T06:00:00Z",
                            "thawed 2026-08-10T06:00:00Z + 24h beats the shelf clock")
        assert parse_instant(thawed["expires_at"]) != parse_instant(
            frozen["expires_at"]), (
            "identical collected_at still yields different expires_at"
        )
