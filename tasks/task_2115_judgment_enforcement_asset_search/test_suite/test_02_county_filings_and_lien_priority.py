"""Perfecting the lien: county recording, the re-filing cycle and priority rank."""

from test_helpers import (
    ApiErrorId,
    assert_county_filing,
    create_county_filing_payload,
    create_creditor,
    create_debtor,
    create_judgment,
    create_verified_finding,
    draft_enforcement_action,
    make_case_manager_headers,
    make_enforcement_officer_headers,
    read_filing,
    read_judgment,
    record_county_filing,
    setup_judgment,
    submit_county_filing,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
EO = make_enforcement_officer_headers("eo-1")


# ==========================================================================
# The re-filing cycle: SUBMITTED -> REJECTED -> SUBMITTED -> RECORDED
# ==========================================================================
def test_rejected_filing_returns_to_submitted_and_accumulates_rejections(api):
    """PRD §3.2: "An `outcome` of `REJECTED` moves the filing `SUBMITTED →
    REJECTED`, requires a `rejection_reason` in the payload, increments
    `rejection_count` by one, and stores the reason on the row; crucially it
    leaves the judgment's `costs_balance_cents` untouched, because a rejected
    instrument was never recorded and its fee is not taxable."
    PRD §3.2: "A rejected filing is not dead — correcting the defect and
    submitting again moves it `REJECTED → SUBMITTED` (the judgment must still be
    `ACTIVE`) and re-stamps `submitted_on`, and a filing may bounce between those
    two states any number of times, with `rejection_count` accumulating each
    rebuff."

    Design: Difficulty/non_linear_state_machine/county_filing_submitted_rejected_submitted_refiling_cycle
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0304", interest_rate_bps=0, filing_costs_cents=45_000
    )
    filing = submit_county_filing(ctx["judgment"]["id"], fee_cents=3_500)

    first_rejection = validate_success(
        api.adjudicate_county_filing(
            filing["id"],
            {"outcome": "REJECTED", "rejection_reason": "missing apostille"},
            CM,
        )
    )
    assert first_rejection["status"] == "REJECTED"
    assert first_rejection["rejection_count"] == 1

    resubmitted = validate_success(api.submit_county_filing(filing["id"], CM))
    assert resubmitted["status"] == "SUBMITTED"

    second_rejection = validate_success(
        api.adjudicate_county_filing(
            filing["id"],
            {"outcome": "REJECTED", "rejection_reason": "wrong recording cover sheet"},
            CM,
        )
    )
    assert second_rejection["rejection_count"] == 2

    assert read_judgment(ctx["judgment"]["id"])["costs_balance_cents"] == 45_000, (
        "a rejected instrument's fee is never taxed to the judgment"
    )


def test_a_twice_rejected_filing_can_still_record_and_perfect_the_lien(api):
    """PRD §3.2: "Recording sets `lien_expires_on` to ten calendar years after
    `recorded_on`."
    PRD §3.2: "It then adds this filing's `fee_cents` to the judgment's
    `costs_balance_cents` and replays the judgment's balances to the current clock
    date, so the recorder's fee becomes recoverable taxed costs."
    PRD §3.2: "It increments the judgment's `perfected_county_count` by one, and
    when that count rises from zero to one the judgment's `enforcement_posture`
    moves `NONE → LIEN_PERFECTED` — the moment at which enforcement first becomes
    possible."
    PRD §3.2: "Each member is then assigned `priority_rank` by its position in
    that order, starting at 1; a filing that has never been recorded carries no
    `priority_rank` at all."

    Design: Difficulty/non_linear_state_machine/county_filing_submitted_rejected_submitted_refiling_cycle
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0305", interest_rate_bps=0, filing_costs_cents=45_000
    )
    filing = submit_county_filing(ctx["judgment"]["id"], fee_cents=3_500)

    for reason in ("missing apostille", "wrong recording cover sheet"):
        validate_success(
            api.adjudicate_county_filing(
                filing["id"], {"outcome": "REJECTED", "rejection_reason": reason}, CM
            )
        )
        validate_success(api.submit_county_filing(filing["id"], CM))

    recorded = validate_success(
        api.adjudicate_county_filing(
            filing["id"], {"outcome": "RECORDED", "recorded_on": "2026-08-01"}, CM
        )
    )
    assert_county_filing(recorded)
    assert recorded["status"] == "RECORDED"
    assert recorded["priority_rank"] == 1
    assert recorded["lien_expires_on"] == "2036-08-01"
    assert recorded["rejection_count"] == 2

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["enforcement_posture"] == "LIEN_PERFECTED"
    assert judgment["costs_balance_cents"] == 48_500


# ==========================================================================
# The writ needs a filing recorded in the debtor's own state
# ==========================================================================
def test_out_of_state_recording_leaves_the_posture_unperfected(api):
    """PRD §3.2: "The judgment must be `ACTIVE`, and for the lien to perfect the
    filing's `state_code` must equal the `state_code` of the debtor reached
    through the judgment's `debtor_id`."
    PRD §3.5: "The judgment's `enforcement_posture` must be `LIEN_PERFECTED` or
    `ENFORCING`; a posture of `NONE` means no county filing has been recorded in
    the debtor's state, which is `ERR_NO_PERFECTED_LIEN`, and a posture of
    `STAYED` is `ERR_ENFORCEMENT_STAYED`."

    Design: Difficulty/cross_entity_state_dependency/writ_requires_recorded_filing_in_the_debtors_own_state
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0701", debtor_overrides={"state_code": "CA"},
        state_code="CA", filing_costs_cents=0,
    )
    nevada_filing = record_county_filing(
        ctx["judgment"]["id"], county_code="NV-CLARK", state_code="NV", fee_cents=0
    )
    assert nevada_filing["status"] == "RECORDED"
    assert read_judgment(ctx["judgment"]["id"])["enforcement_posture"] == "NONE"

    finding = create_verified_finding(
        ctx["judgment"]["id"], estimated_value_cents=900_000
    )
    action = draft_enforcement_action(
        ctx["judgment"]["id"], finding["id"], "BANK_LEVY"
    )

    validate_error(
        api.request_writ(action["id"], EO),
        ApiErrorId.ERR_NO_PERFECTED_LIEN.value,
        409,
    )


def test_recording_in_the_debtors_state_unlocks_the_writ(api):
    """PRD §3.2: "It increments the judgment's `perfected_county_count` by one,
    and when that count rises from zero to one the judgment's
    `enforcement_posture` moves `NONE → LIEN_PERFECTED` — the moment at which
    enforcement first becomes possible."
    PRD §3.5: "An `EnforcementOfficer` then requests the writ, moving the action
    `DRAFT → WRIT_REQUESTED`."

    Design: Difficulty/cross_entity_state_dependency/writ_requires_recorded_filing_in_the_debtors_own_state
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0702", debtor_overrides={"state_code": "CA"},
        state_code="CA", filing_costs_cents=0,
    )
    record_county_filing(
        ctx["judgment"]["id"], county_code="NV-CLARK", state_code="NV", fee_cents=0
    )
    finding = create_verified_finding(
        ctx["judgment"]["id"], estimated_value_cents=900_000
    )
    action = draft_enforcement_action(
        ctx["judgment"]["id"], finding["id"], "BANK_LEVY"
    )
    validate_error(
        api.request_writ(action["id"], EO), ApiErrorId.ERR_NO_PERFECTED_LIEN.value, 409
    )

    record_county_filing(
        ctx["judgment"]["id"], county_code="CA-LOS-ANGELES", state_code="CA", fee_cents=0
    )
    assert read_judgment(ctx["judgment"]["id"])["enforcement_posture"] == "LIEN_PERFECTED"

    granted = validate_success(api.request_writ(action["id"], EO))
    assert granted["status"] == "WRIT_REQUESTED"


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_submitting_a_draft_filing_stamps_the_clock_date(api):
    """PRD §3.2: "Submission moves the filing `DRAFT → SUBMITTED` and stamps
    `submitted_on` with the current clock date; the judgment must still be
    `ACTIVE`, and the same no-live-duplicate condition holds at submission as at
    drafting."
    PRD §3.2: "Each member is then assigned `priority_rank` by its position in
    that order, starting at 1; a filing that has never been recorded carries no
    `priority_rank` at all."

    Design: Corner/state_machines/submit_county_filing_from_draft_moves_to_submitted
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    filing = validate_success(
        api.create_county_filing(
            create_county_filing_payload(ctx["judgment"]["id"], fee_cents=3_500), CM
        ),
        201,
    )
    assert filing["status"] == "DRAFT"

    submitted = validate_success(api.submit_county_filing(filing["id"], CM))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_on"] == "2026-08-01"
    assert submitted.get("priority_rank") is None

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["enforcement_posture"] == "NONE"
    assert judgment["costs_balance_cents"] == 0


def test_recording_without_a_recorded_on_date_is_rejected(api):
    """PRD §3.2: "The payload must supply `recorded_on`, the recorder's acceptance
    date, and that date must fall on or after `submitted_on` and on or before the
    current clock date; a date outside that span is an `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/adjudicate_recorded_without_recorded_on_returns_invalid_request
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    filing = submit_county_filing(ctx["judgment"]["id"], fee_cents=3_500)

    validate_error(
        api.adjudicate_county_filing(filing["id"], {"outcome": "RECORDED"}, CM),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    assert read_filing(filing["id"])["status"] == "SUBMITTED"
    assert read_judgment(ctx["judgment"]["id"])["costs_balance_cents"] == 0


def test_recording_taxes_the_recorder_fee_onto_the_judgment(api):
    """PRD §3.2: "It then adds this filing's `fee_cents` to the judgment's
    `costs_balance_cents` and replays the judgment's balances to the current clock
    date, so the recorder's fee becomes recoverable taxed costs."
    PRD §3.2: "Recording sets `lien_expires_on` to ten calendar years after
    `recorded_on`."

    Design: Corner/state_machines/recording_a_county_filing_syncs_the_judgment_costs_ledger
    """
    ctx = setup_judgment(
        original_principal_cents=100_000, interest_rate_bps=0, filing_costs_cents=0
    )
    assert ctx["judgment"]["costs_balance_cents"] == 0
    assert ctx["judgment"]["total_payoff_cents"] == 100_000

    filing = submit_county_filing(ctx["judgment"]["id"], fee_cents=3_500)
    recorded = validate_success(
        api.adjudicate_county_filing(
            filing["id"], {"outcome": "RECORDED", "recorded_on": "2026-08-01"}, CM
        )
    )
    assert recorded["priority_rank"] == 1
    assert recorded["lien_expires_on"] == "2036-08-01"

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["costs_balance_cents"] == 3_500
    assert judgment["total_payoff_cents"] == 103_500
    assert judgment["perfected_county_count"] == 1


def test_recording_renumbers_the_whole_county_cohort(api):
    """PRD §3.2: "The cohort is every county filing in the system — across all
    judgments, not merely this creditor's — whose `county_code` and `state_code`
    match this filing's and whose status is exactly `RECORDED` immediately after
    this recording, including the filing just recorded."
    PRD §3.2: "That cohort is sorted by `recorded_on` ascending and, for filings
    sharing a recording date, by `created_at` ascending; identifiers are never
    used as a tie-break."
    PRD §3.2: "Because the whole cohort is renumbered, a filing that was created
    later but recorded on the same day as an existing senior filing can take the
    senior position and demote its peer within the same request, whenever creation
    order and recording order disagree."

    Design: Corner/calculations/lien_priority_cohort_renumbers_by_created_at_when_recording_order_reverses
    """
    creditor = create_creditor()
    debtor = create_debtor()
    judgment_one = create_judgment(
        creditor["id"], debtor["id"], interest_rate_bps=0, filing_costs_cents=0
    )
    judgment_two = create_judgment(
        creditor["id"], debtor["id"], interest_rate_bps=0, filing_costs_cents=0
    )

    first_created = validate_success(
        api.create_county_filing(
            create_county_filing_payload(judgment_one["id"], fee_cents=0), CM
        ),
        201,
    )
    second_created = validate_success(
        api.create_county_filing(
            create_county_filing_payload(judgment_two["id"], fee_cents=0), CM
        ),
        201,
    )
    validate_success(api.submit_county_filing(first_created["id"], CM))
    validate_success(api.submit_county_filing(second_created["id"], CM))

    later_recorded_first = validate_success(
        api.adjudicate_county_filing(
            second_created["id"], {"outcome": "RECORDED", "recorded_on": "2026-08-01"},
            CM,
        )
    )
    assert later_recorded_first["priority_rank"] == 1

    earlier_created = validate_success(
        api.adjudicate_county_filing(
            first_created["id"], {"outcome": "RECORDED", "recorded_on": "2026-08-01"},
            CM,
        )
    )
    assert earlier_created["priority_rank"] == 1, (
        "the earlier-created filing takes the senior position on a tied recording date"
    )
    assert read_filing(second_created["id"])["priority_rank"] == 2, (
        "its peer is demoted within the same request"
    )


def test_a_second_live_filing_of_the_same_instrument_is_refused(api):
    """PRD §3.2: "The firm may not carry two live filings of the same instrument
    in the same county for the same judgment: if another filing already shares
    this filing's `judgment_id`, `county_code` and `filing_type` while sitting in
    `DRAFT`, `SUBMITTED` or `RECORDED`, the draft is refused with
    `ERR_DUPLICATE_COUNTY_FILING`."

    Design: Corner/validations/duplicate_live_county_filing_rejected_for_same_judgment_county_and_type
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    validate_success(
        api.create_county_filing(
            create_county_filing_payload(ctx["judgment"]["id"], fee_cents=3_500), CM
        ),
        201,
    )

    validate_error(
        api.create_county_filing(
            create_county_filing_payload(ctx["judgment"]["id"], fee_cents=3_500), CM
        ),
        ApiErrorId.ERR_DUPLICATE_COUNTY_FILING.value,
        409,
    )

    other_instrument = validate_success(
        api.create_county_filing(
            create_county_filing_payload(
                ctx["judgment"]["id"], filing_type="JUDGMENT_LIEN", fee_cents=4_000
            ),
            CM,
        ),
        201,
    )
    assert other_instrument["filing_type"] == "JUDGMENT_LIEN"

    _rows, meta = validate_paginated(
        api.list_county_filings(CM, {"judgment_id": ctx["judgment"]["id"]})
    )
    assert meta["total_count"] == 2


def test_the_recording_cascade_is_visible_without_an_intervening_call(api):
    """PRD §2.11: "Whenever a cascade touches a set of sibling rows — releasing
    every recorded filing on a satisfied judgment, suspending every served writ
    when a settlement activates, staling every skip-trace finding after a new
    trace — those rows are processed in `created_at` ascending order."
    PRD §3.2: "It increments the judgment's `perfected_county_count` by one, and
    when that count rises from zero to one the judgment's `enforcement_posture`
    moves `NONE → LIEN_PERFECTED` — the moment at which enforcement first becomes
    possible."

    Design: Corner/consistency_model/recording_cascade_is_visible_in_the_same_request_response
    """
    ctx = setup_judgment(
        original_principal_cents=100_000, interest_rate_bps=0, filing_costs_cents=0
    )
    filing = submit_county_filing(ctx["judgment"]["id"], fee_cents=3_500)

    recorded = validate_success(
        api.adjudicate_county_filing(
            filing["id"], {"outcome": "RECORDED", "recorded_on": "2026-08-01"}, CM
        )
    )
    assert recorded["status"] == "RECORDED"
    assert recorded["priority_rank"] == 1
    assert recorded["lien_expires_on"] == "2036-08-01"

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["costs_balance_cents"] == 3_500
    assert judgment["perfected_county_count"] == 1
    assert judgment["enforcement_posture"] == "LIEN_PERFECTED"
    assert judgment["total_payoff_cents"] == 103_500


def test_recording_advances_the_judgment_version_by_exactly_one(api):
    """PRD §2.4: "Every object also carries `created_at` and `updated_at`, both
    ISO 8601 UTC timestamps with three fractional digits, and a `version` that
    starts at 1 when the row is created and increments by exactly 1 on every
    mutation of that row."
    PRD §2.4: "A judgment's `version` advances when the judgment is created, when
    a county filing on it is recorded, when a writ against it is served, when a
    settlement offer on it is tendered or accepted, when an installment agreement
    on it defaults or is reinstated, when a payment is booked or reversed, when it
    is renewed, and whenever a cascade moves its `status` or its
    `enforcement_posture`."

    Design: Corner/cross_cutting_complexity_layers/judgment_version_increments_by_one_on_a_recording_mutation
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    filing = submit_county_filing(ctx["judgment"]["id"], fee_cents=0)

    version_before = read_judgment(ctx["judgment"]["id"])["version"]
    validate_success(
        api.adjudicate_county_filing(
            filing["id"], {"outcome": "RECORDED", "recorded_on": "2026-08-01"}, CM
        )
    )

    judgment_after = read_judgment(ctx["judgment"]["id"])
    assert judgment_after["version"] == version_before + 1
    assert judgment_after["enforcement_posture"] == "LIEN_PERFECTED"
