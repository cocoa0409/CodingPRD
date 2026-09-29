"""Version pinning, threshold-driven money paths, sweep idempotence and
read-after-write consistency (PRD §2.4, §2.5, §2.7, §2.9, §3.7, §3.8, §3.10).

Every test builds its own preconditions: the harness relaunches the API server
before each test, so each one starts against an empty database.
"""

import test_helpers.fixtures as fixtures
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_assignment_payload,
    create_credential_payload,
    make_interpreter_headers,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
CREDENTIALING = TEST_USERS["credentialing_officer_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]
FISCAL = TEST_USERS["fiscal_officer_headers"]

# A CERTIFIED interpreter on the canonical schedule: the minimum-call floor of
# 2.00 hours at 8750 cents an hour, no travel and no rare-language premium.
MINIMUM_CALL_ENCUMBRANCE_CENTS = 17500


def test_a_stale_expected_hearing_version_is_refused_on_assignment_create(api):
    """PRD §2.7: "`POST /assignments` requires a non-optional `expected_hearing_version` field in its request body, carrying the client's last observed `version` of the target `Hearing`."
    PRD §2.7: "If that value does not equal the hearing's current `version`, the request is rejected with `ERR_STALE_HEARING_VERSION` (HTTP 412)."
    PRD §2.7: "Note that the hearing's `version` is incremented by the create itself, by the supersede it triggers, by a continuance, and by every coverage transition, so a client must re-read the hearing after any of those before attempting another create."
    PRD §3.6: "An existing `PROPOSED` assignment is not a blocker: it moves to `SUPERSEDED`, and the hearing's `version` is incremented by 1 for that supersede in the same call, on top of the increment the create itself performs."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_expected_version_returns_412_on_both_declared_occ_write_endpoints
    """
    config = fixtures.setup_program_config()
    first_bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    second_bundle = fixtures.setup_active_interpreter(
        config["language"]["id"],
        interpreter_overrides={
            "full_name": "Carla Diaz",
            "email": "carla.diaz@courts.example.gov",
        },
    )
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-8001",
        hearing_type="PLEA",
        scheduled_start="2026-09-15T09:00:00.000Z",
        scheduled_end="2026-09-15T10:00:00.000Z",
    )
    version_before_create = hearing["version"]

    first_assignment = fixtures.propose_assignment(
        hearing["id"], first_bundle["interpreter"]["id"], version_before_create
    )
    after_first_create = fixtures.read_hearing(hearing["id"])
    live_version = after_first_create["version"]
    assert live_version == version_before_create + 1, (
        f"expected the create itself to move the hearing version from "
        f"{version_before_create} to {version_before_create + 1}, got {live_version}"
    )

    stale_response = api.create_assignment(
        create_assignment_payload(
            hearing["id"],
            version_before_create,
            second_bundle["interpreter"]["id"],
        ),
        COORDINATOR,
    )
    validate_error(stale_response, ApiErrorId.ERR_STALE_HEARING_VERSION)

    rows, meta = validate_paginated(
        api.list_assignments(COORDINATOR, params={"hearing_id": hearing["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected the refused create to have created nothing, so 1 assignment "
        f"should exist, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first_assignment["id"], (
        f"expected the surviving assignment to be {first_assignment['id']}, "
        f"got {rows[0]['id']}"
    )
    assert rows[0]["service_status"] == "PROPOSED", (
        f"expected the refused create to have superseded nothing, so the first "
        f"assignment stays PROPOSED, got {rows[0]['service_status']}"
    )

    replacement = validate_success(
        api.create_assignment(
            create_assignment_payload(
                hearing["id"], live_version, second_bundle["interpreter"]["id"]
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert replacement["service_status"] == "PROPOSED", (
        f"expected the retry with the refreshed version to be accepted as "
        f"PROPOSED, got {replacement['service_status']}"
    )
    superseded = fixtures.read_assignment(first_assignment["id"])
    assert superseded["service_status"] == "SUPERSEDED", (
        f"expected the accepted create to supersede the earlier proposal, got "
        f"{superseded['service_status']}"
    )
    after_supersede = fixtures.read_hearing(hearing["id"])
    assert after_supersede["version"] == live_version + 2, (
        f"expected the create plus its supersede to add 2 to the hearing "
        f"version {live_version}, got {after_supersede['version']}"
    )

    replayed_response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], live_version, second_bundle["interpreter"]["id"]
        ),
        COORDINATOR,
    )
    validate_error(replayed_response, ApiErrorId.ERR_STALE_HEARING_VERSION)


def test_a_stale_expected_interpreter_version_is_refused_on_credential_create(api):
    """PRD §2.7: "`POST /credentials` requires a non-optional `expected_interpreter_version` field in its request body, carrying the client's last observed `version` of the target `Interpreter`."
    PRD §2.7: "If that value does not equal the interpreter's current `version`, the request is rejected with `ERR_STALE_INTERPRETER_VERSION` (HTTP 412)."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation of the row — and `version`, an integer that starts at 1 on creation and increases by exactly 1 each time the row is mutated."
    PRD §3.3: "A new credential's `status` is `PENDING_WRITTEN`, its `written_best_score` and `oral_best_score` are null, its `written_attempt_count` and `oral_attempt_count` are 0, its `cycle_credit_hours` is 0, its `renewal_count` is 0, and its three cycle dates — `issued_on`, `expires_on`, and `grace_through` — are all null until the credential is first activated."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_expected_version_returns_412_on_both_declared_occ_write_endpoints
    """
    fixtures.set_clock()
    spanish = fixtures.bootstrap_language()
    korean = fixtures.bootstrap_language(
        code="kor", name="Korean", tier_class="NON_DESIGNATED", oral_exam_available=True
    )
    interpreter = fixtures.enrol_interpreter()
    version_at_enrolment = interpreter["version"]
    assert version_at_enrolment == 1, (
        f"expected a freshly enrolled interpreter to be at version 1, got "
        f"{version_at_enrolment}"
    )

    fixtures.complete_ethics_training(interpreter["id"])
    spanish_credential = fixtures.open_credential(
        interpreter["id"], spanish["id"], "CERTIFIED"
    )
    fixtures.drive_credential_to_active(spanish_credential["id"])
    live = fixtures.read_interpreter(interpreter["id"])
    assert live["version"] > version_at_enrolment, (
        f"expected the ethics, credential and activation mutations to move the "
        f"interpreter past version {version_at_enrolment}, got {live['version']}"
    )

    stale_response = api.create_credential(
        create_credential_payload(
            interpreter["id"], korean["id"], version_at_enrolment, "REGISTERED"
        ),
        CREDENTIALING,
    )
    validate_error(stale_response, ApiErrorId.ERR_STALE_INTERPRETER_VERSION)

    rows, meta = validate_paginated(
        api.list_credentials(
            CREDENTIALING, params={"interpreter_id": interpreter["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected the refused create to have created nothing, so only the "
        f"Spanish credential should exist, got {meta['total_count']} rows"
    )
    assert rows[0]["id"] == spanish_credential["id"], (
        f"expected the only credential to be {spanish_credential['id']}, got "
        f"{rows[0]['id']}"
    )
    unchanged = fixtures.read_interpreter(interpreter["id"])
    assert unchanged["version"] == live["version"], (
        f"expected the refused create to leave the interpreter at version "
        f"{live['version']}, got {unchanged['version']}"
    )

    accepted = validate_success(
        api.create_credential(
            create_credential_payload(
                interpreter["id"], korean["id"], live["version"], "REGISTERED"
            ),
            CREDENTIALING,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PENDING_WRITTEN", (
        f"expected the retry with the live version to open a PENDING_WRITTEN "
        f"credential, got {accepted['status']}"
    )
    assert accepted["language_id"] == korean["id"], (
        f"expected the new credential to name language {korean['id']}, got "
        f"{accepted['language_id']}"
    )


def test_cancelling_at_exactly_forty_eight_hours_lead_time_voids_the_claim(api):
    """PRD §3.7: "What happens next depends entirely on lead time, measured as the difference between the hearing's `scheduled_start` and the logical clock and compared against the governing rate schedule's `late_cancellation_hours`."
    PRD §3.7: "An **early** cancellation — lead time at or above that threshold — voids the encumbered claim: it moves `ENCUMBERED → VOIDED`, `provisional_total_cents` is preserved on the row for audit while `final_total_cents` stays null, and exactly `provisional_total_cents` is released from the courthouse's `encumbered_pay_cents`, restoring the ledger to its pre-confirmation value."
    PRD §3.7: "The hearing follows suit: a `COVERED` hearing returns to `SCHEDULED` on an early cancellation and moves to `UNMET` on a late one, incrementing its `version` by 1; a hearing still in `SCHEDULED` because the assignment was only `PROPOSED` is left untouched, as is a hearing already in `CONTINUED`."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Corner/Cross-Cutting Complexity Layers/the_late_cancellation_lead_time_threshold_is_inclusive_at_forty_eight_hours_and_flips_the_money_path_thirty_minutes_later
    """
    bundle = fixtures.setup_confirmed_assignment(
        hearing_overrides={
            "case_number": "CR-2026-9001",
            "hearing_type": "PLEA",
            "scheduled_start": "2026-09-20T09:00:00.000Z",
            "scheduled_end": "2026-09-20T10:00:00.000Z",
        }
    )
    courthouse_id = bundle["courthouse"]["id"]
    budget_cents = bundle["courthouse"]["pay_budget_cents"]
    claim = bundle["pay_claim"]
    assert claim["provisional_total_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected the confirmation to encumber {MINIMUM_CALL_ENCUMBRANCE_CENTS}, "
        f"got {claim['provisional_total_cents']}"
    )

    # Exactly 48 hours of lead time before a 2026-09-20T09:00 hearing.
    fixtures.set_clock("2026-09-18T09:00:00.000Z")
    cancelled = fixtures.cancel_assignment(bundle["assignment"]["id"])
    assert cancelled["service_status"] == "CANCELLED", (
        f"expected the assignment to be CANCELLED, got {cancelled['service_status']}"
    )

    claim_after = fixtures.read_pay_claim(claim["id"])
    assert claim_after["status"] == "VOIDED", (
        f"expected lead time exactly at the 48-hour threshold to count as early "
        f"and void the claim, got status {claim_after['status']}"
    )
    assert claim_after["provisional_total_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected the voided claim to preserve provisional_total_cents "
        f"{MINIMUM_CALL_ENCUMBRANCE_CENTS} for audit, got "
        f"{claim_after['provisional_total_cents']}"
    )
    assert claim_after["final_total_cents"] is None, (
        f"expected final_total_cents to stay null on an early cancellation, got "
        f"{claim_after['final_total_cents']}"
    )
    assert claim_after["late_cancellation"] is False, (
        f"expected late_cancellation to stay false on an early cancellation, got "
        f"{claim_after['late_cancellation']}"
    )

    hearing_after = fixtures.read_hearing(bundle["hearing"]["id"])
    assert hearing_after["status"] == "SCHEDULED", (
        f"expected the COVERED hearing to return to SCHEDULED on an early "
        f"cancellation, got {hearing_after['status']}"
    )

    ledger = fixtures.read_courthouse(courthouse_id)
    assert ledger["encumbered_pay_cents"] == 0, (
        f"expected the released encumbrance to return encumbered_pay_cents to 0, "
        f"got {ledger['encumbered_pay_cents']}"
    )
    assert ledger["obligated_pay_cents"] == 0, (
        f"expected an early cancellation to obligate nothing, got "
        f"{ledger['obligated_pay_cents']}"
    )
    assert ledger["available_pay_cents"] == budget_cents, (
        f"expected available_pay_cents restored to the pre-confirmation "
        f"{budget_cents}, got {ledger['available_pay_cents']}"
    )


def test_cancelling_thirty_minutes_inside_the_threshold_pays_late_cancellation(api):
    """PRD §3.7: "What happens next depends entirely on lead time, measured as the difference between the hearing's `scheduled_start` and the logical clock and compared against the governing rate schedule's `late_cancellation_hours`."
    PRD §3.7: "A **late** cancellation — lead time strictly below the threshold — compensates the interpreter instead: the claim moves `ENCUMBERED → FINALIZED` with `variant` set to `FINAL`, `late_cancellation` set to true, and `final_total_cents` computed by the late-cancellation arithmetic of §3.8, after which the interpreter's `pending_pay_cents` is recomputed from the newly finalized claim."
    PRD §3.7: "The hearing follows suit: a `COVERED` hearing returns to `SCHEDULED` on an early cancellation and moves to `UNMET` on a late one, incrementing its `version` by 1; a hearing still in `SCHEDULED` because the assignment was only `PROPOSED` is left untouched, as is a hearing already in `CONTINUED`."
    PRD §3.8: "`LATE_CANCELLATION` is computed when a confirmed assignment is cancelled inside the schedule's `late_cancellation_hours`; it pays `late_cancellation_pay_hours` at the snapshot tier's rate with the delivery multiplier applied, adds any rare-language premium on that service component, contributes no travel at all, and sets `late_cancellation` to true."
    PRD §3.8: "The `PROVISIONAL` variant writes that total to `provisional_total_cents`; the `FINAL` and `LATE_CANCELLATION` variants write it to `final_total_cents` and leave `provisional_total_cents` frozen at whatever the provisional run produced."
    PRD §3.2: "`pending_pay_cents` is the sum of `final_total_cents` over this interpreter's pay claims whose status is `FINALIZED`, `SUBMITTED`, or `APPROVED`, and `paid_pay_cents` is the same sum restricted to claims in `PAID`."
    PRD §2.9: "`obligated_pay_cents` is the sum of `final_total_cents` over every pay claim whose `status` is one of `FINALIZED`, `SUBMITTED`, `APPROVED`, or `PAID`, reached through the same assignment-to-hearing-to-courthouse path."

    Design: Corner/Cross-Cutting Complexity Layers/the_late_cancellation_lead_time_threshold_is_inclusive_at_forty_eight_hours_and_flips_the_money_path_thirty_minutes_later
    """
    bundle = fixtures.setup_confirmed_assignment(
        hearing_overrides={
            "case_number": "CR-2026-9002",
            "hearing_type": "PLEA",
            "scheduled_start": "2026-09-20T09:00:00.000Z",
            "scheduled_end": "2026-09-20T10:00:00.000Z",
        }
    )
    courthouse_id = bundle["courthouse"]["id"]
    budget_cents = bundle["courthouse"]["pay_budget_cents"]
    claim = bundle["pay_claim"]

    # 47.5 hours of lead time — thirty minutes inside the 48-hour threshold.
    fixtures.set_clock("2026-09-18T09:30:00.000Z")
    cancelled = fixtures.cancel_assignment(bundle["assignment"]["id"])
    assert cancelled["service_status"] == "CANCELLED", (
        f"expected the assignment to be CANCELLED, got {cancelled['service_status']}"
    )

    claim_after = fixtures.read_pay_claim(claim["id"])
    assert claim_after["status"] == "FINALIZED", (
        f"expected lead time strictly below the threshold to finalize the claim, "
        f"got status {claim_after['status']}"
    )
    assert claim_after["variant"] == "FINAL", (
        f"expected variant FINAL on the late-cancellation path, got "
        f"{claim_after['variant']}"
    )
    assert claim_after["late_cancellation"] is True, (
        f"expected late_cancellation true, got {claim_after['late_cancellation']}"
    )
    # late_cancellation_pay_hours is 2.0 on the governing schedule, paid at the
    # CERTIFIED rate of 8750 cents with the IN_PERSON multiplier of exactly 1.
    assert float(claim_after["billable_hours"]) == 2.0, (
        f"expected billable_hours taken directly from late_cancellation_pay_hours "
        f"(2.0), got {claim_after['billable_hours']}"
    )
    assert claim_after["service_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected service_cents 2.0 x 8750 = {MINIMUM_CALL_ENCUMBRANCE_CENTS}, "
        f"got {claim_after['service_cents']}"
    )
    assert claim_after["travel_cents"] == 0, (
        f"expected no travel on a late cancellation, got "
        f"{claim_after['travel_cents']}"
    )
    assert claim_after["final_total_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected final_total_cents {MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{claim_after['final_total_cents']}"
    )
    assert claim_after["provisional_total_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected provisional_total_cents frozen at "
        f"{MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{claim_after['provisional_total_cents']}"
    )

    hearing_after = fixtures.read_hearing(bundle["hearing"]["id"])
    assert hearing_after["status"] == "UNMET", (
        f"expected the COVERED hearing to move to UNMET on a late cancellation, "
        f"got {hearing_after['status']}"
    )

    ledger = fixtures.read_courthouse(courthouse_id)
    assert ledger["encumbered_pay_cents"] == 0, (
        f"expected the claim to leave the ENCUMBERED set, so "
        f"encumbered_pay_cents is 0, got {ledger['encumbered_pay_cents']}"
    )
    assert ledger["obligated_pay_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected the finalized claim to obligate "
        f"{MINIMUM_CALL_ENCUMBRANCE_CENTS}, got {ledger['obligated_pay_cents']}"
    )
    assert ledger["available_pay_cents"] == budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected available_pay_cents "
        f"{budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{ledger['available_pay_cents']}"
    )

    interpreter_after = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert interpreter_after["pending_pay_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected pending_pay_cents recomputed from the newly finalized claim to "
        f"{MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{interpreter_after['pending_pay_cents']}"
    )


def test_a_second_sweep_at_the_same_clock_reports_nothing_and_rewrites_nothing(api):
    """PRD §3.10: "Every credential in `ACTIVE` status whose `expires_on` date lies strictly before the current logical-clock date moves `ACTIVE → LAPSED` with its `tier` cleared, the owning language's `active_credentialed_count` is decremented, the holder's `credential_tier` and `credentialed_language_ids` are recomputed, and a holder left with no active credential at all drops `ACTIVE → INACTIVE`, which cancels each of their `PROPOSED` and `CONFIRMED` assignments with `cancel_reason_code` set to `CREDENTIAL_LAPSED`, voiding those assignments' encumbered claims and returning their hearings to `SCHEDULED`."
    PRD §3.10: "Its response carries `swept_at`, the logical-clock instant the run executed, together with six identifier arrays: `lapsed_credential_ids`, `downgraded_interpreter_ids`, `expired_action_ids`, `reinstated_interpreter_ids`, `unmet_hearing_ids`, `cancelled_assignment_ids`, and `voided_pay_claim_ids`."
    PRD §3.10: "The run is idempotent with respect to the logical clock: invoked a second time without the clock having moved, it returns all-empty arrays and mutates nothing."
    PRD §3.3: "On success the credential's `status` becomes `ACTIVE` and `tier` is set to `target_tier`; `issued_on` records the logical-clock date of this first activation; `expires_on` is set 730 days — two full years — after that date for a `MASTER`, `CERTIFIED`, or `REGISTERED` credential, and 365 days after it for a `PROVISIONAL` one, whose shorter cycle reflects that it rests on no examination; and `grace_through` is set 90 days after `expires_on`."
    PRD §3.2: "`credential_tier` is the highest tier among the interpreter's credentials whose status is `ACTIVE`, ranked `MASTER` above `CERTIFIED` above `REGISTERED` above `PROVISIONAL`, and reads `NONE` when no credential of theirs is active."
    PRD §3.10: "It mutates no entity, and a target earlier than the clock's present reading is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/Cross-Cutting Complexity Layers/a_second_sweep_at_the_same_clock_reports_nothing_and_rewrites_nothing
    """
    empty_array_fields = (
        "lapsed_credential_ids",
        "downgraded_interpreter_ids",
        "expired_action_ids",
        "reinstated_interpreter_ids",
        "unmet_hearing_ids",
        "cancelled_assignment_ids",
        "voided_pay_claim_ids",
    )

    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    bundle = fixtures.setup_active_interpreter(language["id"])
    interpreter_id = bundle["interpreter"]["id"]
    credential = bundle["credential"]
    assert credential["expires_on"] == "2028-07-31", (
        f"expected a CERTIFIED credential activated on 2026-08-01 to expire 730 "
        f"days later on 2028-07-31, got {credential['expires_on']}"
    )

    quiet = fixtures.run_daily_sweep()
    assert "swept_at" in quiet, "expected the sweep response to carry swept_at"
    for field in empty_array_fields:
        assert quiet[field] == [], (
            f"expected {field} empty on a sweep with nothing due, got {quiet[field]}"
        )

    # One clock tick past the credential's expiry date.
    fixtures.set_clock("2028-08-01T00:00:00.000Z")
    first = fixtures.run_daily_sweep()
    assert first["lapsed_credential_ids"] == [credential["id"]], (
        f"expected the expired credential {credential['id']} to be reported as "
        f"lapsed, got {first['lapsed_credential_ids']}"
    )
    assert first["downgraded_interpreter_ids"] == [interpreter_id], (
        f"expected the holder {interpreter_id} to be reported as downgraded, got "
        f"{first['downgraded_interpreter_ids']}"
    )
    for field in ("expired_action_ids", "reinstated_interpreter_ids",
                  "unmet_hearing_ids", "cancelled_assignment_ids",
                  "voided_pay_claim_ids"):
        assert first[field] == [], (
            f"expected {field} empty when only a credential expired, got "
            f"{first[field]}"
        )

    lapsed = fixtures.read_credential(credential["id"])
    assert lapsed["status"] == "LAPSED", (
        f"expected the credential to be LAPSED, got {lapsed['status']}"
    )
    assert lapsed["tier"] is None, (
        f"expected the lapsed credential's tier cleared to null, got {lapsed['tier']}"
    )
    downgraded = fixtures.read_interpreter(interpreter_id)
    assert downgraded["roster_status"] == "INACTIVE", (
        f"expected the holder with no active credential to drop to INACTIVE, got "
        f"{downgraded['roster_status']}"
    )
    assert downgraded["credential_tier"] == "NONE", (
        f"expected credential_tier NONE with no active credential, got "
        f"{downgraded['credential_tier']}"
    )
    assert downgraded["credentialed_language_ids"] == [], (
        f"expected credentialed_language_ids emptied, got "
        f"{downgraded['credentialed_language_ids']}"
    )
    language_after = fixtures.read_language(language["id"])
    assert language_after["active_credentialed_count"] == 0, (
        f"expected the language's active_credentialed_count decremented to 0, got "
        f"{language_after['active_credentialed_count']}"
    )

    second = fixtures.run_daily_sweep()
    for field in empty_array_fields:
        assert second[field] == [], (
            f"expected {field} empty on the second sweep at the same clock, got "
            f"{second[field]}"
        )
    assert fixtures.read_credential(credential["id"])["version"] == lapsed["version"], (
        f"expected the second sweep to rewrite nothing, leaving the credential at "
        f"version {lapsed['version']}"
    )
    assert (
        fixtures.read_interpreter(interpreter_id)["version"] == downgraded["version"]
    ), (
        f"expected the second sweep to rewrite nothing, leaving the interpreter at "
        f"version {downgraded['version']}"
    )
    assert (
        fixtures.read_language(language["id"])["version"] == language_after["version"]
    ), (
        f"expected the second sweep to rewrite nothing, leaving the language at "
        f"version {language_after['version']}"
    )

    # Moving the clock forward finds nothing new either: the credential has
    # already left ACTIVE, so step one no longer selects it.
    fixtures.set_clock("2028-08-02T00:00:00.000Z")
    third = fixtures.run_daily_sweep()
    for field in empty_array_fields:
        assert third[field] == [], (
            f"expected {field} empty on a later sweep with nothing newly due, got "
            f"{third[field]}"
        )
    assert fixtures.read_credential(credential["id"])["version"] == lapsed["version"], (
        f"expected the already-lapsed credential to stay at version "
        f"{lapsed['version']}"
    )

    backwards = api.set_clock(set_clock_payload("2028-08-01T00:00:00.000Z"), ADMIN)
    validate_error(backwards, ApiErrorId.ERR_INVALID_REQUEST)


def test_every_field_touched_by_a_confirmation_is_correct_on_the_next_read(api):
    """PRD §3.7: "That schedule's `id` is pinned onto a freshly created pay claim as `rate_schedule_id`, and a schedule published later never changes an existing claim."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."
    PRD §2.9: "`encumbered_pay_cents` is the sum of `provisional_total_cents` over every pay claim whose `status` is `ENCUMBERED` and whose assignment's hearing sits at this courthouse."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."
    PRD §2.9: "All three derived values are recomputed on every pay-claim status change and on every assignment confirmation, cancellation, completion and no-show."
    PRD §3.2: "`pending_pay_cents` is the sum of `final_total_cents` over this interpreter's pay claims whose status is `FINALIZED`, `SUBMITTED`, or `APPROVED`, and `paid_pay_cents` is the same sum restricted to claims in `PAID`."
    PRD §3.6: "Assignments are readable individually and by list, the list filterable by `hearing_id`, `interpreter_id`, `credential_id`, `service_status`, and `compliance_status`."

    Design: Corner/Consistency Model/every_ledger_and_roster_field_touched_by_a_confirmation_is_already_correct_on_the_next_read
    """
    config = fixtures.setup_program_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter_id = bundle["interpreter"]["id"]
    budget_cents = config["courthouse"]["pay_budget_cents"]
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-3301",
        hearing_type="PLEA",
        scheduled_start="2026-09-10T09:00:00.000Z",
        scheduled_end="2026-09-10T10:30:00.000Z",
    )
    assignment = fixtures.propose_assignment(hearing["id"], interpreter_id)
    version_before_confirm = assignment["version"]

    confirmed = validate_success(
        api.confirm_assignment(assignment["id"], make_interpreter_headers(interpreter_id))
    )
    assert confirmed["service_status"] == "CONFIRMED", (
        f"expected the confirm response to read CONFIRMED, got "
        f"{confirmed['service_status']}"
    )
    assert confirmed["version"] == version_before_confirm + 1, (
        f"expected the confirm to increment the assignment version to "
        f"{version_before_confirm + 1}, got {confirmed['version']}"
    )

    hearing_after = fixtures.read_hearing(hearing["id"])
    assert hearing_after["status"] == "COVERED", (
        f"expected the hearing to read COVERED on the next read, got "
        f"{hearing_after['status']}"
    )

    claims, meta = validate_paginated(
        api.list_pay_claims(FISCAL, params={"assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one claim created by the confirmation, got "
        f"{meta['total_count']}"
    )
    claim = claims[0]
    assert claim["status"] == "ENCUMBERED", (
        f"expected the new claim to read ENCUMBERED, got {claim['status']}"
    )
    assert claim["variant"] == "PROVISIONAL", (
        f"expected the new claim's variant to read PROVISIONAL, got "
        f"{claim['variant']}"
    )
    assert claim["provisional_total_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected provisional_total_cents {MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{claim['provisional_total_cents']}"
    )
    assert claim["final_total_cents"] is None, (
        f"expected final_total_cents null before finalization, got "
        f"{claim['final_total_cents']}"
    )
    assert claim["rate_schedule_id"] == config["rate_schedule"]["id"], (
        f"expected the claim pinned to rate schedule "
        f"{config['rate_schedule']['id']}, got {claim['rate_schedule_id']}"
    )

    ledger = fixtures.read_courthouse(config["courthouse"]["id"])
    assert ledger["encumbered_pay_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected encumbered_pay_cents {MINIMUM_CALL_ENCUMBRANCE_CENTS} on the "
        f"next read, got {ledger['encumbered_pay_cents']}"
    )
    assert ledger["obligated_pay_cents"] == 0, (
        f"expected obligated_pay_cents still 0, got {ledger['obligated_pay_cents']}"
    )
    assert ledger["available_pay_cents"] == budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected available_pay_cents "
        f"{budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{ledger['available_pay_cents']}"
    )

    interpreter_after = fixtures.read_interpreter(interpreter_id)
    assert interpreter_after["pending_pay_cents"] == 0, (
        f"expected pending_pay_cents 0 while the only claim is ENCUMBERED rather "
        f"than FINALIZED, SUBMITTED or APPROVED, got "
        f"{interpreter_after['pending_pay_cents']}"
    )

    confirmed_rows, confirmed_meta = validate_paginated(
        api.list_assignments(
            COORDINATOR,
            params={"hearing_id": hearing["id"], "service_status": "CONFIRMED"},
        )
    )
    assert confirmed_meta["total_count"] == 1, (
        f"expected the CONFIRMED filter to return the just-confirmed assignment, "
        f"got {confirmed_meta['total_count']} rows"
    )
    assert confirmed_rows[0]["id"] == assignment["id"], (
        f"expected the CONFIRMED filter to return {assignment['id']}, got "
        f"{confirmed_rows[0]['id']}"
    )
    proposed_rows, proposed_meta = validate_paginated(
        api.list_assignments(
            COORDINATOR,
            params={"hearing_id": hearing["id"], "service_status": "PROPOSED"},
        )
    )
    assert proposed_meta["total_count"] == 0, (
        f"expected the PROPOSED filter to return nothing after the confirmation, "
        f"got {proposed_meta['total_count']} rows"
    )
    assert proposed_rows == [], (
        f"expected no PROPOSED assignment to remain, got {proposed_rows}"
    )


def test_a_confirmation_refused_by_the_budget_check_leaves_no_partial_state(api):
    """PRD §3.7: "If the provisional total exceeds `available_pay_cents` the confirmation is refused with `ERR_COURTHOUSE_BUDGET_EXCEEDED` and nothing is created."
    PRD §2.9: "A confirmation whose provisional total is exactly equal to the courthouse's `available_pay_cents` is accepted; only an amount strictly greater than the remainder is refused, with `ERR_COURTHOUSE_BUDGET_EXCEEDED` (HTTP 409)."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."
    PRD §3.7: "An **early** cancellation — lead time at or above that threshold — voids the encumbered claim: it moves `ENCUMBERED → VOIDED`, `provisional_total_cents` is preserved on the row for audit while `final_total_cents` stays null, and exactly `provisional_total_cents` is released from the courthouse's `encumbered_pay_cents`, restoring the ledger to its pre-confirmation value."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Corner/Consistency Model/no_partial_state_survives_a_confirmation_that_fails_the_budget_check
    """
    tight_budget_cents = 20000
    config = fixtures.setup_program_config(
        courthouse_overrides={"pay_budget_cents": tight_budget_cents}
    )
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter_id = bundle["interpreter"]["id"]
    courthouse_id = config["courthouse"]["id"]

    first_hearing = fixtures.schedule_hearing(
        courthouse_id,
        config["language"]["id"],
        case_number="CR-2026-4501",
        hearing_type="PLEA",
        scheduled_start="2026-09-10T09:00:00.000Z",
        scheduled_end="2026-09-10T10:30:00.000Z",
    )
    second_hearing = fixtures.schedule_hearing(
        courthouse_id,
        config["language"]["id"],
        case_number="CR-2026-4502",
        hearing_type="PLEA",
        scheduled_start="2026-09-10T13:00:00.000Z",
        scheduled_end="2026-09-10T14:30:00.000Z",
    )
    first_assignment = fixtures.propose_assignment(first_hearing["id"], interpreter_id)
    second_assignment = fixtures.propose_assignment(second_hearing["id"], interpreter_id)
    second_version_before = second_assignment["version"]

    fixtures.confirm_assignment(first_assignment["id"], interpreter_id)
    ledger_before = fixtures.read_courthouse(courthouse_id)
    assert ledger_before["encumbered_pay_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected the first confirmation to encumber "
        f"{MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{ledger_before['encumbered_pay_cents']}"
    )
    assert ledger_before["available_pay_cents"] == (
        tight_budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS
    ), (
        f"expected available_pay_cents "
        f"{tight_budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{ledger_before['available_pay_cents']}"
    )

    # 17500 is strictly greater than the remaining 2500.
    refused = api.confirm_assignment(
        second_assignment["id"], make_interpreter_headers(interpreter_id)
    )
    validate_error(refused, ApiErrorId.ERR_COURTHOUSE_BUDGET_EXCEEDED)

    second_after = fixtures.read_assignment(second_assignment["id"])
    assert second_after["service_status"] == "PROPOSED", (
        f"expected the refused assignment to stay PROPOSED, got "
        f"{second_after['service_status']}"
    )
    assert second_after["version"] == second_version_before, (
        f"expected the refused confirmation to leave the assignment at version "
        f"{second_version_before}, got {second_after['version']}"
    )
    second_hearing_after = fixtures.read_hearing(second_hearing["id"])
    assert second_hearing_after["status"] == "SCHEDULED", (
        f"expected the hearing not to bubble to COVERED, got "
        f"{second_hearing_after['status']}"
    )
    assert fixtures.pay_claims_for_assignment(second_assignment["id"]) == [], (
        "expected no pay claim to exist for the refused confirmation"
    )
    ledger_after = fixtures.read_courthouse(courthouse_id)
    assert ledger_after["encumbered_pay_cents"] == (
        ledger_before["encumbered_pay_cents"]
    ), (
        f"expected encumbered_pay_cents unchanged at "
        f"{ledger_before['encumbered_pay_cents']}, got "
        f"{ledger_after['encumbered_pay_cents']}"
    )
    assert ledger_after["obligated_pay_cents"] == 0, (
        f"expected obligated_pay_cents still 0, got "
        f"{ledger_after['obligated_pay_cents']}"
    )
    assert ledger_after["available_pay_cents"] == (
        ledger_before["available_pay_cents"]
    ), (
        f"expected available_pay_cents unchanged at "
        f"{ledger_before['available_pay_cents']}, got "
        f"{ledger_after['available_pay_cents']}"
    )

    # Releasing the first encumbrance makes the very same confirmation fit.
    fixtures.cancel_assignment(first_assignment["id"])
    released = fixtures.read_courthouse(courthouse_id)
    assert released["available_pay_cents"] == tight_budget_cents, (
        f"expected the early cancellation to restore available_pay_cents to "
        f"{tight_budget_cents}, got {released['available_pay_cents']}"
    )
    accepted = validate_success(
        api.confirm_assignment(
            second_assignment["id"], make_interpreter_headers(interpreter_id)
        )
    )
    assert accepted["service_status"] == "CONFIRMED", (
        f"expected the retry to be accepted as CONFIRMED, got "
        f"{accepted['service_status']}"
    )
    assert accepted["version"] == second_version_before + 1, (
        f"expected the accepted confirmation to increment the version to "
        f"{second_version_before + 1}, got {accepted['version']}"
    )
    final_ledger = fixtures.read_courthouse(courthouse_id)
    assert final_ledger["encumbered_pay_cents"] == MINIMUM_CALL_ENCUMBRANCE_CENTS, (
        f"expected the accepted confirmation to encumber "
        f"{MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{final_ledger['encumbered_pay_cents']}"
    )
    assert final_ledger["available_pay_cents"] == (
        tight_budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS
    ), (
        f"expected available_pay_cents "
        f"{tight_budget_cents - MINIMUM_CALL_ENCUMBRANCE_CENTS}, got "
        f"{final_ledger['available_pay_cents']}"
    )
