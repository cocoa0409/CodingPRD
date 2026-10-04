"""Per-entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Common fields ────────────────────────────────────

def _is_utc_instant(value) -> bool:
    """An ISO 8601 UTC instant, with or without a fractional part.

    The harness's own `is_iso8601_timestamp` accepts only the three-digit form,
    but every instant in this domain lands on a whole second (the logical clock
    is settable only to whole seconds), so the suite compares against the
    bare-second spelling. Accept both rather than pinning the serializer to a
    `.000` that carries no information.
    """
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    if "." not in value:
        value = value[:-1] + ".000Z"
    return is_iso8601_timestamp(value)


def assert_common_fields(data: dict, entity: str = "entity"):
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert _is_utc_instant(data.get("created_at")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert _is_utc_instant(data.get("updated_at")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


# ─── Clinician ────────────────────────────────────────

def assert_clinician(data: dict):
    assert_common_fields(data, "Clinician")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["license_type"] in ["LCSW", "LMFT", "LPC", "LMHC", "PSY_D", "PHD"]
    assert isinstance(data["primary_state"], str) and len(data["primary_state"]) == 2
    assert isinstance(data["specialty_tags"], list)
    assert isinstance(data["weekly_caseload_target"], int)
    assert data["weekly_caseload_target"] >= 1
    assert data["status"] in [
        "ONBOARDING", "CREDENTIALING", "ACTIVE", "SUSPENDED", "OFFBOARDING", "OFFBOARDED",
    ]
    assert data["billing_posture"] in ["BILLABLE", "GATED", "FROZEN"]
    assert isinstance(data["active_patient_count"], int) and data["active_patient_count"] >= 0
    assert isinstance(data["enrolled_payer_count"], int) and data["enrolled_payer_count"] >= 0
    assert isinstance(data["open_slot_count"], int) and data["open_slot_count"] >= 0
    assert isinstance(data["payout_balance_cents"], int)
    assert isinstance(data["continuity_plan_count"], int)
    assert isinstance(data["cash_basis_opt_in"], bool)


def assert_clinician_invariants(data: dict):
    """A posting-derivation invariant that must hold after any clinician write."""
    posture = data["billing_posture"]
    if posture == "FROZEN":
        assert (
            data["status"] in ("SUSPENDED", "OFFBOARDED")
            or data["enrolled_payer_count"] == 0
        ), "FROZEN requires SUSPENDED/OFFBOARDED status or zero effective enrollments"
    if posture == "BILLABLE":
        assert data["enrolled_payer_count"] >= 1, (
            "BILLABLE requires at least one EFFECTIVE enrollment"
        )


# ─── License ──────────────────────────────────────────

def assert_license(data: dict):
    assert_common_fields(data, "License")
    assert isinstance(data["clinician_id"], str)
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["license_type"] in ["LCSW", "LMFT", "LPC", "LMHC", "PSY_D", "PHD"]
    assert isinstance(data["issuing_state"], str) and len(data["issuing_state"]) == 2
    assert _is_utc_instant(data["expires_on"])
    assert isinstance(data["telehealth_eligible"], bool)
    assert data["verification_status"] in ["UNVERIFIED", "VERIFIED", "EXPIRED", "FAILED"]
    assert isinstance(data["verification_attempts"], int)
    assert data["verification_attempts"] >= 0


# ─── MalpracticePolicy ────────────────────────────────

def assert_malpractice_policy(data: dict):
    assert_common_fields(data, "MalpracticePolicy")
    assert isinstance(data["clinician_id"], str)
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["coverage_cents"], int)
    assert _is_utc_instant(data["effective_on"])
    assert _is_utc_instant(data["expires_on"])
    assert isinstance(data["tail_coverage"], bool)
    assert data["policy_status"] in ["PENDING", "ACTIVE", "LAPSED"]


# ─── Payer ────────────────────────────────────────────

def assert_payer(data: dict):
    assert_common_fields(data, "Payer")
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert isinstance(data["payer_code"], str) and data["payer_code"]
    assert isinstance(data["delegated_credentialing"], bool)
    assert isinstance(data["min_malpractice_coverage_cents"], int)
    assert isinstance(data["timely_filing_days"], int) and data["timely_filing_days"] >= 1
    assert isinstance(data["credentialing_sla_days"], int)
    assert isinstance(data["allowed_cpt_codes"], list)
    assert data["status"] in ["ACTIVE", "SUSPENDED_AT_PAYER", "TERMINATED"]


# ─── PayerRate ────────────────────────────────────────

def assert_payer_rate(data: dict):
    assert_common_fields(data, "PayerRate")
    assert isinstance(data["payer_id"], str)
    assert isinstance(data["rate_set_version"], int)
    assert data["license_type"] in ["LCSW", "LMFT", "LPC", "LMHC", "PSY_D", "PHD"]
    assert isinstance(data["geography"], str) and len(data["geography"]) == 2
    assert isinstance(data["cpt_code"], str)
    assert isinstance(data["rate_cents"], int)
    assert _is_utc_instant(data["effective_from"])


# ─── PayerEnrollment ──────────────────────────────────

def assert_payer_enrollment(data: dict):
    assert_common_fields(data, "PayerEnrollment")
    assert isinstance(data["clinician_id"], str)
    assert isinstance(data["payer_id"], str)
    assert isinstance(data["delegated"], bool)
    assert _is_utc_instant(data["effective_from"])
    assert data["status"] in ["PENDING", "EFFECTIVE", "SUSPENDED", "TERMINATED", "REJECTED"]


# ─── PatientClient ────────────────────────────────────

def assert_patient(data: dict):
    assert_common_fields(data, "PatientClient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["payer_id"], str)
    assert isinstance(data["plan_code"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["deductible_cents"], int)
    assert 0.0 <= data["coinsurance_rate"] <= 1.0
    assert isinstance(data["oop_max_cents"], int)
    assert isinstance(data["oop_met_cents"], int)
    assert data["benefit_status"] in ["UNVERIFIED", "VERIFIED", "STALE"]
    assert isinstance(data["swap_requested"], bool)
    assert isinstance(data["visit_count_year"], int)


# ─── BenefitVerification ──────────────────────────────

def assert_benefit_verification(data: dict):
    assert_common_fields(data, "BenefitVerification")
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["payer_id"], str)
    assert isinstance(data["deductible_remaining_cents"], int)
    assert 0.0 <= data["coinsurance_rate"] <= 1.0
    assert isinstance(data["copay_cents"], int)
    assert isinstance(data["oop_remaining_cents"], int)
    assert data["status"] in ["VERIFIED", "STALE", "FAILED"]
    assert _is_utc_instant(data["verified_at"])
    assert isinstance(data["quoted_cost_share_cents"], int)


# ─── Session ──────────────────────────────────────────

def assert_session(data: dict):
    assert_common_fields(data, "Session")
    assert isinstance(data["clinician_id"], str)
    assert isinstance(data["patient_id"], str)
    assert _is_utc_instant(data["scheduled_start"])
    assert _is_utc_instant(data["scheduled_end"])
    assert isinstance(data["cpt_code"], str)
    assert data["modality"] in ["VIDEO", "PHONE", "IN_PERSON"]
    assert data["status"] in ["REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert data["billing_state"] in [
        "UNBILLED", "CLAIM_SUBMITTED", "PAYER_PAID", "DENIED", "WRITTEN_OFF",
    ]
    assert isinstance(data["slot_consumed"], bool)


def assert_session_invariants(data: dict):
    """The billing axis never advances while the transcription axis is REQUESTED."""
    if data["status"] == "REQUESTED":
        assert data["billing_state"] == "UNBILLED", (
            "a REQUESTED session cannot carry an advanced billing state"
        )
        assert data["slot_consumed"] is False, "a REQUESTED session consumes no slot"


# ─── SessionNote ──────────────────────────────────────

def assert_session_note(data: dict):
    assert_common_fields(data, "SessionNote")
    assert isinstance(data["session_id"], str)
    assert isinstance(data["diagnosis_code"], str)
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert isinstance(data["cpt_code"], str)
    assert isinstance(data["narrative"], str)
    assert data["status"] in ["DRAFT", "SIGNED", "LOCKED"]
    assert isinstance(data["note_version"], int) and data["note_version"] >= 1


# ─── Claim ────────────────────────────────────────────

def assert_claim(data: dict):
    assert_common_fields(data, "Claim")
    assert isinstance(data["session_id"], str)
    assert isinstance(data["payer_id"], str)
    assert isinstance(data["clinician_id"], str)
    assert _is_utc_instant(data["submitted_on"])
    assert isinstance(data["billed_cents"], int)
    assert isinstance(data["allowed_cents"], int)
    assert isinstance(data["patient_resp_cents"], int)
    assert isinstance(data["payer_paid_cents"], int)
    assert data["claim_status"] in [
        "DRAFT", "SUBMITTED", "PAID", "DENIED", "REPROCESSING", "WRITTEN_OFF",
    ]
    assert isinstance(data["resubmission_count"], int)


def assert_claim_invariants(data: dict):
    """payer_paid_cents is the allowed amount less the patient responsibility,
    floored at zero, once the claim has been adjudicated."""
    if data["claim_status"] in ("PAID", "DENIED", "WRITTEN_OFF", "REPROCESSING"):
        expected = max(0, data["allowed_cents"] - data["patient_resp_cents"])
        assert data["payer_paid_cents"] in (0, expected), (
            "payer_paid_cents must be allowed_cents less patient_resp_cents, floored at zero"
        )


# ─── PayoutBatch / PayoutLine ─────────────────────────

def assert_payout_batch(data: dict):
    assert_common_fields(data, "PayoutBatch")
    assert _is_utc_instant(data["period_start"])
    assert _is_utc_instant(data["period_end"])
    assert data["schedule"] in ["WEEKLY", "BIWEEKLY", "SEMIMONTHLY"]
    assert data["status"] in ["OPEN", "LOCKED", "PAID", "RECONCILED", "SKIPPED"]
    assert isinstance(data["total_gross_cents"], int)
    assert isinstance(data["total_adjustment_cents"], int)
    assert isinstance(data["total_net_cents"], int)
    assert isinstance(data["line_count"], int)


def assert_payout_line(data: dict):
    assert_common_fields(data, "PayoutLine")
    assert isinstance(data["payout_batch_id"], str)
    assert isinstance(data["clinician_id"], str)
    assert isinstance(data["session_ids"], list)
    assert isinstance(data["claim_ids"], list)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["adjustment_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["line_status"] in ["PENDING", "PAID", "CLAWED_BACK", "VOIDED"]
    assert data["basis"] in ["SCHEDULED", "CASH_BASIS"]


def assert_payout_line_invariants(line: dict):
    """net is gross plus adjustment; the floor at zero applies to PENDING lines only."""
    expected = line["gross_cents"] + line["adjustment_cents"]
    if line["line_status"] == "PENDING":
        assert line["net_cents"] == max(0, expected), (
            "a PENDING line floors its net at zero"
        )
    elif line["line_status"] == "PAID":
        assert line["net_cents"] == expected, (
            "a PAID line is never floored, so a clawback may drive its net negative"
        )


def assert_batch_totals_match_lines(batch: dict, lines: list):
    """Locked totals are the sums over the batch's non-voided lines."""
    included = [ln for ln in lines if ln["line_status"] != "VOIDED"]
    assert batch["line_count"] == len(included), (
        f"line_count {batch['line_count']} != non-voided line count {len(included)}"
    )
    assert batch["total_gross_cents"] == sum(ln["gross_cents"] for ln in included)
    assert batch["total_adjustment_cents"] == sum(ln["adjustment_cents"] for ln in included)
    assert batch["total_net_cents"] == sum(ln["net_cents"] for ln in included)


# ─── ContinuityPlan ───────────────────────────────────

def assert_continuity_plan(data: dict):
    assert_common_fields(data, "ContinuityPlan")
    assert isinstance(data["clinician_id"], str)
    assert isinstance(data["patient_id"], str)
    assert _is_utc_instant(data["reassignment_deadline"])
    assert data["status"] in ["PENDING", "ACCEPTED", "DECLINED", "ESCALATED", "COMPLETED"]
    assert data["reason"] in ["OFFBOARDING", "CASELOAD_REBALANCE", "CLINICAL_CONFLICT"]


def assert_envelope_object(response):
    """A 2xx object response carries response_type object."""
    body = response.json()
    assert body["response_type"] == "object", "expected response_type object"
    return body["data"]