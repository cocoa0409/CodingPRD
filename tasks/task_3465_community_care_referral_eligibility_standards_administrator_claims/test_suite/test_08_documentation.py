"""Medical documentation: submission preconditions, review gate, the
reject-resubmit-accept cycle, the overdue suspension cascade and its clean
resolution, and the documentation gate on new referrals."""
from test_helpers import (
    TEST_USERS, api_client, validate_error, validate_paginated,
    validate_success,
    authorize_referral, create_extension_request,
    create_referral, create_referral_authorization_payload, create_station,
    create_tpa, create_veteran, get_authorization, list_extension_requests,
    make_documentation_overdue, make_provider_rep_headers, onboard_provider,
    review_documentation, review_documentation_payload, run_assessment,
    schedule_appointment, setup_docs_suspended_episode, setup_episode,
    setup_episode_with_completed_appointments, submit_documentation,
    submit_documentation_payload,
)

COORD = TEST_USERS["care_coordinator_headers"]


def test_documentation_submit_before_completion_returns_not_pending():
    """PRD §3.6: "Submission is only meaningful while the record is `AWAITED`
    or `OVERDUE` — if no record exists for the appointment, or it is already
    `RECEIVED` or `ACCEPTED`, the attempt fails with
    `ERR_DOCUMENTATION_NOT_PENDING` (HTTP 409)."
    PRD §3.6: "Every completed appointment creates exactly one **medical
    documentation** record, born `AWAITED` with its
    `referral_authorization_id` copied from the appointment as a read cache and
    its `deadline_at` set to the completion timestamp plus 30 days."

    Design: Corner/state_machines/documentation_submit_before_completion_returns_not_pending
    """
    env = setup_episode(authorized_visits=2)
    appt = schedule_appointment(env["authorization"])  # SCHEDULED: no record

    resp = api_client.submit_documentation(
        appt["id"], submit_documentation_payload(content_ref="too-early"),
        make_provider_rep_headers(env["provider"]["id"]),
    )
    validate_error(resp, "ERR_DOCUMENTATION_NOT_PENDING")

    docs, meta = validate_paginated(api_client.get_documentation(appt["id"], COORD))
    assert meta["total_count"] == 0 and docs == []


def test_doc_review_on_awaited_returns_not_reviewable():
    """PRD §3.6: "Only a `RECEIVED` record can be reviewed; anything else is
    rejected with `ERR_DOC_NOT_REVIEWABLE` (HTTP 409)."

    Design: Corner/validations/doc_review_on_awaited_returns_not_reviewable
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=2,
                                                    duration_days=300)
    doc = env["documentations"][0]
    assert doc["status"] == "AWAITED"

    resp = api_client.review_documentation(
        doc["id"], review_documentation_payload("ACCEPTED"), COORD
    )
    validate_error(resp, "ERR_DOC_NOT_REVIEWABLE")


def test_documentation_reject_resubmit_accept_cycle():
    """PRD §3.6: "Rejection loops the record back to `AWAITED`:
    `rejection_count` rises by one, `deadline_at` resets to the current logical
    clock plus a 15-day resubmission grace, and the cleared `content_ref`
    awaits a fresh bundle."
    PRD §3.6: "A successful submission moves the record to `RECEIVED` and
    stamps `content_ref` and `submitted_at`."

    Design: Difficulty/non_linear_state_machine/documentation_reject_resubmit_accept_cycle
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=2,
                                                    duration_days=300)
    appt = env["appointments"][0]
    provider = env["provider"]

    d1 = submit_documentation(appt, provider, content_ref="bundle-v1")
    assert d1["status"] == "RECEIVED"

    d2 = validate_success(api_client.review_documentation(
        d1["id"],
        review_documentation_payload("REJECTED",
                                     rejection_note="missing consult note"),
        COORD,
    ), 200)
    assert d2["status"] == "AWAITED"
    assert d2["rejection_count"] == 1
    # deadline_at resets to the review instant plus the 15-day grace (the
    # instant is contract-pinned; fractional-second formatting is not).
    from datetime import datetime
    assert datetime.fromisoformat(d2["deadline_at"].replace("Z", "+00:00")) == \
        datetime.fromisoformat("2026-09-16T00:00:00+00:00")
    # A rejected-but-not-overdue record never suspends the episode.
    assert get_authorization(env["authorization"]["id"])["status"] == "ACTIVE"

    d3 = submit_documentation(appt, provider, content_ref="bundle-v2")
    assert d3["status"] == "RECEIVED"

    d4 = review_documentation(d1["id"], "ACCEPTED")
    assert d4["status"] == "ACCEPTED"
    assert get_authorization(env["authorization"]["id"])["status"] == "ACTIVE"


def test_docs_suspension_clears_to_remembered_state_on_accept():
    """PRD §3.6: "When the record was `OVERDUE`, the episode does not heal on
    submission alone: the authorization stays `DOCS_SUSPENDED` until a reviewer
    accepts the bundle."
    PRD §3.6: "Acceptance is the episode's healing event: when the accepted
    record leaves no other documentation of the authorization in `AWAITED`,
    `OVERDUE`, or `RECEIVED`, a `DOCS_SUSPENDED` authorization returns to the
    state remembered in `docs_suspension_return_state` (`AUTHORIZED` or
    `ACTIVE`), and an `EXPIRED` or `EXHAUSTED` authorization closes."

    Design: Corner/validations/docs_suspension_clears_to_remembered_state_on_accept
    """
    env = setup_docs_suspended_episode(authorized_visits=2, duration_days=300)
    assert env["authorization"]["status"] == "DOCS_SUSPENDED"

    late = submit_documentation(env["appointment"], env["provider"],
                                content_ref="late-bundle")
    assert late["status"] == "RECEIVED"  # OVERDUE submissions still accepted
    mid = get_authorization(env["authorization"]["id"])
    assert mid["status"] == "DOCS_SUSPENDED"  # not healed by submission alone

    review_documentation(late["id"], "ACCEPTED")
    end = get_authorization(env["authorization"]["id"])
    assert end["status"] == "ACTIVE"  # remembered return state restored


def test_doc_overdue_suspends_authorization_denies_extensions():
    """PRD §3.6: "On each logical-clock set, every `AWAITED` record whose
    `deadline_at` has passed becomes `OVERDUE`, and that transition cascades:
    an authorization in `AUTHORIZED` or `ACTIVE` moves to `DOCS_SUSPENDED` with
    its current state remembered in `docs_suspension_return_state`, and every
    `PENDING` extension request of the authorization is auto-denied with
    `denial_reason` `DOCS_OVERDUE`."

    Design: Difficulty/transitive_cascade/doc_overdue_suspends_authorization_denies_extensions
    """
    env = setup_episode(authorized_visits=2, duration_days=300)
    auth = env["authorization"]
    appt = schedule_appointment(auth)
    ext = create_extension_request(auth, requested_visits=3,
                                   requested_extra_days=10)

    appt, doc = make_documentation_overdue(appt, env["provider"])
    assert doc["status"] == "OVERDUE"

    after = get_authorization(auth["id"])
    assert after["status"] == "DOCS_SUSPENDED"
    assert after["docs_suspension_return_state"] == "ACTIVE"
    assert after["end_date_exclusive"] == "2027-07-02"  # 2026-09-05 + 300 days

    exts, _meta = list_extension_requests(auth["id"])
    assert exts[0]["id"] == ext["id"]
    assert exts[0]["status"] == "DENIED"
    assert exts[0]["denial_reason"] == "DOCS_OVERDUE"


def test_referral_create_blocked_by_overdue_documentation():
    """PRD §3.3: "No documentation record on any of the veteran's
    authorizations — not just the new one — may be `OVERDUE` (else
    `ERR_DOCS_OUTSTANDING`)."

    Design: Corner/validations/referral_create_blocked_by_overdue_documentation
    """
    station = create_station(service_codes=["PT_EVAL", "CARD"])
    tpa = create_tpa()
    provider = onboard_provider(tpa, service_codes=["PT_EVAL", "CARD"])
    veteran = create_veteran(station, priority_group=3)

    a1 = run_assessment(veteran["id"])
    auth1 = create_referral(veteran, a1, provider, authorized_visits=2,
                            duration_days=300, start_date="2026-09-05")
    auth1 = authorize_referral(auth1)
    appt = schedule_appointment(auth1)
    _appt, doc = make_documentation_overdue(appt, provider)
    assert doc["status"] == "OVERDUE"

    # A fresh eligible assessment (choice granted, PG-3) for another service
    # does not clear the documentation gate.
    a2 = run_assessment(veteran["id"], service_code="CARD",
                        service_category="SPECIALTY_CARE",
                        geo_classification="URBAN", choice_requested=True,
                        expect_eligible=True)
    resp = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            veteran["id"], a2["id"], provider["id"], service_code="CARD",
            authorized_visits=2, duration_days=60, start_date="2026-10-10",
        ),
        COORD,
    )
    validate_error(resp, "ERR_DOCS_OUTSTANDING")
