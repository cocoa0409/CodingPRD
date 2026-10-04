"""Authentication, role permission, entity-backed ownership, and existence
checks — in the fixed evaluation order of PRD §2.10."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_donation_payload,
    create_donation_site_payload,
    create_org,
    create_site,
    make_donation_attendant_headers,
    make_member_admin_headers,
    validate_error,
)


class TestSecurity:
    def test_request_without_auth_headers_returns_unauthenticated(self, api):
        """PRD 2.1: "A request with missing headers or an undeclared role is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD 2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and a request failing an
        earlier check is rejected with that check's error even if a later check
        would also have failed:"

        Design: Corner/validations/request_without_auth_headers_returns_unauthenticated
        """
        # The path id deliberately does not exist: auth (step 2) must fire
        # before the existence check (step 5).
        resp = api_client.get_member_org(
            "00000000-0000-0000-0000-000000000000", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_store_associate_cannot_create_salvage_lot(self, api):
        """PRD 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD 3.6: "A `MemberAdmin` opens a salvage lot by naming the selling
        `member_org_id`, a `channel` of `TEXTILE_BALE`, `EWASTE`, or
        `OUTLET_BIN`, and an initial `item_ids` load."

        Design: Corner/validations/store_associate_cannot_create_salvage_lot
        """
        org = create_org("Org RB")
        resp = api_client.create_salvage_lot(
            {"member_org_id": org["id"], "channel": "OUTLET_BIN",
             "item_ids": []},
            TEST_USERS["store_associate_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_attendant_posting_at_other_site_rejected(self, api):
        """PRD 2.1: "When `X-User-Role` is `DonationAttendant`, `X-User-ID` is
        the `id` of the acting DonationSite; recording a new donation requires
        the request's `site_id` to equal `X-User-ID`, and sorting a donation
        requires the donation's own `site_id` to equal `X-User-ID`."
        PRD 2.1: "An entity-backed identity that does not match is rejected
        with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/attendant_posting_at_other_site_rejected
        """
        org = create_org("Org OM")
        site_a = create_site(org["id"], name="Site A")
        site_b = create_site(org["id"], name="Site B")
        resp = api_client.create_donation(
            create_donation_payload(site_b["id"], donor_name="Sneaky",
                                    item_count_declared=1),
            make_donation_attendant_headers(site_a["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_member_admin_of_other_org_cannot_create_site(self, api):
        """PRD 2.1: "When `X-User-Role` is `MemberAdmin`, `X-User-ID` is the
        `id` of the acting MemberOrg; ownership checks compare the member
        organization being acted on — directly, or via a child entity's
        `member_org_id` field — against `X-User-ID`."
        PRD 2.1: "An entity-backed identity that does not match is rejected
        with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/member_admin_of_other_org_cannot_create_site
        """
        org1 = create_org("Org One")
        org2 = create_org("Org Two")
        resp = api_client.create_donation_site(
            create_donation_site_payload(org2["id"], name="Intrusion"),
            make_member_admin_headers(org1["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_get_unknown_donated_item_returns_not_found(self, api):
        """PRD 2.10: "Existence of path identifiers and body-referenced foreign
        keys, validated left to right: `ERR_NOT_FOUND` (HTTP 404)."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/validations/get_unknown_donated_item_returns_not_found
        """
        resp = api_client.get_donated_item(
            "11111111-1111-1111-1111-111111111111",
            TEST_USERS["store_associate_headers"])
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["message"]
