"""Cancellation-exposure and gross-up dual-variant behaviour (PRD §3.5, §3.9)."""
from test_helpers import *  # noqa: F401,F403

# ── The §3.5 worked example, verbatim ────────────────────────────────────────
# 12 rooms x 5 nights at 38500 cents, attrition_allowance_bp 2000,
# force_majeure_clause STANDARD, three milestones summing to the contract value.
EXPOSURE_CONTRACT_TERMS = {
    "room_block_count": 12,
    "contracted_nights": 5,
    "stay_start_at": "2026-11-08T00:00:00Z",
    "nightly_rate_cents": 38500,
    "attrition_allowance_bp": 2000,
}
EXPOSURE_MILESTONES = [
    {"sequence": 1, "due_at": "2026-08-15T00:00:00Z", "amount_cents": 577500,
     "refundable_bp": 10000},
    {"sequence": 2, "due_at": "2026-09-15T00:00:00Z", "amount_cents": 577500,
     "refundable_bp": 5000},
    {"sequence": 3, "due_at": "2026-10-15T00:00:00Z", "amount_cents": 1155000,
     "refundable_bp": 0},
]
# A seat inside the stay window 2026-11-08 .. 2026-11-13: five room-nights each.
FIVE_NIGHT_SEAT = {
    "arrival_date": "2026-11-08T00:00:00Z",
    "departure_date": "2026-11-13T00:00:00Z",
    "rooms": 1,
}
LISBON = {"per_person_cost_cents": 431757, "risk_score": 35}

# The two rungs of the §3.2 ladder whose committed costs the PRD pins.
GOLD_TIER = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150000000,
    "budget_per_qualifier_cents": 1600000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40000,
    "service_load_bp": 800,
}
PLATINUM_TIER = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250000000,
    "budget_per_qualifier_cents": 2500000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 150000,
    "service_load_bp": 1275,
}


def _executed_contract_with_schedule(
    exposure_basis,
    milestone_specs=None,
    force_majeure_clause="STANDARD",
    pay_sequences=(1, 2),
):
    """An EXECUTED 12x5 hotel contract carrying its deposit schedule."""
    terms = dict(EXPOSURE_CONTRACT_TERMS)
    terms["force_majeure_clause"] = force_majeure_clause
    terms["exposure_basis"] = exposure_basis
    return setup_contract_with_schedule(
        milestone_specs=[dict(spec) for spec in (milestone_specs or EXPOSURE_MILESTONES)],
        contract_overrides=terms,
        program_overrides={"budget_total_cents": 5000000},
        destination_overrides=dict(LISBON),
        execute=True,
        pay_sequences=list(pay_sequences),
    )


def _confirm_ten_room_nights(base):
    """Two WINNER seats CONFIRMED for five room-nights each (confirmed == 10)."""
    base = setup_registration_open_program(
        contracted=base, num_qualifiers=2, gross_up_policy="FULL_GROSS_UP"
    )
    for qualifier in base["qualifiers"]:
        enrol_and_confirm(base, qualifier, registration_overrides=dict(FIVE_NIGHT_SEAT))
    base["contract"] = read_contract(base["contract"]["id"])
    base["program"] = read_program(base["program"]["id"])
    return base


def _read_projection(contract_id):
    return validate_success(
        api_client.get_exposure_projection(
            contract_id, TEST_USERS["contract_approver_headers"]
        )
    )


def test_exposure_projection_reports_both_variants_with_attrition_binding():
    """Both exposure variants appear in one body; ATTRITION_BASIS is binding.

    PRD §3.5: "with the logical clock at 2026-09-20 the attrition variant yields
    1463000 cents and the deposit-forfeiture variant yields 1732500 cents."

    Design: Difficulty/dual_variant_calc/cancellation_exposure_attrition_vs_deposit_forfeiture_divergence
    """
    base = _confirm_ten_room_nights(_executed_contract_with_schedule("ATTRITION_BASIS"))
    set_logical_clock("2026-09-20T00:00:00Z")

    contract = base["contract"]
    assert contract["status"] == "EXECUTED"
    assert contract["room_nights_blocked"] == 60
    assert contract["room_nights_confirmed"] == 10
    assert_room_nights_conserved(contract)

    projection = _read_projection(contract["id"])
    assert projection["contract_id"] == contract["id"]
    assert projection["contract_value_cents"] == 2310000
    assert projection["room_nights_blocked"] == 60
    assert projection["room_nights_confirmed"] == 10
    assert projection["attrition_floor_room_nights"] == 48
    assert projection["shortfall_room_nights"] == 38
    # Variant A — the room-night shortfall priced at the nightly rate.
    assert projection["attrition_basis_cents"] == 1463000
    # Variant B — the same milestone set walked in ascending sequence order.
    assert projection["deposit_pre_relief_cents"] == 2310000
    assert projection["force_majeure_relief_bp"] == 2500
    assert projection["deposit_forfeiture_basis_cents"] == 1732500
    # The two variants genuinely diverge on identical stored data.
    assert (
        projection["deposit_forfeiture_basis_cents"] - projection["attrition_basis_cents"]
        == 269500
    )
    assert projection["binding_basis"] == "ATTRITION_BASIS"
    assert projection["binding_exposure_cents"] == 1463000
    assert projection["binding_exposure_cents"] != 1732500


def test_deposit_forfeiture_basis_binds_the_divergent_larger_figure():
    """The same contract data binds 1732500 when exposure_basis is the deposit one.

    PRD §3.5: "The answer is deliberately computed two entirely different ways
    from the same contract, the same milestone set and the same logical clock,
    and which of the two is binding is a commercial term negotiated on the
    contract itself as `exposure_basis`."

    Design: Difficulty/dual_variant_calc/cancellation_exposure_attrition_vs_deposit_forfeiture_divergence
    """
    base = _confirm_ten_room_nights(
        _executed_contract_with_schedule("DEPOSIT_FORFEITURE_BASIS")
    )
    set_logical_clock("2026-09-20T00:00:00Z")

    projection = _read_projection(base["contract"]["id"])
    # Both figures are still reported side by side, unchanged by the basis flag.
    assert projection["contract_value_cents"] == 2310000
    assert projection["shortfall_room_nights"] == 38
    assert projection["attrition_basis_cents"] == 1463000
    assert projection["deposit_pre_relief_cents"] == 2310000
    assert projection["force_majeure_relief_bp"] == 2500
    assert projection["deposit_forfeiture_basis_cents"] == 1732500
    # Only the binding selection moved, and it moved to the other number.
    assert projection["binding_basis"] == "DEPOSIT_FORFEITURE_BASIS"
    assert projection["binding_exposure_cents"] == 1732500
    assert projection["binding_exposure_cents"] != 1463000
    assert (
        projection["binding_exposure_cents"] - projection["attrition_basis_cents"]
        == 269500
    )


def test_deposit_forfeiture_matures_a_milestone_due_at_the_logical_instant():
    """A milestone due exactly at the logical instant has matured; one day earlier it has not.

    PRD §3.5: "A milestone whose `due_at` is at or before the current logical
    instant has **matured**, and its whole `amount_cents` is added, because
    nothing about a matured milestone is recoverable. A milestone whose `due_at`
    is still in the future contributes only its non-refundable share: its
    `amount_cents` multiplied by the difference between 10000 and its
    `refundable_bp`, divided by 10000, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/cancellation_exposure_attrition_vs_deposit_forfeiture_divergence
    """
    base = _executed_contract_with_schedule("DEPOSIT_FORFEITURE_BASIS")
    contract_id = base["contract"]["id"]

    # Clock exactly on sequence 2's due_at: "at or before" means matured.
    set_logical_clock("2026-09-15T00:00:00Z")
    matured = _read_projection(contract_id)
    assert matured["deposit_pre_relief_cents"] == 2310000
    assert matured["force_majeure_relief_bp"] == 2500
    assert matured["deposit_forfeiture_basis_cents"] == 1732500
    assert matured["binding_exposure_cents"] == 1732500

    # One day earlier sequence 2 is unmatured: only its 5000 bp non-refundable
    # share counts (577500 -> 288750), so the pre-relief total is 2021250 and the
    # relieved total is round_half_up(2021250 * 7500 / 10000) == 1515938.
    set_logical_clock("2026-09-14T00:00:00Z")
    unmatured = _read_projection(contract_id)
    assert unmatured["deposit_pre_relief_cents"] == 2021250
    assert unmatured["deposit_forfeiture_basis_cents"] == 1515938
    assert unmatured["binding_basis"] == "DEPOSIT_FORFEITURE_BASIS"
    assert unmatured["binding_exposure_cents"] == 1515938
    assert unmatured["binding_exposure_cents"] != matured["binding_exposure_cents"]
    # The attrition side reads no milestone at all, so it did not move.
    assert unmatured["attrition_basis_cents"] == matured["attrition_basis_cents"]


def test_attrition_variant_ignores_the_deposit_schedule_and_force_majeure_clause():
    """A different schedule and an EXPANDED clause leave attrition_basis_cents at 1463000.

    PRD §3.5: "Its figure, `attrition_basis_cents`, is the
    `shortfall_room_nights` from the room-night ledger of §3.7 multiplied by the
    contract's `nightly_rate_cents`. The deposit schedule and the force-majeure
    clause are ignored entirely under this variant."

    Design: Difficulty/dual_variant_calc/cancellation_exposure_attrition_vs_deposit_forfeiture_divergence
    """
    base = _confirm_ten_room_nights(
        _executed_contract_with_schedule(
            "ATTRITION_BASIS",
            milestone_specs=[
                {"sequence": 1, "due_at": "2026-10-15T00:00:00Z",
                 "amount_cents": 100000, "refundable_bp": 0},
            ],
            force_majeure_clause="EXPANDED",
            pay_sequences=(),
        )
    )
    set_logical_clock("2026-09-20T00:00:00Z")

    projection = _read_projection(base["contract"]["id"])
    assert projection["shortfall_room_nights"] == 38
    # Identical to the STANDARD-clause, full-schedule contract of the first test.
    assert projection["attrition_basis_cents"] == 1463000
    # The deposit side did move, which is what makes the two variants distinct.
    assert projection["force_majeure_relief_bp"] == 6000
    assert projection["deposit_pre_relief_cents"] == 100000
    assert projection["deposit_forfeiture_basis_cents"] == 40000
    assert projection["binding_basis"] == "ATTRITION_BASIS"
    assert projection["binding_exposure_cents"] == 1463000
    # The relief never touches the attrition figure: 1463000 * 4000 / 10000.
    assert projection["binding_exposure_cents"] != 585200
    assert projection["binding_exposure_cents"] != 40000


def _travelled_winner(gross_up_policy, tier_overrides, qualifier_overrides=None):
    """A RECONCILED program whose single winner has TRAVELLED on a known base."""
    return setup_reconciled_program(
        num_qualifiers=1,
        gross_up_policy=gross_up_policy,
        qualifier_overrides=dict(qualifier_overrides or {}),
        program_overrides={"budget_total_cents": 5000000},
        tier_overrides=dict(tier_overrides),
        destination_overrides=dict(LISBON),
    )


def _draft_report(qualifier_id, tax_year=2026):
    return validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(qualifier_id, tax_year),
            TEST_USERS["tax_officer_headers"],
        ),
        expected_status=201,
    )


def test_flat_supplemental_gross_up_is_linear_federal_only():
    """A FLAT_SUPPLEMENTAL report grosses up 443198 by 2200 bp only.

    PRD §3.9: "With `FLAT_SUPPLEMENTAL`, the employer covers only the federal
    supplemental rate of 2200 basis points and leaves the social-insurance and
    state components to the winner. `combined_rate_bp` is 2200, and
    `gross_up_cents` is `award_value_cents` multiplied by 2200, divided by 10000,
    rounded half up to a whole cent. The computation is linear and
    non-iterative."

    Design: Difficulty/dual_variant_calc/gross_up_flat_supplemental_variant_on_travelled_winner
    """
    base = _travelled_winner("FLAT_SUPPLEMENTAL", GOLD_TIER)
    qualifier = base["qualifier"]
    assert base["program"]["gross_up_policy"] == "FLAT_SUPPLEMENTAL"
    assert base["program"]["gross_up_policy_locked"] is True
    assert qualifier["award_status"] == "TRAVELLED"
    assert qualifier["committed_cost_cents"] == 521409
    assert qualifier["taxable_award_cents"] == 443198
    assert qualifier["tax_status"] == "PENDING_REPORT"

    report = _draft_report(qualifier["id"])
    assert_tax_award_report(report)
    assert report["status"] == "DRAFT"
    assert report["gross_up_method"] == "FLAT_SUPPLEMENTAL"
    assert report["award_value_cents"] == 443198
    assert report["combined_rate_bp"] == 2200
    assert report["gross_up_cents"] == 97504
    assert report["reported_value_cents"] == 540702
    assert_reported_value_identity(report)
    # Not the FULL_GROSS_UP inverse-withholding answer on the identical base.
    assert report["gross_up_cents"] != 214854
    assert report["reported_value_cents"] != 658052
    # Drafting neither files nor moves any total.
    assert read_qualifier(qualifier["id"])["tax_status"] == "PENDING_REPORT"
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 0


def test_flat_supplemental_gross_up_omits_the_tiered_state_rate():
    """An award of 783500 cents sits in the middle state tier, yet FLAT stays at 2200 bp.

    PRD §3.9: "With `FLAT_SUPPLEMENTAL`, the employer covers only the federal
    supplemental rate of 2200 basis points and leaves the social-insurance and
    state components to the winner."

    Design: Difficulty/dual_variant_calc/gross_up_flat_supplemental_variant_on_travelled_winner
    """
    base = _travelled_winner("FLAT_SUPPLEMENTAL", PLATINUM_TIER, {"guest_count": 1})
    qualifier = base["qualifier"]
    # The §3.2 pinned commitment: 486806 + 269848 + 15111 + 150000 == 921765,
    # less the 1500 bp business-purpose exclusion of 138265.
    assert qualifier["committed_cost_cents"] == 921765
    assert qualifier["taxable_award_cents"] == 783500

    report = _draft_report(qualifier["id"])
    assert report["gross_up_method"] == "FLAT_SUPPLEMENTAL"
    assert report["award_value_cents"] == 783500
    # 783500 is at least 500000, so the state tier would be 500 bp — the flat
    # policy must not add it (2700 bp would yield 211545) nor add FICA.
    assert report["combined_rate_bp"] == 2200
    assert report["gross_up_cents"] == 172370
    assert report["gross_up_cents"] != 211545
    assert report["reported_value_cents"] == 955870
    assert_reported_value_identity(report)
    # Nor is it the FULL_GROSS_UP figure for this base.
    assert report["gross_up_cents"] != 415429


def test_full_gross_up_solves_the_inverse_withholding_equation():
    """FULL_GROSS_UP on 443198 reports 658052 at a combined 3265 bp.

    PRD §3.9: "`combined_rate_bp` is the sum of the federal supplemental 2200
    basis points, the social-insurance 765 basis points, and the tiered state
    rate — **and the state tier is keyed on the pre-gross-up
    `award_value_cents`, not on the grossed-up result**. The reported figure is
    `award_value_cents` multiplied by 10000, divided by the difference between
    10000 and `combined_rate_bp`, rounded half up to a whole cent;
    `gross_up_cents` is that reported figure less `award_value_cents`."

    Design: Difficulty/dual_variant_calc/gross_up_full_inverse_withholding_variant_on_travelled_winner
    """
    base = _travelled_winner("FULL_GROSS_UP", GOLD_TIER)
    qualifier = base["qualifier"]
    assert base["program"]["gross_up_policy"] == "FULL_GROSS_UP"
    assert qualifier["award_status"] == "TRAVELLED"
    assert qualifier["committed_cost_cents"] == 521409
    assert qualifier["taxable_award_cents"] == 443198

    report = _draft_report(qualifier["id"])
    assert_tax_award_report(report)
    assert report["status"] == "DRAFT"
    assert report["gross_up_method"] == "FULL_GROSS_UP"
    assert report["award_value_cents"] == 443198
    # 443198 is below 500000, so the state tier is 300 bp: 2200 + 765 + 300.
    assert report["combined_rate_bp"] == 3265
    assert report["reported_value_cents"] == 658052
    assert report["gross_up_cents"] == 214854
    assert_reported_value_identity(report)
    # Keying the state tier on the grossed-up 658052 would select 500 bp and
    # report 678191 — the circular ordering the PRD forbids.
    assert report["combined_rate_bp"] != 3465
    assert report["reported_value_cents"] != 678191
    # And it diverges from the FLAT_SUPPLEMENTAL variant on the same base by
    # exactly 214854 - 97504 == 117350 cents.
    assert report["gross_up_cents"] - 97504 == 117350
    assert report["reported_value_cents"] != 540702


def test_full_gross_up_state_tier_follows_the_pre_gross_up_award_value():
    """An award value of 783500 selects the 500 bp middle state rung, giving 3465 bp.

    PRD §3.9: "A tiered state supplemental rate underlies it: 300 basis points
    when the award value is below 500000 cents, 500 basis points when it is at
    least 500000 but below 1500000 cents, and 700 basis points when it is at or
    above 1500000 cents."

    Design: Difficulty/dual_variant_calc/gross_up_full_inverse_withholding_variant_on_travelled_winner
    """
    base = _travelled_winner("FULL_GROSS_UP", PLATINUM_TIER, {"guest_count": 1})
    qualifier = base["qualifier"]
    assert qualifier["committed_cost_cents"] == 921765
    assert qualifier["taxable_award_cents"] == 783500

    report = _draft_report(qualifier["id"])
    assert report["gross_up_method"] == "FULL_GROSS_UP"
    assert report["award_value_cents"] == 783500
    # 2200 + 765 + 500, the middle state rung keyed on 783500.
    assert report["combined_rate_bp"] == 3465
    assert report["combined_rate_bp"] != 3265
    # round_half_up(783500 * 10000 / 6535) == 1198929.
    assert report["reported_value_cents"] == 1198929
    assert report["gross_up_cents"] == 415429
    assert_reported_value_identity(report)
    # Holding the state tier at 300 bp would report 1163326 instead.
    assert report["reported_value_cents"] != 1163326
    # Nor is it the linear FLAT_SUPPLEMENTAL answer for this base.
    assert report["gross_up_cents"] != 172370
