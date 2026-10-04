"""Listing submission, the eligibility ladder, review, delisting and the re-listing loop."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import create_listing_payload, next_imei


class TestEligibilityLadder:
    def test_undeclared_cosmetic_grade_is_refused(self, api):
        """PRD §3.2: "the `cosmetic_grade` is one of `FLAWLESS`, `GOOD`, `FAIR`, `POOR`"
        PRD §2.11: "Priority 2 is request-shape validation — every required input field present and type-conformant, every enum-valued field carrying a declared member, every numeric field inside its declared range (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/entities/device_listing_enum_type_constraint_rejected
        """
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]

        response = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(cosmetic_grade="PRISTINE", imei=next_imei()),
            fx.make_seller_headers(seller_id),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        rows, meta = fx.list_seller_listings(seller_id)
        assert meta["total_count"] == 1, "the refused submission must not create a row"

    def test_duplicate_imei_for_the_same_seller_is_refused(self, api):
        """PRD §3.2: "The `imei` is exactly fifteen digits and must be unique across all listings that have not been withdrawn"
        PRD §3.2: "No other non-withdrawn listing belonging to the same seller may already carry the same `imei`, or the submission fails with `ERR_IMEI_ALREADY_LISTED`."

        Design: Corner/errors/imei_already_listed_for_same_seller
        """
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]
        existing_imei = scenario["listing"]["imei"]

        response = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(imei=existing_imei, part_provenance="OEM_ONLY",
                                      provenance_doc_digest=None),
            fx.make_seller_headers(seller_id),
        )
        validate_error(response, ApiErrorId.ERR_IMEI_ALREADY_LISTED, 422)

        rows, meta = fx.list_seller_listings(seller_id)
        non_withdrawn = [row for row in rows if row["listing_state"] != "WITHDRAWN"]
        assert len(non_withdrawn) == 1

    def test_unapproved_seller_cannot_hold_a_listing(self, api):
        """PRD §3.2: "The owning seller must be `APPROVED` — an `APPLICANT`, `DOCUMENT_VERIFIED`, `AUDIT_SCHEDULED` or `REJECTED` seller may neither hold nor submit listings, and such an attempt is refused with `ERR_SELLER_NOT_APPROVED`."

        Design: Corner/errors/verified_seller_without_documents_rejected
        """
        # Every higher-priority eligibility rule is constructed to hold: the
        # model is in the catalogue, the IMEI is on neither blocklist, the
        # battery is at the floor, the price is not adrift and no document is
        # needed for OEM_ONLY parts.  Only seller standing is violated.
        fx.create_active_definition()
        seller = fx.create_verified_seller()
        assert seller["onboarding_state"] == "DOCUMENT_VERIFIED"

        response = fx.api_client.create_listing(
            seller["id"],
            create_listing_payload(imei=next_imei(), part_provenance="OEM_ONLY",
                                      provenance_doc_digest=None),
            fx.make_seller_headers(seller["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SELLER_NOT_APPROVED, 422)

        rows, meta = fx.list_seller_listings(seller["id"])
        assert meta["total_count"] == 0

    def test_undocumented_non_original_parts_are_refused(self, api):
        """PRD §3.2: "`OEM_ONLY` needs no document, whereas `OEM_EQUIVALENT` and `AFTERMARKET` both require a `provenance_doc_digest`, which must be exactly 64 lowercase hexadecimal characters. A missing or malformed digest under either of those provenances is refused with `ERR_PART_PROVENANCE_UNDOCUMENTED`."

        Design: Corner/errors/provenance_digest_absent_for_aftermarket_parts
        """
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]

        refused = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(
                part_provenance="AFTERMARKET", provenance_doc_digest=None, imei=next_imei()
            ),
            fx.make_seller_headers(seller_id),
        )
        validate_error(refused, ApiErrorId.ERR_PART_PROVENANCE_UNDOCUMENTED, 422)

        admitted = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(
                part_provenance="AFTERMARKET", provenance_doc_digest="c" * 64, imei=next_imei()
            ),
            fx.make_seller_headers(seller_id),
        )
        validate_success(admitted, 201)

    def test_price_far_below_the_catalogue_floor_is_refused(self, api):
        """PRD §3.2: "When a listing's `list_price_cents` is more than 50 percent below the model's catalogue floor — the `price_deviation_pct` tolerance — the submission is refused with `ERR_COUNTERFEIT_PRICE_SIGNAL`."

        Design: Corner/errors/counterfeit_price_signal_below_catalog_floor
        """
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]
        floor = fx.model_catalog_floor("APL-IP13-128")

        refused = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(
                imei=next_imei(), list_price_cents=1000,
                part_provenance="OEM_ONLY", provenance_doc_digest=None,
            ),
            fx.make_seller_headers(seller_id),
        )
        validate_error(refused, ApiErrorId.ERR_COUNTERFEIT_PRICE_SIGNAL, 422)

        admitted = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(
                imei=next_imei(), list_price_cents=floor,
                part_provenance="OEM_ONLY", provenance_doc_digest=None,
            ),
            fx.make_seller_headers(seller_id),
        )
        validate_success(admitted, 201)


class TestRelistingLoop:
    def test_review_of_a_delisted_listing_is_refused_on_the_state_ground(self, api):
        """PRD §3.3: "A `ComplianceReviewer` rules on a listing that is `UNDER_REVIEW` by supplying a `decision` and a `reviewer_user_id`."
        PRD §2.11: "State checks occupy 17 through 19 in the order `ERR_INVALID_STATE` (409)"

        Design: Difficulty/non_linear_state_machine/device_listing_parent_gated_relisting_loop
        """
        scenario = fx.setup_listed_device()
        listing_id = scenario["listing"]["id"]
        seller_id = scenario["seller"]["id"]

        delisted = validate_success(fx.delist_listing(listing_id))
        assert delisted["listing_state"] == "DELISTED"

        response = fx.api_client.review_listing(
            listing_id, {"decision": "APPROVED", "reviewer_user_id": "op_reviewer"}, fx.REVIEWER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        after = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert after["listing_state"] == "DELISTED"

    def test_delisted_listing_relists_while_the_parent_stays_approved(self, api):
        """PRD §3.2: "Re-submission exists for listings that failed review or were delisted or suspended. The seller supplies `expected_seller_version` alongside the re-submission, the full eligibility ladder is re-run from scratch, and the then-`ACTIVE` grading definition is re-captured onto the listing."
        PRD §2.10: "When the supplied value does not equal the referenced seller's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/non_linear_state_machine/device_listing_parent_gated_relisting_loop
        """
        scenario = fx.setup_listed_device()
        listing_id = scenario["listing"]["id"]
        seller_id = scenario["seller"]["id"]

        validate_success(fx.delist_listing(listing_id))
        version = fx.current_seller_version(seller_id)

        resubmitted = validate_success(fx.resubmit_listing(listing_id, seller_id, version))
        assert resubmitted["listing_state"] == "UNDER_REVIEW"

    def test_relisting_is_refused_once_the_parent_is_not_approved(self, api):
        """PRD §3.2: "The owning seller must be `APPROVED` — an `APPLICANT`, `DOCUMENT_VERIFIED`, `AUDIT_SCHEDULED` or `REJECTED` seller may neither hold nor submit listings, and such an attempt is refused with `ERR_SELLER_NOT_APPROVED`."
        PRD §3.2: "Re-submission exists for listings that failed review or were delisted or suspended."

        Design: Difficulty/non_linear_state_machine/device_listing_parent_gated_relisting_loop
        """
        scenario = fx.setup_listed_device()
        listing_id = scenario["listing"]["id"]
        seller_id = scenario["seller"]["id"]

        validate_success(fx.delist_listing(listing_id))
        validate_success(
            fx.api_client.blocklist_seller(seller_id, fx.blocklist_payload(finding="CONFIRMED_STOLEN"), fx.REVIEWER)
        )
        blocked = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        assert blocked["onboarding_state"] == "SUSPENDED"

        version = fx.current_seller_version(seller_id)
        response = fx.resubmit_listing(listing_id, seller_id, version)
        validate_error(response, ApiErrorId.ERR_SELLER_NOT_APPROVED, 422)


class TestWithdrawal:
    def test_withdraw_from_listed_is_refused(self, api):
        """PRD §3.2: "a `Seller` may withdraw a listing carrying a `withdrawal_reason` while it is `DRAFT`, `UNDER_REVIEW` or `DELISTED`, but not while any claim against it sits in `FILED`, `UNDER_REVIEW` or `APPROVED`, and not while its reservation is `REPAIRING`"
        PRD §2.11: "State checks occupy 17 through 19 in the order `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/listing_withdraw_from_listed_rejected
        """
        scenario = fx.setup_listed_device()
        listing_id = scenario["listing"]["id"]
        seller_id = scenario["seller"]["id"]

        response = fx.withdraw_listing(listing_id, seller_id)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        after = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert after["listing_state"] == "LISTED"
        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{scenario['servicing_reservation_id']}", headers=fx.ADMIN)
        )
        assert reservation["warranty_state"] == "ACTIVE"

    def test_withdrawal_releases_the_imei_for_reuse(self, api):
        """PRD §3.2: "Withdrawal releases the IMEI for reuse, because the uniqueness filter excludes withdrawn rows."
        PRD §3.2: "Re-submission exists for listings that failed review or were delisted or suspended."

        Design: Corner/entities/withdrawn_listing_releases_imei_uniqueness
        """
        scenario = fx.setup_listed_device()
        listing_id = scenario["listing"]["id"]
        seller_id = scenario["seller"]["id"]
        imei = scenario["listing"]["imei"]

        validate_success(fx.delist_listing(listing_id))
        withdrawn = validate_success(fx.withdraw_listing(listing_id, seller_id))
        assert withdrawn["listing_state"] == "WITHDRAWN"

        # PRD §3.2: "Withdrawal releases the IMEI for reuse, because the uniqueness
        # filter excludes withdrawn rows."  The release is observable by
        # submitting a brand-new listing that carries the withdrawn row's IMEI:
        # the duplicate-IMEI screen ignores withdrawn rows, so this second
        # submission must be admitted rather than refused.
        replacement = validate_success(
            fx.api_client.create_listing(
                seller_id,
                create_listing_payload(imei=imei, part_provenance="OEM_ONLY",
                                       provenance_doc_digest=None),
                fx.make_seller_headers(seller_id),
            ),
            201,
        )
        assert replacement["imei"] == imei, "withdrawal released the IMEI for reuse"
        assert replacement["listing_state"] == "UNDER_REVIEW"

    def test_withdrawn_listing_stays_queryable_by_id(self, api):
        """PRD §3.2: "Withdrawal releases the IMEI for reuse, because the uniqueness filter excludes withdrawn rows."
        PRD §2.3: "Listing lists may be narrowed by `listing_state`, by `model_code`, by `servicing_seller_id`, and by `servicing_reservation_id`."

        Design: Corner/cross_cutting_complexity_layers/soft_delete_withdrawn_listing_queryable_by_id
        """
        scenario = fx.setup_listed_device()
        listing_id = scenario["listing"]["id"]
        seller_id = scenario["seller"]["id"]

        second = fx.create_listing(seller_id, imei=next_imei(), part_provenance="OEM_ONLY",
                                   provenance_doc_digest=None)
        fx.approve_listing(second["id"])

        validate_success(fx.delist_listing(listing_id))
        validate_success(fx.withdraw_listing(listing_id, seller_id))

        archived = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert archived["listing_state"] == "WITHDRAWN"

        rows, meta = fx.list_seller_listings(seller_id, {"listing_state": "WITHDRAWN"})
        assert meta["total_count"] == 1
        assert rows[0]["id"] == listing_id

        listed_rows, listed_meta = fx.list_seller_listings(seller_id, {"listing_state": "LISTED"})
        assert listed_meta["total_count"] == 1
        assert listed_rows[0]["id"] == second["id"]


class TestReviewAndDefinitionBinding:
    def test_review_requires_the_captured_definition_still_active(self, api):
        """PRD §3.3: "Before the decision is honoured, the server re-reads the grading definition captured at submission time and confirms it is still `ACTIVE`; a definition retired in the interim produces `ERR_GRADING_DEFINITION_NOT_ACTIVE` (409)."
        PRD §2.6: "that captured value is never re-resolved afterwards."

        Design: Difficulty/cross_entity_state_dependency/listing_review_requires_captured_definition_active
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        definition = fx.create_active_definition(effective_from="2026-08-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        assert listing["listing_state"] == "UNDER_REVIEW"

        validate_success(
            fx.api_client.retire_grading_definition(
                definition["id"], {"retirement_note": "superseded"}, fx.REVIEWER
            )
        )
        retired = validate_success(api.get(f"/v1/grading-definitions/{definition['id']}", headers=fx.ADMIN))
        assert retired["definition_state"] == "RETIRED"

        response = fx.api_client.review_listing(
            listing["id"], {"decision": "APPROVED", "reviewer_user_id": "op_reviewer"}, fx.REVIEWER
        )
        validate_error(response, ApiErrorId.ERR_GRADING_DEFINITION_NOT_ACTIVE, 409)

        after = validate_success(api.get(f"/v1/listings/{listing['id']}", headers=fx.ADMIN))
        assert after["listing_state"] == "UNDER_REVIEW"

        rows, meta = validate_paginated(
            api.get(f"/v1/listings/{listing['id']}/warranty-reservations", headers=fx.ADMIN)
        )
        assert meta["total_count"] == 0, "a blocked transition must not fire the reservation cascade"

    def test_approval_opens_the_servicing_reservation(self, api):
        """PRD §3.3: "An approval moves the listing to `LISTED` and, in the same transaction, opens a warranty reservation against it: the reservation starts in `ACTIVE`, its `activated_on` is the current logical clock instant, its `warranty_period_days` is the default 180, its `reserved_units` is 1, and its `unit_reserve_per_day_cents` is the default 1800."
        PRD §3.3: "The listing's `servicing_reservation_id` is pointed at that reservation."

        Design: Corner/endpoints/endpoint_side_effect_creates_servicing_reservation
        """
        scenario = fx.setup_listed_device()

        assert scenario["listing"]["servicing_reservation_id"] is not None
        rows, meta = validate_paginated(
            api.get(f"/v1/listings/{scenario['listing']['id']}/warranty-reservations", headers=fx.ADMIN)
        )
        assert meta["total_count"] == 1
        reservation = rows[0]
        assert reservation["warranty_state"] == "ACTIVE"
        assert reservation["warranty_period_days"] == 180
        assert reservation["reserved_units"] == 1
        assert reservation["unit_reserve_per_day_cents"] == 1800
        assert scenario["listing"]["listing_state"] == "LISTED"


class TestGradingDefinitionCycle:
    def test_retire_before_effective_from_is_refused(self, api):
        """PRD §2.6: "`effective_from` (the instant from which a definition becomes binding for listings submitted after it)"
        PRD §3.3: "Before the decision is honoured, the server re-reads the grading definition captured at submission time and confirms it is still `ACTIVE`"

        Design: Corner/state_machines/grading_definition_retire_requires_clock_past_effective_from
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        definition = fx.create_active_definition(effective_from="2027-01-01T00:00:00Z")

        response = fx.api_client.retire_grading_definition(
            definition["id"], {"retirement_note": "too early"}, fx.REVIEWER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        after = validate_success(api.get(f"/v1/grading-definitions/{definition['id']}", headers=fx.ADMIN))
        assert after["definition_state"] == "ACTIVE"

    def test_retire_then_reinstate_completes_the_cycle(self, api):
        """PRD §2.6: "`retired_on` (null while the definition is `DRAFT` or `ACTIVE`)"
        PRD §2.6: "Activation and reinstatement each accept an optional `expected_definition_version` when the caller wishes to guard against re-activating a definition it has not re-read."

        Design: Corner/state_machines/grading_definition_retire_then_reinstate_cycle
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        definition = fx.create_active_definition(effective_from="2026-08-01T00:00:00Z", battery_floor_pct=79)

        retired = validate_success(
            fx.api_client.retire_grading_definition(
                definition["id"], {"retirement_note": "seasonal rotation"}, fx.REVIEWER
            )
        )
        assert retired["definition_state"] == "RETIRED"

        reinstated = validate_success(
            fx.api_client.reinstate_grading_definition(definition["id"], fx.REVIEWER)
        )
        assert reinstated["definition_state"] == "ACTIVE"
        assert reinstated["retired_on"] is None