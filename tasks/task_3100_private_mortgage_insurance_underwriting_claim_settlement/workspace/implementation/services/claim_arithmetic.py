"""Claim arithmetic and settlement option pricing.

Implements calculations `claim_amount_computation` and
`settlement_option_computation` from SCAFFOLD section 1.3 and the prose of
PRD 3.8 / 3.9.

Precision (PRD 3.8, last paragraph): exact integer arithmetic where every
multiplication that could produce a fraction of a cent is floored and no step is
rounded half up - with one exception, the coverage credit inside the DIL
waterfall, which PRD 3.9 / the scaffold pin to round_half_up.

Evaluation order is normative: the coverage ceiling is applied to the recoverable
amount FIRST and only the ceilinged figure is curtailed.
"""

from common import d, floor_int, round_half_up_int

DEDUCTIBLE_RATE = {
    "A": d("0.05"),
    "B": d("0.10"),
    "C": d("0.15"),
    "D": d("0.20"),
}

INTEREST_CAP_RATIO = d("0.15")
ADVANCES_CAP_RATIO = d("1.10")

SETTLEMENT_OPTION_KINDS = ("CASH", "THIRD_PARTY_SALE", "DEED_IN_LIEU", "DIL")

# SCAFFOLD settlement_option_computation constant.
THIRD_PARTY_MIN_PROCEEDS_RATIO = d("0.85")


def deductible_rate_for(credit_grade):
    return DEDUCTIBLE_RATE.get(credit_grade, DEDUCTIBLE_RATE["D"])


def curtailment_rate_for(policy, underwriting_path):
    """Taken from the loan's underwriting path, frozen on the claim at approval."""
    if underwriting_path == "DELEGATED":
        return policy["delegated_curtailment_rate"]
    return policy["nondelagated_curtailment_rate"]


def coverage_ceiling_basis_cents(loan):
    """PRD 3.9: the origination appraised value while verified_property_value_cents
    is null, and the verified value once an independent validation report has
    established it."""
    if loan.get("verified_property_value_cents") is None:
        return loan["origination_property_value_cents"]
    return loan["verified_property_value_cents"]


def compute_claim_arithmetic(claim, loan, policy, curtailment_rate, deductible_rate):
    """Returns every derived claim quantity for the state as it stands now."""
    unpaid_principal = claim["unpaid_principal_cents"]
    gross = claim["gross_proceeds_cents"]
    expenses = claim["expenses_of_sale_cents"]

    permitted_interest = min(
        claim["accrued_interest_cents"], floor_int(d(unpaid_principal) * INTEREST_CAP_RATIO)
    )
    permitted_advances = min(
        claim["allowable_advances_cents"], floor_int(d(unpaid_principal) * ADVANCES_CAP_RATIO)
    )
    net_unpaid_balance = unpaid_principal + permitted_interest + permitted_advances

    net_proceeds = max(0, gross - expenses)
    recoverable_amount = max(0, net_unpaid_balance - net_proceeds)

    coverage_ceiling = loan["coverage_base_upb_cents"]
    covered_claim_amount = min(recoverable_amount, coverage_ceiling)

    curtailed = floor_int(d(covered_claim_amount) * d(curtailment_rate))
    post_curtailment = covered_claim_amount - curtailed

    claim_deductible = floor_int(d(post_curtailment) * d(deductible_rate))
    net_claim_amount = post_curtailment - claim_deductible

    return {
        "permitted_interest_cents": permitted_interest,
        "permitted_advances_cents": permitted_advances,
        "net_unpaid_balance_cents": net_unpaid_balance,
        "recoverable_amount_cents": recoverable_amount,
        "coverage_ceiling_cents": coverage_ceiling,
        "covered_claim_amount_cents": covered_claim_amount,
        "post_curtailment_cents": post_curtailment,
        "claim_deductible_cents": claim_deductible,
        "net_claim_amount_cents": net_claim_amount,
    }


def compute_settlement_amounts(claim, loan, policy, arithmetic):
    """The four priced options for the claim's current arithmetic."""
    net_claim = arithmetic["net_claim_amount_cents"]
    net_unpaid = arithmetic["net_unpaid_balance_cents"]
    ceiling = arithmetic["coverage_ceiling_cents"]

    cash = net_claim
    deed_in_lieu = net_claim

    # THIRD_PARTY_SALE: the net claim amount less the policy's basis-point floor.
    floor_bps = policy["min_third_party_net_bps"]
    share = floor_int(d(net_claim) * d(floor_bps) / 10000)
    third_party_sale = max(0, net_claim - share)

    # DIL: the coverage-percent reinstatement credit through the recovery waterfall.
    net_proceeds = max(0, claim["gross_proceeds_cents"] - claim["expenses_of_sale_cents"])
    basis = coverage_ceiling_basis_cents(loan)
    coverage_credit = round_half_up_int(d(basis) * d(loan["coverage_percent"]) / 100)
    total_recoveries = min(net_unpaid, net_proceeds + coverage_credit)
    dil = min(ceiling, max(0, net_unpaid - total_recoveries))

    return {
        "CASH": cash,
        "THIRD_PARTY_SALE": third_party_sale,
        "DEED_IN_LIEU": deed_in_lieu,
        "DIL": dil,
    }


def third_party_sale_threshold(net_claim_amount):
    """floor(0.85 * net claim amount) - the proceeds floor a THIRD_PARTY_SALE must clear."""
    return floor_int(d(net_claim_amount) * THIRD_PARTY_MIN_PROCEEDS_RATIO)


def net_proceeds_of(claim):
    return max(0, claim["gross_proceeds_cents"] - claim["expenses_of_sale_cents"])