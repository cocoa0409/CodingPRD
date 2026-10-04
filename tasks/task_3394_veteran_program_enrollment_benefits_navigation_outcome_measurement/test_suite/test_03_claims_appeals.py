"""Benefits claims, compensation math, appeals, and segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    validate_error, validate_success,
)
from test_helpers import factories, fixtures

INTAKE = TEST_USERS["intake_coordinator_headers"]
REP = TEST_USERS["accredited_representative_headers"]


def test_claim_compensation_provisional_vs_final(api):
    """PRD section 3.4: "At filing the system also computes
    `provisional_monthly_cents`, a plain estimate shown to the claimant: it is
    exactly the base rate for the *claimed* rating from the statutory rate table,
    with no cost-of-living adjustment and no dependent allowance."
    PRD section 3.4: "a granted claim's `final_monthly_cents` is the base rate
    for the *decided* rating plus a dependent allowance, the sum then multiplied
    by 1.025 — the statutory cost-of-living adjustment of 2.5 percent — and
    rounded half-up to whole cents under decimal arithmetic."

    Design: Difficulty/dual_variant_calc/claim_compensation_provisional_vs_final
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Alex Rivera")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=70, dependent_count=2)
    assert claim["provisional_monthly_cents"] == 166100, "base rate of claimed rating 70, no COLA, no dependents"

    decided = fixtures.decide_claim(claim["id"], "GRANTED", 50, officer_id="officer-a")
    assert decided["final_monthly_cents"] == 140118, "round_half_up((105700 + 31000) * 1.025)"
    assert decided["final_monthly_cents"] != claim["provisional_monthly_cents"]
    assert decided["status"] == "DECIDED"
    assert decided["decided_by_officer_id"] == "officer-a"
    assert fixtures.get_member(member["id"])["total_monthly_compensation_cents"] == 140118


def test_compensation_cola_per_claim_rounding(api):
    """PRD section 3.4: "the sum of `final_monthly_cents` over all of the
    member's claims in `DECIDED` or `CLOSED`, adding the per-claim **rounded**
    values (each claim is rounded to whole cents before the member-level sum; the
    order is pinned)."

    Design: Difficulty/combinatorial_formula/compensation_cola_per_claim_rounding
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Cola Vet")
    claim1 = fixtures.create_claim(member["id"], claimed_rating_pct=10, dependent_count=0)
    claim2 = fixtures.create_claim(member["id"], claimed_rating_pct=10, dependent_count=0)

    decided1 = fixtures.decide_claim(claim1["id"], "GRANTED", 10, officer_id="officer-a")
    decided2 = fixtures.decide_claim(claim2["id"], "GRANTED", 10, officer_id="officer-a")

    assert decided1["final_monthly_cents"] == 17938, "round_half_up(17500 * 1.025)"
    assert decided2["final_monthly_cents"] == 17938
    total = fixtures.get_member(member["id"])["total_monthly_compensation_cents"]
    assert total == 35876, "17938 + 17938 with per-claim rounding first"
    assert total != 35875, "summing unrounded values would give 35875.0"


def test_claim_create_defaults_dependent_count_zero(api):
    """PRD section 3.4: "`dependent_count` records dependents for the award
    computation; it defaults to 0 and must be at least 0."
    PRD section 3.4: "at 30 percent or above it is zero for no dependents, 16000
    cents ($160.00) for exactly one dependent"

    Design: Corner/entities/claim_create_defaults_dependent_count_zero
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Default Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=30,
                                  omit_dependent_count=True)
    assert claim["dependent_count"] == 0, "default applied at creation"

    decided = fixtures.decide_claim(claim["id"], "GRANTED", 30, officer_id="officer-a")
    assert decided["final_monthly_cents"] == 53710, "round_half_up((52400 + 0) * 1.025)"


def test_compensation_dependent_allowance_floor_at_rating_20(api):
    """PRD section 3.4: "The dependent allowance is zero when the decided rating
    is below 30 percent; at 30 percent or above it is zero for no dependents,
    16000 cents ($160.00) for exactly one dependent, and for two or more
    dependents it is 31000 cents ($310.00) plus a further 9000 cents ($90.00) for
    each dependent beyond the second."

    Design: Corner/calculations/compensation_dependent_allowance_floor_at_rating_20
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Floor Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=20, dependent_count=2)
    assert claim["provisional_monthly_cents"] == 34600

    decided = fixtures.decide_claim(claim["id"], "GRANTED", 20, officer_id="officer-a")
    assert decided["final_monthly_cents"] == 35465, "round_half_up(34600 * 1.025) — no allowance below 30"
    assert decided["final_monthly_cents"] != 67260, "wrongly including the 31000 allowance would give 67260"


def test_claim_create_out_of_step_rating_returns_invalid_request(api):
    """PRD section 3.4: "the claimed disability rating, which must be one of the
    statutory steps 0, 10, 20, and so on up to 100."
    PRD section 2.7: "integer ranges are honored (domain scores 0 through 10,
    Likert items 1 through 5, disability rating steps of 10 within 0 through 100,
    non-negative amounts)"

    Design: Corner/entities/claim_create_out_of_step_rating_returns_invalid_request
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Rating Vet")
    resp = api.create_claim(
        factories.create_claim_payload(member["id"], claimed_rating_pct=55), REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert fixtures.list_claims(member["id"]) == []


def test_appeal_overturned_cascade(api):
    """PRD section 3.4: "When the appeal is overturned, the claim's
    `decided_rating_pct` is replaced by the appeal's `new_rating_pct`, the
    claim's `final_monthly_cents` is recomputed under the final variant, and the
    claim's `decided_by_officer_id` becomes the appeal's deciding officer."
    PRD section 3.4: "Each decision — and each overturning appeal decision below —
    recomputes the member's `total_monthly_compensation_cents`"

    Design: Difficulty/transitive_cascade/appeal_overturned_cascade
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Cascade Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=70, dependent_count=2)
    fixtures.decide_claim(claim["id"], "GRANTED", 50, officer_id="officer-a")
    version_after_decide = fixtures.get_member_version(member["id"])

    appeal = fixtures.create_appeal(claim["id"], grounds="rating too low")
    decided_appeal = fixtures.decide_appeal(appeal["id"], "OVERTURNED", new_rating_pct=70,
                                          officer_id="officer-b")
    assert decided_appeal["status"] == "DECIDED"
    assert decided_appeal["outcome"] == "OVERTURNED"
    assert decided_appeal["decided_by_officer_id"] == "officer-b"

    claim_after = fixtures.get_claim(claim["id"])
    assert claim_after["status"] == "DECIDED", "returned from APPEAL_PENDING"
    assert claim_after["decided_rating_pct"] == 70
    assert claim_after["final_monthly_cents"] == 202028, "round_half_up((166100 + 31000) * 1.025)"
    assert claim_after["decided_by_officer_id"] == "officer-b", "the appeal re-anchors the standing decision"

    member_after = fixtures.get_member(member["id"])
    assert member_after["total_monthly_compensation_cents"] == 202028
    assert member_after["version"] - version_after_decide == 1, (
        "the appeal-driven recomputation increments the member's version by 1")


def test_appeal_requires_claim_decided(api):
    """PRD section 3.4: "A representative may appeal a claim only while the claim
    is in `DECIDED` — an appeal against a `FILED`, `APPEAL_PENDING`, or `CLOSED`
    claim is rejected with `ERR_CLAIM_NOT_APPEALABLE` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/appeal_requires_claim_decided
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Appeal Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=40, dependent_count=1)

    err_resp = api.create_appeal(
        factories.create_appeal_payload(claim["id"], grounds="premature"), REP)
    validate_error(err_resp, ApiErrorId.ERR_CLAIM_NOT_APPEALABLE)

    fixtures.decide_claim(claim["id"], "GRANTED", 40, officer_id="officer-a")
    ok_resp = api.create_appeal(
        factories.create_appeal_payload(claim["id"], grounds="rating too low"), REP)
    appeal = validate_success(ok_resp, 201)
    assert appeal["status"] == "OPEN"
    assert fixtures.get_claim(claim["id"])["status"] == "APPEAL_PENDING"
    assert len(fixtures.list_appeals(claim["id"])) == 1


def test_appeal_state_error_beats_temporal_error(api):
    """PRD section 2.7: "When several checks could reject the same request, they
    are evaluated in a single fixed priority order, and the **first** failure
    wins."
    PRD section 3.4: "an appeal against a `FILED`, `APPEAL_PENDING`, or `CLOSED`
    claim is rejected with `ERR_CLAIM_NOT_APPEALABLE` (HTTP 409)"
    PRD section 2.5: "Each `BenefitsClaim` in `DECIDED` whose `decided_at` lies
    more than 97 days before the clock — that is, the 90-day appeal window plus a
    further 7-day close grace — moves to `CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_error_beats_temporal_error
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Window Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=50, dependent_count=0)
    fixtures.set_clock("2026-09-10T12:00:00Z")
    fixtures.decide_claim(claim["id"], "GRANTED", 50, officer_id="officer-a")
    fixtures.set_clock("2026-12-17T00:00:00Z")

    assert fixtures.get_claim(claim["id"])["status"] == "CLOSED", "sweep ran at the clock set"

    err_resp = api.create_appeal(factories.create_appeal_payload(claim["id"]), REP)
    validate_error(err_resp, ApiErrorId.ERR_CLAIM_NOT_APPEALABLE)
    assert err_resp.status_code == 409, "state category beats the temporal ERR_APPEAL_WINDOW_CLOSED (422)"
    assert fixtures.list_appeals(claim["id"]) == []


def test_claim_closed_is_terminal(api):
    """PRD section 3.4: "`CLOSED` is terminal; a closed claim still contributes
    its `final_monthly_cents` to the member's total."
    PRD section 3.4: "A `BenefitsOfficer` decides a claim that sits in `FILED` —
    deciding from any other state is `ERR_INVALID_STATE`"

    Design: Corner/state_machines/claim_closed_is_terminal
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Terminal Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=50, dependent_count=0)
    fixtures.set_clock("2026-09-10T12:00:00Z")
    fixtures.decide_claim(claim["id"], "GRANTED", 50, officer_id="officer-a")
    fixtures.set_clock("2026-12-17T00:00:00Z")  # past decided_at + 97 days

    err_resp = api.decide_claim(
        claim["id"], factories.claim_decision_payload("GRANTED", 60),
        fixtures.make_benefits_officer_headers("officer-b"))
    validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE)

    claim_after = fixtures.get_claim(claim["id"])
    assert claim_after["status"] == "CLOSED"
    assert claim_after["decided_rating_pct"] == 50


def test_clock_sweep_closes_claim_one_second_past_grace(api):
    """PRD section 2.5: "Each `BenefitsClaim` in `DECIDED` whose `decided_at`
    lies more than 97 days before the clock — that is, the 90-day appeal window
    plus a further 7-day close grace — moves to `CLOSED`."
    PRD section 2.5: "the boundary comparisons apply exactly as written above:
    survey opening uses "at or after", while survey expiry, claim closing,
    referral expiry, event no-show, waitlist expiry, and external-record closing
    all use "strictly after"."

    Design: Corner/state_machines/clock_sweep_closes_claim_one_second_past_grace
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Grace Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=40, dependent_count=0)
    fixtures.set_clock("2026-09-10T12:00:00Z")
    fixtures.decide_claim(claim["id"], "GRANTED", 40, officer_id="officer-a")

    fixtures.set_clock("2026-12-16T12:00:00Z")  # exactly decided_at + 97 days
    assert fixtures.get_claim(claim["id"])["status"] == "DECIDED", "not yet strictly past"

    fixtures.set_clock("2026-12-16T12:00:01Z")
    assert fixtures.get_claim(claim["id"])["status"] == "CLOSED"


def test_healthcare_claim_cannot_be_appealed(api):
    """PRD section 3.4: "and only when the claim is a `DISABILITY_COMPENSATION`
    claim, since a `HEALTHCARE_ACCESS` claim is rejected with
    `ERR_CLAIM_TYPE_NOT_APPEALABLE` (HTTP 409)."
    PRD section 3.4: "For a `HEALTHCARE_ACCESS` claim the provisional figure
    stays null."

    Design: Corner/validations/healthcare_claim_cannot_be_appealed
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Health Vet")
    claim = fixtures.create_claim(member["id"], claim_type="HEALTHCARE_ACCESS",
                                  omit_rating=True)
    assert claim["provisional_monthly_cents"] is None

    decided = fixtures.decide_claim(claim["id"], "GRANTED", 0, officer_id="officer-a")
    assert decided["final_monthly_cents"] == 0

    err_resp = api.create_appeal(
        factories.create_appeal_payload(claim["id"], grounds="want a higher tier of care"), REP)
    validate_error(err_resp, ApiErrorId.ERR_CLAIM_TYPE_NOT_APPEALABLE)


def test_appeal_at_exactly_90_days_allowed(api):
    """PRD section 3.4: "The window's upper bound is inclusive — the final
    instant of the 90th day is still inside the window, and one second later is
    not — and a late filing is rejected with `ERR_APPEAL_WINDOW_CLOSED`
    (HTTP 422)."

    Design: Corner/validations/appeal_at_exactly_90_days_allowed
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Deadline Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=40, dependent_count=0)
    fixtures.set_clock("2026-09-10T12:00:00Z")
    fixtures.decide_claim(claim["id"], "GRANTED", 40, officer_id="officer-a")

    fixtures.set_clock("2026-12-09T12:00:00Z")  # decided_at + 90 days exactly
    resp = api.create_appeal(
        factories.create_appeal_payload(claim["id"], grounds="last instant"), REP)
    appeal = validate_success(resp, 201)
    assert appeal["status"] == "OPEN"
    assert fixtures.get_claim(claim["id"])["status"] == "APPEAL_PENDING"
    assert len(fixtures.list_appeals(claim["id"])) == 1


def test_appeal_decide_by_same_officer_rejected(api):
    """PRD section 3.4: "the officer's `X-User-ID` must differ from the claim's
    standing `decided_by_officer_id`; the same officer deciding their own appeal
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/appeal_decide_by_same_officer_rejected
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Segregation Vet")
    claim = fixtures.create_claim(member["id"], claimed_rating_pct=40, dependent_count=0)
    fixtures.decide_claim(claim["id"], "GRANTED", 40, officer_id="officer-a")
    appeal = fixtures.create_appeal(claim["id"], grounds="rating too low")

    err_resp = api.decide_appeal(
        appeal["id"], factories.appeal_decision_payload("UPHELD"),
        fixtures.make_benefits_officer_headers("officer-a"))
    validate_error(err_resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    open_appeals = fixtures.list_appeals(claim["id"])
    assert open_appeals[0]["status"] == "OPEN", "the rejected attempt left the appeal open"

    decided = fixtures.decide_appeal(appeal["id"], "UPHELD", officer_id="officer-b")
    assert decided["status"] == "DECIDED"

    claim_after = fixtures.get_claim(claim["id"])
    assert claim_after["status"] == "DECIDED"
    assert claim_after["decided_rating_pct"] == 40
    assert claim_after["final_monthly_cents"] == 77388, "UPHELD leaves the award untouched"


def test_claim_get_unknown_id_returns_claim_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/claim_get_unknown_id_returns_claim_not_found
    """
    fixtures.reset_clock()
    resp = api.get_claim(
        NON_EXISTENT_UUID, fixtures.make_benefits_officer_headers("officer-a"))
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)


def test_appeal_decide_unknown_id_returns_appeal_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/appeal_decide_unknown_id_returns_appeal_not_found
    """
    fixtures.reset_clock()
    resp = api.decide_appeal(
        NON_EXISTENT_UUID, factories.appeal_decision_payload("UPHELD"),
        fixtures.make_benefits_officer_headers("officer-a"))
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_FOUND)


def test_request_shape_runs_before_existence(api):
    """PRD section 2.7: "When several checks could reject the same request, they
    are evaluated in a single fixed priority order, and the **first** failure
    wins."
    PRD section 2.7: "2. **Request well-formedness.** All required input fields
    are present, enum values fall within their declared sets"

    Design: Corner/validations/request_shape_runs_before_existence
    """
    fixtures.reset_clock()
    resp = api.create_claim(
        {"member_id": NON_EXISTENT_UUID, "claim_type": "BOGUS_ENUM"}, REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.json()["data"]["error_id"] != "ERR_MEMBER_NOT_FOUND", (
        "existence would have fired only after request shape")
