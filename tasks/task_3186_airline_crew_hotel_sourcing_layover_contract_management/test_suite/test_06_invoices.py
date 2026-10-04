"""Invoice reconciliation: per-line rounding, input-set filtering, variance
variants, fiscal gate, dispute/re-reconcile loop, and RBAC denials."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_invoice, make_confirmed_booking, make_checked_in_booking,
    make_station_and_union, make_vendor, make_active_contract,
    setup_sourced_station, make_vendor_rep_headers,
    make_layover, book_layover,
)
from test_helpers.fixtures import ADMIN, SOURCING, CREWOPS, FINANCE


def _book_and_checkin(api, station, contract, vendor, stay_date, crew_type,
                      crew_count, arrival, departure):
    # PRD §3.6: check-in requires the logical clock date to be on or after the
    # stay_date; advance the clock (monotonic) so each stay can be checked in.
    api.set_clock(stay_date, ADMIN)
    return make_checked_in_booking(
        station, contract, vendor, stay_date=stay_date, crew_type=crew_type,
        crew_count=crew_count, arrival=arrival, departure=departure)


class TestPerLineRounding:

    def test_invoice_reconciliation_per_line_rounding_order(self, api):
        """PRD §3.10: "Each eligible allocation contributes a line amount — its
        `nightly_rate_cents` multiplied by its `rooms_held`, rounded half-up to whole
        cents per line — and the `reconciled_amount_cents` is the half-up-rounded sum
        of those lines plus the late-cancel charge, which is half (50 percent) of the
        sum of the late-cancelled allocations' own per-line amounts, each line
        likewise rounded half-up before being summed."

        Design: Difficulty/combinatorial_formula/invoice_reconciliation_per_line_rounding_order
        """
        station, union, vendor, contract = setup_sourced_station(
            "MDW", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=3333, room_block_size=10,
            budget_cap_cents=2_000_000)
        for stay, arrival, departure in [
                ("2026-10-02T00:00:00Z", "2026-10-02T18:00:00Z", "2026-10-03T09:00:00Z"),
                ("2026-10-03T00:00:00Z", "2026-10-03T18:00:00Z", "2026-10-04T09:00:00Z"),
                ("2026-10-04T00:00:00Z", "2026-10-04T18:00:00Z", "2026-10-05T09:00:00Z")]:
            _book_and_checkin(api, station, contract, vendor, stay,
                              "FLIGHT_ATTENDANT", 3, arrival, departure)
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=9,
                               billed_amount_cents=29997)
        data = validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        # 3 lines x round_half_up(3333 x 3) = 3 x 9999 = 29997
        assert data["reconciled_room_nights"] == 9
        assert data["reconciled_amount_cents"] == 29997
        assert data["variance_pct"] == pytest.approx(0.0)

    def test_invoice_reconciliation_per_line_rounding_two_lines(self, api):
        """PRD §3.10: "Each eligible allocation contributes a line amount — its
        `nightly_rate_cents` multiplied by its `rooms_held`, rounded half-up to whole
        cents per line — and the `reconciled_amount_cents` is the half-up-rounded sum
        of those lines plus the late-cancel charge, which is half (50 percent) of the
        sum of the late-cancelled allocations' own per-line amounts, each line
        likewise rounded half-up before being summed."

        Design: Difficulty/combinatorial_formula/invoice_reconciliation_per_line_rounding_order
        """
        station, union, vendor, contract = setup_sourced_station(
            "MDW", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=3333, room_block_size=10,
            budget_cap_cents=2_000_000)
        for stay, arrival, departure in [
                ("2026-10-02T00:00:00Z", "2026-10-02T18:00:00Z", "2026-10-03T09:00:00Z"),
                ("2026-10-03T00:00:00Z", "2026-10-03T18:00:00Z", "2026-10-04T09:00:00Z")]:
            _book_and_checkin(api, station, contract, vendor, stay,
                              "FLIGHT_ATTENDANT", 3, arrival, departure)
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=6,
                               billed_amount_cents=19998)
        data = validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        assert data["reconciled_room_nights"] == 6
        assert data["reconciled_amount_cents"] == 19998
        assert data["variance_pct"] == pytest.approx(0.0)

    def test_invoice_variance_percent_of_reconciled_vs_billed(self, api):
        """PRD §3.10: "Otherwise the variance is the absolute difference between
        `billed_amount_cents` and `reconciled_amount_cents` divided by the reconciled
        amount, expressed as a percentage, rounded half-up to 2 decimal places. (A
        reporting view that instead divides by the billed amount may surface vendor
        overstatement differently, but it must never drive approval.)"
        PRD §3.10: "Approval moves `RECONCILED → APPROVED` and is gated on the
        union's fiscal provision: the invoice's `variance_pct` must be no more than
        the `max_invoice_variance_pct` of the union agreement for the station's crew
        — an exact-threshold variance passes — or approval is refused with
        `ERR_INVOICE_VARIANCE_EXCEEDED` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/invoice_variance_percent_of_reconciled_vs_billed
        """
        station, union, vendor, contract = setup_sourced_station(
            "DFW", station_min_rest=10, transport=30, union_min_rest=10,
            rate_cents=10000, room_block_size=10, budget_cap_cents=2_000_000)
        # two checked-in stays: 4 rooms each at 10000 -> 80000
        _book_and_checkin(api, station, contract, vendor, "2026-10-03T00:00:00Z",
                          "PILOT", 4, "2026-10-03T10:00:00Z", "2026-10-03T23:00:00Z")
        _book_and_checkin(api, station, contract, vendor, "2026-10-04T00:00:00Z",
                          "PILOT", 4, "2026-10-04T10:00:00Z", "2026-10-04T23:00:00Z")
        api.set_clock("2026-10-04T12:00:00Z", ADMIN)
        layover3, alloc3 = make_confirmed_booking(
            station, contract, stay_date="2026-10-05T00:00:00Z", crew_type="PILOT",
            crew_count=4, arrival="2026-10-05T10:00:00Z",
            departure="2026-10-05T23:00:00Z")
        # cancelling at 10-04T12:00Z is within the 24h late-cancel window of the
        # 2026-10-05 stay -> chargeable late cancel
        validate_success(api.cancel_layover(layover3["id"], CREWOPS))
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=16,
                               billed_amount_cents=160000)
        data = validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        # 8 checked-in nights (80000) + late-cancel 0.5 x 40000 (20000) = 100000
        assert data["reconciled_room_nights"] == 8
        assert data["reconciled_amount_cents"] == 100000
        # gating variant divides by reconciled: |160000 - 100000| / 100000 = 60.0
        assert data["variance_pct"] == pytest.approx(60.0)
        resp = api.approve_invoice(invoice["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVOICE_VARIANCE_EXCEEDED)


class TestInputSetFiltering:

    def test_invoice_reconciliation_excludes_noshow_and_out_of_period(self, api):
        """PRD §3.10: "The eligible set is the contract's allocations in
        `CHECKED_IN` whose `stay_date` falls within the billing period, both
        endpoints inclusive; the `reconciled_room_nights` is the sum of `rooms_held`
        across that set."

        Design: Corner/calculations/invoice_reconciliation_excludes_noshow_and_out_of_period
        """
        station, union, vendor, contract = setup_sourced_station(
            "CYS", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=10000, room_block_size=6,
            end_date="2026-11-04T00:00:00Z", budget_cap_cents=4_000_000)
        _book_and_checkin(api, station, contract, vendor, "2026-10-05T00:00:00Z",
                          "FLIGHT_ATTENDANT", 2, "2026-10-05T18:00:00Z",
                          "2026-10-06T09:00:00Z")
        _book_and_checkin(api, station, contract, vendor, "2026-10-06T00:00:00Z",
                          "FLIGHT_ATTENDANT", 2, "2026-10-06T18:00:00Z",
                          "2026-10-07T09:00:00Z")
        # V3: confirmed stay 2026-10-07, then no-showed after the clock passes
        layover3, alloc3 = make_confirmed_booking(
            station, contract, stay_date="2026-10-07T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=2,
            arrival="2026-10-07T18:00:00Z", departure="2026-10-08T09:00:00Z")
        # V4: checked in 2026-11-02 — outside the June billing window
        _book_and_checkin(api, station, contract, vendor, "2026-11-02T00:00:00Z",
                          "FLIGHT_ATTENDANT", 2, "2026-11-02T18:00:00Z",
                          "2026-11-03T09:00:00Z")
        api.set_clock("2026-10-10T00:00:00Z", ADMIN)
        validate_success(api.no_show_allocation(alloc3["id"], CREWOPS))
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=6,
                               billed_amount_cents=60000)
        data = validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        # only V1 + V2 count: 4 nights, 40000; variance |60000-40000|/40000 = 50.0
        assert data["reconciled_room_nights"] == 4
        assert data["reconciled_amount_cents"] == 40000
        assert data["variance_pct"] == pytest.approx(50.0)


class TestDisputeLoop:

    def test_invoice_dispute_rereconcile_recomputes_from_live_state(self, api):
        """PRD §3.10: "Either a reconciled or an approved invoice may instead be
        disputed (`RECONCILED → DISPUTED` or `APPROVED → DISPUTED`), and a disputed
        invoice may be re-reconciled (`DISPUTED → RECONCILED`), which re-runs both
        the reconciliation and the variance computation and overwrites the
        reconciled fields."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_rereconcile_loop
        """
        station, union, vendor, contract = setup_sourced_station(
            "TUL", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=10000, room_block_size=10,
            budget_cap_cents=2_000_000)
        _book_and_checkin(api, station, contract, vendor, "2026-10-02T00:00:00Z",
                          "FLIGHT_ATTENDANT", 4, "2026-10-02T18:00:00Z",
                          "2026-10-03T09:00:00Z")
        # book + confirm (no check-in) so the allocation can be NO_SHOWed later
        lay2 = make_layover(station["id"], crew_type="FLIGHT_ATTENDANT",
                            crew_count=4, arrival="2026-10-03T18:00:00Z",
                            departure="2026-10-04T09:00:00Z")
        api.set_clock("2026-10-03T00:00:00Z", ADMIN)
        lay2, alloc2 = book_layover(lay2, contract["id"],
                                    stay_date="2026-10-03T00:00:00Z")
        validate_success(api.confirm_allocation(alloc2["id"], CREWOPS))
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=8,
                               billed_amount_cents=80000)
        validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        validate_success(api.dispute_invoice(invoice["id"], FINANCE))
        # while DISPUTED, the second allocation becomes NO_SHOW
        api.set_clock("2026-10-10T00:00:00Z", ADMIN)
        validate_success(api.no_show_allocation(alloc2["id"], CREWOPS))
        data = validate_success(api.re_reconcile_invoice(invoice["id"], FINANCE))
        assert data["status"] == "RECONCILED"
        # NO_SHOW drops out of the eligible set on recompute
        assert data["reconciled_room_nights"] == 4
        assert data["reconciled_amount_cents"] == 40000
        assert data["variance_pct"] == pytest.approx(100.0)

    def test_invoice_dispute_rereconcile_without_mutation_conserves_values(self, api):
        """PRD §3.10: "Either a reconciled or an approved invoice may instead be
        disputed (`RECONCILED → DISPUTED` or `APPROVED → DISPUTED`), and a disputed
        invoice may be re-reconciled (`DISPUTED → RECONCILED`), which re-runs both
        the reconciliation and the variance computation and overwrites the
        reconciled fields."

        Design: Difficulty/compensating_invariant/invoice_reconcile_dispute_rereconcile_value_conserved
        """
        station, union, vendor, contract = setup_sourced_station(
            "SNA", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=10000, room_block_size=5,
            budget_cap_cents=1_000_000)
        _book_and_checkin(api, station, contract, vendor, "2026-10-02T00:00:00Z",
                          "FLIGHT_ATTENDANT", 4, "2026-10-02T18:00:00Z",
                          "2026-10-03T09:00:00Z")
        _book_and_checkin(api, station, contract, vendor, "2026-10-03T00:00:00Z",
                          "FLIGHT_ATTENDANT", 4, "2026-10-03T18:00:00Z",
                          "2026-10-04T09:00:00Z")
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=8,
                               billed_amount_cents=80000)
        first = validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        validate_success(api.dispute_invoice(invoice["id"], FINANCE))
        # no allocation mutations between dispute and re-reconcile
        second = validate_success(api.re_reconcile_invoice(invoice["id"], FINANCE))
        assert second["status"] == "RECONCILED"
        assert second["reconciled_amount_cents"] == first["reconciled_amount_cents"] == 80000
        assert second["reconciled_room_nights"] == first["reconciled_room_nights"] == 8
        assert second["variance_pct"] == pytest.approx(0.0)

    def test_dispute_from_approved_then_rereconcile(self, api):
        """PRD §3.10: "Either a reconciled or an approved invoice may instead be
        disputed (`RECONCILED → DISPUTED` or `APPROVED → DISPUTED`), and a disputed
        invoice may be re-reconciled (`DISPUTED → RECONCILED`), which re-runs both
        the reconciliation and the variance computation and overwrites the
        reconciled fields."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_rereconcile_loop
        """
        station, union, vendor, contract = setup_sourced_station(
            "TUL", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=10000, room_block_size=10,
            budget_cap_cents=2_000_000)
        _book_and_checkin(api, station, contract, vendor, "2026-10-02T00:00:00Z",
                          "FLIGHT_ATTENDANT", 4, "2026-10-02T18:00:00Z",
                          "2026-10-03T09:00:00Z")
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=4,
                               billed_amount_cents=40000)
        validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        approved = validate_success(api.approve_invoice(invoice["id"], FINANCE))
        assert approved["status"] == "APPROVED"
        disputed = validate_success(api.dispute_invoice(invoice["id"], FINANCE))
        assert disputed["status"] == "DISPUTED"
        data = validate_success(api.re_reconcile_invoice(invoice["id"], FINANCE))
        assert data["status"] == "RECONCILED"
        assert data["reconciled_amount_cents"] == 40000
        assert data["reconciled_room_nights"] == 4


class TestVarianceGate:

    def test_invoice_variance_at_exact_threshold_passes(self, api):
        """PRD §3.10: "Approval moves `RECONCILED → APPROVED` and is gated on the
        union's fiscal provision: the invoice's `variance_pct` must be no more than
        the `max_invoice_variance_pct` of the union agreement for the station's crew
        — an exact-threshold variance passes — or approval is refused with
        `ERR_INVOICE_VARIANCE_EXCEEDED` (HTTP 422)."
        PRD §2.8: "Comparison boundaries are inclusive where §3 states them with
        \"at least\" or \"no more than\" phrasing; a value sitting exactly on a
        threshold passes the check."

        Design: Difficulty/dual_variant_calc/invoice_variance_percent_of_reconciled_vs_billed
        """
        station, union, vendor, contract = setup_sourced_station(
            "DFW", station_min_rest=10, transport=30, union_min_rest=10,
            rate_cents=10000, room_block_size=10, budget_cap_cents=2_000_000)
        # one checked-in stay: 4 rooms at 10000 -> reconciled 40000
        _book_and_checkin(api, station, contract, vendor, "2026-10-03T00:00:00Z",
                          "PILOT", 4, "2026-10-03T10:00:00Z", "2026-10-03T23:00:00Z")
        # billed 44000 -> variance |44000-40000|/40000 = 10.0 == cap exactly
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=5,
                               billed_amount_cents=44000)
        data = validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        assert data["reconciled_amount_cents"] == 40000
        assert data["variance_pct"] == pytest.approx(10.0)
        approved = validate_success(api.approve_invoice(invoice["id"], FINANCE))
        assert approved["status"] == "APPROVED"


class TestInvoiceRbac:
    def test_vendor_rep_cannot_reconcile_invoice(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the
        targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); this same
        rejection covers entity-backed ownership failures, such as a
        `HotelVendorRep` attempting to withdraw a proposal that belongs to another
        vendor."

        Design: Corner/rbac/vendor_rep_cannot_reconcile_invoice
        """
        station, union, vendor, contract = setup_sourced_station(
            "LNK", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8)
        invoice = make_invoice(contract["id"], vendor)
        resp = api.reconcile_invoice(
            invoice["id"], make_vendor_rep_headers(vendor["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        fresh = validate_success(api.get_invoice(invoice["id"], FINANCE))
        assert fresh["status"] == "RECEIVED"


class TestWithdrawOwnership:

    def test_vendor_rep_cannot_withdraw_other_vendors_proposal(self, api):
        """PRD §3.3: "The vendor representative who owns the proposal — the
        `X-User-ID` matching the proposal's `vendor_id` — may withdraw it from any
        of `SUBMITTED`, `UNDER_REVIEW`, or `SHORTLISTED`, moving it to `WITHDRAWN`;
        a representative acting for a different vendor is refused with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/vendor_rep_cannot_withdraw_other_vendors_proposal
        """
        from test_helpers import (make_station, make_open_cycle_with_proposal)
        station = make_station(code="PIA")
        vendor_a = make_vendor(name="Riverfront A",
                               contact_email="a@riverfront.example")
        vendor_b = make_vendor(name="Riverfront B",
                               contact_email="b@riverfront.example")
        cycle, proposal = make_open_cycle_with_proposal(station["id"], vendor_b)
        resp = api.withdraw_proposal(
            proposal["id"], make_vendor_rep_headers(vendor_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        fresh = validate_success(api.get_proposal(proposal["id"], SOURCING))
        assert fresh["status"] == "SUBMITTED"

    def test_rereconcile_requires_disputed_state(self, api):
        """PRD §3.10: "Either a reconciled or an approved invoice may instead be
        disputed (`RECONCILED → DISPUTED` or `APPROVED → DISPUTED`), and a disputed
        invoice may be re-reconciled (`DISPUTED → RECONCILED`), which re-runs both
        the reconciliation and the variance computation and overwrites the
        reconciled fields."

        Design: Difficulty/compensating_invariant/invoice_reconcile_dispute_rereconcile_value_conserved
        """
        station, union, vendor, contract = setup_sourced_station(
            "SNA", station_min_rest=8, transport=20, crew_type="FLIGHT_ATTENDANT",
            union_min_rest=8, rate_cents=10000, room_block_size=5,
            budget_cap_cents=1_000_000)
        _book_and_checkin(api, station, contract, vendor, "2026-10-02T00:00:00Z",
                          "FLIGHT_ATTENDANT", 4, "2026-10-02T18:00:00Z",
                          "2026-10-03T09:00:00Z")
        invoice = make_invoice(contract["id"], vendor, billed_room_nights=4,
                               billed_amount_cents=40000)
        validate_success(api.reconcile_invoice(invoice["id"], FINANCE))
        # re-reconcile is defined from DISPUTED only; from RECONCILED it is not a
        # legal transition
        resp = api.re_reconcile_invoice(invoice["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
