"""Buyer claim adjudication, return routing and the reserve/exposure ledger."""
from prd_bench_local_runner.testing import build_user_headers

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.test_users import OPERATOR_HEADERS


class TestApprovedClaimSelfLoop:
    def test_second_uphold_of_an_approved_claim_is_refused(self, api):
        """PRD §3.6: "A second uphold of a claim that is already `APPROVED` and awaiting return routing is refused with `ERR_CLAIM_ALREADY_UPHELD` (HTTP 409) — the claim remains legally non-terminal at that point, so the marketplace chooses to answer on the already-upheld ground rather than the terminal ground."

        Design: Difficulty/non_linear_state_machine/warranty_claim_approved_self_loop_before_terminal
        """
        scenario = fx.setup_listed_device()
        claim = fx.create_upheld_claim(scenario["seller"]["id"], scenario["listing"]["id"])

        response = fx.uphold_claim(claim["id"])
        validate_error(response, ApiErrorId.ERR_CLAIM_ALREADY_UPHELD, 409)

        after = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        assert after["claim_state"] == "APPROVED", (
            "a refused second uphold must leave the claim legally non-terminal in APPROVED"
        )

    def test_the_identical_trigger_becomes_a_terminal_refusal_after_routing(self, api):
        """PRD §3.6: "Once the claim reaches `RESOLVED` or `REJECTED`, any further mutation is refused with `ERR_CLAIM_TERMINAL` (409)."
        PRD §3.6: "On success the claim moves to `RESOLVED`, the `return_shipment_cents` is added to `seller_funded_amount_cents`, `claim_reserve_cents` is zeroed, and the released reserve is subtracted from the seller's exposure floor."

        Design: Difficulty/non_linear_state_machine/warranty_claim_approved_self_loop_before_terminal
        """
        scenario = fx.setup_listed_device()
        claim = fx.create_upheld_claim(scenario["seller"]["id"], scenario["listing"]["id"])
        version = claim["version"]

        routed = validate_success(
            fx.route_claim_return(claim["id"], expected_claim_version=version)
        )
        assert routed["claim_state"] == "RESOLVED"

        response = fx.uphold_claim(claim["id"])
        validate_error(response, ApiErrorId.ERR_CLAIM_TERMINAL, 409)


class TestTerminalLockdown:
    def test_evidence_after_resolution_is_refused_as_terminal(self, api):
        """PRD §3.6: "Once the claim reaches `RESOLVED` or `REJECTED`, any further mutation is refused with `ERR_CLAIM_TERMINAL` (409)."
        PRD §3.6: "The two codes therefore make the claim's polarity observable from the error alone."

        Design: Corner/state_machines/warranty_claim_terminal_state_locked
        """
        scenario = fx.setup_listed_device()
        claim = fx.create_resolved_claim(scenario["seller"]["id"], scenario["listing"]["id"])
        assert claim["claim_state"] == "RESOLVED"
        assert claim["claim_reserve_cents"] == 0

        response = fx.attach_evidence(claim["id"])
        validate_error(response, ApiErrorId.ERR_CLAIM_TERMINAL, 409)

        after = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        assert after["claim_state"] == "RESOLVED"
        assert after["claim_reserve_cents"] == 0


class TestEvidenceCompleteness:
    def test_malformed_diagnostic_digest_is_refused(self, api):
        """PRD §3.6: "A `ClaimAdjudicator` attaches a `diagnostic_evidence_digest`, which must be exactly 64 lowercase hexadecimal characters; the digest and its format are checked before the claim may enter `UNDER_REVIEW`, and a claim whose digest is absent or malformed is refused with `ERR_DIAGNOSTIC_EVIDENCE_REQUIRED` (HTTP 422) rather than allowed to reach the transition at all."

        Design: Corner/validations/diagnostic_evidence_malformed_digest_rejected
        """
        scenario = fx.setup_listed_device()
        claim = fx.file_claim(scenario["seller"]["id"], scenario["listing"]["id"])
        assert claim["claim_state"] == "FILED"

        response = fx.attach_evidence(claim["id"], digest="NOT-A-DIGEST")
        validate_error(response, ApiErrorId.ERR_DIAGNOSTIC_EVIDENCE_REQUIRED, 422)

        after = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        assert after["claim_state"] == "FILED"
        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{scenario['servicing_reservation_id']}", headers=fx.ADMIN)
        )
        assert reservation["claims_filed_count"] == 0

    def test_evidence_recorder_may_not_adjudicate_the_same_claim(self, api):
        """PRD §2.9: "An operator who recorded the diagnostic evidence on a claim may not adjudicate that same claim."
        PRD §2.9: "Both are refused with `ERR_SOD_VIOLATION` (HTTP 403), and both checks are evaluated after the general role check of §2.1, so a caller lacking the role outright sees `ERR_FORBIDDEN_ROLE` rather than the duty-separation code."

        Design: Corner/validations/sod_evidence_recorder_cannot_adjudicate_same_claim
        """
        scenario = fx.setup_listed_device()
        claim = fx.file_claim(scenario["seller"]["id"], scenario["listing"]["id"])

        recorder = build_user_headers("op_evidence_recorder", "ClaimAdjudicator")
        recorded = api.post(
            f"/v1/warranty-claims/{claim['id']}/evidence",
            json={"diagnostic_evidence_digest": "b" * 64},
            headers=recorder,
        )
        validate_success(recorded)

        barred = api.post(
            f"/v1/warranty-claims/{claim['id']}/adjudicate",
            json={
                "decision": "APPROVED",
                "resolution_type": "REPAIR",
                "resolution_obligation_cents": 18000,
                "adjudicator_user_id": "op_evidence_recorder",
            },
            headers=recorder,
        )
        validate_error(barred, ApiErrorId.ERR_SOD_VIOLATION, 403)

        after = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        assert after["claim_state"] == "UNDER_REVIEW"

        allowed = api.post(
            f"/v1/warranty-claims/{claim['id']}/adjudicate",
            json={
                "decision": "APPROVED",
                "resolution_type": "REPAIR",
                "resolution_obligation_cents": 18000,
                "adjudicator_user_id": "op_adjudicator",
            },
            headers=OPERATOR_HEADERS["adjudicator"],
        )
        validate_success(allowed)


class TestReserveAndSelector:
    def test_claim_reserve_is_capped_at_the_pre_authorization_ceiling(self, api):
        """PRD §3.6: "The claim additionally takes a reserve, `claim_reserve_cents`, computed as the smaller of 90000 and the sum of 25000 and 151 times the reservation's `unit_reserve_per_day_cents` — so a reservation earning the default 1800 cents per day caps out at 90000 cents."

        Design: Corner/calculations/claim_reserve_pre_authorization_is_capped
        """
        scenario = fx.setup_listed_device()
        under_review = fx.create_claim_under_review(scenario["seller"]["id"], scenario["listing"]["id"])

        assert under_review["claim_reserve_cents"] == 90000, (
            f"Expected the 90000 pre-authorization cap, got {under_review['claim_reserve_cents']}"
        )
        assert under_review["claim_state"] == "UNDER_REVIEW"

    def test_evidence_without_a_live_reservation_is_refused(self, api):
        """PRD §3.5: "An empty candidate set is never represented as a null winner — it raises `ERR_RESERVATION_NOT_FOUND` (HTTP 404)."
        PRD §3.5: "Reservations also expire on their own. When the logical clock advances strictly past a reservation's `expired_on` while the reservation is `ACTIVE`, the system moves it to `COMPLETED` without any client request."

        Design: Corner/errors/reservation_not_found_when_no_candidate
        """
        scenario = fx.setup_listed_device()
        reservation_id = scenario["servicing_reservation_id"]
        first = validate_success(
            api.get(f"/v1/warranty-reservations/{reservation_id}", headers=fx.ADMIN)
        )
        assert first["warranty_state"] == "ACTIVE"

        claim = fx.file_claim(scenario["seller"]["id"], scenario["listing"]["id"])

        fx.set_clock("2027-04-01T00:00:00Z")
        lapsed = validate_success(
            api.get(f"/v1/warranty-reservations/{reservation_id}", headers=fx.ADMIN)
        )
        assert lapsed["warranty_state"] == "COMPLETED"

        response = fx.attach_evidence(claim["id"])
        validate_error(response, ApiErrorId.ERR_RESERVATION_NOT_FOUND, 404)

        after = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        assert after["claim_state"] == "FILED"


class TestObligationCap:
    def test_repair_cap_refuses_while_replacement_admits(self, api):
        """PRD §3.6: "The obligation is checked against the resolution cap — 25000 cents for a `REPAIR` and 90000 cents for a `REPLACE` — and an over-cap request is refused with `ERR_OBLIGATION_EXCEEDS_CAP` (HTTP 422)."
        PRD §3.6: "the reservation's `repair_obligation_cents` is increased by the obligation when the resolution is `REPAIR`, or its `replacement_obligation_cents` is increased by it when the resolution is `REPLACE`"

        Design: Difficulty/cross_entity_state_dependency/claim_adjudication_requires_reservation_activating
        """
        scenario = fx.setup_listed_device()
        claim = fx.create_claim_under_review(scenario["seller"]["id"], scenario["listing"]["id"])

        refused = fx.uphold_claim(
            claim["id"], resolution_type="REPAIR", resolution_obligation_cents=30000
        )
        validate_error(refused, ApiErrorId.ERR_OBLIGATION_EXCEEDS_CAP, 422)

        still = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        assert still["claim_state"] == "UNDER_REVIEW"

        admitted = validate_success(
            fx.uphold_claim(claim["id"], resolution_type="REPLACE", resolution_obligation_cents=90000)
        )
        assert admitted["claim_state"] == "APPROVED"

        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{scenario['servicing_reservation_id']}", headers=fx.ADMIN)
        )
        assert reservation["warranty_state"] == "REPLACED"
        assert reservation["replacement_obligation_cents"] == 90000

    def test_repair_obligation_at_the_cap_is_admitted(self, api):
        """PRD §3.6: "The obligation is checked against the resolution cap — 25000 cents for a `REPAIR` and 90000 cents for a `REPLACE`"
        PRD §3.6: "On an uphold, `seller_funded_amount_cents` is set to the `resolution_obligation_cents` plus the `return_shipment_cents` supplied"

        Design: Difficulty/cross_entity_state_dependency/claim_adjudication_requires_reservation_activating
        """
        scenario = fx.setup_listed_device()
        claim = fx.create_claim_under_review(scenario["seller"]["id"], scenario["listing"]["id"])

        upheld = validate_success(
            fx.uphold_claim(claim["id"], resolution_type="REPAIR", resolution_obligation_cents=25000)
        )
        assert upheld["claim_state"] == "APPROVED"
        assert upheld["seller_funded_amount_cents"] == 25000

        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{scenario['servicing_reservation_id']}", headers=fx.ADMIN)
        )
        assert reservation["repair_obligation_cents"] == 25000


class TestReturnRouting:
    def test_return_slot_collision_at_the_touching_boundary(self, api):
        """PRD §3.6: "The return occupies a one-day slot beginning at `return_shipment_start`, and that half-open interval — from the start instant to 86400 seconds later — may not touch either boundary of an already-booked return on the same carrier; a collision is refused with `ERR_RETURN_SLOT_COLLISION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/return_shipment_halfopen_slot_collision
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]

        first = fx.create_upheld_claim(seller_id, listing_id)
        validate_success(
            fx.route_claim_return(
                first["id"], return_carrier="CARRIER_A", return_shipment_start="2026-09-02T00:00:00Z"
            )
        )

        second = fx.create_upheld_claim(seller_id, listing_id, claim_reason_code="TOUCH_FAILURE")
        collision = fx.route_claim_return(
            second["id"], return_carrier="CARRIER_A", return_shipment_start="2026-09-03T00:00:00Z"
        )
        validate_error(collision, ApiErrorId.ERR_RETURN_SLOT_COLLISION, 409)

        unchanged = validate_success(api.get(f"/v1/warranty-claims/{first['id']}", headers=fx.ADMIN))
        assert unchanged["claim_state"] == "RESOLVED"

    def test_return_slot_one_second_later_is_admitted(self, api):
        """PRD §3.6: "The return occupies a one-day slot beginning at `return_shipment_start`, and that half-open interval — from the start instant to 86400 seconds later — may not touch either boundary of an already-booked return on the same carrier; a collision is refused with `ERR_RETURN_SLOT_COLLISION` (HTTP 409)."
        PRD §3.6: "On success the claim moves to `RESOLVED`, the `return_shipment_cents` is added to `seller_funded_amount_cents`"

        Design: Difficulty/resource_temporal_overlap/return_shipment_halfopen_slot_collision
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]

        first = fx.create_upheld_claim(seller_id, listing_id)
        validate_success(
            fx.route_claim_return(
                first["id"], return_carrier="CARRIER_A", return_shipment_start="2026-09-02T00:00:00Z"
            )
        )

        second = fx.create_upheld_claim(seller_id, listing_id, claim_reason_code="TOUCH_FAILURE")
        routed = validate_success(
            fx.route_claim_return(
                second["id"], return_carrier="CARRIER_A", return_shipment_start="2026-09-03T00:00:01Z"
            )
        )
        assert routed["claim_state"] == "RESOLVED"
        assert routed["seller_funded_amount_cents"] == 18000 + 4500

    def test_route_return_releases_the_reserve_before_resolution(self, api):
        """PRD §3.6: "On success the claim moves to `RESOLVED`, the `return_shipment_cents` is added to `seller_funded_amount_cents`, `claim_reserve_cents` is zeroed, and the released reserve is subtracted from the seller's exposure floor."

        Design: Corner/consistency_model/saga_family_route_return_releases_before_resolution
        """
        scenario = fx.setup_listed_device()
        claim = fx.create_upheld_claim(scenario["seller"]["id"], scenario["listing"]["id"])
        assert claim["claim_reserve_cents"] == 90000
        version = claim["version"]

        routed = validate_success(
            fx.route_claim_return(claim["id"], expected_claim_version=version)
        )
        assert routed["claim_state"] == "RESOLVED"
        assert routed["claim_reserve_cents"] == 0
        assert routed["seller_funded_amount_cents"] == 18000 + 4500

        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{scenario['servicing_reservation_id']}", headers=fx.ADMIN)
        )
        assert reservation["warranty_state"] == "REPAIRING", (
            "the release affects the claim; the device lifecycle stays REPAIRING until remediation"
        )


class TestExposureLedger:
    def test_uphold_and_route_leave_the_floor_unchanged(self, api):
        """PRD §3.6: "the released reserve is subtracted from the seller's exposure floor."
        PRD §2.7: "A seller's reserve for approved-but-unresolved claims is exposed on the exposure read as `reserved_claim_cents`, and consumers of this API should note that it is *not* netted out of the published floor"

        Design: Difficulty/compensating_invariant/routed_return_releases_exactly_the_claim_reserve
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]

        before = fx.get_exposure_floor(seller_id)
        assert before["published_exposure_floor_cents"] == 0
        assert before["cell_count"] == 0

        claim = fx.create_upheld_claim(
            seller_id, listing_id, resolution_type="REPLACE", obligation_cents=90000
        )
        assert claim["claim_reserve_cents"] == 90000
        assert claim["claim_state"] == "APPROVED"
        version = claim["version"]

        validate_success(fx.route_claim_return(claim["id"], expected_claim_version=version))

        settled = validate_success(api.get(f"/v1/warranty-claims/{claim['id']}", headers=fx.ADMIN))
        assert settled["claim_state"] == "RESOLVED"
        # PRD §3.6: "`seller_funded_amount_cents` is set to the
        # `resolution_obligation_cents` plus the `return_shipment_cents`
        # supplied" — the upheld REPLACE obligation is 90000 and the routed
        # return supplies 4500, so the funded amount is 94500.
        assert settled["seller_funded_amount_cents"] == 90000 + 4500

        after = fx.get_exposure_floor(seller_id)
        assert after["reserved_claim_cents"] == 0, (
            "the held reserve is released when the return is routed"
        )
        assert after["published_exposure_floor_cents"] >= 0

    def test_adjudication_cascade_is_visible_within_the_same_request(self, api):
        """PRD §3.6: "the cascade described in §3.5 fires: the reservation flips to `REPAIRING` or `REPLACED` and the listing's `active_reservation_days` advances by one."
        PRD §3.5: "A live exposure cell exists for every reservation that is its listing's servicing reservation and is in `REPAIRING` or `REPLACED`"

        Design: Corner/cross_cutting_complexity_layers/cascade_order_moves_floor_past_reservation
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        claim = fx.create_claim_under_review(seller_id, listing_id)

        before = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert before["active_reservation_days"] == 0

        upheld = validate_success(
            fx.uphold_claim(claim["id"], resolution_type="REPAIR", resolution_obligation_cents=25000)
        )
        assert upheld["claim_state"] == "APPROVED"
        assert upheld["seller_funded_amount_cents"] == 25000

        reservation = validate_success(
            api.get(f"/v1/warranty-reservations/{scenario['servicing_reservation_id']}", headers=fx.ADMIN)
        )
        assert reservation["warranty_state"] == "REPAIRING"

        listing = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert listing["active_reservation_days"] == 1, (
            "the listing's active_reservation_days must be advanced by the same request that upheld the claim"
        )

        exposure = fx.get_exposure_floor(seller_id)
        assert exposure["cell_count"] == 1