"""Resource creation and registration surface: account defaults, required
fields, computed kit capacity, serial uniqueness, instrument initial state,
model obsolescence and regulatory gates, run-record immutability
(PRD sections 2.5, 2.6, 2.9, 3.1, 3.2).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_account,
    assert_kit_capacity,
    assert_run_record,
    create_account,
    create_account_payload,
    create_instrument,
    create_instrument_payload,
    create_model,
    create_reagent_kit_payload,
    is_valid_uuid,
    make_lab_operator_headers,
    record_run,
    setup_run_ready,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestAccountCreation:
    def test_account_creation_defaults(self, api):
        """A fresh account materializes with credit_hold false,
        credit_balance_cents 0, version 1, and a bare-UUID id.

        PRD §3.2: "The server initializes `credit_hold` to false and `credit_balance_cents` to 0."
        PRD §2.5: "`version` (integer): begins at 1 at creation and increases by exactly one on every mutation, whether user-triggered or system-driven."
        PRD §2.5: "`id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix."

        Design: Corner/entities/account_creation_defaults
        """
        resp = api_client.create_account(
            create_account_payload(), TEST_USERS["account_manager_headers"]
        )
        account = validate_success(resp, 201)
        assert_account(account)
        assert account["version"] == 1
        assert account["credit_hold"] is False
        assert account["credit_balance_cents"] == 0
        assert is_valid_uuid(account["id"]), "id must be a bare UUID"

    def test_account_create_missing_required_field_returns_400(self, api):
        """Omitting regulatory_class — an input field with no default — is a
        request-shape rejection.

        PRD §3.2: "An `AccountManager` registers a customer account with a display `name`, a `regulatory_class`, and a free-form `region` code."
        PRD §2.9: "Seventh, the request shape itself — required fields present, types correct, enum members valid — else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/account_create_missing_required_field_returns_400
        """
        resp = api_client.create_account(
            {"name": "Lab Two", "region": "NA"},
            TEST_USERS["account_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCatalogRegistration:
    def test_kit_capacity_computed_and_client_input_ignored(self, api):
        """capacity_gb is server-computed as flow-cell base times chemistry
        multiplier (FC_MID 120 x V2 1.5 = 180.0); a client-supplied value is
        not honored.

        PRD §3.1: "At creation the server computes and stores the kit's `capacity_gb`: the flow cell contributes a base capacity of 50 gigabases for `FC_LOW`, 120 for `FC_MID`, and 300 for `FC_HIGH`, and that base is multiplied by the chemistry throughput factor — 1.0 for `V1`, 1.5 for `V2`, and 2.2 for `V3` — with the product rounded half up to one decimal place."

        Design: Corner/entities/kit_capacity_computed_input_ignored
        """
        resp = api_client.create_reagent_kit(
            create_reagent_kit_payload(
                run_type="STD_LONG",
                flow_cell_version="FC_MID",
                chemistry_version="V2",
                capacity_gb=999,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        kit = validate_success(resp, 201)
        assert float(kit["capacity_gb"]) == pytest.approx(180.0), (
            f"capacity_gb must be 120 * 1.5 = 180.0, got {kit['capacity_gb']}"
        )
        assert_kit_capacity(kit)

    def test_instrument_duplicate_serial_rejected(self, api):
        """serial_number is globally unique: reusing one across different
        accounts still conflicts.

        PRD §3.2: "Registering an instrument into the installed base takes the owning `account_id`, the `model_id`, a `serial_number` that must be unique across every instrument ever registered (a duplicate is rejected with `ERR_DUPLICATE_SERIAL`, HTTP 409), a `regulatory_mode`, and an optional `installed_at` timestamp used when back-registering a pre-existing install."

        Design: Corner/entities/instrument_duplicate_serial_rejected
        """
        account_a = create_account(name="Lab Dup A")
        account_b = create_account(name="Lab Dup B", region="EU")
        model = create_model()
        first = api_client.create_instrument(
            create_instrument_payload(
                account_a["id"], model["id"], serial_number="SN-DUP-1"
            ),
            TEST_USERS["account_manager_headers"],
        )
        validate_success(first, 201)
        resp = api_client.create_instrument(
            create_instrument_payload(
                account_b["id"], model["id"], serial_number="SN-DUP-1"
            ),
            TEST_USERS["account_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)

    def test_instrument_initial_state_ordered(self, api):
        """A newly registered instrument starts ORDERED with factory software
        1.0.0 and no applied updates.

        PRD §3.2: "A new instrument starts in `ORDERED` state with `software_version` \"1.0.0\", an empty `applied_update_ids` list, an empty `service_windows` list, and `decommissioned_at` null."

        Design: Corner/state_machines/instrument_initial_state_ordered
        """
        instrument = create_instrument()
        assert instrument["install_state"] == "ORDERED"
        assert instrument["software_version"] == "1.0.0"
        assert instrument["applied_update_ids"] == []

    def test_obsolete_model_rejected_at_registration(self, api):
        """Registering a new instrument of an OBSOLETE model is rejected.

        PRD §3.1: "A model's `support_status` is one of `CURRENT`, `SUNSET`, or `OBSOLETE` and defaults to `CURRENT` when omitted; an `OBSOLETE` model refuses new instrument registration with `ERR_MODEL_OBSOLETE` (HTTP 422) while instruments already registered remain unaffected."

        Design: Corner/validations/obsolete_model_rejected_at_registration
        """
        account = create_account()
        model = create_model(
            model_code="SQ-50-OB", generation=1, base_price_cents=500_000,
            support_status="OBSOLETE",
        )
        resp = api_client.create_instrument(
            create_instrument_payload(account["id"], model["id"]),
            TEST_USERS["account_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MODEL_OBSOLETE)

    def test_clinical_account_rejects_ruo_instrument(self, api):
        """A CLINICAL account may register only CLINICAL instruments; an RUO
        regulatory_mode is rejected at registration.

        PRD §2.6: "A `CLINICAL` account may only register instruments whose `regulatory_mode` is `CLINICAL`; any other pairing is rejected with `ERR_REGULATORY_MODE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/clinical_account_rejects_ruo_instrument
        """
        account = create_account(regulatory_class="CLINICAL", region="EU")
        model = create_model(
            model_code="SQ-200C-RM", generation=2, base_price_cents=4_000_000,
            supported_chemistry_versions=["V2"],
        )
        resp = api_client.create_instrument(
            create_instrument_payload(
                account["id"], model["id"], regulatory_mode="RUO"
            ),
            TEST_USERS["account_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REGULATORY_MODE_MISMATCH)


class TestRunRecordImmutableSurface:
    def test_run_record_carries_no_version_or_updated_at(self, api):
        """The created run record exposes id and created_at but neither
        version nor updated_at; the list read scoped by instrument returns
        exactly that one record.

        PRD §2.5: "Run records are the single exception to this convention: as immutable event records they carry only `id` and `created_at`."
        PRD §2.5: "Both `updated_at` and `version` are absent from a run record."

        Design: Corner/entities/run_record_immutable_surface
        """
        bag = setup_run_ready()
        run = record_run(
            bag["instrument"]["id"],
            bag["lot"]["id"],
            bag["license"]["id"],
            bag["account"]["id"],
            samples_count=8,
            output_gb=2.0,
        )
        assert_run_record(run)
        assert is_valid_uuid(run["id"]), "run id must be a bare UUID"

        rows, meta = validate_paginated(
            api_client.list_run_records(
                make_lab_operator_headers(bag["account"]["id"]),
                params={"instrument_id": bag["instrument"]["id"]},
            )
        )
        assert len(rows) == 1 and rows[0]["id"] == run["id"]
        assert "version" not in rows[0] and "updated_at" not in rows[0]
