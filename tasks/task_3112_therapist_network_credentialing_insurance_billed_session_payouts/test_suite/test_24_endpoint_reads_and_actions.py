"""Action endpoints, filtered reads and the reverse-reachability read that links
a claim to the payout line carrying its earnings."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EARLY,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    assert_payout_line,
    attach_billable_clinician,
    complete_session,
    create_malpractice_policy_payload,
    get_clinician,
    make_clinician,
    make_license,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    open_and_lock_batch,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000004"


def test_submitting_for_credentialing_needs_both_a_license_and_a_malpractice_policy():
    """PRD §3.1: "Once both a license and a malpractice policy are on file, a
    `ComplianceOfficer` may submit the clinician for credentialing, moving
    `status` from `ONBOARDING` to `CREDENTIALING`."

    Design: Corner/endpoints/clinician_submit_credentials_transitions_to_credentialing
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()

    early = api_client.submit_credentials(clinician["id"], COMPLIANCE)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)
    assert early.status_code == 409
    assert get_clinician(clinician["id"])["status"] == "ONBOARDING"

    make_license(clinician["id"], license_number="LCSW-CA-55401")
    validate_success(
        api_client.create_malpractice_policy(
            clinician["id"], create_malpractice_policy_payload(), OPS
        ),
        201,
    )
    advanced = validate_success(api_client.submit_credentials(clinician["id"], COMPLIANCE))
    assert advanced["status"] == "CREDENTIALING"
    assert advanced["billing_posture"] == "FROZEN", (
        "PRD §2.4: FROZEN when `enrolled_payer_count` is 0, whatever the "
        "license's verification state"
    )


def test_the_clinician_payout_line_read_aggregates_across_batches_and_filters_by_status():
    """PRD §3.6: "At lock time the system materialises one line per clinician who has
    at least one eligible session in the window, and each line is bound to the
    batch through `payout_batch_id` and carries that clinician's `session_ids`,
    `claim_ids`, `gross_cents`, `adjustment_cents` and `net_cents` under whichever
    payout variant is active for that clinician."
    PRD §3.6: "the total gross is the sum of the included lines' `gross_cents`,
    the total adjustment is the signed sum of their `adjustment_cents`, the total
    net is the sum of their `net_cents`, and the line count is the number of
    included lines."

    Design: Corner/endpoints/clinician_payout_lines_read_returns_one_row_across_batches
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])

    first = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], first["id"])
    set_clock("2026-06-03T18:00:00Z")
    complete_session(clinician["id"], first["id"])

    set_clock("2026-06-16T18:00:00Z")
    later = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-16T16:00:00Z", "2026-06-16T17:00:00Z"
    )
    add_signed_note(clinician["id"], later["id"])
    complete_session(clinician["id"], later["id"])

    set_clock("2026-06-09T00:00:00Z")
    batch = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")

    pending, pending_meta = validate_paginated(
        api_client.list_clinician_payout_lines(
            clinician["id"], OPS, {"line_status": "PENDING", "limit": 10, "offset": 0}
        )
    )
    assert len(pending) == 1 and pending_meta["total_count"] == 1

    all_lines, all_meta = validate_paginated(
        api_client.list_clinician_payout_lines(clinician["id"], OPS, {"limit": 10, "offset": 0})
    )
    assert len(all_lines) == 1 and all_meta["total_count"] == 1, (
        "only the first period has been locked"
    )

    batch_lines, batch_meta = validate_paginated(
        api_client.list_payout_batch_lines(batch["id"], OPS, {"limit": 10, "offset": 0})
    )
    assert len(batch_lines) == 1 and batch_meta["total_count"] == 1
    assert_payout_line(pending[0])
    assert pending[0]["gross_cents"] == 15_000
    assert pending[0]["adjustment_cents"] == 0
    assert pending[0]["net_cents"] == 15_000

    paid, paid_meta = validate_paginated(
        api_client.list_payout_batch_lines(
            batch["id"], OPS, {"line_status": "PAID", "limit": 10, "offset": 0}
        )
    )
    assert paid == [] and paid_meta["total_count"] == 0, (
        "the batch was locked but never paid"
    )


def test_each_declared_rate_filter_narrows_the_schedule_independently_and_a_match_of_none_is_not_a_404():
    """PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    sorted by creation timestamp in ascending order."
    PRD §3.2: "Two rows may not share the same combination of payer, rate-set
    version, license type, geography, CPT code and `effective_from`; a duplicate
    is rejected with `ERR_DUPLICATE_RATE` at HTTP 409."

    Design: Corner/endpoints/payer_rates_read_supports_every_declared_filter
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000, rate_set_version=1, geography="CA", cpt_code="90837")
    make_rate(payer["id"], rate_cents=12_000, rate_set_version=1, geography="CA", cpt_code="90834")
    make_rate(payer["id"], rate_cents=13_000, rate_set_version=1, license_type="LMFT",
              geography="TX", cpt_code="90837")
    duplicate = api_client.create_payer_rate(
        payer["id"],
        {
            "rate_set_version": 1,
            "license_type": "LCSW",
            "geography": "CA",
            "cpt_code": "90837",
            "rate_cents": 15_000,
            "effective_from": "2026-01-01T00:00:00Z",
        },
        OPS,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RATE)
    assert duplicate.status_code == 409

    ca, ca_meta = validate_paginated(
        api_client.list_payer_rates(payer["id"], OPS, {"geography": "CA", "limit": 10, "offset": 0})
    )
    assert len(ca) == 2 and ca_meta["total_count"] == 2

    lmft, lmft_meta = validate_paginated(
        api_client.list_payer_rates(payer["id"], OPS, {"license_type": "LMFT", "limit": 10, "offset": 0})
    )
    assert len(lmft) == 1 and lmft_meta["total_count"] == 1

    unmatched, unmatched_meta = validate_paginated(
        api_client.list_payer_rates(payer["id"], OPS, {"cpt_code": "90999", "limit": 10, "offset": 0})
    )
    assert unmatched == [] and unmatched_meta["total_count"] == 0
    assert api_client.list_payer_rates(
        payer["id"], OPS, {"cpt_code": "90999"}
    ).json()["response_type"] == "array"

    every, every_meta = validate_paginated(
        api_client.list_payer_rates(payer["id"], OPS, {"limit": 10, "offset": 0})
    )
    assert len(every) == 3 and every_meta["total_count"] == 3


def test_a_payer_status_patch_cascades_to_every_enrollment_and_clinician_it_holds():
    """PRD §3.8: "Moving a payer to `SUSPENDED_AT_PAYER` cascades in three hops.
    First, every enrollment with that payer in `EFFECTIVE` status moves to
    `SUSPENDED`."
    PRD §3.6: "Returning the payer to `ACTIVE` does not run the cascade in
    reverse: enrollments are not auto-restored, and each one stays `SUSPENDED`
    until an `OpsAdmin` reinstates it individually."

    Design: Corner/endpoints/payer_status_patch_cascades_through_enrollments_to_clinician_posture
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    first = attach_billable_clinician(payer["id"], full_name="Dana Reyes")
    attach_billable_clinician(
        payer["id"], full_name="Zara Whitfield", license_number="LCSW-CA-90211"
    )

    validate_success(api_client.patch_payer(payer["id"], {"status": "SUSPENDED_AT_PAYER"}, OPS))
    suspended, meta = validate_paginated(
        api_client.list_payer_enrollments_for_payer(
            payer["id"], OPS, {"status": "SUSPENDED", "limit": 10, "offset": 0}
        )
    )
    assert len(suspended) == 2 and meta["total_count"] == 2

    frozen, frozen_meta = validate_paginated(
        api_client.list_clinicians(OPS, {"billing_posture": "FROZEN", "limit": 10, "offset": 0})
    )
    assert len(frozen) == 2 and frozen_meta["total_count"] == 2

    scoped, scoped_meta = validate_paginated(
        api_client.list_payer_enrollments(OPS, {"clinician_id": first["clinician"]["id"]})
    )
    assert len(scoped) == 1 and scoped[0]["status"] == "SUSPENDED"

    validate_success(api_client.patch_payer(payer["id"], {"status": "ACTIVE"}, OPS))
    still, still_meta = validate_paginated(
        api_client.list_payer_enrollments_for_payer(
            payer["id"], OPS, {"status": "SUSPENDED", "limit": 10, "offset": 0}
        )
    )
    assert len(still) == 2 and still_meta["total_count"] == 2, (
        "restoring the payer does not auto-restore its enrollments"
    )


def test_session_creation_reports_the_missing_clinician_before_it_considers_the_patient():
    """PRD §2.8: "The first identifier that does not resolve ends the request"
    PRD §2.9: "Existence third, in the left-to-right and path-before-body order
    given in §2.8."

    Design: Corner/endpoints/session_create_rejects_a_missing_clinician_before_touching_the_patient
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    clinician = make_clinician()
    patient = make_verified_patient(payer["id"])

    missing_clinician = api_client.create_session(
        {
            "clinician_id": NON_EXISTENT,
            "patient_id": patient["id"],
            "scheduled_start": "2026-06-10T16:00:00Z",
            "scheduled_end": "2026-06-10T17:00:00Z",
            "cpt_code": "90837",
            "modality": "VIDEO",
        },
        OPS,
    )
    validate_error(missing_clinician, ApiErrorId.ERR_CLINICIAN_NOT_FOUND)

    missing_patient = api_client.create_session(
        {
            "clinician_id": clinician["id"],
            "patient_id": "00000000-0000-4000-8000-000000000005",
            "scheduled_start": "2026-06-10T16:00:00Z",
            "scheduled_end": "2026-06-10T17:00:00Z",
            "cpt_code": "90837",
            "modality": "VIDEO",
        },
        OPS,
    )
    validate_error(missing_patient, ApiErrorId.ERR_PATIENT_NOT_FOUND)

    sessions, meta = validate_paginated(api_client.list_sessions(OPS, {"limit": 10, "offset": 0}))
    assert sessions == [] and meta["total_count"] == 0, (
        "neither rejected request persisted a row"
    )


def test_the_claim_to_line_read_returns_an_empty_array_before_the_lock_and_the_carrying_line_after():
    """PRD §3.6: "A claim is associated with the line that carries its earnings
    through the claim's own `assigned_payout_line_id`, which is null until a line
    has taken the claim on."

    Design: Corner/endpoints/claim_payout_line_read_finds_the_line_carrying_a_claims_earning
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = validate_success(api_client.create_claim({"session_id": session["id"]}, OPS), 201)
    validate_success(api_client.adjudicate_claim(claim["id"], {"outcome": "PAID"}, OPS))

    set_clock("2026-06-09T00:00:00Z")
    batch = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY",
                                lock=False)

    before, before_meta = validate_paginated(
        api_client.get_claim_payout_line(claim["id"], OPS)
    )
    assert before == [] and before_meta["total_count"] == 0, (
        "the link is only made at lock time"
    )

    validate_success(api_client.lock_payout_batch(batch["id"], OPS))
    after, after_meta = validate_paginated(api_client.get_claim_payout_line(claim["id"], OPS))
    assert len(after) == 1 and after_meta["total_count"] == 1
    assert after[0]["clinician_id"] == clinician["id"]
    assert after[0]["gross_cents"] == 15_000
    assert claim["id"] in after[0]["claim_ids"]
    assert api_client.get_claim_payout_line(claim["id"], OPS).json()["response_type"] == "array"