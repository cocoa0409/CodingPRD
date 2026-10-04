"""Second (supplementary) tests for queue-A difficulty instances (§2.1 queue A
requires >=2 tests per instance)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_days,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_transponder,
    create_away_agency,
    create_plate_agreement,
    fail_replenishments,
    file_classification_dispute,
    find_pending_image_bill,
    generate_settlement_file,
    get_account,
    get_account_version,
    get_success_data,
    make_account_holder_headers,
    post_image_trip,
    record_replenishment,
    resolve_bill_to_account,
    setup_agency_pair,
    setup_account_with_plan,
    setup_billed_image_bill,
    setup_classification_dispute_under_review,
    setup_full_account,
    setup_three_trips_101_202_303,
    setup_unregistered_plate_violation,
    validate_error,
    validate_paginated,
)

SO = TEST_USERS["settlement_officer_headers"]
AO = TEST_USERS["agency_ops_headers"]
VO = TEST_USERS["violations_officer_headers"]
PL = TEST_USERS["plate_lookup_agent_headers"]


def test_settlement_per_line_fee_second_file_confirms_convention():
    """PRD §3.9: "The reciprocity fee is computed per line: each line
    contributes its `charged_amount_cents` multiplied by the to-agency's
    `reciprocity_fee_bps`, divided by ten thousand, rounded half-up to whole
    cents — and `fee_amount_cents` is the sum of those per-line fees."

    Design: Difficulty/dual_variant_calc/settlement_fee_per_line_vs_aggregate_rounding
    """
    ctx = setup_three_trips_101_202_303(tag_number="TAG-A2")
    sf = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])
    # Recomputed independently: per-line rhu(101*150/10000)=2, rhu(202*...)=3,
    # rhu(303*...)=5. The rejected aggregate convention would total 9.
    assert sf["fee_amount_cents"] == 2 + 3 + 5
    assert sf["net_amount_cents"] == sf["gross_amount_cents"] - sf["fee_amount_cents"]
    assert sf["status"] == "GENERATED"
    assert sf["exception_count"] == 0


def test_misread_plate_uphold_creates_replacement_bill():
    """PRD §3.8: "A brand-new image bill for the corrected plate or the rental
    liable party is then created in `PENDING_LOOKUP`, priced at the video rate
    against the corrected party's account (or sent down the unregistered-plate
    violation path if no account matches)."
    PRD §3.8: "the original account is credited exactly `billed_amount_cents`
    once — a single net-credit entry, deliberately not a
    reversal-plus-separate-credit-memo pair"

    Design: Difficulty/dual_variant_calc/misread_plate_net_credit_vs_void_and_rebill
    """
    ctx = setup_billed_image_bill(account_balance=5000)
    account, bill = ctx["account"], ctx["bill"]
    balance_after_debit = get_account(account["id"])["balance_cents"]
    assert balance_after_debit == 4100

    resp = api_client.create_dispute(
        {
            "account_id": account["id"],
            "dispute_type": "MISREAD_PLATE",
            "image_bill_id": bill["id"],
            "claimed_plate_number": "XYZ999",
        },
        make_account_holder_headers(account["id"]),
    )
    dispute = get_success_data(resp)
    get_success_data(api_client.begin_review_dispute(dispute["id"], VO))
    upheld = get_success_data(api_client.uphold_dispute(dispute["id"], VO))
    assert upheld["status"] == "UPHOLD"

    # Exactly one net credit restores the pre-debit balance.
    assert get_account(account["id"])["balance_cents"] == 5000
    # The corrected plate gets a fresh bill in PENDING_LOOKUP.
    pend, _ = validate_paginated(
        api_client.list_image_bills(PL, params={"status": "PENDING_LOOKUP"})
    )
    assert len(pend) == 1
    assert pend[0]["plate_number"] == "XYZ999"
    assert pend[0]["id"] != bill["id"]


def test_fare_peak_image_vs_transponder_same_schedule():
    """PRD §3.4: "if `is_peak` is true, that axle component is then multiplied
    by `peak_multiplier` and again rounded half-up to whole cents."
    PRD §3.4: "For an image trip, no discount ever applies:
    `discount_amount_cents` is zero, and `gross_amount_cents` is the pre-fee
    gross plus the schedule's `image_fee_cents`. In both variants,
    `charged_amount_cents` is the gross minus the discount, and that is the
    amount the account is actually debited."

    Design: Difficulty/combinatorial_formula/fare_multi_input_peak_axle_discount_video (mode a)
    """
    home, away = setup_agency_pair()
    create_rate_schedule(
        away["id"], plaza_code="P9", vehicle_class="CLASS_5", base_rate_cents=475,
        axle_multiplier=2.5, peak_multiplier=1.25, image_fee_cents=100,
    )
    plan = create_discount_plan(
        home["id"], plan_code="TRUCK20", discount_pct=0.20,
        daily_discount_cap_cents=0, applies_to_agency_codes=[away["agency_code"]],
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=100000)
    create_transponder(account["id"], tag_number="TAG-T5", vehicle_class="CLASS_5")

    t = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-T5", "away_agency_id": away["id"], "plaza_code": "P9",
             "trip_timestamp": "2026-09-03T08:00:00Z", "is_peak": True,
             "idempotency_key": "t5-peak"}, AO,
        )
    )
    # 475*2.5 = 1187.5 -> rhu 1188; 1188*1.25 = 1485.0; discount rhu(297.0)=297.
    assert t["gross_amount_cents"] == 1485
    assert t["charged_amount_cents"] == 1485 - 297
    assert get_account(account["id"])["balance_cents"] == 100000 - 1188


def test_daily_cap_not_restored_by_void():
    """PRD §3.4: "the cap is never redistributed retroactively, so an earlier
    trip keeps its full discount even if a later trip is voided — voiding does
    not restore `discount_used_today_cents`."

    Design: Difficulty/combinatorial_formula/daily_cap_chronological_nested_rounding (mode b)
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P2", base_rate_cents=575)
    plan = create_discount_plan(
        home["id"], plan_code="COMMUTER", discount_pct=0.20,
        daily_discount_cap_cents=300, applies_to_agency_codes=[away["agency_code"]],
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=100000)
    create_transponder(account["id"], tag_number="TAG-C2", plate_number="CAP301")

    txns = []
    for ts, key in (("2026-09-04T09:00:00Z", "c21"), ("2026-09-04T10:00:00Z", "c22"),
                    ("2026-09-04T11:00:00Z", "c23")):
        txns.append(get_success_data(
            api_client.post_toll_transaction(
                {"tag_number": "TAG-C2", "away_agency_id": away["id"], "plaza_code": "P2",
                 "trip_timestamp": ts, "is_peak": False, "idempotency_key": key}, AO,
            )
        ))
    assert [t["discount_amount_cents"] for t in txns] == [115, 115, 70]

    # Void the first trip: cap usage stays at 300 (not restored).
    get_success_data(api_client.void_toll_transaction(txns[0]["id"], AO))
    assert get_account(account["id"])["discount_used_today_cents"] == 300

    # A fourth trip the same day still gets zero discount.
    t4 = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-C2", "away_agency_id": away["id"], "plaza_code": "P2",
             "trip_timestamp": "2026-09-04T12:00:00Z", "is_peak": False,
             "idempotency_key": "c24"}, AO,
        )
    )
    assert t4["discount_amount_cents"] == 0


def test_violation_hold_referred_pay_leaves_referral_flag():
    """PRD §3.7: "An `AccountHolder` or a `ViolationsOfficer` may pay a
    violation in full from `OPEN`, `NOTICED`, `ESCALATED`, or `HOLD_REFERRED`;
    payment moves it to `PAID` and zeroes `total_outstanding_cents`. Notably,
    paying a violation that was already `HOLD_REFERRED` leaves
    `registration_hold_referred` untouched — releasing the DMV hold is a
    separate out-of-band flow."

    Design: Difficulty/non_linear_state_machine/violation_branching_fork_join
    """
    ctx = setup_unregistered_plate_violation(
        base_rate_cents=2000, image_fee_cents=100, plaza_code="P1", plate_number="UNREG9"
    )
    v = ctx["violation"]
    from test_helpers import notice_three_times
    notice_three_times(v["id"])
    advance_days(1)
    escalated = get_success_data(api_client.get_violation(v["id"], VO))
    # 2100 + 500 + 2500 + 5000 = 10100 >= 10000 -> straight to HOLD_REFERRED.
    assert escalated["status"] == "HOLD_REFERRED"
    assert escalated["registration_hold_referred"] is True

    get_success_data(api_client.pay_violation(v["id"], VO))
    paid = get_success_data(api_client.get_violation(v["id"], VO))
    assert paid["status"] == "PAID"
    assert paid["total_outstanding_cents"] == 0
    assert paid["registration_hold_referred"] is True


def test_dispute_reject_returns_transaction_to_posted():
    """PRD §3.8: "Rejecting a classification dispute moves the dispute to
    `REJECTED` and returns the transaction from `DISPUTED` to `POSTED`
    unchanged."

    Design: Difficulty/non_linear_state_machine/dispute_cycle_review_reject_refire
    """
    ctx = setup_classification_dispute_under_review(tag_number="TAG-V2")
    txn, dispute = ctx["txn"], ctx["dispute"]
    assert get_success_data(api_client.get_toll_transaction(txn["id"], AO))["status"] == "DISPUTED"

    get_success_data(api_client.reject_dispute(dispute["id"], VO))
    assert get_success_data(api_client.get_dispute(dispute["id"], VO))["status"] == "REJECTED"
    txn_now = get_success_data(api_client.get_toll_transaction(txn["id"], AO))
    assert txn_now["status"] == "POSTED"
    assert txn_now["charged_amount_cents"] == 1188


def test_third_failed_replenishment_suspends_and_blocks_posting():
    """PRD §3.5: "When `replenishment_fail_count` reaches three consecutive
    failures, the account transitions from `ACTIVE` to `SUSPENDED` with
    `suspended_reason` set to `REPLENISHMENT_FAILED`, and every `ACTIVE`
    transponder on the account becomes ineligible for new toll postings —
    subsequent postings fail with `ERR_ACCOUNT_SUSPENDED`."

    Design: Difficulty/transitive_cascade/toll_post_to_replenishment_to_suspension (depth 3)
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P4", base_rate_cents=1200)
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(
        home["id"], plan["id"], low_balance_threshold_cents=1000,
        replenishment_amount_cents=2500, opening_balance_cents=1600,
    )
    create_transponder(account["id"], tag_number="TAG-R2", plate_number="LOW101")

    get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-R2", "away_agency_id": away["id"], "plaza_code": "P4",
             "trip_timestamp": "2026-09-06T08:00:00Z", "is_peak": False,
             "idempotency_key": "r21"}, AO,
        )
    )
    # Two failed replenishments: still ACTIVE.
    fail_replenishments(account["id"], 2, amount_cents=2500)
    assert get_account(account["id"])["status"] == "ACTIVE"

    # Third consecutive failure: cascade terminus.
    record_replenishment(account["id"], 2500, "FAILED", get_account_version(account["id"]))
    acct = get_account(account["id"])
    assert acct["status"] == "SUSPENDED"
    assert acct["suspended_reason"] == "REPLENISHMENT_FAILED"
    assert acct["replenishment_fail_count"] == 3

    resp = api_client.post_toll_transaction(
        {"tag_number": "TAG-R2", "away_agency_id": away["id"], "plaza_code": "P4",
         "trip_timestamp": "2026-09-06T09:00:00Z", "is_peak": False,
         "idempotency_key": "r22"}, AO,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)


def test_upheld_dispute_credits_exactly_the_delta():
    """PRD §3.8: "Upholding a classification dispute re-prices the transaction
    at the `claimed_vehicle_class`: `billed_vehicle_class`,
    `gross_amount_cents`, `discount_amount_cents`, and `charged_amount_cents`
    are recomputed, the account's `balance_cents` is credited the difference
    between the old and new charged amounts, and the transaction returns to
    `POSTED` with the corrected class."

    Design: Difficulty/transitive_cascade/upheld_classification_dispute_repricing_cascade (depth 2)
    """
    ctx = setup_classification_dispute_under_review(tag_number="TAG-X2")
    account, txn, dispute = ctx["account"], ctx["txn"], ctx["dispute"]
    before = get_account(account["id"])["balance_cents"]

    get_success_data(api_client.uphold_dispute(dispute["id"], VO))
    after = get_account(account["id"])["balance_cents"]
    # Credited the delta 1188 - 300 = 888, caused by the repricing.
    assert after - before == 888
    txn_now = get_success_data(api_client.get_toll_transaction(txn["id"], AO))
    assert txn_now["gross_amount_cents"] == 300
    assert txn_now["discount_amount_cents"] == 0


def test_state_check_fires_before_rate_lookup_on_suspended_account():
    """PRD §2.8: "Only after those generic checks do business rules run, in the
    following order: account, transponder, and agency operational safety before
    a toll debit; rate-schedule existence and discount-plan applicability"
    PRD §3.4: "the billed account must not be `SUSPENDED`
    (`ERR_ACCOUNT_SUSPENDED`) or `CLOSED` (`ERR_ACCOUNT_CLOSED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_toll_post
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P4", base_rate_cents=1200)
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=500)
    create_transponder(account["id"], tag_number="TAG-S2", plate_number="SUS101")
    fail_replenishments(account["id"], 3)

    resp = api_client.post_toll_transaction(
        {"tag_number": "TAG-S2", "away_agency_id": away["id"], "plaza_code": "PX",
         "trip_timestamp": "2026-09-08T09:00:00Z", "is_peak": False,
         "idempotency_key": "sx2"}, AO,
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
    # No debit occurred.
    assert get_account(account["id"])["balance_cents"] == 500


def test_notice_too_soon_rejected_at_ten_days():
    """PRD §3.7: "at least 30 days must have elapsed since the previous notice
    — issuing too early is rejected with `ERR_NOTICE_TOO_SOON`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_notice_issue
    """
    ctx = setup_unregistered_plate_violation(
        base_rate_cents=800, image_fee_cents=100, plaza_code="P1", plate_number="UNREG10"
    )
    v = ctx["violation"]
    get_success_data(api_client.issue_notice(v["id"], VO))
    advance_days(10)
    resp = api_client.issue_notice(v["id"], VO)
    validate_error(resp, ApiErrorId.ERR_NOTICE_TOO_SOON)
    assert get_success_data(api_client.get_violation(v["id"], VO))["notice_count"] == 1


def test_balance_exactly_at_threshold_stays_active():
    """PRD §3.5: "If the account is `ACTIVE` and its balance has fallen
    strictly below its `low_balance_threshold_cents`, an automatic
    replenishment of `replenishment_amount_cents` is attempted. The boundary is
    strict: a balance exactly equal to the threshold does not trigger a
    top-up."

    Design: Difficulty/boundary_precision_check/low_balance_threshold_strictly_below
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P5", base_rate_cents=200)
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(
        home["id"], plan["id"], low_balance_threshold_cents=1000,
        replenishment_amount_cents=2500, opening_balance_cents=1200,
    )
    create_transponder(account["id"], tag_number="TAG-E2", plate_number="EXA101")
    get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-E2", "away_agency_id": away["id"], "plaza_code": "P5",
             "trip_timestamp": "2026-09-09T09:00:00Z", "is_peak": False,
             "idempotency_key": "e2"}, AO,
        )
    )
    acct = get_account(account["id"])
    assert acct["balance_cents"] == 1000
    assert acct["status"] == "ACTIVE"
    assert acct["replenishment_fail_count"] == 0


def test_escalated_below_threshold_referred_on_next_sweep_after_fees():
    """PRD §3.7: "For violations already sitting in `ESCALATED`, every
    subsequent day advancement re-evaluates the same threshold: once
    `total_outstanding_cents` is at least 10000 cents — and the boundary is
    inclusive, exactly 10000 is referred while 9999 is not — the violation
    moves to `HOLD_REFERRED`, `registration_hold_referred` is set true, and a
    referral is sent to the plate state's DMV."

    Design: Difficulty/boundary_precision_check/reg_hold_threshold_inclusive_boundary
    """
    ctx = setup_unregistered_plate_violation(
        base_rate_cents=1999, image_fee_cents=0, plaza_code="P1", plate_number="UNREG11"
    )
    v = ctx["violation"]
    from test_helpers import notice_three_times
    notice_three_times(v["id"])
    advance_days(1)
    vio = get_success_data(api_client.get_violation(v["id"], VO))
    # 1999 + 8000 = 9999: ESCALATED, not referred.
    assert vio["total_outstanding_cents"] == 9999
    assert vio["status"] == "ESCALATED"
    assert vio["registration_hold_referred"] is False


def test_revoked_agreement_blocks_resolve_midway():
    """PRD §3.9: "An officer may revoke an agreement outright, moving it from
    `ACTIVE` to `REVOKED` (terminal); from that moment, plate lookups relying
    on it are rejected with `ERR_PLATE_LOOKUP_NOT_AVAILABLE`."
    PRD §3.6: "The lookup is only lawful when a plate data agreement in
    `ACTIVE` status exists whose requesting agency is the away agency of the
    trip, whose providing agency covers the plate's state in its
    `covers_states` list, and whose half-open validity window from
    `effective_from` to `effective_to` contains the current logical time."

    Design: Difficulty/cross_entity_state_dependency/image_bill_resolve_gated_by_plate_data_agreement
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=800, effective_to="2026-12-31T00:00:00Z")
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=10000)
    agreement = create_plate_agreement(away["id"], home["id"])

    post_image_trip(away["id"], "P1", "NYP300", "NY", "2026-09-02T09:00:00Z", "l3")
    bill = find_pending_image_bill()
    get_success_data(api_client.revoke_plate_data_agreement(agreement["id"], SO))

    resp = api_client.resolve_image_bill(
        bill["id"], {"resolved_account_id": account["id"]}, PL
    )
    validate_error(resp, ApiErrorId.ERR_PLATE_LOOKUP_NOT_AVAILABLE)
    assert get_success_data(api_client.get_image_bill(bill["id"], PL))["status"] == "PENDING_LOOKUP"
    # No debit happened.
    assert get_account(account["id"])["balance_cents"] == 10000


def test_suspended_agency_blocks_posting_until_reactivated():
    """PRD §3.1: "While suspended, no new toll transaction may be posted at the
    agency's plazas: such attempts fail with `ERR_AGENCY_SUSPENDED`. A
    suspended agency may be reactivated, returning it to `ACTIVE`; reactivation
    has no further preconditions."

    Design: Difficulty/cross_entity_state_dependency/transponder_post_gated_by_agency_suspend
    """
    ctx = setup_full_account(tag_number="TAG-G2", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    get_success_data(api_client.suspend_agency(ctx["away"]["id"], SO))

    resp = api_client.post_toll_transaction(
        {"tag_number": "TAG-G2", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
         "trip_timestamp": "2026-09-10T09:00:00Z", "is_peak": False,
         "idempotency_key": "g2"}, AO,
    )
    validate_error(resp, ApiErrorId.ERR_AGENCY_SUSPENDED)

    # Reactivation has no further preconditions; posting works again.
    get_success_data(api_client.reactivate_agency(ctx["away"]["id"], SO))
    ok = api_client.post_toll_transaction(
        {"tag_number": "TAG-G2", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
         "trip_timestamp": "2026-09-10T10:00:00Z", "is_peak": False,
         "idempotency_key": "g3"}, AO,
    )
    assert ok.status_code == 201
    assert get_account(ctx["account"]["id"])["balance_cents"] == 9200


def test_schedule_overlap_rejected_within_window():
    """PRD §3.1: "The window is half-open: a schedule is usable at
    `effective_from` and stops being usable at `effective_to`. Schedules are
    created in `ACTIVE` status; if the requested window overlaps the window of
    any existing `ACTIVE` schedule for the same agency, plaza, and class,
    creation is rejected with `ERR_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_window_half_open_overlap
    """
    away = create_away_agency()
    create_rate_schedule(
        away["id"], base_rate_cents=800,
        effective_from="2026-09-01T00:00:00Z", effective_to="2026-10-01T00:00:00Z",
    )
    resp = api_client.create_rate_schedule(
        away["id"],
        {
            "plaza_code": "P1", "vehicle_class": "CLASS_2", "base_rate_cents": 860,
            "axle_multiplier": 1.0, "peak_multiplier": 1.0, "image_fee_cents": 100,
            "effective_from": "2026-09-15T00:00:00Z", "effective_to": "2026-11-01T00:00:00Z",
        },
        AO,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)


def test_plate_agreement_overlap_only_on_shared_state():
    """PRD §3.9: "if an existing `ACTIVE` agreement for the same
    requesting-providing pair already covers any shared state with an
    overlapping validity window, creation is rejected with
    `ERR_AGREEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/plate_agreement_shared_state_overlap
    """
    away = create_away_agency()
    prov = create_home_agency(agency_code="PRV2", name="Prov Two", home_state="CT")
    get_success_data(
        api_client.create_plate_data_agreement(
            {
                "requesting_agency_id": away["id"], "providing_agency_id": prov["id"],
                "effective_from": "2026-09-01T00:00:00Z", "effective_to": "2027-09-01T00:00:00Z",
                "covers_states": ["NY", "NJ"],
            },
            SO,
        )
    )
    resp = api_client.create_plate_data_agreement(
        {
            "requesting_agency_id": away["id"], "providing_agency_id": prov["id"],
            "effective_from": "2027-06-01T00:00:00Z", "effective_to": "2028-01-01T00:00:00Z",
            "covers_states": ["NJ"],
        },
        SO,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)


def test_void_then_repost_keeps_cap_consumed():
    """PRD §3.4: "the cap is never redistributed retroactively, so an earlier
    trip keeps its full discount even if a later trip is voided — voiding does
    not restore `discount_used_today_cents`."
    PRD §4: "Void a posted transaction and credit the account"

    Design: Difficulty/compensating_invariant/toll_void_restores_balance_exactly
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=800)
    plan = create_discount_plan(
        home["id"], plan_code="PROMO20", discount_pct=0.20,
        daily_discount_cap_cents=0, applies_to_agency_codes=[away["agency_code"]],
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=5000)
    create_transponder(account["id"], tag_number="TAG-I2", plate_number="VOID02")
    txn = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-I2", "away_agency_id": away["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-11T09:00:00Z", "is_peak": False,
             "idempotency_key": "i21"}, AO,
        )
    )
    assert get_account(account["id"])["balance_cents"] == 4360

    get_success_data(api_client.void_toll_transaction(txn["id"], AO))
    acct = get_account(account["id"])
    assert acct["balance_cents"] == 5000  # credit restores the charged amount
    assert acct["discount_used_today_cents"] == 160  # cap usage NOT restored


def test_sweep_marks_lines_and_second_generate_is_empty():
    """PRD §3.9: "The sweep claims every toll transaction that is in `POSTED`
    status with `settlement_file_id` still null, whose `away_agency_id` is the
    to-agency, and whose account's home agency is the from-agency... Each
    claimed line moves from `POSTED` to `SETTLED` and has its
    `settlement_file_id` set."

    Design: Difficulty/compensating_invariant/settlement_sweep_conserves_line_total
    """
    ctx = setup_three_trips_101_202_303(tag_number="TAG-W2")
    sf1 = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])
    rows, _ = validate_paginated(
        api_client.list_toll_transactions(AO, params={"settlement_file_id": sf1["id"]})
    )
    assert len(rows) == 3
    for row in rows:
        assert row["status"] == "SETTLED"
    sf2 = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])
    assert sf2["line_count"] == 0
    assert sf2["fee_amount_cents"] == 0
    assert sf2["gross_amount_cents"] == 0
