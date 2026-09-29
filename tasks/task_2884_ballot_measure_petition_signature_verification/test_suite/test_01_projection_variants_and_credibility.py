"""The two documented dual-variant calculations of the specification.

`projected_valid_count` diverges between a POOLED and a STRATIFIED standard on
byte-identical data, and `credibility_score_bps` diverges between the
provisional and the adjudicated variant on byte-identical line history.

Adjudication note: the design index spells the two comparison standards
`SOS-POOLED-A` and `SOS-STRAT-A`, but §2.5 caps `jurisdiction_code` at 8
characters, so those literals would be refused with ERR_INVALID_REQUEST. The
codes are carried here as `SOS-POOL` and `SOS-STRA`; the identifier is not part
of any asserted outcome.
"""
from test_helpers import (
    SECOND_EXAMINER_USER_ID,
    THIRD_EXAMINER_USER_ID,
    adjudicate_referral,
    close_circulation_and_open_round,
    create_assignment,
    create_cleared_petition,
    create_registered_circulator,
    file_batch_with_lines,
    make_examiner_headers,
    open_referral,
    read_assignment,
    read_batch,
    read_circulator,
    read_line,
    read_petition,
    refer_referral_to_ag,
    register_standard,
    setup_circulation_ready,
    setup_program,
    tally_round,
    validate_open_sample,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock
from test_helpers.test_users import PROPONENT_USER_ID

# Two counties of twenty registered voters each, and the roll the design pins:
# VA1 ACTIVE and VA2 INACTIVE in ALPHA, VB1 and VB2 ACTIVE in BRAVO.
PROJECTION_COUNTIES = [("ALPHA", 20), ("BRAVO", 20)]
PROJECTION_VOTERS = [
    {"voter_id_number": "VA1", "county_code": "ALPHA", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "county_code": "ALPHA", "registration_status": "INACTIVE"},
    {"voter_id_number": "VB1", "county_code": "BRAVO", "registration_status": "ACTIVE"},
    {"voter_id_number": "VB2", "county_code": "BRAVO", "registration_status": "ACTIVE"},
]


def _build_projection_side(base, jurisdiction_code, stratification_mode, label):
    """One petition under its own standard, carrying an ALPHA batch of
    (VA1, VA2) and a BRAVO batch of (VB1, VB2), all four lines signed on the
    same day, with an OPEN RANDOM_SAMPLE round whose whole sample has been
    validated. Returns the world dict, ready to tally."""
    standard = register_standard(
        jurisdiction_code=jurisdiction_code,
        stratification_mode=stratification_mode,
        sample_pct_bps=5000,
        sample_min_count=2,
    )
    petition = create_cleared_petition(standard["id"])
    circulator = create_registered_circulator(full_name="Circulator %s" % label)
    side = {
        "standard": standard,
        "counties": base["counties"],
        "voters": base["voters"],
        "petition": petition,
        "circulators": {"c1": circulator},
        "assignments": {},
        "batches": {},
        "proponent_user_id": PROPONENT_USER_ID,
    }
    side["assignments"]["c1"] = create_assignment(
        petition["id"],
        circulator["id"],
        assigned_county_codes=["ALPHA", "BRAVO"],
        effective_from=CLOCK_EPOCH,
        effective_to="2026-08-31T00:00:00Z",
    )
    file_batch_with_lines(side, ["VA1", "VA2"], county_code="ALPHA", batch_key="alpha")
    file_batch_with_lines(side, ["VB1", "VB2"], county_code="BRAVO", batch_key="bravo")
    close_circulation_and_open_round(side)
    validate_open_sample(side)
    return side


def test_pooled_projection_extrapolates_one_statewide_rate():
    """A POOLED standard sizes the draw once and extrapolates a single rate
    across the whole accepted pool, projecting 4.

    PRD §3.6: "For a RANDOM_SAMPLE round under a POOLED standard, the
    projection is the petition's accepted_raw_total multiplied by the round's
    validity_rate_bps, divided by 10000, with the remainder discarded: one
    statewide rate extrapolated across the whole accepted pool, so a county
    with a poor validity rate is diluted by better counties."

    Design: Difficulty/dual_variant_calc/pooled_vs_stratified_projection_divergence_on_petition
    """
    set_clock(CLOCK_EPOCH)
    base = setup_program(counties=PROJECTION_COUNTIES, voters=PROJECTION_VOTERS)
    side = _build_projection_side(base, "SOS-POOL", "POOLED", "P")

    assert side["round"]["eligible_pool_size"] == 4, (
        "the pool is the four accepted lines of the two batches"
    )
    assert side["round"]["sample_size"] == 2, (
        "POOLED sizes the draw once: min(4, max(2, ceil(4*5000/10000))) == 2"
    )

    closed = tally_round(side["round"]["id"])
    assert closed["sampled_valid_count"] == 2
    assert closed["validity_rate_bps"] == 10000
    assert closed["projected_valid_count"] == 4, "floor(4 * 10000 / 10000)"
    assert closed["determination"] == "SUFFICIENT"

    petition = read_petition(side["petition"]["id"])
    assert petition["accepted_raw_total"] == 4
    assert petition["projected_valid_count"] == 4


def test_stratified_projection_floors_each_county_before_summing():
    """A STRATIFIED standard applies sample_min_count inside every county
    stratum and discards each county's remainder before the strata are summed,
    projecting 3 — and its round-level audit rate legitimately disagrees.

    PRD §3.6: "For a RANDOM_SAMPLE round under a STRATIFIED standard, the
    projection is instead the sum, taken across the participating counties in
    county_code ascending order, of each county's own accepted line total
    multiplied by that county's own rate and divided by 10000 with the
    remainder discarded ... Note that the round's own validity_rate_bps remains
    the round-level rate even under a stratified projection, so the audit field
    and the projection can legitimately disagree."

    Design: Difficulty/dual_variant_calc/pooled_vs_stratified_projection_divergence_on_petition
    """
    set_clock(CLOCK_EPOCH)
    base = setup_program(counties=PROJECTION_COUNTIES, voters=PROJECTION_VOTERS)
    side = _build_projection_side(base, "SOS-STRA", "STRATIFIED", "S")

    assert side["round"]["eligible_pool_size"] == 4
    assert side["round"]["sample_size"] == 4, (
        "STRATIFIED applies sample_min_count 2 inside each of the two county strata"
    )

    closed = tally_round(side["round"]["id"])
    assert closed["sampled_valid_count"] == 3
    assert closed["validity_rate_bps"] == 7500, (
        "the audit field stays the round-level rate: 3 of 4 selected lines VALID"
    )
    assert closed["projected_valid_count"] == 3, (
        "ALPHA floor(2 * 5000 / 10000) == 1 plus BRAVO floor(2 * 10000 / 10000) == 2"
    )
    assert closed["determination"] == "SUFFICIENT"

    petition = read_petition(side["petition"]["id"])
    assert petition["accepted_raw_total"] == 4
    assert petition["projected_valid_count"] == 3

    alpha_line_two = read_line(side["batches"]["alpha"]["lines"][1]["id"])
    assert alpha_line_two["validation_status"] == "INVALID_NOT_REGISTERED", (
        "VA2 is INACTIVE, so the ALPHA stratum carries one invalid line"
    )


def test_pooled_and_stratified_projections_diverge_on_identical_data():
    """Two petitions differing only in their standard's stratification_mode,
    over byte-identical rolls, batches and signing dates, project 4 and 3.

    PRD §3.6: "For identical data — two accepted lines in each of two counties,
    one line in the first found invalid — a POOLED standard yields 4 and a
    STRATIFIED standard yields 3."

    Design: Difficulty/dual_variant_calc/pooled_vs_stratified_projection_divergence_on_petition
    """
    set_clock(CLOCK_EPOCH)
    base = setup_program(counties=PROJECTION_COUNTIES, voters=PROJECTION_VOTERS)
    pooled = _build_projection_side(base, "SOS-POOL", "POOLED", "P")
    stratified = _build_projection_side(base, "SOS-STRA", "STRATIFIED", "S")

    assert pooled["round"]["eligible_pool_size"] == 4
    assert stratified["round"]["eligible_pool_size"] == 4, (
        "both petitions hold identical 4-line pools"
    )

    pooled_round = tally_round(pooled["round"]["id"])
    stratified_round = tally_round(stratified["round"]["id"])

    assert pooled_round["projected_valid_count"] == 4
    assert stratified_round["projected_valid_count"] == 3
    assert pooled_round["determination"] == "SUFFICIENT"
    assert stratified_round["determination"] == "SUFFICIENT"

    assert read_petition(pooled["petition"]["id"])["projected_valid_count"] == 4
    assert read_petition(stratified["petition"]["id"])["projected_valid_count"] == 3


def _build_credibility_world():
    """One petition, one circulator, one two-line ALPHA batch (VA1 ACTIVE and
    VA2 INACTIVE), and an OPEN FULL_CHECK round whose two lines have both been
    validated — so one line is VALID and one INVALID_NOT_REGISTERED."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        counties=[("ALPHA", 20)],
        voters=[
            {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
            {"voter_id_number": "VA2", "registration_status": "INACTIVE"},
        ],
    )
    file_batch_with_lines(world, ["VA1", "VA2"], batch_key="b1")
    close_circulation_and_open_round(world, round_type="FULL_CHECK")
    validate_open_sample(world)
    return world


def test_provisional_credibility_halves_the_invalid_rate_and_charges_open_referrals():
    """While misconduct_strike_count is 0 the invalid rate weighs 5000 bps,
    scoring 7500, and each still-open referral costs a flat 500 bps.

    PRD §3.9: "Under the provisional variant, used while
    misconduct_strike_count is 0, the raw score is 10000 less the invalid rate
    multiplied by 5000 and divided by 10000 with the remainder discarded, less
    a flat 500 basis points for each FraudReferral of this circulator whose
    status is OPENED or REFERRED_TO_AG."

    Design: Difficulty/dual_variant_calc/provisional_vs_adjudicated_circulator_credibility
    """
    world = _build_credibility_world()
    circulator_id = world["circulators"]["c1"]["id"]

    before = read_circulator(circulator_id)
    assert before["misconduct_strike_count"] == 0
    assert before["credibility_score_bps"] == 7500, (
        "provisional variant: 10000 - floor(5000 * 5000 / 10000)"
    )

    open_referral(
        world["petition"]["id"],
        circulator_id,
        referral_type="CIRCULATOR_MISCONDUCT",
        opened_by=SECOND_EXAMINER_USER_ID,
    )

    with_referral = read_circulator(circulator_id)
    assert with_referral["credibility_score_bps"] == 7000, (
        "still provisional, minus one flat 500 bps open-referral penalty"
    )
    assert with_referral["misconduct_strike_count"] == 0
    assert with_referral["registration_status"] == "REGISTERED", (
        "opening a referral proves nothing and moves no registration status"
    )


def test_adjudicated_credibility_takes_the_full_rate_and_a_strike_penalty():
    """A substantiated finding switches the same line history to the
    adjudicated variant — full weight plus 2000 bps per strike, scoring 3000 —
    and suspends the circulator without touching the verified batch.

    PRD §3.9: "Under the adjudicated variant, used once
    misconduct_strike_count is 1 or more, the raw score is 10000 less the
    invalid rate at full weight, that is multiplied by 10000 and divided by
    10000 with the remainder discarded, less 2000 basis points for each
    substantiated strike; open-referral penalties drop away entirely."

    Design: Difficulty/dual_variant_calc/provisional_vs_adjudicated_circulator_credibility
    """
    world = _build_credibility_world()
    circulator_id = world["circulators"]["c1"]["id"]
    batch_id = world["batches"]["b1"]["batch"]["id"]

    referral = open_referral(
        world["petition"]["id"],
        circulator_id,
        referral_type="CIRCULATOR_MISCONDUCT",
        opened_by=SECOND_EXAMINER_USER_ID,
    )
    refer_referral_to_ag(referral["id"], examiner_id=SECOND_EXAMINER_USER_ID)
    adjudicated = adjudicate_referral(
        referral["id"],
        "SUBSTANTIATED",
        adjudicator_headers=make_examiner_headers(THIRD_EXAMINER_USER_ID),
    )
    assert adjudicated["status"] == "SUBSTANTIATED"

    circulator = read_circulator(circulator_id)
    assert circulator["misconduct_strike_count"] == 1
    assert circulator["credibility_score_bps"] == 3000, (
        "adjudicated variant: 10000 - floor(5000 * 10000 / 10000) - 2000"
    )
    assert circulator["registration_status"] == "SUSPENDED"

    assignment = read_assignment(world["assignments"]["c1"]["id"])
    assert assignment["status"] == "SUSPENDED"

    batch = read_batch(batch_id)
    assert batch["status"] == "AFFIDAVIT_VERIFIED", (
        "the referral named no batch_id, so no batch was invalidated"
    )
    lines = [read_line(line["id"]) for line in world["batches"]["b1"]["lines"]]
    assert [line["validation_status"] for line in lines] == [
        "VALID",
        "INVALID_NOT_REGISTERED",
    ]
