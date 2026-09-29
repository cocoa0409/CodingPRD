"""Corner cases for the RBAC bands of PRD §2.1/§2.9 and the version-echo layer of §2.7.

Every test in this module builds its own state through the API: the harness
relaunches the server before each test, so the database starts empty and the
logical clock starts at its documented default of 2026-08-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, validate_error, validate_paginated, validate_success,
)

from test_helpers import (
    ApiErrorId, api_client, assert_iso_equals, assert_merchant_shape,
    assert_pagination_meta, constants as C, factories as F,
    fixtures, make_admin_headers, make_employee_headers,
    make_employer_admin_headers, make_merchant_headers,
    make_partner_manager_headers, headers_without_identity,
)
from test_helpers.types import (
    AgreementStatus, DecisionValue, EligibilityFileStatus, IntegrationStatus,
    MerchantStatus, PlacementTier, ProgramPosture, ProposerRole, RegionCode,
    SlotStatus, StatementBasis, StatementStatus, StorefrontStatus, UserRole,
    VerificationStatus,
)

# ── Shared local setup ──────────────────────────────────────────────────────

_SLOT_ONE_START = "2026-09-01T00:00:00Z"
_SLOT_ONE_END = "2026-09-03T00:00:00Z"
_SLOT_TWO_START = "2026-09-10T00:00:00Z"
_SLOT_TWO_END = "2026-09-12T00:00:00Z"

# A 2-day run at 36,000 cents/day against an employer of 2 eligible heads:
# base 72,000; reach tier 0 bps (headcount <= 3); gross 72,000; volume tier
# 0 bps (gross < 100,000); fee 72,000 (PRD §3.6).
_TWO_DAY_SLOT_FEE_CENTS = 72000


def _live_program_with_pending_redemption(record_count=1):
    """An `ACTIVE` partner, a `LIVE` employer, one `ACTIVE` offer, one `PENDING` row."""
    program = fixtures.live_program(
        record_count=record_count,
        offer_overrides={"min_spend_cents": 1000},
    )
    program["redemption"] = fixtures.create_redemption(
        program["offer"]["id"], program["memberships"][0]["id"]
    )
    return program


# ── Band 1: missing identity (PRD §2.1, §2.9) ───────────────────────────────


def test_requests_with_an_empty_user_id_header_are_rejected_before_anything_else():
    """A complete payload and a plain collection read both fail on missing identity.

    PRD: "If `X-User-ID` is absent or empty, the request is rejected with `ERR_IDENTITY_REQUIRED`."

    Design: Corner/rbac/a_request_missing_x_user_id_header_returns_unauthenticated
    """
    anonymous = headers_without_identity(UserRole.PARTNER_MANAGER)

    write = api_client.create_merchant(F.merchant_payload(), anonymous)
    validate_error(write, ApiErrorId.IDENTITY_REQUIRED)

    read = api_client.list_merchants(
        anonymous, params={"limit": C.DEFAULT_PAGE_LIMIT, "offset": 0}
    )
    validate_error(read, ApiErrorId.IDENTITY_REQUIRED)

    # Nothing else about the request changed: supplying the header succeeds.
    accepted = api_client.create_merchant(
        F.merchant_payload(), make_partner_manager_headers()
    )
    merchant = validate_success(accepted, 201)
    assert_merchant_shape(merchant)
    assert is_valid_uuid(merchant["id"])
    assert merchant["status"] == MerchantStatus.PROSPECT.value


# ── Band 1: role-exclusive operations (PRD §2.1, §2.9) ──────────────────────


def test_employee_may_neither_verify_nor_fulfill_its_own_redemption():
    """The employee is refused on both merchant-only steps of its own redemption.

    PRD: "An `Employee` may neither verify nor fulfil its own redemption — only the merchant may — and may never write its own `employment_status`."

    Design: Corner/rbac/role_exclusive_writes_are_refused_to_every_other_role_unauthorized
    """
    program = _live_program_with_pending_redemption()
    merchant_id = program["merchant"]["id"]
    membership_id = program["memberships"][0]["id"]
    redemption = program["redemption"]
    verify_payload = F.verify_payload(redemption["verification_token"], 5000)

    refused = api_client.verify_redemption(
        redemption["id"], verify_payload, make_employee_headers(membership_id)
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED)

    # The identical call from the owning merchant crystallises the economics:
    # 5000 gross, 2000 bps discount -> 1000; net 4000; 1200 bps -> 480 commission.
    accepted = api_client.verify_redemption(
        redemption["id"], verify_payload, make_merchant_headers(merchant_id)
    )
    verified = validate_success(accepted)
    assert verified["verification_status"] == VerificationStatus.VERIFIED.value
    assert verified["commission_amount_cents"] == 480

    refused_fulfill = api_client.fulfill_redemption(
        redemption["id"], make_employee_headers(membership_id)
    )
    validate_error(refused_fulfill, ApiErrorId.UNAUTHORIZED)


def test_partner_manager_cannot_read_an_individual_redemption():
    """`GET /perks/redemptions/{id}` is not declared for the `PartnerManager` role.

    PRD: "If the declared role is not one of the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/role_exclusive_writes_are_refused_to_every_other_role_unauthorized
    """
    program = _live_program_with_pending_redemption()
    redemption_id = program["redemption"]["id"]

    refused = api_client.get_redemption(redemption_id, make_partner_manager_headers())
    validate_error(refused, ApiErrorId.UNAUTHORIZED)

    # A declared role reading its own row is unaffected.
    own = api_client.get_redemption(
        redemption_id, make_employee_headers(program["memberships"][0]["id"])
    )
    visible = validate_success(own)
    assert visible["verification_status"] == VerificationStatus.PENDING.value


def test_employer_admin_cannot_freeze_its_own_storefront():
    """Only the platform may suspend a published storefront.

    PRD: "An `EmployerAdmin` may not suspend its own storefront (only the platform may freeze a programme), may not create or verify redemptions, and may not read an individual redemption or dispute at all."

    Design: Corner/rbac/role_exclusive_writes_are_refused_to_every_other_role_unauthorized
    """
    program = fixtures.live_employer(record_count=1)
    employer_id = program["employer"]["id"]
    payload = F.storefront_suspend_payload(suspension_reason="PROGRAM_PAUSE")

    refused = api_client.suspend_storefront(
        employer_id, payload, make_employer_admin_headers(employer_id)
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED)

    accepted = api_client.suspend_storefront(employer_id, payload, make_admin_headers())
    employer = validate_success(accepted)
    assert employer["storefront_status"] == StorefrontStatus.SUSPENDED.value
    assert employer["program_posture"] == ProgramPosture.FROZEN.value


# ── Band 1: the two peer roles on a placement slot (PRD §2.1, §3.6) ─────────


def test_merchant_cannot_confirm_the_slot_it_reserved():
    """Reservation and billing are split, so confirmation is refused to the reserver.

    PRD: "A `Merchant` reserves a placement slot but cannot confirm it — confirmation belongs to the `PartnerManager`, so reservation and billing are split across two peer roles."

    Design: Corner/rbac/slot_confirmation_belongs_to_the_partner_manager_while_release_is_shared_unauthorized
    """
    program = fixtures.live_program(record_count=2)
    merchant_id = program["merchant"]["id"]

    slot = fixtures.reserve_slot(
        program["offer"], program["employer"]["id"], merchant_id,
        placement_tier=PlacementTier.STANDARD,
        slot_window_start=_SLOT_ONE_START, slot_window_end=_SLOT_ONE_END,
    )
    assert slot["status"] == SlotStatus.RESERVED.value
    assert slot["placement_fee_cents"] == _TWO_DAY_SLOT_FEE_CENTS

    refused = api_client.confirm_placement_slot(
        slot["id"], make_merchant_headers(merchant_id)
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED)

    accepted = api_client.confirm_placement_slot(
        slot["id"], make_partner_manager_headers()
    )
    confirmed = validate_success(accepted)
    assert confirmed["status"] == SlotStatus.CONFIRMED.value
    assert_iso_equals(confirmed["confirmed_at"], C.DEFAULT_CLOCK, "slot.confirmed_at")

    merchant = fixtures.get_merchant(merchant_id)
    assert merchant["accrued_commission_payable_cents"] == _TWO_DAY_SLOT_FEE_CENTS


def test_either_peer_role_may_release_a_placement_slot():
    """Release works from the partner manager and from the owning merchant alike.

    PRD: "Either the owning `Merchant` or a `PartnerManager` may release a slot, supplying a `release_reason` that is stored verbatim."

    Design: Corner/rbac/slot_confirmation_belongs_to_the_partner_manager_while_release_is_shared_unauthorized
    """
    program = fixtures.live_program(record_count=2)
    merchant_id = program["merchant"]["id"]
    employer_id = program["employer"]["id"]

    confirmed_slot = fixtures.reserve_slot(
        program["offer"], employer_id, merchant_id,
        placement_tier=PlacementTier.STANDARD,
        slot_window_start=_SLOT_ONE_START, slot_window_end=_SLOT_ONE_END,
    )
    fixtures.confirm_slot(confirmed_slot["id"])

    by_partner_manager = api_client.release_placement_slot(
        confirmed_slot["id"],
        F.release_payload(release_reason="EMPLOYER_REQUEST"),
        make_partner_manager_headers(),
    )
    released = validate_success(by_partner_manager)
    assert released["status"] == SlotStatus.RELEASED.value
    assert released["release_reason"] == "EMPLOYER_REQUEST"
    assert fixtures.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 0

    reserved_slot = fixtures.reserve_slot(
        fixtures.get_offer(program["offer"]["id"], merchant_id=merchant_id),
        employer_id, merchant_id,
        placement_tier=PlacementTier.STANDARD,
        slot_window_start=_SLOT_TWO_START, slot_window_end=_SLOT_TWO_END,
    )
    assert reserved_slot["status"] == SlotStatus.RESERVED.value

    by_merchant = api_client.release_placement_slot(
        reserved_slot["id"],
        F.release_payload(release_reason="MERCHANT_WITHDRAWN"),
        make_merchant_headers(merchant_id),
    )
    merchant_released = validate_success(by_merchant)
    assert merchant_released["status"] == SlotStatus.RELEASED.value
    assert merchant_released["release_reason"] == "MERCHANT_WITHDRAWN"
    assert fixtures.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 0

    # Releasing a merely RESERVED slot bills and refunds nothing.
    entries = api_client.list_ledger_entries(
        make_partner_manager_headers(),
        params={"placement_slot_id": reserved_slot["id"],
                "limit": C.DEFAULT_PAGE_LIMIT, "offset": 0},
    )
    rows, meta = validate_paginated(entries)
    assert rows == []
    assert_pagination_meta(meta, total_count=0)


# ── Band 1: cross-tenant scope isolation (PRD §2.1, §2.9) ───────────────────


def test_merchant_cannot_reach_another_partners_redemption_or_offer():
    """A second partner carries the right role but the wrong merchant id.

    PRD: "When a role is authorised for an endpoint but the targeted row belongs to a different principal under these rules, the rejection is `ERR_SCOPE_VIOLATION`, not `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/an_actor_cannot_reach_a_peer_tenants_rows_scope_violation
    """
    program = _live_program_with_pending_redemption()
    merchant_a = program["merchant"]["id"]
    merchant_b = fixtures.create_merchant(
        legal_name="Cafe Duo", contact_email="ops@cafeduo.example",
        region_codes=[RegionCode.TX],
    )["id"]
    redemption = program["redemption"]
    verify_payload = F.verify_payload(redemption["verification_token"], 5000)

    foreign_verify = api_client.verify_redemption(
        redemption["id"], verify_payload, make_merchant_headers(merchant_b)
    )
    validate_error(foreign_verify, ApiErrorId.SCOPE_VIOLATION)

    foreign_read = api_client.get_redemption(
        redemption["id"], make_merchant_headers(merchant_b)
    )
    validate_error(foreign_read, ApiErrorId.SCOPE_VIOLATION)

    foreign_pause = api_client.pause_offer(
        program["offer"]["id"], F.pause_payload(paused_reason="STOCK_OUTAGE"),
        make_merchant_headers(merchant_b),
    )
    validate_error(foreign_pause, ApiErrorId.SCOPE_VIOLATION)

    owning = api_client.verify_redemption(
        redemption["id"], verify_payload, make_merchant_headers(merchant_a)
    )
    verified = validate_success(owning)
    assert verified["verification_status"] == VerificationStatus.VERIFIED.value
    assert verified["merchant_id"] == merchant_a


def test_employee_cannot_read_a_coworkers_redemption():
    """Employee scope is matched on the acting membership id, not on the employer.

    PRD: "When a role is authorised for an endpoint but the targeted row belongs to a different principal under these rules, the rejection is `ERR_SCOPE_VIOLATION`, not `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/an_actor_cannot_reach_a_peer_tenants_rows_scope_violation
    """
    program = _live_program_with_pending_redemption(record_count=2)
    member_one = program["memberships"][0]["id"]
    member_two = program["memberships"][1]["id"]
    redemption_id = program["redemption"]["id"]

    coworker = api_client.get_redemption(
        redemption_id, make_employee_headers(member_two)
    )
    validate_error(coworker, ApiErrorId.SCOPE_VIOLATION)

    own = api_client.get_redemption(redemption_id, make_employee_headers(member_one))
    visible = validate_success(own)
    assert visible["verification_status"] == VerificationStatus.PENDING.value
    assert visible["membership_id"] == member_one


# ── Band 1: segregation of duties on settlement (PRD §3.9) ──────────────────


def test_statement_finalize_and_pay_are_refused_to_each_others_role():
    """The platform may pay but never finalize, and the partner manager the reverse.

    PRD: "Finalizing is the `PartnerManager`'s act — the `PlatformAdmin` who may pay a statement may never finalize one, and the reverse."

    Design: Corner/rbac/statement_finalize_and_pay_cannot_be_performed_by_the_same_role
    """
    program = fixtures.live_program(record_count=1)
    fixtures.set_clock("2026-08-10T00:00:00Z")
    verified = fixtures.verified_redemption(
        program["offer"]["id"], program["memberships"][0]["id"],
        program["merchant"]["id"],
    )
    assert verified["employer_share_cents"] == 120
    fixtures.set_clock("2026-09-02T00:00:00Z")

    statement = fixtures.create_statement(
        program["employer"]["id"],
        period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
        basis=StatementBasis.ACCRUAL,
    )
    assert statement["status"] == StatementStatus.DRAFT.value

    refused_finalize = api_client.finalize_statement(
        statement["id"], make_admin_headers()
    )
    validate_error(refused_finalize, ApiErrorId.UNAUTHORIZED)

    accepted_finalize = api_client.finalize_statement(
        statement["id"], make_partner_manager_headers()
    )
    finalized = validate_success(accepted_finalize)
    assert finalized["status"] == StatementStatus.FINALIZED.value
    assert_iso_equals(
        finalized["finalized_at"], "2026-09-02T00:00:00Z", "statement.finalized_at"
    )
    assert finalized["included_redemption_count"] == 1
    assert finalized["gross_commission_cents"] == 480
    assert finalized["employer_share_cents"] == 120
    assert finalized["provider_retained_cents"] == 360

    payment = F.pay_payload(payment_reference="WIRE-2026-09-02-001")
    refused_pay = api_client.pay_statement(
        statement["id"], payment, make_partner_manager_headers()
    )
    validate_error(refused_pay, ApiErrorId.UNAUTHORIZED)

    accepted_pay = api_client.pay_statement(
        statement["id"], payment, make_admin_headers()
    )
    paid = validate_success(accepted_pay)
    assert paid["status"] == StatementStatus.PAID.value
    assert_iso_equals(paid["paid_at"], "2026-09-02T00:00:00Z", "statement.paid_at")
    assert paid["payment_reference"] == "WIRE-2026-09-02-001"


# ── Band 1: operations shared by two roles (PRD §3.3) ───────────────────────


def test_eligibility_batch_validation_accepts_either_authorised_role():
    """The same validate call reaches `VALIDATED` from the employer admin or the platform.

    PRD: "Validation is a branching decision that either an `EmployerAdmin` or a `PlatformAdmin` may trigger, with no request body, and it is accepted only from `RECEIVED` — a batch already `VALIDATED`, `REJECTED` or `APPLIED` is refused with `ERR_FILE_INVALID_STATE`."

    Design: Corner/rbac/eligibility_validation_and_employer_patch_work_for_either_authorised_role
    """
    employer_id = fixtures.create_employer()["id"]

    first_batch = fixtures.load_eligibility_file(employer_id)
    by_employer = api_client.validate_eligibility_file(
        first_batch["id"], make_employer_admin_headers(employer_id)
    )
    assert validate_success(by_employer)["status"] == EligibilityFileStatus.VALIDATED.value
    assert fixtures.apply_eligibility_file(
        first_batch["id"], employer_id
    )["created_membership_count"] == 1
    assert fixtures.get_employer(employer_id)["integration_status"] == (
        IntegrationStatus.SYNCED.value
    )

    second_batch = fixtures.load_eligibility_file(
        employer_id, records=F.eligibility_records(2),
        effective_from="2026-08-05T00:00:00Z",
    )
    by_platform = api_client.validate_eligibility_file(
        second_batch["id"], make_admin_headers()
    )
    validated = validate_success(by_platform)
    assert validated["status"] == EligibilityFileStatus.VALIDATED.value
    assert validated["valid_record_count"] == 2

    # Application, unlike validation, stays employer-admin-exclusive.
    applied = fixtures.apply_eligibility_file(second_batch["id"], employer_id)
    assert applied["created_membership_count"] == 1
    assert applied["updated_membership_count"] == 1


def test_employer_patch_accepts_either_authorised_role():
    """Two roles write different employer settings along one version chain.

    PRD: "An `EmployerAdmin` or a `PlatformAdmin` may later adjust `revenue_share_enabled`, `privacy_min_cohort_size` and `employee_count_declared`; because `revenue_share_enabled` is read at verification time, flipping it never rewrites the `employer_share_cents` of a redemption that has already been verified."

    Design: Corner/rbac/eligibility_validation_and_employer_patch_work_for_either_authorised_role
    """
    employer = fixtures.create_employer()
    employer_id = employer["id"]
    assert employer["privacy_min_cohort_size"] == C.DEFAULT_PRIVACY_MIN_COHORT_SIZE
    assert employer["revenue_share_enabled"] is C.DEFAULT_REVENUE_SHARE_ENABLED

    by_platform = api_client.update_employer(
        employer_id, {"privacy_min_cohort_size": 12}, make_admin_headers()
    )
    after_platform = validate_success(by_platform)
    assert after_platform["privacy_min_cohort_size"] == 12

    by_employer = api_client.update_employer(
        employer_id, {"revenue_share_enabled": True},
        make_employer_admin_headers(employer_id),
    )
    after_employer = validate_success(by_employer)
    assert after_employer["revenue_share_enabled"] is True
    assert after_employer["privacy_min_cohort_size"] == 12
    assert after_employer["version"] == after_platform["version"] + 1


# ── Band 4: the version echo (PRD §2.7) ─────────────────────────────────────


def test_replayed_offer_version_on_a_second_slot_reservation_is_refused():
    """An earlier reservation invalidates the read the next reservation echoes.

    PRD: "If the echoed value does not equal the parent row's current `version`, the write is refused with `ERR_STALE_VERSION` and HTTP 412, and nothing is mutated."

    Design: Corner/cross-cutting complexity layers/stale_offer_version_on_slot_reservation_returns_precondition_failed
    """
    program = fixtures.live_program(record_count=2)
    merchant_id = program["merchant"]["id"]
    employer_id = program["employer"]["id"]
    offer_id = program["offer"]["id"]
    stale_version = program["offer"]["version"]

    first_slot = fixtures.reserve_slot(
        program["offer"], employer_id, merchant_id,
        placement_tier=PlacementTier.STANDARD,
        slot_window_start=_SLOT_ONE_START, slot_window_end=_SLOT_ONE_END,
    )
    after_first = fixtures.get_offer(offer_id, merchant_id=merchant_id)
    assert after_first["version"] == stale_version + 1

    replayed = api_client.reserve_placement_slot(
        offer_id,
        F.slot_payload(
            stale_version, employer_id,
            placement_tier=PlacementTier.STANDARD,
            slot_window_start=_SLOT_TWO_START, slot_window_end=_SLOT_TWO_END,
        ),
        make_merchant_headers(merchant_id),
    )
    validate_error(replayed, ApiErrorId.STALE_VERSION)

    # Nothing was mutated: no second slot exists and the offer did not move.
    listing = api_client.list_placement_slots(
        make_partner_manager_headers(),
        params={"offer_id": offer_id, "limit": C.DEFAULT_PAGE_LIMIT, "offset": 0},
    )
    rows, meta = validate_paginated(listing)
    assert_pagination_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [first_slot["id"]]
    unchanged = fixtures.get_offer(offer_id, merchant_id=merchant_id)
    assert unchanged["version"] == after_first["version"]

    accepted = api_client.reserve_placement_slot(
        offer_id,
        F.slot_payload(
            unchanged["version"], employer_id,
            placement_tier=PlacementTier.STANDARD,
            slot_window_start=_SLOT_TWO_START, slot_window_end=_SLOT_TWO_END,
        ),
        make_merchant_headers(merchant_id),
    )
    second_slot = validate_success(accepted, 201)
    assert second_slot["status"] == SlotStatus.RESERVED.value
    assert second_slot["placement_fee_cents"] == _TWO_DAY_SLOT_FEE_CENTS
    assert fixtures.get_offer(offer_id, merchant_id=merchant_id)["version"] == (
        after_first["version"] + 1
    )


def test_replayed_employer_version_on_an_eligibility_batch_is_refused():
    """Branding and an earlier batch each advance the employer past the caller's read.

    PRD: "If the echoed value does not equal the parent row's current `version`, the write is refused with `ERR_STALE_VERSION` and HTTP 412, and nothing is mutated."

    Design: Corner/cross-cutting complexity layers/stale_employer_version_on_eligibility_file_returns_precondition_failed
    """
    employer = fixtures.create_employer()
    employer_id = employer["id"]
    at_registration = employer["version"]
    assert employer["integration_status"] == IntegrationStatus.NOT_CONFIGURED.value

    after_branding = fixtures.brand_storefront(employer_id)
    assert after_branding["version"] == at_registration + 1

    replayed = api_client.create_eligibility_file(
        employer_id, F.eligibility_file_payload(at_registration),
        make_employer_admin_headers(employer_id),
    )
    validate_error(replayed, ApiErrorId.STALE_VERSION)

    still_unconfigured = fixtures.get_employer(employer_id)
    assert still_unconfigured["integration_status"] == (
        IntegrationStatus.NOT_CONFIGURED.value
    )
    assert still_unconfigured["version"] == after_branding["version"]

    accepted = api_client.create_eligibility_file(
        employer_id, F.eligibility_file_payload(after_branding["version"]),
        make_employer_admin_headers(employer_id),
    )
    batch = validate_success(accepted, 201)
    assert batch["status"] == EligibilityFileStatus.RECEIVED.value
    fixtures.validate_eligibility_file(batch["id"], employer_id)
    applied = fixtures.apply_eligibility_file(batch["id"], employer_id)
    assert applied["status"] == EligibilityFileStatus.APPLIED.value

    # Validation and application both advanced the employer again.
    replayed_again = api_client.create_eligibility_file(
        employer_id,
        F.eligibility_file_payload(
            after_branding["version"], records=F.eligibility_records(2),
            effective_from="2026-08-05T00:00:00Z", checksum="sha256:feed-0002",
        ),
        make_employer_admin_headers(employer_id),
    )
    validate_error(replayed_again, ApiErrorId.STALE_VERSION)

    synced = fixtures.get_employer(employer_id)
    assert synced["integration_status"] == IntegrationStatus.SYNCED.value
    assert synced["eligible_headcount"] == 1

    second_accepted = api_client.create_eligibility_file(
        employer_id,
        F.eligibility_file_payload(
            synced["version"], records=F.eligibility_records(2),
            effective_from="2026-08-05T00:00:00Z", checksum="sha256:feed-0002",
        ),
        make_employer_admin_headers(employer_id),
    )
    second_batch = validate_success(second_accepted, 201)
    assert second_batch["status"] == EligibilityFileStatus.RECEIVED.value
    assert second_batch["record_count"] == 2


def test_counter_echoing_the_pre_proposal_agreement_version_is_refused():
    """The provider's proposal has already advanced the row the counter echoes.

    PRD: "If the echoed value does not equal the parent row's current `version`, the write is refused with `ERR_STALE_VERSION` and HTTP 412, and nothing is mutated."

    Design: Corner/cross-cutting complexity layers/stale_agreement_version_on_the_merchant_counter_returns_precondition_failed
    """
    merchant_id = fixtures.create_merchant()["id"]
    agreement = fixtures.create_agreement(merchant_id)
    agreement_id = agreement["id"]
    at_draft = agreement["version"]
    assert agreement["status"] == AgreementStatus.DRAFT.value
    assert agreement["round_count"] == 0

    fixtures.propose_round(agreement)
    proposed = fixtures.get_agreement(agreement_id)
    assert proposed["status"] == AgreementStatus.PROVIDER_PROPOSED.value
    assert proposed["round_count"] == 1
    assert proposed["version"] == at_draft + 1
    assert proposed["commission_rate_bps"] == 1200

    replayed = api_client.counter_round(
        agreement_id, F.round_payload(at_draft, commission_rate_bps=1000),
        make_merchant_headers(merchant_id),
    )
    validate_error(replayed, ApiErrorId.STALE_VERSION)

    # Nothing was mutated: no round was appended and the standing terms hold.
    unchanged = fixtures.get_agreement(agreement_id)
    assert unchanged["status"] == AgreementStatus.PROVIDER_PROPOSED.value
    assert unchanged["round_count"] == 1
    assert unchanged["version"] == proposed["version"]
    assert unchanged["commission_rate_bps"] == 1200
    after_refusal = api_client.list_negotiation_rounds(
        agreement_id, make_partner_manager_headers(),
        params={"limit": C.DEFAULT_PAGE_LIMIT, "offset": 0},
    )
    rows, meta = validate_paginated(after_refusal)
    assert_pagination_meta(meta, total_count=1)
    assert rows[0]["round_number"] == 1
    assert rows[0]["proposer_role"] == ProposerRole.PARTNER_MANAGER.value

    accepted = api_client.counter_round(
        agreement_id,
        F.round_payload(proposed["version"], commission_rate_bps=1000),
        make_merchant_headers(merchant_id),
    )
    # PRD §4 does not pin `/counter`'s success status or response body: it both
    # appends a round and drives `PROVIDER_PROPOSED → MERCHANT_COUNTERED`, so
    # either 201-with-round or 200-with-agreement is a faithful reading.  The
    # round's own facts are asserted below from the negotiation-round history,
    # which PRD §2.3 does pin.
    validate_success(accepted)

    countered = fixtures.get_agreement(agreement_id)
    assert countered["status"] == AgreementStatus.MERCHANT_COUNTERED.value
    assert countered["round_count"] == 2
    assert countered["commission_rate_bps"] == 1000
    assert countered["version"] == proposed["version"] + 1

    history = api_client.list_negotiation_rounds(
        agreement_id, make_partner_manager_headers(),
        params={"limit": C.DEFAULT_PAGE_LIMIT, "offset": 0},
    )
    history_rows, history_meta = validate_paginated(history)
    assert_pagination_meta(history_meta, total_count=2)
    assert [row["round_number"] for row in history_rows] == [1, 2]
    assert [row["proposer_role"] for row in history_rows] == [
        ProposerRole.PARTNER_MANAGER.value, ProposerRole.MERCHANT.value,
    ]

    # The chain resumes from the fresh read: the side that did not author the
    # standing round accepts it.
    decided = api_client.decide_agreement(
        agreement_id, F.decide_payload(DecisionValue.ACCEPT),
        make_partner_manager_headers(),
    )
    settled = validate_success(decided)
    assert settled["status"] == AgreementStatus.ACCEPTED.value
    assert settled["accepted_by_role"] == ProposerRole.PARTNER_MANAGER.value
