"""
Two named calculations that read the same row and must not agree.

The claim reports margin twice from one set of figures — once on the published
benchmark cost and once on the acquisition cost of the vial actually dispensed —
and the lot reports exposure twice from one set of vials, once as financing cost
and once as expiry write-off.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assert_money_cents, assert_vial_conservation
from test_helpers import factories as f


# ==========================================================================
# claim_margin_provisional_vs_realized_diverge_on_one_claim
# ==========================================================================


def test_provisional_margin_is_costed_on_published_asp_at_claim_creation(depth, billing):
    """
    A claim cut from a 2 + 8 unit split prices its three charge lines from the
    coverage policy and costs the drug at published ASP.

    Documentation of 0.06 ml from a 0.27 ml vial at 40 mg/ml with a 1 mg billing
    unit yields 2 administered and 8 wasted units.  The commercial policy allows
    16000 cents a unit and reimburses wastage, so the drug line is 32000, the
    wastage line 128000 and the administration line 12000 — 172000 allowed in
    all.  The PRD pins the standard cost: "`standard_drug_cost_cents` is written
    as the encounter's `administered_billing_units` plus its
    `wasted_billing_units`, multiplied by the effective drug's
    `asp_cents_per_billing_unit`" — (2 + 8) * 15000 = 150000 — and
    "`provisional_margin_cents` is then the sum of `drug_allowed_cents`,
    `wastage_allowed_cents` and `admin_allowed_cents`, less
    `standard_drug_cost_cents`", so 172000 - 150000 = 22000.  At this stage
    "Both `actual_acquisition_cost_cents` and `realized_margin_cents` remain
    null".

    Design: Difficulty/dual_variant_calc/claim_margin_provisional_vs_realized_diverge_on_one_claim
    """
    depth.enc1_attested
    depth.enrollment1

    response = depth.api.create_claim(
        f.claim_payload(injection_encounter_id=depth.enc1["id"]), billing
    )
    claim = validate_success(response, 201)

    assert_money_cents(
        claim,
        "drug_billed_cents",
        "wastage_billed_cents",
        "admin_billed_cents",
        "drug_allowed_cents",
        "wastage_allowed_cents",
        "admin_allowed_cents",
        "total_allowed_cents",
        "standard_drug_cost_cents",
        "provisional_margin_cents",
    )
    assert claim["billed_billing_units"] == 10
    assert claim["drug_allowed_cents"] == 32000
    assert claim["wastage_allowed_cents"] == 128000
    assert claim["admin_allowed_cents"] == 12000
    assert claim["total_allowed_cents"] == 172000
    assert claim["standard_drug_cost_cents"] == 150000
    assert claim["provisional_margin_cents"] == 22000
    assert claim["actual_acquisition_cost_cents"] is None
    assert claim["realized_margin_cents"] is None


def test_realized_margin_is_costed_on_the_dispensed_lot_and_diverges_from_provisional(
    depth, billing
):
    """
    The same claim, fully remitted, reports a realized margin costed on the lot
    behind the administered vial, and the two figures differ by the cost-basis gap.

    The PRD pins the realized side: "`actual_acquisition_cost_cents` is set to the
    `unit_acquisition_cost_cents` of the lot behind the encounter's administered
    vial" — 132000 for this lot — and "`realized_margin_cents` is then the sum of
    `drug_paid_cents`, `wastage_paid_cents`, `admin_paid_cents`,
    `patient_responsibility_cents` and `foundation_applied_cents`, less
    `actual_acquisition_cost_cents`".  With 25600 + 102400 + 9600 paid, 14400 of
    patient responsibility and 20000 of foundation relief, that is 172000 - 132000
    = 40000 against a provisional 22000: the 18000 divergence is exactly the
    150000 benchmark cost against the 132000 paid for the vial.  "The same posting
    moves the encounter `BILLED → CLOSED`."

    Design: Difficulty/dual_variant_calc/claim_margin_provisional_vs_realized_diverge_on_one_claim
    """
    depth.enc1_attested
    depth.enrollment1
    claim = depth.claim(injection_encounter_id=depth.enc1["id"])
    provisional = claim["provisional_margin_cents"]
    depth.submit_claim(claim["id"])

    payload = dict(
        f.drug_line_paid_payload(
            drug_allowed_cents=32000,
            drug_paid_cents=25600,
            wastage_allowed_cents=128000,
            wastage_paid_cents=102400,
        )
    )
    payload.update(f.admin_line_paid_payload(admin_allowed_cents=12000, admin_paid_cents=9600))
    response = depth.api.post_remittance(claim["id"], payload, billing)
    remitted = validate_success(response, 200)

    assert remitted["drug_line_status"] == "PAID"
    assert remitted["admin_line_status"] == "PAID"
    assert remitted["total_allowed_cents"] == 172000
    assert remitted["drug_paid_cents"] + remitted["wastage_paid_cents"] + remitted[
        "admin_paid_cents"
    ] == 137600
    assert remitted["patient_responsibility_cents"] == 14400
    assert remitted["foundation_applied_cents"] == 20000
    assert remitted["actual_acquisition_cost_cents"] == 132000
    assert remitted["realized_margin_cents"] == 40000
    assert provisional == 22000
    assert remitted["realized_margin_cents"] - provisional == 18000
    assert remitted["provisional_margin_cents"] == 22000

    encounter = depth.read_encounter(depth.enc1["id"])
    assert encounter["status"] == "CLOSED"


# ==========================================================================
# lot_exposure_carrying_vs_expiration_diverge_on_one_lot
# ==========================================================================


def _second_lot(world):
    """Book a second lot of the reference product, received two weeks in."""
    return world.lot(
        drug_id=world.drug_ref["id"],
        lot_number="RX-2199",
        expiration_date="2026-09-15T00:00:00Z",
        received_date="2026-07-15T00:00:00Z",
        unit_acquisition_cost_cents=129000,
        vials_received=3,
    )


def test_carrying_basis_accrues_financing_cost_and_ignores_the_expiry_date(depth, tech):
    """
    The `CARRYING` read of a three-vial lot held 47 days reports the financing
    cost of the shelved capital and nothing about expiry.

    The PRD pins each term: "`days_held` is the whole number of days from the
    lot's `received_date` to the logical clock, truncated downward" — 2026-07-15
    to 2026-08-31 is 47 — and "Only vials in `IN_STOCK` are counted ... that count
    is reported as `unconsumed_vials`, and multiplying it by
    `unit_acquisition_cost_cents` gives `unconsumed_value_cents`", so 3 * 129000 =
    387000.  "The accrual itself takes that same unconsumed value, applies the
    practice's annual financing rate of 2000 basis points ... multiplies by
    `days_held`, divides by a 365-day year, and rounds the result half up to whole
    cents exactly once at the very end rather than at any intermediate step":
    387000 * 0.2 * 47 / 365 = 9966.57... which rounds to 9967.  "On this basis
    `projected_burn_vials` and `at_risk_vials` are both reported as 0."

    Design: Difficulty/dual_variant_calc/lot_exposure_carrying_vs_expiration_diverge_on_one_lot
    """
    depth.enc1_documented
    lot = _second_lot(depth)
    depth.set_clock("2026-08-31T00:00:00Z")

    response = depth.api.get_drug_lot_exposure(
        lot["id"], tech, f.exposure_params(basis="CARRYING")
    )
    exposure = validate_success(response, 200)

    assert exposure["drug_lot_id"] == lot["id"]
    assert exposure["basis"] == "CARRYING"
    assert exposure["days_held"] == 47
    assert exposure["unconsumed_vials"] == 3
    assert exposure["unconsumed_value_cents"] == 387000
    assert exposure["exposure_cents"] == 9967
    assert exposure["projected_burn_vials"] == 0
    assert exposure["at_risk_vials"] == 0


def test_expiration_basis_writes_off_every_vial_the_burn_rate_cannot_reach(depth, tech):
    """
    The `EXPIRATION` read of the same lot at the same instant reports 387000 of
    at-risk acquisition value, and neither read leaves a trace on the row.

    One vial of this product was administered at 2026-08-01T09:00:00Z, inside the
    window the PRD defines as beginning "at the logical clock moved back thirty
    days, includes that lower endpoint, and runs up to but does *not* include the
    clock itself", so the trailing count is 1 and "Dividing that count by thirty
    gives a per-day burn rate carried as an exact rational value with no
    rounding".  "Days remaining are the whole days from the logical clock to the
    lot's `expiration_date`" — 2026-08-31 to 2026-09-15 is 15 — and "Multiplying
    the burn rate by the days remaining and taking the floor gives the projected
    consumable count", so 15/30 floors to 0 and all three unconsumed vials are at
    risk: "Multiplying the unusable count by `unit_acquisition_cost_cents` gives
    `exposure_cents` on this basis."  The read is inert — "The read persists
    nothing" — so `carrying_cost_accrued_cents` is still the 0 it was booked with.

    Design: Difficulty/dual_variant_calc/lot_exposure_carrying_vs_expiration_diverge_on_one_lot
    """
    depth.enc1_documented
    lot = _second_lot(depth)
    depth.set_clock("2026-08-31T00:00:00Z")

    carrying = validate_success(
        depth.api.get_drug_lot_exposure(lot["id"], tech, f.exposure_params(basis="CARRYING")), 200
    )
    response = depth.api.get_drug_lot_exposure(
        lot["id"], tech, f.exposure_params(basis="EXPIRATION")
    )
    exposure = validate_success(response, 200)

    assert exposure["basis"] == "EXPIRATION"
    assert exposure["days_held"] == 47
    assert exposure["projected_burn_vials"] == 0
    assert exposure["unconsumed_vials"] == 3
    assert exposure["unconsumed_value_cents"] == 387000
    assert exposure["at_risk_vials"] == 3
    assert exposure["exposure_cents"] == 387000
    assert exposure["exposure_cents"] != carrying["exposure_cents"]

    row = depth.read_lot(lot["id"])
    assert row["carrying_cost_accrued_cents"] == 0
    assert row["last_swept_at"] is None
    assert row["status"] == "AVAILABLE"
    assert_vial_conservation(row, 3)
