"""The two lifecycles that are cycles rather than pipelines.

A parcel's measurement axis walks backward out of TOLERANCE_FLAGGED when a
later scan lands inside tolerance, while its movement axis advances
independently; a dispute's review loop re-enters UNDER_REVIEW twice and is then
stopped by a counter rather than by its status.
"""

import pytest

from test_helpers import (
    CARRIER_OPS_HEADERS,
    DEFAULT_CLOCK_UTC,
    ERR_EVIDENCE_ROUNDS_EXHAUSTED,
    RESIDENTIAL_OVERRIDE_540,
    REVENUE_AUDITOR_HEADERS,
    ROUNDING_DECLARED,
    TOLERANCE_EDGE_DECLARED,
    add_scan,
    assert_instant,
    assert_lbs,
    assert_money_equals,
    assert_pct,
    assert_version_unchanged,
    delivered_shipment,
    evidence_payload,
    filed_dispute,
    get_success_data,
    induct_shipment,
    issued_invoice,
    line_for_shipment,
    open_invoice,
    refresh_shipment,
    shipper_with_active_contract,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The measurement axis recovers while the movement axis advances
# ---------------------------------------------------------------------------
@pytest.fixture
def tolerance_edge_parcel(api):
    """A 10 x 10 x 20 inch, 30.0 lb GROUND parcel with no scan yet.

    Its declared cube of 2000 in3 makes a 2100 in3 capture land on exactly the
    5.00 percent cube tolerance, and its 30.0 lb declaration gives a 0.6 lb
    weight allowance.
    """
    shipper = shipper_with_active_contract(
        api, account_number="SH-1001", with_express=False
    )
    return induct_shipment(
        api,
        shipper,
        service_level="GROUND",
        tracking_number="1Z-TOL-0011",
        zone=2,
        residential_declared=False,
        **TOLERANCE_EDGE_DECLARED,
    )


def test_an_automated_scan_over_tolerance_flags_only_the_measurement_axis(
    api, tolerance_edge_parcel
):
    """PRD §3.4: "The scan breaches on cube when `dim_variance_pct` is greater than or equal to 5.00 percent, and it breaches on weight when `weight_variance_lbs` is greater than or equal to the weight allowance."
    PRD §3.4: "An `AUTOMATED_DWS` capture whose verdict is `EXCEEDS_TOLERANCE` drives the shipment to `TOLERANCE_FLAGGED`, reachable both as `PENDING_SCAN → TOLERANCE_FLAGGED` and as `SCANNED → TOLERANCE_FLAGGED`."
    PRD §3.4: "The shipment's `billable_weight_lbs` then switches to `final_billable_weight_lbs` and stays there for as long as a scan exists."
    PRD §3.4: "When the package is not yet on a line, nothing propagates."

    Design: Difficulty/non_linear_state_machine/shipment_measurement_axis_recovers_while_movement_axis_advances
    """
    scan = add_scan(
        api,
        tolerance_edge_parcel.shipment_id,
        expected_version=tolerance_edge_parcel.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=21,
        scanned_weight_lbs=30.0,
    )
    assert scan["scanned_cube_in3"] == 2100, (
        f"10 x 10 x 21 inches must cube to 2100 in3, got {scan['scanned_cube_in3']}"
    )
    assert_pct(scan["dim_variance_pct"], 5.00, "dim_variance_pct")
    assert_lbs(scan["weight_variance_lbs"], 0.0, "weight_variance_lbs")
    assert scan["tolerance_status"] == "EXCEEDS_TOLERANCE", (
        "a variance landing exactly on 5.00 percent is a breach, got "
        f"{scan['tolerance_status']}"
    )

    shipment = refresh_shipment(api, tolerance_edge_parcel.shipment_id)
    assert shipment["measurement_status"] == "TOLERANCE_FLAGGED"
    assert shipment["movement_status"] == "IN_TRANSIT", (
        "a scan never touches the movement axis, got " f"{shipment['movement_status']}"
    )
    assert shipment["billing_status"] == "UNBILLED", (
        "an unbilled parcel has no line for the capture to propagate to, got "
        f"{shipment['billing_status']}"
    )
    assert shipment["scanned_cube_in3"] == 2100
    assert_lbs(shipment["final_dim_weight_lbs"], 16, "final_dim_weight_lbs")
    assert_lbs(shipment["final_billable_weight_lbs"], 30, "final_billable_weight_lbs")
    assert shipment["final_basis"] == "ACTUAL"
    assert_lbs(shipment["billable_weight_lbs"], 30, "billable_weight_lbs")


def test_a_later_in_tolerance_scan_walks_the_measurement_axis_back_to_scanned(
    api, tolerance_edge_parcel
):
    """PRD §3.4: "An `AUTOMATED_DWS` capture whose verdict is `WITHIN_TOLERANCE` drives the shipment to `SCANNED`."
    PRD §3.4: "This reaches `SCANNED` from `PENDING_SCAN` (`PENDING_SCAN → SCANNED`) and also from a previously flagged shipment (`TOLERANCE_FLAGGED → SCANNED`), which is the recovery cycle: a re-scan that lands back inside tolerance clears the flag and makes the package invoiceable again."
    PRD §3.4: "The scan's `scanned_cube_in3` is built exactly as the declared cube was: each captured dimension rounded half up to a whole inch first, then the three whole-inch values multiplied."
    PRD §3.4: "Immediately after the scan's cube is computed, the capture is compared against the shipper's original declaration — never against a previous scan."

    Design: Difficulty/non_linear_state_machine/shipment_measurement_axis_recovers_while_movement_axis_advances
    """
    add_scan(
        api,
        tolerance_edge_parcel.shipment_id,
        expected_version=tolerance_edge_parcel.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=21,
        scanned_weight_lbs=30.0,
    )
    flagged = refresh_shipment(api, tolerance_edge_parcel.shipment_id)
    assert flagged["measurement_status"] == "TOLERANCE_FLAGGED"

    recovery = add_scan(
        api,
        tolerance_edge_parcel.shipment_id,
        expected_version=flagged["version"],
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=20.4,
        scanned_weight_lbs=30.0,
    )
    assert recovery["scanned_cube_in3"] == 2000, (
        "20.4 inches rounds half up to 20, so the cube is 2000 in3, got "
        f"{recovery['scanned_cube_in3']}"
    )
    assert_pct(recovery["dim_variance_pct"], 0.00, "dim_variance_pct")
    assert_lbs(recovery["weight_variance_lbs"], 0.0, "weight_variance_lbs")
    assert recovery["tolerance_status"] == "WITHIN_TOLERANCE"

    shipment = refresh_shipment(api, tolerance_edge_parcel.shipment_id)
    assert shipment["measurement_status"] == "SCANNED", (
        "the recovery cycle must move the measurement axis backward out of "
        f"TOLERANCE_FLAGGED, got {shipment['measurement_status']}"
    )
    assert shipment["scanned_cube_in3"] == 2000
    assert_lbs(shipment["final_billable_weight_lbs"], 30, "final_billable_weight_lbs")
    assert shipment["final_basis"] == "ACTUAL"


def test_delivery_advances_the_movement_axis_without_disturbing_the_other_two(
    api, tolerance_edge_parcel
):
    """PRD §3.5: "The movement axis is independent of the measurement axis: a package can be `VERIFIED` and still `IN_TRANSIT`, or `DELIVERED` and still `PENDING_SCAN`."
    PRD §3.5: "A `CarrierOps` operator drives the shipment `IN_TRANSIT → DELIVERED`, and the server stamps `delivered_at` from the logical clock and increments the shipment's `version` by 1."
    PRD §3.5: "No charge is created and no accessorial is re-evaluated."
    PRD §3.4: "The full measurement history of a package is readable as a list ordered oldest first, so the sequence of variances and verdicts that produced the current determination is auditable end to end."

    Design: Difficulty/non_linear_state_machine/shipment_measurement_axis_recovers_while_movement_axis_advances
    """
    add_scan(
        api,
        tolerance_edge_parcel.shipment_id,
        expected_version=tolerance_edge_parcel.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=21,
        scanned_weight_lbs=30.0,
    )
    flagged = refresh_shipment(api, tolerance_edge_parcel.shipment_id)
    add_scan(
        api,
        tolerance_edge_parcel.shipment_id,
        expected_version=flagged["version"],
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=20.4,
        scanned_weight_lbs=30.0,
    )

    validate_success(
        api.deliver_shipment(tolerance_edge_parcel.shipment_id, CARRIER_OPS_HEADERS)
    )
    shipment = refresh_shipment(api, tolerance_edge_parcel.shipment_id)
    assert shipment["movement_status"] == "DELIVERED"
    assert shipment["measurement_status"] == "SCANNED", (
        "delivery must not touch the measurement axis, got "
        f"{shipment['measurement_status']}"
    )
    assert shipment["billing_status"] == "UNBILLED", (
        "delivery does not bill the parcel, got " f"{shipment['billing_status']}"
    )
    assert_instant(shipment["delivered_at"], DEFAULT_CLOCK_UTC, "delivered_at")
    assert_lbs(shipment["billable_weight_lbs"], 30, "billable_weight_lbs")

    scans = get_success_data(
        api.list_scans(
            tolerance_edge_parcel.shipment_id, CARRIER_OPS_HEADERS, {"limit": 100}
        )
    )
    assert len(scans) == 2, (
        f"the superseding scan must not delete the flagged one, found {len(scans)}"
    )


# ---------------------------------------------------------------------------
# The bounded evidence review loop
# ---------------------------------------------------------------------------
@pytest.fixture
def dispute_on_a_residential_charge(api):
    """An ACCESSORIAL dispute at SUBMITTED against an issued 7760 cent line."""
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={"accessorial_rate_overrides": dict(RESIDENTIAL_OVERRIDE_540)},
        with_ground=False,
    )
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-P1-0001",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    invoice = issued_invoice(api, open_invoice(api, shipper, [parcel.shipment_id]))
    line = line_for_shipment(api, invoice.invoice_id, parcel.shipment_id)
    assert_money_equals(line["base_line_total_cents"], 7760, "base_line_total_cents")
    dispute = filed_dispute(
        api,
        invoice,
        line["id"],
        claim_type="ACCESSORIAL",
        disputed_codes=["RESIDENTIAL"],
        claimed_reason="Delivered to a commercial dock, residential fee is wrong",
    )
    return {"shipper": shipper, "invoice": invoice, "line": line, "dispute": dispute}


def _read_dispute(api, dispute_id):
    """Re-read a dispute through the auditor's own view of it."""
    return get_success_data(api.get_dispute(dispute_id, REVENUE_AUDITOR_HEADERS))


def _file_evidence(api, dispute_id, item_type, reference, shipper_headers):
    """File one evidence item as the owning shipper."""
    return get_success_data(
        api.submit_evidence(
            dispute_id,
            evidence_payload(item_type=item_type, reference=reference),
            shipper_headers,
        )
    )


def _drive_to_the_round_cap(api, dispute_id, shipper_headers):
    """Burn both permitted review rounds, ending at UNDER_REVIEW with 3 items."""
    _file_evidence(api, dispute_id, "ADDRESS_PROOF", "doc://address-proof-1", shipper_headers)
    validate_success(api.request_evidence(dispute_id, "DELIVERY_PHOTO", REVENUE_AUDITOR_HEADERS))
    _file_evidence(api, dispute_id, "DELIVERY_PHOTO", "img://pod-1", shipper_headers)
    validate_success(api.request_evidence(dispute_id, "SCALE_CERT", REVENUE_AUDITOR_HEADERS))
    _file_evidence(api, dispute_id, "SCALE_CERT", "doc://scale-cert-1", shipper_headers)
    return _read_dispute(api, dispute_id)


def test_each_accepted_evidence_item_returns_the_dispute_to_under_review(
    api, dispute_on_a_residential_charge
):
    """PRD §3.9: "A new dispute opens at `status` `SUBMITTED` with `shipper_user_id` stamped from the filer's `X-User-ID`, `round_count` at 0, `required_item_type` null, `accepted_evidence_count` at 0, `granted_credit_cents` at 0, and `resolved_at` null."
    PRD §3.9: "When the item is accepted, the dispute's `required_item_type` is cleared to null and `accepted_evidence_count` rises by 1."
    PRD §3.9: "Either way the dispute lands at `UNDER_REVIEW`, whether it came from `SUBMITTED → UNDER_REVIEW` or from `EVIDENCE_REQUESTED → UNDER_REVIEW`, and the dispute's `version` increments by 1."
    PRD §3.9: "This is reachable both as `UNDER_REVIEW → EVIDENCE_REQUESTED` and as `SUBMITTED → EVIDENCE_REQUESTED`, and both branches behave identically: the requested type is stored in `required_item_type`, `round_count` rises by 1, and the dispute's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/dispute_evidence_round_cap_terminates_the_review_cycle
    """
    ctx = dispute_on_a_residential_charge
    dispute_id = ctx["dispute"].dispute_id
    shipper_headers = ctx["shipper"].shipper_headers

    opened = _read_dispute(api, dispute_id)
    assert opened["status"] == "SUBMITTED"
    assert opened["round_count"] == 0
    assert opened["accepted_evidence_count"] == 0
    assert opened["required_item_type"] is None

    first = _file_evidence(
        api, dispute_id, "ADDRESS_PROOF", "doc://address-proof-1", shipper_headers
    )
    assert first["accepted"] is True, (
        "an item filed while no type is outstanding is accepted, got "
        f"{first['accepted']}"
    )
    after_first = _read_dispute(api, dispute_id)
    assert after_first["status"] == "UNDER_REVIEW"
    assert after_first["round_count"] == 0, (
        "filing evidence never consumes a round, got " f"{after_first['round_count']}"
    )
    assert after_first["accepted_evidence_count"] == 1
    assert after_first["required_item_type"] is None

    requested = validate_success(
        api.request_evidence(dispute_id, "DELIVERY_PHOTO", REVENUE_AUDITOR_HEADERS)
    )
    assert requested["status"] == "EVIDENCE_REQUESTED"
    assert requested["round_count"] == 1
    assert requested["required_item_type"] == "DELIVERY_PHOTO"

    second = _file_evidence(api, dispute_id, "DELIVERY_PHOTO", "img://pod-1", shipper_headers)
    assert second["accepted"] is True
    after_second = _read_dispute(api, dispute_id)
    assert after_second["status"] == "UNDER_REVIEW", (
        "the loop must re-enter a state it already occupied, got "
        f"{after_second['status']}"
    )
    assert after_second["round_count"] == 1
    assert after_second["accepted_evidence_count"] == 2
    assert after_second["required_item_type"] is None


def test_the_third_round_request_is_refused_by_the_counter_not_by_the_status(
    api, dispute_on_a_residential_charge
):
    """PRD §3.9: "The review loop `UNDER_REVIEW → EVIDENCE_REQUESTED → UNDER_REVIEW` may repeat, but it is bounded at **two** rounds: a request is permitted only while `round_count` is strictly less than 2, and a third request is refused with `ERR_EVIDENCE_ROUNDS_EXHAUSTED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/dispute_evidence_round_cap_terminates_the_review_cycle
    """
    ctx = dispute_on_a_residential_charge
    dispute_id = ctx["dispute"].dispute_id

    at_cap = _drive_to_the_round_cap(api, dispute_id, ctx["shipper"].shipper_headers)
    assert at_cap["status"] == "UNDER_REVIEW", (
        "the third request must be attempted from a legally requestable status, got "
        f"{at_cap['status']}"
    )
    assert at_cap["round_count"] == 2
    assert at_cap["accepted_evidence_count"] == 3

    validate_error(
        api.request_evidence(dispute_id, "SCAN_IMAGE", REVENUE_AUDITOR_HEADERS),
        ERR_EVIDENCE_ROUNDS_EXHAUSTED,
        409,
    )


def test_the_refused_round_request_writes_nothing_to_the_dispute_or_its_evidence_log(
    api, dispute_on_a_residential_charge
):
    """PRD §3.9: "a request is permitted only while `round_count` is strictly less than 2, and a third request is refused with `ERR_EVIDENCE_ROUNDS_EXHAUSTED` (HTTP 409)"
    PRD §3.9: "Each filing creates an immutable `EvidenceItem` recording its `dispute_id`, the `submitted_by_user_id` taken from the filer's `X-User-ID`, and a computed `accepted` verdict: the item is accepted when the dispute's `required_item_type` is null at submission time, or when the item's `item_type` equals the outstanding `required_item_type`; otherwise it is not accepted."
    PRD §2.5: "`version` (integer): a counter that starts at 1 on creation and increments by exactly 1 on every mutation of the record, including mutations the server performs on its own initiative as a cascade from some other request."

    Design: Difficulty/non_linear_state_machine/dispute_evidence_round_cap_terminates_the_review_cycle
    """
    ctx = dispute_on_a_residential_charge
    dispute_id = ctx["dispute"].dispute_id
    shipper_id = ctx["shipper"].shipper_id

    before = _drive_to_the_round_cap(api, dispute_id, ctx["shipper"].shipper_headers)
    validate_error(
        api.request_evidence(dispute_id, "SCAN_IMAGE", REVENUE_AUDITOR_HEADERS),
        ERR_EVIDENCE_ROUNDS_EXHAUSTED,
        409,
    )

    after = _read_dispute(api, dispute_id)
    assert after["status"] == "UNDER_REVIEW"
    assert after["round_count"] == 2, (
        f"the refused request must not consume a round, got {after['round_count']}"
    )
    assert after["accepted_evidence_count"] == 3
    assert_version_unchanged(before, after)

    items = get_success_data(
        api.list_dispute_evidence(dispute_id, REVENUE_AUDITOR_HEADERS, {"limit": 100})
    )
    assert len(items) == 3, (
        f"exactly the three filed evidence items must survive, found {len(items)}"
    )
    assert all(item["accepted"] is True for item in items), (
        "every item was filed against an outstanding type it matched, or against no "
        f"outstanding type at all: {[item['accepted'] for item in items]}"
    )
    assert all(item["submitted_by_user_id"] == shipper_id for item in items), (
        "each item records the filing shipper's own identifier"
    )
