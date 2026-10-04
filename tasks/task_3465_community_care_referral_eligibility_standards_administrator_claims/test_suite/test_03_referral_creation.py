"""Referral authorization creation: server-derived fields and the creation
gates (superseded assessment, ineligible assessment, uncredentialed provider,
service-code/provider referential checks, episode overlap)."""
from test_helpers import (
    TEST_USERS, api_client, validate_error,
    assert_referral_authorization,
    create_referral, create_referral_authorization_payload,
    create_eligible_assessment, create_station, create_tpa, create_veteran,
    onboard_provider, run_assessment, setup_episode,
)

COORD = TEST_USERS["care_coordinator_headers"]


def test_referral_derived_fields_computed_at_creation():
    """PRD §3.3: "At creation the authorization denormalizes its administrative
    context: `tpa_id` is copied from the provider's administering
    administrator, and `scheduling_responsibility` is derived as `TPA` exactly
    when the provider's `contract_scheduling` is `TPA`, otherwise `VAMC`."
    PRD §3.3: "The visit ledger opens with `extended_visits`, `reserved_visits`,
    and `completed_visits` at zero and `remaining_visits` equal to
    `authorized_visits`."
    PRD §3.3: "The episode window is half-open on calendar dates: it includes
    `start_date` and excludes `end_date_exclusive`, which is computed as
    `start_date` plus `duration_days` plus the sum of `requested_extra_days`
    over that authorization's approved extensions."

    Design: Corner/entities/referral_derived_fields_computed_at_creation
    """
    env = setup_episode(authorize=False, authorized_visits=4, duration_days=30)
    auth = env["authorization"]

    assert_referral_authorization(auth)
    assert auth["tpa_id"] == env["tpa"]["id"]
    assert auth["scheduling_responsibility"] == "TPA"
    assert auth["end_date_exclusive"] == "2026-10-05"  # 2026-09-05 + 30 days
    assert auth["status"] == "PENDING_REVIEW"
    assert auth["remaining_visits"] == 4
    assert auth["reserved_visits"] == 0
    assert auth["completed_visits"] == 0
    assert auth["extended_visits"] == 0
    assert auth["authorized_at"] is None


def test_referral_with_superseded_assessment_rejected():
    """PRD §3.3: "The referenced assessment must still be `CURRENT` (a
    superseded one is rejected with `ERR_ASSESSMENT_SUPERSEDED`) and must have
    `eligible` true (else `ERR_SERVICE_NOT_ELIGIBLE`)."

    Design: Corner/validations/referral_with_superseded_assessment_rejected
    """
    station = create_station()
    tpa = create_tpa()
    provider = onboard_provider(tpa)
    veteran = create_veteran(station)
    a1 = run_assessment(veteran["id"])
    run_assessment(veteran["id"])  # same service_code: supersedes a1

    resp = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            veteran["id"], a1["id"], provider["id"]
        ),
        COORD,
    )
    validate_error(resp, "ERR_ASSESSMENT_SUPERSEDED")


def test_referral_create_ineligible_returns_service_not_eligible():
    """PRD §3.3: "The referenced assessment must still be `CURRENT` (a
    superseded one is rejected with `ERR_ASSESSMENT_SUPERSEDED`) and must have
    `eligible` true (else `ERR_SERVICE_NOT_ELIGIBLE`)."

    Design: Corner/validations/referral_create_ineligible_returns_service_not_eligible
    """
    station = create_station()
    tpa = create_tpa()
    provider = onboard_provider(tpa)
    veteran = create_veteran(station)
    assessment = run_assessment(veteran["id"], geo_classification="RURAL",
                                expect_eligible=False)

    resp = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            veteran["id"], assessment["id"], provider["id"]
        ),
        COORD,
    )
    validate_error(resp, "ERR_SERVICE_NOT_ELIGIBLE")


def test_referral_create_pending_provider_returns_not_credentialed():
    """PRD §3.3: "The provider must be `CREDENTIALED` (else
    `ERR_PROVIDER_NOT_CREDENTIALED`)."

    Design: Corner/validations/referral_create_pending_provider_returns_not_credentialed
    """
    station = create_station()
    tpa = create_tpa()
    provider = onboard_provider(tpa, credential=False)  # stays PENDING
    assert provider["credentialing_status"] == "PENDING"
    veteran = create_veteran(station)
    assessment = create_eligible_assessment(veteran["id"])

    resp = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            veteran["id"], assessment["id"], provider["id"]
        ),
        COORD,
    )
    validate_error(resp, "ERR_PROVIDER_NOT_CREDENTIALED")


def test_referral_service_code_and_provider_service_mismatch():
    """PRD §3.3: "The requested `service_code` must equal the assessment's
    `service_code` (else `ERR_SERVICE_CODE_MISMATCH`), and the provider's
    contracted `service_codes` must contain it (else
    `ERR_PROVIDER_SERVICE_MISMATCH`)."

    Design: Corner/validations/referral_service_code_and_provider_service_mismatch
    """
    station = create_station(service_codes=["PT_EVAL", "CARD"])
    tpa = create_tpa()
    provider = onboard_provider(tpa, name="Prov CardOnly",
                                service_codes=["CARD"])
    veteran = create_veteran(station)
    assessment = create_eligible_assessment(veteran["id"])  # PT_EVAL

    resp_mismatch = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            veteran["id"], assessment["id"], provider["id"], service_code="CARD"
        ),
        COORD,
    )
    validate_error(resp_mismatch, "ERR_SERVICE_CODE_MISMATCH")

    resp_provider = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            veteran["id"], assessment["id"], provider["id"],
            service_code="PT_EVAL"
        ),
        COORD,
    )
    validate_error(resp_provider, "ERR_PROVIDER_SERVICE_MISMATCH")


def test_episode_overlap_rejected_but_adjacency_allowed():
    """PRD §3.3: "And no non-terminal authorization may already exist for the
    same veteran and the same `service_code` whose half-open episode window
    overlaps the requested window (else `ERR_EPISODE_OVERLAP`)."
    PRD §2.7: "Calendar arithmetic (episode windows, filing windows, timeliness
    lags) operates on whole calendar dates, and every window in this contract
    is half-open: the start date is included, the end date is excluded."

    Design: Corner/state_machines/episode_overlap_rejected_but_adjacency_allowed
    """
    env = setup_episode(authorize=False, authorized_visits=2, duration_days=30)
    # Existing episode: [2026-09-05, 2026-10-05), PENDING_REVIEW (non-terminal).
    resp_overlap = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            env["veteran"]["id"], env["assessment"]["id"],
            env["provider"]["id"], start_date="2026-10-04",
            authorized_visits=2, duration_days=30,
        ),
        COORD,
    )
    validate_error(resp_overlap, "ERR_EPISODE_OVERLAP")

    adjacent = create_referral(
        env["veteran"], env["assessment"], env["provider"],
        authorized_visits=2, duration_days=30, start_date="2026-10-05",
    )
    assert adjacent["status"] == "PENDING_REVIEW"
    assert adjacent["end_date_exclusive"] == "2026-11-04"
