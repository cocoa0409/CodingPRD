"""Composite setup helpers.

Every helper here builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the API before each individual test, so no
state is ever inherited. Helpers return the raw response payloads so callers can
assert against exact PRD field names.

The bundle returned by the ``setup_*`` helpers is a plain dict whose keys are
filled in progressively as the chain deepens:

``league``, ``sport_classification``, ``policy``, ``participant``,
``enrollment``, ``family_health_plan``, ``activity``, ``injury_report``,
``claim``, ``provider_bill``, ``benefit_payment`` plus the identity-threaded
header dicts ``league_headers`` and ``guardian_headers``.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    cheer_u12_classification_payload,
    create_benefit_payment_payload,
    create_coordination_record_payload,
    create_enrollment_payload,
    create_family_health_plan_payload,
    create_injury_report_payload,
    create_league_payload,
    create_league_policy_payload,
    create_participant_payload,
    create_provider_bill_payload,
    create_sanctioned_activity_payload,
    create_sport_classification_payload,
    swim_u14_classification_payload,
)
from .test_users import (
    SANCTIONING_OFFICIAL_USER_ID,
    TEST_USERS,
    VERIFYING_OFFICIAL_USER_ID,
    make_claims_examiner_headers,
    make_guardian_headers,
    make_league_admin_headers,
    make_league_official_headers,
    make_medical_reviewer_headers,
    make_program_admin_headers,
)

PROGRAM_ADMIN = TEST_USERS["program_administrator_headers"]
CLAIMS_EXAMINER = TEST_USERS["claims_examiner_headers"]
MEDICAL_REVIEWER = TEST_USERS["medical_reviewer_headers"]

CLASSIFICATION_PAYLOADS = {
    "baseball": create_sport_classification_payload,
    "cheer": cheer_u12_classification_payload,
    "swim": swim_u14_classification_payload,
}


# ---------------------------------------------------------------- logical clock
def set_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> None:
    """Move the server's logical clock to an exact UTC instant."""
    response = api_client.set_clock(to_iso8601, headers or PROGRAM_ADMIN)
    get_success_data(response)


# -------------------------------------------------------------------- master data
def create_league(**overrides: Any) -> Dict[str, Any]:
    response = api_client.create_league(create_league_payload(**overrides), PROGRAM_ADMIN)
    return get_success_data(response)


def create_sport_classification(
    classification: str = "baseball", **overrides: Any
) -> Dict[str, Any]:
    payload_builder = CLASSIFICATION_PAYLOADS[classification]
    response = api_client.create_sport_classification(
        payload_builder(**overrides), PROGRAM_ADMIN
    )
    return get_success_data(response)


def quote_policy(
    league_id: str, sport_classification_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api_client.create_league_policy(
        create_league_policy_payload(league_id, sport_classification_id, **overrides),
        PROGRAM_ADMIN,
    )
    return get_success_data(response)


def bind_policy(league_policy_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.bind_league_policy(league_policy_id, PROGRAM_ADMIN)
    )


def activate_policy(league_policy_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.activate_league_policy(league_policy_id, PROGRAM_ADMIN)
    )


def setup_active_policy(
    classification: str = "baseball",
    clock: Optional[str] = "2026-03-05T00:00:00Z",
    league_overrides: Optional[Dict[str, Any]] = None,
    sport_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tier 1 - a league, a sport classification and one ACTIVE policy term."""
    if clock is not None:
        set_clock(clock)
    league = create_league(**(league_overrides or {}))
    sport_classification = create_sport_classification(
        classification, **(sport_overrides or {})
    )
    policy = quote_policy(
        league["id"], sport_classification["id"], **(policy_overrides or {})
    )
    bind_policy(policy["id"])
    policy = activate_policy(policy["id"])
    return {
        "league": league,
        "sport_classification": sport_classification,
        "policy": policy,
        "league_headers": make_league_admin_headers(league["id"]),
    }


# ------------------------------------------------------------------ roster tier
def add_participant(league_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_participant(
            create_participant_payload(league_id, **overrides),
            make_league_admin_headers(league_id),
        )
    )


def enroll_participant(
    participant_id: str, league_policy_id: str, league_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(participant_id, league_policy_id, **overrides),
            make_league_admin_headers(league_id),
        )
    )


def add_family_health_plan(participant_id: str, **overrides: Any) -> Dict[str, Any]:
    """Recorded through the guardian portal, so the identity is the athlete's id."""
    return get_success_data(
        api_client.create_family_health_plan(
            create_family_health_plan_payload(participant_id, **overrides),
            make_guardian_headers(participant_id),
        )
    )


def setup_enrolled_athlete(
    bundle: Optional[Dict[str, Any]] = None,
    participant_overrides: Optional[Dict[str, Any]] = None,
    enrollment_overrides: Optional[Dict[str, Any]] = None,
    **setup_kwargs: Any,
) -> Dict[str, Any]:
    """Tier 2 - an ACTIVE policy plus one ENROLLED athlete on its roster."""
    bundle = dict(bundle or setup_active_policy(**setup_kwargs))
    participant = add_participant(
        bundle["league"]["id"], **(participant_overrides or {})
    )
    enrollment = enroll_participant(
        participant["id"],
        bundle["policy"]["id"],
        bundle["league"]["id"],
        **(enrollment_overrides or {}),
    )
    bundle["participant"] = participant
    bundle["enrollment"] = enrollment
    bundle["guardian_headers"] = make_guardian_headers(participant["id"])
    return bundle


# --------------------------------------------------------------- activity tier
def schedule_activity(
    league_policy_id: str, league_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_sanctioned_activity(
            create_sanctioned_activity_payload(league_policy_id, **overrides),
            make_league_admin_headers(league_id),
        )
    )


def sanction_activity(
    sanctioned_activity_id: str, official_user_id: str = SANCTIONING_OFFICIAL_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_sanction_decision(
            sanctioned_activity_id,
            {"decision": "SANCTION"},
            make_league_official_headers(official_user_id),
        )
    )


def decline_activity(
    sanctioned_activity_id: str, official_user_id: str = SANCTIONING_OFFICIAL_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_sanction_decision(
            sanctioned_activity_id,
            {"decision": "REJECT"},
            make_league_official_headers(official_user_id),
        )
    )


def setup_sanctioned_activity(
    bundle: Optional[Dict[str, Any]] = None,
    activity_overrides: Optional[Dict[str, Any]] = None,
    sanctioning_official_id: str = SANCTIONING_OFFICIAL_USER_ID,
    sanction: bool = True,
    **setup_kwargs: Any,
) -> Dict[str, Any]:
    """Tier 2 - an enrolled athlete plus one scheduled (optionally SANCTIONED)
    activity on the same policy."""
    bundle = dict(bundle or setup_enrolled_athlete(**setup_kwargs))
    activity = schedule_activity(
        bundle["policy"]["id"], bundle["league"]["id"], **(activity_overrides or {})
    )
    if sanction:
        activity = sanction_activity(activity["id"], sanctioning_official_id)
    bundle["activity"] = activity
    return bundle


# --------------------------------------------------------- injury report tier
def file_injury_report(
    enrollment_id: str,
    sanctioned_activity_id: str,
    league_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_injury_report(
            create_injury_report_payload(
                enrollment_id, sanctioned_activity_id, **overrides
            ),
            make_league_admin_headers(league_id),
        )
    )


def verify_injury_report(
    injury_report_id: str,
    official_user_id: str = VERIFYING_OFFICIAL_USER_ID,
    official_attestation: str = "the deciding official witnessed the injury",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_verification_decision(
            injury_report_id,
            {"decision": "VERIFY", "official_attestation": official_attestation},
            make_league_official_headers(official_user_id),
        )
    )


def reject_injury_report(
    injury_report_id: str,
    official_user_id: str = VERIFYING_OFFICIAL_USER_ID,
    official_attestation: str = "the report could not be corroborated",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_verification_decision(
            injury_report_id,
            {"decision": "REJECT", "official_attestation": official_attestation},
            make_league_official_headers(official_user_id),
        )
    )


def discover_claim(injury_report_id: str) -> Dict[str, Any]:
    """The claim opened by a verification is only discoverable through the list
    endpoint filtered on its originating report."""
    rows, _meta = validate_paginated(
        api_client.list_claims(CLAIMS_EXAMINER, {"injury_report_id": injury_report_id})
    )
    assert len(rows) == 1, (
        f"expected exactly 1 claim for injury report {injury_report_id}, got {len(rows)}"
    )
    return rows[0]


def setup_verified_claim(
    bundle: Optional[Dict[str, Any]] = None,
    report_overrides: Optional[Dict[str, Any]] = None,
    filing_clock: Optional[str] = "2026-07-12T00:00:00Z",
    verifying_official_id: str = VERIFYING_OFFICIAL_USER_ID,
    official_attestation: str = "the deciding official witnessed the injury",
    **setup_kwargs: Any,
) -> Dict[str, Any]:
    """Tier 3 - the whole chain down to one VERIFIED report and its open Claim."""
    bundle = dict(bundle or setup_sanctioned_activity(**setup_kwargs))
    if filing_clock is not None:
        set_clock(filing_clock)
    report = file_injury_report(
        bundle["enrollment"]["id"],
        bundle["activity"]["id"],
        bundle["league"]["id"],
        **(report_overrides or {}),
    )
    report = verify_injury_report(
        report["id"], verifying_official_id, official_attestation
    )
    bundle["injury_report"] = report
    bundle["claim"] = discover_claim(report["id"])
    return bundle


# ------------------------------------------------------------- billing tier
def record_provider_bill(claim_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_provider_bill(
            create_provider_bill_payload(claim_id, **overrides), CLAIMS_EXAMINER
        )
    )


def reprice_bill(provider_bill_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reprice_provider_bill(provider_bill_id, CLAIMS_EXAMINER)
    )


def setup_repriced_bill(
    bundle: Optional[Dict[str, Any]] = None,
    bill_overrides: Optional[Dict[str, Any]] = None,
    **setup_kwargs: Any,
) -> Dict[str, Any]:
    """Tier 4 - a verified claim carrying one REPRICED provider charge."""
    bundle = dict(bundle or setup_verified_claim(**setup_kwargs))
    bill = record_provider_bill(bundle["claim"]["id"], **(bill_overrides or {}))
    bundle["provider_bill"] = reprice_bill(bill["id"])
    return bundle


# -------------------------------------------------------- coordination tier
def request_eob(claim_id: str, note: str = "explanation of benefits requested") -> Dict[str, Any]:
    return get_success_data(
        api_client.request_eob(claim_id, {"note": note}, CLAIMS_EXAMINER)
    )


def confirm_no_other_coverage(
    claim_id: str,
    attestation_note: str = "no other health coverage in force for this athlete",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.confirm_no_other_coverage(
            claim_id, {"attestation_note": attestation_note}, CLAIMS_EXAMINER
        )
    )


def attest_no_coverage_on_plan(
    family_health_plan_id: str,
    note: str = "guardian attests the listed plan lapsed before the season",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_family_health_plan(
            family_health_plan_id,
            {"decision": "NO_COVERAGE_ATTESTED", "note": note},
            CLAIMS_EXAMINER,
        )
    )


def verify_family_plan(
    family_health_plan_id: str, note: str = "carrier confirmed the plan is in force"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_family_health_plan(
            family_health_plan_id, {"decision": "VERIFIED", "note": note}, CLAIMS_EXAMINER
        )
    )


def file_coordination_record(
    claim_id: str,
    provider_bill_id: str,
    family_health_plan_id: str,
    expected_claim_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_coordination_record(
            create_coordination_record_payload(
                claim_id,
                provider_bill_id,
                family_health_plan_id,
                expected_claim_version,
                **overrides,
            ),
            CLAIMS_EXAMINER,
        )
    )


# ------------------------------------------------- certification and payment
def certify_catastrophic(
    claim_id: str,
    certification_note: str = "permanent neurological deficit documented by the treating surgeon",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_catastrophic(
            claim_id, {"certification_note": certification_note}, MEDICAL_REVIEWER
        )
    )


def adjudicate_claim(
    claim_id: str, examiner_note: str = "determination ready"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_claim(
            claim_id, {"examiner_note": examiner_note}, CLAIMS_EXAMINER
        )
    )


def issue_benefit_payment(
    claim_id: str,
    provider_bill_id: str,
    amount_cents: int,
    layer: str = "BASE",
    payee_type: str = "PROVIDER",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_benefit_payment(
            create_benefit_payment_payload(
                claim_id,
                provider_bill_id,
                amount_cents,
                layer=layer,
                payee_type=payee_type,
            ),
            CLAIMS_EXAMINER,
        )
    )


def setup_approved_full_excess_claim(
    bundle: Optional[Dict[str, Any]] = None,
    bill_overrides: Optional[Dict[str, Any]] = None,
    **setup_kwargs: Any,
) -> Dict[str, Any]:
    """Tier 5 - a claim adjudicated on a full-excess footing, ready to be paid.

    The athlete carries no family health plan, so ruling other coverage out puts
    the claim on the FULL_EXCESS footing with its doubled deductible.
    """
    bundle = dict(bundle or setup_repriced_bill(bill_overrides=bill_overrides, **setup_kwargs))
    confirm_no_other_coverage(bundle["claim"]["id"])
    bundle["claim"] = adjudicate_claim(bundle["claim"]["id"])
    bundle["provider_bill"] = read_provider_bill(bundle["provider_bill"]["id"])
    return bundle


# -------------------------------------------------------------- read helpers
def read_league(league_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_league(league_id, PROGRAM_ADMIN))


def read_policy(league_policy_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_league_policy(league_policy_id, PROGRAM_ADMIN))


def read_loss_experience(league_policy_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_loss_experience(league_policy_id, PROGRAM_ADMIN)
    )


def read_participant(participant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_participant(participant_id, PROGRAM_ADMIN))


def read_enrollment(enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_enrollment(enrollment_id, PROGRAM_ADMIN))


def read_family_health_plan(family_health_plan_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_family_health_plan(family_health_plan_id, PROGRAM_ADMIN)
    )


def read_activity(sanctioned_activity_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_sanctioned_activity(sanctioned_activity_id, PROGRAM_ADMIN)
    )


def read_injury_report(injury_report_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_injury_report(injury_report_id, PROGRAM_ADMIN)
    )


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_claim(claim_id, CLAIMS_EXAMINER))


def read_provider_bill(provider_bill_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_provider_bill(provider_bill_id, CLAIMS_EXAMINER)
    )


def read_coordination_record(coordination_record_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_coordination_record(coordination_record_id, CLAIMS_EXAMINER)
    )


def read_benefit_payment(benefit_payment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_benefit_payment(benefit_payment_id, CLAIMS_EXAMINER)
    )


def list_rows(response) -> List[Dict[str, Any]]:
    """Return just the rows of a paginated list response."""
    rows, _meta = validate_paginated(response)
    return rows


def claims_for_report(injury_report_id: str) -> List[Dict[str, Any]]:
    return list_rows(
        api_client.list_claims(CLAIMS_EXAMINER, {"injury_report_id": injury_report_id})
    )


def bills_for_claim(claim_id: str) -> List[Dict[str, Any]]:
    return list_rows(api_client.list_provider_bills(CLAIMS_EXAMINER, {"claim_id": claim_id}))


def payments_for_claim(claim_id: str) -> List[Dict[str, Any]]:
    return list_rows(
        api_client.list_benefit_payments(CLAIMS_EXAMINER, {"claim_id": claim_id})
    )


def reports_for_enrollment(enrollment_id: str) -> List[Dict[str, Any]]:
    return list_rows(
        api_client.list_injury_reports(PROGRAM_ADMIN, {"enrollment_id": enrollment_id})
    )


def activities_for_policy(league_policy_id: str) -> List[Dict[str, Any]]:
    return list_rows(
        api_client.list_sanctioned_activities(
            PROGRAM_ADMIN, {"league_policy_id": league_policy_id}
        )
    )
