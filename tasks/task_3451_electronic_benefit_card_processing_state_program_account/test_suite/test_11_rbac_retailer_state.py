"""Authentication and authorization: header presence, role-per-endpoint,
entity-backed ownership, and the retailer APPROVED/SUSPENDED gate on
authorizations and item-file uploads."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_cardholder_headers,
    make_retailer_system_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting party, and `X-User-Role`, declaring the capacity
        in which it acts. The system recognizes exactly four roles, spelled
        exactly as follows: `StateAdmin`, `CardholderServices`, `Cardholder`,
        and `RetailerSystem`. A request missing either header, or presenting a
        role value outside those four, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        fx.create_contract(api)  # some state exists; auth still comes first
        for bad_headers in (
            {},                          # neither header
            headers_without_role(),      # X-User-ID only
            headers_without_user_id(),   # X-User-Role only
            headers_with_unknown_role(), # role outside the four
        ):
            resp = api.list_purses(bad_headers)
            validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestOwnership:
    def test_cardholder_cannot_read_other_case_purse(self, api):
        """PRD §2.1: "When `X-User-Role` is `Cardholder`, `X-User-ID` is the
        `id` of the acting `CaseAccount`; ownership checks on any resource that
        references a case compare the resource's case foreign-key field to
        `X-User-ID`, and a cardholder touching another case's resources is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/cardholder_cannot_read_other_case_purse
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx, case_identifier="0000000000")          # case A
        fx.add_case(api, ctx, case_identifier="0000000001", key="case_b")
        purse_b = fx.get_purse_for_program(api, ctx.case_b["id"],
                                           ctx.programs["FOOD"]["id"])
        resp = api.get_purse(purse_b["id"],
                             make_cardholder_headers(ctx.case["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_cardholder_cannot_create_program(self, api):
        """PRD §2.1: "A request whose role is not among the roles authorized for
        the endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/cardholder_cannot_create_program
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)
        # POST /ebt/programs is authorized for StateAdmin alone (PRD §4).
        resp = api.create_program(
            f.program_payload(ctx.contract["id"], program_type="CASH"),
            make_cardholder_headers(ctx.case["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRetailerStateGate:
    def test_purchase_rejected_when_retailer_suspended(self, api):
        """PRD §3.2: "A `SUSPENDED` retailer rejects new authorizations and
        item-file uploads with `ERR_RETAILER_NOT_ACTIVE`, while its existing
        transactions and settlement batches are unaffected."
        PRD §3.2: "A `StateAdmin` may suspend an `APPROVED` retailer or
        reinstate a `SUSPENDED` one, incrementing the retailer's `version` by 1
        on each change"

        Design: Difficulty/cross_entity_state_dependency/purchase_rejected_when_retailer_suspended
        """
        ctx = fx.setup_pos_ready(api)
        retailer_id = ctx.retailer["id"]
        fx.set_retailer_status(api, retailer_id, "SUSPENDED")
        resp = api.create_authorization(
            retailer_id,
            f.purchase_payload(ctx.card["id"],
                               items=[f.purchase_item(unit_price_cents=100)]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_RETAILER_NOT_ACTIVE)
        # Reinstatement restores the very same purchase.
        fx.set_retailer_status(api, retailer_id, "APPROVED")
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])[0]
        assert txn["total_cents"] == 100

    def test_item_file_upload_rejected_when_retailer_suspended(self, api):
        """PRD §3.2: "A `SUSPENDED` retailer rejects new authorizations and
        item-file uploads with `ERR_RETAILER_NOT_ACTIVE`, while its existing
        transactions and settlement batches are unaffected."

        Design: Difficulty/cross_entity_state_dependency/purchase_rejected_when_retailer_suspended
        """
        ctx = fx.setup_pos_ready(api)
        retailer_id = ctx.retailer["id"]
        fx.set_retailer_status(api, retailer_id, "SUSPENDED")
        resp = api.upload_item_file(
            retailer_id,
            f.item_file_payload([f.item_entry(upc="333333333333")]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_RETAILER_NOT_ACTIVE)
        fx.set_retailer_status(api, retailer_id, "APPROVED")
        resp2 = api.upload_item_file(
            retailer_id,
            f.item_file_payload([f.item_entry(upc="333333333333")]),
            make_retailer_system_headers(retailer_id),
        )
        created = validate_success(resp2, 201)
        assert created["created_count"] == 1
