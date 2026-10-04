"""Seasonal assistance: intake scoring, screening and household limits."""
from test_helpers import (
    ApiErrorId,
    create_application,
    create_application_ok,
    screen_application,
    setup_assistance_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_provisional_score_uses_self_reported_income(api):
    """PRD §3.6: "The self-reported income is divided by the household size, the
    quotient floored to whole cents, and that per-member figure is divided by
    20000 cents — two hundred dollars — and floored again."
    PRD §3.6: "Because this variant reads only what the household said about
    itself and applies no deductions, a household can score below the threshold
    at intake and above it later."

    Design: Difficulty/dual_variant_calc/assistance_score_provisional_vs_final_variant
    """
    unit, _campaign, program = setup_assistance_program()
    application = create_application_ok(
        program["id"], applicant_name="Dolores Whitfield", household_size=4,
        annual_income_cents=3000000, distribution_site_unit_id=unit["id"])

    assert application["provisional_score"] == 63, "100 less floor(750000 / 20000)"
    assert application["eligibility_status"] == "SUBMITTED"
    assert application["annual_income_cents"] == 3000000


def test_final_score_applies_per_member_asset_deduction(api):
    """PRD §3.6: "an asset deduction of 150000 cents — one thousand five hundred
    dollars — is subtracted for each member of the household from the verified
    income, the result floored at zero so it can never go negative".
    PRD §3.6: "The same household can therefore score above the threshold at
    screening even when it scored below at intake".

    Design: Difficulty/dual_variant_calc/assistance_score_provisional_vs_final_variant
    """
    unit, _campaign, program = setup_assistance_program()
    application = create_application_ok(
        program["id"], applicant_name="Dolores Whitfield", household_size=4,
        annual_income_cents=3000000, distribution_site_unit_id=unit["id"])
    assert application["provisional_score"] == 63

    screened = screen_application(application["id"], verified_income_cents=3000000)
    assert screened["eligibility_score"] == 70, "100 less floor(600000 / 20000)"
    assert screened["verified_income_cents"] == 3000000
    assert screened["eligibility_score"] != application["provisional_score"]


def test_final_score_routes_application_to_eligible(api):
    """PRD §3.6: "An application scoring 65 or higher is eligible; an
    application scoring below 65 is `INELIGIBLE`, which is terminal."
    PRD §3.6: "An eligible application is made `ELIGIBLE` when the program still
    has room — that is, when its accepted count is below the `household_cap`".

    Design: Difficulty/dual_variant_calc/assistance_score_provisional_vs_final_variant
    """
    unit, _campaign, program = setup_assistance_program()
    application = create_application_ok(
        program["id"], applicant_name="Dolores Whitfield", household_size=4,
        annual_income_cents=3000000, distribution_site_unit_id=unit["id"])

    screened = screen_application(application["id"], verified_income_cents=3000000)
    assert screened["eligibility_score"] == 70
    assert screened["eligibility_status"] == "ELIGIBLE"


def test_household_size_above_twelve_rejected(api, assistance_caseworker_headers):
    """PRD §2.9: "The `household_size` is between 1 and 12 inclusive; otherwise
    `ERR_HOUSEHOLD_SIZE_INVALID` (HTTP 422)."
    PRD §3.6: "the `household_size` must be between 1 and 12 inclusive, or the
    request is refused with `ERR_HOUSEHOLD_SIZE_INVALID` (HTTP 422)."

    Design: Corner/validations/household_size_above_twelve_rejected
    """
    unit, _campaign, program = setup_assistance_program()
    resp = create_application(
        program["id"], applicant_name="Oversized Household", household_size=15,
        annual_income_cents=1000000, distribution_site_unit_id=unit["id"])
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_SIZE_INVALID)

    listed = api.list_assistance_applications(
        assistance_caseworker_headers,
        params={"program_id": program["id"], "limit": 100})
    _data, meta = validate_paginated(listed)
    assert meta["total_count"] == 0, "the rejected intake must not persist an application"
