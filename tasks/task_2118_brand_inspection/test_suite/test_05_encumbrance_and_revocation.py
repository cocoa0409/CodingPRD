"""When a mark of record is encumbered, exonerated, condemned or contested."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_theft_investigation,
    add_order_in_field,
    close_field_work,
    close_investigation,
    decide_claim_payload,
    make_brand_recorder_headers,
    make_theft_investigator_headers,
    present_lot,
    read_application,
    read_inspector,
    read_investigation,
    read_lot,
    read_order,
    read_owner,
    read_registration,
    refer_investigation_payload,
    reopen_investigation,
    setup_contest_under_adjudication,
    setup_theft_cascade,
    TEST_USERS,
    validate_error,
    validate_success,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
INVESTIGATOR = TEST_USERS["theft_investigator_headers"]
SECOND_RECORDER = make_brand_recorder_headers("recorder-03")


# ─── The four-level theft cascade ─────────────────────────────────────────────

def test_mismatch_finding_opens_an_investigation_and_encumbers_the_mark(api):
    """PRD §3.7: "At the first level the lot itself is impounded on paper: its
    `lot_status` becomes `HELD` and its `disposition` becomes `THEFT_REFERRAL`."
    PRD §3.7: "At the second level a theft investigation comes into existence, opened at
    status `OPENED` with `outcome` `PENDING`, `reopen_count` 0, `referral_agency` and
    `closed_by_user_id` null, `animal_lot_id` naming the lot, `brand_registration_id`
    naming the mark the inspector read, `opened_at` stamped from the logical clock and
    `opened_by_user_id` stamped with the reporting inspector's `X-User-ID`; at the same
    moment the parent inspection order's `hold_flag` is raised to true."
    PRD §3.7: "At the third level the mark itself is encumbered: a record standing at
    `ACTIVE` or `GRACE` moves to `ENCUMBERED` and its `encumbrance_count` rises by one,
    that count being the number of investigations against the record whose status is
    `OPENED` or `REFERRED`."

    Design: Difficulty/transitive_cascade/brand_mismatch_finding_cascades_to_conflict_hold
    """
    scenario = setup_theft_cascade(head_count=25, with_pending_renewal=True)

    lot = read_lot(scenario["lot"]["id"])
    assert lot["lot_status"] == "HELD"
    assert lot["match_status"] == "MISMATCHED"
    assert lot["disposition"] == "THEFT_REFERRAL"

    investigation = read_investigation(scenario["investigation"]["id"])
    assert_theft_investigation(investigation)
    assert investigation["status"] == "OPENED"
    assert investigation["outcome"] == "PENDING"
    assert investigation["reopen_count"] == 0
    assert investigation["referral_agency"] is None
    assert investigation["closed_by_user_id"] is None
    assert investigation["brand_registration_id"] == scenario["registration"]["id"]
    assert investigation["opened_by_user_id"] == scenario["inspector"]["id"]

    assert read_order(scenario["order"]["id"])["hold_flag"] is True

    registration = read_registration(scenario["registration"]["id"])
    assert registration["status"] == "ENCUMBERED"
    assert registration["encumbrance_count"] == 1


def test_encumbrance_freezes_the_pending_renewal_filing(api):
    """PRD §3.7: "At the fourth level the encumbrance freezes paperwork already in
    motion: every brand filing whose `prior_registration_id` names the encumbered record
    and whose status is `SUBMITTED` or `UNDER_EXAMINATION` is moved to `CONFLICT_HOLD`,
    processed in `created_at` ascending order."
    PRD §3.7: "An owner who lodged a renewal last week and has done nothing wrong will
    find that renewal frozen because an inspector two districts away read their mark on
    somebody else's cattle — that freeze is intended, and it lifts only when the
    investigation closes."

    Design: Difficulty/transitive_cascade/brand_mismatch_finding_cascades_to_conflict_hold
    """
    scenario = setup_theft_cascade(head_count=25, with_pending_renewal=True)
    assert scenario["renewal"]["status"] == "SUBMITTED"

    frozen = read_application(scenario["renewal"]["id"])
    assert frozen["status"] == "CONFLICT_HOLD", (
        f"the pending renewal must be frozen, got {frozen['status']}"
    )
    assert frozen["prior_registration_id"] == scenario["registration"]["id"]
    assert read_registration(scenario["registration"]["id"])["status"] == "ENCUMBERED"


def test_unfounded_close_releases_the_encumbrance_and_the_frozen_filing(api):
    """PRD §3.7: "Referring the case moves it `OPENED → REFERRED` and records the
    `referral_agency` the file was handed to."
    PRD §3.7: "Closing the case is available from either `OPENED` or `REFERRED`, moves
    it to `CLOSED`, records the investigator's `X-User-ID` as `closed_by_user_id`, and
    requires an `outcome` of either `SUBSTANTIATED` or `UNFOUNDED`."
    PRD §3.7: "An `UNFOUNDED` close exonerates the mark: once the decrement brings
    `encumbrance_count` to zero, the record moves `ENCUMBERED → ACTIVE` and every filing
    that was frozen against it is released from `CONFLICT_HOLD` to `UNDER_EXAMINATION`,
    processed in `created_at` ascending order."
    PRD §3.7: "Closing always decrements the encumbered record's `encumbrance_count` by
    one, and it always clears the parent order's `hold_flag` back to false once no
    `OPENED` or `REFERRED` investigation remains against any lot of that order — an
    order carrying two open investigations stays held until the second one closes."

    Design: Corner/state_machines/corner_close_investigation_unfounded_releases_encumbrance_and_hold
    """
    scenario = setup_theft_cascade(
        head_count=10, brand_symbol="UF", position_code="RIGHT_RIB",
        with_pending_renewal=True, owner_name="Unfounded Ranch",
    )
    assert scenario["investigation"]["status"] == "OPENED"

    referred = validate_success(
        api.refer_investigation(
            scenario["investigation"]["id"],
            refer_investigation_payload("Musselshell County Sheriff"),
            INVESTIGATOR,
        ),
        200,
    )
    assert referred["status"] == "REFERRED"
    assert referred["referral_agency"] == "Musselshell County Sheriff"

    closed = validate_success(
        api.close_investigation(
            scenario["investigation"]["id"],
            {"outcome": "UNFOUNDED"},
            make_theft_investigator_headers("inv-02"),
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["outcome"] == "UNFOUNDED"
    assert closed["closed_by_user_id"] == "inv-02"

    registration = read_registration(scenario["registration"]["id"])
    assert registration["status"] == "ACTIVE"
    assert registration["encumbrance_count"] == 0

    assert read_application(scenario["renewal"]["id"])["status"] == "UNDER_EXAMINATION"
    assert read_order(scenario["order"]["id"])["hold_flag"] is False

    lot = read_lot(scenario["lot"]["id"])
    assert lot["match_status"] == "MISMATCHED"
    assert lot["lot_status"] == "HELD"


def test_substantiated_close_condemns_the_mark_and_voids_the_lot_reading(api):
    """PRD §3.7: "A `SUBSTANTIATED` close condemns it instead: the record moves
    `ENCUMBERED → REVOKED`, and every lot read against that record that still stands at
    `lot_status` `PRESENTED` has its `match_status` moved to `UNVERIFIABLE`, processed in
    `created_at` ascending order."
    PRD §3.7: "This path stops at the lots; unlike a sustained conflict contest (§3.4), a
    substantiated theft close does not pull scheduled orders back to `REQUESTED`."

    Design: Corner/state_machines/corner_substantiated_close_revokes_registration_and_marks_lots
    """
    scenario = setup_theft_cascade(
        head_count=10, brand_symbol="SB", position_code="LEFT_SHOULDER",
        owner_name="Substantiated Ranch",
    )
    validate_success(
        api.refer_investigation(
            scenario["investigation"]["id"],
            refer_investigation_payload("MT Department of Livestock"),
            INVESTIGATOR,
        ),
        200,
    )
    sibling_inspector, sibling_order = add_order_in_field(scenario)
    sibling_lot = present_lot(
        sibling_order["id"], sibling_inspector["id"], 6,
        brand_registration_id=scenario["registration"]["id"],
    )
    assert sibling_lot["lot_status"] == "PRESENTED"

    closed = validate_success(
        api.close_investigation(
            scenario["investigation"]["id"], {"outcome": "SUBSTANTIATED"}, INVESTIGATOR
        ),
        200,
    )

    assert closed["status"] == "CLOSED"
    assert closed["outcome"] == "SUBSTANTIATED"

    registration = read_registration(scenario["registration"]["id"])
    assert registration["status"] == "REVOKED"
    assert registration["encumbrance_count"] == 0

    assert read_lot(sibling_lot["id"])["match_status"] == "UNVERIFIABLE"
    assert read_lot(scenario["lot"]["id"])["match_status"] == "MISMATCHED"
    assert read_order(sibling_order["id"])["schedule_status"] == "IN_FIELD", (
        "a substantiated theft close stops at the lots and leaves field work in place"
    )
    assert read_order(scenario["order"]["id"])["hold_flag"] is False


def test_second_reopen_of_a_closed_investigation_is_refused(api):
    """PRD §3.7: "A closed case may be reopened, but only once."
    PRD §3.7: "A successful reopen advances `reopen_count` by one, returns `outcome` to
    `PENDING`, raises `encumbrance_count` by one and moves an `ACTIVE` or `GRACE` record
    back to `ENCUMBERED`, and re-raises the parent order's `hold_flag` to true."
    PRD §3.7: "After that single reopen, `CLOSED` is effectively terminal: a second
    reopen attempt is refused with `ERR_INVESTIGATION_INVALID_STATE`, which is also the
    refusal for referring a case that is not `OPENED` or closing one that is already
    `CLOSED`."

    Design: Corner/state_machines/corner_theft_investigation_second_reopen_rejected
    """
    scenario = setup_theft_cascade(
        head_count=10, brand_symbol="RO", position_code="LEFT_HIP",
        owner_name="Reopen Ranch",
    )
    close_investigation(scenario["investigation"]["id"], "UNFOUNDED")

    reopened = reopen_investigation(scenario["investigation"]["id"])
    assert reopened["reopen_count"] == 1
    assert reopened["status"] == "OPENED"
    assert reopened["outcome"] == "PENDING"

    close_investigation(scenario["investigation"]["id"], "UNFOUNDED")

    response = api.reopen_investigation(scenario["investigation"]["id"], INVESTIGATOR)

    validate_error(response, ApiErrorId.ERR_INVESTIGATION_INVALID_STATE.value, 409)

    investigation = read_investigation(scenario["investigation"]["id"])
    assert investigation["status"] == "CLOSED"
    assert investigation["reopen_count"] == 1

    registration = read_registration(scenario["registration"]["id"])
    assert registration["status"] == "ACTIVE"
    assert registration["encumbrance_count"] == 0
    assert read_order(scenario["order"]["id"])["hold_flag"] is False


def test_waive_is_refused_under_a_theft_hold_and_accepted_once_it_clears(api):
    """PRD §3.9: "A `FeeAdministrator` has two ways to take a fee off the books without
    money changing hands, and both are barred while the order is under a theft hold."
    PRD §3.9: "Waiving moves the fee dimension from `ASSESSED` or `DELINQUENT` to
    `WAIVED`."
    PRD §3.9: "Either operation attempted against an order whose `hold_flag` is true is
    refused with `ERR_ORDER_HOLD_ACTIVE`; either attempted against a fee dimension that
    is `UNASSESSED`, `REMITTED` or `WAIVED` is refused with `ERR_FEE_INVALID_STATE`."

    Design: Corner/validations/corner_waive_fee_blocked_by_active_theft_hold
    """
    scenario = setup_theft_cascade(
        head_count=40, brand_symbol="HD", position_code="LEFT_HIP",
        owner_name="Hold Flag Ranch",
    )
    completed = close_field_work(
        scenario["order"]["id"], scenario["inspector"]["id"]
    )
    assert completed["assessed_fee_cents"] == 7450
    assert completed["hold_flag"] is True

    refused = api.waive_fee(
        scenario["order"]["id"], TEST_USERS["fee_administrator_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_ORDER_HOLD_ACTIVE.value, 409)

    close_investigation(scenario["investigation"]["id"], "UNFOUNDED")

    waived = validate_success(
        api.waive_fee(scenario["order"]["id"], TEST_USERS["fee_administrator_headers"]),
        200,
    )
    assert waived["hold_flag"] is False
    assert waived["fee_status"] == "WAIVED"
    assert read_owner(scenario["owner"]["id"])["projected_arrears_cents"] == 0


# ─── Contesting a recorded mark ───────────────────────────────────────────────

def test_sustaining_a_contest_revokes_the_mark_and_voids_the_lot_reading(api):
    """PRD §3.4: "When it proceeds, the first effect is that the respondent record moves
    to `REVOKED`."
    PRD §3.4: "The second effect follows from the first: every lot of head that was read
    against that record and still stands at lot status `PRESENTED` has its ownership
    finding moved to `UNVERIFIABLE`, processed in `created_at` ascending order — the
    inspector's reading is no longer evidence of anything, because the mark it referenced
    is no longer a mark of record."

    Design: Difficulty/transitive_cascade/sustained_conflict_claim_cascades_to_order_unschedule
    """
    scenario = setup_contest_under_adjudication()
    assert scenario["claim"]["status"] == "UNDER_ADJUDICATION"

    decided = validate_success(
        api.decide_claim(
            scenario["claim"]["id"],
            decide_claim_payload(
                "SUSTAIN", decision_note="prior use established by 1998 tally books"
            ),
            SECOND_RECORDER,
        ),
        200,
    )

    assert decided["status"] == "SUSTAINED"
    assert read_registration(scenario["registration"]["id"])["status"] == "REVOKED"
    assert read_lot(scenario["lot"]["id"])["match_status"] == "UNVERIFIABLE"


def test_sustaining_a_contest_pulls_the_field_order_back_to_requested(api):
    """PRD §3.4: "The third effect follows from the second: every inspection order that
    parents one of those lots and whose scheduling dimension reads `SCHEDULED` or
    `IN_FIELD` is pulled back to `REQUESTED`, its `inspector_id` cleared, its
    `scheduled_start_at` and `scheduled_end_at` cleared, and the released inspector's
    `version` incremented by one, again processed in `created_at` ascending order."
    PRD §3.4: "Field work already under way on a revoked mark is aborted and the order
    returns to the request queue to be re-assigned."

    Design: Difficulty/transitive_cascade/sustained_conflict_claim_cascades_to_order_unschedule
    """
    scenario = setup_contest_under_adjudication()
    before = read_inspector(scenario["inspector"]["id"])
    assert before["version"] == 2
    assert before["active_assignment_count"] == 1

    validate_success(
        api.decide_claim(
            scenario["claim"]["id"],
            decide_claim_payload(
                "SUSTAIN", decision_note="prior use established by 1998 tally books"
            ),
            SECOND_RECORDER,
        ),
        200,
    )

    order = read_order(scenario["order"]["id"])
    assert order["schedule_status"] == "REQUESTED"
    assert order["inspector_id"] is None
    assert order["scheduled_start_at"] is None
    assert order["scheduled_end_at"] is None

    after = read_inspector(scenario["inspector"]["id"])
    assert after["version"] == 3, f"the released officer advances one version, got {after['version']}"
    assert after["active_assignment_count"] == 0


def test_second_adjudication_of_the_same_contest_is_refused(api):
    """PRD §3.4: "Adjudication is a `BrandRecorder`'s work and proceeds in two steps,
    `FILED → UNDER_ADJUDICATION → SUSTAINED` or `FILED → UNDER_ADJUDICATION →
    DISMISSED`."
    PRD §3.4: "Taking the contest up moves it to `UNDER_ADJUDICATION` and increments its
    `version`; a contest taken up when it is not `FILED`, or decided when it is not
    `UNDER_ADJUDICATION`, is refused with `ERR_CLAIM_INVALID_STATE`."

    Design: Corner/state_machines/corner_duplicate_adjudicate_on_claim_rejected
    """
    scenario = setup_contest_under_adjudication(
        grounds="DECEPTIVE_SIMILARITY", brand_symbol="DS", position_code="RIGHT_HIP"
    )

    response = api.adjudicate_claim(scenario["claim"]["id"], SECOND_RECORDER)

    validate_error(response, ApiErrorId.ERR_CLAIM_INVALID_STATE.value, 409)

    claim = validate_success(
        api.get_conflict_claim(scenario["claim"]["id"], BOARD_ADMIN), 200
    )
    assert claim["status"] == "UNDER_ADJUDICATION"
    assert read_registration(scenario["registration"]["id"])["status"] == "ACTIVE"
