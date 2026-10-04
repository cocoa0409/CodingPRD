"""Claim validation: pipeline precedence (state before temporal), the
inclusive 180-day timely-filing boundary, episode-window and matching-visit
referential rules, the fiscal floor, and the resubmission cap."""
from test_helpers import (
    api_client, validate_error,
    adjudicate_claim, cancel_referral, claim_service_line, complete_appointment,
    create_claim_for_appointment, create_claim_payload, get_claim, get_tpa,
    list_claims, make_provider_rep_headers, resubmit_claim,
    resubmit_claim_payload, schedule_appointment, set_clock, setup_episode,
    setup_episode_with_completed_appointments,
)


def test_claim_state_error_beats_untimely_filing():
    """PRD §2.8: "Stages are evaluated in the order below, and the first
    failing stage produces the response — an earlier failure masks all later
    checks, so the error a caller receives always identifies the earliest
    unmet obligation:"
    PRD §2.8: "Claim creation requires the authorization to be in `ACTIVE`,
    `EXPIRED`, `EXHAUSTED`, or `CLOSED` (else `ERR_REFERRAL_NOT_ACTIVE`) and
    the administering network to be `ACTIVE` (else `ERR_TPA_SUSPENDED`)"
    PRD §3.7: "the number of days from `service_date` to the submission date
    must be at most 180 — the window is inclusive, so exactly 180 days files
    on time and 181 or more is rejected with `ERR_UNTIMELY_FILED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_error_beats_untimely_filing
    """
    # One spare visit keeps the authorization ACTIVE after the completion;
    # PRD §3.3 permits cancel only from AUTHORIZED, ACTIVE, or DOCS_SUSPENDED,
    # so an exhausted (remaining_visits == 0) episode could not be cancelled.
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=2,
                                                    duration_days=60)
    auth = env["authorization"]
    cancel_referral(auth)  # CANCELLED
    set_clock("2027-03-06T00:00:00Z")  # 181 days after the 2026-09-06 service

    # Both the state gate (CANCELLED) and timely filing (181 days) fail; the
    # earlier lifecycle stage wins.
    resp = api_client.create_claim(
        create_claim_payload(auth["id"], "2026-09-06"),
        make_provider_rep_headers(env["provider"]["id"]),
    )
    validate_error(resp, "ERR_REFERRAL_NOT_ACTIVE")

    _claims, meta = list_claims({"referral_authorization_id": auth["id"]})
    assert meta["total_count"] == 0


def test_timely_filing_day_180_accepted_day_181_rejected():
    """PRD §3.7: "Timely filing binds the paperwork to the care: the number of
    days from `service_date` to the submission date must be at most 180 — the
    window is inclusive, so exactly 180 days files on time and 181 or more is
    rejected with `ERR_UNTIMELY_FILED` (HTTP 422)."
    PRD §3.7: "Resubmission re-validates rather than grandfathering: timely
    filing is re-checked against the claim's `service_date` at resubmission
    time (else `ERR_UNTIMELY_FILED`), the service date must still sit inside
    the episode window and match a completed appointment as at creation (else
    `ERR_SERVICE_DATE_OUTSIDE_EPISODE` or
    `ERR_NO_MATCHING_COMPLETED_APPOINTMENT`), the replacement lines must again
    pass fiscal sanity (else `ERR_AMOUNT_INVALID`), and the network must be
    `ACTIVE` (else `ERR_TPA_SUSPENDED`)."

    Design: Difficulty/boundary_precision_check/timely_filing_day_180_accepted_day_181_rejected
    """
    env = setup_episode(authorized_visits=1, duration_days=300)
    auth = env["authorization"]
    appt = schedule_appointment(auth)
    complete_appointment(appt, env["provider"])

    # Day 180 after the 2026-09-06 service date: filing is still on time.
    set_clock("2027-03-05T00:00:00Z")
    claim = create_claim_for_appointment(auth, appt, env["provider"],
                                         service_date="2026-09-06")
    assert claim["status"] == "RECEIVED"

    denied = adjudicate_claim(claim["id"], env["tpa"], "DENIED",
                              "CLINICAL_REVIEW")
    assert denied["status"] == "DENIED"

    # Day 181: the re-check at resubmission time rejects.
    set_clock("2027-03-06T00:00:00Z")
    resp = api_client.resubmit_claim(
        claim["id"], resubmit_claim_payload(),
        make_provider_rep_headers(env["provider"]["id"]),
    )
    validate_error(resp, "ERR_UNTIMELY_FILED")
    assert get_claim(claim["id"])["status"] == "DENIED"


def test_claim_service_date_outside_episode_rejected():
    """PRD §3.7: "The `service_date` must fall inside the half-open episode
    window, else `ERR_SERVICE_DATE_OUTSIDE_EPISODE` (HTTP 422)."

    Design: Corner/validations/claim_service_date_outside_episode_rejected
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=2,
                                                    duration_days=30)
    # Window [2026-09-05, 2026-10-05); 2026-08-20 precedes it (and is timely).
    resp = api_client.create_claim(
        create_claim_payload(env["authorization"]["id"], "2026-08-20"),
        make_provider_rep_headers(env["provider"]["id"]),
    )
    validate_error(resp, "ERR_SERVICE_DATE_OUTSIDE_EPISODE")


def test_claim_without_matching_completed_appointment_rejected():
    """PRD §3.7: "The claim must correspond to delivered care: a `COMPLETED`
    appointment on the same authorization whose scheduled date equals the
    `service_date` must exist, else `ERR_NO_MATCHING_COMPLETED_APPOINTMENT`
    (HTTP 422)."

    Design: Corner/validations/claim_without_matching_completed_appointment_rejected
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=2,
                                                    duration_days=60)
    # In-window and timely, but the only COMPLETED appointment is 2026-09-06.
    resp = api_client.create_claim(
        create_claim_payload(env["authorization"]["id"], "2026-09-10"),
        make_provider_rep_headers(env["provider"]["id"]),
    )
    validate_error(resp, "ERR_NO_MATCHING_COMPLETED_APPOINTMENT")


def test_claim_amount_invalid_units_zero():
    """PRD §2.8: "Every claim service line must have `units` of at least 1 and
    a positive `unit_billed_cents`; otherwise `ERR_AMOUNT_INVALID`."

    Design: Corner/validations/claim_amount_invalid_units_zero
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=1)
    resp = api_client.create_claim(
        create_claim_payload(
            env["authorization"]["id"], "2026-09-06",
            [claim_service_line(units=0)],
        ),
        make_provider_rep_headers(env["provider"]["id"]),
    )
    validate_error(resp, "ERR_AMOUNT_INVALID")


def test_claim_resubmission_limit_third_resubmit_rejected():
    """PRD §3.7: "The owning `ProviderRep` may resubmit a `DENIED` claim with
    corrected `service_lines`, cycling it back to `RECEIVED` — at most twice
    per claim: a resubmission attempted when `resubmit_count` has already
    reached 2 is rejected with `ERR_RESUBMISSION_LIMIT` (HTTP 409), and
    resubmitting from any status but `DENIED` fails with `ERR_INVALID_STATE`."
    PRD §3.1: "On every claim-finalization event — an adjudication decided
    `PAID`, an adjudication decided `DENIED`, or a cascade auto-denial — the
    administrator's `adjudicated_events` rises by one, and `denied_events`
    rises by one whenever the outcome was a denial; resubmissions and payment
    reversals do not move either counter."

    Design: Corner/validations/claim_resubmission_limit_third_resubmit_rejected
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=1,
                                                    duration_days=300)
    claim = create_claim_for_appointment(
        env["authorization"], env["appointments"][0], env["provider"]
    )
    provider, tpa = env["provider"], env["tpa"]

    for reason in ("CLINICAL_REVIEW", "DUPLICATE", "OTHER"):
        adjudicate_claim(claim["id"], tpa, "DENIED", reason)
        if reason != "OTHER":
            resubmit_claim(claim["id"], provider)

    # resubmit_count == 2 == RESUBMISSION_MAX: the third resubmit is rejected.
    resp = api_client.resubmit_claim(
        claim["id"], resubmit_claim_payload(),
        make_provider_rep_headers(provider["id"]),
    )
    validate_error(resp, "ERR_RESUBMISSION_LIMIT")

    tpa_after = get_tpa(tpa["id"])
    assert tpa_after["adjudicated_events"] == 3
    assert tpa_after["denied_events"] == 3
