"""Rate complaint filing, track selection, and market dominance (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    SHIPPER_ADA,
    api_client,
    assert_petition,
    assert_rate_complaint,
    create_merger_application_payload,
    create_rate_complaint_payload,
    decide_rate_complaint_payload,
    determine_dominance,
    determine_market_dominance_payload,
    file_abandonment,
    file_petition,
    file_rate_complaint,
    file_service_complaint,
    register_carrier,
    register_merger_pair,
    validate_error,
    validate_paginated,
    validate_success,
    make_carrier_operator_headers,
    make_shipper_headers,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_adjudicator_headers"]


class TestTrackSelectionBoundary:
    def test_relief_cap_boundary_selects_track(self):
        """PRD §3.2: "`relief_sought_cents` of at most 100000000 cents (one
        million dollars) places the complaint on the `THREE_BENCHMARK` track;
        at most 400000000 cents (four million dollars) places it on the
        `SIMPLIFIED_SAC` track; anything larger places it on the `FULL_SAC`
        track."

        Design: Difficulty/boundary_precision_check/relief_cap_boundary_selects_track
        """
        carrier = register_carrier()
        cases = [
            (100000000, "THREE_BENCHMARK"),
            (100000001, "SIMPLIFIED_SAC"),
            (400000000, "SIMPLIFIED_SAC"),
            (400000001, "FULL_SAC"),
        ]
        for relief_sought, expected_track in cases:
            complaint = file_rate_complaint(
                carrier["id"], relief_sought_cents=relief_sought)
            assert_rate_complaint(complaint)
            assert complaint["track"] == expected_track, (
                f"relief_sought_cents={relief_sought}: expected "
                f"{expected_track}, got {complaint['track']}")


class TestMarketDominanceThreshold:
    def test_rvc_threshold_exactly_18000_dominates(self):
        """PRD §3.2: "When the `alleged_rvc_ratio` is at least 1.8000 — a
        ratio of exactly 1.8000 clears the threshold, while 1.7999 does not —
        and neither product competition nor geographic competition exists,
        `market_dominance` is set to `PRESENT` and the complaint advances from
        `FILED` to `EVIDENTIARY_PHASE`."
        PRD §3.2: "When the `alleged_rvc_ratio` is below 1.8000, or product
        competition exists, or geographic competition exists,
        `market_dominance` is set to `ABSENT` and the complaint moves from
        `FILED` to `DISMISSED`, a terminal state."

        Design: Difficulty/boundary_precision_check/rvc_threshold_exactly_18000_dominates
        """
        carrier = register_carrier()
        rc_at = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=18000,
            annual_tons=500, relief_sought_cents=50000000)
        rc_below = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=17999,
            commodity="CORN", annual_tons=500, relief_sought_cents=50000000)
        assert rc_at["alleged_rvc_ratio"] == pytest.approx(1.8000)
        assert rc_below["alleged_rvc_ratio"] == pytest.approx(1.7999)

        decided_at = determine_dominance(rc_at["id"])
        assert decided_at["status"] == "EVIDENTIARY_PHASE"
        assert decided_at["market_dominance"] == "PRESENT"

        decided_below = determine_dominance(rc_below["id"])
        assert decided_below["status"] == "DISMISSED"
        assert decided_below["market_dominance"] == "ABSENT"

    def test_determine_md_on_dismissed_complaint_rejected(self):
        """PRD §3.2: the determination is "performed by a `BoardAdjudicator`
        on a complaint in `FILED` status — a complaint in any other state is
        rejected with `ERR_COMPLAINT_NOT_FILED` (HTTP 409)."

        Design: Corner/state_machines/determine_md_on_dismissed_complaint_rejected
        """
        carrier = register_carrier()
        complaint = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=17999,
            annual_tons=100, relief_sought_cents=50000000)
        dismissed = determine_dominance(complaint["id"])
        assert dismissed["status"] == "DISMISSED"
        resp = api_client.determine_market_dominance(
            complaint["id"], determine_market_dominance_payload(), BOARD)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FILED)
        reread = api_client.get_rate_complaint(complaint["id"], BOARD)
        complaint_after = validate_success(reread)
        assert complaint_after["status"] == "DISMISSED"
        assert complaint_after["market_dominance"] == "ABSENT"


class TestAllegedRatioPrecision:
    def test_alleged_ratio_rounds_to_four_places(self):
        """PRD §3.2: "the **alleged revenue-to-variable-cost ratio**
        `alleged_rvc_ratio` is the `challenged_rate_cents_per_ton` divided by
        the `alleged_variable_cost_cents_per_ton`, rounded half up to 4
        decimal places."

        Design: Corner/calculations/alleged_ratio_rounds_to_four_places
        """
        carrier = register_carrier()
        complaint = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=10001,
            alleged_variable_cost_cents_per_ton=7000, annual_tons=100,
            relief_sought_cents=50000000)
        assert complaint["alleged_rvc_ratio"] == pytest.approx(1.4287)


class TestComplaintCreationValidation:
    def test_missing_required_field_on_complaint_create_rejected(self):
        """PRD §2.6: "every required input field must be present, enum values
        must be in range, numeric bounds must be respected, `service_end_date`
        must be strictly later than `service_start_date`, and the `conditions`
        array must be non-empty where an outcome requires it — any such defect
        is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/missing_required_field_on_complaint_create_rejected
        """
        carrier = register_carrier()
        payload = create_rate_complaint_payload(carrier_id=carrier["id"])
        del payload["challenged_rate_cents_per_ton"]
        resp = api_client.create_rate_complaint(
            payload, make_shipper_headers(SHIPPER_ADA))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_board_cannot_file_rate_complaint_rejected(self):
        """PRD §2.1: "A caller whose role is syntactically valid but not
        listed among the roles authorized for the invoked endpoint is rejected
        with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4 lists POST
        /stb/rate-complaints under authorized role Shipper only.

        Design: Corner/rbac/board_cannot_file_rate_complaint_rejected
        """
        carrier = register_carrier()
        resp = api_client.create_rate_complaint(
            create_rate_complaint_payload(
                carrier_id=carrier["id"], challenged_rate_cents_per_ton=20000,
                annual_tons=100, relief_sought_cents=50000000),
            BOARD,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestComplaintReads:
    def test_get_rate_complaint_not_found_returns_404(self):
        """PRD §2.6: "a missing rate complaint `ERR_RATE_COMPLAINT_NOT_FOUND`"
        (HTTP 404, path existence check)."

        Design: Corner/entities/get_rate_complaint_not_found_returns_404
        """
        resp = api_client.get_rate_complaint(NON_EXISTENT_ID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_RATE_COMPLAINT_NOT_FOUND)

    def test_rate_complaint_list_paginates_with_total_count_and_has_more(self):
        """PRD §2.3: "The `meta` object of a list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`,
        where `total_count` is the number of records matching the query before
        pagination and `has_more` reports whether additional records exist
        beyond the returned window."

        Design: Corner/entities/rate_complaint_list_paginates_with_total_count_and_has_more
        """
        carrier = register_carrier()
        for commodity in ("GRAIN", "CORN", "COAL"):
            file_rate_complaint(
                carrier["id"], commodity=commodity,
                challenged_rate_cents_per_ton=20000, annual_tons=100,
                relief_sought_cents=50000000)
        page1, meta1 = validate_paginated(api_client.list_carrier_rate_complaints(
            carrier["id"], make_shipper_headers(SHIPPER_ADA),
            params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api_client.list_carrier_rate_complaints(
            carrier["id"], make_shipper_headers(SHIPPER_ADA),
            params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestDecideStateGate:
    def test_decide_from_filed_state_rejected(self):
        """PRD §3.3: "The complaint must be in `EVIDENTIARY_PHASE`
        (`ERR_COMPLAINT_NOT_IN_EVIDENTIARY`)."

        Design: Corner/state_machines/decide_from_filed_state_rejected
        """
        carrier = register_carrier()
        complaint = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=20000,
            annual_tons=100, relief_sought_cents=50000000)
        assert complaint["status"] == "FILED"
        resp = api_client.decide_rate_complaint(
            complaint["id"],
            decide_rate_complaint_payload(
                "UPHELD", [{"shipment_ref": "S-1", "tons": 1.000}]),
            BOARD,
        )
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_IN_EVIDENTIARY)
        reread = api_client.get_rate_complaint(complaint["id"], BOARD)
        assert validate_success(reread)["status"] == "FILED"


class TestInitialStates:
    def test_initial_states_on_creation(self):
        """PRD §3.2: "The complaint enters `FILED` status with
        `market_dominance` `UNDETERMINED`, `award_status` `NONE`,
        `adjudicated_rvc_ratio` and `decision_outcome` absent (null), and the
        award and prescription fields at their zero or null defaults."
        PRD §3.6: "The application opens in `COMMENT_PERIOD` status, the
        comment window `comment_close_at` is set to the creation time plus 45
        days, `conditions_imposed` initializes as an empty array,
        `service_review_hold` initializes false (recomputing thereafter with
        the acquiring carrier's order lifecycle)"
        PRD §3.7: "The application opens in `UNDER_REVIEW`, with
        `public_convenience_finding` null and `nitu_expires_at` null."
        PRD §3.5: "The complaint opens in `OPEN` status."
        PRD §3.8: "The petition enters `FILED` status."

        Design: Corner/state_machines/initial_states_on_creation
        """
        carrier = register_carrier()
        target = register_carrier(
            carrier_code="NSOR", legal_name="Northern & Southern Railway",
            carrier_class="II", base_route_miles=640)

        complaint = file_rate_complaint(
            carrier["id"], challenged_rate_cents_per_ton=20000,
            annual_tons=100, relief_sought_cents=50000000)
        assert_rate_complaint(complaint)
        assert complaint["status"] == "FILED"
        assert complaint["market_dominance"] == "UNDETERMINED"
        assert complaint["award_status"] == "NONE"
        assert complaint["track"] == "THREE_BENCHMARK"

        merger_resp = api_client.create_merger_application(
            create_merger_application_payload(
                acquiring_carrier_id=carrier["id"],
                target_carrier_id=target["id"],
                transaction_value_cents=100000000),
            make_carrier_operator_headers(carrier["id"]),
        )
        merger = validate_success(merger_resp, 201)
        assert merger["status"] == "COMMENT_PERIOD"
        # Created at the 2026-09-01T00:00:00Z clock default plus 45 days,
        # rendered exactly as the logical clock read (PRD §2.4).
        assert merger["comment_close_at"] == "2026-10-16T00:00:00Z"
        assert merger["service_review_hold"] is False

        abandonment = file_abandonment(carrier["id"])
        assert abandonment["status"] == "UNDER_REVIEW"
        assert abandonment["nitu_expires_at"] is None

        sc = file_service_complaint(carrier["id"], shipper_id=SHIPPER_ADA)
        assert sc["status"] == "OPEN"

        petition = file_petition(SHIPPER_ADA, carrier["id"], sc["id"])
        assert_petition(petition)
        assert petition["status"] == "FILED"
