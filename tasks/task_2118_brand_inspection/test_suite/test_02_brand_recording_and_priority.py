"""Filing a brand, examining it, recording it, and the priority contest."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_brand_application,
    assert_brand_registration,
    assert_instant_equals,
    begin_examination,
    create_brand_application_payload,
    create_renewal_application_payload,
    enrol_owner,
    file_brand_application,
    file_renewal,
    make_brand_recorder_headers,
    make_livestock_owner_headers,
    read_application,
    read_registration,
    record_application,
    record_brand,
    run_delinquency_sweep,
    set_clock,
    setup_correction_cycle_at_ceiling,
    setup_prior_use_priority_contest,
    setup_revoked_prior_registration_renewal,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
EXAMINER = make_brand_recorder_headers("recorder-01")
RECORDER = make_brand_recorder_headers("recorder-02")


# ─── Recording priority and the prior-use affidavit ───────────────────────────

def test_backdated_filing_takes_priority_rank_one_and_demotes_the_incumbent(api):
    """PRD §3.3: "This is exactly why the prior-use affidavit matters — a producer who
    files second but proves ten years of documented prior use is backdated 3,650 days
    and takes the front of the queue from an incumbent who filed last month."
    PRD §3.3: "Whenever a record is created, `priority_rank` is re-derived for every
    `ACTIVE` or `GRACE` member of the group, walking them in the group's own sort order:
    `effective_priority_at` ascending, then `correction_rounds` ascending, then
    `created_at` ascending."

    Design: Difficulty/combinatorial_formula/brand_priority_backdating_caps_and_gates_prior_use
    """
    scenario = setup_prior_use_priority_contest()
    incumbent = scenario["incumbent_registration"]
    assert_instant_equals(
        incumbent["effective_priority_at"], "2026-08-01T00:00:00Z", "incumbent priority"
    )
    assert incumbent["priority_rank"] == 1

    recorded = validate_success(
        api.record_application(scenario["rival_application"]["id"], RECORDER), 201
    )

    assert_brand_registration(recorded)
    assert_instant_equals(
        recorded["effective_priority_at"], "2016-08-04T00:00:00Z", "effective_priority_at"
    )
    assert recorded["priority_rank"] == 1, (
        f"the backdated filing leads the group, got rank {recorded['priority_rank']}"
    )
    assert recorded["status"] == "ACTIVE"

    demoted = read_registration(incumbent["id"])
    assert demoted["priority_rank"] == 2, (
        f"the incumbent is demoted one rank, got {demoted['priority_rank']}"
    )
    assert demoted["status"] == "ACTIVE"


def test_prior_use_credit_is_capped_at_ten_years_and_gated_by_the_affidavit(api):
    """PRD §3.2: "That priority instant is the whole point of the prior-use affidavit:
    the board first determines the credited years, which is the smaller of the
    applicant's `documented_prior_use_years` and the statutory cap of 10 years when
    `prior_use_affidavit_on_file` is true, and is zero years whenever the affidavit is
    absent — an applicant who claims forty years of prior use without an affidavit is
    credited nothing at all."
    PRD §3.2: "The credited years are then converted to days at 365 days per year, and
    `effective_priority_at` is `original_filed_at` moved backward by that many days,
    preserving the original time of day."

    Design: Difficulty/combinatorial_formula/brand_priority_backdating_caps_and_gates_prior_use
    """
    owner = enrol_owner("Cap And Gate Ranch", contact_email="capgate@example.test")
    set_clock("2026-08-02T00:00:00Z")

    with_affidavit = file_brand_application(
        owner["id"],
        brand_symbol="CAP-A",
        position_code="LEFT_RIB",
        documented_prior_use_years=12,
        prior_use_affidavit_on_file=True,
    )
    without_affidavit = file_brand_application(
        owner["id"],
        brand_symbol="CAP-B",
        position_code="RIGHT_RIB",
        documented_prior_use_years=40,
        prior_use_affidavit_on_file=False,
    )

    assert_brand_application(with_affidavit)
    assert_instant_equals(
        with_affidavit["original_filed_at"], "2026-08-02T00:00:00Z", "original_filed_at"
    )
    assert_instant_equals(
        with_affidavit["effective_priority_at"],
        "2016-08-04T00:00:00Z",
        "twelve claimed years are clipped to the ten-year cap",
    )

    assert_instant_equals(
        without_affidavit["effective_priority_at"],
        "2026-08-02T00:00:00Z",
        "without an affidavit no prior use is credited",
    )
    assert_instant_equals(
        without_affidavit["effective_priority_at"],
        without_affidavit["original_filed_at"],
        "effective_priority_at",
    )


def test_outranked_filing_is_refused_with_brand_conflict(api):
    """PRD §3.3: "Recording is refused when the filing's conflict group already holds a
    record, owned by an owner other than the applicant, whose sort key sorts strictly
    ahead of the filing's — the refusal is `ERR_BRAND_CONFLICT_EXISTS` (HTTP 409
    Conflict)."
    PRD §3.3: "Inside a group, records are ordered by three keys applied in sequence —
    first by `effective_priority_at` ascending, so the earliest priority instant leads;
    then, for records sharing a priority instant, by the `correction_rounds` of the
    filing that produced each record, ascending, so a filing that needed no correction
    leads one that did; and finally by `created_at` ascending."

    Design: Corner/errors/corner_brand_conflict_exists_blocks_lower_priority_filing
    """
    scenario = setup_prior_use_priority_contest(
        documented_prior_use_years=12, prior_use_affidavit_on_file=False
    )
    assert scenario["incumbent_registration"]["priority_rank"] == 1
    assert_instant_equals(
        scenario["rival_application"]["effective_priority_at"],
        "2026-08-02T00:00:00Z",
        "effective_priority_at",
    )

    response = api.record_application(scenario["rival_application"]["id"], RECORDER)

    validate_error(response, ApiErrorId.ERR_BRAND_CONFLICT_EXISTS.value, 409)

    unchanged = read_application(scenario["rival_application"]["id"])
    assert unchanged["status"] == "UNDER_EXAMINATION"

    rows, meta = validate_paginated(
        api.list_brand_registrations(
            BOARD_ADMIN, params={"owner_id": scenario["rival_owner"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused filing must not mint a record"

    incumbent = read_registration(scenario["incumbent_registration"]["id"])
    assert incumbent["priority_rank"] == 1
    assert incumbent["status"] == "ACTIVE"


# ─── The correction cycle ─────────────────────────────────────────────────────

def test_third_return_terminates_the_filing_at_rejected(api):
    """PRD §3.2: "Returning the filing for correction advances `correction_rounds` by
    one and sends the filing to `RETURNED_FOR_CORRECTION` — but only while
    `correction_rounds` is still below the board's ceiling of two rounds."
    PRD §3.2: "It advances `correction_rounds` to 3 and terminates the filing at
    `REJECTED` with `rejection_reason` set to the fixed string
    `MAX_CORRECTION_ROUNDS_EXHAUSTED`."
    PRD §3.2: "The breakpoint is exact: a filing at `correction_rounds` 1 is returned, a
    filing at `correction_rounds` 2 is rejected."

    Design: Difficulty/non_linear_state_machine/brand_application_correction_cycle_third_return_rejects
    """
    scenario = setup_correction_cycle_at_ceiling()
    assert scenario["application"]["correction_rounds"] == 2
    assert scenario["application"]["status"] == "UNDER_EXAMINATION"

    final = validate_success(
        api.return_application(scenario["application"]["id"], EXAMINER), 200
    )

    assert final["status"] == "REJECTED", (
        f"the third return terminates the filing, got {final['status']}"
    )
    assert final["correction_rounds"] == 3
    assert final["rejection_reason"] == "MAX_CORRECTION_ROUNDS_EXHAUSTED"
    assert read_application(scenario["application"]["id"])["status"] == "REJECTED"


def test_correction_cycle_preserves_the_original_filing_instant(api):
    """PRD §3.2: "An applicant whose filing sits in `RETURNED_FOR_CORRECTION` may
    resubmit it, moving it back to `SUBMITTED` — the cycle `UNDER_EXAMINATION →
    RETURNED_FOR_CORRECTION → SUBMITTED` may run twice before the ceiling terminates it."
    PRD §3.2: "Crucially, `original_filed_at` is not touched, so an applicant who
    corrects a clerical error does not surrender the queue position they filed for."

    Design: Difficulty/non_linear_state_machine/brand_application_correction_cycle_third_return_rejects
    """
    scenario = setup_correction_cycle_at_ceiling()
    filed_at = scenario["application"]["original_filed_at"]

    final = validate_success(
        api.return_application(scenario["application"]["id"], EXAMINER), 200
    )

    assert final["correction_rounds"] == 3
    assert_instant_equals(final["original_filed_at"], filed_at, "original_filed_at")
    assert_instant_equals(
        final["original_filed_at"], "2026-08-01T00:00:00Z", "original_filed_at"
    )


# ─── Recording preconditions ──────────────────────────────────────────────────

def test_record_is_refused_when_the_prior_record_was_revoked(api):
    """PRD §3.2: "It is also barred when the filing is a `RENEWAL` whose prior record is
    no longer renewable: at recording time the record named by `prior_registration_id`
    must stand at `ACTIVE` or `GRACE`, and a prior record that has drifted to `LAPSED`,
    `SUPERSEDED`, `REVOKED` or `ENCUMBERED` yields
    `ERR_PRIOR_REGISTRATION_NOT_RENEWABLE` (HTTP 422)."
    PRD §3.4: "When it proceeds, the first effect is that the respondent record moves to
    `REVOKED`."

    Design: Difficulty/cross_entity_state_dependency/record_blocked_by_revoked_prior_registration
    """
    scenario = setup_revoked_prior_registration_renewal()
    assert scenario["renewal"]["status"] == "UNDER_EXAMINATION"
    assert read_registration(scenario["registration"]["id"])["status"] == "REVOKED"

    response = api.record_application(scenario["renewal"]["id"], RECORDER)

    validate_error(
        response, ApiErrorId.ERR_PRIOR_REGISTRATION_NOT_RENEWABLE.value, 422
    )


def test_revoked_prior_record_blocks_recording_without_minting_a_registration(api):
    """PRD §3.2: "It is also barred when the filing is a `RENEWAL` whose prior record is
    no longer renewable: at recording time the record named by `prior_registration_id`
    must stand at `ACTIVE` or `GRACE`, and a prior record that has drifted to `LAPSED`,
    `SUPERSEDED`, `REVOKED` or `ENCUMBERED` yields
    `ERR_PRIOR_REGISTRATION_NOT_RENEWABLE` (HTTP 422)."
    PRD §3.2: "When recording succeeds, the filing moves to `RECORDED`,
    `recorded_by_user_id` is stamped, and a brand of record comes into existence at
    status `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/record_blocked_by_revoked_prior_registration
    """
    scenario = setup_revoked_prior_registration_renewal()

    response = api.record_application(scenario["renewal"]["id"], RECORDER)
    error = validate_error(
        response, ApiErrorId.ERR_PRIOR_REGISTRATION_NOT_RENEWABLE.value, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_BRAND_CONFLICT_EXISTS.value

    unchanged = read_application(scenario["renewal"]["id"])
    assert unchanged["status"] == "UNDER_EXAMINATION"
    assert unchanged["recorded_by_user_id"] is None

    rows, meta = validate_paginated(
        api.list_brand_registrations(
            BOARD_ADMIN, params={"source_application_id": scenario["renewal"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "no record may be minted by the refused call"


def test_begin_examination_on_a_recorded_filing_is_refused(api):
    """PRD §3.2: "Examination is a `BrandRecorder`'s work. Taking a `SUBMITTED` filing
    up moves it to `UNDER_EXAMINATION` and stamps `examined_by_user_id` with the
    examining operator's identifier, incrementing the filing's `version`."
    PRD §3.2: "Attempting any of these recorder actions against a filing in a state that
    does not declare the transition is refused with `ERR_APPLICATION_INVALID_STATE`."

    Design: Corner/state_machines/corner_begin_examination_on_recorded_application_rejected
    """
    owner = enrol_owner("Terminal Ranch", contact_email="term@example.test")
    application, registration = record_brand(
        owner["id"], brand_symbol="TR", position_code="LEFT_RIB"
    )

    response = api.begin_examination(application["id"], EXAMINER)

    validate_error(response, ApiErrorId.ERR_APPLICATION_INVALID_STATE.value, 409)
    assert read_application(application["id"])["status"] == "RECORDED"
    assert read_registration(registration["id"])["status"] == "ACTIVE"


def test_recording_operator_must_differ_from_the_examining_operator(api):
    """PRD §2.10: "When a `BrandRecorder` takes a filing up for examination, the acting
    operator's `X-User-ID` is stamped onto the filing as `examined_by_user_id`; when a
    filing is recorded, the acting operator's `X-User-ID` is stamped as
    `recorded_by_user_id`."
    PRD §2.10: "A `BrandRecorder` who attempts to record a filing they themselves
    examined is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403 Forbidden), and the
    enforcement compares the recording caller's `X-User-ID` against the value currently
    stamped in `examined_by_user_id`."

    Design: Corner/validations/corner_segregation_of_duties_same_recorder_cannot_record
    """
    owner = enrol_owner("SoD Ranch", contact_email="sod@example.test")
    application = file_brand_application(
        owner["id"], brand_symbol="SD", position_code="RIGHT_SHOULDER"
    )
    examined = begin_examination(application["id"], "recorder-01")
    assert examined["examined_by_user_id"] == "recorder-01"

    refused = api.record_application(application["id"], EXAMINER)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    registration = validate_success(
        api.record_application(application["id"], RECORDER), 201
    )
    assert registration["status"] == "ACTIVE"
    recorded = read_application(application["id"])
    assert recorded["status"] == "RECORDED"
    assert recorded["recorded_by_user_id"] == "recorder-02"


def test_owner_cannot_file_a_brand_application_for_another_owner(api):
    """PRD §2.1: "When `X-User-Role` is `LivestockOwner`, `X-User-ID` is the `id` of the
    acting `Owner` row; ownership checks on any resource that references an `Owner`
    compare that resource's owner-side foreign key to `X-User-ID`."
    PRD §2.1: "Ownership enforcement carries its own rejection code,
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403 Forbidden), and it guards exactly thirteen write
    operations."

    Design: Corner/validations/corner_owner_cannot_file_application_for_another_owner
    """
    owner_a = enrol_owner("Owner A Ranch", contact_email="a@example.test")
    owner_b = enrol_owner("Owner B Ranch", contact_email="b@example.test")
    payload = create_brand_application_payload(
        owner_a["id"], brand_symbol="XA", position_code="LEFT_RIB"
    )

    response = api.create_brand_application(
        payload, make_livestock_owner_headers(owner_b["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    rows, meta = validate_paginated(
        api.list_brand_applications(BOARD_ADMIN, params={"owner_id": owner_a["id"]})
    )
    assert meta["total_count"] == 0, "the refused filing must not have been written"


def test_livestock_owner_cannot_record_a_filing(api):
    """PRD §2.1: "Each endpoint in §4 names the roles admitted to it; a caller whose
    role is not on that list is refused with `ERR_UNAUTHORIZED` (HTTP 403 Forbidden)."
    PRD §3.2: "Recording is the second `BrandRecorder`'s work, and it is the only path
    out of `UNDER_EXAMINATION` that produces property."

    Design: Corner/rbac/corner_livestock_owner_cannot_record_brand_application
    """
    owner = enrol_owner("RBAC Owner Ranch", contact_email="rbaco@example.test")
    application = file_brand_application(
        owner["id"], brand_symbol="RB", position_code="LEFT_RIB"
    )
    begin_examination(application["id"])

    response = api.record_application(
        application["id"], make_livestock_owner_headers(owner["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_application(application["id"])["status"] == "UNDER_EXAMINATION"

    rows, meta = validate_paginated(
        api.list_brand_registrations(
            BOARD_ADMIN, params={"source_application_id": application["id"]}
        )
    )
    assert meta["total_count"] == 0


# ─── Renewal, supersession and the registration calendar ──────────────────────

def test_recording_a_renewal_supersedes_the_prior_record(api):
    """PRD §3.3: "When a renewal is finally recorded, the prior record itself retires: a
    record standing at `ACTIVE` or `GRACE` moves to `SUPERSEDED`, and its
    `superseded_by_registration_id` is set to the identifier of the record just created,
    forming a chain that a caller can walk backwards through the register."
    PRD §3.2: "The new record copies `brand_symbol`, `position_code`, `species_class`
    and `state_code` from the filing, points back at it through `source_application_id`,
    names the holder through its own `owner_id`, inherits the filing's
    `effective_priority_at` unchanged, stamps `recorded_at` from the logical clock, and
    sets `expires_on` to `recorded_at` advanced by 1,825 days."
    PRD §3.3: "A renewal filed on or before the expiry instant — zero or fewer elapsed
    days — carries no penalty and costs the base amount."

    Design: Corner/state_machines/corner_renewal_record_supersedes_prior_registration
    """
    owner = enrol_owner("Supersede Ranch", contact_email="sup@example.test")
    _, original = record_brand(
        owner["id"], brand_symbol="SUP", position_code="LEFT_RIB", species_class="HORSE"
    )
    assert_instant_equals(original["expires_on"], "2031-07-31T00:00:00Z", "expires_on")

    renewal = file_renewal(owner["id"], original["id"], original["version"])
    assert renewal["application_type"] == "RENEWAL"
    assert renewal["assessed_filing_fee_cents"] == 12000
    begin_examination(renewal["id"])

    new_record = validate_success(api.record_application(renewal["id"], RECORDER), 201)

    assert_brand_registration(new_record)
    assert new_record["status"] == "ACTIVE"
    assert new_record["priority_rank"] == 1

    retired = read_registration(original["id"])
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_by_registration_id"] == new_record["id"]

    rows, meta = validate_paginated(
        api.list_brand_registrations(
            BOARD_ADMIN, params={"superseded_by_registration_id": new_record["id"]}
        )
    )
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_brand_registrations(
            BOARD_ADMIN, params={"owner_id": owner["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1, "exactly one live record survives the renewal"


def test_renewal_penalty_at_day_thirty_versus_day_thirty_one(api):
    """PRD §3.3: "The board counts whole elapsed days from the record's `expires_on` to
    the current logical clock, discarding any partial day."
    PRD §3.3: "A renewal filed from one through thirty days past expiry carries a
    penalty of one quarter of the base; the thirtieth day is still inside the grace
    window and the thirty-first is not."
    PRD §3.3: "A renewal filed from thirty-one through ninety days past expiry carries a
    penalty of three quarters of the base; the ninetieth day is still recoverable and
    the ninety-first is not."
    PRD §3.3: "The penalty is computed against the base, rounded half up to whole cents,
    and added to the base to give `assessed_filing_fee_cents`."

    Design: Corner/calculations/corner_renewal_fee_grace_boundary_day_thirty_versus_thirty_one
    """
    grace_owner = enrol_owner("Grace Day Ranch", contact_email="grace@example.test")
    lapse_owner = enrol_owner("Lapse Day Ranch", contact_email="lapse@example.test")
    _, grace_record = record_brand(
        grace_owner["id"], brand_symbol="G30", position_code="LEFT_RIB"
    )
    _, lapse_record = record_brand(
        lapse_owner["id"], brand_symbol="L31", position_code="RIGHT_RIB",
        species_class="SHEEP",
    )
    assert_instant_equals(grace_record["expires_on"], "2031-07-31T00:00:00Z", "expires_on")

    set_clock("2031-08-30T00:00:00Z")
    day_thirty = file_renewal(
        grace_owner["id"], grace_record["id"], grace_record["version"]
    )

    set_clock("2031-08-31T00:00:00Z")
    day_thirty_one = file_renewal(
        lapse_owner["id"], lapse_record["id"], lapse_record["version"]
    )

    assert day_thirty["assessed_filing_fee_cents"] == 15000, (
        "day thirty is still inside the grace window: 12000 base plus a quarter"
    )
    assert day_thirty_one["assessed_filing_fee_cents"] == 21000, (
        "day thirty-one crosses into the lapse-recovery band: 12000 base plus three quarters"
    )


def test_renewal_more_than_ninety_days_past_expiry_is_refused(api):
    """PRD §3.3: "A renewal attempted more than ninety days past expiry is refused
    outright with `ERR_REGISTRATION_UNRENEWABLE` (HTTP 422)."
    PRD §3.3: "A renewal filed from thirty-one through ninety days past expiry carries a
    penalty of three quarters of the base; the ninetieth day is still recoverable and
    the ninety-first is not."

    Design: Corner/calculations/corner_renewal_beyond_ninety_days_rejected
    """
    owner = enrol_owner("Too Late Ranch", contact_email="toolate@example.test")
    _, record = record_brand(
        owner["id"], brand_symbol="TL", position_code="LEFT_HIP", species_class="HORSE"
    )
    set_clock("2031-10-30T00:00:00Z")

    response = api.create_renewal_application(
        record["id"],
        create_renewal_application_payload(owner["id"], record["version"]),
        make_livestock_owner_headers(owner["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REGISTRATION_UNRENEWABLE.value, 422)

    rows, meta = validate_paginated(
        api.list_brand_applications(
            BOARD_ADMIN, params={"prior_registration_id": record["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused renewal must not have been written"
    assert read_registration(record["id"])["version"] == 1


def test_renewal_against_a_superseded_record_is_refused(api):
    """PRD §3.3: "A renewal may only be lodged against a record that is still `ACTIVE`,
    `GRACE` or `ENCUMBERED`; against a record already `SUPERSEDED`, `LAPSED` or
    `REVOKED` the attempt is refused with `ERR_REGISTRATION_INVALID_STATE`."
    PRD §2.8: "**Eighth**, the state rung: the target row must currently sit in a state
    from which the requested transition is declared, evaluated independently for each
    state dimension a row carries."

    Design: Corner/errors/corner_renewal_against_superseded_registration_rejected
    """
    owner = enrol_owner("Superseded Renewal Ranch", contact_email="spx@example.test")
    _, original = record_brand(
        owner["id"], brand_symbol="SPX", position_code="LEFT_RIB"
    )
    renewal = file_renewal(owner["id"], original["id"], original["version"])
    begin_examination(renewal["id"])
    new_record = record_application(renewal["id"])

    superseded = read_registration(original["id"])
    assert superseded["status"] == "SUPERSEDED"

    response = api.create_renewal_application(
        original["id"],
        create_renewal_application_payload(owner["id"], superseded["version"]),
        make_livestock_owner_headers(owner["id"]),
    )

    error = validate_error(
        response, ApiErrorId.ERR_REGISTRATION_INVALID_STATE.value, 409
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_REGISTRATION_VERSION.value

    assert read_registration(original["id"])["superseded_by_registration_id"] == new_record["id"]
    rows, meta = validate_paginated(
        api.list_brand_applications(
            BOARD_ADMIN, params={"prior_registration_id": original["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_stale_registration_version_is_refused_then_the_refreshed_filing_supersedes(api):
    """PRD §2.7: "Filing a renewal application against a brand record — the nested
    renewal route `POST /brand-inspection/brand-registrations/{id}/renewal-applications`
    — requires `expected_registration_version`, carrying the client's last-observed
    `version` of the `BrandRegistration` named in the path."
    PRD §2.7: "If the record's `version` has advanced since the client read it, the
    filing is refused with `ERR_STALE_REGISTRATION_VERSION` (HTTP 412 Precondition
    Failed)."
    PRD §3.3: "Lodging the renewal increments that record's `version` by one."
    PRD §3.3: "When a renewal is lodged, every earlier filing against the same
    `prior_registration_id` that still stands at `SUBMITTED`, `UNDER_EXAMINATION`,
    `RETURNED_FOR_CORRECTION` or `CONFLICT_HOLD` is moved to `REJECTED` with
    `rejection_reason` set to `SUPERSEDED_BY_LATER_RENEWAL`, processed in `created_at`
    ascending order."

    Design: Corner/cross_cutting_layers/corner_occ_stale_registration_version_rejected_then_supersedes
    """
    owner = enrol_owner("OCC Ranch", contact_email="occ@example.test")
    _, record = record_brand(owner["id"], brand_symbol="OC", position_code="LEFT_RIB")
    assert record["version"] == 1

    first_renewal = file_renewal(owner["id"], record["id"], 1)

    stale = api.create_renewal_application(
        record["id"],
        create_renewal_application_payload(owner["id"], 1),
        make_livestock_owner_headers(owner["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_REGISTRATION_VERSION.value, 412)

    refreshed_version = read_registration(record["id"])["version"]
    assert refreshed_version == 2, "lodging a renewal advances the record's version"

    second_renewal = file_renewal(owner["id"], record["id"], refreshed_version)
    assert second_renewal["status"] == "SUBMITTED"

    superseded = read_application(first_renewal["id"])
    assert superseded["status"] == "REJECTED"
    assert superseded["rejection_reason"] == "SUPERSEDED_BY_LATER_RENEWAL"
    assert read_registration(record["id"])["version"] == 3


def test_sweep_graces_then_lapses_a_record_and_rejects_its_pending_renewal(api):
    """PRD §3.3: "A record standing at `ACTIVE` whose `expires_on` has been reached —
    that is, whose `expires_on` is at or before the logical clock — is moved to `GRACE`."
    PRD §3.3: "A record standing at `GRACE` is moved to `LAPSED` once the clock has
    passed 90 days beyond its `expires_on`, meaning the clock is strictly later than
    `expires_on` advanced by 90 days; a clock sitting exactly on that ninetieth day
    still leaves the record in `GRACE`."
    PRD §3.3: "Reaching `LAPSED` is fatal to anything pending against the record: every
    renewal filing whose `prior_registration_id` names the newly lapsed record and whose
    status is `SUBMITTED`, `UNDER_EXAMINATION`, `RETURNED_FOR_CORRECTION` or
    `CONFLICT_HOLD` is moved to `REJECTED` with `rejection_reason` set to
    `PRIOR_REGISTRATION_LAPSED`."
    PRD §3.9: "The sweep reports what it did: `delinquent_order_count`,
    `graced_registration_count`, `lapsed_registration_count`, `suspended_owner_count`,
    and the `swept_at` instant it ran at."

    Design: Corner/cross_cutting_layers/corner_sweep_lapses_registration_and_rejects_pending_renewal
    """
    owner = enrol_owner("Sweep Ranch", contact_email="sweep@example.test")
    _, record = record_brand(
        owner["id"], brand_symbol="SW", position_code="RIGHT_HIP", species_class="SHEEP"
    )
    assert_instant_equals(record["expires_on"], "2031-07-31T00:00:00Z", "expires_on")

    set_clock("2031-08-01T00:00:00Z")
    renewal = file_renewal(owner["id"], record["id"], record["version"])
    assert renewal["assessed_filing_fee_cents"] == 15000

    first_sweep = run_delinquency_sweep()
    assert first_sweep["graced_registration_count"] == 1
    assert first_sweep["lapsed_registration_count"] == 0
    assert_instant_equals(first_sweep["swept_at"], "2031-08-01T00:00:00Z", "swept_at")
    assert read_registration(record["id"])["status"] == "GRACE"

    set_clock("2031-10-30T00:00:00Z")
    second_sweep = run_delinquency_sweep()
    assert second_sweep["graced_registration_count"] == 0
    assert second_sweep["lapsed_registration_count"] == 1

    assert read_registration(record["id"])["status"] == "LAPSED"
    rejected = read_application(renewal["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "PRIOR_REGISTRATION_LAPSED"


def test_registration_list_applies_the_pagination_defaults(api):
    """PRD §2.3: "`limit` caps the number of rows returned; when it is omitted the
    server applies a default of 10, and a supplied value must be at least 1 and at most
    100."
    PRD §2.3: "`offset` is the number of rows to skip before the returned page begins;
    when it is omitted the server applies a default of 0."

    Design: Corner/endpoints/corner_pagination_defaults_applied_when_omitted
    """
    owner = enrol_owner("Page Default Ranch", contact_email="pgdef@example.test")
    _, record = record_brand(owner["id"], brand_symbol="PD", position_code="LEFT_RIB")

    response = api.list_brand_registrations(EXAMINER)
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["limit"] == 10, f"omitted limit defaults to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"omitted offset defaults to 0, got {meta['offset']}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1 and rows[0]["id"] == record["id"]
