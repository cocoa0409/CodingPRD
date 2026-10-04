"""Access control and entity registration: role denials, entity-backed
ownership, defaults, creation invariants, retrieval round-trips, and schema
rejections."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_client,
    assert_supplier,
    create_client,
    create_opt_out,
    create_prescriber,
    create_supplier,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DAM, PA, PO
from test_helpers.test_users import (
    make_manufacturer_client_headers,
    make_supplier_operator_headers,
)


class TestClientCreation:
    def test_create_returns_defaults_and_computed_balance(self, api):
        """PRD §3.1: "A `PlatformAdmin` onboards a manufacturer licensee by creating a client with a
        `name` and an `entitlement_cells_total` — the ceiling of projection cells the licensee may
        consume across all compiled and reissued deliveries. The client begins `ACTIVE`, and its
        computed `entitlement_cells_balance` starts equal to `entitlement_cells_total`."

        Design: Corner/entities/client_create_returns_defaults_and_computed_balance
        """
        data = validate_success(
            api.create_client({"name": "Client Zero", "entitlement_cells_total": 42}, PA),
            expected_status=201,
        )
        assert_client(data)
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["entitlement_cells_balance"] == 42, (
            "the computed balance starts equal to entitlement_cells_total"
        )
        assert data["id"] and data["created_at"] and data["updated_at"]


class TestSupplierRegistration:
    def test_retrieval_round_trip(self, api):
        """PRD §3.1: "Separately, a `DataAcquisitionManager` registers a data supplier with a
        `name`, a `supplier_type` of `PHARMACY`, `DISTRIBUTOR`, or `CLAIM_PROCESSOR`, and the
        `state_code` of the supplier's headquarters. The `supplier_type` is not decorative: it
        selects the royalty multiplier applied when feed batches from that supplier are accepted
        (§3.3). A new supplier begins `ACTIVE`."

        Design: Corner/entities/supplier_retrieval_round_trip
        """
        created = create_supplier(
            name="Claims R Us", supplier_type="CLAIM_PROCESSOR", state_code="WA"
        )
        fetched = validate_success(api.get_supplier(created["id"], PA))
        assert_supplier(fetched)
        assert fetched["name"] == "Claims R Us"
        assert fetched["supplier_type"] == "CLAIM_PROCESSOR"
        assert fetched["state_code"] == "WA"
        assert fetched["status"] == "ACTIVE"
        assert fetched["version"] == 1

    def test_missing_required_supplier_type_rejected(self, api):
        """PRD §3.1: "Separately, a `DataAcquisitionManager` registers a data supplier with a
        `name`, a `supplier_type` of `PHARMACY`, `DISTRIBUTOR`, or `CLAIM_PROCESSOR`, and the
        `state_code` of the supplier's headquarters."

        Design: Corner/entities/supplier_create_missing_required_returns_invalid_request
        """
        resp = api.create_supplier({"name": "NoType", "state_code": "CA"}, DAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(api.list_suppliers(PA))
        assert meta["total_count"] == 0

    def test_invalid_supplier_type_enum_rejected(self, api):
        """PRD §3.1: "Separately, a `DataAcquisitionManager` registers a data supplier with a
        `name`, a `supplier_type` of `PHARMACY`, `DISTRIBUTOR`, or `CLAIM_PROCESSOR`, and the
        `state_code` of the supplier's headquarters."

        Design: Corner/entities/supplier_create_invalid_enum_type
        """
        resp = api.create_supplier(
            {"name": "BadType", "supplier_type": "WHOLESALER", "state_code": "CA"}, DAM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDeidProfileDefaults:
    def test_defaults_applied_and_overridable(self, api):
        """PRD §3.3: "The referenced profile — created by a `PrivacyOfficer` with a `name`, a
        `salt_version`, an optional `k_anonymity_threshold` defaulting to 5, and an optional
        `hash_algorithm` of `SHA256` or `SHA512` defaulting to `SHA256` — captures the
        tokenization parameters under which the batch's prescriber identifiers were hashed."

        Design: Corner/entities/deid_profile_defaults_applied
        """
        defaulted = validate_success(
            api.create_deid_profile({"name": "DP-DEF", "salt_version": "sv1"}, PO),
            expected_status=201,
        )
        assert defaulted["k_anonymity_threshold"] == 5
        assert defaulted["hash_algorithm"] == "SHA256"
        explicit = validate_success(
            api.create_deid_profile(
                {
                    "name": "DP-EXP",
                    "salt_version": "sv2",
                    "k_anonymity_threshold": 11,
                    "hash_algorithm": "SHA512",
                },
                PO,
            ),
            expected_status=201,
        )
        assert explicit["k_anonymity_threshold"] == 11
        assert explicit["hash_algorithm"] == "SHA512"


class TestPrescriberRetrieval:
    def test_get_nonexistent_prescriber_returns_not_found(self, api):
        """PRD §2.8: "Every request passes through a fixed priority cascade. Authentication and role
        checks come first, then ownership checks, then existence checks on path identifiers and
        body foreign keys (validated left to right, so the first unresolvable identifier is the
        one reported with `ERR_NOT_FOUND`), then request-body schema checks
        (`ERR_INVALID_REQUEST`), then optimistic-concurrency checks, then generic and
        domain-specific state checks, then business safety rules (re-identification prohibition,
        opt-out violation, jurisdiction restriction, QA floor), then business temporal rules
        (window overlap, delivery window, audit cooldown), then business referential rules
        (version currency, deliverable cells, duplicate opt-out), and finally fiscal rules
        (royalty budget, entitlement balance)."

        Design: Corner/entities/prescriber_get_nonexistent_returns_not_found
        """
        resp = api.get_prescriber(NON_EXISTENT_UUID, PA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleDenials:
    def test_supplier_operator_cannot_activate_agreement(self, api):
        """PRD §2.1: "A request whose role is valid but not listed for the target endpoint is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/supplier_operator_cannot_activate_agreement
        """
        from test_helpers import create_agreement

        supplier = create_supplier(name="SR1")
        agreement = create_agreement(supplier["id"], royalty_budget_cents=1000000)
        resp = api.activate_agreement(
            agreement["id"], make_supplier_operator_headers(supplier["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        fetched = validate_success(api.get_agreement(agreement["id"], DAM))
        assert fetched["status"] == "DRAFT"

    def test_data_acquisition_manager_cannot_verify_optout(self, api):
        """PRD §2.1: "A request whose role is valid but not listed for the target endpoint is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/data_acquisition_manager_cannot_verify_optout
        """
        prescriber = create_prescriber(full_name="Dr RB", npi="NPI-701")
        opt_out = create_opt_out(prescriber["id"])
        resp = api.verify_opt_out(opt_out["id"], DAM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        fetched = validate_success(api.get_opt_out(opt_out["id"], PA))
        assert fetched["status"] == "SUBMITTED"


class TestEntityBackedOwnership:
    def test_manufacturer_client_reads_own_record_only(self, api):
        """PRD §2.1: "When `X-User-Role` is `ManufacturerClient`, `X-User-ID` is the `id` of the
        acting `ManufacturerClient`; ownership checks compare the resource's client reference to
        `X-User-ID`. A `ManufacturerClient` may read only its own client record and may request
        audits only for its own client id; acting on another client's record or audit stream is
        rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/manufacturer_client_cannot_access_other_client
        """
        client_a = create_client(name="Client A", entitlement_cells_total=10)
        client_b = create_client(name="Client B", entitlement_cells_total=20)
        resp = api.get_client(client_b["id"], make_manufacturer_client_headers(client_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        own = validate_success(
            api.get_client(client_a["id"], make_manufacturer_client_headers(client_a["id"]))
        )
        assert own["name"] == "Client A"
