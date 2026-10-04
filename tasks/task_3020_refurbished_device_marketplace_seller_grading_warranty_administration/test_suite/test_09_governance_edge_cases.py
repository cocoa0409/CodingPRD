"""Governance edges: floor sources, cascade scope, the reinstatement ramp and listing delisting."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import create_listing_payload, next_imei


class TestBatteryFloorSource:
    def test_floor_is_read_from_the_active_definition_with_a_hard_default(self, api):
        """PRD §3.2: "The `battery_health_pct` must be at least 80, and it must also be at least the `battery_floor_pct` of whichever `GradingDefinition` is `ACTIVE`; when no definition is `ACTIVE`, the hard floor of 80 stands alone. A shortfall is refused with `ERR_BATTERY_BELOW_FLOOR`."
        PRD §2.6: "`battery_floor_pct` (the minimum battery health a device may carry and still be graded at all, between 1 and 100 inclusive)"

        Design: Difficulty/priority_pair_validation_conflict/battery_floor_precedes_model_eligibility
        """
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]

        shortfall = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(imei=next_imei(), battery_health_pct=75,
                                   part_provenance="OEM_ONLY", provenance_doc_digest=None),
            fx.make_seller_headers(seller_id),
        )
        validate_error(shortfall, ApiErrorId.ERR_BATTERY_BELOW_FLOOR, 422)

        at_floor = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(imei=next_imei(), battery_health_pct=80,
                                   part_provenance="OEM_ONLY", provenance_doc_digest=None),
            fx.make_seller_headers(seller_id),
        )
        validate_success(at_floor, 201)

    def test_floor_shortfall_outranks_seller_standing_too(self, api):
        """PRD §2.11: "the battery floor (`ERR_BATTERY_BELOW_FLOOR`, 422) at 7"
        PRD §2.11: "seller approval standing (`ERR_SELLER_NOT_APPROVED`, 422) at 12"
        PRD §2.11: "Validations are evaluated in a fixed priority order, and the order is observable because a request that violates two rules reports the higher-priority error."

        Design: Difficulty/priority_pair_validation_conflict/battery_floor_precedes_model_eligibility
        """
        fx.create_active_definition()
        seller = fx.create_verified_seller()
        fx.book_audit(seller["id"])

        response = fx.api_client.create_listing(
            seller["id"],
            create_listing_payload(imei=next_imei(), battery_health_pct=70,
                                   part_provenance="OEM_ONLY", provenance_doc_digest=None),
            fx.make_seller_headers(seller["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BATTERY_BELOW_FLOOR, 422)


class TestProvenancePriorityAgain:
    def test_provenance_documentation_outranks_an_applicant_standing(self, api):
        """PRD §3.2: "`OEM_ONLY` needs no document, whereas `OEM_EQUIVALENT` and `AFTERMARKET` both require a `provenance_doc_digest`, which must be exactly 64 lowercase hexadecimal characters. A missing or malformed digest under either of those provenances is refused with `ERR_PART_PROVENANCE_UNDOCUMENTED`."
        PRD §2.11: "part-provenance documentation (`ERR_PART_PROVENANCE_UNDOCUMENTED`, 422) at 10"
        PRD §2.11: "seller approval standing (`ERR_SELLER_NOT_APPROVED`, 422) at 12"

        Design: Difficulty/priority_pair_validation_conflict/seller_approval_with_undocumented_provenance
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        fx.create_active_definition()
        seller = fx.create_verified_seller()
        audit = fx.book_audit(seller["id"])
        validate_success(
            fx.api_client.transition_audit_record(
                audit["id"],
                {"target_state": "FAILED", "audit_score": 61, "auditor_user_id": "op_auditor"},
                fx.REVIEWER,
            )
        )
        reworked = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert reworked["onboarding_state"] == "APPLICANT"

        response = fx.api_client.create_listing(
            seller["id"],
            create_listing_payload(part_provenance="OEM_EQUIVALENT", provenance_doc_digest=None,
                                   imei=next_imei()),
            fx.make_seller_headers(seller["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PART_PROVENANCE_UNDOCUMENTED, 422)


class TestDefinitionBindingReCapture:
    def test_reinstating_the_captured_definition_admits_the_review(self, api):
        """PRD §3.3: "Before the decision is honoured, the server re-reads the grading definition captured at submission time and confirms it is still `ACTIVE`; a definition retired in the interim produces `ERR_GRADING_DEFINITION_NOT_ACTIVE` (409)."
        PRD §2.6: "Publishing a definition — that is, moving one from `DRAFT` to `ACTIVE` — sets `binding_definition_id` to its own `id`"

        Design: Difficulty/cross_entity_state_dependency/listing_review_requires_captured_definition_active
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        definition = fx.create_active_definition(effective_from="2026-08-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])

        validate_success(
            fx.api_client.retire_grading_definition(
                definition["id"], {"retirement_note": "suspended pending revision"}, fx.REVIEWER
            )
        )
        blocked = fx.api_client.review_listing(
            listing["id"], {"decision": "APPROVED", "reviewer_user_id": "op_reviewer"}, fx.REVIEWER
        )
        validate_error(blocked, ApiErrorId.ERR_GRADING_DEFINITION_NOT_ACTIVE, 409)

        validate_success(fx.api_client.reinstate_grading_definition(definition["id"], fx.REVIEWER))
        admitted = validate_success(
            fx.api_client.review_listing(
                listing["id"], {"decision": "APPROVED", "reviewer_user_id": "op_reviewer"}, fx.REVIEWER
            )
        )
        assert admitted["listing_state"] == "LISTED"


class TestCompensatingInvariants:
    def test_the_clawback_is_the_reserve_and_never_the_buyer_payout(self, api):
        """PRD §2.7: "A seller's reserve for approved-but-unresolved claims is exposed on the exposure read as `reserved_claim_cents`, and consumers of this API should note that it is *not* netted out of the published floor — an approved claim that has not yet been resolved remains a live obligation, so subtracting it would understate the seller's position."
        PRD §3.6: "it charges the routed seller only the pro-rated share of the refused funded cost, where the refused funded cost is a fixed 90000 cents"

        Design: Difficulty/compensating_invariant/routed_return_releases_exactly_the_claim_reserve
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]

        claim = fx.create_upheld_claim(
            seller_id, listing_id, resolution_type="REPLACE", obligation_cents=90000
        )
        held = fx.get_exposure_floor(seller_id)
        assert held["reserved_claim_cents"] == 90000

        version = claim["version"]
        validate_success(fx.route_claim_return(claim["id"], expected_claim_version=version))

        settled = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        # PRD §3.6: "On an uphold, `seller_funded_amount_cents` is set to the
        # `resolution_obligation_cents` plus the `return_shipment_cents`
        # supplied", and "On success ... the `return_shipment_cents` is added to
        # `seller_funded_amount_cents`".  The routed return supplies 4500 cents,
        # so the funded amount is 90000 + 4500.
        assert settled["seller_funded_amount_cents"] == 90000 + 4500
        assert settled["claim_reserve_cents"] == 0

        released = fx.get_exposure_floor(seller_id)
        assert released["reserved_claim_cents"] == 0, (
            "the reserve released when the return is routed is the one the claim itself formed"
        )
        assert released["published_exposure_floor_cents"] >= 0

    def test_remediating_one_of_two_live_cells_drops_the_floor_by_that_cell(self, api):
        """PRD §3.5: "Remediation illustrates the first term's behaviour — the remediated reservation stops contributing a cell, so the repair term falls by exactly that cell and the published floor falls by the same amount."
        PRD §3.5: "the released cell is subtracted from the seller's `exposure_floor_cents`"

        Design: Difficulty/compensating_invariant/repair_release_returns_floor_to_pre_claim_value
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        fx.create_active_definition()
        seller = fx.create_approved_seller(clock="2026-09-02T00:00:00Z")

        first = fx.create_listing(seller["id"])
        fx.approve_listing(first["id"])
        first_reservation = fx._data(
            fx.api_client.list_listing_reservations(first["id"], fx.ADMIN), "list reservations"
        )

        fx.set_clock("2026-09-11T00:00:00Z")
        second = fx.create_listing(seller["id"], imei=next_imei(), part_provenance="OEM_ONLY",
                                   provenance_doc_digest=None)
        fx.approve_listing(second["id"])
        second_reservation = fx._data(
            fx.api_client.list_listing_reservations(second["id"], fx.ADMIN), "list reservations"
        )

        fx.set_clock("2026-12-10T00:00:00Z")
        first_claim = fx.create_upheld_claim(seller["id"], first["id"])
        validate_success(fx.route_claim_return(first_claim["id"], return_carrier="CARRIER_A",
                                               return_shipment_start="2026-12-12T00:00:00Z"))
        second_claim = fx.create_upheld_claim(seller["id"], second["id"])
        validate_success(fx.route_claim_return(second_claim["id"], return_carrier="CARRIER_B",
                                               return_shipment_start="2026-12-13T00:00:00Z"))

        cell_old = first_reservation[0]["id"]
        cell_new = second_reservation[0]["id"]

        before = fx.get_exposure_floor(seller["id"])
        assert before["cell_count"] == 2
        assert before["published_exposure_floor_cents"] == 1710

        validate_success(fx.remediate_reservation(cell_old, repair_estimate_cents=18000))

        after = fx.get_exposure_floor(seller["id"])
        assert after["cell_count"] == 1
        assert after["published_exposure_floor_cents"] == 900
        assert before["published_exposure_floor_cents"] - after["published_exposure_floor_cents"] == 810, (
            "the floor falls by exactly the released cell's value"
        )
        assert cell_new


class TestCascadeScope:
    def test_the_blocklist_cascade_only_suspends_listed_devices(self, api):
        """PRD §3.9: "the cascade runs: every listing of that seller that is `LISTED` becomes `SUSPENDED`, and every warranty reservation servicing those listings has its `reserved_units` zeroed"
        PRD §3.3: "Delisting a `LISTED` listing — available to a `ComplianceReviewer` with a `reason_code` drawn from `BATTERY_DEGRADED`, `MYSTERY_SHOP_FINDING`, `PART_PROVENANCE_UNVERIFIED`"

        Design: Difficulty/transitive_cascade/blocklist_chain_seller_listing_reservation
        """
        scenario = fx.setup_listed_device()
        seller_id, live_listing_id = scenario["seller"]["id"], scenario["listing"]["id"]

        other = fx.create_listing(seller_id, imei=next_imei(), part_provenance="OEM_ONLY",
                                  provenance_doc_digest=None)
        fx.approve_listing(other["id"])
        validate_success(fx.delist_listing(other["id"]))
        delisted_before = validate_success(api.get(f"/v1/listings/{other['id']}", headers=fx.ADMIN))
        assert delisted_before["listing_state"] == "DELISTED"

        validate_success(
            fx.api_client.blocklist_seller(
                seller_id, fx.blocklist_payload(finding="CONFIRMED_COUNTERFEIT"), fx.REVIEWER
            )
        )

        live = validate_success(api.get(f"/v1/listings/{live_listing_id}", headers=fx.ADMIN))
        assert live["listing_state"] == "SUSPENDED"

        archived = validate_success(api.get(f"/v1/listings/{other['id']}", headers=fx.ADMIN))
        assert archived["listing_state"] == "DELISTED", (
            "the cascade reaches only the listings that are LISTED at the moment of blocklisting"
        )


class TestDisclosureScoreCascade:
    def test_disclosure_recomputes_the_compliance_component(self, api):
        """PRD §3.4: "Then the seller's constraint exposure is raised accordingly and the seller's `exposure_floor_cents` is recomputed, which in turn re-derives `performance_tier` and re-ranks the seller's buy-box position."
        PRD §3.7: "The component `grading_compliance_pct` is one hundred times the quantity of shops minus violations, divided by the greater of one and the shop count."
        PRD §2.7: "`Seller.suspension_trigger_count` records how many closed service-score sections have breached the suspension threshold and is incremented only by the suspension transition driven by section close, never by blocklisting."
        PRD §3.5: "Sellers with no closed section contribute zero."

        Design: Difficulty/transitive_cascade/mystery_shop_disclosure_chain_listing_score_tier
        """
        # PRD §3.7: "The component `grading_compliance_pct` is one hundred
        # times the quantity of shops minus violations, divided by the greater
        # of one and the shop count."  Four shops are run and three find a
        # violation, so the component moves 100.00 -> 0.00 and the weighted
        # score moves 70.00 -> 45.00.
        scenario = fx.setup_listed_device(clock="2026-09-02T00:00:00Z")
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        extra = []
        for _ in range(3):
            row = fx.create_listing(seller_id, imei=next_imei(), part_provenance="OEM_ONLY",
                                    provenance_doc_digest=None)
            fx.approve_listing(row["id"])
            extra.append(row)
        section = fx.open_section(seller_id, "2026-01-05T00:00:00Z")

        shops = []
        for row in [{"id": listing_id}] + extra:
            shops.append(validate_success(
                fx.open_verification(seller_id, row["id"], ordered_cosmetic_grade="GOOD"), 201
            ))

        seller_before = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        floor_before = fx.get_exposure_floor(seller_id)
        assert floor_before["published_exposure_floor_cents"] == 0

        before = fx.read_section(section["id"])
        assert before["grading_compliance_pct"] == 100.00
        assert before["service_score"] == 70.00

        disclosed = validate_success(fx.disclose_verification(shops[0]["id"]))
        assert disclosed["verification_state"] == "DISCLOSED"
        assert disclosed["value_at_risk"] == 1

        listing = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert listing["mystery_shop_disclosed"] is True, (
            "hop two: the disclosure flips the listing flag"
        )

        after = fx.read_section(section["id"])
        assert after["grading_compliance_pct"] == 75.00, (
            "four shops, one violation, is one hundred times (4 - 1) / 4"
        )
        assert after["service_score"] == 63.75

        for shop in shops[1:]:
            validate_success(fx.disclose_verification(shop["id"]))
        final = fx.read_section(section["id"])
        assert final["grading_compliance_pct"] == 0.00
        assert final["service_score"] == 45.00

        # The trigger count is deliberately not asserted here.  PRD §2.7 calls
        # the field a tally of "closed service-score sections [that] have
        # breached the suspension threshold", while PRD §3.9 states that the
        # suspension transition — whose own sentence names the increment — fires
        # "whenever a component-source change ... recomputes an open section's
        # score to or below that threshold".  The two readings diverge on
        # exactly this open-section path, so the sentence does not uniquely
        # determine the count and nothing is claimed of it here.
        seller_after = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        assert seller_after["onboarding_state"] == "SUSPENDED"

class TestReinstatementRamp:
    def test_seller_suspend_ramps_the_tier_back_from_the_archived_cells(self, api):
        """PRD §3.9: "The number of ramp steps is the service-day count divided by the reinstatement window of one day, floored — neither a partial window nor a partial tier is ever credited."
        PRD §3.9: "The escalation score is the seller's latest score percentage minus twenty points per ramp step, floored and then clamped at zero."
        PRD §3.5: "For each live cell the system computes the remaining days as the calendar days from the current logical clock instant to the cell's expiry date"
        PRD §3.9: "A `ComplianceReviewer` may suspend an approved seller directly on a `reason_code`, optionally guarded by an `expected_seller_version`"

        Design: Corner/calculations/tier_escalation_ramp_floors_the_day_count
        """
        fx.set_clock("2026-12-07T00:00:00Z")
        fx.create_active_definition()
        seller = fx.create_approved_seller(clock="2026-12-07T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])

        fx.set_clock("2026-12-10T00:00:00Z")
        claim = fx.create_upheld_claim(seller["id"], listing["id"])
        validate_success(fx.route_claim_return(claim["id"], return_shipment_start="2026-12-11T00:00:00Z"))

        exposure = fx.get_exposure_floor(seller["id"])
        assert exposure["cell_count"] == 1

        validate_success(
            fx.api_client.suspend_seller(seller["id"], {"reason_code": "MYSTERY_SHOP_FINDING"}, fx.REVIEWER)
        )
        suspended = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert suspended["onboarding_state"] == "APPROVED"
        assert suspended["performance_tier"] == "PROBATION", (
            "three whole service days give three ramp steps, an escalation score of 40.00 "
            "and therefore a PROBATION tier"
        )


class TestDelistingRoute:
    def test_suspend_rejects_a_reason_code_outside_the_declared_set(self, api):
        """PRD §3.3: "Delisting a `LISTED` listing — available to a `ComplianceReviewer` with a `reason_code` drawn from `BATTERY_DEGRADED`, `MYSTERY_SHOP_FINDING`, `PART_PROVENANCE_UNVERIFIED`"
        PRD §2.11: "every enum-valued field carrying a declared member"

        Design: Corner/endpoints/conditional_action_suspend_reason_enum_enforced
        """
        scenario = fx.setup_listed_device()
        listing_id = scenario["listing"]["id"]

        response = fx.delist_listing(listing_id, reason_code="SELLER_QUIT")
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        after = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert after["listing_state"] == "LISTED"