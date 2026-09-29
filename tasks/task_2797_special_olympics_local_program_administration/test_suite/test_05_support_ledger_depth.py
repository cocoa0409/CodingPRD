"""Recognition variants, the round-then-sum match credit, and the void reversal."""

from test_helpers import fixtures as fx, validate_success
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.fixtures import PM


def _contribution_rows(program_id):
    rows = api_client.list_program_contributions(
        program_id, PM, params={"limit": 100}).json()["data"]
    return {row["id"]: row for row in rows}


def test_01_in_kind_goods_are_capped_while_in_kind_services_are_discounted():
    """One stated value of 600000 cents recognises two different amounts.

    PRD §3.9: "`IN_KIND_GOODS` is **capped, not discounted**: the recognised
    value is the smaller of the stated value and 500,000 cents … so a stated
    600,000 recognises 500,000. `IN_KIND_SERVICES` is **discounted, not
    capped**: the recognised value is eighty percent of the stated value,
    rounded half up to whole cents, with no ceiling at all, so the same stated
    600,000 recognises 480,000 — a different number from an identical input,
    decided purely by which type was declared."

    Design: Difficulty/dual_variant_calc/contribution_in_kind_recognition_variants
    """
    world = fx.setup_contribution_world([
        {"donor_name": "Halbrook Hardware", "contribution_type": "IN_KIND_GOODS",
         "designation": "GENERAL", "stated_value_cents": 600_000,
         "received_on": "2026-08-01"},
        {"donor_name": "Halbrook Legal", "contribution_type": "IN_KIND_SERVICES",
         "designation": "GENERAL", "stated_value_cents": 600_000,
         "received_on": "2026-08-01"},
    ])
    goods, services = world["contributions"]
    assert goods["stated_value_cents"] == 600_000
    assert services["stated_value_cents"] == 600_000
    assert goods["recognized_value_cents"] == 500_000
    assert services["recognized_value_cents"] == 480_000
    assert goods["status"] == "RECEIVED"
    assert services["status"] == "RECEIVED"

    program = world["program"]
    assert program["recognized_support_cents"] == 980_000
    assert program["pledged_support_cents"] == 0
    assert program["family_engagement_credit_cents"] == 0


def test_02_the_match_credit_rounds_per_row_before_it_is_summed():
    """Three 12345-cent gifts credit 3705, not the sum-then-round 3704.

    PRD §3.9: "The program's `family_engagement_credit_cents` is then the **sum
    of those already-rounded per-row integers** across its received
    contributions. Rounding happens per contribution first and summation second,
    never the other way around. The difference is real: three received
    family-engagement contributions of 12,345 cents each each earn a match of
    1,235 cents, summing to 3,705, whereas rounding a combined 37,035 cents at
    ten percent would yield 3,704 — one cent short, and wrong."

    Design: Difficulty/combinatorial_formula/family_engagement_round_then_sum
    """
    specs = [
        {"donor_name": donor, "contribution_type": "CASH_RECEIPT",
         "designation": "FAMILY_ENGAGEMENT", "stated_value_cents": 12_345,
         "received_on": "2026-08-01"}
        for donor in ("Foster Family", "Petrov Family", "Lin Family")
    ]
    world = fx.setup_contribution_world(specs)
    for contribution in world["contributions"]:
        assert contribution["recognized_value_cents"] == 12_345
        assert contribution["match_credit_cents"] == 1_235
        assert contribution["status"] == "RECEIVED"

    program = world["program"]
    assert program["family_engagement_credit_cents"] == 3_705
    assert program["family_engagement_credit_cents"] != 3_704
    assert program["recognized_support_cents"] == 37_035


def _three_gift_ledger():
    """A PLEDGED cash gift, a capped goods gift and a discounted services gift."""
    world = fx.setup_contribution_world([
        {"donor_name": "Cedar Valley Rotary", "contribution_type": "CASH_PLEDGE",
         "designation": "GENERAL", "stated_value_cents": 250_000},
        {"donor_name": "Northline Sporting Goods",
         "contribution_type": "IN_KIND_GOODS", "designation": "FAMILY_ENGAGEMENT",
         "stated_value_cents": 600_000, "received_on": "2026-08-01"},
        {"donor_name": "Harbor Physio Group",
         "contribution_type": "IN_KIND_SERVICES",
         "designation": "FAMILY_ENGAGEMENT", "stated_value_cents": 123_456,
         "received_on": "2026-08-01"},
    ])
    world["pledge"], world["goods"], world["services"] = world["contributions"]
    return world


def test_03_voiding_a_received_gift_removes_exactly_the_integers_it_added():
    """The reversal is per-row-exact: 98765 and 9877 leave, nothing else moves.

    PRD §2.10: "The program's `recognized_support_cents` and
    `pledged_support_cents` must at all times equal the sums of
    `recognized_value_cents` over that program's contributions in `RECEIVED` and
    `PLEDGED` status respectively"; PRD §3.9: voiding a `RECEIVED` row
    "decrements `family_engagement_credit_cents` by **exactly the integer stored
    in that row's `match_credit_cents`** — the same integer the forward action
    added, read back off the row rather than recomputed from the rate".

    Design: Difficulty/compensating_invariant/contribution_void_conserves_support_ledger
    """
    world = _three_gift_ledger()
    assert world["services"]["recognized_value_cents"] == 98_765
    assert world["services"]["match_credit_cents"] == 9_877
    assert world["goods"]["recognized_value_cents"] == 500_000
    assert world["goods"]["match_credit_cents"] == 50_000
    before = world["program"]
    assert before["recognized_support_cents"] == 598_765
    assert before["pledged_support_cents"] == 250_000
    assert before["family_engagement_credit_cents"] == 59_877

    validate_success(api_client.void_contribution(
        world["services"]["id"],
        f.void_contribution_payload(void_reason_code="VALUATION_ERROR"), PM))

    after = fx.get_program(world["program"]["id"])
    assert after["recognized_support_cents"] == 500_000
    assert after["family_engagement_credit_cents"] == 50_000
    assert after["pledged_support_cents"] == 250_000


def test_04_the_voided_row_zeroes_itself_and_leaves_its_siblings_alone():
    """Only the voided row changes; the pledge and the capped gift are untouched.

    PRD §3.9: "Once the ledgers have been decremented, the voided row's own
    `recognized_value_cents` and `match_credit_cents` are both set to 0"; and
    voiding one already `RECEIVED` "moves it `RECEIVED → VOID`".

    Design: Difficulty/compensating_invariant/contribution_void_conserves_support_ledger
    """
    world = _three_gift_ledger()
    validate_success(api_client.void_contribution(
        world["services"]["id"],
        f.void_contribution_payload(void_reason_code="VALUATION_ERROR"), PM))

    rows = _contribution_rows(world["program"]["id"])
    voided = rows[world["services"]["id"]]
    assert voided["status"] == "VOID"
    assert voided["void_reason_code"] == "VALUATION_ERROR"
    assert voided["recognized_value_cents"] == 0
    assert voided["match_credit_cents"] == 0
    assert voided["stated_value_cents"] == 123_456

    goods = rows[world["goods"]["id"]]
    assert goods["status"] == "RECEIVED"
    assert goods["recognized_value_cents"] == 500_000
    assert goods["match_credit_cents"] == 50_000

    pledge = rows[world["pledge"]["id"]]
    assert pledge["status"] == "PLEDGED"
    assert pledge["recognized_value_cents"] == 250_000
    assert pledge["match_credit_cents"] == 0
