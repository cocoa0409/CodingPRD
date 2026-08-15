"""Photographer payment runs: method selection, period windows, period lock,
OCC, and the paid_out compensation path (PRD §3.9, §2.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_payment_run,
    commission_assignment,
    create_accepted_assignment,
    create_active_license,
    create_payment_run,
    create_payment_run_payload,
    create_photographer,
    create_story,
    get_photographer_fresh,
    get_photographer_version,
    record_usage_run,
    submit_assignment_image,
    submit_assignment,
    set_logical_clock,
    validate_error,
    validate_success,
)

TEST_EDITOR = TEST_USERS["photo_editor_headers"]


def test_payment_run_period_half_open_membership(api, finance_admin_headers):
    """PRD §3.9: "A `FinanceAdmin` settles photographer compensation by creating a
    `PaymentRun` for a period from `period_start` (inclusive) to `period_end`
    (exclusive); `period_end` must be strictly after `period_start`." PRD §3.9:
    "`guarantee_amount_cents` sums, over assignments of this photographer that
    reached `ACCEPTED` with `accepted_at` inside the window, the photographer's
    `day_rate_cents` multiplied by each assignment's `day_count`, plus one
    `per_image_fee_cents` for every image cleared by those in-period acceptances."

    Design: Corner/calculations/payment_run_period_half_open_membership
    """
    photographer = create_photographer()  # STAFF: day 25000, per-image 40000

    # Assignment A1 accepted exactly at period_start -> inside [start, end).
    story1 = create_story(slug="bridge-fire")
    _, a1 = commission_assignment(
        photographer["id"], story_id=story1["id"],
        shoot_start="2026-08-05T09:00:00Z", shoot_end="2026-08-05T17:00:00Z",
    )
    submit_assignment_image(a1, photographer["id"])
    submit_assignment(a1, photographer["id"])
    set_logical_clock("2026-08-01T00:00:00Z")
    validate_success(api_client.accept_assignment(a1, TEST_EDITOR), 200)

    # Assignment A2 accepted exactly at period_end -> outside [start, end).
    story2 = create_story(slug="harbor-festival", needed_by="2026-10-01T00:00:00Z")
    _, a2 = commission_assignment(
        photographer["id"], story_id=story2["id"],
        shoot_start="2026-08-20T09:00:00Z", shoot_end="2026-08-20T17:00:00Z",
    )
    submit_assignment_image(a2, photographer["id"])
    submit_assignment(a2, photographer["id"])
    set_logical_clock("2026-09-01T00:00:00Z")
    validate_success(api_client.accept_assignment(a2, TEST_EDITOR), 200)

    run = create_payment_run(photographer["id"])
    assert_payment_run(run)
    # Only A1 counts: 25000 x 1 day + 40000 x 1 image = 65000.
    assert run["guarantee_amount_cents"] == 65000, (
        f"the half-open window must include A1 (at period_start) and exclude A2 "
        f"(at period_end): expected 65000, got {run['guarantee_amount_cents']}"
    )
    assert run["total_cents"] == 65000


def test_payment_period_overlap_locked(api, finance_admin_headers):
    """PRD §3.9: "The payment period lock prevents double-paying a period: the new
    run's half-open window must not overlap the window of any `APPROVED` or `PAID`
    run for the same photographer — adjacency is allowed — and a violation is
    rejected with `ERR_PAYMENT_PERIOD_LOCKED`."

    Design: Corner/validations/payment_period_overlap_locked
    """
    photographer = create_photographer()
    run1 = create_payment_run(photographer["id"])  # [2026-08-01, 2026-09-01)
    validate_success(api_client.approve_payment_run(run1["id"], finance_admin_headers), 200)

    version = get_photographer_version(photographer["id"])
    resp = api_client.create_payment_run(
        photographer["id"],
        create_payment_run_payload(
            expected_photographer_version=version,
            period_start="2026-08-15T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        ),
        finance_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_PERIOD_LOCKED)

    # Adjacency: starting exactly at the other run's period_end is allowed.
    adjacent = api_client.create_payment_run(
        photographer["id"],
        create_payment_run_payload(
            expected_photographer_version=version,
            period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        ),
        finance_admin_headers,
    )
    run2 = validate_success(adjacent, 201)
    assert_payment_run(run2)


def test_payment_run_create_stale_photographer_version_rejected(api, finance_admin_headers):
    """PRD §2.7: "Creating a payment run against a photographer requires
    `expected_photographer_version` in the request body, carrying the
    photographer's `version` as the client last observed it. If the
    photographer's current `version` has advanced — for example, by a claim
    clawback debit or a prior payment-run creation — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/payment_run_create_stale_photographer_version_rejected
    """
    photographer = create_photographer()
    observed_version = get_photographer_version(photographer["id"])

    first = api_client.create_payment_run(
        photographer["id"],
        create_payment_run_payload(expected_photographer_version=observed_version),
        finance_admin_headers,
    )
    validate_success(first, 201)  # bumps the photographer version by one

    resp = api_client.create_payment_run(
        photographer["id"],
        create_payment_run_payload(
            expected_photographer_version=observed_version,
            period_start="2026-10-01T00:00:00Z", period_end="2026-11-01T00:00:00Z",
        ),
        finance_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / payout_guarantee_vs_royalty_same_period
# ---------------------------------------------------------------------------

def _setup_freelance_with_assignment_and_two_social_runs():
    """FREELANCE photographer (day 20000, per-image 30000, royalty 305) with one
    ACCEPTED 2-day assignment (1 cleared image, accepted_at 2026-08-12) and two
    SOCIAL usage runs in [2026-08-01, 2026-09-01)."""
    bundle = create_accepted_assignment(
        photographer_overrides={
            "full_name": "Fran Free", "email": "fran@freelance.io",
            "photographer_type": "FREELANCE", "day_rate_cents": 20000,
            "per_image_fee_cents": 30000, "rights_reversion_months": 12,
        },
        shoot_start="2026-08-10T09:00:00Z", shoot_end="2026-08-11T17:00:00Z",
        accept_at="2026-08-12T00:00:00Z",
    )
    image_id = bundle["images"][0]["id"]
    lic = create_active_license(
        image_id, usage_scope="SOCIAL",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-09-30T00:00:00Z",
    )
    record_usage_run(image_id, lic["id"], headers=TEST_EDITOR, channel="SOCIAL",
                     story_slug="night-market", published_at="2026-08-15T10:00:00Z")
    record_usage_run(image_id, lic["id"], headers=TEST_EDITOR, channel="SOCIAL",
                     story_slug="night-market", published_at="2026-08-16T10:00:00Z")
    return bundle


def test_both_amounts_always_computed_on_payment_run(api, finance_admin_headers):
    """PRD §3.9: "Both amount fields are always computed and stored, but the run
    pays only the chosen method's amount: `total_cents` is the chosen amount minus
    `clawback_cents`, floored at zero."

    Design: Difficulty/dual_variant_calc/payout_guarantee_vs_royalty_same_period
    """
    bundle = _setup_freelance_with_assignment_and_two_social_runs()
    run = create_payment_run(bundle["photographer"]["id"])
    assert_payment_run(run)
    # Guarantee side: 20000 x day_count 2 + 30000 x 1 image = 70000.
    assert run["guarantee_amount_cents"] == 70000, (
        f"guarantee side must be computed even for a FREELANCE run, got {run['guarantee_amount_cents']}"
    )
    # Royalty side: two SOCIAL lines at round_half_up(305 x 0.5) = 153 -> 306.
    assert run["royalty_amount_cents"] == 306, (
        f"royalty side must be computed even though the method is ROYALTY-selected, "
        f"got {run['royalty_amount_cents']}"
    )


def test_freelance_run_selects_royalty_method(api, finance_admin_headers):
    """PRD §3.9: "The `method` derives from the photographer's type: `GUARANTEE`
    for `STAFF`, `ROYALTY` for `FREELANCE`." PRD §3.9: "A staff photographer's
    royalties never enter their payout, and a freelancer's day rates never enter
    theirs — identical period activity prices differently under the two variants."

    Design: Difficulty/dual_variant_calc/payout_guarantee_vs_royalty_same_period
    """
    bundle = _setup_freelance_with_assignment_and_two_social_runs()
    run = create_payment_run(bundle["photographer"]["id"])
    assert run["method"] == "ROYALTY"
    # total pays only the chosen method's amount (clawback 0): 306, not 70000.
    assert run["total_cents"] == 306, (
        f"the freelancer's day rates never enter the payout: expected 306, got {run['total_cents']}"
    )


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / photographer_paid_out_pay_void_conservation
# ---------------------------------------------------------------------------

def _setup_staff_with_draft_run():
    """STAFF photographer (day 25000, per-image 40000) with one ACCEPTED 2-day
    assignment (1 image) and a DRAFT payment run for August: total 90000."""
    bundle = create_accepted_assignment()
    run = create_payment_run(bundle["photographer"]["id"])
    return bundle, run


def test_pay_credits_paid_out_ledger(api, finance_admin_headers):
    """PRD §3.9: "The run then walks its lifecycle under `FinanceAdmin` control:
    `DRAFT` to `APPROVED` on approval; `APPROVED` to `PAID` on payment, which
    stamps `paid_at` with the logical now and adds `total_cents` to the
    photographer's `paid_out_cents`; and voiding from `DRAFT`, `APPROVED`, or
    `PAID` moves the run to `VOIDED`."

    Design: Difficulty/compensating_invariant/photographer_paid_out_pay_void_conservation
    """
    bundle, run = _setup_staff_with_draft_run()
    # Guarantee: 25000 x day_count 2 + 40000 x 1 image = 90000.
    assert run["total_cents"] == 90000, f"expected total 90000, got {run['total_cents']}"

    validate_success(api_client.approve_payment_run(run["id"], finance_admin_headers), 200)
    paid = validate_success(api_client.pay_payment_run(run["id"], finance_admin_headers), 200)
    assert paid["status"] == "PAID"
    assert paid["paid_at"], "paid_at must be stamped at payment"

    photographer = get_photographer_fresh(bundle["photographer"]["id"], headers=finance_admin_headers)
    assert photographer["paid_out_cents"] == 90000, (
        f"pay must credit the disbursed ledger, got {photographer['paid_out_cents']}"
    )


def test_void_of_paid_run_debits_paid_out_back(api, finance_admin_headers):
    """PRD §3.9: "Voiding a `PAID` run is the compensation path and debits
    `total_cents` back out of `paid_out_cents`."

    Design: Difficulty/compensating_invariant/photographer_paid_out_pay_void_conservation
    """
    bundle, run = _setup_staff_with_draft_run()
    validate_success(api_client.approve_payment_run(run["id"], finance_admin_headers), 200)
    validate_success(api_client.pay_payment_run(run["id"], finance_admin_headers), 200)
    assert get_photographer_fresh(bundle["photographer"]["id"], headers=finance_admin_headers)["paid_out_cents"] == 90000

    voided = validate_success(api_client.void_payment_run(run["id"], finance_admin_headers), 200)
    assert voided["status"] == "VOIDED"

    photographer = get_photographer_fresh(bundle["photographer"]["id"], headers=finance_admin_headers)
    assert photographer["paid_out_cents"] == 0, (
        f"voiding the PAID run must compensate exactly, got {photographer['paid_out_cents']}"
    )
