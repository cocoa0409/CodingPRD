"""The refusals that guard money already recorded: the ledger, the settlement sweep, the
royalty adjudication and the corporate pool.

Each of these routes has a neighbour it must not be confused with. Twenty-nine days past due is
not delinquency; a payment larger than the balance is not a credit; an accepted report is not a
disputed one; an unposted settlement has moved nothing to reverse; and a funded pool with nobody
enrolled has nowhere to send the money.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_royalty_report_payload,
    allocate_corporate_account_payload,
    api_client,
    create_agreement_payload,
    create_billing_event_payload,
    create_corporate_account,
    create_franchisee,
    create_member,
    create_usage_settlement,
    create_usage_settlement_payload,
    fund_corporate_account,
    inspect_club,
    make_club_manager_headers,
    place_in_collections_payload,
    post_dues,
    post_payment,
    post_payment_failure,
    post_usage_settlement,
    read_agreement,
    read_club,
    read_club_version,
    read_corporate_account,
    read_franchisee,
    read_guest_usage_event,
    read_inspection,
    read_member,
    read_royalty_report,
    read_usage_settlement,
    recall_allocation_payload,
    record_guest_usage,
    reverse_usage_settlement_payload,
    set_clock_date,
    setup_guest_usage_scenario,
    setup_single_club_franchise,
    sign_active_agreement,
    sign_agreement,
    submit_royalty_report,
    suspend_corporate_account,
    waive_remediation_payload,
)

BRAND = TEST_USERS["brand_administrator_headers"]
BILLING = TEST_USERS["billing_partner_headers"]
AUDITOR_ALT = TEST_USERS["compliance_auditor_alt_headers"]


def _a_membership_twenty_nine_days_past_its_due_date() -> dict:
    """A 9000-cent charge due 2026-09-05 against which only 100 cents ever arrived, read at a
    clock of 2026-10-04."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        "2026-08-01",
    )
    post_dues(agreement["id"], 9000, "2026-08-01", due_on="2026-09-05")
    post_payment(agreement["id"], 100, "2026-08-02")
    set_clock_date("2026-10-04")
    post_payment_failure(agreement["id"], "2026-10-04")
    scenario["agreement"] = read_agreement(agreement["id"])
    return scenario


def _place_in_collections(agreement_id: str):
    return api_client.place_in_collections(
        agreement_id,
        place_in_collections_payload(agency_reference="AGY-2026-0001"),
        BILLING,
    )


def test_collections_placement_from_past_due_is_the_wrong_source_state():
    """The account is genuinely in arrears and the billing partner is the right actor, but the
    transition begins at DELINQUENT and this account has not got there.

    PRD 3.4: "It moves the collections dimension `DELINQUENT → IN_COLLECTIONS`, and both of its
    preconditions are checked: an account not currently in `DELINQUENT` is refused with
    `ERR_INVALID_DUES_STATE`, and an account whose `delinquency_days` is below 60 — two months of
    unpaid dues — is refused with `ERR_COLLECTIONS_THRESHOLD_NOT_MET`."

    Design: Corner/errors/corner_placing_a_past_due_agreement_in_collections_is_rejected
    """
    scenario = _a_membership_twenty_nine_days_past_its_due_date()

    validate_error(
        _place_in_collections(scenario["agreement"]["id"]),
        ApiErrorId.ERR_INVALID_DUES_STATE.value,
        409,
    )
    after = read_agreement(scenario["agreement"]["id"])
    assert after["dues_status"] == "PAST_DUE"
    assert after["delinquency_days"] == 29


def test_twenty_nine_days_is_past_due_and_the_thirtieth_day_is_delinquency():
    """The refusal hangs on a single day of ageing, and the projection is exact at that boundary.

    PRD 3.4: "Otherwise, if `delinquency_days` is at least 30, `dues_status` becomes
    `DELINQUENT`. Otherwise, if `delinquency_days` is at least 1, it becomes `PAST_DUE`. Otherwise
    it becomes `CURRENT`. The boundary is exact and inclusive on the delinquency side: an age of
    29 days is `PAST_DUE`, and an age of 30 days is `DELINQUENT`."

    Design: Corner/errors/corner_placing_a_past_due_agreement_in_collections_is_rejected
    """
    scenario = _a_membership_twenty_nine_days_past_its_due_date()
    agreement_id = scenario["agreement"]["id"]

    assert scenario["agreement"]["outstanding_balance_cents"] == 8900
    assert scenario["agreement"]["dues_status"] == "PAST_DUE"
    set_clock_date("2026-10-05")
    post_payment_failure(agreement_id, "2026-10-05")
    aged = read_agreement(agreement_id)
    assert aged["delinquency_days"] == 30
    assert aged["dues_status"] == "DELINQUENT"


def test_once_delinquent_the_same_placement_fails_on_the_sixty_day_threshold_instead():
    """Reaching DELINQUENT unblocks the source state and immediately exposes the second
    precondition, which is a different refusal about a different fact.

    PRD 3.4: "an account whose `delinquency_days` is below 60 — two months of unpaid dues — is
    refused with `ERR_COLLECTIONS_THRESHOLD_NOT_MET`"

    Design: Corner/errors/corner_placing_a_past_due_agreement_in_collections_is_rejected
    """
    scenario = _a_membership_twenty_nine_days_past_its_due_date()
    agreement_id = scenario["agreement"]["id"]

    set_clock_date("2026-10-05")
    post_payment_failure(agreement_id, "2026-10-05")
    validate_error(
        _place_in_collections(agreement_id),
        ApiErrorId.ERR_COLLECTIONS_THRESHOLD_NOT_MET.value,
        409,
    )
    assert read_agreement(agreement_id)["dues_status"] == "DELINQUENT"


def _a_pending_membership_with_one_unpaid_charge() -> dict:
    """A signed but not yet live membership carrying a single 4500-cent charge."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["agreement"] = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        "2026-08-01",
    )
    scenario["charge"] = post_dues(
        scenario["agreement"]["id"], 4500, "2026-08-01", due_on="2026-09-05"
    )
    return scenario


def _pay(scenario: dict, amount_cents: int):
    return api_client.create_billing_event(
        create_billing_event_payload(
            scenario["agreement"]["id"], "PAYMENT_RECEIVED", amount_cents, "2026-08-02"
        ),
        BILLING,
    )


def test_a_payment_larger_than_the_balance_is_refused_rather_than_clamped():
    """Five thousand cents against a 4500-cent balance would drive the ledger credit-negative, so
    the entry is rejected outright and the membership never goes live.

    PRD 3.4: "A `PAYMENT_RECEIVED` or `WRITE_OFF` amount that exceeds the agreement's current
    outstanding balance, a `DUES_POSTED` entry that omits `due_on`, and any dues entry posted
    against an agreement whose `agreement_status` is `CANCELLED` are all refused with
    `ERR_INVALID_DUES_EVENT`."

    Design: Corner/errors/corner_payment_exceeding_the_outstanding_balance_is_rejected
    """
    scenario = _a_pending_membership_with_one_unpaid_charge()

    validate_error(_pay(scenario, 5000), ApiErrorId.ERR_INVALID_DUES_EVENT.value, 409)
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["outstanding_balance_cents"] == 4500
    assert agreement["dues_paid_cents"] == 0
    assert agreement["agreement_status"] == "PENDING"


def test_the_refused_payment_leaves_no_row_and_no_new_balance_snapshot():
    """The ledger is an append-only record of what actually happened, so the rejected entry is
    absent and the charge's own snapshot still reads 4500.

    PRD 3.4: "Every appended entry also stores `resulting_outstanding_balance_cents`, a snapshot
    of the agreement's outstanding balance immediately after that entry was folded into the
    projection, so the ledger can be replayed for audit."

    Design: Corner/errors/corner_payment_exceeding_the_outstanding_balance_is_rejected
    """
    scenario = _a_pending_membership_with_one_unpaid_charge()

    _pay(scenario, 5000)
    rows, meta = validate_paginated(
        api_client.list_agreement_billing_events(scenario["agreement"]["id"], BRAND)
    )
    assert meta["total_count"] == 1
    assert rows[0]["event_type"] == "DUES_POSTED"
    assert rows[0]["resulting_outstanding_balance_cents"] == 4500


def test_a_payment_of_exactly_the_balance_lands_and_activates_the_membership():
    """The refusal was about the amount alone: 4500 cents on the nose is accepted and does the
    activating work the oversized payment never got to do.

    PRD 3.4: "When a `PAYMENT_RECEIVED` entry with an `amount_cents` greater than 0 is the first
    such entry on the agreement, the contract dimension advances `PENDING → ACTIVE` in the same
    request: the home club's `active_agreement_count` increases by 1, `collections_watch` is
    recomputed from the new share, the owning franchisee's `compliance_score` is recomputed, and
    the agreement's and the club's `version` each increment."

    Design: Corner/errors/corner_payment_exceeding_the_outstanding_balance_is_rejected
    """
    scenario = _a_pending_membership_with_one_unpaid_charge()

    validate_error(_pay(scenario, 5000), ApiErrorId.ERR_INVALID_DUES_EVENT.value, 409)
    validate_success(_pay(scenario, 4500), expected_status=201)
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["agreement_status"] == "ACTIVE"
    assert agreement["dues_paid_cents"] == 4500
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 1


def _a_club_whose_inspection_closed_itself_at_ninety_one_points():
    """Nothing to remediate: 95 / 92 / 90 at a twelve-month worst equipment age scores 91."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    scenario["inspection"] = inspect_club(scenario["club"]["id"], "2026-07-15", 95, 92, 90, 12)
    return scenario


def _waive(scenario: dict):
    return api_client.waive_inspection_remediation(
        scenario["inspection"]["id"],
        waive_remediation_payload(reason="Nothing to waive."),
        AUDITOR_ALT,
    )


def test_there_is_no_remediation_to_forgive_on_a_passing_inspection():
    """The caller is a second, properly segregated auditor, so segregation of duties is satisfied
    and the only objection left is that the inspection passed.

    PRD 3.9: "An inspection that is not in `REMEDIATION_REQUIRED`, or whose `score` is at or above
    70 and therefore never needed remediation, is refused with `ERR_REMEDIATION_NOT_REQUIRED`."

    Design: Corner/errors/corner_waiving_remediation_on_a_passing_inspection_is_rejected
    """
    scenario = _a_club_whose_inspection_closed_itself_at_ninety_one_points()

    assert scenario["inspection"]["score"] == 91
    validate_error(_waive(scenario), ApiErrorId.ERR_REMEDIATION_NOT_REQUIRED.value, 409)
    inspection = read_inspection(scenario["inspection"]["id"])
    assert inspection["status"] == "CLOSED"
    assert inspection["waived_by_user_id"] is None


def test_the_refused_waiver_does_not_downgrade_the_club_to_watch():
    """A waiver would have moved the club to WATCH; because no waiver happened, the club keeps the
    compliant, open posture its passing score earned it.

    PRD 3.9: "The waiver sets the club's `equipment_compliance_state` to `WATCH` — leaving
    `last_inspection_score` untouched, because the failing score is a historical fact — and
    returns a `SUSPENDED` club to `OPEN`."

    Design: Corner/errors/corner_waiving_remediation_on_a_passing_inspection_is_rejected
    """
    scenario = _a_club_whose_inspection_closed_itself_at_ninety_one_points()

    _waive(scenario)
    club = read_club(scenario["club"]["id"])
    assert club["equipment_compliance_state"] == "COMPLIANT"
    assert club["status"] == "OPEN"
    assert read_inspection(scenario["inspection"]["id"])["waiver_reason"] is None


def _a_truthful_august_royalty_report_that_auto_accepted() -> dict:
    """One undiscounted membership, one honest head count, and therefore no dispute to settle."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        royalty_rate_bps=650,
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        due_on="2026-09-05",
    )
    set_clock_date("2026-09-05")
    scenario["report"] = submit_royalty_report(scenario["franchisee"]["id"], "2026-08", 1)
    return scenario


def _adjudicate(scenario: dict, adjusted_royalty_cents: int = 150):
    return api_client.adjudicate_royalty_report(
        scenario["report"]["id"],
        adjudicate_royalty_report_payload(
            adjusted_royalty_cents, note="Trying to discount an accepted report."
        ),
        BRAND,
    )


def test_an_accepted_royalty_report_cannot_be_re_priced():
    """Adjudication exists to settle a dispute, and this report never became one, so the brand has
    no figure to substitute.

    PRD 3.9: "Adjudicating a report that is not `DISPUTED` is refused with
    `ERR_INVALID_ROYALTY_STATE`."

    Design: Corner/errors/corner_adjudicating_an_accepted_royalty_report_is_rejected
    """
    scenario = _a_truthful_august_royalty_report_that_auto_accepted()

    validate_error(_adjudicate(scenario), ApiErrorId.ERR_INVALID_ROYALTY_STATE.value, 409)
    report = read_royalty_report(scenario["report"]["id"])
    assert report["status"] == "ACCEPTED"
    assert report["adjusted_royalty_cents"] is None


def test_the_accepted_report_keeps_its_own_verified_royalty_and_leaves_no_dispute_behind():
    """A zero variance resolved the report on submission at 293 cents, and the franchisee carries
    no disputed report for the brand to clear.

    PRD 3.9: "The report is created `SUBMITTED` and immediately auto-resolves on the absolute
    value of `variance_pct` against a tolerance of 5.00 percent: a variance whose magnitude
    exceeds 5.00 resolves to `DISPUTED`, and anything at or within 5.00 resolves to `ACCEPTED`.
    `ACCEPTED` is terminal."

    Design: Corner/errors/corner_adjudicating_an_accepted_royalty_report_is_rejected
    """
    scenario = _a_truthful_august_royalty_report_that_auto_accepted()

    _adjudicate(scenario)
    report = read_royalty_report(scenario["report"]["id"])
    assert report["verified_member_count"] == 1
    assert report["royalty_due_cents"] == 293
    assert read_franchisee(scenario["franchisee"]["id"])["disputed_royalty_count"] == 0


def _two_august_visit_batches_at_the_host_club() -> dict:
    """Eighty-four guest visits, all of them in 2026-08 and none in 2026-07, still unswept."""
    return setup_guest_usage_scenario(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
        period_visits=[("2026-08", 50), ("2026-08", 34)],
    )


def _cut_settlement(scenario: dict, period_month: str):
    return api_client.create_usage_settlement(
        create_usage_settlement_payload(
            period_month, scenario["home_club"]["id"], scenario["host_club"]["id"]
        ),
        BRAND,
    )


def test_a_period_with_no_unsettled_usage_produces_no_settlement_at_all():
    """The club pair really does trade guest visits, but not in July, so the sweep comes back
    empty and the create is refused instead of booking a zero.

    PRD 3.7: "An empty sweep is refused with `ERR_NO_SETTLEABLE_USAGE`; there is no such thing as
    a zero-value settlement."

    Design: Corner/errors/corner_settlement_for_a_period_with_no_unsettled_usage_is_rejected
    """
    scenario = _two_august_visit_batches_at_the_host_club()

    validate_error(
        _cut_settlement(scenario, "2026-07"), ApiErrorId.ERR_NO_SETTLEABLE_USAGE.value, 409
    )
    for event in scenario["guest_usage_events"]:
        assert read_guest_usage_event(event["id"])["settlement_id"] is None
    assert read_club(scenario["home_club"]["id"])["settlement_ledger_cents"] == 0
    assert read_club(scenario["host_club"]["id"])["settlement_ledger_cents"] == 0


def test_the_august_batches_remain_available_to_the_period_that_actually_matches():
    """The refusal claimed nothing: the same two batches are still eligible, and the 2026-08 sweep
    picks up both of them.

    PRD 3.7: "The sweep collects every guest usage batch whose `settlement_id` is null, whose
    `period_month` matches, whose `host_club_id` matches, and whose `home_club_id_at_visit`
    matches the settlement's `home_club_id`, considered in ascending `created_at` order."

    Design: Corner/errors/corner_settlement_for_a_period_with_no_unsettled_usage_is_rejected
    """
    scenario = _two_august_visit_batches_at_the_host_club()

    _cut_settlement(scenario, "2026-07")
    settlement = validate_success(_cut_settlement(scenario, "2026-08"), expected_status=201)
    assert settlement["event_count"] == 2
    assert settlement["visit_count"] == 84
    for event in scenario["guest_usage_events"]:
        assert read_guest_usage_event(event["id"])["settlement_id"] == settlement["id"]


def _an_august_settlement_and_one_late_batch() -> dict:
    """The 2026-08 triple is already settled when a further six-visit batch arrives."""
    scenario = _two_august_visit_batches_at_the_host_club()
    scenario["settlement"] = create_usage_settlement(
        "2026-08", scenario["home_club"]["id"], scenario["host_club"]["id"]
    )
    scenario["late_event"] = record_guest_usage(
        scenario["agreement"]["id"], scenario["host_club"]["id"], "2026-08", 6
    )
    return scenario


def test_the_settled_triple_stays_settled_even_when_fresh_usage_arrives():
    """There genuinely is sweepable usage now, yet uniqueness on the period and club pair outranks
    it, so the second create is a duplicate rather than a top-up.

    PRD 3.7: "Only one settlement may exist per `period_month`, `home_club_id` and `host_club_id`
    triple: a second attempt while an `OPEN` or `POSTED` settlement already covers that triple is
    refused with `ERR_DUPLICATE_SETTLEMENT_PERIOD`."

    Design: Corner/errors/corner_second_settlement_for_the_same_triple_is_rejected
    """
    scenario = _an_august_settlement_and_one_late_batch()

    validate_error(
        _cut_settlement(scenario, "2026-08"),
        ApiErrorId.ERR_DUPLICATE_SETTLEMENT_PERIOD.value,
        409,
    )
    settlement = read_usage_settlement(scenario["settlement"]["id"])
    assert settlement["event_count"] == 2
    assert settlement["net_payable_cents"] == 93702


def test_the_late_batch_keeps_its_own_fee_and_stays_unclaimed():
    """Six visits at the host club's 1250-cent guest fee were priced on arrival, and the refusal
    leaves that batch outside every settlement.

    PRD 3.7: "And `usage_fee_cents` is `visit_count` multiplied by `guest_fee_cents_at_visit`. The
    batch is created unsettled, with `settlement_id` null, and it is immutable: it has no
    `version`, no `updated_at`, and no update operation."

    Design: Corner/errors/corner_second_settlement_for_the_same_triple_is_rejected
    """
    scenario = _an_august_settlement_and_one_late_batch()

    _cut_settlement(scenario, "2026-08")
    late = read_guest_usage_event(scenario["late_event"]["id"])
    assert late["usage_fee_cents"] == 7500
    assert late["settlement_id"] is None


def _an_open_settlement_that_has_never_been_posted() -> dict:
    """The August sweep is cut but no money has moved yet."""
    scenario = _two_august_visit_batches_at_the_host_club()
    scenario["settlement"] = create_usage_settlement(
        "2026-08", scenario["home_club"]["id"], scenario["host_club"]["id"]
    )
    return scenario


def _reverse(scenario: dict):
    return api_client.reverse_usage_settlement(
        scenario["settlement"]["id"],
        reverse_usage_settlement_payload(reason="Nothing has been posted yet."),
        BRAND,
    )


def test_a_settlement_that_never_posted_has_nothing_to_reverse():
    """Reversal is the compensating half of posting, and with both club ledgers still at zero
    there is no posting for it to compensate.

    PRD 3.7: "Reversing anything that is not `POSTED` is refused with
    `ERR_INVALID_SETTLEMENT_STATE`, and `REVERSED` is terminal — a reversed settlement is never
    re-posted, though the released batches may be swept into a fresh one."

    Design: Corner/errors/corner_reversing_a_settlement_that_was_never_posted_is_rejected
    """
    scenario = _an_open_settlement_that_has_never_been_posted()

    validate_error(_reverse(scenario), ApiErrorId.ERR_INVALID_SETTLEMENT_STATE.value, 409)
    settlement = read_usage_settlement(scenario["settlement"]["id"])
    assert settlement["status"] == "OPEN"
    assert settlement["posted_on"] is None
    assert settlement["reversed_on"] is None
    assert read_club(scenario["home_club"]["id"])["settlement_ledger_cents"] == 0
    assert read_club(scenario["host_club"]["id"])["settlement_ledger_cents"] == 0


def test_the_refused_reversal_leaves_the_settlement_still_postable():
    """The refusal is about order rather than validity: the same settlement posts cleanly
    afterwards and moves the money it was always going to move.

    PRD 3.7: "The home club's `settlement_ledger_cents` decreases by `net_payable_cents` and the
    host club's increases by the same amount, `status` advances `OPEN → POSTED`, `posted_on`
    records the logical clock date, and the settlement's `version` plus both clubs' `version`
    values each increment by 1."

    Design: Corner/errors/corner_reversing_a_settlement_that_was_never_posted_is_rejected
    """
    scenario = _an_open_settlement_that_has_never_been_posted()

    validate_error(_reverse(scenario), ApiErrorId.ERR_INVALID_SETTLEMENT_STATE.value, 409)
    posted = post_usage_settlement(scenario["settlement"]["id"])
    assert posted["status"] == "POSTED"
    assert read_club(scenario["home_club"]["id"])["settlement_ledger_cents"] == -93702
    assert read_club(scenario["host_club"]["id"])["settlement_ledger_cents"] == 93702


def _a_funded_pool_and_a_franchisee_nobody_enrolled_with() -> dict:
    """An active, nationally eligible franchisee that sells no memberships, and a 100000-cent
    pool waiting to be distributed."""
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        national_account_eligible=True,
    )
    account = create_corporate_account(
        name="Meridian Logistics", corporate_credit_pct=0.045, allocation_method="USAGE_SHARE"
    )
    fund_corporate_account(account["id"], 100000)
    return {"franchisee": franchisee, "corporate_account": account}


def _allocate(scenario: dict):
    return api_client.allocate_corporate_account(
        scenario["corporate_account"]["id"],
        allocate_corporate_account_payload(note="Nobody is enrolled."),
        BRAND,
    )


def test_a_pool_with_nobody_enrolled_has_no_eligible_recipient():
    """The franchisee is ACTIVE and flagged for national accounts, but no agreement names the
    account, so its weight is 0 and the candidate set is empty.

    PRD 3.8: "A franchisee is eligible when its `status` is `ACTIVE`, its
    `national_account_eligible` flag is true, and its weight is at least 1; a franchisee excluded
    by that flag is excluded from every candidate set no matter how many enrolled members it
    serves. If no franchisee is eligible, the allocation is refused with
    `ERR_NO_ELIGIBLE_FRANCHISEE`, and an allocation attempted while `pool_balance_cents` is 0 is
    refused earlier with `ERR_INVALID_ALLOCATION_STATE`."

    Design: Corner/errors/corner_allocating_a_pool_with_no_enrolled_agreement_is_rejected
    """
    scenario = _a_funded_pool_and_a_franchisee_nobody_enrolled_with()

    validate_error(_allocate(scenario), ApiErrorId.ERR_NO_ELIGIBLE_FRANCHISEE.value, 409)
    account = read_corporate_account(scenario["corporate_account"]["id"])
    assert account["enrolled_agreement_count"] == 0
    assert account["pool_balance_cents"] == 100000
    assert account["allocated_cents"] == 0


def test_the_refused_allocation_leaves_the_funded_pool_whole():
    """Nothing was retained and nothing was spread over zero recipients: the money is still in the
    pool and the franchisee has received none of it.

    PRD 3.8: "Each franchisee's weight is the number of agreements enrolled in this account — that
    is, carrying this `corporate_account_id` — whose `agreement_status` is `ACTIVE` or
    `CANCELLATION_PENDING` and whose home club belongs to that franchisee."

    Design: Corner/errors/corner_allocating_a_pool_with_no_enrolled_agreement_is_rejected
    """
    scenario = _a_funded_pool_and_a_franchisee_nobody_enrolled_with()

    _allocate(scenario)
    account = read_corporate_account(scenario["corporate_account"]["id"])
    assert account["lifetime_funded_cents"] == 100000
    assert account["pool_balance_cents"] + account["allocated_cents"] == 100000
    assert read_franchisee(scenario["franchisee"]["id"])["corporate_allocation_cents"] == 0


def _a_funded_pool_that_was_never_allocated() -> dict:
    """One hundred thousand cents funded and still entirely undistributed."""
    account = create_corporate_account(
        name="Meridian Logistics", corporate_credit_pct=0.045, allocation_method="USAGE_SHARE"
    )
    fund_corporate_account(account["id"], 100000)
    return {"corporate_account": account}


def _recall(scenario: dict):
    return api_client.recall_corporate_allocation(
        scenario["corporate_account"]["id"],
        recall_allocation_payload(reason="There is nothing out there to recall."),
        BRAND,
    )


def test_a_recall_has_nothing_to_undo_while_the_pool_was_never_allocated():
    """Recall is the exact inverse of allocation, so with allocated_cents at 0 there is no
    distribution for it to walk back.

    PRD 3.8: "A recall attempted while `allocated_cents` is 0 is refused with
    `ERR_INVALID_ALLOCATION_STATE`."

    Design: Corner/errors/corner_recalling_before_any_allocation_is_rejected
    """
    scenario = _a_funded_pool_that_was_never_allocated()

    validate_error(_recall(scenario), ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value, 409)
    account = read_corporate_account(scenario["corporate_account"]["id"])
    assert account["status"] == "ACTIVE"
    assert account["pool_balance_cents"] == 100000
    assert account["allocated_cents"] == 0


def test_the_refused_recall_does_not_credit_the_pool_back_into_itself():
    """A recall adds `allocated_cents` back to the pool; refusing it is what keeps the funded total
    from being counted twice.

    PRD 3.8: "The allocation is recomputed to derive the precise share each franchisee received,
    every affected franchisee's `corporate_allocation_cents` is decreased by exactly that share,
    `pool_balance_cents` increases by `allocated_cents`, `allocated_cents` returns to 0, and the
    account's `version` increments — restoring `pool_balance_cents` plus `allocated_cents` to equal
    `lifetime_funded_cents`."

    Design: Corner/errors/corner_recalling_before_any_allocation_is_rejected
    """
    scenario = _a_funded_pool_that_was_never_allocated()
    before = read_corporate_account(scenario["corporate_account"]["id"])

    _recall(scenario)
    after = read_corporate_account(scenario["corporate_account"]["id"])
    assert after["lifetime_funded_cents"] == 100000
    assert after["pool_balance_cents"] + after["allocated_cents"] == 100000
    assert after["version"] == before["version"]


def _a_suspended_corporate_account_and_a_member_ready_to_sign() -> dict:
    """A funded national account that was suspended after funding, plus a club and a member with
    everything else in order."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    account = create_corporate_account(
        name="Meridian Logistics", corporate_credit_pct=0.045, allocation_method="USAGE_SHARE"
    )
    fund_corporate_account(account["id"], 100000)
    scenario["corporate_account"] = suspend_corporate_account(
        account["id"], reason="Master services agreement lapsed."
    )
    return scenario


def _sign_into_the_account(scenario: dict):
    payload = create_agreement_payload(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        read_club_version(scenario["club"]["id"]),
        "2026-08-01",
        corporate_account_id=scenario["corporate_account"]["id"],
    )
    return api_client.create_agreement(
        payload, make_club_manager_headers(scenario["club"]["id"])
    )


def test_a_suspended_account_takes_no_new_enrolments_however_much_it_holds():
    """The pool still carries 100000 cents and the credit would have been lawful; the gate is the
    account's state, not its balance.

    PRD 3.8: "Suspension is a gate on *new* business only: no further agreement may enrol in the
    account, and an attempt to sign one naming it is refused with
    `ERR_CORPORATE_ACCOUNT_SUSPENDED`."

    Design: Corner/errors/corner_enrolling_into_a_suspended_corporate_account_is_rejected
    """
    scenario = _a_suspended_corporate_account_and_a_member_ready_to_sign()

    validate_error(
        _sign_into_the_account(scenario),
        ApiErrorId.ERR_CORPORATE_ACCOUNT_SUSPENDED.value,
        409,
    )
    account = read_corporate_account(scenario["corporate_account"]["id"])
    assert account["status"] == "SUSPENDED"
    assert account["enrolled_agreement_count"] == 0
    assert account["pool_balance_cents"] == 100000


def test_the_refused_enrolment_leaves_no_agreement_anywhere():
    """The signing was rejected as a whole rather than stripped of its corporate reference, so no
    contract exists and no counter moved.

    PRD 3.3: "At most one corporate account participates and it must be `ACTIVE`; naming a
    `SUSPENDED` account is refused with `ERR_CORPORATE_ACCOUNT_SUSPENDED`."

    Design: Corner/errors/corner_enrolling_into_a_suspended_corporate_account_is_rejected
    """
    scenario = _a_suspended_corporate_account_and_a_member_ready_to_sign()

    _sign_into_the_account(scenario)
    _, meta = validate_paginated(api_client.list_agreements(BRAND))
    assert meta["total_count"] == 0
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 0
    assert read_member(scenario["member"]["id"])["agreement_count"] == 0
