"""Corner queue B: mixed-manufacturer variant selection and remedy split."""
from test_helpers import (
    adjudicate,
    file_claim_with_photos,
    get_remedy,
    setup_active_registration,
)


def test_mixed_manufacturer_forces_standard_schedule_and_zero_labor(api, program_admin_headers, claimant_headers):
    """PRD §3.3: "On successful activation the registration ... computes
    `coverage_class`: `QUALIFYING_SYSTEM` when every required-type component has
    `manufacturer` `GAF`, and `MIXED_MANUFACTURER` when any required-type component
    is `OTHER`-manufactured." PRD §3.6 step 1: "...unless the registration's
    `coverage_class` is `MIXED_MANUFACTURER`, in which case the `STANDARD` schedule is
    forced regardless of tier." PRD §3.6 step 6: "`labor_covered_cents` is zero
    whenever the registration is `MIXED_MANUFACTURER` — mixed systems carry no labor
    coverage at all."

    Design: Corner/calculations/mixed_manufacturer_forces_standard_schedule_and_zero_labor
    """
    ctx = setup_active_registration(
        tier="GOLD", line_cents=25000, mixed_manufacturer=True,
        license_expiry="2040-01-01", insurance_expiry="2040-01-01")
    reg = ctx["registration"]
    assert reg["coverage_class"] == "MIXED_MANUFACTURER"
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=300000,
                                  file_at="2032-09-10", description="leak")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["schedule_used"] == "STANDARD"
    assert rem["material_pct"] == 50
    assert rem["material_covered_cents"] == 50000
    assert rem["labor_covered_cents"] == 0
