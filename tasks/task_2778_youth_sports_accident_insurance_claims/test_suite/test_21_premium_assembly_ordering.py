"""Premium assembly: per-band rounding and the pinned annual build-up order.

The underwriting desk's quote is the only place a league sees the price before it
commits, so the arithmetic that produces it is pinned down to the cent: each
volume band is rounded on its own before the three lines are added, and the
volume credit rate is looked up from the subtotal that already carries the
catastrophic layer charge.
"""
from test_helpers import (
    assert_league_policy,
    create_league,
    create_league_policy_payload,
    create_sport_classification,
    make_program_admin_headers,
    validate_success,
)


def test_moderate_hazard_quote_at_404_athletes_sums_three_separately_rounded_band_lines(api):
    """PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.2: "Concretely, the first band's head count is the declared count capped at 75; the second band's head count is the declared count capped at 400 with 75 subtracted, and is zero if that subtraction would go negative; the third band's head count is the declared count with 400 subtracted, and is likewise zero if that would go negative."
    PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "The hazard load is folded into each band line before that line is rounded; it is never applied to a summed total."
    PRD §3.2: "`gross_premium_cents` is then the plain sum of the three already-rounded band lines."
    PRD §3.2: "This ordering is pinned and consequential: an implementation that adds the three unrounded band amounts and rounds once at the end will differ from the specification by a cent or two on many head counts, and that answer is wrong."

    Design: Difficulty/combinatorial_formula/gross_premium_round_per_band_then_sum_not_sum_then_round
    """
    league = create_league(
        name="Riverside Youth Baseball",
        league_code="RYB-003",
        state_code="OH",
        governing_body_code="USYSA",
        contact_email="admin@ryb.example",
    )
    sport = create_sport_classification("baseball")
    assert sport["hazard_load_bps"] == 1150, (
        "a CLASS_2_MODERATE sport carries a hazard load of 1150 basis points, got "
        f"{sport['hazard_load_bps']}"
    )

    policy = validate_success(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2027-03-01",
                enrolled_participant_count=404,
                coverage_basis_election="EXCESS_ONLY",
                cat_layer_elected=True,
            ),
            make_program_admin_headers(),
        ),
        201,
    )
    assert_league_policy(policy)

    # 75 athletes at 1.0000, 325 at 0.9250 and 4 at 0.8500, each band line loaded
    # by 1150 basis points and rounded on its own: 154706 + 620114 + 7013.
    assert policy["gross_premium_cents"] == 781833, (
        "gross_premium_cents must be the sum of the three already-rounded band "
        f"lines, got {policy['gross_premium_cents']}"
    )
    assert policy["gross_premium_cents"] != 781834, (
        "781834 is the answer produced by summing the three unrounded band "
        "amounts and rounding once at the end, which the program forbids"
    )


def test_quote_at_404_athletes_carries_the_rounded_gross_through_to_the_annual_premium(api):
    """PRD §2.5: "Wherever a calculation in §3 produces a non-integral number of cents or basis points, the result is rounded **half up** to the nearest whole unit at exactly the point the calculation names — never earlier and never later."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.2: "A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data."

    Design: Difficulty/combinatorial_formula/gross_premium_round_per_band_then_sum_not_sum_then_round
    """
    league = create_league(
        name="Riverside Youth Baseball",
        league_code="RYB-003",
        state_code="OH",
        governing_body_code="USYSA",
        contact_email="admin@ryb.example",
    )
    sport = create_sport_classification("baseball")

    policy = validate_success(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2027-03-01",
                enrolled_participant_count=404,
                coverage_basis_election="EXCESS_ONLY",
                cat_layer_elected=True,
            ),
            make_program_admin_headers(),
        ),
        201,
    )

    assert policy["gross_premium_cents"] == 781833
    # 781833 * 850 / 10000 = 66455.805, rounded half up.
    assert policy["cat_layer_charge_cents"] == 66456, (
        "the elected catastrophic layer charge is 850 basis points of the gross "
        f"premium rounded half up, got {policy['cat_layer_charge_cents']}"
    )
    assert policy["premium_subtotal_cents"] == 848289, (
        "premium_subtotal_cents is the gross premium plus the catastrophic layer "
        f"charge, got {policy['premium_subtotal_cents']}"
    )
    assert policy["volume_credit_bps"] == 300, (
        "a subtotal of 848289 cents sits in the 500,000-through-1,499,999 band and "
        f"earns 300 basis points, got {policy['volume_credit_bps']}"
    )
    # 848289 * 300 / 10000 = 25448.67, rounded half up.
    assert policy["volume_credit_cents"] == 25449, (
        "volume_credit_cents is the subtotal times the credit rate rounded half "
        f"up, got {policy['volume_credit_cents']}"
    )
    assert policy["annual_premium_cents"] == 822840, (
        "annual_premium_cents is the subtotal less the volume credit, well above "
        f"the 25,000-cent floor, got {policy['annual_premium_cents']}"
    )
    assert policy["status"] == "QUOTED", (
        f"a newly quoted term takes status QUOTED, got {policy['status']}"
    )


def test_electing_the_cat_layer_at_800_athletes_lifts_the_volume_credit_rate_to_550_bps(api):
    """PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "If the layer was not elected, the charge is exactly 0."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "`volume_credit_bps` is the credit rate selected **from the subtotal computed in step 2** — never from the gross premium, and never from the final annual premium."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "Keying the credit on the subtotal rather than on the gross premium is a deliberate design decision with a visible effect: because the catastrophic layer charge is inside the subtotal, electing that layer can push a policy into a higher credit tier and change the credit *rate*, not merely the credit amount."

    Design: Difficulty/combinatorial_formula/annual_premium_pinned_order_cat_charge_before_volume_tier
    """
    league = create_league(
        name="Riverside Youth Baseball",
        league_code="RYB-004",
        state_code="OH",
        governing_body_code="USYSA",
        contact_email="admin@ryb.example",
    )
    sport = create_sport_classification("baseball")
    admin = make_program_admin_headers()

    with_cat = validate_success(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2027-03-01",
                enrolled_participant_count=800,
                coverage_basis_election="EXCESS_ONLY",
                cat_layer_elected=True,
            ),
            admin,
        ),
        201,
    )
    without_cat = validate_success(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2027-03-01",
                enrolled_participant_count=800,
                coverage_basis_election="EXCESS_ONLY",
                cat_layer_elected=False,
            ),
            admin,
        ),
        201,
    )

    # 75 at 1.0000, 325 at 0.9250 and 400 at 0.8500, each band loaded by 1150
    # basis points and rounded on its own: 154706 + 620114 + 701335.
    assert with_cat["gross_premium_cents"] == 1476155, (
        "the banded gross premium at 800 athletes is 1476155 cents, got "
        f"{with_cat['gross_premium_cents']}"
    )
    assert without_cat["gross_premium_cents"] == 1476155, (
        "the catastrophic election does not touch the gross premium, got "
        f"{without_cat['gross_premium_cents']}"
    )

    # 1476155 * 850 / 10000 = 125473.175, rounded half up.
    assert with_cat["cat_layer_charge_cents"] == 125473, (
        f"expected a 125473-cent layer charge, got {with_cat['cat_layer_charge_cents']}"
    )
    assert without_cat["cat_layer_charge_cents"] == 0, (
        "an unelected catastrophic layer is charged exactly 0, got "
        f"{without_cat['cat_layer_charge_cents']}"
    )

    assert with_cat["premium_subtotal_cents"] == 1601628
    assert without_cat["premium_subtotal_cents"] == 1476155

    assert with_cat["volume_credit_bps"] == 550, (
        "a subtotal of 1601628 cents reaches the 1,500,000-through-4,999,999 band "
        f"and earns 550 basis points, got {with_cat['volume_credit_bps']}"
    )
    assert without_cat["volume_credit_bps"] == 300, (
        "without the layer charge the subtotal of 1476155 cents stays in the "
        f"300-basis-point band, got {without_cat['volume_credit_bps']}"
    )


def test_cat_layer_election_at_800_athletes_changes_the_annual_premium_through_the_credit_tier(api):
    """PRD §2.5: "Applying a basis-point figure means multiplying by that figure and dividing by 10000."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.2: "The floor is applied **after** the credit, not before it."
    PRD §3.2: "Keying the credit on the subtotal rather than on the gross premium is a deliberate design decision with a visible effect: because the catastrophic layer charge is inside the subtotal, electing that layer can push a policy into a higher credit tier and change the credit *rate*, not merely the credit amount."

    Design: Difficulty/combinatorial_formula/annual_premium_pinned_order_cat_charge_before_volume_tier
    """
    league = create_league(
        name="Riverside Youth Baseball",
        league_code="RYB-004",
        state_code="OH",
        governing_body_code="USYSA",
        contact_email="admin@ryb.example",
    )
    sport = create_sport_classification("baseball")
    admin = make_program_admin_headers()

    with_cat = validate_success(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2027-03-01",
                enrolled_participant_count=800,
                coverage_basis_election="EXCESS_ONLY",
                cat_layer_elected=True,
            ),
            admin,
        ),
        201,
    )
    without_cat = validate_success(
        api.create_league_policy(
            create_league_policy_payload(
                league["id"],
                sport["id"],
                term_effective_date="2026-03-01",
                term_expiration_date="2027-03-01",
                enrolled_participant_count=800,
                coverage_basis_election="EXCESS_ONLY",
                cat_layer_elected=False,
            ),
            admin,
        ),
        201,
    )

    # 1601628 * 550 / 10000 = 88089.54 and 1476155 * 300 / 10000 = 44284.65,
    # each rounded half up at the point the credit step names.
    assert with_cat["volume_credit_cents"] == 88090, (
        "the credit on the layer-bearing subtotal is 88090 cents, got "
        f"{with_cat['volume_credit_cents']}"
    )
    assert without_cat["volume_credit_cents"] == 44285, (
        "the credit without the layer charge is 44285 cents, got "
        f"{without_cat['volume_credit_cents']}"
    )

    assert with_cat["annual_premium_cents"] == 1513538, (
        "1601628 less an 88090-cent credit is 1513538 cents, got "
        f"{with_cat['annual_premium_cents']}"
    )
    assert without_cat["annual_premium_cents"] == 1431870, (
        "1476155 less a 44285-cent credit is 1431870 cents, got "
        f"{without_cat['annual_premium_cents']}"
    )
    assert with_cat["annual_premium_cents"] - without_cat["annual_premium_cents"] == 81668, (
        "electing the layer costs 81668 cents net of the larger credit it unlocks"
    )
