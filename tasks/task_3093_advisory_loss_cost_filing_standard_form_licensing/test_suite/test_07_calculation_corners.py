"""Calculation corners: royalty accrual, overlap input-set filtering, and
quality-score constants (PRD §3.2, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_finding,
    begin_edit,
    dispose,
    make_agreement,
    make_effective_filing,
    make_form_with_variants,
    make_insurer,
    make_submission,
    setup_adoption_scenario,
    setup_insurer_with_active_plan,
    validate_success,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


def test_royalty_accrual_computed_read(api):
    """PRD §3.4: "Royalties accrue on read. The royalty view for an agreement
    sums the `authorized_premium_cents` of the insurer's `AUTHORIZED`
    adoptions whose filings became `EFFECTIVE` while the agreement was
    `ACTIVE`, multiplies that sum by the agreement's `royalty_rate_bps`
    divided by 10000, and rounds half-up once to integer cents, returning the
    result as `royalty_due_cents`."

    Design: Corner/calculations/royalty_accrual_computed_read
    """
    scenario = setup_adoption_scenario(
        multiplier_pct=125,
        filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
        agreement_overrides={"royalty_rate_bps": 250},
    )
    adoption = validate_success(api.authorize_adoption(scenario["adoption"]["id"], ADMIN))
    assert adoption["adoption_status"] == "AUTHORIZED"
    assert adoption["authorized_premium_cents"] == 150000
    resp = api.get_royalty(scenario["agreement"]["id"], ADMIN)
    royalty = validate_success(resp)
    assert royalty["royalty_due_cents"] == 3750


def test_variant_window_overlap_input_set_excludes_blocked_and_retired(api):
    """PRD §3.5: "Sibling variants in `BLOCKED` review status or `RETIRED`
    publication status are excluded from the comparison set."
    PRD §3.5: "On the review dimension, a `BureauActuary` clears a variant —
    moving `review_status` from `PENDING` to `CLEARED` — only while its
    `publication_status` is still `UNPUBLISHED` and only when no sibling
    variant of the same form and same `state_code` has a conflicting usability
    window."

    Design: Corner/calculations/variant_window_overlap_input_set_excludes_blocked_and_retired
    """
    form, variants = make_form_with_variants([
        {"state_code": "CW", "effective_from": "2026-01-01T00:00:00Z",
         "effective_to": "2026-12-01T00:00:00Z"},
        {"state_code": "CW", "effective_from": "2026-03-01T00:00:00Z",
         "effective_to": "2026-09-01T00:00:00Z"},
    ])
    v1, v2 = variants
    validate_success(api.block_variant(v1["id"], ACTUARY))
    resp = api.clear_variant(v2["id"], ACTUARY)
    cleared = validate_success(resp)
    assert cleared["review_status"] == "CLEARED"
    v1_after = validate_success(api.get_variant(v1["id"], ADMIN))
    assert v1_after["review_status"] == "BLOCKED"


def test_quality_score_constants_applied_error_and_warning_penalties(api):
    """PRD §3.2: "For each submission, compute its points as 10000 minus 200
    per error finding minus 50 per warning finding, floored at zero so no
    single submission contributes negative points."
    PRD §3.2: "The score is the weighted average — the sum over submissions of
    points times weight, divided by the sum of the weights — rounded half-up
    to an integer number of basis points exactly once at the end, and finally
    clamped into the 0 to 10000 range."

    Design: Corner/calculations/quality_score_constants_applied_error_and_warning_penalties
    """
    insurer, plan = setup_insurer_with_active_plan()
    sub = make_submission(insurer["id"], plan["id"], record_count=10)
    begin_edit(sub["id"])
    add_finding(sub["id"], severity="ERROR", edit_code="E-1")
    add_finding(sub["id"], severity="ERROR", edit_code="E-2")
    add_finding(sub["id"], severity="WARNING", edit_code="W-1")
    disposed = dispose(sub["id"])
    assert disposed["submission_status"] == "REJECTED"
    insurer_after = validate_success(api.get_insurer(insurer["id"], ADMIN))
    assert insurer_after["quality_score_bps"] == 9550
