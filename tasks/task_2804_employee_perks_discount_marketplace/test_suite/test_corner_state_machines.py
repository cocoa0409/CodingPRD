"""Corner tests for the state machines of the Employee Perks & Discount
Marketplace API: initial states, declared transitions, the invalid-state
refusals of PRD §2.9 band 5, terminal-state lockdown, sweep idempotency,
guarded transitions and the cascades that hang off a single transition.

Every test builds its own world: the harness restarts the server before each
test, so the database is empty and the logical clock reads its documented
default of 2026-08-01T00:00:00Z (PRD §2.4).
"""
from prd_bench_local_runner.testing import (
    validate_error, validate_paginated, validate_success,
)

from test_helpers import (
    ApiErrorId, api_client, assertions, constants as C, factories as F,
    fixtures, make_admin_headers, make_employee_headers,
    make_employer_admin_headers, make_merchant_headers,
    make_partner_manager_headers,
)
from test_helpers.types import (
    AgreementStatus, DisputeReason, DisputeStatus,
    EligibilityFileStatus, EmploymentStatus, IntegrationStatus, LedgerEntryType,
    MembershipStatus, MerchantStatus, OfferStatus, PerkCategory, PlacementTier,
    ProgramPosture, ProposerRole, RegionCode, ReviewDecision, SlotStatus,
    StatementBasis, StatementStatus, StorefrontStatus, VerificationStatus,
    VoidReason,
)


def _memberships_in_records_order(employer_id):
    """That employer's memberships, ordered `created_at` ASC (PRD §3.3)."""
    return fixtures.list_memberships(employer_id)


def test_eligibility_batch_is_created_in_received_with_its_tallies_computed():
    """A freshly loaded batch lands in RECEIVED with its three record tallies already computed and nothing applied.

    PRD: "The batch itself is created in `RECEIVED` with its `employer_id` set, with `rejection_reason` and `applied_at` null, with `created_membership_count`, `updated_membership_count` and `suspended_membership_count` all 0, and with its three record tallies computed immediately."

    Design: Corner/state_machines/eligibility_file_starts_in_received_with_computed_record_counts
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    employer = fixtures.create_employer(
        name="Northwind Co", region_code=RegionCode.CA,
        employee_count_declared=3, revenue_share_enabled=True,
        privacy_min_cohort_size=3,
    )
    records = [
        F.eligibility_record("E-001"),
        F.eligibility_record("E-002", employment_status=EmploymentStatus.LEAVE),
        # Outside {CA, TX, NY, WA, IL}: an invalid record, not a rejected batch.
        F.eligibility_record("E-003", region_code="ZZ"),
    ]
    batch = validate_success(
        api_client.create_eligibility_file(
            employer["id"],
            F.eligibility_file_payload(
                employer["version"], records=records,
                effective_from=C.DEFAULT_CLOCK, checksum="sha-initial-1",
            ),
            make_employer_admin_headers(employer["id"]),
        ),
        expected_status=201,
    )
    assertions.assert_eligibility_file_shape(batch)
    assertions.assert_fields(batch, {
        "employer_id": employer["id"],
        "status": EligibilityFileStatus.RECEIVED.value,
        "checksum": "sha-initial-1",
        "record_count": 3,
        "invalid_record_count": 1,
        "valid_record_count": 2,
        "created_membership_count": 0,
        "updated_membership_count": 0,
        "suspended_membership_count": 0,
    }, "eligibility file")
    assertions.assert_nulls(batch, ("applied_at", "rejection_reason"), "eligibility file")

    employer_after = validate_success(
        api_client.get_employer(employer["id"], make_admin_headers())
    )
    assertions.assert_fields(employer_after, {
        "integration_status": IntegrationStatus.FILE_RECEIVED.value,
        "storefront_status": StorefrontStatus.DRAFT.value,
        "program_posture": ProgramPosture.SETUP.value,
        "eligible_headcount": 0,
    }, "employer")

    rows, meta = validate_paginated(api_client.list_memberships(
        make_employer_admin_headers(employer["id"]),
        params={"employer_id": employer["id"]},
    ))
    assert meta["total_count"] == 0, "loading a batch must not create memberships"
    assert rows == []


def test_first_provider_proposal_opens_round_one_and_lifts_the_partner_into_negotiation():
    """One propose call moves the agreement DRAFT to PROVIDER_PROPOSED, writes round 1 as PARTNER_MANAGER and drags the partner to IN_NEGOTIATION.

    PRD: "Each accepted proposal writes a new round whose `agreement_id` points at the agreement, whose `round_number` is the previous highest round number plus one — the first round is numbered 1 — and whose `proposer_role` is recorded as `PARTNER_MANAGER`."

    Design: Corner/state_machines/first_proposal_moves_agreement_to_provider_proposed_and_merchant_to_in_negotiation
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant(
        legal_name="Bistro Uno", contact_email="ops@bistrouno.example",
        primary_category=PerkCategory.DINING, region_codes=[RegionCode.CA],
    )
    agreement = fixtures.create_agreement(
        merchant["id"], category=PerkCategory.DINING, region_code=RegionCode.CA,
    )
    assertions.assert_fields(agreement, {
        "status": AgreementStatus.DRAFT.value, "round_count": 0,
    }, "agreement")

    # PRD §4 does not pin `/propose`'s success status: the call both appends a
    # round and drives the agreement `DRAFT → PROVIDER_PROPOSED` (§3.1), so
    # "resource creation returns 201" and "action endpoints that drive a state
    # transition return 200" both reach it.  The rule this test is about — round
    # 1, `PARTNER_MANAGER`, and the partner lift — is asserted from the GET
    # endpoints below, which PRD does pin.
    validate_success(
        api_client.propose_round(
            agreement["id"],
            F.round_payload(
                agreement["version"], commission_rate_bps=1200,
                placement_fee_base_cents=36000, employer_revenue_share_bps=2500,
                note="opening terms",
            ),
            make_partner_manager_headers(),
        )
    )

    agreement_after = validate_success(
        api_client.get_agreement(agreement["id"], make_partner_manager_headers())
    )
    assertions.assert_agreement_shape(agreement_after)
    assertions.assert_fields(agreement_after, {
        "status": AgreementStatus.PROVIDER_PROPOSED.value,
        "round_count": 1,
        "commission_rate_bps": 1200,
        "placement_fee_base_cents": 36000,
        "employer_revenue_share_bps": 2500,
    }, "agreement")
    assertions.assert_version_is(agreement_after, agreement["version"] + 1, "agreement")
    assertions.assert_nulls(
        agreement_after,
        ("accepted_by_role", "activated_at", "terminated_reason"), "agreement",
    )

    merchant_after = validate_success(
        api_client.get_merchant(merchant["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(merchant_after, {
        "status": MerchantStatus.IN_NEGOTIATION.value,
        "active_agreement_count": 0,
    }, "merchant")

    rounds, meta = validate_paginated(api_client.list_negotiation_rounds(
        agreement["id"], make_partner_manager_headers()
    ))
    assert meta["total_count"] == 1, "exactly one round should exist"
    assertions.assert_negotiation_round_shape(rounds[0])
    assertions.assert_fields(rounds[0], {
        "agreement_id": agreement["id"],
        "round_number": 1,
        "proposer_role": ProposerRole.PARTNER_MANAGER.value,
        "commission_rate_bps": 1200,
        "placement_fee_base_cents": 36000,
        "employer_revenue_share_bps": 2500,
        "note": "opening terms",
    }, "negotiation round")


def test_activation_without_negotiated_exclusivity_windows_is_refused():
    """Exclusivity activation needs both windows on the standing round; without them the agreement stays ACCEPTED and ungranted.

    PRD: "The terms-completeness check then verifies that the standing round actually negotiated an exclusivity window at all: if either `exclusivity_window_start` or `exclusivity_window_end` on the standing terms is null, activation is refused with `ERR_EXCLUSIVITY_TERMS_MISSING`."

    Design: Corner/state_machines/exclusivity_activation_requires_negotiated_windows_on_the_standing_round
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant_a = fixtures.create_merchant(
        legal_name="Bistro Uno", contact_email="ops@bistrouno.example",
    )
    merchant_b = fixtures.create_merchant(
        legal_name="Cafe Duo", contact_email="ops@cafeduo.example",
    )

    agreement_a = fixtures.create_agreement(
        merchant_a["id"], category=PerkCategory.DINING,
        region_code=RegionCode.CA, exclusivity_requested=True,
    )
    fixtures.propose_round(agreement_a)          # no exclusivity window at all
    fixtures.accept_agreement(agreement_a["id"], merchant_a["id"])

    agreement_b = fixtures.create_agreement(
        merchant_b["id"], category=PerkCategory.DINING,
        region_code=RegionCode.CA, exclusivity_requested=True,
    )
    fixtures.propose_round(
        agreement_b,
        exclusivity_window_start="2026-09-01T00:00:00Z",
        exclusivity_window_end="2026-10-01T00:00:00Z",
    )
    fixtures.accept_agreement(agreement_b["id"], merchant_b["id"])

    validate_error(
        api_client.activate_agreement(agreement_a["id"], make_partner_manager_headers()),
        ApiErrorId.EXCLUSIVITY_TERMS_MISSING,
    )
    refused = validate_success(
        api_client.get_agreement(agreement_a["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(refused, {
        "status": AgreementStatus.ACCEPTED.value,
        "exclusivity_requested": True,
        "exclusivity_granted": False,
    }, "agreement A")
    assertions.assert_nulls(
        refused,
        ("activated_at", "exclusivity_window_start", "exclusivity_window_end"),
        "agreement A",
    )

    activated = validate_success(
        api_client.activate_agreement(agreement_b["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(activated, {
        "status": AgreementStatus.ACTIVE.value,
        "exclusivity_requested": True,
        "exclusivity_granted": True,
    }, "agreement B")
    assertions.assert_iso_equals(
        activated["exclusivity_window_start"], "2026-09-01T00:00:00Z",
        "agreement B.exclusivity_window_start",
    )
    assertions.assert_iso_equals(
        activated["exclusivity_window_end"], "2026-10-01T00:00:00Z",
        "agreement B.exclusivity_window_end",
    )
    assertions.assert_iso_equals(
        activated["activated_at"], C.DEFAULT_CLOCK, "agreement B.activated_at",
    )

    partner_a = validate_success(
        api_client.get_merchant(merchant_a["id"], make_partner_manager_headers())
    )
    partner_b = validate_success(
        api_client.get_merchant(merchant_b["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(
        partner_a, {"status": MerchantStatus.IN_NEGOTIATION.value}, "partner A",
    )
    assertions.assert_fields(
        partner_b, {"status": MerchantStatus.ACTIVE.value,
                    "active_agreement_count": 1}, "partner B",
    )


def test_setup_stage_triggers_from_a_wrong_state_return_each_entity_own_invalid_state_code():
    """Reinstating a PROSPECT partner, re-activating an ACTIVE agreement, publishing a DRAFT storefront and applying a RECEIVED batch each return that entity's own invalid-state code.

    PRD: "The target row is not in a state from which the requested transition is declared, using that entity's own invalid-state code: `ERR_MERCHANT_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_EMPLOYER_INVALID_STATE`, `ERR_FILE_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`, `ERR_SLOT_INVALID_STATE`, `ERR_REDEMPTION_INVALID_STATE`, `ERR_DISPUTE_INVALID_STATE` or `ERR_STATEMENT_INVALID_STATE`."

    Design: Corner/state_machines/setup_stage_triggers_from_wrong_state_return_each_entity_own_invalid_state_code
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    partner = fixtures.active_partner(merchant_overrides={"legal_name": "Bistro Uno"})
    agreement_before = fixtures.get_agreement(partner["agreement"]["id"])
    prospect = fixtures.create_merchant(
        legal_name="Cafe Duo", contact_email="ops@cafeduo.example",
    )
    employer = fixtures.create_employer(name="Northwind Co", employee_count_declared=1)
    batch = fixtures.load_eligibility_file(
        employer["id"], records=F.eligibility_records(1),
    )

    # PROSPECT is not SUSPENDED, so reinstatement is not a declared transition.
    validate_error(
        api_client.reinstate_merchant(prospect["id"], make_admin_headers()),
        ApiErrorId.MERCHANT_INVALID_STATE,
    )
    # Activation is declared only ACCEPTED → ACTIVE.
    validate_error(
        api_client.activate_agreement(
            agreement_before["id"], make_partner_manager_headers()
        ),
        ApiErrorId.AGREEMENT_INVALID_STATE,
    )
    # Publishing is declared only BRANDED → PUBLISHED.
    validate_error(
        api_client.publish_storefront(
            employer["id"], make_employer_admin_headers(employer["id"])
        ),
        ApiErrorId.EMPLOYER_INVALID_STATE,
    )
    # Application is declared only VALIDATED → APPLIED.
    validate_error(
        api_client.apply_eligibility_file(
            batch["id"], make_employer_admin_headers(employer["id"])
        ),
        ApiErrorId.FILE_INVALID_STATE,
    )

    prospect_after = validate_success(
        api_client.get_merchant(prospect["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(
        prospect_after, {"status": MerchantStatus.PROSPECT.value}, "prospect merchant",
    )
    assertions.assert_nulls(prospect_after, ("suspended_at",), "prospect merchant")

    agreement_after = validate_success(
        api_client.get_agreement(agreement_before["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(
        agreement_after, {"status": AgreementStatus.ACTIVE.value}, "agreement",
    )
    assertions.assert_version_is(
        agreement_after, agreement_before["version"], "agreement",
    )

    employer_after = validate_success(
        api_client.get_employer(employer["id"], make_admin_headers())
    )
    assertions.assert_fields(employer_after, {
        "storefront_status": StorefrontStatus.DRAFT.value,
    }, "employer")

    batch_after = validate_success(
        api_client.get_eligibility_file(
            batch["id"], make_employer_admin_headers(employer["id"])
        )
    )
    assertions.assert_fields(batch_after, {
        "status": EligibilityFileStatus.RECEIVED.value,
        "created_membership_count": 0,
    }, "eligibility file")
    assertions.assert_nulls(batch_after, ("applied_at",), "eligibility file")

    _rows, meta = validate_paginated(api_client.list_memberships(
        make_employer_admin_headers(employer["id"]),
        params={"employer_id": employer["id"]},
    ))
    assert meta["total_count"] == 0, "a refused apply must not create memberships"


def test_offer_slot_and_statement_triggers_from_a_wrong_state_return_their_own_invalid_state_code():
    """Submitting an ACTIVE offer, confirming a CONFIRMED slot and paying a DRAFT statement each return that entity's own invalid-state code and change nothing.

    PRD: "The target row is not in a state from which the requested transition is declared, using that entity's own invalid-state code: `ERR_MERCHANT_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_EMPLOYER_INVALID_STATE`, `ERR_FILE_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`, `ERR_SLOT_INVALID_STATE`, `ERR_REDEMPTION_INVALID_STATE`, `ERR_DISPUTE_INVALID_STATE` or `ERR_STATEMENT_INVALID_STATE`."

    Design: Corner/state_machines/offer_slot_and_statement_triggers_from_wrong_state_return_their_own_invalid_state_code
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    program = fixtures.live_program(record_count=1, placement_fee_base_cents=36000)
    merchant_id = program["merchant"]["id"]
    offer = program["offer"]

    slot = fixtures.reserve_slot(
        offer, program["employer"]["id"], merchant_id,
        placement_tier=PlacementTier.STANDARD,
        slot_window_start="2026-09-01T00:00:00Z",
        slot_window_end="2026-09-03T00:00:00Z",
    )
    confirmed = fixtures.confirm_slot(slot["id"])
    assertions.assert_placement_fee_breakdown(
        confirmed, slot_duration_days=2, base_fee_cents=72000,
        reach_surcharge_bps=0, reach_surcharge_cents=0, gross_fee_cents=72000,
        volume_discount_bps=0, volume_discount_cents=0, placement_fee_cents=72000,
    )
    statement = fixtures.create_statement(
        program["employer"]["id"], basis=StatementBasis.ACCRUAL,
    )
    assertions.assert_fields(
        statement, {"status": StatementStatus.DRAFT.value}, "statement",
    )

    validate_error(
        api_client.submit_offer(offer["id"], make_merchant_headers(merchant_id)),
        ApiErrorId.OFFER_INVALID_STATE,
    )
    validate_error(
        api_client.confirm_placement_slot(slot["id"], make_partner_manager_headers()),
        ApiErrorId.SLOT_INVALID_STATE,
    )
    validate_error(
        api_client.pay_statement(
            statement["id"], F.pay_payload(payment_reference="WIRE-2026-09-0001"),
            make_admin_headers(),
        ),
        ApiErrorId.STATEMENT_INVALID_STATE,
    )

    offer_after = validate_success(api_client.get_offer(offer["id"], make_admin_headers()))
    assertions.assert_fields(
        offer_after, {"status": OfferStatus.ACTIVE.value}, "offer",
    )

    slot_after = validate_success(
        api_client.get_placement_slot(slot["id"], make_admin_headers())
    )
    assertions.assert_fields(
        slot_after, {"status": SlotStatus.CONFIRMED.value}, "placement slot",
    )
    assertions.assert_version_is(slot_after, confirmed["version"], "placement slot")
    assertions.assert_nulls(
        slot_after, ("released_at", "release_reason"), "placement slot",
    )

    statement_after = validate_success(
        api_client.get_statement(statement["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(
        statement_after, {"status": StatementStatus.DRAFT.value}, "statement",
    )
    assertions.assert_nulls(
        statement_after, ("paid_at", "payment_reference"), "statement",
    )

    merchant_after = validate_success(
        api_client.get_merchant(merchant_id, make_partner_manager_headers())
    )
    assertions.assert_fields(merchant_after, {
        "accrued_commission_payable_cents": 72000,
    }, "merchant")


def test_redemption_and_dispute_triggers_from_a_wrong_state_return_their_own_invalid_state_code():
    """Voiding an already VOID redemption and requesting information on an OPEN dispute each return that entity's own invalid-state code.

    PRD: "The target row is not in a state from which the requested transition is declared, using that entity's own invalid-state code: `ERR_MERCHANT_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_EMPLOYER_INVALID_STATE`, `ERR_FILE_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`, `ERR_SLOT_INVALID_STATE`, `ERR_REDEMPTION_INVALID_STATE`, `ERR_DISPUTE_INVALID_STATE` or `ERR_STATEMENT_INVALID_STATE`."

    Design: Corner/state_machines/redemption_and_dispute_triggers_from_wrong_state_return_their_own_invalid_state_code
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    program = fixtures.live_program(
        record_count=1, offer_overrides={"inventory_limit": 5},
    )
    merchant_id = program["merchant"]["id"]
    offer_id = program["offer"]["id"]
    membership_id = program["memberships"][0]["id"]

    cancelled = fixtures.create_redemption(offer_id, membership_id)
    voided = fixtures.void_redemption(cancelled["id"], membership_id=membership_id)
    assertions.assert_fields(voided, {
        "verification_status": VerificationStatus.VOID.value,
        "void_reason": VoidReason.MEMBER_CANCELLED.value,
    }, "voided redemption")

    verified = fixtures.verified_redemption(
        offer_id, membership_id, merchant_id, gross_amount_cents=5000,
    )
    dispute = fixtures.file_dispute(
        verified["id"], membership_id, reason=DisputeReason.WRONG_DISCOUNT,
        description="The till charged the undiscounted price.",
    )
    assertions.assert_fields(dispute, {
        "status": DisputeStatus.OPEN.value, "info_request_count": 0,
    }, "dispute")

    validate_error(
        api_client.void_redemption(
            cancelled["id"], make_employee_headers(membership_id)
        ),
        ApiErrorId.REDEMPTION_INVALID_STATE,
    )
    validate_error(
        api_client.request_dispute_info(dispute["id"], make_admin_headers()),
        ApiErrorId.DISPUTE_INVALID_STATE,
    )

    redemption_after = validate_success(
        api_client.get_redemption(cancelled["id"], make_admin_headers())
    )
    assertions.assert_fields(redemption_after, {
        "verification_status": VerificationStatus.VOID.value,
        "void_reason": VoidReason.MEMBER_CANCELLED.value,
    }, "voided redemption")
    assertions.assert_version_is(redemption_after, voided["version"], "voided redemption")

    dispute_after = validate_success(
        api_client.get_dispute(dispute["id"], make_admin_headers())
    )
    assertions.assert_fields(dispute_after, {
        "status": DisputeStatus.OPEN.value, "info_request_count": 0,
    }, "dispute")
    assertions.assert_version_is(dispute_after, dispute["version"], "dispute")

    offer_after = validate_success(api_client.get_offer(offer_id, make_admin_headers()))
    assertions.assert_fields(offer_after, {
        "inventory_limit": 5, "inventory_reserved": 0, "inventory_redeemed": 1,
        "sold_out": False,
    }, "offer")


def test_revoked_membership_refuses_every_further_employment_status_write():
    """Once a termination has driven a membership to REVOKED, every later employment-status write is refused.

    PRD: "`REVOKED` is terminal: a further employment-status write against a revoked membership is refused with `ERR_MEMBERSHIP_REVOKED`, and rehiring an employee requires a fresh eligibility batch rather than a status flip."

    Design: Corner/state_machines/revoked_membership_rejects_every_further_employment_status_write
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    employer = fixtures.create_employer(name="Northwind Co", employee_count_declared=1)
    employer_id = employer["id"]
    fixtures.sync_eligibility(employer_id, records=[F.eligibility_record("E-001")])
    membership = _memberships_in_records_order(employer_id)[0]

    revoked = fixtures.set_employment_status(
        membership["id"], employer_id, EmploymentStatus.TERMINATED,
    )
    assertions.assert_membership_shape(revoked)
    assertions.assert_fields(revoked, {
        "status": MembershipStatus.REVOKED.value,
        "employment_status": EmploymentStatus.TERMINATED.value,
    }, "membership")

    validate_error(
        api_client.set_employment_status(
            membership["id"],
            F.employment_status_payload(EmploymentStatus.ACTIVE),
            make_employer_admin_headers(employer_id),
        ),
        ApiErrorId.MEMBERSHIP_REVOKED,
    )
    validate_error(
        api_client.set_employment_status(
            membership["id"],
            F.employment_status_payload(EmploymentStatus.TERMINATED),
            make_employer_admin_headers(employer_id),
        ),
        ApiErrorId.MEMBERSHIP_REVOKED,
    )

    final = validate_success(api_client.get_membership(
        membership["id"], make_employer_admin_headers(employer_id)
    ))
    assertions.assert_fields(final, {
        "status": MembershipStatus.REVOKED.value,
        "employment_status": EmploymentStatus.TERMINATED.value,
    }, "membership")
    assertions.assert_version_is(final, revoked["version"], "membership")

    employer_after = validate_success(
        api_client.get_employer(employer_id, make_admin_headers())
    )
    assertions.assert_fields(
        employer_after, {"eligible_headcount": 0}, "employer",
    )


def test_second_epoch_run_reports_all_zero_counts_after_the_first_expiry_sweep():
    """The offer-expiry pass fires once; re-running the sweep on the same clock reports zero in all five counters and mutates nothing.

    PRD: "The sweep is idempotent with respect to the clock: running it a second time without advancing the clock reports zero in all five counters."

    Design: Corner/state_machines/second_epoch_run_reports_all_zero_counts_after_the_first_expiry_sweep
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    partner = fixtures.active_partner()
    offer = fixtures.approved_offer(
        partner["agreement"]["id"], partner["merchant"]["id"],
        window_start=C.DEFAULT_CLOCK, window_end="2026-09-01T00:00:00Z",
    )
    assertions.assert_fields(offer, {"status": OfferStatus.ACTIVE.value}, "offer")

    fixtures.set_clock("2026-09-02T00:00:00Z")
    first = validate_success(api_client.run_epoch(make_admin_headers()))
    assertions.assert_sweep_counts(
        first, expired_offer_count=1, completed_slot_count=0,
        voided_redemption_count=0, stale_employer_count=0,
        default_judged_dispute_count=0,
    )
    after_first = validate_success(
        api_client.get_offer(offer["id"], make_admin_headers())
    )
    assertions.assert_fields(
        after_first, {"status": OfferStatus.EXPIRED.value}, "offer",
    )
    assertions.assert_iso_equals(
        after_first["expired_at"], "2026-09-02T00:00:00Z", "offer.expired_at",
    )

    second = validate_success(api_client.run_epoch(make_admin_headers()))
    assertions.assert_sweep_idle(second)
    after_second = validate_success(
        api_client.get_offer(offer["id"], make_admin_headers())
    )
    assertions.assert_fields(
        after_second, {"status": OfferStatus.EXPIRED.value}, "offer",
    )
    assertions.assert_iso_equals(
        after_second["expired_at"], "2026-09-02T00:00:00Z", "offer.expired_at",
    )
    assertions.assert_version_is(after_second, after_first["version"], "offer")


def test_offer_drafting_requires_the_agreement_to_be_active():
    """An offer cannot be drafted against a merely ACCEPTED agreement; once the agreement is ACTIVE the offer walks DRAFT to PENDING_REVIEW to ACTIVE.

    PRD: "Drafting also requires the referenced agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`) and the partner not to be `SUSPENDED` or `TERMINATED` (otherwise `ERR_MERCHANT_SUSPENDED`)."

    Design: Corner/state_machines/offer_work_is_guarded_by_the_agreement_being_active
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant(legal_name="Bistro Uno")
    merchant_id = merchant["id"]
    agreement = fixtures.create_agreement(
        merchant_id, category=PerkCategory.DINING, region_code=RegionCode.CA,
    )
    fixtures.propose_round(agreement)
    accepted = fixtures.accept_agreement(agreement["id"], merchant_id)
    assertions.assert_fields(
        accepted, {"status": AgreementStatus.ACCEPTED.value}, "agreement",
    )

    validate_error(
        api_client.create_offer(
            F.offer_payload(agreement["id"], title="Twenty percent off lunch"),
            make_merchant_headers(merchant_id),
        ),
        ApiErrorId.AGREEMENT_NOT_ACTIVE,
    )
    _rows, meta = validate_paginated(api_client.list_offers(
        make_merchant_headers(merchant_id),
        params={"agreement_id": agreement["id"]},
    ))
    assert meta["total_count"] == 0, "a refused draft must not leave an offer row"

    fixtures.activate_agreement(agreement["id"])
    drafted = validate_success(
        api_client.create_offer(
            F.offer_payload(agreement["id"], title="Twenty percent off lunch"),
            make_merchant_headers(merchant_id),
        ),
        expected_status=201,
    )
    assertions.assert_offer_shape(drafted)
    assertions.assert_fields(drafted, {
        "status": OfferStatus.DRAFT.value,
        "agreement_id": agreement["id"],
        "merchant_id": merchant_id,
        "category": PerkCategory.DINING.value,
    }, "offer")

    submitted = validate_success(
        api_client.submit_offer(drafted["id"], make_merchant_headers(merchant_id))
    )
    assertions.assert_fields(
        submitted, {"status": OfferStatus.PENDING_REVIEW.value}, "offer",
    )

    approved = validate_success(api_client.review_offer(
        drafted["id"],
        F.review_payload(ReviewDecision.APPROVE, review_note="Looks good."),
        make_admin_headers(),
    ))
    assertions.assert_fields(approved, {
        "status": OfferStatus.ACTIVE.value, "review_note": "Looks good.",
    }, "offer")


def test_storefront_suspension_voids_only_pending_redemptions_and_frees_their_inventory():
    """Suspending a PUBLISHED storefront freezes the posture, voids exactly the PENDING redemptions with PROGRAM_FROZEN and hands their inventory back.

    PRD: "Because the recomputed posture becomes `FROZEN`, every redemption of that employer whose `verification_status` is `PENDING` moves to `VOID` with `void_reason` set to `PROGRAM_FROZEN` and `voided_at` taken from the logical clock; each voided redemption drops out of its offer's reserved count, lowering that offer's `inventory_reserved` by 1 and forcing a recomputation of the offer's `sold_out` flag."

    Design: Corner/state_machines/storefront_suspension_voids_only_pending_redemptions_and_frees_their_inventory
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    program = fixtures.live_program(
        record_count=3, offer_overrides={"inventory_limit": 3},
    )
    employer_id = program["employer"]["id"]
    merchant_id = program["merchant"]["id"]
    offer_id = program["offer"]["id"]
    members = program["memberships"]
    assert len(members) == 3, "the roster should hold three memberships"

    pending_one = fixtures.create_redemption(offer_id, members[0]["id"])
    pending_two = fixtures.create_redemption(offer_id, members[1]["id"])
    verified = fixtures.verified_redemption(
        offer_id, members[2]["id"], merchant_id, gross_amount_cents=5000,
    )
    assertions.assert_fields(verified, {
        "verification_status": VerificationStatus.VERIFIED.value,
    }, "verified redemption")

    offer_before = validate_success(api_client.get_offer(offer_id, make_admin_headers()))
    assertions.assert_fields(offer_before, {
        "inventory_limit": 3, "inventory_reserved": 2, "inventory_redeemed": 1,
        "sold_out": True,
    }, "offer before suspension")

    frozen = validate_success(api_client.suspend_storefront(
        employer_id,
        F.storefront_suspend_payload(suspension_reason="COMPLIANCE_AUDIT"),
        make_admin_headers(),
    ))
    assertions.assert_employer_shape(frozen)
    assertions.assert_fields(frozen, {
        "storefront_status": StorefrontStatus.SUSPENDED.value,
        "program_posture": ProgramPosture.FROZEN.value,
        "suspension_reason": "COMPLIANCE_AUDIT",
        "integration_status": IntegrationStatus.SYNCED.value,
    }, "employer")

    for label, reserved in (("first", pending_one), ("second", pending_two)):
        voided = validate_success(
            api_client.get_redemption(reserved["id"], make_admin_headers())
        )
        assertions.assert_fields(voided, {
            "verification_status": VerificationStatus.VOID.value,
            "void_reason": VoidReason.PROGRAM_FROZEN.value,
        }, f"{label} pending redemption")
        assertions.assert_iso_equals(
            voided["voided_at"], C.DEFAULT_CLOCK,
            f"{label} pending redemption.voided_at",
        )

    verified_after = validate_success(
        api_client.get_redemption(verified["id"], make_admin_headers())
    )
    assertions.assert_fields(verified_after, {
        "verification_status": VerificationStatus.VERIFIED.value,
    }, "verified redemption")
    assertions.assert_nulls(
        verified_after, ("voided_at", "void_reason"), "verified redemption",
    )

    offer_after = validate_success(api_client.get_offer(offer_id, make_admin_headers()))
    assertions.assert_fields(offer_after, {
        "inventory_limit": 3, "inventory_reserved": 0, "inventory_redeemed": 1,
        "sold_out": False,
    }, "offer after suspension")

    validate_error(
        api_client.create_redemption(
            F.redemption_payload(offer_id, members[0]["id"]),
            make_employee_headers(members[0]["id"]),
        ),
        ApiErrorId.PROGRAM_FROZEN,
    )


def test_slot_confirm_and_release_keep_the_merchant_payable_reconciled():
    """Confirming then releasing a slot writes a placement fee and its exact negative, so the payable returns to zero and the slot's ledger nets out.

    PRD: "Releasing a slot that was `CONFIRMED` additionally writes a compensating placement-fee refund entry to the ledger for the negative of `placement_fee_cents` and lowers the partner's `accrued_commission_payable_cents` by that amount, so the slot's total ledger contribution nets to zero."

    Design: Corner/state_machines/slot_confirm_and_release_keep_the_merchant_payable_reconciled
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    program = fixtures.live_program(record_count=1, placement_fee_base_cents=36000)
    merchant_id = program["merchant"]["id"]
    assertions.assert_fields(program["merchant"], {
        "accrued_commission_payable_cents": 0,
    }, "merchant before confirmation")

    slot = fixtures.reserve_slot(
        program["offer"], program["employer"]["id"], merchant_id,
        placement_tier=PlacementTier.STANDARD,
        slot_window_start="2026-09-01T00:00:00Z",
        slot_window_end="2026-09-03T00:00:00Z",
    )
    assertions.assert_placement_slot_shape(slot)
    assertions.assert_placement_fee_breakdown(
        slot, slot_duration_days=2, base_fee_cents=72000,
        reach_surcharge_bps=0, reach_surcharge_cents=0, gross_fee_cents=72000,
        volume_discount_bps=0, volume_discount_cents=0, placement_fee_cents=72000,
    )
    assertions.assert_fields(
        slot, {"status": SlotStatus.RESERVED.value}, "placement slot",
    )

    confirmed = validate_success(
        api_client.confirm_placement_slot(slot["id"], make_partner_manager_headers())
    )
    assertions.assert_fields(
        confirmed, {"status": SlotStatus.CONFIRMED.value}, "placement slot",
    )
    assertions.assert_iso_equals(
        confirmed["confirmed_at"], C.DEFAULT_CLOCK, "placement slot.confirmed_at",
    )
    merchant_mid = validate_success(
        api_client.get_merchant(merchant_id, make_partner_manager_headers())
    )
    assertions.assert_fields(merchant_mid, {
        "accrued_commission_payable_cents": 72000,
    }, "merchant after confirmation")

    released = validate_success(api_client.release_placement_slot(
        slot["id"], F.release_payload(release_reason="CAMPAIGN_CANCELLED"),
        make_merchant_headers(merchant_id),
    ))
    assertions.assert_fields(released, {
        "status": SlotStatus.RELEASED.value,
        "release_reason": "CAMPAIGN_CANCELLED",
        "placement_fee_cents": 72000,
    }, "placement slot")
    assertions.assert_iso_equals(
        released["released_at"], C.DEFAULT_CLOCK, "placement slot.released_at",
    )

    merchant_after = validate_success(
        api_client.get_merchant(merchant_id, make_partner_manager_headers())
    )
    assertions.assert_fields(merchant_after, {
        "accrued_commission_payable_cents": 0,
    }, "merchant after release")

    entries, meta = validate_paginated(api_client.list_ledger_entries(
        make_admin_headers(),
        params={"placement_slot_id": slot["id"], "limit": C.MAX_PAGE_LIMIT},
    ))
    assertions.assert_pagination_meta(meta, total_count=2)
    for entry in entries:
        assertions.assert_ledger_entry_shape(entry)
        assertions.assert_fields(entry, {
            "merchant_id": merchant_id, "placement_slot_id": slot["id"],
        }, "ledger entry")
    assertions.assert_ledger_signature(entries, [
        (LedgerEntryType.PLACEMENT_FEE.value, 72000),
        (LedgerEntryType.PLACEMENT_FEE_REFUND.value, -72000),
    ])
    assertions.assert_ledger_nets_to_zero(entries)


def test_eligibility_apply_writes_its_three_membership_counts_and_suspends_the_omitted_reference():
    """Successive applies report created, updated and suspended separately: an omitted reference is suspended, and its reappearance is an update that restores it.

    PRD: "Application then stamps the batch `VALIDATED → APPLIED` with `applied_at` from the logical clock and fills in `created_membership_count`, `updated_membership_count` and `suspended_membership_count`, sets the employer's `last_sync_at` to the logical clock, recomputes `eligible_headcount` and `program_posture`, drives the integration dimension `VALIDATED → SYNCED`, and increments both the employer's and the batch's `version`."

    Design: Corner/state_machines/eligibility_apply_writes_its_three_membership_counts_and_suspends_the_omitted_reference
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    employer = fixtures.create_employer(name="Northwind Co", employee_count_declared=2)
    employer_id = employer["id"]
    fixtures.brand_storefront(employer_id)
    fixtures.publish_storefront(employer_id)

    batch_one = fixtures.sync_eligibility(employer_id, records=[
        F.eligibility_record("E-001"), F.eligibility_record("E-002"),
    ])
    assertions.assert_fields(batch_one, {
        "status": EligibilityFileStatus.APPLIED.value,
        "created_membership_count": 2,
        "updated_membership_count": 0,
        "suspended_membership_count": 0,
    }, "first batch")
    assertions.assert_iso_equals(
        batch_one["applied_at"], C.DEFAULT_CLOCK, "first batch.applied_at",
    )

    employer_after_one = validate_success(
        api_client.get_employer(employer_id, make_admin_headers())
    )
    assertions.assert_fields(employer_after_one, {
        "integration_status": IntegrationStatus.SYNCED.value,
        "storefront_status": StorefrontStatus.PUBLISHED.value,
        "program_posture": ProgramPosture.LIVE.value,
        "eligible_headcount": 2,
    }, "employer after the first apply")
    assertions.assert_iso_equals(
        employer_after_one["last_sync_at"], C.DEFAULT_CLOCK,
        "employer.last_sync_at after the first apply",
    )

    roster = _memberships_in_records_order(employer_id)
    assert [row["external_employee_ref"] for row in roster] == ["E-001", "E-002"], (
        "memberships should be created in the order the records were supplied"
    )
    first_membership, second_membership = roster
    for membership in roster:
        assertions.assert_membership_shape(membership)
        assertions.assert_fields(membership, {
            "employer_id": employer_id,
            "status": MembershipStatus.ELIGIBLE.value,
            "employment_status": EmploymentStatus.ACTIVE.value,
            "source_file_id": batch_one["id"],
        }, f"membership {membership['external_employee_ref']}")

    # A second batch that omits E-002 entirely.
    fixtures.set_clock("2026-08-05T00:00:00Z")
    batch_two = fixtures.sync_eligibility(employer_id, records=[
        F.eligibility_record("E-001", employment_status=EmploymentStatus.LEAVE),
    ])
    assertions.assert_fields(batch_two, {
        "status": EligibilityFileStatus.APPLIED.value,
        "created_membership_count": 0,
        "updated_membership_count": 1,
        "suspended_membership_count": 1,
    }, "second batch")

    kept = validate_success(api_client.get_membership(
        first_membership["id"], make_employer_admin_headers(employer_id)
    ))
    assertions.assert_fields(kept, {
        "status": MembershipStatus.ELIGIBLE.value,
        "employment_status": EmploymentStatus.LEAVE.value,
        "source_file_id": batch_two["id"],
    }, "membership E-001")

    omitted = validate_success(api_client.get_membership(
        second_membership["id"], make_employer_admin_headers(employer_id)
    ))
    assertions.assert_fields(omitted, {
        "status": MembershipStatus.SUSPENDED.value,
        "employment_status": EmploymentStatus.ACTIVE.value,
        "source_file_id": batch_one["id"],
    }, "membership E-002")

    employer_after_two = validate_success(
        api_client.get_employer(employer_id, make_admin_headers())
    )
    assertions.assert_fields(employer_after_two, {
        "integration_status": IntegrationStatus.SYNCED.value,
        "eligible_headcount": 1,
    }, "employer after the second apply")
    assertions.assert_iso_equals(
        employer_after_two["last_sync_at"], "2026-08-05T00:00:00Z",
        "employer.last_sync_at after the second apply",
    )

    # A third batch in which the omitted reference reappears: two updates.
    batch_three = fixtures.sync_eligibility(employer_id, records=[
        F.eligibility_record("E-001"),
        F.eligibility_record("E-002", region_code=RegionCode.TX),
    ])
    assertions.assert_fields(batch_three, {
        "status": EligibilityFileStatus.APPLIED.value,
        "created_membership_count": 0,
        "updated_membership_count": 2,
        "suspended_membership_count": 0,
    }, "third batch")

    restored = validate_success(api_client.get_membership(
        second_membership["id"], make_employer_admin_headers(employer_id)
    ))
    assertions.assert_fields(restored, {
        "status": MembershipStatus.ELIGIBLE.value,
        "employment_status": EmploymentStatus.ACTIVE.value,
        "region_code": RegionCode.TX.value,
        "source_file_id": batch_three["id"],
    }, "membership E-002 after reappearing")

    employer_after_three = validate_success(
        api_client.get_employer(employer_id, make_admin_headers())
    )
    assertions.assert_fields(employer_after_three, {
        "integration_status": IntegrationStatus.SYNCED.value,
        "eligible_headcount": 2,
    }, "employer after the third apply")


def test_agreement_termination_expires_only_the_non_terminal_offers():
    """Terminating an agreement expires its DRAFT, PENDING_REVIEW, ACTIVE and PAUSED offers and leaves an already REJECTED offer alone.

    PRD: "The agreement records the supplied `terminated_reason`, resets `exclusivity_granted` to false, and expires every offer it owns whose status is `DRAFT`, `PENDING_REVIEW`, `ACTIVE` or `PAUSED`, stamping each such offer's `expired_at` from the logical clock."

    Design: Corner/state_machines/agreement_termination_expires_only_the_non_terminal_offers
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    partner = fixtures.active_partner(merchant_overrides={"legal_name": "Bistro Uno"})
    agreement_id = partner["agreement"]["id"]
    merchant_id = partner["merchant"]["id"]

    active_offer = fixtures.approved_offer(
        agreement_id, merchant_id, title="Twenty percent off lunch",
    )
    paused_source = fixtures.approved_offer(
        agreement_id, merchant_id, title="Fifteen percent off brunch",
    )
    paused_offer = fixtures.pause_offer(
        paused_source["id"], merchant_id, paused_reason="Kitchen refurbishment",
    )
    draft_offer = fixtures.create_offer(
        agreement_id, merchant_id, title="Ten percent off dinner",
    )
    pending_offer = fixtures.create_offer(
        agreement_id, merchant_id, title="Five percent off breakfast",
    )
    fixtures.submit_offer(pending_offer["id"], merchant_id)
    rejected_source = fixtures.create_offer(
        agreement_id, merchant_id, title="Ninety percent off everything",
    )
    fixtures.submit_offer(rejected_source["id"], merchant_id)
    rejected_offer = fixtures.review_offer(
        rejected_source["id"], ReviewDecision.REJECT,
        review_note="The discount is implausible.",
    )
    assertions.assert_fields(
        paused_offer, {"status": OfferStatus.PAUSED.value}, "paused offer",
    )
    assertions.assert_fields(
        rejected_offer, {"status": OfferStatus.REJECTED.value}, "rejected offer",
    )

    fixtures.set_clock("2026-08-10T00:00:00Z")
    terminated = validate_success(api_client.terminate_agreement(
        agreement_id, F.terminate_payload(terminated_reason="PARTNER_EXIT"),
        make_partner_manager_headers(),
    ))
    assertions.assert_agreement_shape(terminated)
    assertions.assert_fields(terminated, {
        "status": AgreementStatus.TERMINATED.value,
        "terminated_reason": "PARTNER_EXIT",
        "exclusivity_granted": False,
    }, "agreement")

    for label, offer in (
        ("active", active_offer), ("paused", paused_offer),
        ("draft", draft_offer), ("pending review", pending_offer),
    ):
        expired = validate_success(
            api_client.get_offer(offer["id"], make_admin_headers())
        )
        assertions.assert_fields(
            expired, {"status": OfferStatus.EXPIRED.value}, f"{label} offer",
        )
        assertions.assert_iso_equals(
            expired["expired_at"], "2026-08-10T00:00:00Z",
            f"{label} offer.expired_at",
        )

    untouched = validate_success(
        api_client.get_offer(rejected_offer["id"], make_admin_headers())
    )
    assertions.assert_fields(
        untouched, {"status": OfferStatus.REJECTED.value}, "rejected offer",
    )
    assertions.assert_nulls(untouched, ("expired_at",), "rejected offer")

    merchant_after = validate_success(
        api_client.get_merchant(merchant_id, make_partner_manager_headers())
    )
    assertions.assert_fields(merchant_after, {
        "status": MerchantStatus.ACTIVE.value, "active_agreement_count": 0,
    }, "merchant")
