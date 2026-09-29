"""Calculation edges: band selection, per-key rounding, density precision, fee tiers.

Every number asserted here is re-derived from the arithmetic sections of the
specification: the translation-effort bands and their pinned rounding order, the
localization cost components and their input-set filters, the weighted defect
points and their four-decimal density, the risk-score band table, the pinned
five-step submission fee, and the ordered release-gate posture chain.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# ─── Key corpora ───────────────────────────────────────────────────────

# Six 100-character MENU keys straddling all three translation-memory band
# edges. MENU carries a surface uplift of 1.00, so band selection is the only
# thing that moves each contribution.
_TM_BAND_KEY_SPECS = [
    {
        "key_name": "band.a95",
        "source_text": "exact band sample",
        "source_char_count": 100,
        "ui_surface": "MENU",
        "display_char_limit": 400,
        "tm_match_pct": 95,
    },
    {
        "key_name": "band.b94",
        "source_text": "high fuzzy upper sample",
        "source_char_count": 100,
        "ui_surface": "MENU",
        "display_char_limit": 400,
        "tm_match_pct": 94,
    },
    {
        "key_name": "band.c75",
        "source_text": "high fuzzy lower sample",
        "source_char_count": 100,
        "ui_surface": "MENU",
        "display_char_limit": 400,
        "tm_match_pct": 75,
    },
    {
        "key_name": "band.d74",
        "source_text": "low fuzzy upper sample",
        "source_char_count": 100,
        "ui_surface": "MENU",
        "display_char_limit": 400,
        "tm_match_pct": 74,
    },
    {
        "key_name": "band.e50",
        "source_text": "low fuzzy lower sample",
        "source_char_count": 100,
        "ui_surface": "MENU",
        "display_char_limit": 400,
        "tm_match_pct": 50,
    },
    {
        "key_name": "band.f49",
        "source_text": "new band sample",
        "source_char_count": 100,
        "ui_surface": "MENU",
        "display_char_limit": 400,
        "tm_match_pct": 49,
    },
]

# The two keys that sit either side of the exact-band edge on their own.
_TM_EDGE_KEY_SPECS = [_TM_BAND_KEY_SPECS[0], _TM_BAND_KEY_SPECS[1]]

# Four 200-character keys at the same tm 60, differing only in ui_surface.
_SURFACE_KEY_SPECS = [
    {
        "key_name": "surface.a_legal",
        "source_text": "legal surface sample",
        "source_char_count": 200,
        "ui_surface": "LEGAL",
        "display_char_limit": 600,
        "tm_match_pct": 60,
        "context_note": "End user licence agreement footer, reviewed by counsel.",
    },
    {
        "key_name": "surface.b_subtitle",
        "source_text": "subtitle surface sample",
        "source_char_count": 200,
        "ui_surface": "SUBTITLE",
        "display_char_limit": 600,
        "tm_match_pct": 60,
    },
    {
        "key_name": "surface.c_hud",
        "source_text": "hud surface sample",
        "source_char_count": 200,
        "ui_surface": "HUD",
        "display_char_limit": 600,
        "tm_match_pct": 60,
    },
    {
        "key_name": "surface.d_menu",
        "source_text": "menu surface sample",
        "source_char_count": 200,
        "ui_surface": "MENU",
        "display_char_limit": 600,
        "tm_match_pct": 60,
    },
]


def test_tm_band_edges_are_read_per_key_before_the_contributions_are_summed(api):
    """Six keys straddling all three band edges total 3.70, not 3.50.

    "The translation-memory factor is 0.10 when the match percentage is at least
    95 (the exact band), 0.45 when it is at least 75 and less than 95 (the
    high-fuzzy band), 0.75 when it is at least 50 and less than 75 (the low-fuzzy
    band), and 1.00 when it is below 50 (the new-text band)."

    "**Each row's raw contribution is rounded half up to one decimal place
    first.** Only then are the rounded per-row values summed, and the sum is
    rounded half up to two decimal places."

    All six keys are 100 source characters on a MENU surface, so each raw
    contribution is exactly its band factor: 0.10, 0.45, 0.45, 0.75, 0.75 and
    1.00. Rounded per key those become 0.1, 0.5, 0.5, 0.8, 0.8 and 1.0 for a
    total of 3.70; summing the unrounded factors first gives 3.50 instead.

    Design: Corner/calculations/tm_band_boundaries_are_read_per_key_before_summing
    """
    world = fx.build_market(api, title_code="NOVA-51", name="Nova Drift 51",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=_TM_BAND_KEY_SPECS,
                            stage=fx.STAGE_STRINGS_LOCKED)

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    assert plan["status"] == "SCOPED"
    A.assert_effort_units(plan["text_effort_units"], 3.70)
    assert round(float(plan["text_effort_units"]), 2) != 3.50
    assert plan["text_effort_variant"] == "SCOPE_ESTIMATE"
    A.assert_effort_units(A.effort_units(_TM_BAND_KEY_SPECS), 3.70)
    assert plan["required_unit_count"] == 6


def test_tm_band_selection_carries_into_the_localization_cost_in_cents(api):
    """The 3.70 units price at 15,540 cents under the TEXT_ONLY multiplier.

    "The text component is `text_effort_units` multiplied by a text rate of
    4,200 cents per effort unit, multiplied by a scope multiplier of 1.00 for
    `TEXT_ONLY`, 1.25 for `SUBTITLED`, 1.80 for `FULL_VOICE` or 2.40 for
    `FULL_CULTURAL`, with that product rounded half up to whole cents."

    "For any other scope tier the surcharge is zero."

    3.70 units at 4,200 cents and a TEXT_ONLY multiplier of 1.00 is 15,540
    cents, comfortably under the 5,000,000-cent cap, so the overage is zero. The
    3.50 that the sum-then-round order produces would have priced at 14,700.

    Design: Corner/calculations/tm_band_boundaries_are_read_per_key_before_summing
    """
    world = fx.build_market(api, title_code="NOVA-51", name="Nova Drift 51",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=_TM_BAND_KEY_SPECS,
                            stage=fx.STAGE_STRINGS_LOCKED)

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    A.assert_money_cents(plan["localization_cost_cents"], 15540,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")
    assert plan["localization_cost_cents"] != 14700


def test_a_ninety_five_per_cent_match_is_the_first_exact_band_key(api):
    """95 lands in the exact band and 94 in the high-fuzzy band.

    "The translation-memory factor is 0.10 when the match percentage is at least
    95 (the exact band), 0.45 when it is at least 75 and less than 95 (the
    high-fuzzy band), 0.75 when it is at least 50 and less than 75 (the low-fuzzy
    band), and 1.00 when it is below 50 (the new-text band)."

    Two 100-character MENU keys one match point apart contribute 0.1 and 0.5 for
    a total of 0.60 units and 2,520 cents. Reading 95 as the last high-fuzzy key
    instead would have made both contributions 0.5, that is 1.00 unit.

    Design: Corner/calculations/tm_band_boundaries_are_read_per_key_before_summing
    """
    world = fx.build_market(api, title_code="NOVA-51E", name="Nova Drift 51 Edge",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=_TM_EDGE_KEY_SPECS,
                            stage=fx.STAGE_STRINGS_LOCKED)

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    A.assert_effort_units(plan["text_effort_units"], 0.60)
    assert round(float(plan["text_effort_units"]), 2) != 1.00
    A.assert_money_cents(plan["localization_cost_cents"], 2520,
                         "localization_cost_cents")
    assert A.tm_factor(95) == 0.10
    assert A.tm_factor(94) == 0.45


def test_surface_uplift_is_applied_to_each_key_before_its_own_rounding(api):
    """Four keys at the same match differ only by surface: 2.3, 1.8, 1.7 and 1.5.

    "The surface uplift is 1.50 for `LEGAL`, 1.20 for `SUBTITLE`, 1.10 for `HUD`
    and 1.00 for `MENU`."

    "**Each row's raw contribution is rounded half up to one decimal place
    first.** Only then are the rounded per-row values summed, and the sum is
    rounded half up to two decimal places."

    Every key is 200 source characters at tm 60, so each raw contribution is
    2.00 times the low-fuzzy factor 0.75 times its uplift: 2.25 for LEGAL, 1.80
    for SUBTITLE, 1.65 for HUD and 1.50 for MENU. Rounded half up to one decimal
    those are 2.3, 1.8, 1.7 and 1.5, and the total is 7.30 units.

    Design: Corner/calculations/surface_uplift_multipliers_applied_per_key
    """
    world = fx.build_market(api, title_code="NOVA-52", name="Nova Drift 52",
                            market_code="DE", scope_tier="SUBTITLED",
                            target_rating="MATURE_15", budget_cap_cents=5000000,
                            key_specs=_SURFACE_KEY_SPECS,
                            stage=fx.STAGE_STRINGS_LOCKED)

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    assert plan["status"] == "SCOPED"
    A.assert_effort_units(plan["text_effort_units"], 7.30)
    assert plan["text_effort_variant"] == "SCOPE_ESTIMATE"
    A.assert_effort_units(A.effort_units(_SURFACE_KEY_SPECS), 7.30)
    assert plan["required_unit_count"] == 4
    assert world["keys"]["surface.a_legal"]["context_note"] is not None


def test_the_scope_multiplier_moves_the_money_and_never_the_units(api):
    """Two plans over one key set: 7.30 units both ways, 30,660 against 38,325.

    "The text component is `text_effort_units` multiplied by a text rate of
    4,200 cents per effort unit, multiplied by a scope multiplier of 1.00 for
    `TEXT_ONLY`, 1.25 for `SUBTITLED`, 1.80 for `FULL_VOICE` or 2.40 for
    `FULL_CULTURAL`, with that product rounded half up to whole cents."

    "A cultural surcharge applies only when `scope_tier` is `FULL_CULTURAL`, and
    it has a hard floor: it is the greater of 1,500,000 cents and fifteen per
    cent of the sum of the text and voice components rounded half up to whole
    cents."

    The SUBTITLED market prices 7.30 units at 4,200 times 1.25, which is 38,325
    cents, while the TEXT_ONLY market over the identical keys pays 30,660. Both
    effort figures stay at 7.30, and neither tier takes a cultural surcharge, so
    each subtotal is its text component alone.

    Design: Corner/calculations/surface_uplift_multipliers_applied_per_key
    """
    world = fx.build_market(api, title_code="NOVA-52", name="Nova Drift 52",
                            market_code="DE", scope_tier="SUBTITLED",
                            target_rating="MATURE_15", budget_cap_cents=5000000,
                            key_specs=_SURFACE_KEY_SPECS,
                            stage=fx.STAGE_STRINGS_LOCKED)
    text_only_plan = fx.create_market_plan(api, world["title"]["id"],
                                           market_code="JP",
                                           scope_tier="TEXT_ONLY",
                                           target_rating="TEEN_12",
                                           budget_cap_cents=5000000)

    subtitled = validate_success(
        api.scope_market_plan(world["plan"]["id"], users.PRODUCER)
    )
    text_only = validate_success(
        api.scope_market_plan(text_only_plan["id"], users.PRODUCER)
    )

    A.assert_effort_units(subtitled["text_effort_units"], 7.30)
    A.assert_effort_units(text_only["text_effort_units"], 7.30)
    A.assert_money_cents(subtitled["localization_cost_cents"], 38325,
                         "localization_cost_cents")
    A.assert_money_cents(text_only["localization_cost_cents"], 30660,
                         "localization_cost_cents")
    A.assert_money_cents(subtitled["overage_cents"], 0, "overage_cents")
    A.assert_money_cents(text_only["overage_cents"], 0, "overage_cents")
    assert subtitled["cultural_adaptation_required"] is False


def _jp_voiced_market_with_one_menu_key(api):
    """A JP FULL_VOICE market in IN_LOCALIZATION with booth, talent and contract.

    The single 125-character MENU key at tm 96 scopes to 0.10 effort units, so
    the text component is 0.10 x 4,200 x 1.80 = 756 cents.
    """
    return fx.build_market(api, title_code="NOVA-53", name="Nova Drift 53",
                           market_code="JP", scope_tier="FULL_VOICE",
                           target_rating="TEEN_12", budget_cap_cents=9000000,
                           required_voice_line_count=100,
                           key_specs=[f.MENU_KEY_SPEC],
                           booth_code="TOK-E", turnaround_buffer_minutes=30,
                           talent_name="Miki Sato", talent_language_code="JA",
                           buyout_fee_cents=500000, per_line_rate_cents=250,
                           territory_scope=["JP"],
                           stage=fx.STAGE_IN_LOCALIZATION)


def test_a_scheduled_and_in_progress_session_adds_no_cost_and_no_commitment(api):
    """Booking reserves booth minutes while billing exactly nothing.

    "The voice component is the sum, over every recording session of this market
    plan whose `status` is `RECORDED`, of that session's `recorded_line_count`
    multiplied by the `per_line_rate_cents` of the talent contract the session
    was booked against; sessions in `SCHEDULED`, `IN_PROGRESS` or `CANCELLED`
    contribute exactly zero."

    "A booth's `reserved_minutes_total` is the sum, over every session on that
    booth whose `status` is `SCHEDULED`, `IN_PROGRESS` or `RECORDED`, of that
    session's `duration_minutes` plus the booth's `turnaround_buffer_minutes`."

    The 09:00-to-11:00 booking is 120 minutes and occupies the booth until
    11:30, so the booth holds 150 reserved minutes from the moment it is booked,
    yet the plan's cost stays at its scope-time 756 cents and the contract's
    commitment stays at the 500,000-cent buyout through both SCHEDULED and
    IN_PROGRESS.

    Design: Corner/calculations/localization_cost_counts_only_recorded_voice_sessions
    """
    world = _jp_voiced_market_with_one_menu_key(api)
    A.assert_money_cents(world["plan"]["localization_cost_cents"], 756,
                         "localization_cost_cents")
    session = fx.book_session(api, world["plan"]["id"], world["talent"]["id"],
                              world["booth"]["id"], world["contract"]["id"],
                              start_utc="2026-09-10T09:00:00Z",
                              end_utc="2026-09-10T11:00:00Z",
                              planned_line_count=100)
    assert session["status"] == "SCHEDULED"
    A.assert_whole_minutes(session["duration_minutes"], 120, "duration_minutes")
    A.assert_instant_equals(session["occupied_end_utc"], "2026-09-10T11:30:00Z",
                            "occupied_end_utc")
    A.assert_whole_minutes(fx.read_booth(api, world["booth"]["id"])
                           ["reserved_minutes_total"], 150, "reserved_minutes_total")
    A.assert_money_cents(fx.read_plan(api, world["plan"]["id"])
                         ["localization_cost_cents"], 756, "localization_cost_cents")
    fx.set_clock(api, session["start_utc"])
    agent = users.make_talent_agent_headers(world["talent"]["id"])

    started = validate_success(api.start_voice_session(session["id"], agent))

    assert started["status"] == "IN_PROGRESS"
    A.assert_money_cents(started["line_fee_cents"], 0, "line_fee_cents")
    plan = fx.read_plan(api, world["plan"]["id"])
    A.assert_money_cents(plan["localization_cost_cents"], 756,
                         "localization_cost_cents")
    assert plan["voice_recorded_line_count"] == 0
    A.assert_money_cents(fx.read_contract(api, world["contract"]["id"])
                         ["committed_fee_cents"], 500000, "committed_fee_cents")
    A.assert_whole_minutes(fx.read_booth(api, world["booth"]["id"])
                           ["reserved_minutes_total"], 150, "reserved_minutes_total")


def test_only_the_recorded_transition_moves_the_cost_and_the_ledger(api):
    """Completing 100 lines at 250 cents adds 25,000 to both figures.

    "Completion stores `recorded_line_count`, sets `line_fee_cents` to
    `recorded_line_count` multiplied by the contract's `per_line_rate_cents`,
    recomputes the contract's `committed_fee_cents`, recomputes the market plan's
    `voice_recorded_line_count` together with its `localization_cost_cents` and
    `overage_cents`, and increments the `version` of the session, the contract
    and the market plan by 1 each."

    "A contract's `committed_fee_cents` is its `buyout_fee_cents` plus the sum,
    over every recording session booked against this contract whose `status` is
    `RECORDED`, of that session's `recorded_line_count` multiplied by the
    contract's `per_line_rate_cents`."

    The line fee is 100 x 250 = 25,000 cents, so the plan's cost becomes
    756 + 25,000 = 25,756 and the commitment becomes 500,000 + 25,000 = 525,000.
    The booth's reservation is unchanged at 150 minutes, because reservation is
    by booking while cost is by recording.

    Design: Corner/calculations/localization_cost_counts_only_recorded_voice_sessions
    """
    world = _jp_voiced_market_with_one_menu_key(api)
    session = fx.book_session(api, world["plan"]["id"], world["talent"]["id"],
                              world["booth"]["id"], world["contract"]["id"],
                              start_utc="2026-09-10T09:00:00Z",
                              end_utc="2026-09-10T11:00:00Z",
                              planned_line_count=100)

    recorded = fx.record_session_at_its_start(api, session, world["talent"]["id"], 100)

    assert recorded["status"] == "RECORDED"
    assert recorded["recorded_line_count"] == 100
    A.assert_money_cents(recorded["line_fee_cents"], 25000, "line_fee_cents")
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["voice_recorded_line_count"] == 100
    A.assert_money_cents(plan["localization_cost_cents"], 25756,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")
    A.assert_effort_units(plan["text_effort_units"], 0.10)
    A.assert_money_cents(fx.read_contract(api, world["contract"]["id"])
                         ["committed_fee_cents"], 525000, "committed_fee_cents")
    A.assert_whole_minutes(fx.read_booth(api, world["booth"]["id"])
                           ["reserved_minutes_total"], 150, "reserved_minutes_total")


def _functional_pass_with_one_defect_of_each_severity(api):
    """A FUNCTIONAL pass over 100 units carrying one S1, S2, S3 and S4 defect."""
    world = fx.build_market(api, title_code="NOVA-54", name="Nova Drift 54",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    world["qa_pass"] = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 100)
    world["s1"] = fx.log_bug(api, world["qa_pass"]["id"],
                             bug_class="FUNCTIONAL_CRASH", severity="S1",
                             summary="Hard lock when the save file is reloaded.")
    world["s2"] = fx.log_bug(api, world["qa_pass"]["id"],
                             bug_class="FUNCTIONAL_CRASH", severity="S2",
                             summary="Crash when the language is switched twice.")
    world["s3"] = fx.log_bug(api, world["qa_pass"]["id"],
                             bug_class="FUNCTIONAL_CRASH", severity="S3",
                             summary="Crash when the language is switched twice again.")
    world["s4"] = fx.log_bug(api, world["qa_pass"]["id"],
                             bug_class="FUNCTIONAL_CRASH", severity="S4",
                             summary="Audio pop on the pause menu.")
    return world


def test_every_freshly_logged_defect_is_inside_the_open_set(api):
    """Four defects, one per severity, weigh 15 points over 100 units.

    "Severity carries weight: `S1` weighs 8 points, `S2` weighs 4, `S3` weighs 2
    and `S4` weighs 1."

    "A pass's `weighted_defect_points` is the sum of the severity weights of
    every defect filed under that pass whose `status` is `NEW`, `TRIAGED` or
    `FIX_SUBMITTED` — the *open set*."

    Every defect is still `NEW`, so the points are 8 + 4 + 2 + 1 = 15 and the
    density is 15 / 100 = 0.1500, three times the 0.0500 ceiling, so the close is
    refused and the pass stays `OPEN`.

    Design: Corner/calculations/defect_density_open_set_excludes_verified_rejected_and_duplicate_bugs
    """
    world = _functional_pass_with_one_defect_of_each_severity(api)
    opened = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert opened["weighted_defect_points"] == 15
    A.assert_defect_density(opened["defect_density"], 0.1500)
    assert [world[key]["severity_weight"] for key in ("s1", "s2", "s3", "s4")] == \
        [8, 4, 2, 1]
    assert all(world[key]["status"] == "NEW" for key in ("s1", "s2", "s3", "s4"))

    response = api.close_qa_pass(world["qa_pass"]["id"], users.LQA_CLOSER)

    validate_error(response, E.ERR_DEFECT_DENSITY_EXCEEDED, expected_status=422)
    after = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert after["status"] == "OPEN"
    assert after["closed_at_utc"] is None
    A.assert_defect_density(after["defect_density"], 0.1500)


def test_rejected_and_duplicate_defects_leave_the_set_while_a_claimed_fix_stays(api):
    """Removing the S2 and the S3 drops 15 points to 9, and a claimed fix holds.

    "Defects in `VERIFIED`, `REJECTED` or `DUPLICATE` are excluded, which is why
    rejecting a defect at triage, resolving it as a duplicate, or verifying its
    fix all lower the density."

    "The pass's density is recomputed but does not change, because
    `FIX_SUBMITTED` is still inside the open set."

    Rejecting the 4-point S2 and marking the 2-point S3 a duplicate of the S1
    leaves the S1 and the S4 in the set for 8 + 1 = 9 points and a density of
    0.0900. Accepting the S4 and claiming its fix moves it `NEW → TRIAGED →
    FIX_SUBMITTED` without moving the arithmetic at all, so 0.0900 is still above
    the ceiling and the close is still refused.

    Design: Corner/calculations/defect_density_open_set_excludes_verified_rejected_and_duplicate_bugs
    """
    world = _functional_pass_with_one_defect_of_each_severity(api)

    rejected = fx.triage_bug(api, world["s2"]["id"], "REJECT")
    duplicate = fx.triage_bug(api, world["s3"]["id"], "DUPLICATE",
                              duplicate_of_bug_id=world["s1"]["id"])
    fx.triage_bug(api, world["s4"]["id"], "ACCEPT")
    claimed = fx.submit_fix(api, world["s4"]["id"])

    assert rejected["status"] == "REJECTED"
    assert duplicate["status"] == "DUPLICATE"
    assert duplicate["duplicate_of_bug_id"] == world["s1"]["id"]
    assert claimed["status"] == "FIX_SUBMITTED"
    reread = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert reread["weighted_defect_points"] == 9
    A.assert_defect_density(reread["defect_density"], 0.0900)
    assert A.weighted_points(["S1", "S4"]) == 9

    response = api.close_qa_pass(world["qa_pass"]["id"], users.LQA_CLOSER)

    validate_error(response, E.ERR_DEFECT_DENSITY_EXCEEDED, expected_status=422)
    assert fx.read_qa_pass(api, world["qa_pass"]["id"])["status"] == "OPEN"


def test_verifying_the_remaining_fixes_empties_the_set_and_closes_the_pass(api):
    """The last two verifications take 9 points to 0 and the gate opens.

    "On success `verified_by_user_id` is set to the acting `X-User-ID`, the pass's
    `weighted_defect_points` and `defect_density` are recomputed and drop because
    the defect leaves the open set, the linked unit's `open_bug_count` is
    recomputed, and the defect's `version` increments by 1."

    "On success `status` becomes `CLOSED`, `closed_at_utc` is stamped with the
    logical clock, `weighted_defect_points` and `defect_density` are frozen at the
    values that passed the gate, and the pass's `version` increments by 1."

    Verifying the S4 takes the 9 points to 8 and the density to 0.0800, and
    resolving the S1 empties the open set for 0 points and 0.0000, which is
    strictly below the ceiling, so the pass closes with the clock's startup
    instant.

    Design: Corner/calculations/defect_density_open_set_excludes_verified_rejected_and_duplicate_bugs
    """
    world = _functional_pass_with_one_defect_of_each_severity(api)
    fx.triage_bug(api, world["s2"]["id"], "REJECT")
    fx.triage_bug(api, world["s3"]["id"], "DUPLICATE",
                  duplicate_of_bug_id=world["s1"]["id"])
    fx.triage_bug(api, world["s4"]["id"], "ACCEPT")
    fx.submit_fix(api, world["s4"]["id"])

    verified = fx.verify_bug(api, world["s4"]["id"])
    mid = fx.read_qa_pass(api, world["qa_pass"]["id"])
    fx.resolve_bug(api, world["s1"]["id"])

    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] is not None
    assert mid["weighted_defect_points"] == 8
    A.assert_defect_density(mid["defect_density"], 0.0800)
    emptied = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert emptied["weighted_defect_points"] == 0
    A.assert_defect_density(emptied["defect_density"], 0.0000)

    closed = validate_success(
        api.close_qa_pass(world["qa_pass"]["id"], users.LQA_CLOSER)
    )

    assert closed["status"] == "CLOSED"
    assert closed["weighted_defect_points"] == 0
    A.assert_defect_density(closed["defect_density"], 0.0000)
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")


def _jp_market_at_lqa(api, title_code, name):
    return fx.build_market(api, title_code=title_code, name=name,
                           market_code="JP", scope_tier="TEXT_ONLY",
                           target_rating="TEEN_12", budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)


def test_a_repeating_density_is_truncated_to_four_places_by_rounding_up(api):
    """Two points over three units is 0.6667, not 0.6666 and not 0.67.

    "`defect_density` is `weighted_defect_points` divided by the pass's
    `inspected_unit_count`, rounded half up to four decimal places."

    "Defect density is rounded half up to four decimal places."

    A single `S3` defect weighs 2 points, and 2 divided by 3 is 0.66666…, whose
    fifth decimal digit is 6, so the four-place figure is 0.6667. That is far
    above the 0.0500 ceiling, so the close is refused.

    Design: Corner/calculations/defect_density_rounds_to_four_decimals_half_up
    """
    world = _jp_market_at_lqa(api, "NOVA-55", "Nova Drift 55")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 3)
    A.assert_defect_density(qa_pass["defect_density"], 0.0000)
    fx.log_bug(api, qa_pass["id"], bug_class="FUNCTIONAL_CRASH", severity="S3",
               summary="Options menu flickers on the third open.")
    dense = fx.read_qa_pass(api, qa_pass["id"])
    assert dense["weighted_defect_points"] == 2
    A.assert_defect_density(dense["defect_density"], 0.6667)
    assert round(float(dense["defect_density"]), 4) != 0.6666

    response = api.close_qa_pass(qa_pass["id"], users.LQA_CLOSER)

    validate_error(response, E.ERR_DEFECT_DENSITY_EXCEEDED, expected_status=422)
    assert fx.read_qa_pass(api, qa_pass["id"])["status"] == "OPEN"


def test_an_exact_half_at_the_fifth_decimal_rounds_up_and_still_clears(api):
    """One point over twenty thousand units is exactly 0.00005 and shows as 0.0001.

    "`defect_density` is `weighted_defect_points` divided by the pass's
    `inspected_unit_count`, rounded half up to four decimal places."

    "The market plan must be in `IN_LOCALIZATION` or `LQA`, else
    `ERR_PREREQUISITE_STATE_NOT_MET`, and the plan may hold at most one `OPEN`
    pass of the requested `pass_type` at a time, else `ERR_OPEN_QA_PASS_EXISTS`."

    One `S4` defect weighs 1 point, and 1 divided by 20,000 is exactly 0.00005 —
    a dead tie at the fifth decimal — so rounding half up publishes 0.0001 rather
    than 0.0000. The figure is still strictly below the 0.0500 ceiling, so the
    pass closes, and the second pass may be open at the same time because it
    carries the other `pass_type`.

    Design: Corner/calculations/defect_density_rounds_to_four_decimals_half_up
    """
    world = _jp_market_at_lqa(api, "NOVA-55", "Nova Drift 55")
    functional = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 3)
    linguistic = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 20000)
    assert functional["status"] == "OPEN"
    assert linguistic["status"] == "OPEN"
    fx.log_bug(api, linguistic["id"], bug_class="MISTRANSLATION", severity="S4",
               summary="Trailing full stop missing from one tooltip.")
    tie = fx.read_qa_pass(api, linguistic["id"])
    assert tie["weighted_defect_points"] == 1
    A.assert_defect_density(tie["defect_density"], 0.0001)
    assert round(float(tie["defect_density"]), 4) != 0.0000

    closed = validate_success(api.close_qa_pass(linguistic["id"], users.LQA_CLOSER))

    assert closed["status"] == "CLOSED"
    A.assert_defect_density(closed["defect_density"], 0.0001)
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")
    assert fx.read_qa_pass(api, functional["id"])["status"] == "OPEN"


def _market_at_lqa(api, title_code, name, market_code, target_rating):
    return fx.build_market(api, title_code=title_code, name=name,
                           market_code=market_code, scope_tier="TEXT_ONLY",
                           target_rating=target_rating,
                           budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)


def test_a_score_of_exactly_forty_is_the_last_teen_twelve_point(api):
    """22 plus 8 plus 10 is 40, the upper end of the TEEN_12 band.

    "Each descriptor carries a weight: `VIOLENCE_REALISTIC` 25,
    `VIOLENCE_STYLIZED` 12, `BLOOD` 15, `SEXUAL_CONTENT` 20, `LANGUAGE_STRONG`
    10, `DRUG_REFERENCE` 14, `GAMBLING_SIM` 18, `LOOTBOX_PAID` 22 and `HORROR`
    8."

    "The score maps to a band as follows: a score of 20 or below is `ALL_AGES`;
    21 through 40 inclusive is `TEEN_12`; 41 through 60 inclusive is
    `MATURE_15`; 61 through 80 inclusive is `MATURE_17`; and 81 or above is
    `ADULTS_ONLY_18`."

    "Review entry records `reviewed_by_user_id`, computes
    `board_adjusted_risk_score` under the `BOARD_ADJUSTED` variant, sets
    `projected_rating_band` to the band that score maps to, and increments the
    submission's `version` by 1."

    `LOOTBOX_PAID` 22 plus `HORROR` 8 plus `LANGUAGE_STRONG` 10 is exactly 40, so
    both variants agree at 40 with no legal defects and no edits, and 40 is still
    `TEEN_12`. `LOOTBOX_PAID` is footage-mandatory, so the package carries two
    assets, and the round-one `CERO` filing 122 days out costs 456,000 cents.

    Design: Corner/calculations/rating_band_edges_at_forty_and_forty_one
    """
    world = _market_at_lqa(api, "NOVA-56", "Nova Drift 56", "JP", "TEEN_12")
    submission = fx.draft_submission(
        api, world["plan"]["id"], ["LOOTBOX_PAID", "HORROR", "LANGUAGE_STRONG"], 2,
        "TEEN_12",
    )
    filed = fx.submit_submission(api, submission["id"])
    assert filed["self_assessed_risk_score"] == 40
    A.assert_money_cents(filed["fee_cents"], 456000, "fee_cents")
    assert filed["projected_rating_band"] is None

    reviewed = validate_success(api.begin_review(submission["id"], users.BOARD))

    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["board_adjusted_risk_score"] == 40
    assert reviewed["projected_rating_band"] == "TEEN_12"
    assert A.base_risk_points(["LOOTBOX_PAID", "HORROR", "LANGUAGE_STRONG"]) == 40
    assert A.band_for_score(40) == "TEEN_12"
    assert reviewed["self_assessed_risk_score"] == 40


def test_a_score_of_forty_one_is_the_first_mature_fifteen_point(api):
    """14 plus 12 plus 15 is 41, one point into the MATURE_15 band.

    "The score maps to a band as follows: a score of 20 or below is `ALL_AGES`;
    21 through 40 inclusive is `TEEN_12`; 41 through 60 inclusive is
    `MATURE_15`; 61 through 80 inclusive is `MATURE_17`; and 81 or above is
    `ADULTS_ONLY_18`."

    "Step three selects a volume discount percentage **keyed on the pre-discount
    subtotal only**: ten per cent when that subtotal is at least 600,000 cents,
    otherwise five per cent when it is at least 400,000 cents, otherwise zero."

    `DRUG_REFERENCE` 14 plus `VIOLENCE_STYLIZED` 12 plus `BLOOD` 15 is 41, one
    point past the `TEEN_12` ceiling, so the projected band is `MATURE_15`. None
    of the three descriptors is footage-mandatory, so a zero footage count is
    accepted, and the `ESRB` round-one subtotal of 320,000 falls below the
    400,000-cent tier threshold, so no discount applies and the fee is 320,000.

    Design: Corner/calculations/rating_band_edges_at_forty_and_forty_one
    """
    world = _market_at_lqa(api, "NOVA-57", "Nova Drift 57", "US", "MATURE_15")
    submission = fx.draft_submission(
        api, world["plan"]["id"], ["DRUG_REFERENCE", "VIOLENCE_STYLIZED", "BLOOD"], 0,
        "MATURE_15",
    )
    filed = fx.submit_submission(api, submission["id"])
    assert filed["self_assessed_risk_score"] == 41
    A.assert_money_cents(filed["fee_cents"], 320000, "fee_cents")
    assert filed["fee_cents"] != 304000

    reviewed = validate_success(api.begin_review(submission["id"], users.BOARD))

    assert reviewed["board_adjusted_risk_score"] == 41
    assert reviewed["projected_rating_band"] == "MATURE_15"
    assert A.base_risk_points(["DRUG_REFERENCE", "VIOLENCE_STYLIZED", "BLOOD"]) == 41
    assert A.band_for_score(41) == "MATURE_15"
    assert A.band_for_score(40) == "TEEN_12"


def test_a_filing_exactly_forty_five_days_out_pays_no_expedite_fee(api):
    """The threshold is strict, so 45 days is not expedited.

    "Step two computes an expedite fee: when the days to release is fewer than
    45, it is thirty per cent of the pre-discount subtotal rounded half up to
    whole cents, and otherwise it is zero."

    "The number of days to release is the difference between the title's
    `target_release_utc` and the logical clock at filing time, expressed in whole
    days and rounded down; the title is reached through the market plan's
    `title_id`."

    From 2026-10-17T00:00:00Z to the 2026-12-01T00:00:00Z release is exactly 45
    whole days, which is not fewer than 45, so the `CERO` round-one subtotal of
    480,000 takes no expedite fee, a five per cent tier and a 24,000-cent
    discount, for a fee of 456,000. The gate stays `OPEN` because no market is
    ready yet and the release is still more than 30 days away.

    Design: Corner/calculations/expedite_fee_threshold_at_forty_five_versus_forty_four_days
    """
    world = _market_at_lqa(api, "NOVA-58", "Nova Drift 58", "JP", "TEEN_12")
    A.assert_instant_equals(world["title"]["target_release_utc"],
                            C.DEFAULT_TARGET_RELEASE_UTC, "target_release_utc")
    fx.set_clock(api, "2026-10-17T00:00:00Z")
    submission = fx.draft_submission(api, world["plan"]["id"],
                                     ["VIOLENCE_STYLIZED"], 0, "TEEN_12")

    filed = validate_success(
        api.submit_rating_submission(submission["id"], users.COMPLIANCE)
    )

    assert filed["status"] == "SUBMITTED"
    assert filed["submission_round"] == 1
    A.assert_money_cents(filed["fee_cents"], 456000, "fee_cents")
    assert filed["fee_cents"] != 600000
    assert filed["self_assessed_risk_score"] == 12
    A.assert_instant_equals(filed["submitted_at_utc"], "2026-10-17T00:00:00Z",
                            "submitted_at_utc")
    assert fx.read_title(api, world["title"]["id"])["release_gate_state"] == "OPEN"


def test_one_day_closer_than_the_threshold_adds_the_thirty_per_cent_expedite(api):
    """At 44 days the same filing costs 600,000 cents.

    "Step two computes an expedite fee: when the days to release is fewer than
    45, it is thirty per cent of the pre-discount subtotal rounded half up to
    whole cents, and otherwise it is zero."

    "Step five sets `fee_cents` to the pre-discount subtotal plus the expedite fee
    minus the volume discount."

    From 2026-10-18T00:00:00Z the release is 44 whole days away, which is fewer
    than 45, so the expedite fee is thirty per cent of 480,000, that is 144,000.
    The tier is still read off the 480,000 pre-discount subtotal, so the discount
    is 24,000 and the fee is 480,000 + 144,000 - 24,000 = 600,000 — exactly
    144,000 more than the same filing one day earlier.

    Design: Corner/calculations/expedite_fee_threshold_at_forty_five_versus_forty_four_days
    """
    world = _market_at_lqa(api, "NOVA-58", "Nova Drift 58", "JP", "TEEN_12")
    fx.set_clock(api, "2026-10-18T00:00:00Z")
    submission = fx.draft_submission(api, world["plan"]["id"],
                                     ["VIOLENCE_STYLIZED"], 0, "TEEN_12")

    filed = validate_success(
        api.submit_rating_submission(submission["id"], users.COMPLIANCE)
    )

    A.assert_money_cents(filed["fee_cents"], 600000, "fee_cents")
    assert filed["fee_cents"] - 456000 == 144000
    A.assert_instant_equals(filed["submitted_at_utc"], "2026-10-18T00:00:00Z",
                            "submitted_at_utc")


def _jp_booth_with_a_morning_session(api):
    """A JP FULL_VOICE market whose booth already holds 09:00-to-11:00."""
    world = fx.build_market(api, title_code="NOVA-59", name="Nova Drift 59",
                            market_code="JP", scope_tier="FULL_VOICE",
                            target_rating="TEEN_12", budget_cap_cents=9000000,
                            required_voice_line_count=100,
                            key_specs=[f.MENU_KEY_SPEC],
                            booth_code="TOK-F", turnaround_buffer_minutes=30,
                            talent_name="Miki Sato", talent_language_code="JA",
                            max_daily_recording_minutes=240,
                            buyout_fee_cents=500000, per_line_rate_cents=250,
                            territory_scope=["JP"],
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["first"] = fx.book_session(api, world["plan"]["id"], world["talent"]["id"],
                                     world["booth"]["id"], world["contract"]["id"],
                                     start_utc="2026-09-10T09:00:00Z",
                                     end_utc="2026-09-10T11:00:00Z",
                                     planned_line_count=60)
    return world


def _second_booking(world, start_utc, end_utc, planned_line_count):
    return f.voice_session_payload(
        world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc=start_utc, end_utc=end_utc,
        planned_line_count=planned_line_count,
    )


def test_two_adjacent_bookings_each_carry_their_own_buffer_into_the_total(api):
    """150 plus 90 is 240 reserved minutes over two touching intervals.

    "Because both intervals are half-open, a session starting exactly at an
    existing session's `occupied_end_utc` is accepted, while one starting a single
    minute earlier is rejected."

    "A booth's `reserved_minutes_total` is the sum, over every session on that
    booth whose `status` is `SCHEDULED`, `IN_PROGRESS` or `RECORDED`, of that
    session's `duration_minutes` plus the booth's `turnaround_buffer_minutes`."

    The 09:00-to-11:00 session occupies the booth up to but not including 11:30,
    so a session starting exactly at 11:30 is accepted. The booth then holds
    120 + 30 = 150 minutes for the first booking and 60 + 30 = 90 for the second,
    a total of 240 — the buffer is charged once per session, so the 180 minutes of
    bare duration is not the answer.

    Design: Corner/calculations/disjoint_booth_intervals_are_summed_and_adjacent_ones_accepted
    """
    world = _jp_booth_with_a_morning_session(api)
    A.assert_instant_equals(world["first"]["occupied_end_utc"],
                            "2026-09-10T11:30:00Z", "occupied_end_utc")
    A.assert_whole_minutes(fx.read_booth(api, world["booth"]["id"])
                           ["reserved_minutes_total"], 150, "reserved_minutes_total")

    second = validate_success(
        api.create_voice_session(
            _second_booking(world, "2026-09-10T11:30:00Z", "2026-09-10T12:30:00Z", 40),
            users.PRODUCER,
        ),
        expected_status=201,
    )

    assert second["status"] == "SCHEDULED"
    A.assert_whole_minutes(second["duration_minutes"], 60, "duration_minutes")
    A.assert_instant_equals(second["occupied_end_utc"], "2026-09-10T13:00:00Z",
                            "occupied_end_utc")
    booth = fx.read_booth(api, world["booth"]["id"])
    A.assert_whole_minutes(booth["reserved_minutes_total"], 240,
                           "reserved_minutes_total")
    assert booth["reserved_minutes_total"] == 150 + 90
    assert booth["reserved_minutes_total"] != 180


def test_the_talent_day_sums_bare_durations_while_the_booth_sums_buffered_ones(api):
    """The same two bookings are 180 talent minutes and 240 booth minutes.

    "A talent's reserved minutes on a given UTC calendar date is the sum of
    `duration_minutes` over every session for that talent whose `status` is
    `SCHEDULED`, `IN_PROGRESS` or `RECORDED` and whose `start_utc` falls on that
    date; `CANCELLED` sessions are excluded."

    "Reading a talent exposes `reserved_minutes_on_clock_date`, which is that
    aggregate evaluated for the logical clock's current UTC date."

    The talent day is 120 + 60 = 180 minutes with no buffer, exactly 60 minutes
    short of the 240-minute daily cap, while the booth carries 240 because each
    booking pays its own teardown gap. With the clock still on 2026-08-01 the
    talent's figure is 0, because no session starts on that date. Neither booking
    is `RECORDED`, so the plan's cost stays at its 756-cent text component.

    Design: Corner/calculations/disjoint_booth_intervals_are_summed_and_adjacent_ones_accepted
    """
    world = _jp_booth_with_a_morning_session(api)
    validate_success(
        api.create_voice_session(
            _second_booking(world, "2026-09-10T11:30:00Z", "2026-09-10T12:30:00Z", 40),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    before = fx.read_talent(api, world["talent"]["id"])
    A.assert_whole_minutes(before["reserved_minutes_on_clock_date"], 0,
                           "reserved_minutes_on_clock_date")

    fx.set_clock(api, "2026-09-10T08:00:00Z")

    talent = fx.read_talent(api, world["talent"]["id"])
    A.assert_whole_minutes(talent["reserved_minutes_on_clock_date"], 180,
                           "reserved_minutes_on_clock_date")
    assert talent["reserved_minutes_on_clock_date"] == 120 + 60
    assert talent["max_daily_recording_minutes"] == 240
    A.assert_whole_minutes(fx.read_booth(api, world["booth"]["id"])
                           ["reserved_minutes_total"], 240, "reserved_minutes_total")
    plan = fx.read_plan(api, world["plan"]["id"])
    A.assert_money_cents(plan["localization_cost_cents"], 756,
                         "localization_cost_cents")
    assert plan["voice_recorded_line_count"] == 0


def _title_with_two_markets_one_driven_to_lqa(api, release_mode):
    """Two market plans created before the string lock, only JP taken to LQA."""
    title = fx.create_title(api, title_code="NOVA-60", name="Nova Drift 60",
                            release_mode=release_mode)
    key = fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC)
    keys = {key["key_name"]: key}
    japan = fx.create_market_plan(api, title["id"], market_code="JP",
                                  scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                                  budget_cap_cents=5000000)
    germany = fx.create_market_plan(api, title["id"], market_code="DE",
                                    scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                                    budget_cap_cents=5000000)
    fx.lock_strings(api, title["id"])
    fx.scope_plan(api, japan["id"])
    fx.start_localization(api, japan["id"])
    fx.deliver_all_units(api, japan["id"], keys)
    fx.enter_lqa(api, japan["id"])
    return {"title": title, "keys": keys, "japan": japan, "germany": germany}


def _drive_to_release_ready(api, market_plan_id):
    """Rate the package, close a LINGUISTIC pass and declare the market ready."""
    submission = fx.draft_submission(
        api, market_plan_id, ["VIOLENCE_STYLIZED", "HORROR", "LANGUAGE_STRONG"], 0,
        "TEEN_12",
    )
    fx.rate_submission(api, submission["id"])
    fx.open_and_close_linguistic_pass(api, market_plan_id)
    return validate_success(api.mark_release_ready(market_plan_id, users.COMPLIANCE))


def test_a_simultaneous_title_with_one_market_of_two_ready_is_at_risk(api):
    """Clause three fires on partial readiness, 122 days from release.

    "Otherwise, if the title's `release_mode` is `SIMULTANEOUS` and the ready
    count is at least 1 and strictly less than the total count, the posture is
    `AT_RISK` — a simultaneous-release title with some markets ready and some not
    is, by definition, at risk."

    "Otherwise, if the total count is at least 1, the ready count is less than the
    total count, and the number of days to release is fewer than 30, the posture
    is `AT_RISK`."

    The Japanese market reaches `RELEASE_READY` while the German one is still in
    `DRAFT`, so the ready count is 1 against a total of 2. The clock is still at
    its 2026-08-01 startup value, 122 days from the 2026-12-01 release, so the
    30-day clause cannot be what fires: the posture is `AT_RISK` purely because
    the release mode is `SIMULTANEOUS`. The title also stays in `STRINGS_LOCKED`,
    because a bubble to `CERT_WINDOW` needs every plan in `LQA` or
    `RELEASE_READY`.

    Design: Corner/calculations/simultaneous_release_mode_puts_a_partially_ready_title_at_risk
    """
    world = _title_with_two_markets_one_driven_to_lqa(api, "SIMULTANEOUS")
    assert world["title"]["release_mode"] == "SIMULTANEOUS"
    assert C.DEFAULT_DAYS_TO_RELEASE == 122

    ready = _drive_to_release_ready(api, world["japan"]["id"])

    assert ready["status"] == "RELEASE_READY"
    assert fx.read_plan(api, world["germany"]["id"])["status"] == "DRAFT"
    title = fx.read_title(api, world["title"]["id"])
    assert title["market_plan_count"] == 2
    assert title["ready_market_count"] == 1
    assert title["release_gate_state"] == "AT_RISK"
    assert title["localization_state"] == "STRINGS_LOCKED"


def test_the_same_partial_readiness_staggered_leaves_the_gate_open(api):
    """Only the simultaneous mode reads partial readiness as a risk.

    "Otherwise, if the title's `release_mode` is `SIMULTANEOUS` and the ready
    count is at least 1 and strictly less than the total count, the posture is
    `AT_RISK` — a simultaneous-release title with some markets ready and some not
    is, by definition, at risk."

    "Otherwise the posture is `OPEN`."

    The identical population — one of two markets ready, 122 days from release,
    nothing blocked — resolves to `OPEN` on a `STAGGERED` title, because clause
    two needs the ready count to equal the total, clause three needs
    `SIMULTANEOUS` and clause four needs fewer than 30 days.

    Design: Corner/calculations/simultaneous_release_mode_puts_a_partially_ready_title_at_risk
    """
    world = _title_with_two_markets_one_driven_to_lqa(api, "STAGGERED")
    assert world["title"]["release_mode"] == "STAGGERED"

    ready = _drive_to_release_ready(api, world["japan"]["id"])

    assert ready["status"] == "RELEASE_READY"
    title = fx.read_title(api, world["title"]["id"])
    assert title["market_plan_count"] == 2
    assert title["ready_market_count"] == 1
    assert title["release_gate_state"] == "OPEN"
