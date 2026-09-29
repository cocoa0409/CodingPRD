"""Queue A — priority_pair_validation_conflict and boundary_precision_check.

Every test below translates exactly one instance of §1.8's difficulty design
index; the `Design:` line of each docstring names it.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    AgreementStatus, ApiErrorId, EligibilityFileStatus, EmploymentStatus,
    IntegrationStatus, VerificationStatus, api_client, assertions as A,
    constants as C, factories as F, fixtures as fx, make_merchant_headers,
    make_partner_manager_headers,
)


# ── priority_pair_validation_conflict ───────────────────────────────────────


def _exhausted_lane():
    """A lane whose round budget is spent, plus the stale version from creation.

    Returns ``(merchant, agreement_at_creation, agreement_now)``: four rounds
    have been exchanged, so the version the `PartnerManager` captured when it
    opened the agreement is four writes out of date.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    merchant = fx.create_merchant(
        legal_name="Bistro Uno", contact_email="ops@bistrouno.example",
        primary_category="DINING", region_codes=["CA"],
    )
    opened = fx.create_agreement(merchant["id"], category="DINING", region_code="CA")
    terms = [
        (1200, 36000, 2500, "round 1"),
        (900, 30000, 1000, "round 2"),
        (1100, 34000, 2000, "round 3"),
        (1000, 32000, 1500, "round 4"),
    ]
    for index, (commission, base, share, note) in enumerate(terms):
        current = fx.get_agreement(opened["id"])
        overrides = {
            "commission_rate_bps": commission,
            "placement_fee_base_cents": base,
            "employer_revenue_share_bps": share,
            "note": note,
        }
        if index % 2 == 0:
            fx.propose_round(current, **overrides)
        else:
            fx.counter_round(current, merchant["id"], **overrides)
    standing = fx.get_agreement(opened["id"])
    assert standing["round_count"] == 4
    assert standing["version"] != opened["version"]
    return merchant, opened, standing


def _stale_fifth_round(agreement_id, stale_version):
    return api_client.propose_round(
        agreement_id,
        F.round_payload(
            stale_version, commission_rate_bps=1050,
            placement_fee_base_cents=33000, employer_revenue_share_bps=1800,
            note="stale round 5",
        ),
        make_partner_manager_headers(),
    )


def test_stale_agreement_version_outranks_the_exhausted_round_budget():
    """One call breaks band 4 and band 8; only band 4 is ever reported.

    PRD: "Beyond existence, every endpoint evaluates the rules applicable to it in one fixed global order and **returns the first violation it meets; later violations are never reported**."

    Design: Difficulty/priority_pair_validation_conflict/stale_agreement_version_outranks_exhausted_negotiation_round_budget
    """
    _merchant, opened, _standing = _exhausted_lane()

    response = _stale_fifth_round(opened["id"], opened["version"])

    # ERR_STALE_VERSION is band 4 (412); ERR_NEGOTIATION_ROUND_LIMIT is band 8
    # (409) and must never be consulted.
    error = validate_error(response, ApiErrorId.STALE_VERSION)
    assert error["error_id"] != ApiErrorId.NEGOTIATION_ROUND_LIMIT


def test_the_refused_stale_round_leaves_the_negotiation_exactly_as_it_was():
    """A rejected proposal writes nothing: no round, no version, no terms.

    PRD: "The version echo of §2.7 (`ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/stale_agreement_version_outranks_exhausted_negotiation_round_budget
    """
    _merchant, opened, standing = _exhausted_lane()

    _stale_fifth_round(opened["id"], opened["version"])

    after = fx.get_agreement(opened["id"])
    A.assert_fields(after, {
        "round_count": 4,
        "status": AgreementStatus.MERCHANT_COUNTERED.value,
        "commission_rate_bps": 1000,
        "placement_fee_base_cents": 32000,
        "version": standing["version"],
    }, "agreement")
    _rounds, meta = validate_paginated(api_client.list_negotiation_rounds(
        opened["id"], make_partner_manager_headers()
    ))
    assert meta["total_count"] == 4


def _redemption_at_its_expiry_instant():
    """A `PENDING` redemption observed exactly at `verification_expires_at`.

    The offer's `min_spend_cents` is 3,000, so a 1,000 cent till amount breaks
    the economics band as well as the temporal one.  The epoch sweep is not run,
    so the redemption is still `PENDING` at the expiry instant.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        employer_overrides={"employee_count_declared": 1},
        offer_overrides={
            "title": "20 percent off dinner over 3000", "min_spend_cents": 3000,
            "inventory_limit": 10, "per_member_limit": 5,
        },
    )
    created = fx.create_redemption(
        program["offer"]["id"], program["memberships"][0]["id"],
        intended_gross_amount_cents=5000,
    )
    A.assert_iso_equals(created["verification_expires_at"], "2026-08-04T00:00:00Z")
    fx.set_clock("2026-08-04T00:00:00Z")
    program["redemption"] = created
    return program


def test_elapsed_verification_ttl_outranks_the_unmet_minimum_spend():
    """The clock sitting on the TTL instant is already too late, band 7 wins.

    PRD: "the logical clock must be strictly before `verification_expires_at` (`ERR_VERIFICATION_EXPIRED`); the supplied `gross_amount_cents` must be greater than or equal to the offer's `min_spend_cents` (`ERR_MIN_SPEND_NOT_MET`)"

    Design: Difficulty/priority_pair_validation_conflict/expired_verification_window_outranks_unmet_minimum_spend
    """
    program = _redemption_at_its_expiry_instant()
    created = program["redemption"]

    response = api_client.verify_redemption(
        created["id"],
        F.verify_payload(created["verification_token"], 1000),
        make_merchant_headers(program["merchant"]["id"]),
    )

    error = validate_error(response, ApiErrorId.VERIFICATION_EXPIRED)
    assert error["error_id"] != ApiErrorId.MIN_SPEND_NOT_MET


def test_the_refused_verification_leaves_the_line_unpriced_and_unscored():
    """No economics crystallise, and the AUDIT score is never even computed.

    PRD: "Verification is the merchant's act and is where all economics crystallise."

    Design: Difficulty/priority_pair_validation_conflict/expired_verification_window_outranks_unmet_minimum_spend
    """
    program = _redemption_at_its_expiry_instant()
    created = program["redemption"]
    merchant_id = program["merchant"]["id"]

    api_client.verify_redemption(
        created["id"], F.verify_payload(created["verification_token"], 1000),
        make_merchant_headers(merchant_id),
    )

    after = fx.get_redemption(created["id"], merchant_id=merchant_id)
    assert after["verification_status"] == VerificationStatus.PENDING.value
    A.assert_nulls(after, [
        "gross_amount_cents", "audit_risk_score", "commission_amount_cents",
        "employer_share_cents",
    ], "redemption")
    assert fx.redemption_ledger_entries(created["id"]) == []


# ── boundary_precision_check ────────────────────────────────────────────────


def _membership_on_leave_with_seven_open_tickets():
    """A seasoned `LEAVE` membership holding two subject tickets and five priors.

    At verification the AUDIT variant sees six other redemptions of the same
    membership, so 8 points each caps the velocity term at 40.  Employment adds
    15 for `LEAVE` and seasoning adds 0 because the membership was valid from
    2026-07-01, well over seven days before the clock.  Only the amount term is
    left to move the total across the threshold.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        records=[F.eligibility_record(
            "E-001", employment_status=EmploymentStatus.LEAVE,
            eligibility_valid_from="2026-07-01T00:00:00Z",
            eligibility_valid_until="2027-07-01T00:00:00Z",
        )],
        commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        employer_overrides={"employee_count_declared": 1},
        offer_overrides={
            "title": "20 percent off dinner", "min_spend_cents": 1000,
            "inventory_limit": 50, "per_member_limit": 20,
        },
    )
    offer_id = program["offer"]["id"]
    membership_id = program["memberships"][0]["id"]
    for _ in range(5):
        fx.create_redemption(offer_id, membership_id, intended_gross_amount_cents=5000)
    program["at_threshold"] = fx.create_redemption(
        offer_id, membership_id, intended_gross_amount_cents=150000
    )
    program["below_threshold"] = fx.create_redemption(
        offer_id, membership_id, intended_gross_amount_cents=149999
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    return program


def test_audit_score_of_exactly_seventy_blocks_and_persists_the_failure():
    """15 + 40 + 15 lands on the threshold, and the refusal is written down.

    PRD: "When every other precondition holds but the recomputed `AUDIT` score is 70 or above, the redemption moves `PENDING → FAILED` rather than being merely rejected: the system stores `audit_risk_score`, sets `risk_block_reason` to the fixed string `FRAUD_RISK_THRESHOLD`, leaves `gross_amount_cents` null, writes no ledger entry at all, lowers the offer's `inventory_reserved` by 1 and recomputes `sold_out`, and increments the redemption's `version`."

    Design: Difficulty/boundary_precision_check/audit_risk_score_blocks_at_exactly_seventy_and_passes_at_sixty_nine
    """
    program = _membership_on_leave_with_seven_open_tickets()
    subject = program["at_threshold"]
    merchant_id = program["merchant"]["id"]

    # A 150,000 cent ticket contributes floor(150000 / 10000) = 15 amount points.
    response = api_client.verify_redemption(
        subject["id"], F.verify_payload(subject["verification_token"], 150000),
        make_merchant_headers(merchant_id),
    )
    validate_error(response, ApiErrorId.FRAUD_RISK_BLOCKED)

    blocked = fx.get_redemption(subject["id"], merchant_id=merchant_id)
    A.assert_fields(blocked, {
        "audit_risk_score": C.FRAUD_BLOCK_THRESHOLD,
        "verification_status": VerificationStatus.FAILED.value,
        "risk_block_reason": C.FRAUD_RISK_THRESHOLD,
    }, "redemption")
    assert blocked["audit_risk_score"] == 70
    A.assert_nulls(blocked, ["gross_amount_cents", "commission_amount_cents"], "redemption")
    assert fx.redemption_ledger_entries(subject["id"]) == []


def test_audit_score_of_sixty_nine_verifies_and_prices_the_line():
    """One cent less floors the amount term to 14, so the ticket clears at 69.

    PRD: "One point per whole 10,000 cents of `gross_amount_cents`, computed by dividing `gross_amount_cents` by 10,000 and taking the **floor** — never rounding — and capped at 25 points. A ticket of 149,999 cents therefore scores 14 points, not 15."

    Design: Difficulty/boundary_precision_check/audit_risk_score_blocks_at_exactly_seventy_and_passes_at_sixty_nine
    """
    program = _membership_on_leave_with_seven_open_tickets()
    subject = program["below_threshold"]
    merchant_id = program["merchant"]["id"]

    verified = fx.verify_redemption(subject, merchant_id, gross_amount_cents=149999)

    assert verified["audit_risk_score"] == 69
    assert verified["verification_status"] == VerificationStatus.VERIFIED.value
    # 149999 * 2000 / 10000 = 29999.8 -> 30000 by round half up.
    A.assert_line_economics(verified, 149999, 30000, 119999, 14400, 3600, 10800)


def _ratio_records(prefix, count):
    """`count` records, of which exactly the last one has a reversed window."""
    records = [
        F.eligibility_record(
            f"{prefix}-{index:02d}",
            eligibility_valid_from="2026-07-01T00:00:00Z",
            eligibility_valid_until="2027-07-01T00:00:00Z",
        )
        for index in range(1, count)
    ]
    records.append(F.eligibility_record(
        f"{prefix}-{count:02d}",
        eligibility_valid_from="2027-07-01T00:00:00Z",
        eligibility_valid_until="2026-07-01T00:00:00Z",
    ))
    return records


def test_one_invalid_record_in_twenty_is_exactly_five_hundred_bps_and_validates():
    """The inclusive boundary: a ratio of exactly 500 bps is accepted.

    PRD: "**The boundary is inclusive: a ratio of exactly 500 basis points validates.** A batch of 20 records with 1 invalid record yields exactly 500 and is accepted; a batch of 19 records with 1 invalid record yields 526 and is rejected."

    Design: Difficulty/boundary_precision_check/eligibility_file_validates_at_exactly_five_hundred_bps_and_rejects_at_five_hundred_twenty_six
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    employer = fx.create_employer(
        name="Northwind Co", region_code="CA", employee_count_declared=20,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
    )

    batch = fx.load_eligibility_file(
        employer["id"], records=_ratio_records("A", 20), checksum="sha-bound-2a"
    )
    A.assert_fields(batch, {"record_count": 20, "invalid_record_count": 1}, "batch")

    validated = fx.validate_eligibility_file(batch["id"], employer["id"])

    A.assert_fields(validated, {
        "status": EligibilityFileStatus.VALIDATED.value,
        "valid_record_count": 19,
    }, "batch")
    assert validated["rejection_reason"] is None
    assert fx.get_employer(employer["id"])["integration_status"] == (
        IntegrationStatus.VALIDATED.value
    )


def test_one_invalid_record_in_nineteen_rounds_to_five_hundred_twenty_six_and_rejects():
    """One over the boundary: 526 bps is strictly greater than 500 and rejects.

    PRD: "If the resulting ratio is **strictly greater than 500 basis points** — five percent — the batch moves `RECEIVED → REJECTED` and its `rejection_reason` is set to the fixed string `INVALID_RECORD_RATIO_EXCEEDED`; the employer's `integration_status` is left where it is, at `FILE_RECEIVED`, and only the batch's `version` advances."

    Design: Difficulty/boundary_precision_check/eligibility_file_validates_at_exactly_five_hundred_bps_and_rejects_at_five_hundred_twenty_six
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    employer = fx.create_employer(
        name="Northwind Co", region_code="CA", employee_count_declared=20,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
    )

    batch = fx.load_eligibility_file(
        employer["id"], records=_ratio_records("B", 19), checksum="sha-bound-2b"
    )
    A.assert_fields(batch, {"record_count": 19, "invalid_record_count": 1}, "batch")

    rejected = fx.validate_eligibility_file(batch["id"], employer["id"])

    A.assert_fields(rejected, {
        "status": EligibilityFileStatus.REJECTED.value,
        "valid_record_count": 18,
        "rejection_reason": C.INVALID_RECORD_RATIO_EXCEEDED,
    }, "batch")
    assert fx.get_employer(employer["id"])["integration_status"] == (
        IntegrationStatus.FILE_RECEIVED.value
    )
