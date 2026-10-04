"""Contract lifecycle, cascades, RBAC, and basic validation tests."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    set_clock,
    make_customer,
    make_contract,
    add_service_line,
    activate_contract,
    make_cancellation,
    make_competing_offer,
    make_fixed_config,
    make_pickup_event,
    make_rate_notice,
    make_service_change,
    approve_service_change,
    get_customer_balance,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_customer_headers

OPS = TEST_USERS["ops_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
HAULER = TEST_USERS["hauler_agent_headers"]


def _instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an instant. PRD §3.1 defines
    `end_date` as ISO 8601 UTC without pinning a fractional-digit format
    (only `created_at`/`updated_at`/`api_request_timestamp` are pinned to
    three fractional digits in §2.2/§2.5), so date-valued assertions compare
    instants rather than exact strings."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestCustomerCreationDefaults:
    def test_credit_balance_defaults_to_zero(self, api):
        """PRD section 3.1: "The new customer's `credit_balance_cents` is
        initialized to 0 by the server."
        PRD section 2.7: "which starts at 0 when the customer is created and is
        never accepted from client input — any input value for it is ignored."

        Design: Corner/entities/customer_creation_defaults_and_computed_balance
        """
        resp = api.create_customer(
            {
                "legal_name": "New Co",
                "billing_email": "n@x.example",
                "credit_balance_cents": 99999,
            },
            ADMIN,
        )
        created = validate_success(resp, expected_status=201)
        assert created["credit_balance_cents"] == 0
        assert created["version"] == 1
        fetched = validate_success(api.get_customer(created["id"], ADMIN))
        assert fetched["credit_balance_cents"] == 0


class TestContractCreationValidation:
    def test_missing_term_months_rejected(self, api):
        """PRD section 3.2: "An `OpsManager` drafts a contract against a
        customer by supplying the `customer_id`, a `start_date` (ISO 8601 UTC,
        required), and a `term_months` length in whole months (required, and it
        must be at least 1)."
        PRD section 2.10: "fourth request shape — required fields present,
        well-typed values, enums within their declared sets, numeric ranges
        respected (`ERR_INVALID_REQUEST`, HTTP 400)".

        Design: Corner/entities/contract_missing_required_term_months
        """
        customer = make_customer(legal_name="Req Co", billing_email="rq@x.example")
        resp = api.create_contract(
            {
                "customer_id": customer["id"],
                "start_date": "2026-09-01T00:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestServiceLineEnumValidation:
    def test_invalid_container_size_rejected(self, api):
        """PRD section 3.2: "Each line declares a `container_size` — one of
        `CY_2`, `CY_4`, `CY_6`, or `CY_8` cubic yards".
        PRD section 2.10: "enums within their declared sets ...
        (`ERR_INVALID_REQUEST`, HTTP 400)".

        Design: Corner/entities/service_line_invalid_enum_container_size
        """
        customer = make_customer(legal_name="Enum Co", billing_email="e@x.example")
        contract = make_contract(customer["id"], term_months=12)
        resp = api.create_service_line(
            contract["id"],
            {
                "container_size": "CY_5",
                "frequency_per_week": 2,
                "base_rate_cents": 100000,
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestContractNotFound:
    def test_get_unknown_contract_is_not_found(self, api):
        """PRD section 2.10: "third resource existence (`ERR_NOT_FOUND`)".
        PRD section 2.10: "rejecting with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource."

        Design: Corner/entities/get_contract_not_found
        """
        resp = api.get_contract(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", OPS
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestActivationPreconditions:
    def test_activate_without_lines_rejected(self, api):
        """PRD section 3.2: "An `OpsManager` may activate only when two
        preconditions both hold: the contract has at least one service line,
        and its `start_date` is on or before the logical clock. A contract
        without lines, or one whose start date still lies in the future, is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/activate_contract_without_lines_invalid
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="NoLine Co", billing_email="nl@x.example")
        contract = make_contract(customer["id"], term_months=12)
        resp = api.activate_contract(contract["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_contract(contract["id"], OPS))
        assert after["status"] == "DRAFT"


class TestDisputeCompletedEventRejected:
    def test_disputing_completed_event_rejected(self, api):
        """PRD section 3.5: "Disputing a `COMPLETED` or `MISSED` event is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/dispute_completed_event_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Disp Co", billing_email="dp@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        set_clock("2026-09-02T12:00:00Z")
        event = make_pickup_event(line["id"], "2026-09-02", "COMPLETED")
        resp = api.dispute_pickup_event(
            event["id"], make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAutoRenewal:
    def test_clock_advance_past_end_date_renews(self, api):
        """PRD section 3.2: "on every advance of the logical clock, any
        contract in `ACTIVE` whose `end_date` is on or before the new clock
        time extends its `end_date` by `renewal_term_months` months, increments
        `current_term_index` by 1, and increments its `version` by 1."

        Design: Corner/state_machines/auto_renewal_extends_end_date
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Ren Co", billing_email="rn@x.example")
        contract = make_contract(
            customer["id"], term_months=6, renewal_term_months=12,
        )
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        set_clock("2027-03-05T00:00:00Z")
        renewed = validate_success(api.get_contract(contract["id"], OPS))
        assert renewed["status"] == "ACTIVE"
        assert renewed["current_term_index"] == 2
        assert renewed["end_date"] and _instant(renewed["end_date"]) == _instant(
            "2028-03-01T00:00:00Z"
        )


class TestReinstateCycle:
    def test_timely_terminated_contract_can_be_reinstated(self, api):
        """PRD section 3.2: "reinstatement moves a contract from `TERMINATED`
        back to `ACTIVE` and is permitted only while the logical clock is
        strictly before the contract's `end_date`; it increments the contract's
        `version` by 1."

        Design: Difficulty/non_linear_state_machine/rolloff_cancellation_return_to_reservable_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(
            legal_name="Reinstate Co", billing_email="ri@x.example"
        )
        contract = make_contract(
            customer["id"], term_months=12, cancellation_notice_days=60,
        )
        add_service_line(
            contract["id"], container_size="CY_4",
            frequency_per_week=2, base_rate_cents=200000,
        )
        activate_contract(contract["id"])
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2026-11-01T00:00:00Z"
        )
        validate_success(api.approve_cancellation(cancellation["id"], OPS))
        terminated = validate_success(api.get_contract(contract["id"], OPS))
        assert terminated["status"] == "TERMINATED"
        assert _instant(terminated["end_date"]) == _instant("2027-09-01T00:00:00Z")

        reinstated = validate_success(api.reinstate_contract(contract["id"], OPS))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["version"] == terminated["version"] + 1

    def test_reinstatement_preserves_end_date_and_zero_ld(self, api):
        """PRD section 3.2: "Its `end_date` is computed by the server as the
        `start_date` plus `term_months` whole months on the same day-of-month".
        PRD section 3.8: "On the timely branch — where `timely` is true and
        therefore `ld_total_cents` is 0 — the contract moves directly from
        `ACTIVE` to `TERMINATED` and no damages are assessed."

        Design: Difficulty/non_linear_state_machine/rolloff_cancellation_return_to_reservable_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(
            legal_name="Reinstate2 Co", billing_email="ri2@x.example"
        )
        contract = make_contract(
            customer["id"], term_months=12, cancellation_notice_days=60,
        )
        add_service_line(contract["id"], base_rate_cents=200000)
        activate_contract(contract["id"])
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2026-11-01T00:00:00Z"
        )
        approved = validate_success(
            api.approve_cancellation(cancellation["id"], OPS)
        )
        assert approved["ld_total_cents"] == 0
        validate_success(api.reinstate_contract(contract["id"], OPS))
        after = validate_success(api.get_contract(contract["id"], OPS))
        assert _instant(after["end_date"]) == _instant("2027-09-01T00:00:00Z")
        assert get_customer_balance(customer["id"]) == 0


class TestTerminationCascade:
    def test_untimely_approval_cascades_to_all_pending_artifacts(self, api):
        """PRD section 3.8: "Approval forks on the `timely` flag, and both
        branches run the same shutdown cascade on the contract: every
        `SCHEDULED` rate adjustment notice on the contract moves to
        `CANCELLED`, every `PENDING` or `APPROVED` service change request on
        the contract's lines moves to `CANCELLED`, and every `SUBMITTED`
        competing offer on the contract moves to `VOID`."

        Design: Difficulty/transitive_cascade/cancellation_approval_four_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Cascade Co", billing_email="cs@x.example")
        contract = make_contract(
            customer["id"], term_months=12,
            cancellation_notice_days=60, rofr_enabled=True,
        )
        line = add_service_line(
            contract["id"], container_size="CY_6",
            frequency_per_week=3, base_rate_cents=300000,
        )
        activate_contract(contract["id"])
        notice = make_rate_notice(
            contract["id"], pct_increase=0.04,
            effective_date="2026-09-20T00:00:00Z",
        )
        change = make_service_change(
            customer["id"], line["id"], new_container_size="CY_6",
            new_frequency_per_week=4, effective_date="2026-09-10T00:00:00Z",
        )
        approve_service_change(change["id"])
        offer = make_competing_offer(
            customer["id"], contract["id"], competitor_monthly_cents=280000,
        )
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2027-07-04T00:00:00Z"
        )

        validate_success(api.approve_cancellation(cancellation["id"], OPS))

        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["status"] == "TERMINATION_PENDING"
        notice_after = validate_success(api.get_rate_notice(notice["id"], OPS))
        assert notice_after["status"] == "CANCELLED"
        change_after = validate_success(
            api.get_service_change_request(change["id"], OPS)
        )
        assert change_after["status"] == "CANCELLED"
        offer_after = validate_success(api.get_competing_offer(offer["id"], OPS))
        assert offer_after["status"] == "VOID"

    def test_cascade_debits_customer_balance_by_assessed_ld(self, api):
        """PRD section 3.8: "Assessing damages sets the request's `ld_status`
        from its initial `NONE` to `ASSESSED` and immediately debits the
        customer's `credit_balance_cents` by `ld_total_cents` per section 2.7."

        Design: Difficulty/transitive_cascade/cancellation_approval_four_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Cascade2 Co", billing_email="cs2@x.example")
        contract = make_contract(
            customer["id"], term_months=12, cancellation_notice_days=60,
        )
        add_service_line(
            contract["id"], container_size="CY_6",
            frequency_per_week=3, base_rate_cents=300000,
        )
        activate_contract(contract["id"])
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2027-07-04T00:00:00Z"
        )
        approved = validate_success(
            api.approve_cancellation(cancellation["id"], OPS)
        )
        assert approved["ld_total_cents"] == 300000
        assert approved["ld_status"] == "ASSESSED"
        assert get_customer_balance(customer["id"]) == -300000


class TestRbacDenials:
    def test_customer_cannot_activate_contract(self, api):
        """PRD section 2.1: "When the headers are well-formed but the named
        role is not permitted to perform the requested operation, the request
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 2.1: "The `OpsManager` role runs waste-management
        operations: it creates and activates contracts".

        Design: Corner/rbac/customer_cannot_activate_contract
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Rb Co", billing_email="rb@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(contract["id"], base_rate_cents=100000)
        resp = api.activate_contract(
            contract["id"], make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_contract(contract["id"], OPS))
        assert after["status"] == "DRAFT"

    def test_opsmanager_cannot_set_clock_or_create_surcharge_config(self, api):
        """PRD section 2.1: "The `PlatformAdmin` role is the platform operator:
        it manages customers and surcharge configurations, drives the logical
        clock, and has read access to every resource."
        PRD section 2.1: "the named role is not permitted to perform the
        requested operation, the request is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/opsmanager_cannot_set_clock_or_create_surcharge_config
        """
        clock_resp = api.set_clock("2026-09-02T00:00:00Z", OPS)
        validate_error(clock_resp, ApiErrorId.ERR_FORBIDDEN)
        cfg_resp = api.create_surcharge_config(
            {
                "fuel_mode": "FIXED",
                "fuel_fixed_pct": 0.10,
                "environmental_pct": 0.10,
                "admin_pct": 0.05,
                "contamination_fee_cents": 15000,
                "overweight_fee_cents": 20000,
                "effective_from": "2026-09-01T00:00:00Z",
            },
            OPS,
        )
        validate_error(cfg_resp, ApiErrorId.ERR_FORBIDDEN)

    def test_hauler_cannot_resolve_dispute(self, api):
        """PRD section 2.1: "The `HaulerAgent` role records collection events
        and may list and read pickup events."
        PRD section 2.1: "When the headers are well-formed but the named role
        is not permitted to perform the requested operation, the request is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/hauler_cannot_resolve_dispute
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(effective_from="2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Hb Co", billing_email="hb@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        event = make_pickup_event(
            line["id"], "2026-09-01", "CONTAMINATED",
            photo_evidence_url="https://img.example/x.jpg",
        )
        validate_success(
            api.dispute_pickup_event(
                event["id"], make_customer_headers(customer["id"])
            )
        )
        resp = api.resolve_pickup_dispute(event["id"], "UPHELD", HAULER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_pickup_event(event["id"], OPS))
        assert after["dispute_status"] == "DISPUTED"


class TestPickupPhotoEvidence:
    def test_contaminated_event_requires_photo(self, api):
        """PRD section 3.5: "Photo evidence is mandatory whenever the outcome
        involves contamination or overweight — that is, for `CONTAMINATED`,
        `OVERWEIGHT`, and `CONTAMINATED_OVERWEIGHT` — and omitting
        `photo_evidence_url` on those outcomes is rejected with
        `ERR_INVALID_REQUEST`; for `COMPLETED` and `MISSED` the photo field is
        optional."

        Design: Corner/endpoints/pickup_event_contaminated_requires_photo
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(effective_from="2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Ph Co", billing_email="ph@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])

        missing = api.create_pickup_event(
            {
                "service_line_id": line["id"],
                "occurred_date": "2026-09-02",
                "outcome": "CONTAMINATED",
            },
            HAULER,
        )
        validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

        ok = validate_success(
            api.create_pickup_event(
                {
                    "service_line_id": line["id"],
                    "occurred_date": "2026-09-02",
                    "outcome": "CONTAMINATED",
                    "photo_evidence_url": "https://img.example/ok.jpg",
                },
                HAULER,
            ),
            expected_status=201,
        )
        assert ok["contamination_fee_cents"] == 15000


class TestServiceCreditRequiresMissedOutcome:
    def test_credit_against_completed_event_rejected(self, api):
        """PRD section 3.6: "The referenced event must have outcome `MISSED`
        and must belong to the same service line named in the filing; a credit
        filed against a non-missed event or a mismatched line is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/validations/service_credit_requires_missed_outcome
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(effective_from="2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="CrCo", billing_email="cc@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        event = make_pickup_event(line["id"], "2026-09-01", "COMPLETED")
        resp = api.create_service_credit(
            {"service_line_id": line["id"], "pickup_event_id": event["id"]},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestListContractsPagination:
    def test_limit_offset_pagination_envelope(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter specifies how many items to skip and defaults to
        0."
        PRD section 2.3: "The `meta` object of every list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_contracts_pagination_envelope
        """
        from prd_bench_local_runner.testing import validate_paginated

        customer = make_customer(legal_name="Pg Co", billing_email="pg@x.example")
        make_contract(customer["id"], term_months=12)
        make_contract(customer["id"], term_months=24)

        page1, meta1 = validate_paginated(
            api.list_contracts(OPS, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_contracts(OPS, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"]


class TestRolloffCancel:
    def test_cancel_before_delivery_succeeds_second_cancel_rejected(self, api):
        """PRD section 3.10: "The placing `Customer` may cancel a `RESERVED`
        order while the logical clock is strictly before the `delivery_date`,
        moving it to `CANCELLED`; cancelling at or after the delivery date is
        rejected."
        PRD section 3.10: "`COMPLETED` and `CANCELLED` are terminal."

        Design: Corner/endpoints/rolloff_cancel_before_delivery_date
        """
        from test_helpers import make_rolloff_order

        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Cx Co", billing_email="cx@x.example")
        order = make_rolloff_order(
            customer["id"], delivery_date="2026-09-05T00:00:00Z",
            container_size="YD_30", rental_days=7,
            delivery_fee_cents=12000, daily_rental_cents=1500,
            overage_ton_cents=9000,
        )
        cancelled = validate_success(
            api.cancel_rolloff_order(
                order["id"], make_customer_headers(customer["id"])
            )
        )
        assert cancelled["status"] == "CANCELLED"
        resp = api.cancel_rolloff_order(
            order["id"], make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
