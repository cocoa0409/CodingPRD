"""Boundaries: the density ceiling, the footage count and the booth buffer."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def _jp_market_with_a_pass_at_the_ceiling(api):
    """A FUNCTIONAL pass over 160 units carrying two open S2 defects."""
    world = fx.build_market(api, title_code="NOVA-20", name="Nova Drift 20",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    world["qa_pass"] = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 160)
    world["bug_a"] = fx.log_bug(api, world["qa_pass"]["id"],
                                bug_class="FUNCTIONAL_CRASH", severity="S2",
                                summary="Crash on language switch.")
    world["bug_b"] = fx.log_bug(api, world["qa_pass"]["id"],
                                bug_class="FUNCTIONAL_CRASH", severity="S2",
                                summary="Crash on subtitle toggle.")
    return world


def test_a_density_exactly_at_the_ceiling_refuses_the_close(api):
    """The ceiling comparison is strict, so equality is a violation.

    "And the density gate must pass: `defect_density` must be **strictly less
    than** the ceiling of 0.0500, so a density exactly equal to the ceiling is a
    violation and is rejected with `ERR_DEFECT_DENSITY_EXCEEDED`."

    "To make the boundary concrete: a pass with an `inspected_unit_count` of 160
    carrying two open `S2` defects has eight weighted points and a density of
    exactly 0.0500, and its close is refused; verifying one of those two fixes
    leaves four points and a density of 0.0250, and the close then succeeds."

    Design: Difficulty/boundary_precision_check/qa_pass_close_at_defect_density_exactly_at_ceiling_rejected
    """
    world = _jp_market_with_a_pass_at_the_ceiling(api)
    at_ceiling = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert at_ceiling["weighted_defect_points"] == 8
    A.assert_defect_density(at_ceiling["defect_density"], 0.0500)

    response = api.close_qa_pass(world["qa_pass"]["id"], users.LQA_CLOSER)

    validate_error(response, E.ERR_DEFECT_DENSITY_EXCEEDED, expected_status=422)
    after = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert after["status"] == "OPEN"
    assert after["closed_at_utc"] is None
    assert after["weighted_defect_points"] == 8
    A.assert_defect_density(after["defect_density"], 0.0500)


def test_one_more_inspected_unit_rounds_the_density_below_the_ceiling(api):
    """The four-decimal rounding is what separates 0.0500 from 0.0497.

    "`defect_density` is `weighted_defect_points` divided by the pass's
    `inspected_unit_count`, rounded half up to four decimal places."

    Eight weighted points over 161 inspected units is 0.04968944…, which rounds
    to 0.0497 and is strictly below the ceiling, so the same two `S2` defects
    close cleanly one unit further into the sample.

    Design: Difficulty/boundary_precision_check/qa_pass_close_at_defect_density_exactly_at_ceiling_rejected
    """
    world = _jp_market_with_a_pass_at_the_ceiling(api)
    linguistic = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 161)
    fx.log_bug(api, linguistic["id"], bug_class="MISTRANSLATION", severity="S2",
               summary="Honorific register wrong in the opening line.")
    fx.log_bug(api, linguistic["id"], bug_class="MISTRANSLATION", severity="S2",
               summary="Item name inconsistent with the glossary.")
    below = fx.read_qa_pass(api, linguistic["id"])
    assert below["weighted_defect_points"] == 8
    A.assert_defect_density(below["defect_density"], 0.0497)

    closed = validate_success(api.close_qa_pass(linguistic["id"], users.LQA_CLOSER))

    assert closed["status"] == "CLOSED"
    A.assert_defect_density(closed["defect_density"], 0.0497)
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")


def test_verifying_one_of_the_two_defects_clears_the_gate(api):
    """Halving the open set halves the density and the close succeeds.

    "A pass's `weighted_defect_points` is the sum of the severity weights of
    every defect filed under that pass whose `status` is `NEW`, `TRIAGED` or
    `FIX_SUBMITTED` — the *open set*."

    "On success `status` becomes `CLOSED`, `closed_at_utc` is stamped with the
    logical clock, `weighted_defect_points` and `defect_density` are frozen at
    the values that passed the gate, and the pass's `version` increments by 1."

    Design: Difficulty/boundary_precision_check/qa_pass_close_at_defect_density_exactly_at_ceiling_rejected
    """
    world = _jp_market_with_a_pass_at_the_ceiling(api)
    fx.resolve_bug(api, world["bug_a"]["id"])
    cleared = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert cleared["weighted_defect_points"] == 4
    A.assert_defect_density(cleared["defect_density"], 0.0250)

    closed = validate_success(
        api.close_qa_pass(world["qa_pass"]["id"], users.LQA_CLOSER)
    )

    assert closed["status"] == "CLOSED"
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")
    A.assert_defect_density(closed["defect_density"], 0.0250)


def _de_market_awaiting_a_gambling_disclosure(api):
    return fx.build_market(api, title_code="NOVA-21", name="Nova Drift 21",
                           market_code="DE", scope_tier="TEXT_ONLY",
                           target_rating="TEEN_12", budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)


def test_zero_footage_assets_is_one_short_of_the_evidence_minimum(api):
    """The footage rule bites at exactly zero attached assets.

    "And when the effective disclosure set shares at least one descriptor with
    the four footage-mandatory descriptors of §2.9, `footage_asset_count` must be
    at least 1; a zero count is `ERR_FOOTAGE_EVIDENCE_MISSING`."

    "Four descriptors make gameplay footage evidence mandatory in every market:
    `VIOLENCE_REALISTIC`, `SEXUAL_CONTENT`, `GAMBLING_SIM` and `LOOTBOX_PAID`."

    Design: Difficulty/boundary_precision_check/submission_submit_with_zero_footage_assets_rejected
    """
    world = _de_market_awaiting_a_gambling_disclosure(api)
    submission = fx.draft_submission(api, world["plan"]["id"], ["GAMBLING_SIM"], 0,
                                     "TEEN_12")
    assert submission["footage_asset_count"] == 0

    response = api.submit_rating_submission(submission["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_FOOTAGE_EVIDENCE_MISSING, expected_status=422)
    after = fx.read_submission(api, submission["id"])
    assert after["status"] == "DRAFT"
    A.assert_money_cents(after["fee_cents"], 0, "fee_cents")
    assert after["submitted_at_utc"] is None


def test_one_footage_asset_carries_the_round_two_fee(api):
    """A single asset satisfies the evidence rule and the filing is priced.

    "Step one computes a pre-discount subtotal as the board's base fee plus
    75,000 cents for each round beyond the first — that is, the base fee plus
    `submission_round` minus one, multiplied by the round surcharge."

    "Each board carries a base fee in cents: `CERO` 480,000, `USK` 350,000,
    `DJCTQ` 300,000, `ESRB` 320,000, `ACB` 290,000 and `GRAC` 260,000."

    The round-two `USK` subtotal is 425,000, there is no expedite fee 122 days
    out, the tier keyed on 425,000 is five per cent and the discount is 21,250,
    so the fee is 403,750. `GAMBLING_SIM` alone is 18 base points.

    Design: Difficulty/boundary_precision_check/submission_submit_with_zero_footage_assets_rejected
    """
    world = _de_market_awaiting_a_gambling_disclosure(api)
    first = fx.draft_submission(api, world["plan"]["id"], ["GAMBLING_SIM"], 0,
                                "TEEN_12")
    validate_success(api.withdraw_rating_submission(first["id"], users.COMPLIANCE))
    second = fx.draft_submission(api, world["plan"]["id"], ["GAMBLING_SIM"], 1,
                                 "TEEN_12")
    assert second["submission_round"] == 2
    assert second["footage_asset_count"] == 1

    filed = validate_success(
        api.submit_rating_submission(second["id"], users.COMPLIANCE)
    )

    assert filed["status"] == "SUBMITTED"
    A.assert_money_cents(filed["fee_cents"], 403750, "fee_cents")
    assert filed["self_assessed_risk_score"] == 18
    assert A.band_for_score(18) == "ALL_AGES"
    assert filed["projected_rating_band"] is None


def _voiced_market_with_a_buffered_session(api):
    world = fx.build_market(api, title_code="NOVA-22", name="Nova Drift 22",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=9000000,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="BER-D",
                            turnaround_buffer_minutes=30,
                            max_daily_recording_minutes=240,
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["session"] = fx.book_session(api, world["plan"]["id"],
                                       world["talent"]["id"], world["booth"]["id"],
                                       world["contract"]["id"],
                                       start_utc="2026-09-10T09:00:00Z",
                                       end_utc="2026-09-10T12:00:00Z",
                                       planned_line_count=120)
    return world


def _booking_at(world, start_utc, end_utc):
    return f.voice_session_payload(
        world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc=start_utc, end_utc=end_utc,
        planned_line_count=40,
    )


def test_a_booking_one_minute_inside_the_buffer_is_refused(api):
    """The buffered interval is occupied right up to its upper bound.

    "Every session occupies its booth for a half-open interval that begins at
    `start_utc` and ends at `occupied_end_utc`, which is `end_utc` advanced by
    the booth's `turnaround_buffer_minutes`."

    "Because both intervals are half-open, a session starting exactly at an
    existing session's `occupied_end_utc` is accepted, while one starting a
    single minute earlier is rejected."

    Design: Difficulty/boundary_precision_check/booth_buffer_boundary_one_minute_early_rejected
    """
    world = _voiced_market_with_a_buffered_session(api)
    session = world["session"]
    assert session["duration_minutes"] == 180
    A.assert_instant_equals(session["occupied_end_utc"], "2026-09-10T12:30:00Z",
                            "occupied_end_utc")

    response = api.create_voice_session(
        _booking_at(world, "2026-09-10T12:29:00Z", "2026-09-10T13:29:00Z"),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_BOOTH_WINDOW_CONFLICT, expected_status=409)
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 210


def test_a_booking_exactly_at_the_buffer_end_is_accepted_at_the_daily_cap(api):
    """12:30 is free, and the talent lands on exactly the daily maximum.

    "A new booking is rejected with `ERR_TALENT_DAILY_CAPACITY_EXCEEDED` when the
    talent's already-reserved minutes on the date of the new session's
    `start_utc`, plus the new session's `duration_minutes`, is strictly greater
    than the talent's `max_daily_recording_minutes`."

    "Booking a talent to exactly their daily cap is therefore accepted."

    180 recorded-day minutes plus a 60-minute booking is exactly the 240-minute
    cap, and the booth ends up holding 300 reserved minutes: 180 plus 30 for the
    first booking and 60 plus 30 for the second.

    Design: Difficulty/boundary_precision_check/booth_buffer_boundary_one_minute_early_rejected
    """
    world = _voiced_market_with_a_buffered_session(api)

    accepted = validate_success(
        api.create_voice_session(
            _booking_at(world, "2026-09-10T12:30:00Z", "2026-09-10T13:30:00Z"),
            users.PRODUCER,
        ),
        expected_status=201,
    )

    assert accepted["status"] == "SCHEDULED"
    assert accepted["duration_minutes"] == 60
    A.assert_instant_equals(accepted["occupied_end_utc"], "2026-09-10T14:00:00Z",
                            "occupied_end_utc")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 300
    sessions, meta = validate_paginated(
        api.list_voice_sessions(users.PRODUCER,
                                {"recording_booth_id": world["booth"]["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in sessions] == [world["session"]["id"],
                                               accepted["id"]]
