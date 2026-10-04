"""GPO rebate claims: accrual tiers, dual-variant amounts, dispute cycle,
closed-interval period overlap."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_rebate_claim,
    create_facility,
    create_rebate_claim,
    create_rebate_claim_payload,
    get_success_data,
    record_claim_event,
    validate_error,
    validate_success,
)

GPO = TEST_USERS["gpo_analyst_headers"]


def test_claim_create_computes_provisional_only(api):
    """PRD §3.7: "The `provisional_amount_cents` stored at creation is simply
    the eligible volume times that base rate, rounded half up to whole cents —
    no private-label bonus, no compliance multiplier — and the claim starts in
    `ACCRUED` status." 250000 cents at the 0.01 tier -> 2500.

    Design: Corner/entities/claim_create_computes_provisional_only
    """
    facility = create_facility()
    claim = create_rebate_claim(facility["id"], eligible_purchase_cents=250000)
    assert_rebate_claim(claim)
    assert claim["provisional_amount_cents"] == 2500
    assert claim.get("final_amount_cents") is None
    assert claim["status"] == "ACCRUED"


def test_claim_period_equal_dates_422(api):
    """PRD §3.7: "The period must be well formed: `period_end` strictly after
    `period_start`, otherwise `ERR_CLAIM_PERIOD_INVALID` (HTTP 422)."

    Design: Corner/validations/claim_period_end_before_start_rejected
    """
    facility = create_facility()
    resp = api.create_rebate_claim(
        create_rebate_claim_payload(
            facility["id"], period_start="2026-03-31", period_end="2026-03-31"
        ),
        headers=GPO,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_PERIOD_INVALID.value, 422)


def test_rebate_tier_boundary_inclusive(api):
    """PRD §3.7: "at least 1000000 cents earns 0.03 — so a period of exactly
    1000000 cents selects the 0.03 tier; at least 500000 cents earns 0.02".
    Exactly 1000000 -> 30000; 999999 -> round_half_up(19999.98) = 20000.

    Design: Corner/calculations/rebate_tier_boundary_inclusive
    """
    facility = create_facility()
    c1 = create_rebate_claim(
        facility["id"], eligible_purchase_cents=1000000, private_label_share=0.0
    )
    assert c1["provisional_amount_cents"] == 30000
    c2 = create_rebate_claim(
        facility["id"],
        eligible_purchase_cents=999999,
        private_label_share=0.0,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    assert c2["provisional_amount_cents"] == 20000


def test_claim_settle_paid_from_accrued_409(api):
    """PRD §3.7: "any event attempted from a non-sponsoring state rejected with
    `ERR_INVALID_STATE`" — and settlement forks from `SUBMITTED` only.

    Design: Corner/state_machines/claim_settle_paid_from_accrued_rejected
    """
    facility = create_facility()
    claim = create_rebate_claim(facility["id"])
    resp = api.record_lifecycle_event(claim["id"], {"event": "SETTLE_PAID"}, GPO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = get_success_data(api.get_rebate_claim(claim["id"], GPO))
    assert reread["status"] == "ACCRUED"


def test_claim_dispute_missing_reason_400(api):
    """PRD §3.7: "a `SETTLE_DISPUTED` event — which requires a non-empty
    `dispute_reason` in the payload, otherwise `ERR_INVALID_REQUEST` — moves it
    to `DISPUTED` and stores that reason."

    Design: Corner/state_machines/claim_dispute_missing_reason_rejected
    """
    facility = create_facility()
    claim = create_rebate_claim(facility["id"])
    record_claim_event(claim["id"], "SUBMIT")
    resp = api.record_lifecycle_event(claim["id"], {"event": "SETTLE_DISPUTED"}, GPO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    reread = get_success_data(api.get_rebate_claim(claim["id"], GPO))
    assert reread["status"] == "SUBMITTED"


def test_claim_paid_terminal_lockdown(api):
    """PRD §3.7: "a `SETTLE_PAID` event moves the claim to `PAID`, the terminal
    state" — and "any event attempted from a non-sponsoring state rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/claim_paid_terminal_lockdown
    """
    facility = create_facility()
    claim = create_rebate_claim(facility["id"])
    record_claim_event(claim["id"], "SUBMIT")
    record_claim_event(claim["id"], "SETTLE_PAID")
    resp = api.record_lifecycle_event(
        claim["id"],
        {"event": "SETTLE_DISPUTED", "dispute_reason": "late dispute"},
        GPO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = get_success_data(api.get_rebate_claim(claim["id"], GPO))
    assert reread["status"] == "PAID"


def test_rebate_provisional_ignores_bonus_and_compliance(api):
    """PRD §3.7: "The `provisional_amount_cents` stored at creation is simply
    the eligible volume times that base rate, rounded half up to whole cents —
    no private-label bonus, no compliance multiplier". 1200000 at tier 0.03 ->
    36000 even with share 0.35 and compliant true.

    Design: Difficulty/dual_variant_calc/rebate_provisional_ignores_bonus_and_compliance
    """
    facility = create_facility()
    claim = create_rebate_claim(
        facility["id"],
        eligible_purchase_cents=1200000,
        private_label_share=0.35,
        compliant=True,
    )
    assert claim["provisional_amount_cents"] == 36000
    assert claim["status"] == "ACCRUED"


def test_rebate_final_after_submit_adds_bonus(api):
    """PRD §3.7: "A `SUBMIT` event moves an `ACCRUED` claim to `SUBMITTED` and
    computes the validated `final_amount_cents`. The validated rate is the base
    tier rate plus a private-label bonus of 0.005 when `private_label_share` is
    at least 0.30". 1200000 x (0.03 + 0.005) x 1.0 = 42000, a 6000 delta over
    the 36000 provisional.

    Design: Difficulty/dual_variant_calc/rebate_provisional_ignores_bonus_and_compliance
    """
    facility = create_facility()
    claim = create_rebate_claim(
        facility["id"],
        eligible_purchase_cents=1200000,
        private_label_share=0.35,
        compliant=True,
    )
    submitted = record_claim_event(claim["id"], "SUBMIT")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["final_amount_cents"] == 42000
    assert (
        submitted["final_amount_cents"] - claim["provisional_amount_cents"] == 6000
    )


def test_rebate_noncompliant_provisional_uses_tier_only(api):
    """PRD §3.7: "no private-label bonus, no compliance multiplier" — the
    provisional accrual is 1200000 x 0.03 = 36000 even when the facility was
    non-compliant (the multiplier only enters the validated variant).

    Design: Difficulty/combinatorial_formula/rebate_validated_formula_tier_bonus_multiplier
    """
    facility = create_facility()
    claim = create_rebate_claim(
        facility["id"],
        eligible_purchase_cents=1200000,
        private_label_share=0.35,
        compliant=False,
    )
    assert claim["provisional_amount_cents"] == 36000


def test_rebate_noncompliant_final_applies_multiplier(api):
    """PRD §3.7: "The computation order is pinned: first multiply the eligible
    volume by the validated rate and round half up to whole cents; then multiply
    by the compliance multiplier and round half up to whole cents again; the
    result is `final_amount_cents`." — 1200000 x 0.035 = 42000, then
    42000 x 0.5 = 21000, proving the bonus branch (0.35 >= 0.30) and the
    non-compliance multiplier (0.5) compose.

    Design: Difficulty/combinatorial_formula/rebate_validated_formula_tier_bonus_multiplier
    """
    facility = create_facility()
    claim = create_rebate_claim(
        facility["id"],
        eligible_purchase_cents=1200000,
        private_label_share=0.35,
        compliant=False,
    )
    submitted = record_claim_event(claim["id"], "SUBMIT")
    assert submitted["final_amount_cents"] == 21000


def test_rebate_dispute_cycle_statuses(api):
    """PRD §3.7: "Settlement forks from `SUBMITTED`: a `SETTLE_PAID` event moves
    the claim to `PAID`, the terminal state, while a `SETTLE_DISPUTED` event —
    which requires a non-empty `dispute_reason` in the payload, otherwise
    `ERR_INVALID_REQUEST` — moves it to `DISPUTED` and stores that reason." The
    validated amount on SUBMIT: round_half_up(250000 x (0.01 + 0.005)) x 1.0 =
    3750.

    Design: Difficulty/non_linear_state_machine/rebate_claim_dispute_resubmission_cycle
    """
    facility = create_facility()
    claim = create_rebate_claim(
        facility["id"], eligible_purchase_cents=250000, private_label_share=0.40
    )
    assert claim["provisional_amount_cents"] == 2500
    submitted = record_claim_event(claim["id"], "SUBMIT")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["final_amount_cents"] == 3750
    disputed = record_claim_event(claim["id"], "SETTLE_DISPUTED", "volume mismatch")
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "volume mismatch"


def test_rebate_resubmit_recomputes_and_clears_reason(api):
    """PRD §3.7: "From `DISPUTED`, a `RESUBMIT` event returns the claim to
    `SUBMITTED`, recomputes `final_amount_cents` under the same validated
    variant, and clears `dispute_reason` back to null". The cycle then settles:
    ACCRUED -> SUBMITTED -> DISPUTED -> SUBMITTED -> PAID (terminal).

    Design: Difficulty/non_linear_state_machine/rebate_claim_dispute_resubmission_cycle
    """
    facility = create_facility()
    claim = create_rebate_claim(
        facility["id"], eligible_purchase_cents=250000, private_label_share=0.40
    )
    record_claim_event(claim["id"], "SUBMIT")
    record_claim_event(claim["id"], "SETTLE_DISPUTED", "volume mismatch")
    resubmitted = record_claim_event(claim["id"], "RESUBMIT")
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["final_amount_cents"] == 3750
    assert resubmitted.get("dispute_reason") is None
    paid = record_claim_event(claim["id"], "SETTLE_PAID")
    assert paid["status"] == "PAID"


def test_rebate_period_shared_boundary_overlaps(api):
    """PRD §3.7: "Periods for the same facility and GPO may not overlap under
    the closed-interval convention: a new claim collides with an existing one
    whenever the existing period starts on or before the new period's end and
    the new period starts on or before the existing period's end — two periods
    sharing a boundary date count as overlapping — and the collision is rejected
    with `ERR_REBATE_PERIOD_OVERLAP` (HTTP 409) regardless of the existing
    claim's status."

    Design: Difficulty/resource_temporal_overlap/rebate_periods_closed_interval_adjacency
    """
    facility = create_facility()
    create_rebate_claim(
        facility["id"], period_start="2026-01-01", period_end="2026-03-31"
    )
    resp = api.create_rebate_claim(
        create_rebate_claim_payload(
            facility["id"],
            period_start="2026-03-31",  # shared boundary date: closed intervals touch
            period_end="2026-06-30",
            eligible_purchase_cents=300000,
        ),
        headers=GPO,
    )
    validate_error(resp, ApiErrorId.ERR_REBATE_PERIOD_OVERLAP.value, 409)


def test_rebate_period_day_after_and_other_gpo_ok(api):
    """PRD §3.7: the closed-interval collision rule is scoped to "the same
    facility and GPO" — the day after a closed interval does not touch it, and
    identical dates under a different `gpo_name` are outside the rule's scope.

    Design: Difficulty/resource_temporal_overlap/rebate_periods_closed_interval_adjacency
    """
    facility = create_facility()
    create_rebate_claim(
        facility["id"], period_start="2026-01-01", period_end="2026-03-31"
    )
    resp_next = api.create_rebate_claim(
        create_rebate_claim_payload(
            facility["id"],
            period_start="2026-04-01",  # first non-overlapping day
            period_end="2026-06-30",
            eligible_purchase_cents=300000,
        ),
        headers=GPO,
    )
    validate_success(resp_next, 201)
    resp_gpo_b = api.create_rebate_claim(
        create_rebate_claim_payload(
            facility["id"],
            gpo_name="GPO-B",
            period_start="2026-01-01",  # identical dates, different GPO
            period_end="2026-03-31",
            eligible_purchase_cents=300000,
        ),
        headers=GPO,
    )
    validate_success(resp_gpo_b, 201)
