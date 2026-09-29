"""Combinatorial formulas: where the order of two operations changes the answer.

Per-batch half-up rounding before summation, the min/max clamp pair that sizes
a random sample, and the reimbursement tier keyed on the gross before any
discount.

Adjudication note: the design index spells the sampling standard
`SOS-POOLED-A`, which exceeds the 8-character `jurisdiction_code` ceiling of
§2.5; it is carried here as `SOS-POOL`.
"""
from test_helpers import (
    api_client,
    close_circulation_and_open_round,
    create_assignment,
    create_cleared_petition,
    create_registered_circulator,
    file_batch_with_lines,
    make_county_clerk_headers,
    read_batch,
    read_petition,
    setup_circulation_ready,
    tally_round,
    validate_open_sample,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

FOUR_ACTIVE_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA3", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA4", "registration_status": "ACTIVE"},
]


def _build_four_line_world(batch_shapes):
    """A cleared petition with one registered circulator over ALPHA, carrying
    the given batches, with an OPEN FULL_CHECK round covering every line and
    every line validated VALID. ``batch_shapes`` is a list of line lists."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        counties=[("ALPHA", 20)], voters=FOUR_ACTIVE_VOTERS
    )
    for index, lines in enumerate(batch_shapes, start=1):
        file_batch_with_lines(world, lines, batch_key="b%d" % index)
    close_circulation_and_open_round(world, round_type="FULL_CHECK")
    validate_open_sample(world)
    return world


def test_two_two_line_batches_round_once_each_and_accrue_twenty_cents():
    """Half-up millicent conversion happens once per batch, so two batches of
    two examined lines accrue 10 + 10 == 20 cents, not the 19 a single
    four-line conversion would produce.

    PRD §2.6: "Batch verification cost converts millicents to cents with
    half-up rounding, and does so once per batch — never once per round and
    never once per petition ... At a rate of 4750 millicents per signature the
    per-batch amounts are 5 cents for one line, 10 cents for two, 14 cents for
    three and 19 cents for four; two batches of two lines therefore accrue 20
    cents in total, whereas rounding a four-line total in one step would have
    produced 19."

    Design: Difficulty/combinatorial_formula/per_batch_rounding_before_summation_on_cost_ledger
    """
    world = _build_four_line_world([["VA1", "VA2"], ["VA3", "VA4"]])

    closed = tally_round(world["round"]["id"])
    assert closed["accrued_cost_cents"] == 20
    assert closed["determination"] == "SUFFICIENT"

    first = read_batch(world["batches"]["b1"]["batch"]["id"])
    second = read_batch(world["batches"]["b2"]["batch"]["id"])
    assert first["checked_signature_count"] == 2
    assert first["verification_cost_cents"] == 10
    assert second["checked_signature_count"] == 2
    assert second["verification_cost_cents"] == 10
    assert first["status"] == "FULLY_CHECKED"
    assert second["status"] == "FULLY_CHECKED"

    petition = read_petition(world["petition"]["id"])
    assert petition["verification_cost_accrued_cents"] == 20, (
        "NOT 19, which is what one half-up rounding over the four-line total yields"
    )
    assert petition["verified_valid_count"] == 4
    assert petition["status"] == "PENDING_CERTIFICATION"


def test_one_four_line_batch_rounds_once_and_accrues_nineteen_cents():
    """The same four examined lines gathered into a single batch convert once,
    accruing 19 cents — the asymmetry the per-batch boundary creates.

    PRD §2.6: "Because rounding happens at the batch boundary, two batches of
    two examined lines each accrue more than one batch of four examined lines
    would at the same rate."

    Design: Difficulty/combinatorial_formula/per_batch_rounding_before_summation_on_cost_ledger
    """
    world = _build_four_line_world([["VA1", "VA2", "VA3", "VA4"]])

    closed = tally_round(world["round"]["id"])
    assert closed["accrued_cost_cents"] == 19

    batch = read_batch(world["batches"]["b1"]["batch"]["id"])
    assert batch["checked_signature_count"] == 4
    assert batch["verification_cost_cents"] == 19
    assert batch["status"] == "FULLY_CHECKED"

    petition = read_petition(world["petition"]["id"])
    assert petition["verification_cost_accrued_cents"] == 19

# The sampling standard: half the pool, but never fewer than two lines.
SAMPLING_STANDARD = {
    "jurisdiction_code": "SOS-POOL",
    "stratification_mode": "POOLED",
    "sample_pct_bps": 5000,
    "sample_min_count": 2,
}


def _open_sample_over(lines):
    """A cleared petition under the sampling standard carrying one ALPHA batch
    of the given lines, with a RANDOM_SAMPLE round just opened over it."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides=SAMPLING_STANDARD,
        counties=[("ALPHA", 20)],
        voters=FOUR_ACTIVE_VOTERS,
    )
    file_batch_with_lines(world, lines, batch_key="b1")
    close_circulation_and_open_round(world, round_type="RANDOM_SAMPLE")
    return world


def test_sample_size_is_capped_at_a_one_line_pool_by_the_outer_minimum():
    """A one-line pool draws one line: the statutory floor of two would exceed
    the pool, and the outer min() caps it back down.

    PRD §3.5: "A RANDOM_SAMPLE round takes the larger of the standard's
    sample_min_count and the pool size multiplied by sample_pct_bps divided by
    10000 with any remainder rounded up, and then caps that at the pool size — a
    statutory minimum can never demand more lines than exist."

    Design: Difficulty/combinatorial_formula/sample_size_min_max_clamp_interaction
    """
    world = _open_sample_over(["VA1"])

    assert world["round"]["eligible_pool_size"] == 1
    assert world["round"]["sample_size"] == 1, (
        "min(1, max(2, ceil(1*5000/10000))) == 1 — the outer min caps the draw "
        "at the pool"
    )
    assert world["round"]["status"] == "OPEN"
    assert read_petition(world["petition"]["id"])["status"] == "SAMPLE_VERIFICATION"


def test_sample_size_is_lifted_to_the_statutory_minimum_by_the_inner_maximum():
    """A two-line pool draws both lines: half of two is one, but the inner
    max() lifts that to sample_min_count 2, and the outer min() does not bite.

    PRD §3.5: "A RANDOM_SAMPLE round takes the larger of the standard's
    sample_min_count and the pool size multiplied by sample_pct_bps divided by
    10000 with any remainder rounded up, and then caps that at the pool size."

    Design: Difficulty/combinatorial_formula/sample_size_min_max_clamp_interaction
    """
    world = _open_sample_over(["VA2", "VA3"])

    assert world["round"]["eligible_pool_size"] == 2
    assert world["round"]["sample_size"] == 2, (
        "the inner max() lifts ceil(2*5000/10000) == 1 up to sample_min_count 2"
    )
    assert world["round"]["status"] == "OPEN"
    assert read_petition(world["petition"]["id"])["status"] == "SAMPLE_VERIFICATION"


def test_both_clamp_directions_hold_for_two_petitions_in_one_program():
    """Two petitions under the same standard, one with a one-line pool and one
    with a two-line pool, exercise the cap and the floor side by side.

    PRD §3.5: "a statutory minimum can never demand more lines than exist."

    Design: Difficulty/combinatorial_formula/sample_size_min_max_clamp_interaction
    """
    set_clock(CLOCK_EPOCH)
    base = setup_circulation_ready(
        standard_overrides=SAMPLING_STANDARD,
        counties=[("ALPHA", 20)],
        voters=FOUR_ACTIVE_VOTERS,
    )
    file_batch_with_lines(base, ["VA1"], batch_key="b1")

    second_petition = create_cleared_petition(base["standard"]["id"])
    second_circulator = create_registered_circulator(full_name="Cora Second")
    other = {
        "standard": base["standard"],
        "counties": base["counties"],
        "voters": base["voters"],
        "petition": second_petition,
        "circulators": {"c1": second_circulator},
        "assignments": {},
        "batches": {},
        "proponent_user_id": base["proponent_user_id"],
    }
    other["assignments"]["c1"] = create_assignment(
        second_petition["id"],
        second_circulator["id"],
        assigned_county_codes=["ALPHA"],
        effective_from=CLOCK_EPOCH,
        effective_to="2026-08-31T00:00:00Z",
    )
    file_batch_with_lines(other, ["VA2", "VA3"], batch_key="b1")

    close_circulation_and_open_round(base, round_type="RANDOM_SAMPLE")
    close_circulation_and_open_round(other, round_type="RANDOM_SAMPLE")

    assert base["round"]["eligible_pool_size"] == 1
    assert base["round"]["sample_size"] == 1
    assert other["round"]["eligible_pool_size"] == 2
    assert other["round"]["sample_size"] == 2
    assert base["round"]["status"] == "OPEN"
    assert other["round"]["status"] == "OPEN"


def test_invoice_tier_is_keyed_on_the_gross_before_the_discount_is_applied():
    """A gross of exactly 20 cents lands in TIER_A, and the tier is never
    re-keyed on the discounted subtotal or the final total.

    PRD §3.6: "The tier is keyed on gross_cents before any discount ... A gross
    of exactly 20 cents therefore selects TIER_A; the boundary is inclusive ...
    Worked at a county_surcharge_bps of 250: ... a gross of 20 cents gives
    TIER_A, a discount of 2, a subtotal of 18, a surcharge of 1 and a total of
    19."

    Design: Difficulty/combinatorial_formula/invoice_tier_keyed_on_gross_before_discount
    """
    world = _build_four_line_world([["VA1", "VA2"], ["VA3", "VA4"]])
    tally_round(world["round"]["id"])

    clerk = make_county_clerk_headers(world["counties"]["ALPHA"]["id"])
    invoice = validate_success(
        api_client.get_verification_invoice(world["petition"]["id"], clerk)
    )

    assert invoice["gross_cents"] == 20, "10 + 10 from the two FULLY_CHECKED batches"
    assert invoice["tier"] == "TIER_A", (
        "the 20-cent floor is inclusive and the tier is keyed on the gross"
    )
    assert invoice["discount_bps"] == 1000
    assert invoice["discount_cents"] == 2, "floor(20 * 1000 / 10000)"
    assert invoice["subtotal_cents"] == 18
    assert invoice["surcharge_cents"] == 1, "ceil(18 * 250 / 10000)"
    assert invoice["total_cents"] == 19, (
        "NOT 21, which re-keying the tier on total_cents would produce, and NOT "
        "20, which one rounding over the four-line total would produce"
    )


def test_invoice_falls_to_no_tier_when_the_gross_sits_one_cent_below_the_floor():
    """The same four examined lines in a single batch gross 19 cents, one below
    the TIER_A floor, so no discount is granted at all.

    PRD §3.6: "anything below 20 cents is TIER_NONE with a discount_bps of 0 ...
    The same four examined lines rounded in one step instead of once per batch
    would have produced a gross of 19, which slips below the tier-A floor and
    yields a total of 20; skipping the discount entirely would yield 21."

    Design: Difficulty/combinatorial_formula/invoice_tier_keyed_on_gross_before_discount
    """
    world = _build_four_line_world([["VA1", "VA2", "VA3", "VA4"]])
    tally_round(world["round"]["id"])

    clerk = make_county_clerk_headers(world["counties"]["ALPHA"]["id"])
    invoice = validate_success(
        api_client.get_verification_invoice(world["petition"]["id"], clerk)
    )

    assert invoice["gross_cents"] == 19
    assert invoice["tier"] == "TIER_NONE"
    assert invoice["discount_bps"] == 0
    assert invoice["discount_cents"] == 0
    assert invoice["subtotal_cents"] == 19
    assert invoice["surcharge_cents"] == 1, "ceil(19 * 250 / 10000)"
    assert invoice["total_cents"] == 20, (
        "a smaller gross can carry a larger total: the discount is lost entirely"
    )
