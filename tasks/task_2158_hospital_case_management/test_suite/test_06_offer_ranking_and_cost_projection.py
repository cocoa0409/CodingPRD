"""Cost projection on a bed offer — the two rate variants and the pinned per-day
rounding order — and the advisory rank score that drives the recommendation."""
from test_helpers import (
    CASE_MANAGER,
    assert_bed_offer,
    assert_projection_splits_exactly,
    document_choice_payload,
    get_success_data,
    make_liaison_headers,
    read_referral,
    referral_payload,
    seed_network_contract,
    seed_provider,
    setup_broadcast_referral,
    setup_screened_episode,
    validate_success,
)

MERIDIAN = {
    "name": "Meridian Health", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}


def _offer_body(version, **overrides):
    body = {
        "expected_referral_version": version,
        "bed_unit_code": "UNIT-A",
        "bed_available_from": "2026-08-05T00:00:00Z",
        "hold_expires_at": "2026-08-12T00:00:00Z",
        "daily_rate_cents": 32808,
    }
    body.update(overrides)
    return body


def _thirty_day_search(mrn, contracts=None):
    return setup_broadcast_referral(
        payer=dict(MERIDIAN),
        patient={
            "mrn": mrn, "full_name": "Bo Reyes", "date_of_birth": "1951-07-04",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        referral={"requested_level_of_care": "SNF", "projected_stay_days": 30,
                  "needed_by": "2026-08-20T00:00:00Z"},
        contracts=contracts,
    )


def test_contracted_provider_projects_at_the_negotiated_network_rate(api):
    """PRD §3.5: "The projection first decides which rate variant applies by looking for
    the single network contract joining the episode's patient's `primary_payer_id` to the
    offer's `provider_id`. When such a contract exists and its `in_network` is true,
    `rate_variant_applied` is `NETWORK_RATE` and the raw daily rate is that contract's
    `negotiated_daily_rate_cents`."
    PRD §3.5: "Each covered day is priced separately: the first twenty days are priced at
    the raw daily rate, and every day from the twenty-first onward is priced at eighty-five
    percent of the raw daily rate, rounded half up to whole cents **for that day**."
    PRD §3.5: "From the gross, `projected_patient_share_cents` is the gross multiplied by
    the payer's `coinsurance_pct` and rounded half up to whole cents, and
    `projected_plan_share_cents` is simply the gross less the patient share, so the two
    always add back to the gross exactly."

    Design: Difficulty/dual_variant_calc/placement_cost_network_rate_versus_billed_rate_variant
    """
    env = _thirty_day_search(
        "MRN-2001",
        contracts=[{"index": 0, "in_network": True, "negotiated_daily_rate_cents": 30000}],
    )

    offer = validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(env["referral_version"]),
            make_liaison_headers(env["provider_a"]["id"]),
        ),
        201,
    )

    assert_bed_offer(offer)
    assert offer["rate_variant_applied"] == "NETWORK_RATE"
    assert offer["daily_rate_cents"] == 32808, "the billed rate is stored but not used"
    assert offer["projected_gross_cents"] == 855000, (
        "20 days at 30000 plus 10 days at 25500 == 855000, got "
        f"{offer['projected_gross_cents']}"
    )
    assert offer["projected_patient_share_cents"] == 171000
    assert offer["projected_plan_share_cents"] == 684000
    assert_projection_splits_exactly(offer)


def test_uncontracted_provider_projects_at_the_marked_up_billed_rate(api):
    """PRD §3.5: "When no contract row exists, or the row exists with `in_network` false,
    `rate_variant_applied` is `BILLED_RATE` and the raw daily rate is the offer's
    `daily_rate_cents` increased by a quarter — that is, multiplied by 1.25 and rounded
    half up to whole cents. The same offer therefore projects a materially larger gross,
    patient share and plan share when the facility is out of network."
    PRD §3.5: "From the gross, `projected_patient_share_cents` is the gross multiplied by
    the payer's `coinsurance_pct` and rounded half up to whole cents, and
    `projected_plan_share_cents` is simply the gross less the patient share, so the two
    always add back to the gross exactly."

    Design: Difficulty/dual_variant_calc/placement_cost_network_rate_versus_billed_rate_variant
    """
    env = _thirty_day_search(
        "MRN-2002",
        contracts=[{"index": 0, "in_network": True, "negotiated_daily_rate_cents": 30000}],
    )
    contracted = validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(env["referral_version"]),
            make_liaison_headers(env["provider_a"]["id"]),
        ),
        201,
    )
    version = read_referral(env["referral"]["id"])["version"]

    uncontracted = validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(version),
            make_liaison_headers(env["provider_b"]["id"]),
        ),
        201,
    )

    assert uncontracted["rate_variant_applied"] == "BILLED_RATE"
    assert uncontracted["daily_rate_cents"] == contracted["daily_rate_cents"] == 32808, (
        "the two offers are byte-identical on the billed per-diem"
    )
    assert uncontracted["projected_gross_cents"] == 1168790
    assert uncontracted["projected_patient_share_cents"] == 233758
    assert uncontracted["projected_plan_share_cents"] == 935032
    assert uncontracted["projected_plan_share_cents"] > contracted["projected_plan_share_cents"]
    assert_projection_splits_exactly(uncontracted)


def test_tier_two_days_are_rounded_individually_before_being_summed(api):
    """PRD §3.5: "The gross is tiered by day, and the rounding order is pinned. The
    covered-day count is the referral's `projected_stay_days`. Each covered day is priced
    separately: the first twenty days are priced at the raw daily rate, and every day from
    the twenty-first onward is priced at eighty-five percent of the raw daily rate, rounded
    half up to whole cents **for that day**. Only after every day has been individually
    rounded are the day prices summed into `projected_gross_cents`. Summing first and
    rounding once at the end is a different and incorrect answer."

    Design: Difficulty/combinatorial_formula/per_day_rounding_before_summation_on_tier_two_days
    """
    env = _thirty_day_search("MRN-2101")

    offer = validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(env["referral_version"]),
            make_liaison_headers(env["provider_b"]["id"]),
        ),
        201,
    )

    assert offer["rate_variant_applied"] == "BILLED_RATE"
    assert offer["projected_gross_cents"] == 1168790, (
        "each of the ten tier-2 days rounds to 34859 before summing, got "
        f"{offer['projected_gross_cents']}"
    )
    assert offer["projected_gross_cents"] != 1168785, (
        "1168785 is what summing the unrounded 34858.5 day prices first would yield"
    )
    assert offer["projected_patient_share_cents"] == 233758
    assert offer["projected_plan_share_cents"] == 935032


def test_the_ten_tier_two_days_add_exactly_ten_individually_rounded_prices(api):
    """PRD §3.5: "Each covered day is priced separately: the first twenty days are priced
    at the raw daily rate, and every day from the twenty-first onward is priced at
    eighty-five percent of the raw daily rate, rounded half up to whole cents **for that
    day**. Only after every day has been individually rounded are the day prices summed
    into `projected_gross_cents`. Summing first and rounding once at the end is a different
    and incorrect answer."
    PRD §3.5: "When no contract row exists, or the row exists with `in_network` false,
    `rate_variant_applied` is `BILLED_RATE` and the raw daily rate is the offer's
    `daily_rate_cents` increased by a quarter — that is, multiplied by 1.25 and rounded
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/per_day_rounding_before_summation_on_tier_two_days
    """
    twenty = setup_broadcast_referral(
        payer=dict(MERIDIAN),
        patient={
            "mrn": "MRN-2102", "full_name": "Cy Okafor", "date_of_birth": "1955-01-19",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        referral={"requested_level_of_care": "SNF", "projected_stay_days": 20,
                  "needed_by": "2026-08-20T00:00:00Z"},
    )
    thirty = _thirty_day_search("MRN-2103")

    tier_one_only = validate_success(
        api.create_offer(
            twenty["referral"]["id"],
            _offer_body(twenty["referral_version"]),
            make_liaison_headers(twenty["provider_b"]["id"]),
        ),
        201,
    )
    with_tier_two = validate_success(
        api.create_offer(
            thirty["referral"]["id"],
            _offer_body(thirty["referral_version"]),
            make_liaison_headers(thirty["provider_b"]["id"]),
        ),
        201,
    )

    assert tier_one_only["projected_gross_cents"] == 820200, (
        "twenty days all priced at the raw 41010 daily rate, got "
        f"{tier_one_only['projected_gross_cents']}"
    )
    assert with_tier_two["projected_gross_cents"] == 1168790
    delta = with_tier_two["projected_gross_cents"] - tier_one_only["projected_gross_cents"]
    assert delta == 348590, (
        f"ten tier-2 days at an individually rounded 34859 each, got {delta}"
    )
    assert delta != 348585, "348585 is the summed-then-rounded answer the PRD rules out"


def test_coinsurance_share_rounds_half_up_on_an_exact_half_cent(api):
    """PRD §3.5: "From the gross, `projected_patient_share_cents` is the gross multiplied
    by the payer's `coinsurance_pct` and rounded half up to whole cents, and
    `projected_plan_share_cents` is simply the gross less the patient share, so the two
    always add back to the gross exactly."
    PRD §2.9: "All monetary amounts in this system are integer cents. Wherever a monetary
    computation produces a fraction of a cent, the result is rounded half up to a whole
    cent."

    Design: Corner/calculations/coinsurance_share_rounds_half_up_on_odd_half_cent
    """
    env = setup_broadcast_referral(
        payer={"name": "Quarter Share Plan", "coinsurance_pct": 0.125,
               "snf_auth_required": False, "hh_auth_required": False},
        patient={
            "mrn": "MRN-C303", "full_name": "Ned Oyola", "date_of_birth": "1947-03-30",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        referral={"requested_level_of_care": "SNF", "projected_stay_days": 30,
                  "needed_by": "2026-08-20T00:00:00Z"},
    )

    offer = validate_success(
        api.create_offer(
            env["referral"]["id"],
            _offer_body(env["referral_version"]),
            make_liaison_headers(env["provider_b"]["id"]),
        ),
        201,
    )

    assert offer["projected_gross_cents"] == 1168790
    assert offer["projected_patient_share_cents"] == 146099, (
        "an exact 146098.75 rounds half up to 146099, got "
        f"{offer['projected_patient_share_cents']}"
    )
    assert offer["projected_plan_share_cents"] == 1022691
    assert_projection_splits_exactly(offer)


def test_a_rank_score_tie_is_broken_by_the_cheaper_daily_rate(api):
    """PRD §3.5: "It is assembled from four terms. The provider's `quality_star_rating` is
    multiplied by ten, so a five-star facility starts fifty points ahead of a zero
    baseline. A flat bonus of twenty-five points is added when a network contract exists
    between the episode's payer and the offering provider with `in_network` set to true. A
    proximity term adds whatever remains of a twenty-mile allowance after subtracting the
    provider's `distance_miles_from_hospital`, floored at zero — so a facility eight miles
    away earns twelve points, one exactly twenty miles away earns nothing, and one thirty
    miles away is not penalised below zero. Finally a cost penalty is subtracted: the
    offer's `daily_rate_cents` divided by five thousand and rounded down to a whole number,
    so each full fifty dollars of daily rate costs the offer one point."
    PRD §3.5: "Those are ordered by `rank_score` descending; ties are broken by
    `daily_rate_cents` ascending, and any remaining tie by `created_at` ascending — never by
    `id`. The top entry's identifier becomes `recommended_bed_offer_id`."
    PRD §3.5: "Any offer of the current round that is still `OFFERED` may be chosen; the
    advisory recommendation is not a constraint, and `choice_basis` exists precisely to
    record why a lower-ranked offer was preferred."

    Design: Corner/calculations/recommended_offer_tie_broken_by_lower_daily_rate
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200, "snf_auth_required": False,
               "hh_auth_required": False},
        patient={
            "mrn": "MRN-C304", "full_name": "Oli Pace", "date_of_birth": "1946-04-14",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    cedar = seed_provider(name="Cedar SNF", quality_star_rating=3,
                          distance_miles_from_hospital=5, bed_unit_codes=["UNIT-A"])
    birch = seed_provider(name="Birch SNF", quality_star_rating=4,
                          distance_miles_from_hospital=14, bed_unit_codes=["UNIT-A"])
    alder = seed_provider(name="Alder SNF", quality_star_rating=3,
                          distance_miles_from_hospital=12, bed_unit_codes=["UNIT-A"])
    seed_network_contract(env["payer"]["id"], cedar["id"], in_network=True,
                          negotiated_daily_rate_cents=28000)
    seed_network_contract(env["payer"]["id"], birch["id"], in_network=True,
                          negotiated_daily_rate_cents=29000)
    referral = get_success_data(
        api.create_referral(env["episode"]["id"], referral_payload(), CASE_MANAGER)
    )
    broadcast = get_success_data(
        api.broadcast_referral(
            referral["id"],
            {"provider_ids": [cedar["id"], birch["id"], alder["id"]]},
            CASE_MANAGER,
        )
    )

    offer_a = validate_success(
        api.create_offer(
            referral["id"],
            _offer_body(broadcast["version"], daily_rate_cents=30000),
            make_liaison_headers(cedar["id"]),
        ),
        201,
    )
    version = read_referral(referral["id"])["version"]
    offer_b = validate_success(
        api.create_offer(
            referral["id"],
            _offer_body(version, daily_rate_cents=35000),
            make_liaison_headers(birch["id"]),
        ),
        201,
    )

    assert offer_a["rank_score"] == 64, (
        "3 stars x 10 + 25 in-network + 15 proximity - 6 cost penalty == 64, got "
        f"{offer_a['rank_score']}"
    )
    assert offer_b["rank_score"] == 64, (
        "4 stars x 10 + 25 in-network + 6 proximity - 7 cost penalty == 64, got "
        f"{offer_b['rank_score']}"
    )
    assert offer_a["rate_variant_applied"] == "NETWORK_RATE"
    assert offer_a["projected_gross_cents"] == 392000, "14 tier-1 days at the 28000 contract rate"

    refreshed = validate_success(api.get_referral(referral["id"], CASE_MANAGER))
    assert refreshed["recommended_bed_offer_id"] == offer_a["id"], (
        "the tie is broken by the cheaper daily_rate_cents, not by insertion order"
    )

    placed = validate_success(
        api.document_choice(
            referral["id"],
            document_choice_payload(offer_b["id"], choice_basis="FAMILY_PREFERENCE"),
            CASE_MANAGER,
        )
    )
    assert placed["status"] == "PLACED"
    assert placed["chosen_bed_offer_id"] == offer_b["id"], (
        "the advisory recommendation never constrains which offer may be chosen"
    )
