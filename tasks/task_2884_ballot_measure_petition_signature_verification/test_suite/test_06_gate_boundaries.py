"""Inclusive boundaries examined from exactly on the line and one step off it.

The sufficiency lower gate, the closed `signed_on` circulation window, and the
county distribution minimum.
"""
from test_helpers import (
    api_client,
    add_line,
    add_signature_payload,
    assert_instants_equal,
    file_batch_with_lines,
    make_examiner_headers,
    make_proponent_headers,
    read_batch,
    read_petition,
    run_verification_round,
    setup_circulation_ready,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

# Under STANDARD_BASE the frozen threshold is ceil(100 * 200 / 10000) == 2, so
# the upper gate is ceil(2 * 15000 / 10000) == 3 and the lower gate is
# floor(2 * 5000 / 10000) == 1.
LOWER_GATE = 1
UPPER_GATE = 3


def _four_line_petition(active_voter_ids):
    """A census-sampled four-line ALPHA batch where only the named voters are
    ACTIVE on the roll."""
    set_clock(CLOCK_EPOCH)
    voters = [
        {
            "voter_id_number": vid,
            "registration_status": "ACTIVE" if vid in active_voter_ids else "INACTIVE",
        }
        for vid in ("VA1", "VA2", "VA3", "VA4")
    ]
    world = setup_circulation_ready(counties=[("ALPHA", 20)], voters=voters)
    file_batch_with_lines(world, ["VA1", "VA2", "VA3", "VA4"], batch_key="b1")
    return world


class TestSufficiencyLowerGate:
    """Both band comparisons are inclusive, so the lower gate itself is a
    failing projection."""

    def test_a_projection_landing_exactly_on_the_lower_gate_is_insufficient(self):
        """One valid line in four gives a 2500-bps rate and a projection of 1,
        which is the lower gate exactly — and therefore INSUFFICIENT.

        PRD §3.6: "For a RANDOM_SAMPLE round, a projected_valid_count at or
        above the upper gate yields SUFFICIENT; one at or below the lower gate
        yields INSUFFICIENT; anything strictly between the two yields
        FULL_CHECK_REQUIRED. Both comparisons are inclusive, so a projection
        landing exactly on the lower gate is INSUFFICIENT."

        Design: Difficulty/boundary_precision_check/sufficiency_lower_gate_inclusive_boundary
        """
        world = _four_line_petition({"VA1"})

        closed = run_verification_round(world)
        assert closed["sample_size"] == 4, "sample_pct_bps 10000 draws the whole pool"
        assert closed["sampled_valid_count"] == 1
        assert closed["validity_rate_bps"] == 2500, "floor(1 * 10000 / 4)"
        assert closed["projected_valid_count"] == LOWER_GATE
        assert closed["determination"] == "INSUFFICIENT"

        petition = read_petition(world["petition"]["id"])
        assert petition["required_valid_signatures"] == 2
        assert petition["accepted_raw_total"] == 4
        assert petition["projected_valid_count"] == 1
        assert petition["status"] == "CURE_PERIOD", (
            "cure-eligible: 1 * 10000 is at or above 2 * 5000"
        )

        batch = read_batch(world["batches"]["b1"]["batch"]["id"])
        assert batch["status"] == "SAMPLED"
        assert batch["verification_cost_cents"] == 19

    def test_a_projection_one_signature_above_the_lower_gate_requires_a_full_check(self):
        """Two valid lines in four lift the projection to 2 — strictly between
        the gates, so the middle band applies instead.

        PRD §3.6: "anything strictly between the two yields
        FULL_CHECK_REQUIRED."

        Design: Difficulty/boundary_precision_check/sufficiency_lower_gate_inclusive_boundary
        """
        world = _four_line_petition({"VA1", "VA2"})

        closed = run_verification_round(world)
        assert closed["sampled_valid_count"] == 2
        assert closed["validity_rate_bps"] == 5000
        assert closed["projected_valid_count"] == 2
        assert LOWER_GATE < 2 < UPPER_GATE
        assert closed["determination"] == "FULL_CHECK_REQUIRED"

        assert read_petition(world["petition"]["id"])["status"] == "FULL_CHECK"


class TestSignedOnClosedWindow:
    """`signed_on` runs from `cleared_at` through `circulation_deadline`,
    inclusive at both ends."""

    CLEARED_AT = "2026-08-01T00:00:00Z"
    DEADLINE = "2027-01-28T00:00:00Z"
    DAY_AFTER_DEADLINE = "2027-01-29T00:00:00Z"
    DAY_BEFORE_CLEARANCE = "2026-07-31T00:00:00Z"

    def _open_batch(self):
        """A petition cleared at the clock epoch, with the clock then parked at
        2026-08-10 and an unverified ALPHA batch open for lines."""
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)],
            voters=["VA1", "VA2", "VA3", "VA4"],
        )
        petition = read_petition(world["petition"]["id"])
        assert petition["cleared_at"] == "2026-08-01T00:00:00.000Z"
        assert petition["circulation_deadline"] == "2027-01-28T00:00:00.000Z", (
            "cleared_at advanced by circulation_window_days 180"
        )
        set_clock("2026-08-10T00:00:00Z")
        record = file_batch_with_lines(world, [], batch_key="b1", verify=False)
        world["batch_id"] = record["batch"]["id"]
        return world

    def test_lines_signed_on_either_endpoint_of_the_window_are_accepted(self):
        """A line signed on `cleared_at` and a line signed on
        `circulation_deadline` are both inside the window.

        PRD §3.4: "Every line's signed_on must fall inside the petition's window,
        from cleared_at through circulation_deadline inclusive at both ends."

        Design: Difficulty/boundary_precision_check/signed_on_closed_window_endpoint_boundary
        """
        world = self._open_batch()

        first = add_line(
            world["batch_id"], line_number=1, claimed_voter_id_number="VA1",
            signed_on=self.CLEARED_AT,
        )
        assert_instants_equal(first["signed_on"], self.CLEARED_AT, "line 1 signed_on")

        second = add_line(
            world["batch_id"], line_number=2, claimed_voter_id_number="VA2",
            signed_on=self.DEADLINE,
        )
        assert_instants_equal(second["signed_on"], self.DEADLINE, "line 2 signed_on")

        assert read_batch(world["batch_id"])["raw_count"] == 2
        assert read_petition(world["petition"]["id"])["raw_signature_count"] == 2

    def test_a_line_signed_the_day_after_the_deadline_is_refused(self):
        """One day past `circulation_deadline` falls outside the closed window.

        PRD §3.4: "A line signed outside its applicable window is refused with
        ERR_SIGNED_OUTSIDE_WINDOW."

        Design: Difficulty/boundary_precision_check/signed_on_closed_window_endpoint_boundary
        """
        world = self._open_batch()
        add_line(
            world["batch_id"], line_number=1, claimed_voter_id_number="VA1",
            signed_on=self.CLEARED_AT,
        )

        validate_error(
            api_client.add_signature(
                world["batch_id"],
                add_signature_payload(
                    line_number=3,
                    claimed_voter_id_number="VA3",
                    signed_on=self.DAY_AFTER_DEADLINE,
                    signature_hash="H-VA3",
                    signer_name="Signer VA3",
                ),
                make_proponent_headers(),
            ),
            "ERR_SIGNED_OUTSIDE_WINDOW",
            409,
        )

        assert read_batch(world["batch_id"])["raw_count"] == 1

    def test_a_line_signed_the_day_before_clearance_is_refused(self):
        """One day before `cleared_at` falls outside the closed window on the
        other side.

        PRD §3.4: "Every line's signed_on must fall inside the petition's window,
        from cleared_at through circulation_deadline inclusive at both ends ... A
        line signed outside its applicable window is refused with
        ERR_SIGNED_OUTSIDE_WINDOW."

        Design: Difficulty/boundary_precision_check/signed_on_closed_window_endpoint_boundary
        """
        world = self._open_batch()
        add_line(
            world["batch_id"], line_number=1, claimed_voter_id_number="VA1",
            signed_on=self.DEADLINE,
        )

        validate_error(
            api_client.add_signature(
                world["batch_id"],
                add_signature_payload(
                    line_number=4,
                    claimed_voter_id_number="VA4",
                    signed_on=self.DAY_BEFORE_CLEARANCE,
                    signature_hash="H-VA4",
                    signer_name="Signer VA4",
                ),
                make_proponent_headers(),
            ),
            "ERR_SIGNED_OUTSIDE_WINDOW",
            409,
        )

        assert read_batch(world["batch_id"])["raw_count"] == 1
        assert read_petition(world["petition"]["id"])["raw_signature_count"] == 1


class TestCountyDistributionMinimum:
    """A county exactly on its minimum qualifies; one credit short does not."""

    def _two_county_report(self):
        """ALPHA (20 registered voters, minimum 1) and BRAVO (40, minimum 2),
        one valid line each, after a FULL_CHECK round."""
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20), ("BRAVO", 40)],
            voters=[
                {"voter_id_number": "VA1", "county_code": "ALPHA",
                 "registration_status": "ACTIVE"},
                {"voter_id_number": "VB1", "county_code": "BRAVO",
                 "registration_status": "ACTIVE"},
            ],
        )
        file_batch_with_lines(world, ["VA1"], county_code="ALPHA", batch_key="alpha")
        file_batch_with_lines(world, ["VB1"], county_code="BRAVO", batch_key="bravo")
        closed = run_verification_round(world, round_type="FULL_CHECK")
        assert closed["determination"] == "SUFFICIENT"
        report = validate_success(
            api_client.get_distribution_report(
                world["petition"]["id"], make_examiner_headers()
            )
        )
        world["report"] = {row["county_code"]: row for row in report["counties"]}
        world["report_root"] = report
        return world

    def test_a_county_sitting_exactly_on_its_minimum_qualifies(self):
        """ALPHA's minimum is 1 and its credited count is 1, so the inclusive
        comparison lets it qualify.

        PRD §3.6: "that county's minimum is its registered_voter_count
        multiplied by the standard's county_distribution_pct_bps, divided by
        10000, with any remainder rounded up ... A county qualifies when its
        credited count is at or above its minimum, so a county sitting exactly on
        its minimum qualifies."

        Design: Difficulty/boundary_precision_check/county_distribution_minimum_inclusive_boundary
        """
        world = self._two_county_report()
        alpha = world["report"]["ALPHA"]

        assert alpha["distribution_minimum"] == 1, "ceil(20 * 500 / 10000)"
        assert alpha["credited_count"] == 1, (
            "the latest closed round is a FULL_CHECK, so credit is the VALID line count"
        )
        assert alpha["qualifies"] is True

        assert world["report_root"]["qualifying_county_count"] == 1
        assert world["report_root"]["required_qualifying_counties"] == 1

        petition = read_petition(world["petition"]["id"])
        assert petition["accepted_raw_total"] == 2
        assert petition["qualifying_county_count"] == 1
        assert petition["status"] == "PENDING_CERTIFICATION"

    def test_a_county_one_credit_short_of_its_minimum_does_not_qualify(self):
        """BRAVO's larger roll lifts its minimum to 2 while it too carries only
        one valid line, so it fails the same inclusive comparison.

        PRD §2.6: "Each county's distribution minimum rounds up; each county's
        credited projection rounds down; the qualification comparison is
        inclusive."

        Design: Difficulty/boundary_precision_check/county_distribution_minimum_inclusive_boundary
        """
        world = self._two_county_report()
        bravo = world["report"]["BRAVO"]

        assert bravo["distribution_minimum"] == 2, "ceil(40 * 500 / 10000)"
        assert bravo["credited_count"] == 1
        assert bravo["qualifies"] is False

        assert world["report_root"]["qualifying_county_count"] == 1, (
            "ALPHA alone qualifies, which still meets required_qualifying_counties 1"
        )
