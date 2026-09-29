"""Declared transitions, initial states, terminal lockdowns and consequence moves.

Every rule exercised here is stated in PRD s3.3, s3.4, s3.5, s3.7, s3.8 or s3.9.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_ATHLETE_STATE_INVALID,
    ERR_COMMITMENT_STATE_INVALID,
    ERR_CONTRACT_NOT_DRAFT,
    ERR_DISCLOSURE_NOT_CLEARED,
)
from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_deliverable_scoring,
    assert_donor_ledger,
    assert_release_money,
    assert_timestamp_equals,
    read_data,
)
from test_helpers.factories import (
    commitment_payload,
    commitment_transition_payload,
    contribution_payload,
    deliverable_payload,
    eligibility_change_payload,
    membership_tier_payload,
    payment_release_payload,
    settlement_payload,
    termination_payload,
    tier_transition_payload,
)
from test_helpers.fixtures import (
    activate_contract,
    add_evidence,
    build_athlete,
    build_collective,
    build_donor,
    build_draft_contract,
    build_open_tier,
    build_settled_contribution,
    clear_disclosure,
    move_clock,
    read_athlete,
    read_collective,
    read_contract,
    read_deliverable,
    read_donor,
    read_release,
    record_taxpayer_doc,
    review_work,
    submit_work,
)
from test_helpers.test_users import (
    make_compliance_headers,
    make_director_headers,
    make_treasury_headers,
)


def test_a_tier_walks_draft_to_open_to_closed_without_touching_its_price(api):
    """Both declared tier transitions run through the one transitions endpoint.

    PRD s3.3: "Opening a tier advances it `DRAFT -> OPEN`" and "Closing a tier advances
    it `OPEN -> CLOSED` and requires the tier to be `OPEN` ... `CLOSED` is terminal".
    PRD s3.3 also states that "a new tier begins life in `tier_status` `DRAFT`".

    Design: Corner/state_machines/membership_tier_open_transition_moves_draft_to_open_then_closed
    """
    collective = build_collective(
        api,
        "021400",
        name="Transition Collective",
        institution_name="Transition Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    created = read_data(
        api.create_membership_tier(
            collective["id"],
            membership_tier_payload("T3", 150000, 3, tier_name="Gold"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert created["tier_status"] == "DRAFT"

    opened = read_data(
        api.transition_membership_tier(
            created["id"], tier_transition_payload("OPEN"), make_director_headers()
        )
    )
    assert opened["tier_status"] == "OPEN"

    closed = read_data(
        api.transition_membership_tier(
            created["id"], tier_transition_payload("CLOSE"), make_director_headers()
        )
    )
    assert closed["tier_status"] == "CLOSED"
    assert closed["annual_dues_cents"] == 150000
    assert closed["benefit_rank"] == 3
    assert closed["active_commitment_count"] == 0


def test_activation_is_refused_while_the_disclosure_is_still_pending(api):
    """The lifecycle transition is guarded by the independent disclosure dimension.

    PRD s3.8: "Its `disclosure_status` must be `DISCLOSURE_NOT_REQUIRED` or
    `DISCLOSURE_ACCEPTED` — a contract still pending, late or returned on disclosure is
    refused with `ERR_DISCLOSURE_NOT_CLEARED`."

    Design: Corner/state_machines/activation_before_disclosure_accepted_is_rejected
    """
    collective = build_collective(
        api,
        "021500",
        name="Guard Collective",
        institution_name="Guard Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
    )
    athlete = build_athlete(
        api, collective["id"], "ath-guard", full_name="Guard Athlete", sport="FOOTBALL"
    )
    contract = build_draft_contract(api, collective["id"], athlete["id"], 100000)
    assert contract["disclosure_status"] == "DISCLOSURE_PENDING"

    refused = api.activate_deal_contract(contract["id"], {}, make_director_headers())
    validate_error(refused, ERR_DISCLOSURE_NOT_CLEARED, expected_status=409)

    still_draft = read_contract(api, contract["id"])
    assert_contract_dimensions(still_draft, lifecycle_status="DRAFT")
    assert still_draft["disclosure_submitted_at"] is None

    clear_disclosure(api, contract["id"], state_law_citation="OH-3345.56")
    activated = activate_contract(api, contract["id"])
    assert_contract_dimensions(
        activated, lifecycle_status="ACTIVE", disclosure_status="DISCLOSURE_ACCEPTED"
    )


def test_a_deferred_contribution_moves_every_ledger_only_on_settlement(api):
    """Nothing is derived until the deferred decision approves the charge.

    PRD s3.5: "`DEFER` leaves it in `PENDING`, to be resolved later by a settlement
    decision. That later decision ... supplies an `outcome` of `APPROVE` or `DECLINE` and
    requires the contribution to still be `PENDING`", and "an inline settlement and a
    deferred settlement have identical consequences". PRD s3.3 adds that "A donor in
    `PROSPECT` becomes `ACTIVE` the moment any contribution of theirs reaches `SETTLED`".

    Design: Corner/state_machines/deferred_contribution_settlement_syncs_collective_and_donor_ledgers
    """
    collective = build_collective(
        api,
        "021600",
        name="Ledger Sync Collective",
        institution_name="Ledger Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        entity_structure="NONPROFIT_501C3",
    )
    tier = build_open_tier(api, collective["id"], "T2", 50000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Sync Donor",
        email="sync@example.com",
        donor_kind="INDIVIDUAL",
        annual_agi_cents=1000000,
    )
    deferred = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"], 100000, designation="UNRESTRICTED", processor_outcome="DEFER"
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(deferred, status="PENDING", net_amount_cents=0)
    assert_donor_ledger(
        read_donor(api, donor["id"]), lifetime_settled_cents=0, status="PROSPECT"
    )
    assert_collective_ledger(read_collective(api, collective["id"]), settled_net_funds_cents=0)

    settled = read_data(
        api.settle_contribution(
            deferred["id"], settlement_payload("APPROVE"), make_treasury_headers()
        )
    )
    assert_contribution_money(
        settled,
        status="SETTLED",
        processing_fee_cents=2530,
        net_amount_cents=97470,
        deductible_amount_cents=97470,
        deduction_variant="AT_RECEIPT",
    )
    assert_donor_ledger(
        read_donor(api, donor["id"]),
        lifetime_settled_cents=97470,
        lifetime_deductible_cents=97470,
        status="ACTIVE",
    )
    assert_collective_ledger(
        read_collective(api, collective["id"]),
        settled_net_funds_cents=97470,
        funding_posture="OPEN",
    )


def test_a_cancelled_commitment_refuses_every_further_action(api):
    """CANCELLED is terminal, so no action reaches it a second time.

    PRD s3.4: "`CANCEL` advances `ACTIVE -> CANCELLED`, `PAST_DUE -> CANCELLED` or
    `PAUSED -> CANCELLED` ... Any action attempted from a state its rule does not permit
    is refused with `ERR_COMMITMENT_STATE_INVALID`", and "`FULFILLED` and `CANCELLED` are
    terminal."

    Design: Corner/state_machines/cancel_already_cancelled_commitment_returns_state_invalid
    """
    collective = build_collective(
        api,
        "021700",
        name="Cancel Collective",
        institution_name="Cancel Institution",
        home_state_code="FL",
        association_ruleset="NAIA",
    )
    tier = build_open_tier(api, collective["id"], "T1", 20000, 1)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Cancel Donor",
        email="cancel@example.com",
    )
    commitment = read_data(
        api.create_commitment(
            commitment_payload(
                donor["id"],
                "MAJOR_GIFT_PLEDGE",
                300000,
                "NONE",
                expected_donor_member_version=donor["version"],
                installments_total=3,
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    cancelled = read_data(
        api.transition_commitment(
            commitment["id"], commitment_transition_payload("CANCEL"), make_director_headers()
        )
    )
    assert cancelled["status"] == "CANCELLED"

    for action in ("CANCEL", "PAUSE", "RESUME"):
        response = api.transition_commitment(
            commitment["id"],
            commitment_transition_payload(action),
            make_director_headers(),
        )
        validate_error(response, ERR_COMMITMENT_STATE_INVALID, expected_status=409)

    stored = read_data(api.get_commitment(commitment["id"], make_director_headers()))
    assert stored["status"] == "CANCELLED"
    assert stored["installments_charged"] == 0
    tier_now = read_data(api.get_membership_tier(tier["id"], make_director_headers()))
    assert tier_now["active_commitment_count"] == 0


def test_a_contract_below_the_threshold_and_its_deliverable_are_born_clean(api):
    """One cent below 60000 needs no disclosure, and a fresh deliverable is all zeros.

    PRD s3.8: "A contract whose `total_value_cents` is at least 60,000 cents ... starts in
    `disclosure_status` `DISCLOSURE_PENDING` with a `disclosure_due_at` equal to its
    `created_at` plus 168 hours ... A contract below that face value starts in
    `DISCLOSURE_NOT_REQUIRED` with a null `disclosure_due_at` ... and
    `disclosure_return_count` starts at 0." PRD s3.9: a new deliverable "begins in `status`
    `PENDING` with an empty `evidence_records` list, a `submission_count` of 0, a
    `late_flag` of false, a `charity_hours_tenths` of 0, null `performed_at`,
    `submitted_at`, `verified_by_user_id` and `verified_at`", and its
    `payout_eligible_cents` "is 0 unless its `status` is `VERIFIED` or `WAIVED`".

    Design: Corner/state_machines/new_deal_contract_and_deliverable_start_in_declared_initial_states
    """
    collective = build_collective(
        api,
        "021800",
        name="Initial Collective",
        institution_name="Initial Institution",
        home_state_code="AL",
        association_ruleset="NCAA_2024",
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-init",
        full_name="Init Athlete",
        sport="SOFTBALL",
        class_year=2028,
    )
    # A merely DRAFT contract already counts as committed (PRD s3.8), so the collective is
    # funded first: without settled money the first draft alone would drive the posture to
    # FROZEN and PRD s2.10 would then refuse the second creation with
    # ERR_COLLECTIVE_FUNDING_FROZEN before either disclosure rule could be observed.
    tier = build_open_tier(api, collective["id"], "T1", 20000, 1)
    funder = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Init Donor",
        email="init@example.com",
    )
    build_settled_contribution(api, funder["id"], 200000)

    contract = build_draft_contract(api, collective["id"], athlete["id"], 59999)
    assert_contract_dimensions(
        contract,
        lifecycle_status="DRAFT",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_NOT_REQUIRED",
    )
    assert contract["disclosure_due_at"] is None
    assert contract["disclosure_return_count"] == 0

    deliverable = read_data(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("AUTOGRAPH_SESSION", 59999, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_deliverable_scoring(
        deliverable,
        status="PENDING",
        payout_eligible_cents=0,
        late_flag=False,
        submission_count=0,
        evidence_count=0,
    )
    assert deliverable["evidence_records"] == []
    assert deliverable["charity_hours_tenths"] == 0
    assert deliverable["required_charity_hours_tenths"] == 0
    assert deliverable["verified_by_user_id"] is None
    assert deliverable["performed_at"] is None

    at_threshold = build_draft_contract(api, collective["id"], athlete["id"], 60000)
    assert at_threshold["disclosure_status"] == "DISCLOSURE_PENDING"
    assert_timestamp_equals(at_threshold["disclosure_due_at"], "2026-08-08T00:00:00Z")


def test_a_transferred_out_athlete_refuses_every_declared_change(api):
    """TRANSFERRED_OUT is terminal, so even a REINSTATE that suits INELIGIBLE fails.

    PRD s3.7: "Each is a declared transition out of a specific current state, and a change
    requested from any other state is refused with `ERR_ATHLETE_STATE_INVALID`", and
    "`COMPLETE_TRANSFER` moves `PORTAL_ENTERED -> TRANSFERRED_OUT` ... `TRANSFERRED_OUT` is
    terminal."

    Design: Corner/state_machines/transferred_out_athlete_rejects_further_eligibility_changes
    """
    collective = build_collective(
        api,
        "021900",
        name="Terminal Collective",
        institution_name="Terminal Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2026",
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-term",
        full_name="Term Athlete",
        sport="FOOTBALL",
        class_year=2027,
        as_compliance=True,
    )
    read_data(
        api.change_athlete_eligibility(
            athlete["id"], eligibility_change_payload("ENTER_PORTAL"), make_compliance_headers()
        )
    )
    transferred = read_data(
        api.change_athlete_eligibility(
            athlete["id"],
            eligibility_change_payload("COMPLETE_TRANSFER"),
            make_compliance_headers(),
        )
    )
    assert transferred["eligibility_status"] == "TRANSFERRED_OUT"

    for change in (
        "REINSTATE",
        "ENTER_PORTAL",
        "WITHDRAW_FROM_PORTAL",
        "DECLARE_INELIGIBLE",
        "COMPLETE_TRANSFER",
    ):
        response = api.change_athlete_eligibility(
            athlete["id"], eligibility_change_payload(change), make_compliance_headers()
        )
        validate_error(response, ERR_ATHLETE_STATE_INVALID, expected_status=409)

    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]), eligibility_status="TRANSFERRED_OUT"
    )


def test_activation_replayed_against_an_active_contract_is_refused(api):
    """Activation is not idempotent, and the refusal leaves the version alone.

    PRD s3.8: "The contract's `lifecycle_status` must be `DRAFT`, or the request is
    `ERR_CONTRACT_NOT_DRAFT`." PRD s2.8 adds that "the **first** violated check decides the
    response; no later check can mask an earlier one, and nothing is written when any check
    fails", so the refused replay cannot bump the version a second time.

    Design: Corner/state_machines/second_activation_of_active_contract_is_rejected
    """
    collective = build_collective(
        api,
        "022000",
        name="Idempotency Collective",
        institution_name="Idempotency Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-idem",
        full_name="Idem Athlete",
        sport="BASEBALL",
        class_year=2028,
    )
    contract = build_draft_contract(api, collective["id"], athlete["id"], 50000)
    assert contract["disclosure_status"] == "DISCLOSURE_NOT_REQUIRED"

    first = activate_contract(api, contract["id"])
    assert first["lifecycle_status"] == "ACTIVE"
    version_after_first = read_contract(api, contract["id"])["version"]

    replay = api.activate_deal_contract(contract["id"], {}, make_director_headers())
    validate_error(replay, ERR_CONTRACT_NOT_DRAFT, expected_status=409)

    stored = read_contract(api, contract["id"])
    assert_contract_dimensions(stored, lifecycle_status="ACTIVE")
    assert stored["version"] == version_after_first


def test_completion_needs_both_full_payment_and_terminal_deliverables(api):
    """Verifying the only deliverable does not complete the contract; the payment does.

    PRD s3.8: "A contract in `ACTIVE` moves to `COMPLETED` when both of two things hold at
    once: its `payment_status` is `FULLY_PAID`, and it has at least one deliverable with
    every one of them in a terminal deliverable position." PRD s3.9 fixes the release
    consequences: payment_status goes "from `UNPAID` straight to `FULLY_PAID` ... when that
    total now equals `total_value_cents`", and segregation of duties requires that "the
    caller's `X-User-ID` must differ from the named deliverable's `verified_by_user_id`".

    Design: Corner/state_machines/contract_completes_when_payment_full_and_all_deliverables_terminal
    """
    collective = build_collective(
        api,
        "022100",
        name="Bubble Collective",
        institution_name="Bubble Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T2", 30000, 2)
    donor = build_donor(
        api, collective["id"], tier["id"], display_name="Bub Donor", email="bub@example.com"
    )
    contribution = build_settled_contribution(
        api, donor["id"], 120000, designation="UNRESTRICTED"
    )
    assert_contribution_money(
        contribution, processing_fee_cents=3030, net_amount_cents=116970, status="SETTLED"
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-bub",
        full_name="Bub Athlete",
        sport="FOOTBALL",
        class_year=2028,
    )
    record_taxpayer_doc(api, athlete["id"], "W9")

    contract = build_draft_contract(
        api, collective["id"], athlete["id"], 60000, funding_designation="UNRESTRICTED"
    )
    clear_disclosure(
        api,
        contract["id"],
        state_law_citation="CA-AB131",
        association_rule_citation="NCAA-2026-12.5",
    )
    activate_contract(api, contract["id"])

    deliverable = read_data(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("SOCIAL_POST", 60000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    add_evidence(api, deliverable["id"], "ANALYTICS_SCREENSHOT", "bub-post")
    submit_work(api, deliverable["id"], "2026-08-05T00:00:00Z")
    verified = review_work(api, deliverable["id"], "VERIFY", "compliance-b")
    assert_deliverable_scoring(
        verified,
        status="VERIFIED",
        payout_basis="STRICT_UNIT_BASIS",
        payout_eligible_cents=60000,
    )

    before = read_contract(api, contract["id"])
    assert_contract_dimensions(
        before, lifecycle_status="ACTIVE", payment_status="UNPAID"
    )

    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "DELIVERABLE_PAYOUT",
                60000,
                expected_deal_contract_version=before["version"],
                deliverable_id=deliverable["id"],
            ),
            make_treasury_headers("treasury-b"),
        ),
        expected_status=201,
    )
    assert_release_money(
        release,
        status="RELEASED",
        withholding_basis="NONE",
        withholding_amount_cents=0,
        net_payable_cents=60000,
    )

    completed = read_contract(api, contract["id"])
    assert_contract_money(completed, released_total_cents=60000)
    assert_contract_dimensions(
        completed, lifecycle_status="COMPLETED", payment_status="FULLY_PAID"
    )
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]),
        tax_year_gross_paid_cents=60000,
        tax_form_required="FORM_1099_NEC",
    )


def test_withdrawing_from_the_portal_advances_the_queued_release(api):
    """A change on the athlete moves a release row in another aggregate.

    PRD s3.9: "when the athlete is `PORTAL_ENTERED`, the row remains `QUEUED` until the
    athlete withdraws from the portal, at which point the withdraw cascade of s3.7 advances
    it." PRD s3.7: "`WITHDRAW_FROM_PORTAL` moves `PORTAL_ENTERED -> ENROLLED` ... It then
    releases the held money: every payment release still in `QUEUED` on an `ACTIVE` contract
    of this athlete advances `QUEUED -> RELEASED`, processed in ascending payment-release
    `sequence_no`, each with all the release-time consequences of s3.9", with `released_at`
    "stamped from the logical clock".

    Design: Corner/state_machines/withdraw_from_portal_releases_queued_payment_release
    """
    collective = build_collective(
        api,
        "022200",
        name="Queued Collective",
        institution_name="Queued Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T3", 100000, 3)
    donor = build_donor(
        api, collective["id"], tier["id"], display_name="Que Donor", email="que@example.com"
    )
    contribution = build_settled_contribution(
        api, donor["id"], 500000, designation="UNRESTRICTED"
    )
    assert_contribution_money(
        contribution, processing_fee_cents=12530, net_amount_cents=487470
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-que",
        full_name="Que Athlete",
        sport="MENS_BASKETBALL",
        class_year=2029,
    )
    record_taxpayer_doc(api, athlete["id"], "W9")

    contract = build_draft_contract(
        api, collective["id"], athlete["id"], 200000, funding_designation="UNRESTRICTED"
    )
    clear_disclosure(
        api,
        contract["id"],
        state_law_citation="TX-51.9246",
        association_rule_citation="NCAA-2024-12.5",
    )
    activate_contract(api, contract["id"])

    read_data(
        api.change_athlete_eligibility(
            athlete["id"], eligibility_change_payload("ENTER_PORTAL"), make_compliance_headers()
        )
    )
    contract_version = read_contract(api, contract["id"])["version"]
    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                80000,
                expected_deal_contract_version=contract_version,
            ),
            make_treasury_headers("treasury-c"),
        ),
        expected_status=201,
    )
    assert_release_money(release, status="QUEUED", initiated_by_user_id="treasury-c")
    assert release["released_at"] is None

    move_clock(api, "2026-08-20T00:00:00Z")
    withdrawn = read_data(
        api.change_athlete_eligibility(
            athlete["id"],
            eligibility_change_payload("WITHDRAW_FROM_PORTAL"),
            make_compliance_headers(),
        )
    )
    assert withdrawn["eligibility_status"] == "ENROLLED"

    settled_release = read_release(api, release["id"])
    assert_release_money(settled_release, status="RELEASED", net_payable_cents=80000)
    assert_timestamp_equals(settled_release["released_at"], "2026-08-20T00:00:00Z")

    contract_now = read_contract(api, contract["id"])
    assert_contract_money(contract_now, released_total_cents=80000)
    assert_contract_dimensions(contract_now, payment_status="PARTIALLY_PAID")
    assert_collective_ledger(
        read_collective(api, collective["id"]), released_total_cents=80000
    )
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]),
        tax_year_gross_paid_cents=80000,
        tax_form_required="FORM_1099_NEC",
    )


def test_termination_forfeits_the_open_deliverable_and_spares_the_verified_one(api):
    """The forfeit cascade is conditional on each child's own status.

    PRD s3.8: "every deliverable of the contract whose `status` is `PENDING`, `SUBMITTED` or
    `REJECTED` becomes `FORFEITED` with `payout_eligible_cents` set to 0 in ascending
    deliverable `sequence_no`, and the contract's `deliverable_value_total_cents` is
    re-derived with those forfeited rows excluded", while "`VERIFIED`, `WAIVED` and
    `FORFEITED` are the terminal deliverable positions" (s3.9). PRD s3.8 also states that
    "If the `termination_reason` is `MUTUAL_RELEASE`, the `clawback_amount_cents` is 0
    outright".

    Design: Corner/state_machines/termination_forfeits_only_non_terminal_deliverables
    """
    collective = build_collective(
        api,
        "022300",
        name="Conditional Collective",
        institution_name="Conditional Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T3", 100000, 3)
    donor = build_donor(
        api, collective["id"], tier["id"], display_name="Cond Donor", email="cond@example.com"
    )
    assert_contribution_money(
        build_settled_contribution(api, donor["id"], 500000, designation="UNRESTRICTED"),
        net_amount_cents=487470,
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-cond",
        full_name="Cond Athlete",
        sport="FOOTBALL",
        class_year=2028,
    )
    contract = build_draft_contract(
        api, collective["id"], athlete["id"], 200000, funding_designation="UNRESTRICTED"
    )
    clear_disclosure(api, contract["id"])
    activate_contract(api, contract["id"])

    to_verify = read_data(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("SOCIAL_POST", 120000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    left_pending = read_data(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("APPEARANCE", 80000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    add_evidence(api, to_verify["id"], "ANALYTICS_SCREENSHOT", "cond-post")
    submit_work(api, to_verify["id"], "2026-08-05T00:00:00Z")
    review_work(api, to_verify["id"], "VERIFY", "compliance-c")

    before = read_contract(api, contract["id"])
    assert_contract_money(before, deliverable_value_total_cents=200000)

    terminated = read_data(
        api.terminate_deal_contract(
            contract["id"], termination_payload("MUTUAL_RELEASE"), make_compliance_headers()
        )
    )
    assert_contract_dimensions(
        terminated, lifecycle_status="TERMINATED", payment_status="UNPAID"
    )
    assert_contract_money(
        terminated,
        deliverable_value_total_cents=120000,
        clawback_amount_cents=0,
        termination_reason="MUTUAL_RELEASE",
    )

    assert_deliverable_scoring(
        read_deliverable(api, left_pending["id"]),
        status="FORFEITED",
        payout_eligible_cents=0,
    )
    assert_deliverable_scoring(
        read_deliverable(api, to_verify["id"]),
        status="VERIFIED",
        payout_eligible_cents=120000,
    )
    assert_collective_ledger(
        read_collective(api, collective["id"]), committed_unreleased_cents=0
    )
