"""Entry fee assessment, the catalogue levy and the show's money ledger."""

from test_helpers.assertions import (
    assert_cents,
    assert_show_ledger_conserved,
)
from test_helpers.fixtures import (
    close_entries,
    declare_season,
    read_class,
    read_entry,
    read_show,
    setup_multi_dog_household,
)


def _household_of_three():
    """One handler, three dogs, three confirmed entries in one BREED class."""
    return setup_multi_dog_household(
        num_dogs=3,
        dog_overrides=[{"sex": "BITCH"}, {"sex": "BITCH"}, {"sex": "DOG"}],
        class_overrides={"class_code": "GR-OPEN-D"},
    )


def test_provisional_pricing_sees_only_the_confirmations_made_so_far():
    """Each confirmation prices against the entries confirmed before it.

    PRD 3.5: "Entries still sitting in `RECEIVED` are invisible, so the
    household discount can only appear from a handler's third confirmation
    onward, and each earlier entry keeps the fee it was assessed at its own
    confirmation instant."

    Design: Difficulty/dual_variant_calc/entry_fee_provisional_versus_final_on_show_ledger
    """
    context = _household_of_three()
    e1, e2, e3 = (read_entry(entry) for entry in context["entries"])

    assert e1["entry_fee_cents"] == 4663
    assert e2["entry_fee_cents"] == 3763
    assert e3["entry_fee_cents"] == 3387
    for entry in (e1, e2, e3):
        assert entry["fee_basis"] == "PROVISIONAL"

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 11813


def test_closing_entries_reprices_the_whole_confirmed_population_at_once():
    """The final occasion applies the household discount retroactively.

    PRD 3.5: "the whole confirmed population is visible at once and the
    household discount is applied retroactively to every counted entry of a
    qualifying handler."

    Design: Difficulty/dual_variant_calc/entry_fee_provisional_versus_final_on_show_ledger
    """
    context = _household_of_three()

    closed = close_entries(context["klass"])
    assert closed["status"] == "CLOSED"
    assert closed["final_assessment_done"] is True

    e1, e2, e3 = (read_entry(entry) for entry in context["entries"])
    assert e1["entry_fee_cents"] == 4197
    assert e2["entry_fee_cents"] == 3387
    assert e3["entry_fee_cents"] == 3387
    assert e1["fee_basis"] == "FINAL"


def test_final_reassessment_records_the_negative_charge_delta_on_the_show():
    """The delta is the new charge less the charge immediately before closing.

    PRD 3.5: "`fee_assessment_delta_cents` is written as the new
    `fee_charged_cents` minus its value immediately before the re-assessment, a
    figure that is negative whenever the retroactive household discount bites."

    Design: Difficulty/dual_variant_calc/entry_fee_provisional_versus_final_on_show_ledger
    """
    context = _household_of_three()
    assert read_show(context["show"])["fee_charged_cents"] == 11813

    close_entries(context["klass"])

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 10971
    assert show["fee_assessment_delta_cents"] == -842


def test_every_entry_carries_its_own_levy_rounded_half_up_to_a_whole_cent():
    """Seven and a half percent of 3,500 cents is 262.5, which rounds to 263.

    PRD 3.5: "computes the catalogue levy as seven and a half percent of the
    base, rounded half-up to a whole cent — 263 cents on a 3,500-cent base and
    210 cents on a 2,800-cent base — and this rounded value is what lands in the
    entry's `levy_cents`."

    Design: Difficulty/combinatorial_formula/catalog_levy_rounded_per_entry_then_summed
    """
    context = _household_of_three()

    for entry in context["entries"]:
        row = read_entry(entry)
        assert_cents(row["levy_cents"], "levy_cents")
        assert row["levy_cents"] == 263


def test_show_levy_total_sums_the_already_rounded_per_entry_levies():
    """Rounding per entry then summing gives 789, not the 788 of a single rounding.

    PRD 3.5: "The show's `levy_total_cents` and `fee_charged_cents` are then
    re-derived by summing those already-rounded per-entry values, and
    `fee_collected_cents` is `fee_charged_cents` less `fee_refunded_cents`."

    Design: Difficulty/combinatorial_formula/catalog_levy_rounded_per_entry_then_summed
    """
    context = _household_of_three()

    show = read_show(context["show"])
    assert show["levy_total_cents"] == 789
    assert show["fee_charged_cents"] == 11813
    assert show["fee_collected_cents"] == 11813


def test_third_confirmation_prices_at_the_household_rate_without_touching_siblings():
    """The discount reaching entry three leaves the two earlier fees alone.

    PRD 3.7: "No other entry is re-priced, so a household discount already
    granted to a sibling entry is not clawed back."

    Design: Difficulty/combinatorial_formula/catalog_levy_rounded_per_entry_then_summed
    """
    context = _household_of_three()
    e1, e2, e3 = (read_entry(entry) for entry in context["entries"])

    assert e3["entry_fee_cents"] == 3387
    assert e1["entry_fee_cents"] == 4663
    assert e2["entry_fee_cents"] == 3763


def test_retention_tier_reads_the_balance_as_it_stood_before_the_refund():
    """A pre-refund balance of 11,813 cents retains five percent, which is 233.

    PRD 3.7: "The retention tier is chosen from the show's
    `fee_collected_cents` as it stood *before* this refund — a snapshot read
    once, before any field of this withdrawal is written, and never re-derived
    from the post-refund balance."

    Design: Difficulty/combinatorial_formula/refund_retention_tier_keyed_on_pre_refund_ledger
    """
    context = _household_of_three()
    e1 = context["entries"][0]

    withdrawn = declare_season(e1, context["handler"])
    assert withdrawn["entry_status"] == "WITHDRAWN"
    assert withdrawn["welfare_status"] == "SEASON_DECLARED"
    assert withdrawn["fee_refunded_cents"] == 4430
    assert withdrawn["net_fee_cents"] == 233

    show = read_show(context["show"])
    assert show["fee_refunded_cents"] == 4430
    assert show["fee_retained_cents"] == 233


def test_withdrawal_re_derives_the_collected_balance_and_leaves_siblings_priced():
    """Collected money is charged less refunded, and no sibling is re-priced.

    PRD 3.7: "the show's `fee_refunded_cents` grows by the net refund, its
    `fee_retained_cents` grows by the retention, and its `fee_collected_cents`
    is re-derived as `fee_charged_cents` less `fee_refunded_cents`."

    Design: Difficulty/combinatorial_formula/refund_retention_tier_keyed_on_pre_refund_ledger
    """
    context = _household_of_three()
    declare_season(context["entries"][0], context["handler"])

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 11813
    assert show["fee_collected_cents"] == 7383

    e2, e3 = (read_entry(entry) for entry in context["entries"][1:])
    assert e2["entry_fee_cents"] == 3763
    assert e3["entry_fee_cents"] == 3387
    assert read_class(context["klass"])["entry_count"] == 2


def test_second_withdrawal_retains_nothing_once_the_balance_falls_below_the_tier():
    """The tier is re-read per withdrawal, so 7,383 cents retains nothing at all.

    PRD 3.7: "anything below 10,000 retains nothing at all, so an early
    withdrawal returns the entry fee in full."

    Design: Difficulty/compensating_invariant/money_conservation_across_two_withdrawals
    """
    context = _household_of_three()
    e1, e2 = context["entries"][0], context["entries"][1]

    declare_season(e1, context["handler"])
    assert read_show(context["show"])["fee_collected_cents"] == 7383

    second = declare_season(e2, context["handler"])
    assert second["fee_refunded_cents"] == 3763
    assert second["net_fee_cents"] == 0
    assert second["entry_status"] == "WITHDRAWN"


def test_money_conservation_holds_after_two_successive_withdrawals():
    """Collected money still equals the sum of every entry's net fee.

    PRD 2.7: "it is the conserved quantity: at every instant it must equal the
    sum of `net_fee_cents` across the show's entries, where each entry's
    `net_fee_cents` is its own `entry_fee_cents` less its own
    `fee_refunded_cents`."

    Design: Difficulty/compensating_invariant/money_conservation_across_two_withdrawals
    """
    context = _household_of_three()
    declare_season(context["entries"][0], context["handler"])
    declare_season(context["entries"][1], context["handler"])

    entries = [read_entry(entry) for entry in context["entries"]]
    assert [entry["net_fee_cents"] for entry in entries] == [233, 0, 3387]

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 11813
    assert show["fee_refunded_cents"] == 8193
    assert show["fee_retained_cents"] == 233
    assert show["fee_collected_cents"] == 3620
    assert_show_ledger_conserved(show, entries)
    assert read_class(context["klass"])["entry_count"] == 1
