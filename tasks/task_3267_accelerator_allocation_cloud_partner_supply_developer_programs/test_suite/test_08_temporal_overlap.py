"""Resource temporal overlap: the three interval semantics the API uses for
supply contracts, preview grants and confidentiality acknowledgements.
"""
from test_helpers import (
    api, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_stack_license, create_supply_contract,
    create_membership, create_confidentiality_ack, create_preview_grant,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
COMPLIANCE = TEST_USERS["supply_compliance_officer_headers"]
LIFECYCLE = TEST_USERS["lifecycle_program_manager_headers"]


class TestSupplyContractWindows:
    """Contract windows are half-open over months, so adjacency is legal."""

    def test_a_contract_starting_inside_the_existing_month_collides(self):
        """PRD §3.9: "Two contracts for the same SKU collide when their half-open
        windows intersect".

        Design: Difficulty/resource_temporal_overlap/supply_contract_half_open_month_windows_allow_adjacency
        """
        startup_clock()
        partner = create_validated_partner()
        product = create_product()
        create_supply_contract(product["id"], partner["id"], start_month="2026-01",
                              end_month="2026-03")

        response = api.create_supply_contract({
            "product_sku_id": product["id"],
            "partner_id": partner["id"],
            "start_month": "2026-03",
            "end_month": "2026-05",
            "contracted_units": 300,
        }, LIFECYCLE)
        validate_error(response, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)

    def test_a_contract_starting_the_month_after_the_last_contracted_month_is_accepted(self):
        """PRD §3.9: "the inclusive boundary case — a new contract whose start month is
        exactly the existing contract's end month plus one month — is reported as
        `ERR_CONTRACT_WINDOW_OVERLAP`."
        PRD §3.9: "The window is half-open: it runs from the first day of the start
        month inclusive to the first day of the month after the end month exclusive."

        Design: Difficulty/resource_temporal_overlap/supply_contract_half_open_month_windows_allow_adjacency
        """
        startup_clock()
        partner = create_validated_partner()
        product = create_product()
        create_supply_contract(product["id"], partner["id"], start_month="2026-01",
                              end_month="2026-03")

        adjacent = validate_success(api.create_supply_contract({
            "product_sku_id": product["id"],
            "partner_id": partner["id"],
            "start_month": "2026-04",
            "end_month": "2026-06",
            "contracted_units": 300,
        }, LIFECYCLE), 201)
        assert adjacent["start_month"] == "2026-04"

        contracts, meta = validate_paginated(api.list_supply_contracts(
            LIFECYCLE, params={"product_sku_id": product["id"]}))
        assert meta["total_count"] == 2, (
            f"both contracts are on file, got total_count {meta['total_count']}"
        )


class TestPreviewGrantWindows:
    """Preview grant windows are closed day spans extended by a 30-day buffer."""

    def _membership_with_preview_stack(self):
        partner = create_validated_partner()
        product = create_product()
        stack = create_stack_license(product["id"], license_code="SL-PREV-1",
                                     entitlement_units=25, min_package_version="2.0.0-preview",
                                     preview_stack_flag=True)
        membership = create_membership(partner["id"], requested_tier="ELITE")
        get_success_data(api.evaluate_membership(membership["id"], PROGRAM))
        return partner, product, stack, membership

    def test_a_grant_starting_inside_the_buffered_window_collides(self):
        """PRD §3.6: "a grant whose window collides with an existing grant for the same
        partner and SKU is refused with `ERR_PREVIEW_GRANT_WINDOW_OVERLAP`."
        PRD §3.6: "The collision test treats the windows as closed day spans from the
        boundary to the expiry, applying a 30-day buffer to the existing grant's end".

        Design: Difficulty/resource_temporal_overlap/preview_grant_closed_day_windows_with_buffer
        """
        startup_clock()
        partner, product, stack, membership = self._membership_with_preview_stack()
        ack = create_confidentiality_ack(membership["id"], stack["id"])
        create_preview_grant(stack["id"], ack["id"], device_serial="EVAL-0001",
                             commitment_boundary_at="2026-09-01T00:00:00Z",
                             commitment_expires_at="2026-09-30T00:00:00Z")

        response = api.create_preview_grant({
            "stack_license_id": stack["id"],
            "device_serial": "EVAL-0002",
            "commitment_boundary_at": "2026-10-25T00:00:00Z",
            "commitment_expires_at": "2026-11-24T00:00:00Z",
            "confidentiality_ack_id": ack["id"],
        }, PROGRAM)
        validate_error(response, ApiErrorId.ERR_PREVIEW_GRANT_WINDOW_OVERLAP)

    def test_a_grant_starting_past_the_buffer_is_accepted(self):
        """PRD §3.6: "a new grant whose start falls on the buffered end minus one day
        counts as an overlap."
        PRD §3.6: "a span of 60 days from the boundary".

        Design: Difficulty/resource_temporal_overlap/preview_grant_closed_day_windows_with_buffer
        """
        startup_clock()
        partner, product, stack, membership = self._membership_with_preview_stack()
        ack = create_confidentiality_ack(membership["id"], stack["id"])
        create_preview_grant(stack["id"], ack["id"], device_serial="EVAL-0001",
                             commitment_boundary_at="2026-09-01T00:00:00Z",
                             commitment_expires_at="2026-09-30T00:00:00Z")

        accepted = api.create_preview_grant({
            "stack_license_id": stack["id"],
            "device_serial": "EVAL-0003",
            "commitment_boundary_at": "2026-11-05T00:00:00Z",
            "commitment_expires_at": "2026-12-05T00:00:00Z",
            "confidentiality_ack_id": ack["id"],
        }, PROGRAM)
        validate_success(accepted, 201)

    def test_a_back_filled_grant_beginning_before_the_existing_window_is_accepted(self):
        """PRD §3.6: "a new grant whose start falls on the buffered end minus one day
        counts as an overlap" — only the end is buffered, so an earlier window does not
        collide.

        Design: Difficulty/resource_temporal_overlap/preview_grant_closed_day_windows_with_buffer
        """
        startup_clock()
        partner, product, stack, membership = self._membership_with_preview_stack()
        ack = create_confidentiality_ack(membership["id"], stack["id"])
        create_preview_grant(stack["id"], ack["id"], device_serial="EVAL-0001",
                             commitment_boundary_at="2026-09-01T00:00:00Z",
                             commitment_expires_at="2026-09-30T00:00:00Z")

        backfilled = api.create_preview_grant({
            "stack_license_id": stack["id"],
            "device_serial": "EVAL-0004",
            "commitment_boundary_at": "2026-07-01T00:00:00Z",
            "commitment_expires_at": "2026-08-01T00:00:00Z",
            "confidentiality_ack_id": ack["id"],
        }, PROGRAM)
        validate_success(backfilled, 201)


class TestConfidentialityAckWindows:
    """Acknowledgement windows are open month windows with a one-month grace tail."""

    def _membership_with_preview_stack(self):
        partner = create_validated_partner()
        product = create_product()
        stack = create_stack_license(product["id"], license_code="SL-PREV-1",
                                     entitlement_units=25, min_package_version="2.0.0-preview",
                                     preview_stack_flag=True)
        membership = create_membership(partner["id"], requested_tier="PREFERRED")
        get_success_data(api.evaluate_membership(membership["id"], PROGRAM))
        return partner, product, stack, membership

    def test_an_acknowledgement_the_next_month_collides(self):
        """PRD §3.6: "Two acknowledgements for the same stack license are compared as
        open month windows that permit a single month of adjacency: the collision is
        refused with `ERR_NDA_WINDOW_OVERLAP` only when the new window starts strictly
        before the existing window's end month minus one."

        Design: Difficulty/resource_temporal_overlap/confidentiality_ack_open_month_windows_with_grace_tail
        """
        startup_clock()
        partner, product, stack, membership = self._membership_with_preview_stack()
        create_confidentiality_ack(membership["id"], stack["id"],
                                   acknowledged_at="2026-09-01T00:00:00Z")

        response = api.create_confidentiality_ack({
            "membership_id": membership["id"],
            "stack_license_id": stack["id"],
            "acknowledged_at": "2026-10-05T00:00:00Z",
        }, COMPLIANCE)
        validate_error(response, ApiErrorId.ERR_NDA_WINDOW_OVERLAP)

    def test_an_acknowledgement_two_months_later_clears_the_grace_tail(self):
        """PRD §3.6: "the collision is refused with `ERR_NDA_WINDOW_OVERLAP` only when the
        new window starts strictly before the existing window's end month minus one."

        Design: Difficulty/resource_temporal_overlap/confidentiality_ack_open_month_windows_with_grace_tail
        """
        startup_clock()
        partner, product, stack, membership = self._membership_with_preview_stack()
        first = create_confidentiality_ack(membership["id"], stack["id"],
                                           acknowledged_at="2026-09-01T00:00:00Z")
        assert first["ack_status"] == "BOUND"

        accepted = api.create_confidentiality_ack({
            "membership_id": membership["id"],
            "stack_license_id": stack["id"],
            "acknowledged_at": "2026-11-05T00:00:00Z",
        }, COMPLIANCE)
        validate_success(accepted, 201)