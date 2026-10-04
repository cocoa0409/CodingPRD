"""Mystery-shop verification windows, disclosure cascades and buy-box placement."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import next_imei


class TestVerificationWindows:
    def test_strictly_overlapping_window_is_refused(self, api):
        """PRD §3.4: "its windows may not strictly overlap another still-`OPEN` verification for the same listing; two windows that merely abut end-to-start do not collide, and a genuine overlap is refused with `ERR_VERIFICATION_OVERLAP` (HTTP 409)."
        PRD §3.4: "The window is half-open: `verification_end` must be strictly later than `verification_start` and is exclusive."

        Design: Difficulty/resource_temporal_overlap/mystery_shop_verification_strict_overlap
        """
        scenario = fx.setup_listed_device(clock="2026-12-01T00:00:00Z")
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]

        first = validate_success(
            fx.open_verification(
                seller_id, listing_id,
                verification_start="2026-12-05T00:00:00Z",
                verification_end="2026-12-10T00:00:00Z",
            ),
            201,
        )
        assert first["verification_state"] == "OPEN"

        overlap = fx.open_verification(
            seller_id, listing_id,
            rationale_code="PART_PROVENANCE",
            verification_start="2026-12-06T00:00:00Z",
            verification_end="2026-12-10T00:00:00Z",
        )
        validate_error(overlap, ApiErrorId.ERR_VERIFICATION_OVERLAP, 409)

    def test_a_window_abutting_the_exclusive_end_is_admitted(self, api):
        """PRD §3.4: "two windows that merely abut end-to-start do not collide, and a genuine overlap is refused with `ERR_VERIFICATION_OVERLAP` (HTTP 409)."
        PRD §3.4: "The new verification opens in state `OPEN`, and its windows may not strictly overlap another still-`OPEN` verification for the same listing"

        Design: Difficulty/resource_temporal_overlap/mystery_shop_verification_strict_overlap
        """
        scenario = fx.setup_listed_device(clock="2026-12-01T00:00:00Z")
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]

        validate_success(
            fx.open_verification(
                seller_id, listing_id,
                verification_start="2026-12-05T00:00:00Z",
                verification_end="2026-12-10T00:00:00Z",
            ),
            201,
        )
        abutting = validate_success(
            fx.open_verification(
                seller_id, listing_id,
                rationale_code="PART_PROVENANCE",
                verification_start="2026-12-10T00:00:00Z",
                verification_end="2026-12-14T00:00:00Z",
            ),
            201,
        )
        assert abutting["verification_state"] == "OPEN"

        rows, meta = validate_paginated(
            api.get(f"/v1/mystery-shop-verifications?listing_id={listing_id}", headers=fx.ADMIN)
        )
        open_rows = [row for row in rows if row["verification_state"] == "OPEN"]
        assert len(open_rows) == 2, "adjacency at the boundary does not collide"


class TestDisclosureCascade:
    def test_disclosure_fans_out_across_three_resources(self, api):
        """PRD §3.4: "The verification moves from `OPEN` to `DISCLOSED`, and the effects fan out across three resources. The listing's `mystery_shop_disclosed` flag is set to true. On the verification row itself, `value_at_risk` is set to 1, `reserved_units_delta` is set to 1, and `exposure_floor_delta_cents` is set to 9600 — the `grading_constraint_violation_unit_cents` value. Then the seller's constraint exposure is raised accordingly and the seller's `exposure_floor_cents` is recomputed"
        PRD §3.4: "a void mutates neither the listing nor the seller's score, so the programme can close out a clean shop without leaving a mark."

        Design: Difficulty/transitive_cascade/mystery_shop_disclosure_chain_listing_score_tier
        """
        # PRD §3.7: "The component `grading_compliance_pct` is one hundred
        # times the quantity of shops minus violations, divided by the greater
        # of one and the shop count."  Two shops are run and both find a
        # violation, so the component moves 100.00 -> 0.00 and the weighted
        # score falls to 45.00, at or below the suspension threshold.
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        second = fx.create_listing(seller_id, imei=next_imei(), part_provenance="OEM_ONLY",
                                   provenance_doc_digest=None)
        fx.approve_listing(second["id"])
        section = fx.open_section(seller_id, "2026-01-05T00:00:00Z")

        first_shop = validate_success(fx.open_verification(seller_id, listing_id), 201)
        second_shop = validate_success(fx.open_verification(seller_id, second["id"]), 201)

        before = fx.read_section(section["id"])
        assert before["grading_compliance_pct"] == 100.00
        assert before["service_score"] == 70.00

        disclosed = validate_success(fx.disclose_verification(first_shop["id"]))
        assert disclosed["verification_state"] == "DISCLOSED"
        assert disclosed["value_at_risk"] == 1

        listing = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert listing["mystery_shop_disclosed"] is True

        after = fx.read_section(section["id"])
        assert after["grading_compliance_pct"] == 50.00, (
            "hop two: two shops, one violation, is one hundred times (2 - 1) / 2"
        )
        assert after["service_score"] == 57.50

        validate_success(fx.disclose_verification(second_shop["id"]))
        final = fx.read_section(section["id"])
        assert final["grading_compliance_pct"] == 0.00
        assert final["service_score"] == 45.00

        seller = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        assert seller["onboarding_state"] == "SUSPENDED", (
            "hop three: the section recompute remaps the seller and suspends it at or below 55.00"
        )

    def test_a_grade_mismatch_records_one_violation_unit(self, api):
        """PRD §3.4: "On the verification row itself, `value_at_risk` is set to 1, `reserved_units_delta` is set to 1, and `exposure_floor_delta_cents` is set to 9600 — the `grading_constraint_violation_unit_cents` value."
        PRD §3.4: "The verifier supplies `received_cosmetic_grade` (the cosmetic grade actually observed on the delivered device), `measured_battery_health_pct` (1 to 100 inclusive), and a `verifier_user_id`."

        Design: Corner/validations/mystery_shop_grade_mismatch_discloses
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        verification = validate_success(
            fx.open_verification(seller_id, listing_id, ordered_cosmetic_grade="GOOD"), 201
        )

        disclosed = validate_success(
            fx.disclose_verification(
                verification["id"], received_cosmetic_grade="POOR", measured_battery_health_pct=74
            )
        )
        assert disclosed["value_at_risk"] == 1
        assert disclosed["ordered_cosmetic_grade"] == "GOOD"
        assert disclosed["received_cosmetic_grade"] == "POOR"
        assert disclosed["exposure_floor_delta_cents"] == 9600

        listing = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert listing["mystery_shop_disclosed"] is True

    def test_disclosure_is_not_idempotent(self, api):
        """PRD §3.4: "A listing that already carries a `DISCLOSED` verification cannot be disclosed against a second time; the attempt is refused with `ERR_VERIFICATION_ALREADY_DISCLOSED` (HTTP 409)."
        PRD §3.4: "`DISCLOSED` and `VOIDED` are both terminal."

        Design: Corner/validations/mystery_shop_grade_mismatch_discloses
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        fx.setup_disclosed_verification(seller_id, listing_id)

        second = validate_success(fx.open_verification(seller_id, listing_id), 201)
        response = fx.disclose_verification(second["id"])
        validate_error(response, ApiErrorId.ERR_VERIFICATION_ALREADY_DISCLOSED, 409)

        after = validate_success(
            api.get(f"/v1/mystery-shop-verifications/{second['id']}", headers=fx.ADMIN)
        )
        assert after["verification_state"] == "OPEN"


class TestBuyBox:
    def test_buy_box_picks_the_winner_without_any_random_identifier(self, api):
        """PRD §3.7: "The winner is the first candidate under a pinned sort key: the negation of the candidate's `list_price_cents` rounded half-up to two decimals, with `created_at` ascending as the tie-break."
        PRD §3.7: "The response for a buy-box query carries `winner_listing_id`, `winner_seller_id`, `winner_rank_score`, `buy_box_price_cents` and `ranked_listing_ids`."
        PRD §3.7: "A's listing wins the ranking, because the sort key for 150000 beats the sort key for 160000."

        Design: Corner/endpoints/cross_reference_buy_box_returns_ranked_candidates
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        fx.create_active_definition()

        seller_a = fx.create_approved_seller(clock="2026-12-01T00:00:00Z", legal_name="Refurb BuyBox A")
        listing_a = fx.create_listing(seller_a["id"], list_price_cents=150000)
        fx.approve_listing(listing_a["id"])
        _score_section_to_premium(seller_a["id"], listing_a["id"], carrier="CARRIER_A")

        seller_c = fx.create_approved_seller(clock="2026-12-01T00:00:00Z", legal_name="Refurb BuyBox C")
        listing_c = fx.create_listing(seller_c["id"], list_price_cents=160000, imei=next_imei())
        fx.approve_listing(listing_c["id"])
        _score_section_to_premium(seller_c["id"], listing_c["id"], carrier="CARRIER_C")

        seller_a_after = validate_success(api.get(f"/v1/sellers/{seller_a['id']}", headers=fx.ADMIN))
        assert seller_a_after["performance_tier"] == "STANDARD", (
            "PRD §3.7: `STANDARD` at 70.00 or above"
        )

        response = validate_success(api.get(f"/v1/listings/{listing_a['id']}/buy-box", headers=fx.ADMIN))
        assert response["winner_listing_id"] == listing_a["id"], (
            "the winner is chosen by the pinned sort key, not by any random identifier"
        )
        # PRD §3.7: "A's listing wins the ranking, because the sort key for
        # 150000 beats the sort key for 160000.  A's competitor average is
        # 160000 cents, so A's buy-box price is 0.40 times 160000 rounded
        # half-up, which is 64000 cents."
        assert set(response["ranked_listing_ids"]) == {listing_a["id"], listing_c["id"]}
        assert response["winner_seller_id"] == seller_a["id"]
        assert response["winner_rank_score"] == 70.00
        assert response["buy_box_price_cents"] == 64000


class TestClockDrivenTradeIn:
    def test_the_server_starts_on_the_declared_default_clock(self, api):
        """PRD §2.4: "The clock starts fixed at `2026-09-01T00:00:00Z` and never falls back to wall-clock time."
        PRD §3.8: "when the logical clock advances strictly past the `acceptance_deadline`, the system moves the submission to `REJECTED`."

        Design: Corner/cross_cutting_complexity_layers/reliance_on_clock_for_reservation_expiry
        """
        trade_in = fx.submit_trade_in()
        fx.inspect_trade_in(trade_in["id"])
        revised = validate_success(fx.revise_trade_in(trade_in["id"]))
        # PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
        # timestamp with three fractional digits", and §2.4 makes every
        # persisted timestamp follow the same shape.
        assert revised["acceptance_deadline"] == "2026-09-08T00:00:00.000Z", (
            "the server-start clock is 2026-09-01T00:00:00Z, so the deadline is seven days later"
        )

        fx.set_clock("2026-09-10T00:00:00Z")
        after = fx.read_trade_in(trade_in["id"])
        assert after["submission_state"] == "REJECTED"

    def test_acceptance_exactly_at_the_deadline_succeeds(self, api):
        """PRD §3.8: "Acceptance is legal while the clock reads at or before `acceptance_deadline` and while the `final_quote_cents` is strictly greater than zero."
        PRD §3.8: "Acceptance exactly at the deadline succeeds; the same request one day later is refused with `ERR_ACCEPTANCE_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/reliance_on_clock_for_reservation_expiry
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        trade_in = fx.submit_trade_in()
        fx.inspect_trade_in(trade_in["id"])
        revised = validate_success(fx.revise_trade_in(trade_in["id"]))
        deadline = revised["acceptance_deadline"]

        fx.set_clock(deadline)
        accepted = validate_success(fx.accept_trade_in(trade_in["id"]))
        assert accepted["submission_state"] == "ACCEPTED"


class TestRoutedSellerBinding:
    def test_routed_return_reassigns_the_seller_binding(self, api):
        """PRD §3.6: "On success the claim moves to `RESOLVED`, the `return_shipment_cents` is added to `seller_funded_amount_cents`, `claim_reserve_cents` is zeroed, and the released reserve is subtracted from the seller's exposure floor."

        Design: Corner/consistency_model/saga_family_route_return_releases_before_resolution
        """
        scenario = fx.setup_listed_device()
        claim = fx.create_upheld_claim(scenario["seller"]["id"], scenario["listing"]["id"])
        version = claim["version"]

        routed = validate_success(
            fx.route_claim_return(claim["id"], return_carrier="CARRIER_C", expected_claim_version=version)
        )
        assert routed["claim_state"] == "RESOLVED"
        assert routed["claim_reserve_cents"] == 0
        assert routed["seller_funded_amount_cents"] == 22500

        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{scenario['servicing_reservation_id']}", headers=fx.ADMIN)
        )
        assert reservation["warranty_state"] == "REPAIRING"

def _score_section_to_premium(seller_id, listing_id, carrier="CARRIER_A"):
    """Close a section on an unambiguous, PRD-derivable 70.00 profile.

    Building it in this order never recomputes the OPEN section to or below
    55.00, so PRD §3.9's suspension cascade never fires and the seller stays
    APPROVED with a PROBATION tier:

        cf = 100 * 0/1 =   0.00   (one routed claim, none rejected)
        ot = 100 * 0/1 =   0.00   (no routed claim resolved on time)
        gc = 100 * 1/1 = 100.00   (one shop, no violation)
        rr = 100 * 0/1 =   0.00   (no repaired reservation at close)
        score = .35*100 + .30*0 + .25*100 + .10*100 = 70.00
    """
    section = fx.open_section(seller_id, "2026-01-05T00:00:00Z")
    fx.open_verification(seller_id, listing_id)
    fx.create_claim_under_review(seller_id, listing_id, claim_reason_code="BATTERY_SWELL")

    closed = validate_success(
        fx.close_section(section["id"], fx.current_seller_version(seller_id))
    )
    assert closed["service_score"] == 70.00
    assert closed["threshold_breached"] is False
    return closed
