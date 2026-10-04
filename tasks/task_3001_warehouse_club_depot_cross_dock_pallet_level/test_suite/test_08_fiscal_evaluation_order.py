"""Fiscal evaluation order: unload-fee tiers combined with the repeat-offender
chargeback multiplier for a vendor with an existing confirmed history."""
from test_helpers import (
    book_appointment,
    check_in_appointment,
    create_active_item,
    create_depot,
    receive_pallet,
    setup_vendor_with_confirmed_no_shows,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DM, RO


def _setup_repeat_offender_with_big_load(api, regional_ops_headers):
    """Vendor carrying exactly 2 CONFIRMED NO_SHOW chargebacks assessed 2026-09-01
    (repeat multiplier 1.5); a 26-pallet appointment checked in on 2026-09-04 with
    26 pallets received; and a 1-pallet appointment booked for 2026-09-05 that will
    no-show. Clock ends at 2026-09-04T08:05."""
    region, vendor, depot, confirmed = setup_vendor_with_confirmed_no_shows(
        2, delivery_date="2026-09-01", rollover_to="2026-09-02T00:00:01Z"
    )
    item = create_active_item(vendor["id"])
    appt_big = book_appointment(depot["id"], vendor["id"], "2026-09-04",
                                start_time="08:00", end_time="08:30", pallet_count=26)
    appt_ns = book_appointment(depot["id"], vendor["id"], "2026-09-05",
                               start_time="08:00", end_time="08:30", pallet_count=1)
    api.set_clock("2026-09-04T08:05:00Z", regional_ops_headers)
    check_in_appointment(appt_big["id"])
    for _ in range(26):
        receive_pallet(appt_big["id"], item["id"], 480)
    return vendor, appt_big, appt_ns


class TestUnloadFeeWithRepeatHistory:
    def test_unload_fee_tier_applies_on_booked_count_with_repeat_history(self, api, regional_ops_headers):
        """PRD §3.2: "the base fee is the booked `pallet_count` multiplied by a per-pallet fee of 4500 cents,
        then scaled by a tier multiplier — 1.00 when the booked count is at most 10
        pallets, 1.15 when it is more than 10 and at most 25, and 1.30 when it exceeds
        25 — with the product rounded half-up to whole cents."
        PRD §3.6: "The assessment amount is computed in a pinned order: base by reason first,
        then per-extra-pallet penalty, then the repeat-offender multiplier."

        Design: Difficulty/combinatorial_formula/unload_fee_tier_crossing_with_repeat_offender_chargeback
        """
        vendor, appt_big, appt_ns = _setup_repeat_offender_with_big_load(api, regional_ops_headers)
        completed = validate_success(api.complete_appointment(appt_big["id"], DM))
        # 26 pallets * 4500 = 117000; above the 25-pallet tier the multiplier is
        # 1.30 -> 152100. The vendor's confirmed history does not touch the fee.
        assert completed["unload_fee_cents"] == 152100, (
            f"26 * 4500 * 1.30 = 152100, got {completed['unload_fee_cents']}"
        )
        # Received count equals the booked count: no over-pallet chargeback.
        assert completed["chargeback_cents"] == 0

    def test_no_show_chargeback_uses_repeat_multiplier(self, api, regional_ops_headers):
        """PRD §3.6: "The subtotal is then multiplied by a repeat multiplier of 1 plus one-quarter times the
        vendor's count of `CONFIRMED` chargebacks assessed within the trailing 90 days
        inclusive, with that count capped at 4 priors; the result is rounded half-up to
        whole cents."
        PRD §3.6: "The base is 15000 cents for `LATE_CHECKIN`, 75000 cents for `NO_SHOW`, and 25000 cents
        for `OVER_PALLET_COUNT`."

        Design: Difficulty/combinatorial_formula/unload_fee_tier_crossing_with_repeat_offender_chargeback
        """
        vendor, appt_big, appt_ns = _setup_repeat_offender_with_big_load(api, regional_ops_headers)
        validate_success(api.complete_appointment(appt_big["id"], DM))
        # Roll over past the 2026-09-05 appointment with no check-in.
        api.set_clock("2026-09-06T00:00:01Z", regional_ops_headers)
        cbs, _ = validate_paginated(
            api.list_chargebacks(DM, params={"appointment_id": appt_ns["id"]})
        )
        assert len(cbs) == 1
        assert cbs[0]["reason"] == "NO_SHOW"
        # 75000 * (1 + 2 * 0.25) = 112500: the two prior CONFIRMED chargebacks
        # lift the repeat multiplier to 1.5.
        assert cbs[0]["amount_cents"] == 112500, (
            f"NO_SHOW base 75000 * repeat multiplier 1.5, got {cbs[0]['amount_cents']}"
        )
