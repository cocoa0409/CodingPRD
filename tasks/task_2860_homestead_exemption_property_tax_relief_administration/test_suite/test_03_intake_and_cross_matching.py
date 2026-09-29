"""Opening accounts and applications, and reading the external registries.

Intake is clerk work: the account carries a server-initialised relief ledger, the
application names three foreign keys that must all resolve, and each cross-match
is recorded as an immutable event row that accumulates rather than overwrites.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_DRAFT,
    ERR_DUPLICATE_APPLICATION,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_NOT_FOUND,
    ERR_TAXPAYER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_event_row_fields,
    assert_instant,
    assert_instants_equal,
    assert_taxpayer_ledger,
    ids_of,
)
from test_helpers.constants import ADDR_OAK
from test_helpers.test_users import CLERK, CLERK_USER_ID


def test_an_account_opened_without_a_name_is_refused_and_persists_nothing(api):
    """PRD §3.2: "An `IntakeClerk` opens a **taxpayer account** for each claimant,
    recording the `full_name`, the `date_of_birth` as a calendar date ..., the
    `ssn_last4` ..., the `mailing_address_normalized` address of record, and
    optionally the `disability_rating_pct_bps`." PRD §2.10 rung 5:
    "Request-body shape — `ERR_INVALID_REQUEST`: required fields present".

    Design: Corner/entities/taxpayer_account_without_full_name_is_rejected
    """
    fx.set_clock(api)
    payload = {
        key: value
        for key, value in f.taxpayer_account().items()
        if key != "full_name"
    }
    assert "full_name" not in payload, "the payload under test must omit the name"

    validate_error(
        api.create_taxpayer_account(payload, CLERK),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )

    # Nothing was minted, so no account id resolves at all.
    validate_error(
        api.get_taxpayer_account(NON_EXISTENT_UUID, CLERK),
        ERR_TAXPAYER_NOT_FOUND,
        expected_status=404,
    )


def test_a_new_account_arrives_in_good_standing_with_an_empty_relief_ledger(api):
    """PRD §3.2: "The account opens in `GOOD_STANDING` with `lifetime_refund_cents`,
    `lifetime_recovery_collected_cents` and `net_relief_cents` all at 0". PRD §2.4:
    "Every resource the API persists carries an `id`: a server-minted UUID with no
    type prefix ... `version` is an integer that starts at 1 when the row is
    created".

    Design: Corner/entities/taxpayer_account_system_fields_and_ledger_are_server_initialised
    """
    fx.set_clock(api)

    account = validate_success(
        api.create_taxpayer_account(
            f.taxpayer_account(disability_rating_pct_bps=0), CLERK
        ),
        expected_status=201,
    )

    assert_common_fields(account)
    assert account["version"] == 1, (
        f"a freshly opened account starts at version 1, got {account['version']}"
    )
    assert_taxpayer_ledger(
        account,
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
        status="GOOD_STANDING",
    )

    # None of those fields was supplied by the caller, so the read must agree.
    fetched = validate_success(api.get_taxpayer_account(account["id"], CLERK))
    assert fetched["id"] == account["id"], (
        f"the read must return the account that was opened, got {fetched['id']}"
    )
    assert_taxpayer_ledger(
        fetched,
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
        status="GOOD_STANDING",
    )


def test_an_application_naming_no_registered_programme_is_refused(api):
    """PRD §2.10 rung 7: "Body foreign keys resolve — the same not-found family plus
    `ERR_PROGRAM_NOT_FOUND` and `ERR_NOTICE_NOT_FOUND`, covering `parcel_id`,
    `taxpayer_id`, `program_id` ... Applies to ... `POST /exemption-applications`".
    PRD §3.2: "The payload names the `parcel_id` the exemption is claimed on, the
    `taxpayer_id` of the claimant, the `program_id` of the classification applied
    for".

    Design: Corner/entities/application_with_an_unknown_program_id_returns_program_not_found
    """
    fx.set_clock(api)
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())

    # Both of the other two foreign keys resolve; only the programme does not.
    validate_error(
        api.create_application(
            f.application(parcel["id"], taxpayer["id"], NON_EXISTENT_UUID), CLERK
        ),
        ERR_PROGRAM_NOT_FOUND,
        expected_status=404,
    )

    rows, meta = validate_paginated(
        api.list_applications(CLERK, parcel_id=parcel["id"])
    )
    assert meta["total_count"] == 0, (
        f"no partial application row may have been written, got {meta['total_count']}"
    )
    assert rows == [], f"unexpected applications on the parcel: {rows}"


def test_a_second_cross_match_appends_a_row_instead_of_rewriting_the_first(api):
    """PRD §2.4: "The single exception is `VerificationCheck`. A verification check
    is an immutable event: once recorded it is never rewritten, superseded checks
    are retained alongside their successors, and the row carries only `id` and
    `created_at`. Both `updated_at` and `version` are absent". PRD §3.3: "the
    resulting row is immutable — checks accumulate rather than overwrite", and
    "`NO_RECORD` is written when no registry record exists at all for that
    taxpayer-and-source pair."

    Design: Corner/entities/verification_check_is_an_immutable_event_row
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    application = fx.submitted_application(
        api, parcel["id"], taxpayer["id"], program["id"]
    )

    # No voter registry row exists yet, so the first cross-match finds nothing.
    first = validate_success(
        api.create_verification_check(
            application["id"], f.verification_check("VOTER_REGISTRY"), CLERK
        ),
        expected_status=201,
    )
    assert first["result"] == "NO_RECORD", (
        f"an absent registry row reads NO_RECORD, got {first['result']}"
    )
    assert first["expected_value"] == ADDR_OAK, (
        f"the expected value is the address the application asserted, got {first['expected_value']!r}"
    )
    assert_event_row_fields(first)

    fx.inject_registry(
        api,
        taxpayer["id"],
        "VOTER_REGISTRY",
        record_effective_date="2026-01-05",
        address_normalized=ADDR_OAK,
    )

    second = validate_success(
        api.create_verification_check(
            application["id"], f.verification_check("VOTER_REGISTRY"), CLERK
        ),
        expected_status=201,
    )
    assert second["result"] == "MATCH", (
        f"the injected row agrees with the claimed address, got {second['result']}"
    )
    assert second["expected_value"] == ADDR_OAK, (
        f"the expected value is unchanged, got {second['expected_value']!r}"
    )
    assert_event_row_fields(second)
    assert second["id"] != first["id"], (
        "the second cross-match must be a new row, not the first one rewritten"
    )

    rows, meta = validate_paginated(
        api.list_verification_checks(
            application["id"], CLERK, source="VOTER_REGISTRY"
        )
    )
    assert meta["total_count"] == 2, (
        f"both cross-matches are retained, got {meta['total_count']}"
    )
    assert ids_of(rows) == [first["id"], second["id"]], (
        f"unexpected cross-match history: {ids_of(rows)}"
    )

    older = rows[0]
    assert older["result"] == "NO_RECORD", (
        f"the superseded row keeps its own verdict, got {older['result']}"
    )
    assert older["observed_value"] == first["observed_value"], (
        "the superseded row's observed value was rewritten: "
        f"{first['observed_value']!r} became {older['observed_value']!r}"
    )
    assert_instants_equal(older["checked_at"], first["checked_at"], "checked_at")
    assert_event_row_fields(older)


def _draft_application(api):
    """An open programme, a parcel, a claimant and one freshly keyed draft."""
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    draft = validate_success(
        api.create_application(
            f.application(parcel["id"], taxpayer["id"], program["id"]), CLERK
        ),
        expected_status=201,
    )
    return {
        "program": program,
        "parcel": parcel,
        "taxpayer": taxpayer,
        "draft": draft,
    }


def test_a_new_application_is_a_draft_carrying_no_determination_state(api):
    """PRD §3.2: "The application is created in `DRAFT` with `info_request_round` at
    0, `determined_by_user_id`, `denial_reason` and `resulting_grant_id` all null,
    and `intake_user_id` stamped with the acting `X-User-ID`. That stamp is the
    duty-separation bar of §2.8: whoever keyed the application is thereafter
    disqualified from determining it."

    Design: Corner/state_machines/new_application_starts_in_draft_with_no_determination_state
    """
    draft = _draft_application(api)["draft"]

    assert_common_fields(draft)
    assert draft["status"] == "DRAFT", (
        f"a keyed application waits in draft, got {draft['status']}"
    )
    assert draft["info_request_round"] == 0, (
        f"no information has been requested yet, got {draft['info_request_round']}"
    )
    assert draft["determined_by_user_id"] is None, (
        f"nobody has determined it, got {draft['determined_by_user_id']!r}"
    )
    assert draft["resulting_grant_id"] is None, (
        f"no grant has been minted, got {draft['resulting_grant_id']!r}"
    )
    assert draft["denial_reason"] is None, (
        f"no denial has been recorded, got {draft['denial_reason']!r}"
    )
    assert draft["intake_user_id"] == CLERK_USER_ID, (
        "the acting clerk is stamped as the intake operator, got "
        f"{draft['intake_user_id']!r}"
    )


def test_submitting_a_draft_stops_at_submitted_and_runs_no_cross_match(api):
    """PRD §3.2: "Submission moves the application from `DRAFT` to `SUBMITTED`, and
    only from `DRAFT` ... Submission is a mutation of the application and increments
    its `version` by 1; verification is deliberately *not* run here, because the
    clerk or reviewer records each cross-match explicitly."

    Design: Corner/state_machines/submit_moves_a_draft_application_to_submitted
    """
    world = _draft_application(api)
    draft = world["draft"]
    assert draft["version"] == 1, (
        f"the draft starts at version 1, got {draft['version']}"
    )

    submitted = validate_success(api.submit_application(draft["id"], CLERK))

    assert submitted["status"] == "SUBMITTED", (
        f"submission stops at submitted, got {submitted['status']}"
    )
    assert submitted["version"] == 2, (
        f"submission is one mutation, so the version is 2, got {submitted['version']}"
    )
    assert submitted["info_request_round"] == 0, (
        f"submission requests no information, got {submitted['info_request_round']}"
    )
    assert submitted["determined_by_user_id"] is None, (
        f"submission determines nothing, got {submitted['determined_by_user_id']!r}"
    )

    # The status did not run ahead to UNDER_REVIEW, because that event rides on
    # the first cross-match and no cross-match has been recorded.
    rows, meta = validate_paginated(
        api.list_verification_checks(draft["id"], CLERK)
    )
    assert meta["total_count"] == 0, (
        f"submission records no cross-match, got {meta['total_count']}"
    )
    assert rows == [], f"unexpected cross-match rows: {rows}"


def test_submitting_an_already_submitted_application_is_refused(api):
    """PRD §3.2: "Submission moves the application from `DRAFT` to `SUBMITTED`, and
    only from `DRAFT` — a submission attempt against any other status is rejected
    with `ERR_APPLICATION_NOT_DRAFT`."

    Design: Corner/state_machines/repeating_submit_on_a_submitted_application_is_rejected
    """
    world = _draft_application(api)
    first = validate_success(api.submit_application(world["draft"]["id"], CLERK))
    assert first["version"] == 2, (
        f"the accepted submission moved the version to 2, got {first['version']}"
    )

    validate_error(
        api.submit_application(world["draft"]["id"], CLERK),
        ERR_APPLICATION_NOT_DRAFT,
        expected_status=409,
    )

    again = validate_success(api.get_application(world["draft"]["id"], CLERK))
    assert again["status"] == "SUBMITTED", (
        f"the refused replay leaves the status alone, got {again['status']}"
    )
    assert again["version"] == first["version"], (
        "a refused replay is not a mutation, so the version must not move: "
        f"{first['version']} became {again['version']}"
    )


def test_a_denied_predecessor_does_not_block_a_fresh_claim_on_the_same_triple(api):
    """PRD §3.2: "And no other application may already be live for the same
    `parcel_id`, `program_id` and `tax_year` combination, where "live" means an
    application whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED` or
    `APPROVED`; a collision is rejected with `ERR_DUPLICATE_APPLICATION`. A withdrawn
    `DRAFT` or a `DENIED` predecessor does not block a fresh claim."

    Design: Corner/validations/submitting_after_the_earlier_application_was_denied_passes
    """
    world = fx.denial_notice_world(api, claimants=1)
    first = world["applications"][0]
    parcel_id = world["parcel"]["id"]
    program_id = world["program"]["id"]
    taxpayer_id = world["taxpayers"][0]["id"]
    assert first["status"] == "DENIED", (
        f"the predecessor must be out of the live set, got {first['status']}"
    )

    second = validate_success(
        api.create_application(
            f.application(parcel_id, taxpayer_id, program_id), CLERK
        ),
        expected_status=201,
    )

    resubmitted = validate_success(api.submit_application(second["id"], CLERK))
    assert resubmitted["status"] == "SUBMITTED", (
        f"the fresh claim must be accepted, got {resubmitted['status']}"
    )

    # The refused-collision path was never taken, so the predecessor is untouched.
    predecessor = validate_success(api.get_application(first["id"], CLERK))
    assert predecessor["status"] == "DENIED", (
        f"the denial still stands, got {predecessor['status']}"
    )
    assert predecessor["denial_reason"] == first["denial_reason"], (
        "the recorded ground was rewritten: "
        f"{first['denial_reason']!r} became {predecessor['denial_reason']!r}"
    )

    rows, meta = validate_paginated(
        api.list_applications(CLERK, parcel_id=parcel_id, program_id=program_id)
    )
    assert meta["total_count"] == 2, (
        f"both the denied and the fresh claim are on file, got {meta['total_count']}"
    )
    assert ids_of(rows) == [first["id"], second["id"]], (
        f"unexpected claim history on the parcel: {ids_of(rows)}"
    )


def test_a_claim_under_review_blocks_a_second_submission_on_the_same_triple(api):
    """PRD §3.2: "no other application may already be live for the same `parcel_id`,
    `program_id` and `tax_year` combination, where "live" means an application whose
    `status` is `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED` or `APPROVED`; a
    collision is rejected with `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/validations/submitting_while_an_earlier_application_is_under_review_is_rejected
    """
    world = _draft_application(api)
    parcel_id = world["parcel"]["id"]
    taxpayer_id = world["taxpayer"]["id"]
    program_id = world["program"]["id"]

    first = fx.submitted_application(api, parcel_id, taxpayer_id, program_id)
    fx.run_checks(api, first["id"], ["VOTER_REGISTRY"])
    under_review = validate_success(api.get_application(first["id"], CLERK))
    assert under_review["status"] == "UNDER_REVIEW", (
        f"the first cross-match opens the review, got {under_review['status']}"
    )

    second = world["draft"]
    validate_error(
        api.submit_application(second["id"], CLERK),
        ERR_DUPLICATE_APPLICATION,
        expected_status=409,
    )

    refused = validate_success(api.get_application(second["id"], CLERK))
    assert refused["status"] == "DRAFT", (
        f"the refused submission leaves the claim in draft, got {refused['status']}"
    )
    assert refused["version"] == 1, (
        f"a refused submission is not a mutation, got version {refused['version']}"
    )

    still_live = validate_success(api.get_application(first["id"], CLERK))
    assert still_live["status"] == "UNDER_REVIEW", (
        f"the live predecessor is untouched, got {still_live['status']}"
    )


def test_the_first_cross_match_finds_nothing_and_still_opens_the_review(api):
    """PRD §3.3: "`NO_RECORD` is written when no registry record exists at all for
    that taxpayer-and-source pair, and also when the source is `INCOME_DOR` and no
    income certification satisfies the selector above — there is then nothing to
    compare the reported income against, and `observed_value` is the empty string."
    PRD §3.3 adds: "The **first** check recorded for an application auto-transitions
    that application from `SUBMITTED` to `UNDER_REVIEW` and increments its `version`
    by 1".

    Design: Corner/endpoints/first_verification_check_records_no_record_and_opens_the_review
    """
    world = _draft_application(api)
    submitted = validate_success(api.submit_application(world["draft"]["id"], CLERK))
    application_id = submitted["id"]
    assert submitted["status"] == "SUBMITTED", (
        f"the application waits for its first cross-match, got {submitted['status']}"
    )

    # No registry row was ever injected for this claimant.
    check = validate_success(
        api.create_verification_check(
            application_id, f.verification_check("VOTER_REGISTRY"), CLERK
        ),
        expected_status=201,
    )

    assert check["result"] == "NO_RECORD", (
        f"an absent registry row reads NO_RECORD, got {check['result']}"
    )
    assert check["observed_value"] == "", (
        f"there was nothing to observe, got {check['observed_value']!r}"
    )
    assert check["expected_value"] == ADDR_OAK, (
        "the expected value is the address the application asserted, got "
        f"{check['expected_value']!r}"
    )
    assert check["source"] == "VOTER_REGISTRY", (
        f"the check records the source it was asked for, got {check['source']}"
    )
    assert check["application_id"] == application_id, (
        f"the check names its application, got {check['application_id']}"
    )
    assert_instant(check, "checked_at", "2026-08-01T00:00:00.000Z")
    assert_event_row_fields(check)

    reviewed = validate_success(api.get_application(application_id, CLERK))
    assert reviewed["status"] == "UNDER_REVIEW", (
        "a fruitless cross-match still opens the review, got "
        f"{reviewed['status']}"
    )
    assert reviewed["version"] == submitted["version"] + 1, (
        "the auto-transition is one mutation on top of the submission: "
        f"{submitted['version']} became {reviewed['version']}"
    )

    rows, meta = validate_paginated(
        api.list_verification_checks(application_id, CLERK)
    )
    assert meta["total_count"] == 1, (
        f"exactly one cross-match is on record, got {meta['total_count']}"
    )
    assert ids_of(rows) == [check["id"]], f"unexpected cross-match log: {ids_of(rows)}"
