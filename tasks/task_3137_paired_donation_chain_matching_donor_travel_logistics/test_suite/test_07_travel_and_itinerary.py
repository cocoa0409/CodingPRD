"""Travel reimbursement calculation and itinerary lifecycle tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_center,
    create_confirmed_itinerary,
    create_donor,
    create_itinerary_payload,
    get_success_data,
    make_center_coordinator_headers,
    reset_clock,
    setup_donor_with_policy,
    validate_error,
    validate_success,
)

LOGISTICS = TEST_USERS["logistics_headers"]
ADMIN = TEST_USERS["registry_admin_headers"]


class TestTravelReimbursementVariants:
    def test_travel_reimbursement_paired_vs_altruistic_divergence(self, api):
        """PRD §3.10: "For a non-altruistic donor, the flight component is
        `FLIGHT_CENTS_PER_MILE` of 50 cents per mile multiplied by
        `segment_miles`, rounded half-up to the nearest cent, and then capped at
        `FLIGHT_CAP_CENTS` of 80000. The lodging component is `lodging_nights`
        multiplied by `LODGING_PER_NIGHT_CENTS` of 15000, capped at
        `LODGING_CAP_CENTS` of 60000. The estimate is the flight component plus
        the lodging component plus a flat booking fee `FLAT_FEE_CENTS` of 2500."
        PRD §3.10: "For an `ALTRUISTIC` donor, the structure is identical but
        with elevated caps and a mileage multiplier: the flight component
        multiplies the per-mile rate by `ALTRUISTIC_MILEAGE_MULTIPLIER` of 1.10
        before the per-component rounding and caps at
        `FLIGHT_CAP_CENTS_ALTRUISTIC` of 95000, while the lodging cap is
        `LODGING_CAP_CENTS_ALTRUISTIC` of 75000; the per-night rate, the
        per-mile base rate, and the flat fee are unchanged."

        Design: Difficulty/dual_variant_calc/travel_reimbursement_paired_vs_altruistic_divergence
        """
        reset_clock()
        center = create_center()
        paired = create_donor(center, abo_type="A", donor_kind="PAIRED")
        altruistic = create_donor(center, abo_type="O", donor_kind="ALTRUISTIC")
        it_paired = get_success_data(
            api.create_itinerary(
                create_itinerary_payload(paired["id"], segment_miles=2586, lodging_nights=4),
                LOGISTICS,
            ),
            expected_status=201,
        )
        it_altruistic = get_success_data(
            api.create_itinerary(
                create_itinerary_payload(
                    altruistic["id"], segment_miles=2586, lodging_nights=4
                ),
                LOGISTICS,
            ),
            expected_status=201,
        )
        confirmed_paired = validate_success(api.confirm_itinerary(it_paired["id"], LOGISTICS))
        confirmed_altruistic = validate_success(
            api.confirm_itinerary(it_altruistic["id"], LOGISTICS)
        )
        # paired: min(80000, 50*2586) + min(60000, 4*15000) + 2500 = 142500
        assert confirmed_paired["estimated_cost_cents"] == 142500
        # altruistic: min(95000, round(50*1.10*2586)) + min(75000, 60000) + 2500 = 157500
        assert confirmed_altruistic["estimated_cost_cents"] == 157500
        assert (
            confirmed_paired["estimated_cost_cents"]
            != confirmed_altruistic["estimated_cost_cents"]
        )

    def test_travel_reimbursement_altruistic_caps_bind(self, api):
        """PRD §3.10: "For identical inputs, the altruistic variant yields a
        strictly greater estimate whenever the multiplier or the elevated caps
        bind, and an equal estimate otherwise."

        Design: Difficulty/dual_variant_calc/travel_reimbursement_paired_vs_altruistic_divergence
        """
        reset_clock()
        center = create_center()
        paired = create_donor(center, abo_type="A", donor_kind="PAIRED")
        altruistic = create_donor(center, abo_type="O", donor_kind="ALTRUISTIC")
        it_paired = get_success_data(
            api.create_itinerary(
                create_itinerary_payload(paired["id"], segment_miles=2586, lodging_nights=4),
                LOGISTICS,
            ),
            expected_status=201,
        )
        it_altruistic = get_success_data(
            api.create_itinerary(
                create_itinerary_payload(
                    altruistic["id"], segment_miles=2586, lodging_nights=4
                ),
                LOGISTICS,
            ),
            expected_status=201,
        )
        confirmed_paired = validate_success(api.confirm_itinerary(it_paired["id"], LOGISTICS))
        confirmed_altruistic = validate_success(
            api.confirm_itinerary(it_altruistic["id"], LOGISTICS)
        )
        assert (
            confirmed_altruistic["estimated_cost_cents"]
            > confirmed_paired["estimated_cost_cents"]
        )

    def test_travel_reimbursement_per_component_rounding(self, api):
        """PRD §3.10: "Rounding is applied per component first, then components
        are summed, then the flat fee is added — that order is mandatory."
        PRD §3.10: "For a non-altruistic donor, the flight component is
        `FLIGHT_CENTS_PER_MILE` of 50 cents per mile multiplied by
        `segment_miles`, rounded half-up to the nearest cent, and then capped at
        `FLIGHT_CAP_CENTS` of 80000. The lodging component is `lodging_nights`
        multiplied by `LODGING_PER_NIGHT_CENTS` of 15000, capped at
        `LODGING_CAP_CENTS` of 60000."

        Design: Difficulty/combinatorial_formula/travel_reimbursement_per_component_rounding
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center, abo_type="O", donor_kind="PAIRED")
        itinerary = get_success_data(
            api.create_itinerary(
                create_itinerary_payload(donor["id"], segment_miles=1333, lodging_nights=3),
                LOGISTICS,
            ),
            expected_status=201,
        )
        confirmed = validate_success(api.confirm_itinerary(itinerary["id"], LOGISTICS))
        # flight = min(80000, round(50*1333)) = 66650; lodging = min(60000, 45000);
        # total = 66650 + 45000 + 2500 = 114150
        assert confirmed["estimated_cost_cents"] == 114150

    def test_travel_reimbursement_per_component_rounding_at_caps(self, api):
        """PRD §3.10: "Rounding is applied per component first, then components
        are summed, then the flat fee is added — that order is mandatory."
        PRD §3.10: "the flight component is `FLIGHT_CENTS_PER_MILE` of 50 cents
        per mile multiplied by `segment_miles`, rounded half-up to the nearest
        cent, and then capped at `FLIGHT_CAP_CENTS` of 80000."

        Design: Difficulty/combinatorial_formula/travel_reimbursement_per_component_rounding
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center, abo_type="O", donor_kind="PAIRED")
        # segment_miles=2000 -> flight component 100000, capped to 80000.
        itinerary = get_success_data(
            api.create_itinerary(
                create_itinerary_payload(donor["id"], segment_miles=2000, lodging_nights=5),
                LOGISTICS,
            ),
            expected_status=201,
        )
        confirmed = validate_success(api.confirm_itinerary(itinerary["id"], LOGISTICS))
        # flight = 80000; lodging = min(60000, 5*15000=75000) = 60000
        assert confirmed["estimated_cost_cents"] == 80000 + 60000 + 2500


class TestItineraryLifecycle:
    def test_itinerary_confirm_then_cancel_conserves_traveled_distance(self, api):
        """PRD §3.10: "Cancelling recomputes the donor's
        `traveled_distance_miles` to exclude the cancelled segment."
        PRD §3.10: "the donor's `traveled_distance_miles` is then recomputed as
        the sum of `segment_miles` over the donor's confirmed itineraries only."
        PRD §3.2: "the computed fields `traveled_distance_miles` and
        `complications_recorded` start at zero."

        Design: Difficulty/compensating_invariant/itinerary_confirm_then_cancel_conserves_traveled_distance
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center, abo_type="O")
        assert donor["traveled_distance_miles"] == 0
        itinerary = create_confirmed_itinerary(donor)
        cancelled = validate_success(
            api.cancel_itinerary(
                itinerary["id"], {"cancelled_reason": "SCHEDULE_MOVED"}, LOGISTICS
            )
        )
        assert cancelled["itinerary_state"] == "CANCELLED"
        refreshed = validate_success(api.get_donor(donor["id"], ADMIN))
        assert refreshed["traveled_distance_miles"] == 0

    def test_itinerary_confirm_then_cancel_state_terminal(self, api):
        """PRD §3.10: "The itinerary begins in `DRAFT`; its `itinerary_state`
        moves to `CONFIRMED` on confirmation and terminates at either
        `REIMBURSED` or `CANCELLED`."
        PRD §3.10: "Cancelling recomputes the donor's
        `traveled_distance_miles` to exclude the cancelled segment."

        Design: Difficulty/compensating_invariant/itinerary_confirm_then_cancel_conserves_traveled_distance
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center, abo_type="O")
        itinerary = create_confirmed_itinerary(donor)
        # While CONFIRMED, the segment counts toward traveled distance.
        mid = validate_success(api.get_donor(donor["id"], ADMIN))
        assert mid["traveled_distance_miles"] == itinerary["segment_miles"]
        validate_success(
            api.cancel_itinerary(
                itinerary["id"], {"cancelled_reason": "SCHEDULE_MOVED"}, LOGISTICS
            )
        )
        final = validate_success(api.get_donor(donor["id"], ADMIN))
        assert final["traveled_distance_miles"] == 0

    def test_itinerary_reimburse_before_arrival_rejected(self, api):
        """PRD §3.10: "a `RegistryAdmin` reimburses a confirmed itinerary only
        once the logical clock has reached `arrive_utc` — an attempt before
        arrival is rejected with `ERR_FLIGHT_ALREADY_DEPARTED` as well — and
        only while the donor has an active protection policy, otherwise
        `ERR_NO_PROTECTION_POLICY`."

        Design: Difficulty/compensating_invariant/itinerary_confirm_then_cancel_conserves_traveled_distance
        """
        ctx, donor, policy = setup_donor_with_policy()
        itinerary = create_confirmed_itinerary(donor)
        resp = api.reimburse_itinerary(itinerary["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FLIGHT_ALREADY_DEPARTED.value)


class TestReimbursementAndClaimMinting:
    def test_reimbursement_auto_mints_travel_claim(self, api):
        """PRD §3.10: "Reimbursement moves the itinerary to `REIMBURSED`,
        auto-mints a `DonorProtectionClaim` with `claim_kind` equal to `TRAVEL`,
        `requested_amount_cents` equal to the itinerary's
        `estimated_cost_cents`, and `claim_state` equal to `APPROVED`, and
        credits the policy's `travel_reimbursed_cents` by the same amount."

        Design: Difficulty/compensating_invariant/itinerary_confirm_then_cancel_conserves_traveled_distance
        """
        from test_helpers import validate_paginated

        ctx, donor, policy = setup_donor_with_policy()
        itinerary = create_confirmed_itinerary(donor)
        # Move the logical clock to the arrival timestamp.
        get_success_data(api.set_clock("2026-09-10T16:00:00Z", ADMIN))
        reimbursed = validate_success(api.reimburse_itinerary(itinerary["id"], ADMIN))
        assert reimbursed["itinerary_state"] == "REIMBURSED"
        policy_after = validate_success(api.get_policy(policy["id"], ADMIN))
        assert (
            policy_after["travel_reimbursed_cents"]
            == policy["travel_reimbursed_cents"] + itinerary["estimated_cost_cents"]
        )
        claims, _meta = validate_paginated(
            api.list_claims(ADMIN, params={"claim_kind": "TRAVEL"})
        )
        assert len(claims) == 1
        assert claims[0]["claim_state"] == "APPROVED"
        assert claims[0]["requested_amount_cents"] == itinerary["estimated_cost_cents"]
