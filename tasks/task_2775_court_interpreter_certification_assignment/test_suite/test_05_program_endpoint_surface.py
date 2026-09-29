"""The program's endpoint surface: CRUD, ordered action chains, bulk operations,
cross-reference links, computed reads and conditional branching actions.

Courthouse create/read/list/patch; the ordered pay-claim money chain
submit -> approve -> pay; the daily operations run deciding per row; the
complaint-to-assignment link that freezes the compliance dimension; the
quality-score computed read; the ranked eligible-interpreter pool; and the
single advance action that branches on target tier
(PRD §2.3, §2.6, §2.9, §3.1-§3.3, §3.6, §3.8-§3.10).
"""

import test_helpers.fixtures as fixtures
from test_helpers import (
    ApiErrorId,
    assert_complaint,
    assert_courthouse,
    assert_courthouse_ledger_invariants,
    assert_credential,
    assert_pay_claim,
    assert_quality_score_read,
    assert_sweep_response,
    assert_three_fraction_digit_timestamp,
    create_complaint_payload,
    create_courthouse_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A syntactically well-formed UUID that no row in the program ever carries.
UNKNOWN_UUID = "00000000-0000-4000-8000-0000000000a5"

# The MOTION hearing every money scenario below shares: one scheduled hour at
# the main courthouse, well inside the future of the default logical clock.
MOTION_HEARING = {
    "case_number": "CR-2026-1801",
    "hearing_type": "MOTION",
    "in_custody": False,
    "scheduled_start": "2026-08-25T09:00:00.000Z",
    "scheduled_end": "2026-08-25T10:00:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}


# ---------------------------------------------------------------------------
# Courthouse: the one entity with a full create-read-list-patch surface
# ---------------------------------------------------------------------------
def test_courthouse_creation_seeds_the_ledger_and_defaults_the_facility_open(
    api, program_admin_headers, fiscal_officer_headers
):
    """PRD §3.1: "The facility's `status` is `OPEN` or `CLOSED` and defaults to `OPEN`."
    PRD §3.1: "Creation initialises `encumbered_pay_cents` and `obligated_pay_cents` to 0,
    which leaves `available_pay_cents` equal to `pay_budget_cents`."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less
    `obligated_pay_cents`."

    Design: Corner/Endpoints/courthouse_crud_surface_creates_reads_lists_and_patches
    """
    payload = create_courthouse_payload(
        name="Capitol Main Courthouse",
        county_code="CAS",
        courtroom_count=12,
        remote_equipment_tier="CERTIFIED_VRI",
        vri_concurrent_capacity=2,
        pay_budget_cents=5_000_000,
    )
    payload.pop("status")

    created = validate_success(api.create_courthouse(payload, program_admin_headers), 201)
    assert_courthouse(created)
    assert created["status"] == "OPEN", (
        f"an omitted status must default to OPEN, got {created['status']!r}"
    )
    assert created["encumbered_pay_cents"] == 0, (
        f"creation must seed encumbered_pay_cents at 0, got "
        f"{created['encumbered_pay_cents']}"
    )
    assert created["obligated_pay_cents"] == 0, (
        f"creation must seed obligated_pay_cents at 0, got "
        f"{created['obligated_pay_cents']}"
    )
    assert created["available_pay_cents"] == 5_000_000, (
        f"expected available_pay_cents 5000000 on a fresh courthouse, got "
        f"{created['available_pay_cents']}"
    )

    fetched = validate_success(api.get_courthouse(created["id"], fiscal_officer_headers))
    assert fetched["name"] == "Capitol Main Courthouse", (
        f"expected the created name back, got {fetched['name']!r}"
    )
    assert fetched["vri_concurrent_capacity"] == 2, (
        f"expected vri_concurrent_capacity 2 back, got "
        f"{fetched['vri_concurrent_capacity']}"
    )
    assert_courthouse_ledger_invariants(fetched)


def test_courthouse_list_is_ordered_by_name_ascending_with_pagination_meta(
    api, program_admin_headers, scheduling_coordinator_headers
):
    """PRD §2.3: "The endpoints that declare their own ordering are: languages by `code`
    ascending; courthouses by `name` ascending; rate schedules by `effective_from`
    ascending; interpreters by `full_name` ascending and then `created_at` ascending;
    hearings by `scheduled_start` ascending and then `created_at` ascending; examination
    attempts by `taken_on` ascending and then `created_at` ascending; disciplinary actions
    by `effective_from` ascending and then `created_at` ascending; unmet-need reports by
    `period_start` ascending and then `created_at` ascending; and the ranked
    eligible-interpreter pool, whose ordering is described in §3.5."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside
    `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true exactly when rows remain beyond the
    current page."

    Design: Corner/Endpoints/courthouse_crud_surface_creates_reads_lists_and_patches
    """
    main = validate_success(
        api.create_courthouse(
            create_courthouse_payload(name="Capitol Main Courthouse", county_code="CAS"),
            program_admin_headers,
        ),
        201,
    )
    annex = validate_success(
        api.create_courthouse(
            create_courthouse_payload(
                name="Annex Courthouse",
                county_code="CAS",
                courtroom_count=3,
                remote_equipment_tier="NONE",
                vri_concurrent_capacity=0,
                pay_budget_cents=250_000,
            ),
            program_admin_headers,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_courthouses(scheduling_coordinator_headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, (
        f"two rows on a limit-10 page leaves nothing beyond it, got has_more "
        f"{meta['has_more']!r}"
    )
    names = [row["name"] for row in rows]
    assert names == ["Annex Courthouse", "Capitol Main Courthouse"], (
        f"courthouses must come back by name ascending, got {names}"
    )
    assert [row["id"] for row in rows] == [annex["id"], main["id"]], (
        "name-ascending ordering must place the Annex row before the Capitol Main row"
    )


def test_courthouse_patch_moves_only_supplied_keys_and_bumps_the_version(
    api, program_admin_headers
):
    """PRD §3.1: "A courthouse's equipment tier, video capacity, facility status and pay
    budget can all be revised later by a `ProgramAdmin`, and two of those revisions have
    teeth."
    PRD §3.1: "Every accepted revision increments the courthouse's `version` by 1."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less
    `obligated_pay_cents`."

    Design: Corner/Endpoints/courthouse_crud_surface_creates_reads_lists_and_patches
    """
    created = validate_success(
        api.create_courthouse(
            create_courthouse_payload(
                name="Capitol Main Courthouse",
                county_code="CAS",
                courtroom_count=12,
                remote_equipment_tier="CERTIFIED_VRI",
                vri_concurrent_capacity=2,
                pay_budget_cents=5_000_000,
            ),
            program_admin_headers,
        ),
        201,
    )
    version_before = created["version"]

    patched = validate_success(
        api.patch_courthouse(
            created["id"],
            {"vri_concurrent_capacity": 4, "pay_budget_cents": 6_000_000},
            program_admin_headers,
        )
    )
    assert patched["version"] == version_before + 1, (
        f"expected version {version_before + 1} after the patch, got {patched['version']}"
    )
    assert patched["vri_concurrent_capacity"] == 4, (
        f"expected vri_concurrent_capacity 4 after the patch, got "
        f"{patched['vri_concurrent_capacity']}"
    )
    assert patched["pay_budget_cents"] == 6_000_000, (
        f"expected pay_budget_cents 6000000 after the patch, got "
        f"{patched['pay_budget_cents']}"
    )
    assert patched["available_pay_cents"] == 6_000_000, (
        f"available_pay_cents must follow the raised budget on an empty ledger, got "
        f"{patched['available_pay_cents']}"
    )
    assert patched["remote_equipment_tier"] == "CERTIFIED_VRI", (
        "an unsupplied remote_equipment_tier must be left where it was, got "
        f"{patched['remote_equipment_tier']!r}"
    )
    assert patched["county_code"] == "CAS", (
        f"county_code is not revisable and must survive the patch, got "
        f"{patched['county_code']!r}"
    )
    assert patched["courtroom_count"] == 12, (
        f"courtroom_count is not revisable and must survive the patch, got "
        f"{patched['courtroom_count']}"
    )

    refetched = validate_success(api.get_courthouse(created["id"], program_admin_headers))
    assert refetched["vri_concurrent_capacity"] == 4, (
        "the fetch after the patch must return the patched capacity, got "
        f"{refetched['vri_concurrent_capacity']}"
    )
    assert refetched["available_pay_cents"] == 6_000_000, (
        "the fetch after the patch must return the recomputed remainder, got "
        f"{refetched['available_pay_cents']}"
    )
    assert_courthouse_ledger_invariants(refetched)


# ---------------------------------------------------------------------------
# Pay claim: three actions that only run in one order
# ---------------------------------------------------------------------------
def test_pay_claim_cannot_be_approved_before_its_holder_submits_it(api, fiscal_officer_headers):
    """PRD §3.8: "A `VOIDED` claim accepts none of them, and any of the three requested from
    the wrong status is refused with `ERR_INVALID_PAY_CLAIM_STATE`."
    PRD §2.12: "Pay-claim `status` admits the requested transition — otherwise
    `ERR_INVALID_PAY_CLAIM_STATE` (409)."
    PRD §3.8: "Then take the larger of that rounded figure and the rate schedule's
    `minimum_call_hours`; the result is `billable_hours`, always a multiple of 0.25 and always
    carried to two decimal places."

    Design: Corner/Endpoints/pay_claim_action_chain_runs_submit_then_approve_then_pay_in_order
    """
    bundle = fixtures.setup_served_assignment(
        check_in_clock="2026-08-25T09:00:00Z",
        actual_end_utc="2026-08-25T10:00:00.000Z",
        one_way_miles=10.0,
        hearing_overrides=MOTION_HEARING,
    )
    claim = bundle["pay_claim"]
    assert_pay_claim(claim)
    assert claim["status"] == "FINALIZED", (
        f"completion must leave the claim FINALIZED, got {claim['status']!r}"
    )
    assert claim["final_total_cents"] == 17_500, (
        f"expected final_total_cents 17500 for a two-hour minimum call at the CERTIFIED "
        f"rate, got {claim['final_total_cents']}"
    )

    validate_error(
        api.approve_pay_claim(claim["id"], fiscal_officer_headers),
        ApiErrorId.ERR_INVALID_PAY_CLAIM_STATE,
    )

    unchanged = fixtures.read_pay_claim(claim["id"])
    assert unchanged["status"] == "FINALIZED", (
        f"the refused approval must leave the claim FINALIZED, got {unchanged['status']!r}"
    )
    assert unchanged["version"] == claim["version"], (
        f"the refused approval must not bump the version, expected {claim['version']}, "
        f"got {unchanged['version']}"
    )


def test_pay_claim_walks_submit_then_approve_then_pay_with_a_version_bump_each_hop(api):
    """PRD §3.8: "The `Interpreter` who served the assignment submits their own claim,
    `FINALIZED → SUBMITTED`."
    PRD §3.8: "Finally the same `FiscalOfficer` role issues the warrant, `APPROVED → PAID`,
    supplying a `payment_reference` that is recorded on the claim; that transition moves
    `final_total_cents` out of the interpreter's `pending_pay_cents` and into their
    `paid_pay_cents`."
    PRD §3.8: "Each of the three transitions increments the claim's `version` by 1."

    Design: Corner/Endpoints/pay_claim_action_chain_runs_submit_then_approve_then_pay_in_order
    """
    bundle = fixtures.setup_served_assignment(
        check_in_clock="2026-08-25T09:00:00Z",
        actual_end_utc="2026-08-25T10:00:00.000Z",
        one_way_miles=10.0,
        hearing_overrides=MOTION_HEARING,
    )
    claim = bundle["pay_claim"]
    finalized_version = claim["version"]

    submitted = fixtures.submit_pay_claim(claim["id"], bundle["interpreter"]["id"])
    assert submitted["status"] == "SUBMITTED", (
        f"submit must move the claim to SUBMITTED, got {submitted['status']!r}"
    )
    assert submitted["version"] == finalized_version + 1, (
        f"expected version {finalized_version + 1} after submit, got {submitted['version']}"
    )

    approved = fixtures.approve_pay_claim(claim["id"])
    assert approved["status"] == "APPROVED", (
        f"approve must move the claim to APPROVED, got {approved['status']!r}"
    )
    assert approved["version"] == finalized_version + 2, (
        f"expected version {finalized_version + 2} after approve, got {approved['version']}"
    )

    paid = fixtures.issue_payment(claim["id"], payment_reference="WARRANT-2026-000417")
    assert paid["status"] == "PAID", (
        f"pay must move the claim to PAID, got {paid['status']!r}"
    )
    assert paid["version"] == finalized_version + 3, (
        f"expected version {finalized_version + 3} after pay, got {paid['version']}"
    )
    assert paid["payment_reference"] == "WARRANT-2026-000417", (
        f"the supplied warrant number must be stored, got {paid['payment_reference']!r}"
    )
    assert paid["final_total_cents"] == 17_500, (
        f"payment must not move the money, expected 17500, got {paid['final_total_cents']}"
    )


def test_paying_a_claim_moves_the_money_from_encumbered_to_obligated(api, fiscal_officer_headers):
    """PRD §3.8: "Finally the same `FiscalOfficer` role issues the warrant, `APPROVED → PAID`,
    supplying a `payment_reference` that is recorded on the claim; that transition moves
    `final_total_cents` out of the interpreter's `pending_pay_cents` and into their
    `paid_pay_cents`."
    PRD §2.9: "`encumbered_pay_cents` is the sum of `provisional_total_cents` over every pay
    claim whose `status` is `ENCUMBERED` and whose assignment's hearing sits at this
    courthouse."
    PRD §2.9: "`obligated_pay_cents` is the sum of `final_total_cents` over every pay claim
    whose `status` is one of `FINALIZED`, `SUBMITTED`, `APPROVED`, or `PAID`, reached through
    the same assignment-to-hearing-to-courthouse path."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less
    `obligated_pay_cents`."

    Design: Corner/Endpoints/pay_claim_action_chain_runs_submit_then_approve_then_pay_in_order
    """
    bundle = fixtures.setup_served_assignment(
        check_in_clock="2026-08-25T09:00:00Z",
        actual_end_utc="2026-08-25T10:00:00.000Z",
        one_way_miles=10.0,
        hearing_overrides=MOTION_HEARING,
    )
    claim = bundle["pay_claim"]
    fixtures.submit_pay_claim(claim["id"], bundle["interpreter"]["id"])
    fixtures.approve_pay_claim(claim["id"])
    fixtures.issue_payment(claim["id"], payment_reference="WARRANT-2026-000417")

    interpreter = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert interpreter["pending_pay_cents"] == 0, (
        f"payment must clear pending_pay_cents, got {interpreter['pending_pay_cents']}"
    )
    assert interpreter["paid_pay_cents"] == 17_500, (
        f"expected paid_pay_cents 17500 after payment, got {interpreter['paid_pay_cents']}"
    )

    courthouse = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"no claim is left in ENCUMBERED status, so the encumbrance sum must be 0, got "
        f"{courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == 17_500, (
        f"a PAID claim's final_total_cents belongs to obligated_pay_cents, got "
        f"{courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 4_982_500, (
        f"expected available_pay_cents 4982500 after payment, got "
        f"{courthouse['available_pay_cents']}"
    )
    assert_courthouse_ledger_invariants(courthouse)

    rows, meta = validate_paginated(
        api.list_pay_claims(fiscal_officer_headers, params={"status": "PAID"})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one PAID claim in the program, got {meta['total_count']}"
    )
    assert rows[0]["id"] == claim["id"], (
        "the PAID listing must return the claim that was just paid"
    )


# ---------------------------------------------------------------------------
# The daily operations run: a bulk endpoint that decides row by row
# ---------------------------------------------------------------------------
def _four_hearing_calendar():
    """Two uncovered hearings, one covered hearing, one still in the future."""
    config = fixtures.setup_program_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    courthouse_id = config["courthouse"]["id"]
    language_id = config["language"]["id"]

    due_uncovered_one = fixtures.schedule_hearing(
        courthouse_id, language_id, case_number="CR-2026-1901",
        hearing_type="MOTION", in_custody=False,
        scheduled_start="2026-08-25T09:00:00.000Z",
        scheduled_end="2026-08-25T10:00:00.000Z",
    )
    due_uncovered_two = fixtures.schedule_hearing(
        courthouse_id, language_id, case_number="CR-2026-1902",
        hearing_type="MOTION", in_custody=False,
        scheduled_start="2026-08-25T11:00:00.000Z",
        scheduled_end="2026-08-25T12:00:00.000Z",
    )
    due_covered = fixtures.schedule_hearing(
        courthouse_id, language_id, case_number="CR-2026-1903",
        hearing_type="MOTION", in_custody=False,
        scheduled_start="2026-08-25T13:00:00.000Z",
        scheduled_end="2026-08-25T14:00:00.000Z",
    )
    future = fixtures.schedule_hearing(
        courthouse_id, language_id, case_number="CR-2026-1904",
        hearing_type="MOTION", in_custody=False,
        scheduled_start="2026-09-15T09:00:00.000Z",
        scheduled_end="2026-09-15T10:00:00.000Z",
    )
    assignment = fixtures.propose_assignment(
        due_covered["id"], bundle["interpreter"]["id"]
    )
    fixtures.confirm_assignment(assignment["id"], bundle["interpreter"]["id"])
    return {
        "config": config,
        "interpreter": bundle["interpreter"],
        "due_uncovered_one": due_uncovered_one,
        "due_uncovered_two": due_uncovered_two,
        "due_covered": due_covered,
        "future": future,
        "assignment": assignment,
    }


def test_daily_sweep_unmets_only_the_reached_and_uncovered_hearings(api):
    """PRD §3.10: "**Step three, uncovered hearings.** Every hearing still in `SCHEDULED`
    status whose `scheduled_start` has been reached or passed by the logical clock, and which
    has no assignment in `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`, moves `SCHEDULED → UNMET`,
    and each of that hearing's assignments still in `PROPOSED` is cancelled with
    `cancel_reason_code` set to `COORDINATOR_CANCELLED`."
    PRD §3.10: "Its response carries `swept_at`, the logical-clock instant the run executed,
    together with six identifier arrays: `lapsed_credential_ids`,
    `downgraded_interpreter_ids`, `expired_action_ids`, `reinstated_interpreter_ids`,
    `unmet_hearing_ids`, `cancelled_assignment_ids`, and `voided_pay_claim_ids`."

    Design: Corner/Endpoints/daily_sweep_marks_only_the_hearings_that_are_due_and_leaves_the_rest
    """
    calendar = _four_hearing_calendar()
    fixtures.set_clock("2026-08-26T00:00:00Z")

    result = fixtures.run_daily_sweep()
    assert_sweep_response(result)
    assert_three_fraction_digit_timestamp(result["swept_at"])
    assert result["swept_at"].startswith("2026-08-26T00:00:00"), (
        f"swept_at must be the logical-clock instant the run executed, got "
        f"{result['swept_at']!r}"
    )
    assert sorted(result["unmet_hearing_ids"]) == sorted(
        [calendar["due_uncovered_one"]["id"], calendar["due_uncovered_two"]["id"]]
    ), (
        "only the two reached, uncovered hearings may be swept to UNMET, got "
        f"{result['unmet_hearing_ids']}"
    )
    for field in ("lapsed_credential_ids", "downgraded_interpreter_ids",
                  "expired_action_ids", "reinstated_interpreter_ids",
                  "cancelled_assignment_ids", "voided_pay_claim_ids"):
        assert result[field] == [], (
            f"nothing in this calendar triggers {field}, got {result[field]}"
        )

    assert fixtures.read_hearing(calendar["due_uncovered_one"]["id"])["status"] == "UNMET", (
        "the first reached uncovered hearing must read UNMET after the run"
    )
    assert fixtures.read_hearing(calendar["due_uncovered_two"]["id"])["status"] == "UNMET", (
        "the second reached uncovered hearing must read UNMET after the run"
    )
    assert fixtures.read_hearing(calendar["due_covered"]["id"])["status"] == "COVERED", (
        "a hearing held by a CONFIRMED assignment must be left COVERED"
    )
    assert fixtures.read_hearing(calendar["future"]["id"])["status"] == "SCHEDULED", (
        "a hearing whose scheduled_start the clock has not reached must be left SCHEDULED"
    )

    claim = fixtures.pay_claim_for_assignment(calendar["assignment"]["id"])
    assert claim["status"] == "ENCUMBERED", (
        f"the covered hearing's claim must be untouched, got {claim['status']!r}"
    )
    courthouse = fixtures.read_courthouse(calendar["config"]["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 17_500, (
        f"the surviving encumbrance must still stand, got "
        f"{courthouse['encumbered_pay_cents']}"
    )


def test_daily_sweep_repeated_on_the_same_clock_reports_nothing_and_mutates_nothing(api):
    """PRD §3.10: "The run is idempotent with respect to the logical clock: invoked a second
    time without the clock having moved, it returns all-empty arrays and mutates nothing."

    Design: Corner/Endpoints/daily_sweep_marks_only_the_hearings_that_are_due_and_leaves_the_rest
    """
    calendar = _four_hearing_calendar()
    fixtures.set_clock("2026-08-26T00:00:00Z")
    fixtures.run_daily_sweep()

    after_first = {
        key: fixtures.read_hearing(calendar[key]["id"])
        for key in ("due_uncovered_one", "due_uncovered_two", "due_covered", "future")
    }

    second = fixtures.run_daily_sweep()
    assert_sweep_response(second)
    for field in ("lapsed_credential_ids", "downgraded_interpreter_ids",
                  "expired_action_ids", "reinstated_interpreter_ids",
                  "unmet_hearing_ids", "cancelled_assignment_ids",
                  "voided_pay_claim_ids"):
        assert second[field] == [], (
            f"a second run on an unmoved clock must report an empty {field}, got "
            f"{second[field]}"
        )

    for key, before in after_first.items():
        now = fixtures.read_hearing(calendar[key]["id"])
        assert now["status"] == before["status"], (
            f"{key} changed status on the idempotent second run: "
            f"{before['status']!r} -> {now['status']!r}"
        )
        assert now["version"] == before["version"], (
            f"{key} was mutated by the idempotent second run: version "
            f"{before['version']} -> {now['version']}"
        )


# ---------------------------------------------------------------------------
# Complaint intake: the optional cross-reference with a side effect
# ---------------------------------------------------------------------------
def test_complaint_naming_an_unknown_assignment_is_refused_and_files_nothing(
    api, quality_reviewer_headers
):
    """PRD §2.6: "A `language_id`, `courthouse_id`, or `rate_schedule_id` that does not
    resolve yields `ERR_CONFIG_RESOURCE_NOT_FOUND`; an `interpreter_id`,
    `ERR_INTERPRETER_NOT_FOUND`; a `hearing_id`, `ERR_HEARING_NOT_FOUND`; an
    `assignment_id`, `ERR_ASSIGNMENT_NOT_FOUND`; a `complaint_id`,
    `ERR_COMPLAINT_NOT_FOUND`."
    PRD §2.6: "Body-level foreign-key resolution is checked on exactly five write endpoints:
    `POST /credentials`, `POST /hearings`, `POST /assignments`, `POST /complaints`, and
    `POST /unmet-need-reports`."

    Design: Corner/Endpoints/complaint_links_to_an_assignment_and_freezes_its_compliance_dimension
    """
    bundle = fixtures.setup_confirmed_assignment(hearing_overrides=MOTION_HEARING)

    payload = create_complaint_payload(
        bundle["interpreter"]["id"],
        category="PROFESSIONALISM",
        severity="MINOR",
        narrative="Counsel reports the interpreter addressed the jury directly.",
    )
    payload["assignment_id"] = UNKNOWN_UUID

    validate_error(
        api.create_complaint(payload, quality_reviewer_headers),
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
    )

    _rows, meta = validate_paginated(api.list_complaints(quality_reviewer_headers, params={}))
    assert meta["total_count"] == 0, (
        f"the refused intake must not have filed a complaint, got total_count "
        f"{meta['total_count']}"
    )
    assignment = fixtures.read_assignment(bundle["assignment"]["id"])
    assert assignment["compliance_status"] == "CLEAR", (
        f"the refused intake must leave the assignment CLEAR, got "
        f"{assignment['compliance_status']!r}"
    )


def test_complaint_that_names_an_assignment_freezes_only_its_compliance_dimension(
    api, quality_reviewer_headers
):
    """PRD §3.9: "Filing sets `status` to `FILED`, records `filed_by_user_id` from the acting
    `X-User-ID`, and leaves `reviewer_user_id`, `reviewer_recommendation`,
    `adjudicator_user_id`, `disposition`, `adjudicated_at` and `appeal_filed_at` all null with
    `remand_count` at 0."
    PRD §3.9: "Intake changes neither the interpreter's roster standing nor their
    `complaint_points` — nothing is proven yet."
    PRD §3.9: "When an `assignment_id` is present, however, the named assignment's
    `compliance_status` moves `CLEAR → UNDER_QUALITY_REVIEW`, which immediately freezes fiscal
    approval of that assignment's pay claim."

    Design: Corner/Endpoints/complaint_links_to_an_assignment_and_freezes_its_compliance_dimension
    """
    bundle = fixtures.setup_confirmed_assignment(hearing_overrides=MOTION_HEARING)
    interpreter_id = bundle["interpreter"]["id"]
    assignment_id = bundle["assignment"]["id"]

    complaint = fixtures.file_complaint(
        interpreter_id,
        assignment_id=assignment_id,
        filer_user_id="qr-001",
        category="PROFESSIONALISM",
        severity="MINOR",
        narrative="Counsel reports the interpreter addressed the jury directly.",
    )
    assert_complaint(complaint)
    assert complaint["status"] == "FILED", (
        f"intake must set status FILED, got {complaint['status']!r}"
    )
    assert complaint["assignment_id"] == assignment_id, (
        f"the named assignment must be recorded, got {complaint['assignment_id']!r}"
    )
    assert complaint["interpreter_id"] == interpreter_id, (
        f"the named interpreter must be recorded, got {complaint['interpreter_id']!r}"
    )
    assert complaint["filed_by_user_id"] == "qr-001", (
        f"filed_by_user_id must come from the acting X-User-ID, got "
        f"{complaint['filed_by_user_id']!r}"
    )
    for field in ("reviewer_user_id", "reviewer_recommendation", "adjudicator_user_id",
                  "disposition", "adjudicated_at", "appeal_filed_at"):
        assert complaint[field] is None, (
            f"intake must leave {field} null, got {complaint[field]!r}"
        )
    assert complaint["remand_count"] == 0, (
        f"intake must leave remand_count at 0, got {complaint['remand_count']}"
    )

    assignment = fixtures.read_assignment(assignment_id)
    assert assignment["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"the linked assignment must move to UNDER_QUALITY_REVIEW, got "
        f"{assignment['compliance_status']!r}"
    )
    assert assignment["service_status"] == "CONFIRMED", (
        f"the service dimension must be untouched by intake, got "
        f"{assignment['service_status']!r}"
    )

    interpreter = fixtures.read_interpreter(interpreter_id)
    assert interpreter["roster_status"] == "ACTIVE", (
        f"intake must not change roster standing, got {interpreter['roster_status']!r}"
    )
    assert interpreter["complaint_points"] == 0, (
        f"intake must not award complaint points, got {interpreter['complaint_points']}"
    )

    rows, meta = validate_paginated(
        api.list_complaints(quality_reviewer_headers, params={"assignment_id": assignment_id})
    )
    assert meta["total_count"] == 1, (
        f"expected one complaint against the named assignment, got {meta['total_count']}"
    )
    assert rows[0]["id"] == complaint["id"], (
        "the assignment-filtered listing must return the complaint just filed"
    )


# ---------------------------------------------------------------------------
# The quality-score read: a computed projection, not a stored row
# ---------------------------------------------------------------------------
def test_quality_score_read_on_a_clean_record_returns_both_variants_at_one_hundred(api):
    """PRD §3.2: "Enrolment sets `roster_status` to `APPLICANT` and `ethics_training_status`
    to `NOT_STARTED`, and it initialises `complaint_points` to 0 with `rolling_12_month_score`
    and `lifetime_score` both at 100."
    PRD §3.2: "A dedicated computed read exposes the two side by side for one interpreter,
    returning `interpreter_id`, `rolling_12_month_score`, `lifetime_score`,
    `complaint_points`, and the two intermediate figures `recent_points` and `older_points`
    that the formula above derived."

    Design: Corner/Endpoints/quality_score_computed_read_exposes_both_variants_and_the_point_split
    """
    fixtures.set_clock()
    interpreter = fixtures.enrol_interpreter()

    score = fixtures.read_quality_score(interpreter["id"])
    assert_quality_score_read(score)
    assert score["interpreter_id"] == interpreter["id"], (
        f"the read must name the interpreter it summarises, got "
        f"{score['interpreter_id']!r}"
    )
    assert score["rolling_12_month_score"] == 100, (
        f"a clean record must read rolling_12_month_score 100, got "
        f"{score['rolling_12_month_score']}"
    )
    assert score["lifetime_score"] == 100, (
        f"a clean record must read lifetime_score 100, got {score['lifetime_score']}"
    )
    assert score["complaint_points"] == 0, (
        f"a clean record must read complaint_points 0, got {score['complaint_points']}"
    )
    assert score["recent_points"] == 0, (
        f"a clean record must read recent_points 0, got {score['recent_points']}"
    )
    assert score["older_points"] == 0, (
        f"a clean record must read older_points 0, got {score['older_points']}"
    )


def test_quality_score_read_splits_a_fresh_letter_into_recent_points_only(api):
    """PRD §3.2: "Each action contributes `points`, and points accrue by sanction type: a
    letter of instruction is worth 5 points, probation 10 points, a suspension 12 points, and
    a revocation 20 points."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the recent-points figure,
    floored at 0 so it never reports a negative number."
    PRD §3.2: "The separate field `complaint_points` is the plain, unweighted sum of `points`
    over the same `IN_EFFECT` and `EXPIRED` rows, with no decay and no floor."

    Design: Corner/Endpoints/quality_score_computed_read_exposes_both_variants_and_the_point_split
    """
    config = fixtures.setup_program_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter_id = bundle["interpreter"]["id"]

    fixtures.setup_sanction(
        interpreter_id,
        "LETTER",
        severity="MINOR",
        category="PROFESSIONALISM",
        narrative="Interpreter argued with counsel in front of the jury.",
    )

    score = fixtures.read_quality_score(interpreter_id)
    assert_quality_score_read(score)
    assert score["interpreter_id"] == interpreter_id, (
        f"the read must name the sanctioned interpreter, got {score['interpreter_id']!r}"
    )
    assert score["complaint_points"] == 5, (
        f"a LETTER is worth 5 unweighted points, got {score['complaint_points']}"
    )
    assert score["recent_points"] == 5, (
        f"an action dated on the current clock date is recent, got "
        f"{score['recent_points']}"
    )
    assert score["older_points"] == 0, (
        f"nothing in this history predates the 365-day cutoff, got "
        f"{score['older_points']}"
    )
    assert score["rolling_12_month_score"] == 80, (
        f"expected 100 less four times 5 recent points, got "
        f"{score['rolling_12_month_score']}"
    )
    assert score["lifetime_score"] == 80, (
        f"a history entirely inside the last year scores identically on both variants, got "
        f"{score['lifetime_score']}"
    )

    interpreter = fixtures.read_interpreter(interpreter_id)
    assert interpreter["complaint_points"] == 5, (
        f"the roster row must agree with the computed read, got "
        f"{interpreter['complaint_points']}"
    )
    assert interpreter["rolling_12_month_score"] == 80, (
        f"the roster row must agree with the computed read, got "
        f"{interpreter['rolling_12_month_score']}"
    )
    assert interpreter["lifetime_score"] == 80, (
        f"the roster row must agree with the computed read, got "
        f"{interpreter['lifetime_score']}"
    )


# ---------------------------------------------------------------------------
# The ranked eligible-interpreter pool
# ---------------------------------------------------------------------------
def _ranking_pool():
    """Three eligible interpreters enrolled in an order the ranking must override."""
    config = fixtures.setup_program_config()
    language_id = config["language"]["id"]

    out_of_county_certified = fixtures.setup_active_interpreter(
        language_id,
        target_tier="CERTIFIED",
        interpreter_overrides={
            "full_name": "Alba Ruiz",
            "email": "alba.ruiz@courts.example.gov",
            "home_county_code": "RUR",
        },
    )
    in_county_registered = fixtures.setup_active_interpreter(
        language_id,
        target_tier="REGISTERED",
        interpreter_overrides={
            "full_name": "Bruno Salas",
            "email": "bruno.salas@courts.example.gov",
            "home_county_code": "CAS",
        },
    )
    in_county_certified = fixtures.setup_active_interpreter(
        language_id,
        target_tier="CERTIFIED",
        interpreter_overrides={
            "full_name": "Carla Tovar",
            "email": "carla.tovar@courts.example.gov",
            "home_county_code": "CAS",
        },
    )
    uncredentialed = fixtures.enrol_interpreter(
        full_name="Dora Vela",
        email="dora.vela@courts.example.gov",
        home_county_code="CAS",
    )
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"], language_id,
        case_number="CR-2026-2101", hearing_type="PLEA", in_custody=True,
        scheduled_start="2026-09-15T09:00:00.000Z",
        scheduled_end="2026-09-15T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    return {
        "config": config,
        "hearing": hearing,
        "out_of_county_certified": out_of_county_certified["interpreter"],
        "in_county_registered": in_county_registered["interpreter"],
        "in_county_certified": in_county_certified["interpreter"],
        "uncredentialed": uncredentialed,
    }


def test_eligible_pool_ranks_tier_first_then_county_regardless_of_enrolment_order(api):
    """PRD §3.6: "Survivors are ordered by a four-part key applied in sequence: highest tier
    rank of their best active credential in the hearing's language first; then interpreters
    whose `home_county_code` equals the hosting courthouse's `county_code` ahead of those whose
    does not; then higher `rolling_12_month_score` ahead of lower; and finally, as the last
    tie-break, earlier interpreter `created_at` ahead of later."
    PRD §3.6: "The comparison is on tier rank — `MASTER` 3, `CERTIFIED` 2, `REGISTERED` 1,
    `PROVISIONAL` 0 — and the interpreter's best active credential in the hearing's language
    must rank at or above the required tier's rank."

    Design: Corner/Endpoints/eligible_interpreter_ranking_puts_tier_ahead_of_county_and_ignores_creation_order
    """
    pool = _ranking_pool()

    rows = fixtures.eligible_interpreters(pool["hearing"]["id"])
    ranked_ids = [row["id"] for row in rows]
    assert ranked_ids == [
        pool["in_county_certified"]["id"],
        pool["out_of_county_certified"]["id"],
        pool["in_county_registered"]["id"],
    ], (
        "the pool must rank the in-county CERTIFIED interpreter first, the out-of-county "
        "CERTIFIED interpreter second and the in-county REGISTERED interpreter last, got "
        f"{ranked_ids}"
    )
    assert ranked_ids[0] != pool["out_of_county_certified"]["id"], (
        "tier ties must be broken by county match, not by which interpreter enrolled first"
    )
    assert ranked_ids.index(pool["out_of_county_certified"]["id"]) < ranked_ids.index(
        pool["in_county_registered"]["id"]
    ), (
        "a higher tier rank outranks a county match, so the out-of-county CERTIFIED "
        "interpreter must precede the in-county REGISTERED one"
    )


def test_eligible_pool_excludes_an_interpreter_with_no_credential_at_all(
    api, scheduling_coordinator_headers
):
    """PRD §3.6: "The interpreter's `roster_status` must be `ACTIVE`, so `APPLICANT`,
    `CANDIDATE`, `SUSPENDED`, `INACTIVE` and `REVOKED` interpreters never appear at all."
    PRD §3.6: "They must hold a credential in the hearing's `language_id` whose `status` is
    `ACTIVE` and whose tier rank reaches the required minimum tier derived above."
    PRD §3.5: "Add the type weight, the custody bonus, the rarity bonus and the urgency term,
    then cap the sum at 100; the result is `priority_score`."

    Design: Corner/Endpoints/eligible_interpreter_ranking_puts_tier_ahead_of_county_and_ignores_creation_order
    """
    pool = _ranking_pool()
    hearing = fixtures.read_hearing(pool["hearing"]["id"])
    assert hearing["priority_score"] == 55, (
        f"a custodial plea 45 days out scores 30 + 25, got {hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "B", (
        f"a priority_score of exactly 55 is class B, got {hearing['priority_class']!r}"
    )

    rows, meta = validate_paginated(
        api.list_eligible_interpreters(pool["hearing"]["id"], scheduling_coordinator_headers)
    )
    assert meta["total_count"] == 3, (
        f"only the three credentialed, ethics-complete interpreters qualify, got "
        f"{meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"three rows on the default page leaves nothing beyond it, got {meta['has_more']!r}"
    )
    returned_ids = [row["id"] for row in rows]
    assert pool["uncredentialed"]["id"] not in returned_ids, (
        "an APPLICANT holding no credential must never appear in the pool"
    )
    assert pool["uncredentialed"]["roster_status"] == "APPLICANT", (
        f"the excluded interpreter must still be an APPLICANT, got "
        f"{pool['uncredentialed']['roster_status']!r}"
    )


# ---------------------------------------------------------------------------
# Credential advancement: one endpoint, one branch per target tier
# ---------------------------------------------------------------------------
def test_advance_sends_a_certified_target_to_the_oral_stage(api):
    """PRD §3.3: "From `PENDING_WRITTEN` the credential moves to `PENDING_ORAL` when the
    target tier is `MASTER` or `CERTIFIED`, the language's `oral_exam_available` is true, and
    `written_best_score` has reached the written floor for that target tier — 90 for `MASTER`,
    80 for `CERTIFIED`."
    PRD §3.3: "Each of these three advancements increments the credential's `version` by 1 and
    changes nothing else."

    Design: Corner/Endpoints/credential_advance_branches_on_target_tier_and_refuses_a_fourth_call
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language(
        code="spa", name="Spanish", tier_class="DESIGNATED", oral_exam_available=True
    )
    interpreter = fixtures.enrol_interpreter()
    interpreter = fixtures.complete_ethics_training(interpreter["id"])
    credential = fixtures.open_credential(
        interpreter["id"], language["id"], target_tier="CERTIFIED"
    )
    assert credential["status"] == "PENDING_WRITTEN", (
        f"a new credential opens in PENDING_WRITTEN, got {credential['status']!r}"
    )
    fixtures.record_exam_attempt(credential["id"], "WRITTEN", 86, "2026-08-01")
    before = fixtures.read_credential(credential["id"])

    advanced = fixtures.advance_credential(credential["id"])
    assert_credential(advanced)
    assert advanced["status"] == "PENDING_ORAL", (
        f"a CERTIFIED target in an orally examinable language must advance to PENDING_ORAL, "
        f"got {advanced['status']!r}"
    )
    assert advanced["version"] == before["version"] + 1, (
        f"expected version {before['version'] + 1} after the advancement, got "
        f"{advanced['version']}"
    )
    assert advanced["tier"] is None, (
        f"tier stays null until activation, got {advanced['tier']!r}"
    )
    for field in ("issued_on", "expires_on", "grace_through"):
        assert advanced[field] is None, (
            f"{field} must still be null before activation, got {advanced[field]!r}"
        )
    assert advanced["written_best_score"] == 86, (
        f"the advancement must change nothing else, got written_best_score "
        f"{advanced['written_best_score']}"
    )
    assert advanced["oral_attempt_count"] == 0, (
        f"entering the oral stage records no attempt, got "
        f"{advanced['oral_attempt_count']}"
    )


def test_advance_sends_a_registered_target_past_the_oral_stage_and_then_issues_the_licence(api):
    """PRD §3.3: "From `PENDING_WRITTEN` the credential instead moves straight to
    `PENDING_ETHICS` when `written_best_score` has reached 80 and either the target tier is
    `REGISTERED`, for which the program administers no oral performance examination at all, or
    the language offers no oral instrument, so there is no oral stage to enter."
    PRD §3.3: "On success the credential's `status` becomes `ACTIVE` and `tier` is set to
    `target_tier`; `issued_on` records the logical-clock date of this first activation;
    `expires_on` is set 730 days — two full years — after that date for a `MASTER`,
    `CERTIFIED`, or `REGISTERED` credential, and 365 days after it for a `PROVISIONAL` one,
    whose shorter cycle reflects that it rests on no examination; and `grace_through` is set 90
    days after `expires_on`."
    PRD §3.3: "The activation then cascades: the language's `active_credentialed_count` is
    recomputed, the holder's `credential_tier` and `credentialed_language_ids` are recomputed,
    and the holder's `roster_status` bubbles up from `CANDIDATE` to `ACTIVE` if this is their
    first active credential or from `INACTIVE` to `ACTIVE` if they had fallen off the roster."

    Design: Corner/Endpoints/credential_advance_branches_on_target_tier_and_refuses_a_fourth_call
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language(
        code="kor", name="Korean", tier_class="NON_DESIGNATED", oral_exam_available=True
    )
    interpreter = fixtures.enrol_interpreter()
    interpreter = fixtures.complete_ethics_training(interpreter["id"])
    credential = fixtures.open_credential(
        interpreter["id"], language["id"], target_tier="REGISTERED"
    )
    fixtures.record_exam_attempt(credential["id"], "WRITTEN", 82, "2026-08-01")

    to_ethics = fixtures.advance_credential(credential["id"])
    assert to_ethics["status"] == "PENDING_ETHICS", (
        f"a REGISTERED target bypasses the oral stage entirely, got {to_ethics['status']!r}"
    )
    assert to_ethics["oral_best_score"] is None, (
        f"no oral attempt was ever sat, got {to_ethics['oral_best_score']!r}"
    )

    active = fixtures.advance_credential(credential["id"])
    assert_credential(active)
    assert active["status"] == "ACTIVE", (
        f"the final advancement must issue the licence, got {active['status']!r}"
    )
    assert active["tier"] == "REGISTERED", (
        f"tier must mirror target_tier on activation, got {active['tier']!r}"
    )
    assert active["issued_on"] == "2026-08-01", (
        f"issued_on must record the logical-clock date, got {active['issued_on']!r}"
    )
    assert active["expires_on"] == "2028-07-31", (
        f"expected expires_on 730 days after issue, got {active['expires_on']!r}"
    )
    assert active["grace_through"] == "2028-10-29", (
        f"expected grace_through 90 days after expiry, got {active['grace_through']!r}"
    )
    assert active["version"] == to_ethics["version"] + 1, (
        f"expected version {to_ethics['version'] + 1} after activation, got "
        f"{active['version']}"
    )

    holder = fixtures.read_interpreter(interpreter["id"])
    assert holder["roster_status"] == "ACTIVE", (
        f"the first activation must bubble the holder up to ACTIVE, got "
        f"{holder['roster_status']!r}"
    )
    assert holder["credential_tier"] == "REGISTERED", (
        f"credential_tier must be recomputed to REGISTERED, got "
        f"{holder['credential_tier']!r}"
    )
    assert holder["credentialed_language_ids"] == [language["id"]], (
        f"credentialed_language_ids must list the newly active language, got "
        f"{holder['credentialed_language_ids']}"
    )
    assert fixtures.read_language(language["id"])["active_credentialed_count"] == 1, (
        "the language's active_credentialed_count must be recomputed to 1"
    )


def test_advancing_an_already_active_credential_is_refused(
    api, credentialing_officer_headers
):
    """PRD §3.3: "An advancement request whose current stage requirement is unmet, or which
    matches none of the branches above, is refused with `ERR_INVALID_CREDENTIAL_STATE`."
    PRD §2.12: "Credential state admits the requested transition — otherwise
    `ERR_INVALID_CREDENTIAL_STATE` (409)."

    Design: Corner/Endpoints/credential_advance_branches_on_target_tier_and_refuses_a_fourth_call
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    bundle = fixtures.setup_active_interpreter(config["language"]["id"], target_tier="CERTIFIED")
    credential = fixtures.read_credential(bundle["credential"]["id"])
    assert credential["status"] == "ACTIVE", (
        f"the three advancements must have left the credential ACTIVE, got "
        f"{credential['status']!r}"
    )

    validate_error(
        api.advance_credential(credential["id"], credentialing_officer_headers),
        ApiErrorId.ERR_INVALID_CREDENTIAL_STATE,
    )

    unchanged = fixtures.read_credential(credential["id"])
    assert unchanged["status"] == "ACTIVE", (
        f"the refused fourth advancement must leave the credential ACTIVE, got "
        f"{unchanged['status']!r}"
    )
    assert unchanged["version"] == credential["version"], (
        f"the refused fourth advancement must not bump the version, expected "
        f"{credential['version']}, got {unchanged['version']}"
    )
    assert unchanged["tier"] == "CERTIFIED", (
        f"the refused advancement must leave tier intact, got {unchanged['tier']!r}"
    )
