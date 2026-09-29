"""Entity creation defaults, retrieval echoes, listings and reference lookups."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    assert_absent,
    assert_append_only_row,
    assert_attestation_outcome,
    assert_cents,
    assert_decimal_2,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_instant,
    assert_null,
    assert_passport_token,
    assert_versioned_row,
    build_provider_with_customer,
    build_signing_ready_provider,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import (
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TRACEBACK_NOT_FOUND,
)
from test_helpers.constants import CLOCK_DEFAULT, NUMBER_1, NUMBER_CALLED
from test_helpers.factories import (
    blocking_event_payload,
    call_attestation_payload,
    certificate_payload,
    customer_payload,
    provider_payload,
    traffic_observation_payload,
)


class TestProviderRow:
    """The provider register and its derived compliance counters."""

    def test_registration_defaults_every_compliance_counter(self, world):
        """A freshly registered provider reads unfiled, suspended and all-zero.

        PRD: "At registration `rmd_filing_status` reads `UNFILED`, `auth_posture` reads `SIGNING_SUSPENDED`, `active_certificate_id` is null, `penalty_points`, `overdue_traceback_count`, `open_notice_count`, `active_assigned_number_count`, `outstanding_forfeiture_cents` and `sweep_index` are all 0, and `blocking_false_positive_rate` is 0.0."

        Design: Corner/entities/provider_creation_defaults_every_compliance_counter
        """
        provider = expect_created(
            world.client.create_provider(
                provider_payload(provider_type="FACILITIES_BASED"), world.regulator
            )
        )

        assert_versioned_row(provider, 1)
        assert_fields(
            provider,
            provider_type="FACILITIES_BASED",
            rmd_filing_status="UNFILED",
            auth_posture="SIGNING_SUSPENDED",
            penalty_points=0,
            overdue_traceback_count=0,
            open_notice_count=0,
            active_assigned_number_count=0,
            sweep_index=0,
        )
        assert_null(provider, "active_certificate_id")
        assert_cents(provider, "outstanding_forfeiture_cents", 0)
        assert_decimal_4(provider, "blocking_false_positive_rate", 0.0)

    def test_provider_type_rejects_an_undeclared_enum_member(self, world):
        """An enum value outside the three declared classifications is a bad request.

        PRD: "The body is valid JSON, every required input field is present and of its declared type, every enum-valued field carries a declared member, integer count fields are not negative, four-decimal score fields lie within 0.0000 to 1.0000 inclusive, and `limit` / `offset` are within their bounds — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/provider_type_rejects_undeclared_enum_member
        """
        expect_error(
            world.client.create_provider(
                provider_payload(provider_type="WHOLESALE"), world.regulator
            ),
            ERR_INVALID_REQUEST,
        )

        expect_list_total(world.client.list_providers(world.regulator), 0)


class TestCertificateRow:
    """The requested certificate as it is stored and read back."""

    def test_retrieval_echoes_the_stored_validity_interval(self, world):
        """The read returns the requested interval, generation 1 and every null.

        PRD: "The new row lands in `status` `REQUESTED` with `renewal_generation` 1, `predecessor_certificate_id` null, and `issued_at`, `activated_at`, `revoked_at` and `revocation_reason` all null."

        Design: Corner/entities/certificate_retrieval_echoes_stored_validity_interval
        """
        provider = world.register_provider()
        payload = certificate_payload(
            provider["id"],
            not_before="2026-07-15T00:00:00Z",
            not_after="2027-01-15T00:00:00Z",
        )
        created = expect_created(
            world.client.create_certificate(payload, world.policy_admin)
        )

        fetched = expect_ok(
            world.client.get_certificate(created["id"], world.policy_admin)
        )

        assert_versioned_row(fetched, 1)
        assert_fields(
            fetched,
            provider_id=provider["id"],
            status="REQUESTED",
            renewal_generation=1,
            spc_token=payload["spc_token"],
            public_key_fingerprint=payload["public_key_fingerprint"],
        )
        assert_instant(fetched, "not_before", "2026-07-15T00:00:00Z")
        assert_instant(fetched, "not_after", "2027-01-15T00:00:00Z")
        for field in (
            "predecessor_certificate_id",
            "issued_at",
            "activated_at",
            "revoked_at",
            "revocation_reason",
        ):
            assert_null(fetched, field)


class TestCustomerRow:
    """Customer onboarding defaults, shape validation and the register listing."""

    def test_onboarding_defaults_pending_kyc_and_disabled_origination(self, world):
        """Both dimensions start closed and every risk and audit field starts empty.

        PRD: "A freshly onboarded customer reads `kyc_state` `PENDING` and `origination_state` `DISABLED`, with `traffic_risk_index` 0.0000, `risk_tier` `LOW`, `observation_count` 0, `false_positive_count` 0, `suspension_cause` and `suspension_source_id` null, and `kyc_submitted_by_user_id`, `kyc_decided_by_user_id` and `kyc_decided_at` all null."

        Design: Corner/entities/customer_defaults_pending_kyc_and_disabled_origination
        """
        provider = world.register_provider()

        customer = expect_created(
            world.client.create_customer(
                customer_payload(provider["id"], kyc_evidence_level="CONTRACT_ONLY"),
                world.provider_admin(provider["id"]),
            )
        )

        assert_versioned_row(customer, 1)
        assert_fields(
            customer,
            provider_id=provider["id"],
            kyc_evidence_level="CONTRACT_ONLY",
            kyc_state="PENDING",
            origination_state="DISABLED",
            risk_tier="LOW",
            observation_count=0,
            false_positive_count=0,
        )
        assert_decimal_4(customer, "traffic_risk_index", 0.0)
        for field in (
            "suspension_cause",
            "suspension_source_id",
            "kyc_submitted_by_user_id",
            "kyc_decided_by_user_id",
            "kyc_decided_at",
        ):
            assert_null(customer, field)

    def test_onboarding_without_an_evidence_level_is_rejected(self, world):
        """A body missing the mandatory evidence strength never creates a row.

        PRD: "The body is valid JSON, every required input field is present and of its declared type, every enum-valued field carries a declared member, integer count fields are not negative, four-decimal score fields lie within 0.0000 to 1.0000 inclusive, and `limit` / `offset` are within their bounds — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/customer_creation_missing_kyc_evidence_level_rejected
        """
        provider = world.register_provider()
        payload = customer_payload(provider["id"])
        payload.pop("kyc_evidence_level")

        expect_error(
            world.client.create_customer(
                payload, world.provider_admin(provider["id"])
            ),
            ERR_INVALID_REQUEST,
        )

        expect_list_total(
            world.client.list_customers(world.regulator, provider_id=provider["id"]), 0
        )

    def test_listing_filters_by_provider_and_paginates(self, world):
        """The provider filter reports three rows and the page returns the first two.

        PRD: "The customer register can be filtered by `provider_id`, by `kyc_state`, by `origination_state` and by `risk_tier`, which is the usual way an analyst finds the queue of customers awaiting a decision."

        Design: Corner/entities/customer_listing_filters_by_provider_and_paginates
        """
        provider_a = world.register_provider()
        provider_b = world.register_provider()
        owned = {world.onboard_customer(provider_a["id"])["id"] for _ in range(3)}
        foreign = world.onboard_customer(provider_b["id"])["id"]

        items, meta = expect_list_total(
            world.client.list_customers(
                world.regulator, provider_id=provider_a["id"], limit=2, offset=0
            ),
            3,
        )

        assert len(items) == 2, f"expected a page of 2 rows, got {len(items)}"
        assert meta["has_more"] is True, "a page of 2 out of 3 rows has more to follow"
        returned = {item["id"] for item in items}
        assert returned <= owned, "the page returned a row outside the filtered provider"
        assert foreign not in returned, "the other provider's customer leaked into the page"


class TestAppendOnlyEvidenceRows:
    """Signed-call records and monitoring windows, the two immutable families."""

    def test_level_a_is_computed_for_a_fully_verified_owned_number(self, world):
        """Registry-verified evidence over an owned number signs at level A.

        PRD: "Otherwise, if `kyc_evidence_level` is `BUSINESS_REGISTRY_VERIFIED` and `ownership_verified` is true, the level is `A` with reason `FULL_KYC_AND_OWNERSHIP`."

        Design: Corner/entities/attestation_level_a_computed_for_fully_verified_owned_number
        """
        setup = build_signing_ready_provider(
            world,
            kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED",
            ownership_evidence="DIRECT_ALLOCATION",
        )

        attestation = expect_created(
            world.client.create_call_attestation(
                call_attestation_payload(
                    setup.provider_id,
                    setup.customer_id,
                    NUMBER_1,
                    NUMBER_CALLED,
                    CLOCK_DEFAULT,
                ),
                world.provider_admin(setup.provider_id),
            )
        )

        assert_attestation_outcome(
            attestation, "A", "FULL_KYC_AND_OWNERSHIP", True, "LOW"
        )
        assert_equals(attestation, "certificate_id", setup.certificate_id)
        assert_passport_token(attestation, setup.certificate_id, "A")
        assert_append_only_row(attestation)

    def test_observation_records_the_acting_operator_as_the_recorder(self, world):
        """The window stores its recorder server-side and scores 0.40 for a half-short window.

        PRD: "The acting operator's `X-User-ID` is stored as `recorded_by_user_id`."

        Design: Corner/entities/observation_recorded_by_user_id_is_system_assigned
        """
        setup = build_provider_with_customer(world)

        observation = expect_created(
            world.client.create_traffic_observation(
                traffic_observation_payload(
                    setup.provider_id,
                    setup.customer_id,
                    window_start="2026-07-01T00:00:00Z",
                    window_end="2026-07-02T00:00:00Z",
                    total_call_count=1000,
                    short_duration_call_count=500,
                    unanswered_call_count=500,
                    complaint_count=0,
                ),
                world.provider_admin(setup.provider_id),
            )
        )

        assert_equals(observation, "recorded_by_user_id", setup.provider_id)
        assert_equals(observation, "triggered_suspension", False)
        assert_decimal_2(observation, "window_subscore", 0.40)
        assert_decimal_4(observation, "resulting_risk_index", 0.4000)

        customer = world.read_customer(setup.customer_id)
        assert_fields(customer, risk_tier="ELEVATED", observation_count=1)
        assert_decimal_4(customer, "traffic_risk_index", 0.4000)

    def test_observation_is_immutable_with_no_version_field(self, world):
        """The stored window carries only id and created_at, on create and on read.

        PRD: "A signed-call record (`CallAttestation`) and a traffic-monitoring window (`TrafficObservation`) each carry only `id` and `created_at`: they have no `updated_at` and no `version` field at all, and no endpoint exists to modify or delete them."

        Design: Corner/entities/traffic_observation_is_immutable_with_no_version_field
        """
        setup = build_provider_with_customer(world)

        observation = expect_created(
            world.client.create_traffic_observation(
                traffic_observation_payload(
                    setup.provider_id,
                    setup.customer_id,
                    window_start="2026-07-01T00:00:00Z",
                    window_end="2026-07-02T00:00:00Z",
                    total_call_count=10,
                    short_duration_call_count=1,
                    unanswered_call_count=1,
                    complaint_count=0,
                ),
                world.provider_admin(setup.provider_id),
            )
        )

        assert_append_only_row(observation)
        assert_absent(observation, "version")
        assert_absent(observation, "updated_at")
        assert_decimal_2(observation, "window_subscore", 0.08)

        fetched = expect_ok(
            world.client.get_traffic_observation(observation["id"], world.regulator)
        )
        assert_append_only_row(fetched)
        assert_decimal_2(fetched, "window_subscore", 0.08)


class TestUnresolvableReferences:
    """Identifiers that name no row, in the path and in the body."""

    def test_traceback_get_with_an_unknown_id_returns_its_own_not_found(self, world):
        """A path identifier naming no traceback returns the traceback-specific 404.

        PRD: "Every identifier embedded in the URL path must resolve to a row, validated strictly left to right, with the 404 code naming the entity that failed: `ERR_PROVIDER_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_TRACEBACK_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_BLOCKING_EVENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_ENFORCEMENT_NOT_FOUND` or `ERR_REPORT_NOT_FOUND`."

        Design: Corner/entities/traceback_get_with_unknown_id_returns_not_found
        """
        expect_error(
            world.client.get_traceback_request(NON_EXISTENT_UUID, world.regulator),
            ERR_TRACEBACK_NOT_FOUND,
        )

    def test_blocking_event_with_an_unknown_customer_reports_the_missing_row(
        self, world
    ):
        """The unresolvable body reference outranks the sub-threshold analytics score.

        PRD: "Every foreign reference supplied in the body must resolve to a row, validated in body-field declaration order — `provider_id` first, then `customer_id`, then whichever of `blocking_event_id`, `certificate_id`, `identified_customer_id` or `produced_attestation_id` the payload carries."

        Design: Corner/entities/blocking_event_with_unknown_customer_id_returns_not_found
        """
        provider = world.register_provider()

        expect_error(
            world.client.create_blocking_event(
                blocking_event_payload(
                    provider["id"],
                    NON_EXISTENT_UUID,
                    calling_number=NUMBER_1,
                    analytics_score=0.10,
                    reason="ANALYTICS_SCORE",
                ),
                world.fraud(),
            ),
            ERR_CUSTOMER_NOT_FOUND,
        )

        refreshed = world.read_provider(provider["id"])
        assert_decimal_4(refreshed, "blocking_false_positive_rate", 0.0)
