"""Seller onboarding, governance remedies and the warranty exposure ledger."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import create_listing_payload, next_imei


class TestSellerRegistration:
    def test_missing_required_field_is_refused_before_persistence(self, api):
        """PRD §3.1: "supplying its `legal_name`, its `country_code` (an ISO 3166-1 alpha-2 code of exactly two uppercase letters) and its `refurbishment_capacity_units`, the maximum number of devices it can refurbish per calendar month."
        PRD §2.11: "Priority 2 is request-shape validation — every required input field present and type-conformant"

        Design: Corner/entities/seller_create_missing_required_field_rejected
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        response = fx.api_client.create_seller(
            {"legal_name": "Refurb Bad", "country_code": "US"}, fx.ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, page_meta = validate_paginated(fx.api_client.list_sellers(fx.ADMIN))
        assert page_meta["total_count"] == 0

    def test_computed_seller_fields_ignore_client_values(self, api):
        """PRD §3.1: "A registered seller lands in `APPLICANT` with `performance_tier` set to `PROBATION` and `exposure_floor_cents` set to 0."
        PRD §2.5: "`latest_score_id` (the most recent closed service-score section, which may legally be null when none has been finalised)"

        Design: Corner/entities/seller_computed_tier_and_floor_ignore_input_values
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        created = fx.register_seller()
        assert created["performance_tier"] == "PROBATION"
        assert created["exposure_floor_cents"] == 0
        assert created["onboarding_state"] == "APPLICANT"
        assert created["latest_score_id"] is None

        seller, audit = fx.create_seller_in_audit(fx.verify_seller(created["id"])["id"])
        approved = validate_success(
            fx.api_client.transition_audit_record(
                audit["id"],
                {"target_state": "PASSED", "audit_score": 88, "auditor_user_id": "op_auditor"},
                fx.REVIEWER,
            )
        )
        reread = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert reread["onboarding_state"] == "APPROVED"
        assert reread["performance_tier"] == "PROBATION", (
            "the computed tier lands at PROBATION on approval"
        )
        assert reread["exposure_floor_cents"] == 0, (
            "approval resets the computed exposure floor to zero"
        )
        assert reread["latest_score_id"] is None
        assert approved["audit_state"] == "PASSED"

    def test_read_of_an_absent_seller_is_refused(self, api):
        """PRD §2.11: "Priority 4 is path-resource existence, validated left to right so that a non-existent parent identifier fails before the child identifier is examined (`ERR_RESOURCE_NOT_FOUND`, 404)."

        Design: Corner/entities/seller_read_unknown_id_returns_not_found
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        response = fx.api_client.get_seller("00000000-0000-4000-8000-000000000000", fx.ADMIN)
        validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)

        _, meta = validate_paginated(fx.api_client.list_sellers(fx.ADMIN))
        assert meta["total_count"] == 0

    def test_failed_audit_returns_the_seller_to_applicant(self, api):
        """PRD §3.1: "If the audit record's `declared_monthly_throughput` exceeds the seller's `refurbishment_capacity_units`, the applicant is rejected outright: the seller moves to `REJECTED`, the audit record is marked `FAILED`, and no score band is consulted at all."
        PRD §3.1: "That rework loop is bounded rather than open-ended, and for a structural reason worth stating plainly: an audit record row is single-use, so the next attempt requires a brand-new record, which in turn requires the seller to be re-verified and re-booked."

        Design: Corner/state_machines/seller_self_loop_reaudit_after_failed_audit
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_verified_seller()
        audit = fx.book_audit(seller["id"])

        failed = validate_success(
            fx.api_client.transition_audit_record(
                audit["id"],
                {"target_state": "FAILED", "audit_score": 61, "auditor_user_id": "op_auditor"},
                fx.REVIEWER,
            )
        )
        assert failed["audit_state"] == "FAILED"

        reread = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert reread["onboarding_state"] == "APPLICANT", (
            "a failed audit returns the seller to APPLICANT so it may be re-audited"
        )

        _, meta = validate_paginated(
            fx.api_client.list_seller_audit_records(seller["id"], fx.ADMIN)
        )
        assert meta["total_count"] == 1, "the loop is bounded by the single-use audit row"


class TestEligibilityPriority:
    def test_battery_floor_error_pre_empts_model_eligibility(self, api):
        """PRD §2.11: "the battery floor (`ERR_BATTERY_BELOW_FLOOR`, 422) at 7"
        PRD §2.11: "model-catalogue eligibility (`ERR_MODEL_NOT_ELIGIBLE`, 422) at 11"
        PRD §2.11: "Validations are evaluated in a fixed priority order, and the order is observable because a request that violates two rules reports the higher-priority error."

        Design: Difficulty/priority_pair_validation_conflict/battery_floor_precedes_model_eligibility
        """
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]

        response = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(
                model_code="UNKNOWN-MODEL-999",
                imei=next_imei(),
                battery_health_pct=75,
                part_provenance="OEM_ONLY",
                provenance_doc_digest=None,
            ),
            fx.make_seller_headers(seller_id),
        )
        validate_error(response, ApiErrorId.ERR_BATTERY_BELOW_FLOOR, 422)

        rows, meta = fx.list_seller_listings(seller_id)
        assert meta["total_count"] == 1, "the refused submission creates no listing row"

    def test_provenance_documentation_pre_empts_seller_standing(self, api):
        """PRD §2.11: "part-provenance documentation (`ERR_PART_PROVENANCE_UNDOCUMENTED`, 422) at 10; model-catalogue eligibility (`ERR_MODEL_NOT_ELIGIBLE`, 422) at 11; and seller approval standing (`ERR_SELLER_NOT_APPROVED`, 422) at 12."
        PRD §2.11: "Priority 2 is request-shape validation — every required input field present and type-conformant"

        Design: Difficulty/priority_pair_validation_conflict/seller_approval_with_undocumented_provenance
        """
        fx.create_active_definition()
        seller = fx.create_verified_seller()
        fx.book_audit(seller["id"])
        pending = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert pending["onboarding_state"] == "AUDIT_SCHEDULED"

        response = fx.api_client.create_listing(
            seller["id"],
            create_listing_payload(
                part_provenance="AFTERMARKET", provenance_doc_digest=None, imei=next_imei()
            ),
            fx.make_seller_headers(seller["id"]),
        )
        # Priority 10 (provenance documentation) outranks priority 12 (seller standing).
        validate_error(response, ApiErrorId.ERR_PART_PROVENANCE_UNDOCUMENTED, 422)

        unchanged = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert unchanged["onboarding_state"] == "AUDIT_SCHEDULED"


class TestGovernanceRemedies:
    def test_blocklisting_cascades_three_hops_and_empties_the_exposure(self, api):
        """PRD §3.9: "The seller's `blocklisted` flag is set true, `onboarding_state` and `performance_tier` both become `SUSPENDED`, and the cascade runs: every listing of that seller that is `LISTED` becomes `SUSPENDED`, and every warranty reservation servicing those listings has its `reserved_units` zeroed, with the owner's `exposure_floor_cents` recomputed from the now-empty repair term."
        PRD §3.5: "A seller whose every servicing reservation has been suspended by a blocklisting illustrates the other: with every cell removed the repair term is zero and the published floor equals the constraint term alone."

        Design: Difficulty/transitive_cascade/blocklist_chain_seller_listing_reservation
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        reservation_id = scenario["servicing_reservation_id"]

        claim = fx.create_upheld_claim(seller_id, listing_id)
        validate_success(fx.route_claim_return(claim["id"]))
        before = fx.get_exposure_floor(seller_id)
        assert before["cell_count"] == 1

        validate_success(
            fx.api_client.blocklist_seller(
                seller_id, fx.blocklist_payload(finding="CONFIRMED_COUNTERFEIT"), fx.REVIEWER
            )
        )

        seller = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        assert seller["blocklisted"] is True
        assert seller["onboarding_state"] == "SUSPENDED"
        assert seller["performance_tier"] == "SUSPENDED"

        listing = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert listing["listing_state"] == "SUSPENDED", "hop two: the seller cascade suspends the listing"

        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{reservation_id}", headers=fx.ADMIN)
        )
        assert reservation["warranty_state"] == "SUSPENDED", (
            "hop three: the listing mutation suspends the servicing reservation"
        )
        assert reservation["reserved_units"] == 0

        after = fx.get_exposure_floor(seller_id)
        assert after["published_exposure_floor_cents"] == 0, (
            "hop four: with every live cell released the published floor equals the constraint term alone"
        )
        assert after["cell_count"] == 0

    def test_unconfirmed_finding_is_refused_by_request_shape(self, api):
        """PRD §2.12: "A seller may be blocklisted only while `blocklisted` is false, and only with a `finding` of `CONFIRMED_COUNTERFEIT` or `CONFIRMED_STOLEN`"
        PRD §2.11: "every enum-valued field carrying a declared member"

        Design: Corner/errors/unconfirmed_finding_cannot_blocklist
        """
        seller = fx.create_approved_seller()
        response = fx.api_client.blocklist_seller(
            seller["id"], fx.blocklist_payload(finding="SUSPECTED_COUNTERFEIT"), fx.REVIEWER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        after = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert after["blocklisted"] is False

    def test_blocklisting_never_raises_the_suspension_trigger_count(self, api):
        """PRD §2.7: "`Seller.suspension_trigger_count` records how many closed service-score sections have breached the suspension threshold and is incremented only by the suspension transition driven by section close, never by blocklisting."
        PRD §2.12: "A seller may be blocklisted only while `blocklisted` is false, and only with a `finding` of `CONFIRMED_COUNTERFEIT` or `CONFIRMED_STOLEN`"

        Design: Corner/calculations/seller_escalation_ceiling_never_admits_blocklisting
        """
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]

        validate_success(
            fx.api_client.blocklist_seller(seller_id, fx.blocklist_payload(finding="CONFIRMED_STOLEN"), fx.REVIEWER)
        )
        after = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        assert after["blocklisted"] is True
        assert after["suspension_trigger_count"] == 0, (
            "blocklisting itself never raises the trigger count"
        )


class TestExposureLedger:
    def test_expired_reservation_is_completed_when_the_clock_moves(self, api):
        """PRD §3.5: "When the logical clock advances strictly past a reservation's `expired_on` while the reservation is `ACTIVE`, the system moves it to `COMPLETED` without any client request."
        PRD §2.4: "The clock starts fixed at `2026-09-01T00:00:00Z` and never falls back to wall-clock time."

        Design: Corner/cross_cutting_complexity_layers/reliance_on_clock_for_reservation_expiry
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])

        reservation = fx.add_reservation(
            listing["id"], activated_on="2026-12-01T00:00:00Z", warranty_period_days=20
        )
        assert reservation["warranty_state"] == "ACTIVE"

        fx.set_clock("2026-12-25T00:00:00Z")
        after = validate_success(
            api.get(f"/v1/warranty-reservations/{reservation['id']}", headers=fx.ADMIN)
        )
        assert after["warranty_state"] == "COMPLETED"

    def test_expired_on_reconciles_with_the_source_fields(self, api):
        """PRD §3.3: "Whichever path created it, a reservation's `expired_on` is its activation date plus its warranty period, and it is recomputed whenever `activated_on` or `warranty_period_days` changes."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciles_after_source_mutation
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])

        created = fx.add_reservation(
            listing["id"], activated_on="2026-12-01T00:00:00Z", warranty_period_days=365
        )
        assert created["expired_on"] == "2027-12-01T00:00:00.000Z", (
            f"expired_on must be activated_on plus 365 days, got {created['expired_on']}"
        )
        assert created["warranty_state"] == "ACTIVE"

        reread = validate_success(
            api.get(f"/v1/warranty-reservations/{created['id']}", headers=fx.ADMIN)
        )
        assert reread["expired_on"] == created["expired_on"]

    def test_live_exposure_reads_back_the_breakdown(self, api):
        """PRD §3.5: "For each live cell the system computes the remaining days as the calendar days from the current logical clock instant to the cell's expiry date — its `activated_on` plus its `warranty_period_days` — clamped at zero, and the remaining fraction as those remaining days divided by the warranty period."
        PRD §2.7: "A seller's reserve for approved-but-unresolved claims is exposed on the exposure read as `reserved_claim_cents`"

        Design: Corner/endpoints/computed_read_exposure_floor_breakdown
        """
        # The 180-day term is opened after the approval-opened reservation and
        # carries a strictly later activation instant, so the selector ranks it
        # first and the claim pins to it.
        fx.set_clock("2026-09-02T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-09-02T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])

        fx.set_clock("2026-12-10T00:00:00Z")
        reservation = fx.add_reservation(
            listing["id"],
            activated_on="2026-12-01T00:00:00Z",
            warranty_period_days=180,
            unit_reserve_per_day_cents=1800,
        )

        claim = fx.create_upheld_claim(seller["id"], listing["id"])
        validate_success(fx.route_claim_return(claim["id"]))

        reservation = fx.servicing_reservation(listing["id"])
        assert reservation["warranty_period_days"] == 180
        reservation_id = reservation["id"]
        live = validate_success(api.get(f"/v1/warranty-reservations/{reservation_id}", headers=fx.ADMIN))
        assert live["warranty_state"] == "REPAIRING", (
            "the reservation with the latest activation instant is the servicing reservation"
        )

        exposure = fx.get_exposure_floor(seller["id"])
        assert exposure["cell_count"] == 1
        assert exposure["reserved_claim_cents"] == 0
        seller_row = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert exposure["published_exposure_floor_cents"] == seller_row["exposure_floor_cents"]

    def test_remediation_releases_exactly_the_live_cell(self, api):
        """PRD §3.5: "Remediation illustrates the first term's behaviour — the remediated reservation stops contributing a cell, so the repair term falls by exactly that cell and the published floor falls by the same amount."
        PRD §3.5: "the released cell is subtracted from the seller's `exposure_floor_cents`, the seller's `performance_tier` is re-derived, and the buy-box rank is recomputed."

        Design: Difficulty/compensating_invariant/repair_release_returns_floor_to_pre_claim_value
        """
        # The servicing reservation is the one approval opens, and the selector
        # prefers the latest activation instant, so the clock is moved to the
        # instant that reservation is meant to carry.
        fx.set_clock("2026-09-02T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-09-02T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        reservation = fx.servicing_reservation(listing["id"])

        fx.set_clock("2026-12-10T00:00:00Z")
        claim = fx.create_upheld_claim(seller["id"], listing["id"])
        validate_success(fx.route_claim_return(claim["id"]))

        before = fx.get_exposure_floor(seller["id"])
        assert before["published_exposure_floor_cents"] == 810, (
            f"99 days elapsed of a 180-day period at 1800 cents per day is 810 cents, "
            f"got {before['published_exposure_floor_cents']}"
        )
        assert before["cell_count"] == 1

        validate_success(fx.remediate_reservation(reservation["id"], repair_estimate_cents=18000))
        released = validate_success(
            api.get(f"/v1/warranty-reservations/{reservation['id']}", headers=fx.ADMIN)
        )
        assert released["warranty_state"] == "ACTIVE"

        after = fx.get_exposure_floor(seller["id"])
        assert after["cell_count"] == 0
        assert after["published_exposure_floor_cents"] == 0
        assert before["published_exposure_floor_cents"] - after["published_exposure_floor_cents"] == 810, (
            "the floor must fall by exactly the released cell, so the obligation carries no drift"
        )

    def test_per_cell_rounding_and_the_single_rounding_trace_diverge_by_one_cent(self, api):
        """PRD §3.5: "Crucially, each cell is rounded *individually* and only then are the cells summed; rounding once over the combined total is the non-conforming order and yields different cents whenever two cells' fractional parts cross the halfway point together."
        PRD §3.9: "`published_exposure_floor_cents` is the per-cell-rounded balance carried on the seller row, and `traced_exposure_cents` is the single-rounding recomputation; the two are returned side by side and may legitimately differ by one cent when two or more live cells have fractional parts that cross the halfway point together."
        PRD §3.9: "When the seller has exactly one live cell the two orders coincide and the values agree exactly"

        Design: Difficulty/dual_variant_calc/warranty_exposure_per_cell_sum_vs_combined_rounding
        """
        # The approvals happen at an earlier instant than the explicitly-opened
        # 270-day terms, so PRD §3.5's selector — `activated_on` descending —
        # ranks the 270-day term first and every claim pins to it.
        fx.set_clock("2026-11-18T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-11-18T00:00:00Z")

        listings = []
        for _ in range(2):
            listing = fx.create_listing(seller["id"], imei=next_imei(), part_provenance="OEM_ONLY",
                                        provenance_doc_digest=None)
            fx.approve_listing(listing["id"])
            listings.append(listing)

        fx.set_clock("2026-11-20T00:00:00Z")
        devices = []
        for listing in listings:
            reservation = fx.add_reservation(
                listing["id"],
                activated_on="2026-11-20T00:00:00Z",
                warranty_period_days=270,
                reserved_units=1,
                unit_reserve_per_day_cents=1800,
            )
            devices.append((listing, reservation))

        fx.set_clock("2026-12-10T00:00:00Z")
        for index, (listing, reservation) in enumerate(devices):
            claim = fx.create_upheld_claim(seller["id"], listing["id"])
            validate_success(
                fx.route_claim_return(
                    claim["id"],
                    return_carrier=f"CARRIER_{chr(65 + index)}",
                    return_shipment_start=f"2026-12-1{index + 2}T00:00:00Z",
                )
            )
            live = validate_success(
                api.get(f"/v1/warranty-reservations/{reservation['id']}", headers=fx.ADMIN)
            )
            assert live["warranty_state"] == "REPAIRING"

        exposure = fx.get_exposure_floor(seller["id"])
        assert exposure["cell_count"] == 2
        # Each cell has 250 of its 270 days remaining, so it rounds individually
        # to 1667; the combined total of 3333.33 rounds once to 3333.
        assert exposure["published_exposure_floor_cents"] == 3334, (
            f"Expected the per-cell sum 3334, got {exposure['published_exposure_floor_cents']}"
        )
        assert exposure["traced_exposure_cents"] == 3333, (
            f"Expected the single-rounding trace 3333, got {exposure['traced_exposure_cents']}"
        )
        assert exposure["traced_exposure_cents"] - exposure["published_exposure_floor_cents"] == -1, (
            "the two rounding orders differ by exactly one cent on identical live cells"
        )

    def test_a_single_live_cell_rounds_identically_under_both_orders(self, api):
        """PRD §3.9: "When the seller has exactly one live cell the two orders coincide and the values agree exactly, and a seller with no live cell returns a trace of zero with a cell count of zero."
        PRD §3.9: "`published_exposure_floor_cents` is the per-cell-rounded balance carried on the seller row"

        Design: Difficulty/dual_variant_calc/warranty_exposure_per_cell_sum_vs_combined_rounding
        """
        # The 270-day term is opened after the approval-opened reservation and
        # carries a strictly later activation instant, so PRD §3.5's selector
        # ranks it first and the claim pins to it.
        fx.set_clock("2026-11-20T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-11-20T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])

        fx.set_clock("2026-12-30T00:00:00Z")
        reservation = fx.add_reservation(
            listing["id"],
            activated_on="2026-12-10T00:00:00Z",
            warranty_period_days=270,
            reserved_units=1,
            unit_reserve_per_day_cents=1800,
        )

        claim = fx.create_upheld_claim(seller["id"], listing["id"])
        validate_success(fx.route_claim_return(claim["id"], return_carrier="CARRIER_A",
                                               return_shipment_start="2026-12-11T00:00:00Z"))
        # The claim pinned the selector's winner, so the REPAIRING cell is the
        # 270-day term; 250 of its days remain at 2026-12-30.
        reservation = fx.servicing_reservation(listing["id"])
        assert reservation["warranty_period_days"] == 270
        live = validate_success(
            api.get(f"/v1/warranty-reservations/{reservation['id']}", headers=fx.ADMIN)
        )
        assert live["warranty_state"] == "REPAIRING"

        exposure = fx.get_exposure_floor(seller["id"])
        assert exposure["cell_count"] == 1
        assert exposure["published_exposure_floor_cents"] == exposure["traced_exposure_cents"], (
            "with exactly one live cell the per-cell and combined rounding orders coincide"
        )
        assert exposure["published_exposure_floor_cents"] == 1667

    def test_constraint_exposure_above_the_denominator_uses_raw_units(self, api):
        """PRD §3.5: "At or above a denominator of 300 units, the raw figure is used unchanged."
        PRD §3.5: "The unit count is multiplied by 9600 cents to give the constraint exposure."
        PRD §3.4: "On the verification row itself, `value_at_risk` is set to 1, `reserved_units_delta` is set to 1, and `exposure_floor_delta_cents` is set to 9600 — the `grading_constraint_violation_unit_cents` value."

        Design: Corner/calculations/constraint_exposure_above_denominator_uses_raw_units
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        fx.create_active_definition()
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        section = fx.open_section(seller["id"], "2026-01-05T00:00:00Z")

        for reason in ("BATTERY_SWELL", "TOUCH_FAILURE", "CAMERA_FAILURE", "UNLOCKED_PROMISE_BREACH"):
            fx.create_claim_under_review(seller["id"], listing["id"], claim_reason_code=reason)

        version = fx.current_seller_version(seller["id"])
        closed = validate_success(fx.close_section(section["id"], version))
        assert closed["section_state"] == "CLOSED"

        verification = fx.setup_disclosed_verification(seller["id"], listing["id"])
        assert verification["value_at_risk"] == 1

        _, page_meta = validate_paginated(
            fx.api_client.list_claims(fx.ADMIN, {"routed_seller_id": seller["id"]})
        )
        assert page_meta["total_count"] == 4

        exposure = fx.get_exposure_floor(seller["id"])
        assert exposure["published_exposure_floor_cents"] == 38400, (
            f"four violations at 9600 cents each is 38400, got "
            f"{exposure['published_exposure_floor_cents']}"
        )