"""Drafting a custom-farming agreement, enrolling blocks and countersignature."""
from test_helpers import (
    MISSING_UUID_A,
    ApiErrorId,
    assert_block,
    assert_contract,
    assert_money,
    assert_version,
    make_client_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestAgreementDrafting:
    """PRD §3.2 — a drafted agreement opens empty."""

    def test_drafted_agreement_opens_in_draft_with_zero_aggregates(self, api):
        """A newly drafted agreement reports `settled_period_count` 0, `enrolled_block_count` 0, `total_contracted_acres` 0.00, `accrued_quality_incentive` 0.00, `projected_total_billable` 0.00, a null `client_signature_name` and a null `last_settlement_total`.

        Design: Corner/state_machines/contract_created_starts_in_draft_with_zero_aggregates
        """
        s = fx.setup_ranch_with_block(api)

        data = validate_success(
            api.create_contract(f.contract_payload(s.vineyard["id"]), fx.VM), 201
        )

        assert_contract(data)
        assert data["contract_status"] == "DRAFT"
        assert data["enrolled_block_count"] == 0
        assert_money(data["total_contracted_acres"], 0.00, "total_contracted_acres")
        assert_money(data["accrued_quality_incentive"], 0.00,
                     "accrued_quality_incentive")
        assert_money(data["projected_total_billable"], 0.00,
                     "projected_total_billable")
        assert data["settled_period_count"] == 0
        assert data["last_settlement_total"] is None
        assert data["client_signature_name"] is None
        assert_version(data, 1, "agreement")


class TestBlockEnrollment:
    """PRD §3.2 — enrollment is the only writer of a block's contract fields."""

    def test_enrolled_block_is_reachable_from_its_agreement(self, api):
        """Enrollment sets the block's `contract_id`, `contracted_acres` and `per_acre_fee_override`, increments the block's `version` by 1, and then recomputes the agreement's `enrolled_block_count` (the number of blocks pointing at it) and `total_contracted_acres` (the sum of their `contracted_acres`, rounded to two decimal places), refreshes its `projected_total_billable`, and increments the agreement's own `version` by 1.

        Design: Corner/entities/enrolled_block_is_reverse_reachable_from_its_contract
        """
        s = fx.setup_ranch_with_block(api)
        other_block = fx.create_block_b14(api, s.vineyard["id"])
        contract = fx.create_contract(api, s.vineyard["id"])

        enrolled = fx.enroll_block(api, contract["id"], s.block["id"], 12.5)

        assert_block(enrolled)
        assert enrolled["contract_id"] == contract["id"]
        assert_money(enrolled["contracted_acres"], 12.5, "contracted_acres")
        assert enrolled["per_acre_fee_override"] is None
        assert_version(enrolled, 2, "block")

        rows, _ = validate_paginated(
            api.list_blocks(fx.VM, {"contract_id": contract["id"]})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == s.block["id"]
        assert fx.read_block(api, other_block["id"])["contract_id"] is None

        contract = fx.read_contract(api, contract["id"])
        assert contract["enrolled_block_count"] == 1
        assert_money(contract["total_contracted_acres"], 12.5,
                     "total_contracted_acres")
        assert_money(contract["projected_total_billable"], 11875.00,
                     "projected_total_billable")

    def test_enroll_block_returns_the_updated_block_carrying_its_fee_override(self, api):
        """The `VineyardManager` names the `block_id`, states the `contracted_acres` being enrolled, and may supply a `per_acre_fee_override` — a block-specific per-acre management fee that displaces the agreement's `per_acre_annual_fee` for that block alone; omitting it leaves the field null, which means the contract rate applies. The updated block is what comes back to the caller.

        Design: Corner/endpoints/enroll_block_returns_updated_block_with_contract_link
        """
        s = fx.setup_ranch_with_block(api)
        block_b14 = fx.create_block_b14(api, s.vineyard["id"], acres=4.0)
        contract = fx.create_contract(api, s.vineyard["id"])

        first = fx.enroll_block(api, contract["id"], s.block["id"], 12.5)
        assert first["contract_id"] == contract["id"]
        assert_money(first["contracted_acres"], 12.5, "contracted_acres")
        assert first["per_acre_fee_override"] is None

        second = fx.enroll_block(api, contract["id"], block_b14["id"], 4.0,
                                 per_acre_fee_override=1100.00)
        assert_block(second)
        assert second["contract_id"] == contract["id"]
        assert_money(second["contracted_acres"], 4.0, "contracted_acres")
        assert_money(second["per_acre_fee_override"], 1100.00,
                     "per_acre_fee_override")
        assert_version(second, 2, "block")

        contract = fx.read_contract(api, contract["id"])
        assert contract["enrolled_block_count"] == 2
        assert_money(contract["total_contracted_acres"], 16.5,
                     "total_contracted_acres")
        assert_version(contract, 3, "agreement")
        assert contract["contract_status"] == "DRAFT"

    def test_enrolling_a_block_of_another_ranch_is_refused(self, api):
        """The operation is refused with `ERR_CONTRACT_NOT_DRAFT` once the agreement has left `DRAFT`, with `ERR_VINEYARD_MISMATCH` when the block belongs to a different ranch than the agreement covers, and with `ERR_BLOCK_ALREADY_ENROLLED` when the block's `contract_id` is already set.

        Design: Corner/validations/enroll_block_from_another_vineyard_rejected
        """
        ranch_a = fx.create_vineyard(api)
        fx.create_block(api, ranch_a["id"])
        ranch_b = fx.create_vineyard(api, name="Salinas Bench",
                                     owner_legal_name="Salinas Bench Farms LLC",
                                     ava_region="Monterey",
                                     client_contact_email="ops@salinas.example")
        foreign_block = fx.create_block(
            api, ranch_b["id"], block_code="S-01", variety="PINOT_NOIR",
            clone="FPS-23", rootstock="ROOTSTOCK_SO4", trellis_system="VSP",
            planting_year=2016, vine_spacing_ft=4.0, row_spacing_ft=8.0, acres=6.0,
        )
        contract = fx.create_contract(api, ranch_a["id"])

        validate_error(
            api.enroll_block(contract["id"],
                             f.enroll_block_payload(foreign_block["id"], 6.0), fx.VM),
            ApiErrorId.ERR_VINEYARD_MISMATCH,
        )

        contract = fx.read_contract(api, contract["id"])
        assert contract["enrolled_block_count"] == 0
        assert_money(contract["total_contracted_acres"], 0.00,
                     "total_contracted_acres")
        assert_version(contract, 1, "agreement")
        assert fx.read_block(api, foreign_block["id"])["contract_id"] is None

    def test_enrolling_a_block_a_second_time_is_refused(self, api):
        """A block may only ever be enrolled under one agreement, and `contract_id` is never cleared once written.

        Design: Corner/validations/enroll_block_already_under_a_contract_rejected
        """
        s = fx.setup_enrolled_block(api)
        second_contract = fx.create_contract(
            api, s.vineyard["id"], per_acre_annual_fee=1100.00,
            cost_pass_through_pct=0.10, quality_incentive_per_ton=50.00,
            quality_brix_threshold=25.0, period_overhead_pool=2000.00,
        )

        validate_error(
            api.enroll_block(second_contract["id"],
                             f.enroll_block_payload(s.block["id"], 12.5), fx.VM),
            ApiErrorId.ERR_BLOCK_ALREADY_ENROLLED,
        )

        second_contract = fx.read_contract(api, second_contract["id"])
        assert second_contract["enrolled_block_count"] == 0
        assert_version(second_contract, 1, "second agreement")

        first_contract = fx.read_contract(api, s.contract["id"])
        assert first_contract["enrolled_block_count"] == 1
        assert_money(first_contract["total_contracted_acres"], 12.5,
                     "total_contracted_acres")
        assert fx.read_block(api, s.block["id"])["contract_id"] == s.contract["id"]


class TestCountersignature:
    """PRD §3.2 and §2.2 — countersignature is the client's move and the client's alone."""

    def test_countersignature_moves_the_agreement_active_and_stores_the_name(self, api):
        """A `ClientOwner` whose `X-User-ID` matches the agreement's `vineyard_id` supplies a `client_signature_name`, which drives the agreement `DRAFT → ACTIVE`, stores the supplied name, and increments the agreement's `version` by 1.

        Design: Corner/state_machines/contract_activate_from_draft_records_signature_and_bumps_version
        """
        s = fx.setup_enrolled_block(api)
        assert_version(s.contract, 2, "agreement before countersignature")

        data = validate_success(
            api.activate_contract(s.contract["id"], f.activate_contract_payload(),
                                  make_client_owner_headers(s.vineyard["id"]))
        )

        assert_contract(data)
        assert data["contract_status"] == "ACTIVE"
        assert data["client_signature_name"] == "Dana Ridgecrest"
        assert_version(data, 3, "agreement")
        assert data["enrolled_block_count"] == 1
        assert data["settled_period_count"] == 0

    def test_countersigning_an_agreement_with_nothing_enrolled_is_refused(self, api):
        """An agreement with nothing enrolled cannot be activated: when `enrolled_block_count` is 0 the attempt is refused with `ERR_NO_ENROLLED_BLOCKS`.

        Design: Corner/state_machines/contract_activate_without_enrolled_blocks_rejected
        """
        s = fx.setup_ranch_with_block(api)
        contract = fx.create_contract(api, s.vineyard["id"])

        validate_error(
            api.activate_contract(contract["id"], f.activate_contract_payload(),
                                  make_client_owner_headers(s.vineyard["id"])),
            ApiErrorId.ERR_NO_ENROLLED_BLOCKS,
        )

        contract = fx.read_contract(api, contract["id"])
        assert contract["contract_status"] == "DRAFT"
        assert contract["client_signature_name"] is None
        assert_version(contract, 1, "agreement")

    def test_countersigning_an_already_active_agreement_is_refused(self, api):
        """An agreement that has already left `DRAFT` is refused with `ERR_CONTRACT_NOT_DRAFT`.

        Design: Corner/state_machines/contract_activate_twice_returns_contract_not_draft
        """
        s = fx.setup_enrolled_block(api)
        activated = fx.activate_contract(api, s.contract["id"], s.vineyard["id"])
        assert_version(activated, 3, "agreement after countersignature")

        validate_error(
            api.activate_contract(s.contract["id"], f.activate_contract_payload(),
                                  make_client_owner_headers(s.vineyard["id"])),
            ApiErrorId.ERR_CONTRACT_NOT_DRAFT,
        )

        contract = fx.read_contract(api, s.contract["id"])
        assert contract["contract_status"] == "ACTIVE"
        assert contract["client_signature_name"] == "Dana Ridgecrest"
        assert_version(contract, 3, "agreement")

    def test_countersigning_by_the_owner_of_another_ranch_is_refused(self, api):
        """Reading a ranch, reading or listing contracts, and countersigning a contract all require that the reached `Vineyard` identifier equal `X-User-ID`; a mismatch is `ERR_VINEYARD_OWNERSHIP_REQUIRED` (HTTP 403).

        Design: Corner/rbac/client_owner_of_another_vineyard_cannot_activate_contract
        """
        s = fx.setup_enrolled_block(api)
        other_ranch = fx.create_vineyard(
            api, name="Salinas Bench", owner_legal_name="Salinas Bench Farms LLC",
            ava_region="Monterey", client_contact_email="ops@salinas.example",
        )

        validate_error(
            api.activate_contract(s.contract["id"], f.activate_contract_payload(),
                                  make_client_owner_headers(other_ranch["id"])),
            ApiErrorId.ERR_VINEYARD_OWNERSHIP_REQUIRED,
        )

        contract = fx.read_contract(api, s.contract["id"])
        assert contract["contract_status"] == "DRAFT"
        assert contract["client_signature_name"] is None

        activated = validate_success(
            api.activate_contract(s.contract["id"], f.activate_contract_payload(),
                                  make_client_owner_headers(s.vineyard["id"]))
        )
        assert activated["contract_status"] == "ACTIVE"
        assert activated["client_signature_name"] == "Dana Ridgecrest"


class TestAgreementPathResolution:
    """PRD §2.5 — each entity has its own 404 code."""

    def test_reading_an_unknown_agreement_id_reports_contract_not_found(self, api):
        """Each entity has its own 404 code: a missing `Vineyard` yields `ERR_VINEYARD_NOT_FOUND`, a missing `Block` yields `ERR_BLOCK_NOT_FOUND`, a missing `CustomFarmingContract` yields `ERR_CONTRACT_NOT_FOUND`.

        Design: Corner/errors/unknown_contract_path_id_returns_contract_not_found
        """
        s = fx.setup_ranch(api)
        known = fx.create_contract(api, s.vineyard["id"])

        response = api.get_contract(MISSING_UUID_A, fx.VM)
        error = validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""

        assert fx.read_contract(api, known["id"])["contract_status"] == "DRAFT"
