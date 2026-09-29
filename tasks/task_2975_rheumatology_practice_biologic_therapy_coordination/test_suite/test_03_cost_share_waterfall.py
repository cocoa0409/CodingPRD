"""The member cost waterfall: channel variants and per-dose rounding order.

Sources: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rules `dual_variant_calc` and
`combinatorial_formula`.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import api_client
from test_helpers.assertions import assert_cents, assert_cost_share_estimate
from test_helpers.constants import CLOCK_DEFAULT
from test_helpers.factories import create_drug_payload, meridian_plan_payload
from test_helpers.fixtures import (
    ADMIN,
    COUNSELOR,
    bootstrap_reference,
    create_drug,
    open_planned_episode,
    planned_episode,
    register_patient,
    set_clock,
)

SC_DRUG = create_drug_payload(
    name="Tocilizumab SC",
    molecule_class="IL6",
    route="SC",
    acquisition_cost_cents=250_050,
    admin_time_minutes=0,
    monitoring_panel_type="CBC",
    monitoring_panel_interval_days=180,
)

IV_DRUG = create_drug_payload(
    name="Tocilizumab IV",
    molecule_class="IL6",
    route="IV",
    acquisition_cost_cents=250_050,
    admin_time_minutes=150,
    monitoring_panel_type="CMP",
    monitoring_panel_interval_days=90,
)


def _two_channel_practice():
    """One plan funding both benefits, two IL6 products of identical acquisition
    cost — one subcutaneous, one intravenous — and one `PLANNED` episode each for
    two distinct patients, so neither episode supersedes the other."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = bootstrap_reference(
        drug_payload=dict(SC_DRUG), plan_payload=meridian_plan_payload()
    )
    iv_drug = create_drug(None, dict(IV_DRUG))

    register_patient(scenario)
    sc_episode = open_planned_episode(scenario)

    register_patient(scenario)
    iv_episode = open_planned_episode(scenario, drug_id=iv_drug["id"])

    return scenario, sc_episode, iv_episode


def _estimate(episode_id, dose_count=6, headers=COUNSELOR):
    return get_success_data(
        api_client.get_cost_share_estimate(episode_id, headers, {"dose_count": dose_count})
    )


# ---------------------------------------------------------------------------
# dual_variant_calc /
# cost_share_channel_variant_divergence_pharmacy_vs_medical
# ---------------------------------------------------------------------------
def test_pharmacy_variant_charges_no_facility_fee_and_no_multiplier():
    """On the pharmacy benefit the allowed amount is the bare acquisition cost.

    PRD §3.7: "On the `PHARMACY` variant, `allowed_per_dose_cents` is simply the
    drug's `acquisition_cost_cents` and `facility_per_dose_cents` is zero."

    Design: Difficulty/dual_variant_calc/cost_share_channel_variant_divergence_pharmacy_vs_medical
    """
    _scenario, sc_episode, _iv_episode = _two_channel_practice()

    assert sc_episode["benefit_channel"] == "PHARMACY"
    assert sc_episode["site_of_care"] == "SELF_ADMIN"

    estimate = _estimate(sc_episode["id"])

    assert estimate["benefit_channel"] == "PHARMACY"
    assert estimate["site_of_care"] == "SELF_ADMIN"
    assert_cost_share_estimate(
        estimate,
        allowed_per_dose_cents=250_050,
        facility_per_dose_cents=0,
        per_dose_share_cents=[126_259, 43_759, 43_759, 43_759, 43_759, 43_759],
    )
    assert estimate["total_member_share_cents"] == 345_054
    assert estimate["facility_cents"] == 0


def test_medical_variant_adds_a_flat_facility_fee_to_every_dose():
    """On the medical benefit a flat facility fee rides on every dose.

    PRD §3.7: "`facility_per_dose_cents` is the plan's `medical_facility_fee_cents`,
    charged on **every** dose and never absorbed by the deductible — it sits
    outside the waterfall entirely."

    Design: Difficulty/dual_variant_calc/cost_share_channel_variant_divergence_pharmacy_vs_medical
    """
    _scenario, _sc_episode, iv_episode = _two_channel_practice()

    assert iv_episode["benefit_channel"] == "MEDICAL"
    assert iv_episode["site_of_care"] == "AMBULATORY_INFUSION_CENTER"

    estimate = _estimate(iv_episode["id"])

    assert estimate["benefit_channel"] == "MEDICAL"
    assert estimate["site_of_care"] == "AMBULATORY_INFUSION_CENTER"
    assert_cost_share_estimate(
        estimate,
        allowed_per_dose_cents=250_050,
        facility_per_dose_cents=12_500,
        per_dose_share_cents=[138_759, 56_259, 56_259, 56_259, 56_259, 56_259],
    )
    assert estimate["total_member_share_cents"] == 420_054
    assert estimate["facility_cents"] == 75_000


def test_the_two_channel_variants_diverge_by_the_whole_facility_fee():
    """The same acquisition cost on two channels differs by six facility fees.

    PRD §3.7: "Two amounts feed the waterfall and both come from the variant that
    the episode's frozen `benefit_channel` selects."

    Design: Difficulty/dual_variant_calc/cost_share_channel_variant_divergence_pharmacy_vs_medical
    """
    _scenario, sc_episode, iv_episode = _two_channel_practice()

    sc_estimate = _estimate(sc_episode["id"])
    iv_estimate = _estimate(iv_episode["id"])

    assert sc_estimate["allowed_per_dose_cents"] == iv_estimate["allowed_per_dose_cents"] == 250_050
    assert sc_estimate["total_member_share_cents"] == 345_054
    assert iv_estimate["total_member_share_cents"] == 420_054
    assert (
        iv_estimate["total_member_share_cents"] - sc_estimate["total_member_share_cents"]
        == 75_000
    ), "the whole divergence is the flat facility fee charged on all six doses"
    assert sc_estimate["benefit_channel"] != iv_estimate["benefit_channel"]
    assert sc_estimate["site_of_care"] != iv_estimate["site_of_care"]


# ---------------------------------------------------------------------------
# combinatorial_formula /
# per_dose_rounding_then_sum_pins_medical_cost_share_total
# ---------------------------------------------------------------------------
def _infliximab_episode():
    """Infliximab (IV, 250050 cents, 150 minutes) on Meridian PPO — coinsurance
    0.175, deductible 100000, facility fee 12500, PREFER_AMBULATORY — with one
    `PLANNED` episode for one patient."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = planned_episode()
    return scenario, scenario.episode


def test_the_deductible_is_consumed_in_ascending_dose_order():
    """The deductible pool drains dose by dose and is never replenished.

    PRD §3.7: "For each dose in turn, the amount of deductible applied to that
    dose is the smaller of the pool that is left and `allowed_per_dose_cents`,
    and the pool is reduced by that amount."

    Design: Difficulty/combinatorial_formula/per_dose_rounding_then_sum_pins_medical_cost_share_total
    """
    _scenario, episode = _infliximab_episode()

    estimate = _estimate(episode["id"])

    assert estimate["deductible_applied_cents"] == 100_000, (
        "the whole 100000 pool is absorbed by dose one and nothing is left for dose two"
    )
    assert estimate["per_dose_share_cents"][0] == 138_759
    assert all(share == 56_259 for share in estimate["per_dose_share_cents"][1:])
    assert estimate["per_dose_share_cents"][0] != estimate["per_dose_share_cents"][1], (
        "dose one carries the deductible and later doses do not"
    )


def test_coinsurance_is_rounded_once_per_dose_then_summed():
    """Rounding per dose and then summing pins 245054, not 245053.

    PRD §3.7: "This rounding discipline is mandatory and not a matter of
    implementation taste: the coinsurance is rounded once per dose and the rounded
    per-dose figures are then summed."

    Design: Difficulty/combinatorial_formula/per_dose_rounding_then_sum_pins_medical_cost_share_total
    """
    _scenario, episode = _infliximab_episode()

    estimate = _estimate(episode["id"])

    assert_cents(estimate["coinsurance_cents"], "coinsurance_cents")
    assert estimate["coinsurance_cents"] == 245_054, (
        "26259 for dose one plus 43759 for each of five later doses is 245054, got "
        f"{estimate['coinsurance_cents']}"
    )
    assert estimate["coinsurance_cents"] != 245_053, (
        "245053 is the forbidden sum-then-round answer"
    )
    assert estimate["facility_cents"] == 75_000
    assert (
        estimate["deductible_applied_cents"]
        + estimate["coinsurance_cents"]
        + estimate["facility_cents"]
        == estimate["total_member_share_cents"]
    )


def test_the_medical_total_over_six_doses_is_pinned_at_420054():
    """The whole waterfall over six doses sums to 420054 cents.

    PRD §3.7: "Accumulating unrounded coinsurance across doses and rounding only
    the total is wrong and differs from the correct answer by one or more cents."

    Design: Difficulty/combinatorial_formula/per_dose_rounding_then_sum_pins_medical_cost_share_total
    """
    _scenario, episode = _infliximab_episode()

    estimate = _estimate(episode["id"])

    assert_cost_share_estimate(
        estimate,
        allowed_per_dose_cents=250_050,
        facility_per_dose_cents=12_500,
        per_dose_share_cents=[138_759, 56_259, 56_259, 56_259, 56_259, 56_259],
    )
    assert estimate["total_member_share_cents"] == 420_054
    assert estimate["total_member_share_cents"] != 420_053, (
        "420053 is the forbidden sum-then-round answer"
    )
