"""
The background-music exemption ladder and the two arithmetic edges of the annual
licence fee.

Three tests walk the exemption determination: a survey sitting exactly on both
speaker limits, the category-dependent floor-area boundary either side of its
inclusive edge, and the ordering of the clause ladder itself, where a venue that
would fail several clauses is answered by the first one that matches. Two more
tests pin the fee: one extra fixed seat crossing the first occupancy tier's
ceiling re-prices the whole fee rather than the marginal occupant, and the
schedule's minimum annual fee lifts the pre-apportionment amount so that the
society's slice ends up far below that same minimum.
"""

from test_helpers import (
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    CLOCK_START_INSTANT,
    DEFAULT_ADJUSTMENT_BP,
    DEFAULT_MAX_ANNUAL_FEE_CENTS,
    DEFAULT_MIN_ANNUAL_FEE_CENTS,
    EXEMPTION_EXEMPT,
    EXEMPTION_INCONCLUSIVE,
    EXEMPTION_NOT_ANALYZED,
    EXEMPTION_NOT_EXEMPT,
    FLOOR_AREA_LIMIT_DEFAULT_SQ_FT,
    FLOOR_AREA_LIMIT_FOOD_SERVICE_SQ_FT,
    MAX_SPEAKERS_PER_ROOM_LIMIT,
    REASON_COVER_CHARGE_DISQUALIFIES,
    REASON_DATA_INCOMPLETE,
    REASON_LICENSED_SERVICE_PASSTHROUGH,
    REASON_MUSIC_USE_PROFILE_INELIGIBLE,
    REASON_SIZE_LIMIT_EXCEEDED,
    REASON_SPEAKER_LIMIT_EXCEEDED,
    REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS,
    SHARE_BMI_BP,
    SHARE_SESAC_BP,
    SPEAKER_COUNT_LIMIT,
    admin_headers,
    assert_assessment,
    assert_bp,
    assert_count,
    assert_money,
    assert_not_money,
    assert_venue_ledger,
    assert_version_advanced,
    assessments_of_license,
    bgm_survey_fields,
    bmi_payload,
    fitness_studio_venue_payload,
    get_success_data,
    given_active_license,
    given_effective_schedule,
    given_society,
    given_venue,
    sesac_payload,
    venue_payload,
    venue_row,
)

# The PRD names these enum values but ``test_helpers`` exposes no single-value
# constant for each, so they are spelled once here rather than inline.
_CATEGORY_BAR_GRILL = "BAR_GRILL"
_CATEGORY_FITNESS_STUDIO = "FITNESS_STUDIO"
_CATEGORY_HOTEL = "HOTEL"
_CATEGORY_RESTAURANT = "RESTAURANT"

_PROFILE_BACKGROUND_ONLY = "BACKGROUND_ONLY"
_PROFILE_MIXED = "MIXED"

_LICENSE_TYPE_BLANKET = "BLANKET"


def _analyse_exemption(api, venue_id):
    """Run the background-music exemption determination against one venue."""
    return get_success_data(api.run_exemption_analysis(venue_id, admin_headers()))


def _revise_survey(api, venue_id, changes):
    """Revise the verified survey figures of one venue."""
    return get_success_data(api.update_venue(venue_id, changes, admin_headers()))


def test_calc_exemption_within_size_and_speaker_limits_is_exempt(api):
    """A background-only studio sitting exactly on both speaker limits is exempt.

    Six loudspeakers in total and four in the largest room are the boundary
    values themselves, and the limits are breached only by a strictly larger
    figure, so the ladder falls all the way through to the exempt verdict and
    the determination advances the venue's revision counter.

    PRD §3.3: "Otherwise, when `speaker_count` is strictly greater than 6
    loudspeakers in total, or `max_speakers_per_room` is strictly greater than 4
    loudspeakers in any one room, the verdict is `NOT_EXEMPT` with reason
    `SPEAKER_LIMIT_EXCEEDED`."

    PRD §3.3: "When neither limit is breached, the verdict is `EXEMPT` with
    reason `WITHIN_SIZE_AND_SPEAKER_LIMITS`."

    PRD §3.3: "It writes `bgm_exemption_status` — one of `NOT_ANALYZED`,
    `EXEMPT`, `NOT_EXEMPT` or `INCONCLUSIVE` — together with
    `bgm_exemption_reason`, and increments the venue's `version`."

    Design: Corner/calculations/corner_bgm_exemption_exempt_within_size_and_speaker_limits
    """
    created = given_venue(
        api,
        fitness_studio_venue_payload("Pulse Fitness Studio", **bgm_survey_fields()),
    )
    assert created["bgm_exemption_status"] == EXEMPTION_NOT_ANALYZED, (
        "a fresh venue carries no exemption verdict yet"
    )
    assert created["bgm_exemption_reason"] is None, (
        "a fresh venue carries no exemption reason yet"
    )

    analysed = _analyse_exemption(api, created["id"])

    assert analysed["bgm_exemption_status"] == EXEMPTION_EXEMPT, (
        f"expected EXEMPT, got {analysed['bgm_exemption_status']!r}"
    )
    assert analysed["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS, (
        f"expected WITHIN_SIZE_AND_SPEAKER_LIMITS, "
        f"got {analysed['bgm_exemption_reason']!r}"
    )
    assert_version_advanced(analysed, created, 1, "venue")

    # The determination reads the survey; it rewrites none of it.
    assert_count(analysed["gross_square_feet"], 1800, "gross_square_feet")
    assert_count(analysed["speaker_count"], SPEAKER_COUNT_LIMIT, "speaker_count")
    assert_count(
        analysed["max_speakers_per_room"],
        MAX_SPEAKERS_PER_ROOM_LIMIT,
        "max_speakers_per_room",
    )


def test_calc_exemption_size_limit_boundary_differs_by_venue_category(api):
    """The floor-area limit is inclusive and depends on the venue's category.

    A fitness studio is measured against 2000 gross square feet and is inside
    that limit at exactly 2000, outside it at 2001; a bar and grill at the very
    same 2001 square feet is measured against 3750 instead and stays exempt. The
    survey revision in between also discards the earlier verdict.

    PRD §3.3: "The applicable floor-area limit is 3750 gross square feet when
    the venue's `venue_category` is `BAR_GRILL` or `RESTAURANT`, and 2000 gross
    square feet for every other category."

    PRD §3.3: "The boundary is **inclusive**: a `gross_square_feet` figure
    exactly equal to the applicable limit is still within it, and one square
    foot more is not."

    PRD §3.3: "And the exemption verdict is discarded: `bgm_exemption_status`
    returns to `NOT_ANALYZED` and `bgm_exemption_reason` returns to null,
    because a verdict computed against superseded floor-area or speaker data is
    worthless."

    Design: Corner/calculations/corner_bgm_exemption_size_limit_boundary_by_venue_category
    """
    studio = given_venue(
        api,
        fitness_studio_venue_payload(
            "Pulse Fitness Studio",
            **bgm_survey_fields(gross_square_feet=FLOOR_AREA_LIMIT_DEFAULT_SQ_FT),
        ),
    )
    over_the_studio_limit = FLOOR_AREA_LIMIT_DEFAULT_SQ_FT + 1
    grill = given_venue(
        api,
        venue_payload(
            "Corner Tap Bar and Grill",
            _CATEGORY_BAR_GRILL,
            40,
            60,
            90,
            _PROFILE_BACKGROUND_ONLY,
            0,
            0,
            **bgm_survey_fields(gross_square_feet=over_the_studio_limit),
        ),
    )

    at_the_limit = _analyse_exemption(api, studio["id"])
    assert at_the_limit["bgm_exemption_status"] == EXEMPTION_EXEMPT, (
        "exactly 2000 gross square feet is still inside the 2000 limit"
    )
    assert (
        at_the_limit["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    ), "expected WITHIN_SIZE_AND_SPEAKER_LIMITS at the limit itself"

    revised = _revise_survey(
        api, studio["id"], {"gross_square_feet": over_the_studio_limit}
    )
    assert revised["bgm_exemption_status"] == EXEMPTION_NOT_ANALYZED, (
        "revising the surveyed floor area discards the stored verdict"
    )
    assert revised["bgm_exemption_reason"] is None, (
        "revising the surveyed floor area clears the stored reason"
    )

    one_foot_over = _analyse_exemption(api, studio["id"])
    assert one_foot_over["bgm_exemption_status"] == EXEMPTION_NOT_EXEMPT, (
        "2001 gross square feet is one foot outside the 2000 limit"
    )
    assert one_foot_over["bgm_exemption_reason"] == REASON_SIZE_LIMIT_EXCEEDED, (
        f"expected SIZE_LIMIT_EXCEEDED, got {one_foot_over['bgm_exemption_reason']!r}"
    )

    grill_verdict = _analyse_exemption(api, grill["id"])
    assert_count(
        grill_verdict["gross_square_feet"], over_the_studio_limit, "gross_square_feet"
    )
    assert over_the_studio_limit <= FLOOR_AREA_LIMIT_FOOD_SERVICE_SQ_FT, (
        "the food-and-drink limit of 3750 is what leaves 2001 square feet inside it"
    )
    assert grill_verdict["bgm_exemption_status"] == EXEMPTION_EXEMPT, (
        "a bar and grill is measured against 3750 square feet, not 2000"
    )
    assert (
        grill_verdict["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    ), "expected WITHIN_SIZE_AND_SPEAKER_LIMITS for the bar and grill"


def test_calc_exemption_first_matching_clause_wins(api):
    """The exemption clauses are an ordered ladder, not a set of independent tests.

    Five venues each carry a survey that would satisfy more than one clause, and
    each is answered by the topmost matching clause: an ineligible use profile
    outranks a compliant survey, a licensed background-music service outranks an
    oversized room with a cover charge, incomplete survey data outranks the
    cover charge, the cover charge outranks the retransmission clause, and only
    a venue that reaches the bottom rung is judged on its speaker count.

    PRD §3.3: "The clauses below are evaluated strictly from top to bottom and
    **the first one that matches wins**; nothing below a matching clause is
    consulted:"

    PRD §3.3: "Otherwise, when `uses_licensed_bgm_service` is true, the verdict
    is `EXEMPT` with reason `LICENSED_SERVICE_PASSTHROUGH`."

    PRD §3.3: "Otherwise, when any one of `gross_square_feet`, `speaker_count`
    or `max_speakers_per_room` is null, the verdict is `INCONCLUSIVE` with
    reason `DATA_INCOMPLETE`."

    Design: Corner/calculations/corner_bgm_exemption_first_matching_clause_wins
    """
    ineligible_profile = given_venue(
        api,
        venue_payload(
            "Mixed Use Tavern",
            _CATEGORY_BAR_GRILL,
            40,
            60,
            90,
            _PROFILE_MIXED,
            2,
            0,
            **bgm_survey_fields(),
        ),
    )
    licensed_service = given_venue(
        api,
        venue_payload(
            "Atrium Hotel Lobby",
            _CATEGORY_HOTEL,
            0,
            30,
            60,
            _PROFILE_BACKGROUND_ONLY,
            0,
            500000,
            **bgm_survey_fields(
                gross_square_feet=9999,
                speaker_count=40,
                max_speakers_per_room=20,
                has_cover_charge=True,
                retransmission_only=False,
                uses_licensed_bgm_service=True,
                bgm_service_provider="Ambient Feed Co",
            ),
        ),
    )
    # gross_square_feet is simply omitted, so it defaults to null.
    unsurveyed = given_venue(
        api,
        venue_payload(
            "Unsurveyed Diner",
            _CATEGORY_RESTAURANT,
            50,
            10,
            70,
            _PROFILE_BACKGROUND_ONLY,
            0,
            0,
            speaker_count=SPEAKER_COUNT_LIMIT,
            max_speakers_per_room=MAX_SPEAKERS_PER_ROOM_LIMIT,
            has_cover_charge=True,
            retransmission_only=True,
        ),
    )
    cover_charged = given_venue(
        api,
        venue_payload(
            "Cover Charge Cafe",
            _CATEGORY_RESTAURANT,
            50,
            10,
            70,
            _PROFILE_BACKGROUND_ONLY,
            0,
            250000,
            **bgm_survey_fields(has_cover_charge=True, retransmission_only=False),
        ),
    )
    too_many_speakers = given_venue(
        api,
        venue_payload(
            "Seven Speaker Spa",
            _CATEGORY_FITNESS_STUDIO,
            0,
            20,
            30,
            _PROFILE_BACKGROUND_ONLY,
            0,
            0,
            **bgm_survey_fields(speaker_count=SPEAKER_COUNT_LIMIT + 1),
        ),
    )

    expected = [
        (ineligible_profile, EXEMPTION_NOT_EXEMPT, REASON_MUSIC_USE_PROFILE_INELIGIBLE),
        (licensed_service, EXEMPTION_EXEMPT, REASON_LICENSED_SERVICE_PASSTHROUGH),
        (unsurveyed, EXEMPTION_INCONCLUSIVE, REASON_DATA_INCOMPLETE),
        (cover_charged, EXEMPTION_NOT_EXEMPT, REASON_COVER_CHARGE_DISQUALIFIES),
        (too_many_speakers, EXEMPTION_NOT_EXEMPT, REASON_SPEAKER_LIMIT_EXCEEDED),
    ]
    for created, wanted_status, wanted_reason in expected:
        verdict = _analyse_exemption(api, created["id"])
        assert verdict["bgm_exemption_status"] == wanted_status, (
            f"{created['legal_name']}: expected {wanted_status}, "
            f"got {verdict['bgm_exemption_status']!r}"
        )
        assert verdict["bgm_exemption_reason"] == wanted_reason, (
            f"{created['legal_name']}: expected {wanted_reason}, "
            f"got {verdict['bgm_exemption_reason']!r}"
        )

    # The speaker-limit venue is inside the per-room limit and still fails on
    # the total, so the two speaker limits are read independently.
    spa = venue_row(api, too_many_speakers["id"])
    assert_count(spa["speaker_count"], SPEAKER_COUNT_LIMIT + 1, "speaker_count")
    assert_count(
        spa["max_speakers_per_room"],
        MAX_SPEAKERS_PER_ROOM_LIMIT,
        "max_speakers_per_room",
    )


def test_calc_fee_tier_boundary_at_occupancy_100_and_101(api):
    """One extra fixed seat crosses the occupancy tier and re-prices the whole fee.

    Two otherwise identical bars and grills differ only in seating: 100 fixed
    seats sits in the first tier and bills 27600 cents, while 101 seats moves
    into the second tier and bills 47030 cents. The step is the whole difference
    between two tier constants, not a marginal charge for one occupant, so the
    per-occupant interpolation of 27876 cents is ruled out.

    PRD §3.5: "The billable occupancy is the **larger** of the seating figure
    and the standing figure — never their sum."

    PRD §3.5: "That occupancy selects one of four tiers: the first tier for an
    occupancy of at most 100; the second for an occupancy from 101 through 300
    inclusive; the third for an occupancy from 301 through 750 inclusive; and
    the fourth for an occupancy of 751 or more."

    PRD §3.5: "Only now is the society's `repertoire_share_bp` applied: the
    clamped amount is multiplied by `repertoire_share_bp`, divided by 10000, and
    rounded half up to whole cents."

    Design: Corner/calculations/corner_annual_fee_tier_boundary_at_occupancy_100_and_101
    """
    society = given_society(api, bmi_payload())
    assert_bp(society["repertoire_share_bp"], SHARE_BMI_BP, "repertoire_share_bp")
    schedule = given_effective_schedule(api, society["id"], _CATEGORY_BAR_GRILL)
    assert_bp(schedule["adjustment_bp"], DEFAULT_ADJUSTMENT_BP, "adjustment_bp")
    assert_money(
        schedule["min_annual_fee_cents"],
        DEFAULT_MIN_ANNUAL_FEE_CENTS,
        "min_annual_fee_cents",
    )
    assert_money(
        schedule["max_annual_fee_cents"],
        DEFAULT_MAX_ANNUAL_FEE_CENTS,
        "max_annual_fee_cents",
    )

    first_tier_venue = given_venue(
        api,
        venue_payload(
            "Hundred Seat Tap",
            _CATEGORY_BAR_GRILL,
            100,
            0,
            100,
            _PROFILE_MIXED,
            0,
            0,
        ),
    )
    second_tier_venue = given_venue(
        api,
        venue_payload(
            "Hundred One Seat Tap",
            _CATEGORY_BAR_GRILL,
            101,
            0,
            101,
            _PROFILE_MIXED,
            0,
            0,
        ),
    )

    first_tier_license = given_active_license(
        api, first_tier_venue, society["id"], CLOCK_START_INSTANT
    )
    second_tier_license = given_active_license(
        api, second_tier_venue, society["id"], CLOCK_START_INSTANT
    )

    # First tier: base 42000 + 180 * 100 = 18000, no cover revenue, subtotal
    # 60000; the MIXED multiplier of 10000 bp with no live nights leaves it
    # unchanged; 4600 bp of 60000 is 27600.
    assert_money(
        first_tier_license["annual_fee_cents"], 27600, "first-tier annual_fee_cents"
    )
    # Second tier: base 78000 + 240 * 101 = 24240, subtotal 102240, and 4600 bp
    # of 102240 is 47030.40, which rounds half up to 47030.
    assert_money(
        second_tier_license["annual_fee_cents"], 47030, "second-tier annual_fee_cents"
    )
    assert_not_money(
        second_tier_license["annual_fee_cents"],
        27876,
        "second-tier annual_fee_cents",
    )

    for licence in (first_tier_license, second_tier_license):
        assert_money(
            licence["verified_fee_delta_cents"], 0, "verified_fee_delta_cents"
        )

    assert_venue_ledger(venue_row(api, first_tier_venue["id"]), 27600, 0, 0, 27600)
    assert_venue_ledger(venue_row(api, second_tier_venue["id"]), 47030, 0, 0, 47030)


def test_calc_fee_min_clamp_lifts_before_apportionment(api):
    """The minimum annual fee is applied before the society's share is taken.

    A tiny background-only studio scales to 29520 cents, which the schedule's
    30000-cent floor lifts; only then does SESAC's 500-basis-point share reduce
    it to 1500 cents. Neither 30000 cents (a floor applied after apportionment)
    nor 1476 cents (500 basis points of the unclamped amount) is the answer.

    PRD §3.5: "The scaled amount is raised to the schedule's
    `min_annual_fee_cents` if it falls below it, and lowered to the schedule's
    `max_annual_fee_cents` if it rises above it. This clamp acts on the
    **pre-apportionment** figure."

    PRD §3.5: "Note carefully that the fee **may legitimately end up below the
    schedule's `min_annual_fee_cents`** — a society controlling 2000 basis
    points of the repertoire bills a fifth of the clamped amount, and that is
    correct, not a floor violation."

    PRD §3.5: "Those two basis-point figures are **added together first** to
    give a single multiplier, and only then is the multiplier applied: the
    *scaled* amount is the subtotal multiplied by the combined multiplier in
    basis points, divided by 10000, rounded half up to whole cents."

    Design: Corner/calculations/corner_annual_fee_min_clamp_lifts_tiny_venue_before_apportionment
    """
    society = given_society(api, sesac_payload())
    assert_bp(society["repertoire_share_bp"], SHARE_SESAC_BP, "repertoire_share_bp")
    schedule = given_effective_schedule(api, society["id"], _CATEGORY_FITNESS_STUDIO)
    assert_money(
        schedule["min_annual_fee_cents"],
        DEFAULT_MIN_ANNUAL_FEE_CENTS,
        "min_annual_fee_cents",
    )

    studio = given_venue(api, fitness_studio_venue_payload("Pulse Fitness Studio"))
    licence = given_active_license(
        api, studio, society["id"], CLOCK_START_INSTANT
    )

    # Base 42000 + 180 * 40 = 7200 with no cover revenue gives a subtotal of
    # 49200; the BACKGROUND_ONLY multiplier of 6000 bp scales that to 29520; the
    # floor lifts it to 30000; and 500 bp of 30000 is 1500.
    assert_money(licence["annual_fee_cents"], 1500, "annual_fee_cents")
    assert_not_money(
        licence["annual_fee_cents"], DEFAULT_MIN_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )
    assert_not_money(licence["annual_fee_cents"], 1476, "annual_fee_cents")

    # A background-only venue that has not been analysed still needs a blanket
    # licence, so the operator's hint is not what decided the type.
    assert licence["license_type"] == _LICENSE_TYPE_BLANKET, (
        f"expected a BLANKET licence, got {licence['license_type']!r}"
    )

    assert_venue_ledger(venue_row(api, studio["id"]), 1500, 0, 0, 1500)
    initial = assessments_of_license(api, licence["id"])
    assert len(initial) == 1, f"expected one assessment, got {len(initial)}"
    assert_assessment(
        initial[0], ASSESSMENT_KIND_INITIAL, 1500, ASSESSMENT_STATUS_ISSUED, paid=0
    )
