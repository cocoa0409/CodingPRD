"""Depth tests: claim intake boundary, validation priority, rejection/denial
boundary, and cross-entity connectivity guards."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_outage,
    get_claim,
    get_payer,
    setup_acknowledged_claim,
    setup_claims_pipeline,
    setup_world,
    submit_claim,
)
from test_helpers.factories import create_claim_payload as claim_payload_factory
from test_helpers.test_users import CLEARINGHOUSE_OPS_HEADERS


class TestEmptyLinesBoundary:
    def test_empty_lines_with_zero_total_accepted(self, api: ApiClient):
        """PRD §3.4: "`total_charge_cents` must equal the sum over `lines` of
        each line's `unit_charge_cents` multiplied by its `units`, with any
        discrepancy rejected as `ERR_CLAIM_TOTAL_MISMATCH` (HTTP 422)." A claim
        with zero lines and a zero total satisfies the check (the sum of zero
        terms is zero).

        Design: Difficulty/boundary_precision_check/claim_lines_empty_array_zero_units
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Empty Lines Provider",
                "tax_identification_number": "888888888",
                "national_provider_identifier": "1888888884",
            },
            payer_code="PAYEM",
        )
        resp = api.create_claim(
            world.provider_id,
            claim_payload_factory(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-Z0",
                idempotency_key="IDEM-Z0",
                total_charge_cents=0,
                diagnosis_codes=["Z00.0"],
                rendering_npi="1888888884",
                subscriber_id="MBR-Z",
                lines=[],
            ),
            world.admin_headers(),
        )
        claim = validate_success(resp, expected_status=201)
        assert claim["total_charge_cents"] == 0
        assert claim["lines"] == []

    def test_mismatched_total_rejected_just_above_zero(self, api: ApiClient):
        """PRD §3.4: "`total_charge_cents` must equal the sum over `lines` of
        each line's `unit_charge_cents` multiplied by its `units`, with any
        discrepancy rejected as `ERR_CLAIM_TOTAL_MISMATCH` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/claim_lines_empty_array_zero_units
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Mismatch Lines Provider",
                "tax_identification_number": "888888889",
                "national_provider_identifier": "1888888892",
            },
            payer_code="PAYE2",
        )
        resp = api.create_claim(
            world.provider_id,
            claim_payload_factory(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-Z1",
                idempotency_key="IDEM-Z1",
                total_charge_cents=1,
                diagnosis_codes=["Z00.0"],
                rendering_npi="1888888892",
                subscriber_id="MBR-Z",
                lines=[],
            ),
            world.admin_headers(),
        )
        # 1 != 0 (sum over an empty lines array)
        validate_error(resp, ApiErrorId.CLAIM_TOTAL_MISMATCH)


class TestValidationPriorityPairs:
    def test_suspended_provider_reports_provider_not_active(self, api: ApiClient):
        """PRD §2.7: "Because earlier checks mask later ones, a claim
        submission against a suspended provider reports
        `ERR_PROVIDER_NOT_ACTIVE` even if its claim total is also wrong".

        Design: Difficulty/priority_pair_validation_conflict/provider_inactive_state_trumps_enrollment_referential_check
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "Priority Provider",
                "tax_identification_number": "555555555",
                "national_provider_identifier": "1555555550",
            },
            payer_code="PAYPC",
        )
        # No enrollment exists for the (provider, payer) pair — the
        # referential check would fail too.
        validate_success(api.suspend_provider(world.provider_id, CLEARINGHOUSE_OPS_HEADERS))

        resp = api.create_claim(
            world.provider_id,
            claim_payload_factory(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-X1",
                idempotency_key="IDEM-X1",
                rendering_npi="1555555550",
            ),
            world.admin_headers(),
        )
        validate_error(resp, ApiErrorId.PROVIDER_NOT_ACTIVE)

    def test_claim_intake_requires_active_provider(self, api: ApiClient):
        """PRD §2.7: "Parent aggregate state — the owning provider must be
        `ACTIVE` for claim intake, eligibility intake, and enrollment
        submit/resubmit, else `ERR_PROVIDER_NOT_ACTIVE`"."

        Design: Difficulty/priority_pair_validation_conflict/provider_inactive_state_trumps_enrollment_referential_check
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "Onboarding Provider",
                "tax_identification_number": "555555557",
                "national_provider_identifier": "1555555576",
            },
            payer_code="PAYP3",
        )
        # Suspend the provider so intake hits the parent-state guard; no
        # CLAIMS_837 enrollment exists either.
        validate_success(api.suspend_provider(world.provider_id, CLEARINGHOUSE_OPS_HEADERS))

        resp = api.create_claim(
            world.provider_id,
            claim_payload_factory(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-X2",
                idempotency_key="IDEM-X2",
                rendering_npi="1555555576",
            ),
            world.admin_headers(),
        )
        validate_error(resp, ApiErrorId.PROVIDER_NOT_ACTIVE)

    def test_missing_enrollment_reports_enrollment_not_approved_over_total_mismatch(
        self, api: ApiClient
    ):
        """PRD §2.7: "Every endpoint applies its guards in a fixed order, and
        the order is observable: a request that would fail two checks always
        surfaces the earlier one." The claims enrollment gate (item 10)
        precedes the claim total consistency check (item 13).

        Design: Difficulty/priority_pair_validation_conflict/enrollment_referential_trumps_fiscal_total_mismatch
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "Priority2 Provider",
                "tax_identification_number": "666666666",
                "national_provider_identifier": "1666666668",
            },
            payer_code="PAYP2",
        )
        # Provider is ACTIVE but no CLAIMS_837 enrollment exists; the claim
        # total (99999) deliberately mismatches its lines (100).
        resp = api.create_claim(
            world.provider_id,
            claim_payload_factory(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-Y1",
                idempotency_key="IDEM-Y1",
                total_charge_cents=99999,
                diagnosis_codes=["Z00.0"],
                rendering_npi="1666666668",
                subscriber_id="MBR-Y",
                lines=[{"cpt_code": "99213", "units": 1, "unit_charge_cents": 100}],
            ),
            world.admin_headers(),
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_NOT_APPROVED)

    def test_claim_intake_without_approved_enrollment_rejected(self, api: ApiClient):
        """PRD §3.4: "an `APPROVED` `CLAIMS_837` enrollment must exist for this
        (provider, payer)". PRD §2.7: "Claims enrollment gate — an `APPROVED`
        enrollment for the claims transaction type must exist for the
        (provider, payer) pair before a claim is persisted, else
        `ERR_ENROLLMENT_NOT_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/enrollment_referential_trumps_fiscal_total_mismatch
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "No Enrollment Provider",
                "tax_identification_number": "666666667",
                "national_provider_identifier": "1666666676",
            },
            payer_code="PAYP4",
        )
        resp = api.create_claim(
            world.provider_id,
            claim_payload_factory(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-Y2",
                idempotency_key="IDEM-Y2",
                rendering_npi="1666666676",
            ),
            world.admin_headers(),
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_NOT_APPROVED)


class TestClaimForwardConnectivityGuard:
    def test_forward_refused_when_payer_offline(self, api: ApiClient):
        """PRD §3.4: "Forwarding is refused outright when the payer is
        `OFFLINE` for claims — that is, when any `ACTIVE` outage lists
        `CLAIMS_837` in `affects_transaction_types` at `FULL` severity — with
        `ERR_PAYER_OFFLINE`".

        Design: Difficulty/cross_entity_state_dependency/claim_forward_requires_payer_connectivity_online
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "CrossDep Provider",
                "tax_identification_number": "999999999",
                "national_provider_identifier": "1999999992",
            },
            payer_code="PAYXD",
        )
        claim = submit_claim(
            api, world, patient_control_number="PCN-CD1", idempotency_key="IDEM-CD1"
        )
        create_outage(
            api, world.payer_id, severity="FULL", affects_transaction_types=["CLAIMS_837"]
        )

        resp = api.forward_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, CLEARINGHOUSE_OPS_HEADERS
        )
        validate_error(resp, ApiErrorId.PAYER_OFFLINE)

        payer = get_payer(api, world.payer_id)
        assert payer["connectivity_status"] == "OFFLINE"

    def test_forward_succeeds_again_once_outage_resolved(self, api: ApiClient):
        """PRD §3.7: "every `ACCEPTED` claim whose forwarding had been blocked
        transitions to `FORWARDED` if its payer is back to `ONLINE`, with all
        the usual forwarding side effects."

        Design: Difficulty/cross_entity_state_dependency/claim_forward_requires_payer_connectivity_online
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "CrossDep2 Provider",
                "tax_identification_number": "999999998",
                "national_provider_identifier": "1999999984",
            },
            payer_code="PAYX2",
        )
        claim = submit_claim(
            api, world, patient_control_number="PCN-CD2", idempotency_key="IDEM-CD2"
        )
        outage = create_outage(
            api, world.payer_id, severity="FULL", affects_transaction_types=["CLAIMS_837"]
        )
        validate_error(
            api.forward_claim(
                claim["id"], {"expected_claim_version": claim["version"]}, CLEARINGHOUSE_OPS_HEADERS
            ),
            ApiErrorId.PAYER_OFFLINE,
        )

        resolved = validate_success(api.resolve_outage(outage["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert resolved["status"] == "RESOLVED"

        payer = get_payer(api, world.payer_id)
        assert payer["connectivity_status"] == "ONLINE"

        claim_now = get_claim(api, claim["id"])
        forwarded = validate_success(
            api.forward_claim(
                claim["id"],
                {"expected_claim_version": claim_now["version"]},
                CLEARINGHOUSE_OPS_HEADERS,
            )
        )
        assert forwarded["acceptance_status"] == "FORWARDED"


class TestRemittancePostEnrollmentGate:
    def test_post_refused_without_remittance_enrollment(self, api: ApiClient):
        """PRD §3.5: "Four preconditions must hold: the claim's
        `acceptance_status` is `ACKNOWLEDGED_BY_PAYER`; the claim's
        `adjudication_status` is `PENDING`; an `APPROVED` `REMITTANCE_835`
        enrollment exists for the claim's (provider, payer); and the
        arithmetic balances". PRD §5: `ERR_ENROLLMENT_NOT_APPROVED` — "No
        APPROVED enrollment exists for (provider, payer, transaction_type)".

        Design: Difficulty/cross_entity_state_dependency/remittance_post_requires_remittance_enrollment_approved
        """
        # CLAIMS_837 approved, REMITTANCE_835 deliberately absent.
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "RemDep Provider",
                "tax_identification_number": "121212121",
                "national_provider_identifier": "1121212124",
            },
            payer_code="PAYRD",
        )
        claim = setup_acknowledged_claim(
            api,
            world,
            claim_overrides={
                "patient_control_number": "PCN-RD1",
                "idempotency_key": "IDEM-RD1",
                "total_charge_cents": 5000,
            },
        )
        remittance = get_success_data(
            api.create_remittance(
                claim["id"],
                {
                    "check_number": "CHK-RD1",
                    "paid_amount_cents": 5000,
                    "adjustment_amount_cents": 0,
                    "patient_responsibility_cents": 0,
                    "denial_reason_codes": [],
                },
                world.payer_headers(),
            )
        )

        resp = api.post_remittance(remittance["id"], CLEARINGHOUSE_OPS_HEADERS)
        validate_error(resp, ApiErrorId.ENROLLMENT_NOT_APPROVED)

        claim_now = get_claim(api, claim["id"])
        assert claim_now["adjudication_status"] == "PENDING"

    def test_post_succeeds_once_remittance_enrollment_approved(self, api: ApiClient):
        """PRD §3.5: "an `APPROVED` `REMITTANCE_835` enrollment exists for the
        claim's (provider, payer)" — once it does, posting proceeds and "moves
        the claim's `adjudication_status` accordingly ... `PAID` when
        `paid_amount_cents` equals the claim's `total_charge_cents` and both
        `adjustment_amount_cents` and `patient_responsibility_cents` are zero".

        Design: Difficulty/cross_entity_state_dependency/remittance_post_requires_remittance_enrollment_approved
        """
        from test_helpers.fixtures import enroll_and_approve, post_remittance

        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "RemDep2 Provider",
                "tax_identification_number": "121212122",
                "national_provider_identifier": "1121212124",
            },
            payer_code="PAYR2",
        )
        claim = setup_acknowledged_claim(
            api,
            world,
            claim_overrides={
                "patient_control_number": "PCN-RD2",
                "idempotency_key": "IDEM-RD2",
                "total_charge_cents": 5000,
            },
        )
        remittance = get_success_data(
            api.create_remittance(
                claim["id"],
                {
                    "check_number": "CHK-RD2",
                    "paid_amount_cents": 5000,
                    "adjustment_amount_cents": 0,
                    "patient_responsibility_cents": 0,
                    "denial_reason_codes": [],
                },
                world.payer_headers(),
            )
        )
        # Open the gate after ingest, then post.
        enroll_and_approve(api, world, "REMITTANCE_835")

        posted = post_remittance(api, remittance["id"])
        assert posted["status"] == "POSTED"
        claim_now = get_claim(api, claim["id"])
        assert claim_now["adjudication_status"] == "PAID"
