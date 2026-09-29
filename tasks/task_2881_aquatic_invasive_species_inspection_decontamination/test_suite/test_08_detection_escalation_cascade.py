"""Detection acceptance: the four-hop escalation from a report to posted staffing."""
from test_helpers import (
    acknowledge_detection_report,
    draft_detection_report,
    fetch_record,
    fetch_station,
    fetch_station_hours,
    fetch_water_body,
    setup_accepted_detection_report,
    setup_inspection,
    setup_program,
    submit_detection_report,
)


def _water_body_at_suspect_with_a_second_report_submitted():
    """One accepted live report already sits on a MODERATE, formerly CLEAN water body.

    A second `LIVE_ORGANISM` report is SUBMITTED and awaiting the state verdict,
    so the water body is one acceptance short of `CONFIRMED_INFESTED`.
    """
    ctx = setup_program(
        risk_tier="MODERATE", infestation_status="CLEAN",
        mandatory_inspection=False, staffing_level="SINGLE",
    )
    ctx = setup_accepted_detection_report(
        ctx, ack_id="ACK-0001", arrived_at="2026-08-05T09:00:00Z",
        screen_at="2026-08-05T09:00:00Z", disposition="PASS",
    )
    first_record = ctx["record"]
    setup_inspection(
        ctx, arrived_at="2026-08-05T11:00:00Z", screen_at="2026-08-05T11:00:00Z",
        disposition="PASS",
    )
    second_report = draft_detection_report(
        ctx["record"]["id"], ctx["inspector_a"]["id"], "LIVE_ORGANISM",
        species_code="DREISSENA-POLY",
    )
    submit_detection_report(second_report["id"], ctx["inspector_a"]["id"])
    return ctx, first_record, ctx["record"], second_report


class TestDetectionAcceptanceCascadesFourHops:
    """Each hop is conditional on the previous hop's outcome, not on the request."""

    def test_the_first_acceptance_stops_at_suspect(self):
        """One accepted report raises SUSPECT and leaves the tier and the stations alone.

        PRD: "Otherwise, when `detection_count` has reached 1 and the water body's
        `infestation_status` is still `CLEAN`, `infestation_status` is set to
        `SUSPECT` and `risk_tier` is left as it was."

        Design: Difficulty/transitive_cascade/detection_acceptance_cascades_four_hops_to_station_hours_staffing
        """
        ctx, _first, _second, _report = _water_body_at_suspect_with_a_second_report_submitted()

        water_body = fetch_water_body(ctx["water_body"]["id"])

        assert water_body["detection_count"] == 1
        assert water_body["live_detection_count"] == 1
        assert water_body["infestation_status"] == "SUSPECT"
        assert water_body["risk_tier"] == "MODERATE"
        station = fetch_station(ctx["station"]["id"])
        assert station["mandatory_inspection"] is False
        assert [row["staffing_level"] for row in fetch_station_hours(station["id"])] == [
            "SINGLE"
        ]

    def test_the_second_live_acceptance_confirms_the_infestation_and_raises_the_tier(self):
        """The live check is evaluated first and fires at a live count of two.

        PRD: "In the second hop, the water body's `detection_count` is incremented
        by 1, and its `live_detection_count` is incremented by 1 as well when the
        report's `detection_class` is `LIVE_ORGANISM`; the escalation rule then runs
        **on the counters as they stand after those increments**. When
        `live_detection_count` has reached 2, the water body's `infestation_status`
        is set to `CONFIRMED_INFESTED` and its `risk_tier` is set to `HIGH`."

        Design: Difficulty/transitive_cascade/detection_acceptance_cascades_four_hops_to_station_hours_staffing
        """
        ctx, _first, _second, report = _water_body_at_suspect_with_a_second_report_submitted()

        accepted = acknowledge_detection_report(
            report["id"], "ACCEPTED", state_db_ack_id="ACK-0002"
        )

        assert accepted["status"] == "ACCEPTED"
        assert accepted["state_db_ack_id"] == "ACK-0002"
        water_body = fetch_water_body(ctx["water_body"]["id"])
        assert water_body["detection_count"] == 2
        assert water_body["live_detection_count"] == 2
        assert water_body["infestation_status"] == "CONFIRMED_INFESTED"
        assert water_body["risk_tier"] == "HIGH"

    def test_the_confirmation_makes_inspection_mandatory_and_doubles_the_staffing(self):
        """Hops three and four reach the station and every SINGLE hours window.

        PRD: "The third hop is a policy change at the stations. *Because* the water
        body became `CONFIRMED_INFESTED`, every station whose `water_body_id` is
        that water body and whose `status` is `PLANNED`, `OPEN` or `SUSPENDED` and
        whose `mandatory_inspection` is currently false has `mandatory_inspection`
        set to true"  PRD: "The fourth hop follows from the third: *because* those
        stations flipped from voluntary to mandatory, every operating-hours window
        of each such station whose `staffing_level` is `SINGLE` is upgraded to
        `DOUBLE`, since a mandatory checkpoint needs two crew."

        Design: Difficulty/transitive_cascade/detection_acceptance_cascades_four_hops_to_station_hours_staffing
        """
        ctx, _first, _second, report = _water_body_at_suspect_with_a_second_report_submitted()

        acknowledge_detection_report(
            report["id"], "ACCEPTED", state_db_ack_id="ACK-0002"
        )

        station = fetch_station(ctx["station"]["id"])
        assert station["mandatory_inspection"] is True
        assert station["status"] == "OPEN"
        assert [row["staffing_level"] for row in fetch_station_hours(station["id"])] == [
            "DOUBLE"
        ]

    def test_the_cascade_never_rescores_the_records_it_passes(self):
        """Both records keep the score their own screening froze.

        PRD: "The **risk score** is a weighted point count over exactly two other
        rows: the water body named by `prior_water_body_id` and the vessel named by
        `watercraft_id`. No sibling inspection record contributes anything."

        Design: Difficulty/transitive_cascade/detection_acceptance_cascades_four_hops_to_station_hours_staffing
        """
        _ctx, first_record, second_record, report = (
            _water_body_at_suspect_with_a_second_report_submitted()
        )

        acknowledge_detection_report(
            report["id"], "ACCEPTED", state_db_ack_id="ACK-0002"
        )

        first = fetch_record(first_record["id"])
        assert first["risk_score"] == 20
        assert first["risk_band"] == "LOW"
        second = fetch_record(second_record["id"])
        assert second["risk_score"] == 35
        assert second["risk_band"] == "MODERATE"
