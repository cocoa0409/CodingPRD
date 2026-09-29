"""Case clock boundaries at the needle target and the four-hop handoff settlement."""
from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import REQUIRED_HANDOFF_PACKET_ITEMS


def _dtn_case(dtn_minutes):
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = fx.setup_reportable_case(
        context, door_at,
        dtn_minutes=dtn_minutes,
        dti_minutes=10,
        last_known_well_at="2026-09-01T07:45:00Z",
    )
    return built


def test_needle_at_exactly_sixty_minutes_scores_the_certified_numerator():
    """Sixty whole minutes is on the inclusive side of the needle target.

    PRD 3.9: "`STK_DTN_60` requires `door_to_needle_minutes` to be non-null and 60 or less. Exactly 60 counts; 61 does not."
    PRD 3.6: "exactly 60 minutes is on target and raises nothing, 61 does"

    Design: Difficulty/boundary_precision_check/door_to_needle_numerator_boundary_at_sixty_and_sixty_one_minutes
    """
    built = _dtn_case(60)
    case = built["case"]
    abstraction = built["abstractions"]["STK_DTN_60"]

    assert case["door_to_needle_minutes"] == 60, (
        f"the needle lands exactly sixty minutes after door, got {case['door_to_needle_minutes']}"
    )
    assert case["lkw_to_needle_minutes"] == 75, (
        "fifteen minutes of pre-arrival onset plus sixty of door time, got "
        f"{case['lkw_to_needle_minutes']}"
    )
    assert case["door_to_imaging_minutes"] == 10, "the scan is well inside its own target"
    assert case["deviation_count"] == 0, (
        f"sixty minutes opens no DTN deviation, got {case['deviation_count']}"
    )
    assert fx.list_case_deviations(case["id"]) == [], "no deviation of any type exists"

    assert abstraction["variant"] == "CERTIFIED", (
        f"finalisation switches the variant, got {abstraction['variant']}"
    )
    assert abstraction["status"] == "FINALIZED"
    assert abstraction["numerator_flag"] is True, (
        "60 <= 60 scores the numerator under the certified variant"
    )
    assert abstraction["exclusion_reason"] == "NONE"
    assert abstraction["denominator_included"] is True
    assert abstraction["report_id"] is None, "no report exists to attach to"


def test_needle_at_sixty_one_minutes_misses_the_numerator_but_stays_in_the_denominator():
    """One minute past the target flips the numerator and opens the major deviation.

    PRD 3.9: "`STK_DTN_60` requires `door_to_needle_minutes` to be non-null and 60 or less. Exactly 60 counts; 61 does not."
    PRD 3.6: "When `door_to_needle_minutes` exceeds 60 a system-detected `ProtocolDeviation` of type `DTN_EXCEEDED` and severity `MAJOR` is opened on the case with `deviation_count` raised by 1"

    Design: Difficulty/boundary_precision_check/door_to_needle_numerator_boundary_at_sixty_and_sixty_one_minutes
    """
    built = _dtn_case(61)
    case = built["case"]
    abstraction = built["abstractions"]["STK_DTN_60"]

    assert case["door_to_needle_minutes"] == 61, (
        f"the needle lands one minute late, got {case['door_to_needle_minutes']}"
    )
    assert case["lkw_to_needle_minutes"] == 76, (
        f"the minute arithmetic is exact, not rounded from seconds, got {case['lkw_to_needle_minutes']}"
    )
    assert case["deviation_count"] == 1, (
        f"exactly one deviation is opened, got {case['deviation_count']}"
    )
    deviations = fx.list_case_deviations(case["id"])
    assert len(deviations) == 1
    assert deviations[0]["deviation_type"] == "DTN_EXCEEDED"
    assert deviations[0]["severity"] == "MAJOR"
    assert deviations[0]["source"] == "SYSTEM_DETECTED"

    assert abstraction["numerator_flag"] is False, (
        "61 misses the inclusive 60-minute numerator"
    )
    assert abstraction["exclusion_reason"] == "NONE", (
        f"a late needle is not an exclusion clause, got {abstraction['exclusion_reason']}"
    )
    assert abstraction["denominator_included"] is True, (
        "the certified variant keeps the row in the denominator because nothing excluded it"
    )
    assert abstraction["variant"] == "CERTIFIED"


def _congested_transfer(*, accept=True):
    """A drip-and-ship transfer from a spoke holding three open cases to a DEGRADED destination."""
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    spoke_id = context["spoke"]["id"]
    destination = fx.register_thrombectomy_center()
    degraded = fx.degrade_center(destination["id"], "VIDEO_CART")
    assert degraded["equipment_readiness_posture"] == "DEGRADED"
    assert degraded["ems_routing_posture"] == "DIVERT_ADVISORY"
    assert degraded["open_case_count"] == 0

    built = fx.setup_treated_case(context, door_at, dtn_minutes=45, dti_minutes=10)
    fillers = [fx.activate_case(spoke_id, "2026-09-01T08:50:00Z") for _ in range(2)]
    origin = fx.read_center(spoke_id)
    assert origin["open_case_count"] == 3, (
        f"the treated case plus two fillers are open at the origin, got {origin['open_case_count']}"
    )
    assert origin["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "three open cases put the origin on divert advisory"
    )

    transfer = fx.propose_transfer(
        built["case"]["id"], destination["id"],
        mode="DRIP_AND_SHIP", transport_eta_minutes=35, at="2026-09-01T08:55:00Z",
    )
    if accept:
        transfer = fx.accept_transfer(transfer["id"], at="2026-09-01T08:58:00Z")
    return {
        "context": context, "case": built["case"], "destination": destination,
        "transfer": transfer, "fillers": fillers,
    }


def test_congested_destination_freezes_a_seventy_four_minute_projection_at_proposal():
    """The snapshot, the factor, the rounded-up transport leg and the unmultiplied overheads.

    PRD 3.7: "The same destination on `DIVERT_ADVISORY` gives 35 × 1.25 = 43.75, which rounds up to an `adjusted_transport_minutes` of 44, and a projection of 44 + 20 + 10 = 74."
    PRD 3.7: "No `open_case_count` moves at proposal time; a proposal is not yet a commitment."

    Design: Difficulty/transitive_cascade/handoff_settlement_cascades_case_closure_origin_release_and_deviation
    """
    scenario = _congested_transfer(accept=False)
    transfer = scenario["transfer"]
    destination = scenario["destination"]

    assert transfer["destination_posture_at_proposal"] == "DIVERT_ADVISORY", (
        "the live posture is frozen into the proposal, got "
        f"{transfer['destination_posture_at_proposal']}"
    )
    assert transfer["congestion_factor"] == 1.25, (
        f"divert advisory carries a 1.25 factor, got {transfer['congestion_factor']}"
    )
    a.assert_two_decimal_places(transfer["congestion_factor"], "congestion_factor")
    assert transfer["adjusted_transport_minutes"] == 44, (
        f"43.75 minutes rounds up to a whole 44, got {transfer['adjusted_transport_minutes']}"
    )
    assert transfer["projected_door_in_door_out_minutes"] == 74, (
        "44 plus 20 of preparation plus 10 for the infusion in transit, got "
        f"{transfer['projected_door_in_door_out_minutes']}"
    )
    assert transfer["status"] == "PROPOSED"
    assert transfer["door_in_door_out_minutes"] is None
    assert transfer["handoff_packet_complete"] is False
    assert transfer["handoff_packet_items"] == []

    case = fx.read_case(scenario["case"]["id"])
    assert case["status"] == "TRANSFER_INITIATED"
    assert case["disposition"] == "DRIP_AND_SHIP", (
        f"the treated case keeps its drip-and-ship branch, got {case['disposition']}"
    )
    assert fx.read_center(destination["id"])["open_case_count"] == 0, (
        "a proposal is not yet a commitment at the destination"
    )
    assert fx.read_center(case["center_id"])["open_case_count"] == 3, (
        "the origin still holds the patient too"
    )

    accepted = fx.accept_transfer(transfer["id"], at="2026-09-01T08:58:00Z")
    assert accepted["accepted_at"] == "2026-09-01T08:58:00Z"
    assert accepted["destination_posture_at_proposal"] == "DIVERT_ADVISORY", (
        "the snapshot never refreshes on acceptance"
    )
    assert accepted["adjusted_transport_minutes"] == 44
    assert accepted["projected_door_in_door_out_minutes"] == 74
    assert fx.read_center(destination["id"])["open_case_count"] == 1, (
        "acceptance is the moment the destination starts carrying the patient"
    )


def test_handoff_settles_the_case_releases_both_facilities_and_opens_the_dido_deviation():
    """One request closes the case, decrements both counts, re-derives postures and deviates.

    PRD 3.7: "Both facilities release the patient: the origin's `open_case_count` and the destination's `open_case_count` are each lowered by 1, and both decrements land before any posture is re-derived."
    PRD 3.7: "when the `door_in_door_out_minutes` measured in step 1 exceeds 120, a system-detected `ProtocolDeviation` of type `DIDO_EXCEEDED` and severity `MAJOR` is opened on the case with `deviation_count` raised by 1"

    Design: Difficulty/transitive_cascade/handoff_settlement_cascades_case_closure_origin_release_and_deviation
    """
    scenario = _congested_transfer()
    transfer = scenario["transfer"]
    case_id = scenario["case"]["id"]
    origin_id = scenario["case"]["center_id"]
    destination_id = scenario["destination"]["id"]
    assert fx.read_center(destination_id)["open_case_count"] == 1

    settled = fx.complete_handoff(
        transfer["id"], mode="DRIP_AND_SHIP", at="2026-09-01T10:10:00Z"
    )

    assert settled["status"] == "HANDOFF_COMPLETE"
    assert settled["handoff_completed_at"] == "2026-09-01T10:10:00Z"
    assert settled["handoff_packet_complete"] is True
    for item in REQUIRED_HANDOFF_PACKET_ITEMS:
        assert item in settled["handoff_packet_items"], (
            f"the drip-and-ship packet must carry {item}"
        )
    assert settled["door_in_door_out_minutes"] == 130, (
        "08:00 to 10:10 is 130 whole minutes, got "
        f"{settled['door_in_door_out_minutes']}"
    )
    assert settled["projected_door_in_door_out_minutes"] == 74, (
        "the projection is never refreshed with the realised interval, got "
        f"{settled['projected_door_in_door_out_minutes']}"
    )

    case = fx.read_case(case_id)
    assert case["status"] == "CLOSED", f"the handoff closes the case, got {case['status']}"
    assert case["disposition"] == "DRIP_AND_SHIP", "the closed case keeps its mode's disposition"

    origin = fx.read_center(origin_id)
    assert origin["open_case_count"] == 2, (
        f"the origin releases the transferred patient, got {origin['open_case_count']}"
    )
    assert origin["ems_routing_posture"] == "ROUTINE", (
        "dropping below three open cases returns the origin to routine in the same request"
    )

    destination = fx.read_center(destination_id)
    assert destination["open_case_count"] == 0, (
        f"the destination releases the patient as well, got {destination['open_case_count']}"
    )
    assert destination["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "its degraded equipment keeps the destination off routine regardless of the count"
    )

    deviations = fx.list_case_deviations(case_id)
    assert len(deviations) == 1, f"exactly one deviation on the case, got {len(deviations)}"
    a.assert_system_detected_deviation(deviations[0], "DIDO_EXCEEDED", "MAJOR")
    assert case["deviation_count"] == 1

    for filler in scenario["fillers"]:
        still_open = fx.read_case(filler["id"])
        assert still_open["status"] == "ACTIVATED", (
            "the other open cases are untouched by the settlement"
        )
