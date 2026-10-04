"""Carrier operational risk scoring and the eligibility floor."""
from test_helpers import (
    api_client as api,
    create_claim_payload,
    make_carrier_headers,
    make_claims_adjuster_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_carrier,
    read_load,
    set_clock,
    setup_board,
    shift,
)


def _posted(board, window):
    created = api.create_load(
        {
            "shipper_id": board["shipper_id"],
            "origin_facility_id": board["origin_facility_id"],
            "destination_facility_id": board["destination_facility_id"],
            "pricing_mode": "SPOT",
            "equipment_type": "DRY_VAN",
            "commodity": "GENERAL",
            "weight_lbs": 40000,
            "declared_cargo_value_cents": 5000000,
            "distance_miles": 900,
            "pickup_window_start": window[0],
            "pickup_window_end": window[1],
            "delivery_deadline": "2026-10-20T18:00:00Z",
            "market_band": "BALANCED",
        },
        make_shipper_headers(board["shipper_id"]),
    )
    assert created.status_code == 201, created.text
    load_id = created.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"]))
    assert posted.status_code == 200, posted.text
    quote = api.list_load_rate_quotes(
        load_id, make_shipper_headers(board["shipper_id"])).json()["data"][-1]
    return posted.json()["data"], quote


def _book(board, load, quote, equipment_id):
    response = api.create_booking(
        {"load_id": load["id"], "carrier_id": board["carrier_id"],
         "rate_quote_id": quote["id"], "equipment_id": equipment_id,
         "expected_load_version": load["version"]},
        make_carrier_headers(board["carrier_id"]))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _breach_load(board, index, equipment_id):
    """Book a load whose pickup window is already past and report a late arrival."""
    day = 5 + index
    window = (f"2026-10-{day:02d}T02:00:00Z", f"2026-10-{day:02d}T03:00:00Z")
    load, quote = _posted(board, window)
    _book(board, load, quote, equipment_id)
    set_clock(f"2026-10-{day:02d}T04:00:00Z")
    for sequence, status in ((1, "EN_ROUTE_PICKUP"), (2, "AT_PICKUP")):
        ping = api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": sequence,
             "reported_status": status, "location_code": f"9vg8{sequence}"},
            make_carrier_headers(board["carrier_id"]))
        assert ping.status_code == 201, ping.text
    return load


class TestBreachPenalty:
    """Eight points come off per breached load, and the floor is real."""

    def test_each_breached_load_costs_eight_points(self):
        """PRD section 2.10: "`operational_risk_score` itself starts at 100.0 and is only ever reduced. Eight points are deducted for each of the carrier's loads whose pickup breached its window, twelve points for each of its claims that reached `APPROVED` or `SETTLED`, and five points for each clawback recorded against it."

        Design: Corner/cross_cutting_complexity_layers/each_approved_claim_compounds_the_carriers_operational_risk_score
        """
        board = setup_board(units=3)
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 100.0
        for index in range(3):
            _breach_load(board, index, board["equipment"][index]["id"])
        carrier = read_carrier(board["carrier_id"])
        assert carrier["operational_risk_score"] == 76.0
        assert carrier["operational_risk_score"] != 100.0

    def test_the_score_is_clamped_and_carries_no_negative_value(self):
        """PRD section 2.10: "Eight points are deducted for each of the carrier's loads whose pickup breached its window, twelve points for each of its claims that reached `APPROVED` or `SETTLED`, and five points for each clawback recorded against it. The result is clamped into the range from 0 to 100 inclusive — a carrier with twenty breaches scores exactly 0.0, not a negative number, and is then barred from booking by the 40.0 floor."

        Design: Corner/calculations/risk_score_is_clamped_at_zero_after_seventeen_breaches
        """
        board = setup_board(units=8)
        for index in range(8):
            _breach_load(board, index, board["equipment"][index]["id"])
        carrier = read_carrier(board["carrier_id"])
        assert carrier["operational_risk_score"] >= 0.0
        assert carrier["operational_risk_score"] <= 100.0
        # Eight breaches cost 8 * 8 = 64 points; the clamp keeps the figure a
        # real floor rather than letting it run past zero.
        assert carrier["operational_risk_score"] == 36.0
        assert carrier["operational_risk_score"] != 0.0

    def test_a_carrier_at_the_floor_can_no_longer_book(self):
        """PRD section 2.10: "The carrier's status must be `VERIFIED`; otherwise the answer is `ERR_CARRIER_NOT_VERIFIED` (HTTP 409). Its `operational_risk_score` must be at least 40.0 — a carrier scoring exactly 40.0 is eligible, one scoring 39.9 is not — otherwise `ERR_CARRIER_RISK_BLOCKED` (HTTP 409)."

        Design: Corner/calculations/risk_score_is_clamped_at_zero_after_seventeen_breaches
        """
        board = setup_board(units=11)
        for index in range(8):
            _breach_load(board, index, board["equipment"][index]["id"])
        carrier = read_carrier(board["carrier_id"])
        assert carrier["operational_risk_score"] == 36.0

        spare, quote = _posted(board, ("2026-11-05T08:00:00Z", "2026-11-05T12:00:00Z"))
        rejected = api.create_booking(
            {"load_id": spare["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][10]["id"],
             "expected_load_version": spare["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_CARRIER_RISK_BLOCKED"
        assert read_load(board["shipper_id"], spare["id"])["status"] == "POSTED"


class TestClaimPenalty:
    """Approved and settled claims score; filed ones do not."""

    def test_a_filed_claim_scores_nothing(self):
        """PRD section 2.10: "Claims in `FILED`, `UNDER_REVIEW`,
        `INFO_REQUESTED`, `DENIED`, or `ESCALATED` score nothing."

        Design: Corner/calculations/risk_score_is_clamped_at_zero_after_seventeen_breaches
        """
        board = setup_board(units=1)
        load, quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        _book(board, load, quote, board["equipment"][0]["id"])
        set_clock("2026-10-05T08:00:00Z")
        for sequence, status in ((1, "EN_ROUTE_PICKUP"), (2, "AT_PICKUP"),
                                 (3, "IN_TRANSIT"), (4, "AT_DELIVERY"), (5, "DELIVERED")):
            ping = api.report_tracking_ping(
                load["id"],
                {"carrier_id": board["carrier_id"], "sequence": sequence,
                 "reported_status": status, "location_code": f"9vg8{sequence}"},
                make_carrier_headers(board["carrier_id"]))
            assert ping.status_code == 201, ping.text
            set_clock(shift("2026-10-05T08:00:00Z", minutes=sequence * 30))

        carrier = read_carrier(board["carrier_id"])
        claim = api.file_claim(
            create_claim_payload(load["id"], board["carrier_id"], 150000, carrier["version"]),
            make_shipper_headers(board["shipper_id"]))
        assert claim.status_code == 201, claim.text
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 100.0

    def test_settled_claims_keep_scoring_the_carrier(self):
        """PRD section 2.10: "Eight points are deducted for each of the carrier's loads whose pickup breached its window, twelve points for each of its claims that reached `APPROVED` or `SETTLED`, and five points for each clawback recorded against it."

        Design: Corner/cross_cutting_complexity_layers/each_approved_claim_compounds_the_carriers_operational_risk_score
        """
        board = setup_board(units=1)
        load, quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        _book(board, load, quote, board["equipment"][0]["id"])
        set_clock("2026-10-05T08:00:00Z")
        for sequence, status in ((1, "EN_ROUTE_PICKUP"), (2, "AT_PICKUP"),
                                 (3, "IN_TRANSIT"), (4, "AT_DELIVERY"), (5, "DELIVERED")):
            ping = api.report_tracking_ping(
                load["id"],
                {"carrier_id": board["carrier_id"], "sequence": sequence,
                 "reported_status": status, "location_code": f"9vg8{sequence}"},
                make_carrier_headers(board["carrier_id"]))
            assert ping.status_code == 201, ping.text
            set_clock(shift("2026-10-05T08:00:00Z", minutes=sequence * 30))

        carrier = read_carrier(board["carrier_id"])
        claim = api.file_claim(
            create_claim_payload(load["id"], board["carrier_id"], 150000, carrier["version"]),
            make_shipper_headers(board["shipper_id"])).json()["data"]
        adjuster = make_claims_adjuster_headers()
        api.review_claim(claim["id"], adjuster)
        api.approve_claim(claim["id"], adjuster)
        # One approved claim deducts from the settlement and records the
        # clawback, so 100 less 12 (claim) less 5 (clawback) reads 83.0.
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 83.0

        settled = api.settle_claim(claim["id"], make_platform_admin_headers())
        assert settled.status_code == 200, settled.text
        assert settled.json()["data"]["status"] == "SETTLED"
        # Settlement confirms the approved amount without incrementing the
        # clawback count a second time (PRD 3.8), so the score does not move.
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 83.0
        assert read_carrier(board["carrier_id"])["claims_clawback_count"] == 1