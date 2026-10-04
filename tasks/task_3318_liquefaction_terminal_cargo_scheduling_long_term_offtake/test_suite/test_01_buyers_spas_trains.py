"""Buyer registration, SPA lifecycle, train commissioning, and access control."""
import pytest

from test_helpers import (
    CM,
    MS,
    OP,
    ApiErrorId,
    add_cargo_slot,
    assert_adp,
    assert_adp_quantity_invariant,
    assert_customer,
    assert_spa,
    create_commenced_spa,
    create_customer,
    create_customer_payload,
    create_draft_adp,
    create_spa_payload,
    get_success_data,
    make_customer_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerCreate:
    def test_customer_create_defaults_and_system_fields(self, api):
        """PRD §3.1: "a `TerminalOperator` registers a buyer by supplying the buyer's
        `legal_name`, a `credit_rating` drawn from `AAA`, `AA`, `A`, or `BBB`, and
        optionally a `billing_currency` which defaults to `USD` when omitted."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by
        exactly 1 on every mutation, including every state transition and every
        system-driven cascade that touches the resource."

        Design: Corner/entities/customer_create_defaults_and_system_fields
        """
        resp = api.create_customer(
            create_customer_payload(legal_name="Rho Energy", credit_rating="BBB"), OP
        )
        customer = validate_success(resp, expected_status=201)
        assert_customer(customer)
        assert customer["billing_currency"] == "USD", (
            f"default billing_currency must be USD, got {customer['billing_currency']}"
        )
        assert customer["version"] == 1, (
            f"new customer version must start at 1, got {customer['version']}"
        )

    def test_spa_missing_required_field_rejected(self, api):
        """PRD §3.1: the SPA requires "the `annual_contract_quantity_mmbtu` per
        contract year (greater than zero)" among its declared inputs.
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/spa_missing_required_field_rejected
        """
        customer = create_customer(legal_name="Sigma Gas")
        payload = create_spa_payload(customer["id"])
        del payload["annual_contract_quantity_mmbtu"]
        resp = api.create_spa(payload, CM)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert err["error_id"] == "ERR_INVALID_REQUEST"


class TestSpaLifecycle:
    def test_spa_commence_fails_without_commercial_train(self, api):
        """PRD §3.1: "Once at least one liquefaction train anywhere at the terminal
        has reached `COMMERCIAL_OPERATION`, a `CommercialManager` may commence
        deliveries, moving the SPA from `EXECUTED` to `DELIVERIES_COMMENCED`;
        attempting this with no commercial train in service is rejected with
        `ERR_NO_COMMERCIAL_TRAIN`".

        Design: Difficulty/cross_entity_state_dependency/spa_commence_requires_commercial_train
        """
        customer = create_customer(legal_name="Mu Energy Partners")
        spa = get_success_data(
            api.create_spa(create_spa_payload(customer["id"]), CM)
        )
        train = get_success_data(
            api.create_train(
                {
                    "name": "Train 1",
                    "design_capacity_mtpa": 5.0,
                    "daily_capacity_mmbtu": 700000,
                    "commissioning_cargoes_required": 1,
                },
                OP,
            )
        )
        get_success_data(api.begin_commissioning(train["id"], OP))

        resp = api.commence_spa_deliveries(spa["id"], CM)
        err = validate_error(resp, ApiErrorId.ERR_NO_COMMERCIAL_TRAIN.value)
        assert err["error_id"] == "ERR_NO_COMMERCIAL_TRAIN"
        spa = get_success_data(api.get_spa(spa["id"], CM))
        assert spa["status"] == "EXECUTED", (
            f"SPA must remain EXECUTED, got {spa['status']}"
        )

    def test_spa_commence_succeeds_after_train_reaches_cod(self, api):
        """PRD §3.1: "Once at least one liquefaction train anywhere at the terminal
        has reached `COMMERCIAL_OPERATION`, a `CommercialManager` may commence
        deliveries, moving the SPA from `EXECUTED` to `DELIVERIES_COMMENCED`".

        Design: Difficulty/cross_entity_state_dependency/spa_commence_requires_commercial_train
        """
        customer = create_customer(legal_name="Mu Energy Partners")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        train = get_success_data(
            api.create_train(
                {
                    "name": "Train 1",
                    "design_capacity_mtpa": 5.0,
                    "daily_capacity_mmbtu": 700000,
                    "commissioning_cargoes_required": 1,
                },
                OP,
            )
        )
        get_success_data(api.begin_commissioning(train["id"], OP))
        get_success_data(
            api.record_commissioning_cargo(train["id"], {"proceeds_usd": 500000}, OP)
        )
        get_success_data(
            api.declare_cod(
                train["id"],
                {"cod_date": "2026-12-01", "performance_test_passed": True},
                OP,
            )
        )

        spa = get_success_data(api.commence_spa_deliveries(spa["id"], CM))
        assert spa["status"] == "DELIVERIES_COMMENCED", (
            f"SPA must reach DELIVERIES_COMMENCED, got {spa['status']}"
        )
        assert_spa(spa)

    def test_spa_expiry_system_transition(self, api):
        """PRD §2.4: "the SPA `EXPIRED` transition, for example, is applied on any
        subsequent read or write of the SPA once the clock has passed the contract's
        final instant, not by a background sweep."
        PRD §3.1: "when the current logical UTC reaches or passes the first instant
        after the last contract year — that is, the start of the year obtained by
        adding `term_years` to `contract_year_start` — the SPA moves from
        `DELIVERIES_COMMENCED` to `EXPIRED`".

        Design: Corner/state_machines/spa_expiry_system_transition
        """
        customer = create_customer(legal_name="Aleph Gas")
        spa = create_commenced_spa(
            customer["id"], contract_year_start=2027, term_years=1,
            annual_contract_quantity_mmbtu=3600000,
        )
        get_success_data(api.set_clock("2028-01-01T00:00:00Z", OP))
        spa = get_success_data(api.get_spa(spa["id"], CM))
        assert spa["status"] == "EXPIRED", (
            f"1-year SPA read at 2028-01-01 must report EXPIRED, got {spa['status']}"
        )

    def test_train_get_not_found_returns_404(self, api):
        """PRD §2.6: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not correspond to an existing
        resource."

        Design: Corner/entities/train_get_not_found_returns_404
        """
        resp = api.get_train("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", OP)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
        assert err["error_id"] == "ERR_NOT_FOUND"


class TestTrainCommissioning:
    def test_cod_before_commissioning_complete_rejected(self, api):
        """PRD §3.2: "The COD declaration is gated: the recorded
        `commissioning_cargoes_completed` must be at least
        `commissioning_cargoes_required`, and the request's `performance_test_passed`
        flag must be true; failing either condition is rejected with
        `ERR_COMMISSIONING_INCOMPLETE`."

        Design: Corner/validations/cod_before_commissioning_complete_rejected
        """
        train = get_success_data(
            api.create_train(
                {
                    "name": "Train 1",
                    "design_capacity_mtpa": 5.0,
                    "daily_capacity_mmbtu": 700000,
                    "commissioning_cargoes_required": 2,
                },
                OP,
            )
        )
        get_success_data(api.begin_commissioning(train["id"], OP))
        get_success_data(
            api.record_commissioning_cargo(train["id"], {"proceeds_usd": 900000}, OP)
        )

        resp = api.declare_cod(
            train["id"], {"cod_date": "2026-12-01", "performance_test_passed": True}, OP
        )
        err = validate_error(resp, ApiErrorId.ERR_COMMISSIONING_INCOMPLETE.value)
        assert err["error_id"] == "ERR_COMMISSIONING_INCOMPLETE"

    def test_cod_succeeds_after_required_cargoes_recorded(self, api):
        """PRD §3.2: "Declaring commercial operation moves the train from
        `COMMISSIONING` to `COMMERCIAL_OPERATION` and sets the `cod_date` supplied
        in the request."

        Design: Corner/validations/cod_before_commissioning_complete_rejected
        """
        train = get_success_data(
            api.create_train(
                {
                    "name": "Train 1",
                    "design_capacity_mtpa": 5.0,
                    "daily_capacity_mmbtu": 700000,
                    "commissioning_cargoes_required": 2,
                },
                OP,
            )
        )
        get_success_data(api.begin_commissioning(train["id"], OP))
        get_success_data(
            api.record_commissioning_cargo(train["id"], {"proceeds_usd": 900000}, OP)
        )
        get_success_data(
            api.record_commissioning_cargo(train["id"], {"proceeds_usd": 950000}, OP)
        )
        train = get_success_data(
            api.declare_cod(
                train["id"],
                {"cod_date": "2026-12-01", "performance_test_passed": True},
                OP,
            )
        )
        assert train["status"] == "COMMERCIAL_OPERATION", (
            f"train must reach COMMERCIAL_OPERATION, got {train['status']}"
        )
        assert train["cod_date"] == "2026-12-01", (
            f"cod_date must be set from the request, got {train['cod_date']}"
        )


class TestAccessControl:
    def test_unauthenticated_missing_headers(self, api):
        """PRD §2.1: "A request whose headers are missing or malformed, or whose
        role is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        resp = api._request(
            "GET",
            "/api/customers/8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            headers={},
        )
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert err["error_id"] == "ERR_UNAUTHENTICATED"

    def test_forbidden_role_cannot_create_spa(self, api):
        """PRD §2.1: "A request whose role is not listed for the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST `/api/spas` is listed for `CommercialManager`.

        Design: Corner/validations/forbidden_role_cannot_create_spa
        """
        customer = create_customer(legal_name="Tet Corp")
        resp = api.create_spa(create_spa_payload(customer["id"]), OP)
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert err["error_id"] == "ERR_FORBIDDEN"

    def test_customer_rep_ownership_mismatch_on_confirm(self, api):
        """PRD §2.1: "the same error applies when a `CustomerRep` acts against a
        resource whose owning buyer does not match their identity."
        PRD §3.3: "Confirming is the buyer's act: a `CustomerRep` whose `X-User-ID`
        equals the owning SPA's `customer_id` moves `PROPOSED` to `CONFIRMED`".

        Design: Corner/validations/customer_rep_ownership_mismatch_on_confirm
        """
        customer_a = create_customer(legal_name="Yod Energy A")
        customer_b = create_customer(legal_name="Yod Energy B")
        spa = get_success_data(api.create_spa(create_spa_payload(customer_a["id"]), CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        add_cargo_slot(
            adp["id"],
            window_start="2027-02-01T00:00:00Z",
            window_end="2027-02-08T00:00:00Z",
        )
        get_success_data(api.propose_adp(adp["id"], CM))

        resp = api.confirm_adp(adp["id"], make_customer_rep_headers(customer_b["id"]))
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert err["error_id"] == "ERR_FORBIDDEN"
        adp = get_success_data(api.get_adp(adp["id"], CM))
        assert adp["status"] == "PROPOSED", (
            f"ADP must remain PROPOSED, got {adp['status']}"
        )
