"""Not-found errors, uniqueness violations, RBAC denials, dispute eligibility,
header validation, and the audit trail."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_contact,
    add_product,
    add_record_item,
    add_responder,
    add_verified_item,
    create_member_payload,
    create_product_payload,
    create_responder_payload,
    enroll_member,
    make_member_headers,
    place_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ZERO_UUID = NON_EXISTENT_UUID


class TestNotFoundErrors:
    def test_unknown_order_id_returns_order_not_found(self, api):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_order_id_returns_order_not_found
        """
        set_clock(api=api)
        member = enroll_member(full_name="No Order", email="no@x.com", dob="1988-08-08", api=api)
        resp = api.confirm_order(
            member["id"], ZERO_UUID,
            {"expected_member_version": member["version"]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)

    def test_unknown_product_id_returns_product_not_found(self, api, admin_headers):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_product_id_returns_product_not_found
        """
        resp = api.get_product(ZERO_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)

    def test_unknown_ticket_id_returns_ticket_not_found(self, api, verifier_headers):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_ticket_id_returns_ticket_not_found
        """
        resp = api.resolve_verification_ticket(
            ZERO_UUID, {"decision": "APPROVE", "decision_note": "x"}, verifier_headers
        )
        validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FOUND.value)

    def test_unknown_record_item_id_returns_record_item_not_found(self, api):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_record_item_id_returns_record_item_not_found
        """
        set_clock(api=api)
        member = enroll_member(full_name="No Item", email="ni@x.com", dob="1990-01-01", api=api)
        resp = api.get_record_item(member["id"], ZERO_UUID, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_RECORD_ITEM_NOT_FOUND.value)

    def test_unknown_contact_id_returns_contact_not_found(self, api):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_contact_id_returns_contact_not_found
        """
        set_clock(api=api)
        member = enroll_member(full_name="No Contact", email="nc@x.com", dob="1990-01-01", api=api)
        resp = api.remove_contact(member["id"], ZERO_UUID, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CONTACT_NOT_FOUND.value)

    def test_unknown_directive_id_returns_directive_not_found(self, api):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_directive_id_returns_directive_not_found
        """
        set_clock(api=api)
        member = enroll_member(full_name="No Dir", email="nd@x.com", dob="1990-01-01", api=api)
        resp = api.revoke_directive(member["id"], ZERO_UUID, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_DIRECTIVE_NOT_FOUND.value)

    def test_unknown_case_id_returns_case_not_found(self, api, hotline_headers):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_case_id_returns_case_not_found
        """
        set_clock(api=api)
        member = enroll_member(full_name="No Case", email="ncase@x.com", dob="1990-01-01", api=api)
        resp = api.resolve_wandering_case(member["id"], ZERO_UUID, {"outcome": "REUNITED"}, hotline_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND.value)

    def test_unknown_dispute_id_returns_dispute_not_found(self, api, verifier_headers):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_dispute_id_returns_dispute_not_found
        """
        resp = api.claim_dispute_for_review(ZERO_UUID, verifier_headers)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_FOUND.value)

    def test_unknown_responder_id_returns_responder_not_found(self, api, admin_headers):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/errors/unknown_responder_id_returns_responder_not_found
        """
        resp = api.revoke_responder(ZERO_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESPONDER_NOT_FOUND.value)


class TestUniquenessViolations:
    def test_duplicate_responder_credential_rejected(self, api, admin_headers):
        """PRD §3.6: "Credentials are registered by a `PlatformAdmin` with an
        `agency_name`, a globally unique `credential_code` (duplicates rejected
        with `ERR_DUPLICATE_CREDENTIAL`), an `access_tier` of `BASIC` or `FULL`,
        and an `expires_on`."

        Design: Corner/errors/duplicate_responder_credential_rejected
        """
        set_clock(api=api)
        add_responder(api=api, agency_name="A", credential_code="EMS-DUP",
                      access_tier="BASIC", expires_on="2027-01-01")
        resp = api.create_responder(
            create_responder_payload(agency_name="B", credential_code="EMS-DUP",
                                     access_tier="FULL", expires_on="2027-06-01"),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CREDENTIAL.value)

    def test_duplicate_product_sku_rejected(self, api, admin_headers):
        """PRD §3.4: "The product catalog is administered by a `PlatformAdmin`, who
        registers each `IDProduct` with a unique `product_sku`, a display
        `product_name`, a `base_price_cents` at or above zero, and a
        `max_engrave_chars` of at least one describing how much text fits on the
        engraving surface. A duplicate SKU is rejected with `ERR_DUPLICATE_SKU`."

        Design: Corner/errors/duplicate_product_sku_rejected
        """
        add_product(api=api, product_sku="DUP-SKU", product_name="One",
                    base_price_cents=100, max_engrave_chars=10)
        resp = api.create_product(
            create_product_payload(product_sku="DUP-SKU", product_name="Two",
                                   base_price_cents=200, max_engrave_chars=20),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)


class TestHeaderAndRbac:
    def test_missing_user_context_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty value
        in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_returns_400
        """
        resp = api.list_members({"X-User-ID": "", "X-User-Role": "PlatformAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_missing_role_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty value
        in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_returns_400
        """
        resp = api.list_members({"X-User-ID": "admin-1"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_member_cannot_resolve_verification_ticket(self, api, verifier_headers):
        """PRD §2.1: "Once headers are present, the role is checked against the
        endpoint's authorization list; a role not permitted for the endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: `POST /medical-id/verification-tickets/{ticketId}/resolve` is
        authorized for `RecordVerifier` only.

        Design: Corner/rbac/member_cannot_resolve_verification_ticket
        """
        from test_helpers import open_ticket_for_item

        set_clock(api=api)
        member = enroll_member(full_name="Rachel Rbac", email="rachel@x.com", dob="1993-03-03", api=api)
        item = add_record_item(member["id"], api=api, item_kind="ALLERGY", label="Sulfa",
                               detail="rash", severity="MEDIUM", provider_document_ref="doc-s")
        ticket = open_ticket_for_item(member["id"], item["id"], api=api)
        resp = api.resolve_verification_ticket(
            ticket["id"],
            {"decision": "APPROVE", "decision_note": "self approve"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
        ticket_after = validate_success(api.get_verification_ticket(ticket["id"], verifier_headers))
        assert ticket_after["status"] == "OPEN"

    def test_fulfillment_agent_cannot_create_products(self, api, fulfillment_headers):
        """PRD §2.1: "Once headers are present, the role is checked against the
        endpoint's authorization list; a role not permitted for the endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: `POST /medical-id/products` is authorized for `PlatformAdmin` only.

        Design: Corner/rbac/fulfillment_agent_cannot_create_products
        """
        resp = api.create_product(
            create_product_payload(product_sku="NO-1", product_name="Nope",
                                   base_price_cents=100, max_engrave_chars=10),
            fulfillment_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_member_cannot_act_on_other_members_resources(self, api):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of
        the acting `Member`; ownership checks on any resource that references a
        `Member` compare the resource's foreign-key field to `X-User-ID`. A
        `Member` may act only on their own record — self-service operations on
        another member's resources are rejected with `ERR_GUARDIANSHIP_REQUIRED`."

        Design: Corner/rbac/member_cannot_act_on_other_members_resources
        """
        set_clock(api=api)
        member_a = enroll_member(full_name="Aaa", email="aaa@x.com", dob="1980-01-01", api=api)
        member_b = enroll_member(full_name="Bbb", email="bbb@x.com", dob="1980-01-02", api=api)
        resp = api.create_record_item(
            member_b["id"],
            {"item_kind": "CONDITION", "label": "X", "detail": "y",
             "severity": "LOW", "provider_document_ref": "doc-x"},
            make_member_headers(member_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GUARDIANSHIP_REQUIRED.value)


class TestDisputeEligibility:
    def test_dispute_against_other_members_item_rejected(self, api):
        """PRD §3.9: "The disputed item must belong to the member in the path and
        must not be `SUPERSEDED`; otherwise the dispute is rejected with
        `ERR_RECORD_ITEM_NOT_DISPUTABLE` (HTTP 409)."

        Design: Corner/validations/dispute_against_other_members_item_rejected
        """
        set_clock(api=api)
        member_a = enroll_member(full_name="A Member", email="am@x.com", dob="1980-01-01", api=api)
        member_b = enroll_member(full_name="B Member", email="bm@x.com", dob="1980-01-02", api=api)
        item_b = add_record_item(member_b["id"], api=api, item_kind="ALLERGY", label="Iodine",
                                 detail="contrast", severity="HIGH", provider_document_ref="doc-io")
        resp = api.create_dispute(
            member_a["id"],
            {"record_item_id": item_b["id"], "claim_text": "not mine"},
            make_member_headers(member_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RECORD_ITEM_NOT_DISPUTABLE.value)

    def test_dispute_against_superseded_item_rejected(self, api):
        """PRD §3.9: "The disputed item must belong to the member in the path and
        must not be `SUPERSEDED`; otherwise the dispute is rejected with
        `ERR_RECORD_ITEM_NOT_DISPUTABLE` (HTTP 409)."

        Design: Corner/validations/dispute_against_other_members_item_rejected
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        item = add_verified_item(member["id"], api=api, label="OldLabel", severity="HIGH")
        fresh = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        validate_success(
            api.supersede_record_item(
                member["id"], item["id"],
                {"replacement_label": "NewLabel", "replacement_detail": "c",
                 "provider_document_ref": "doc-n", "expected_member_version": fresh["version"]},
                make_member_headers(member["id"]),
            )
        )
        resp = api.create_dispute(
            member["id"],
            {"record_item_id": item["id"], "claim_text": "stale item"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RECORD_ITEM_NOT_DISPUTABLE.value)


class TestAuditTrail:
    def test_audit_trail_records_business_actions(self, api):
        """PRD §2.9: "Every state-changing workflow in the system appends an
        `AuditEvent` row naming the acting role (`actor_role`, the request's
        `X-User-Role`), the actor (`actor_id`, the request's `X-User-ID`), a
        machine `action` name, and a `detail` payload snapshot carrying entity ids
        and before/after field values."
        PRD §2.9: "Machine action names include `ENROLL`, `RENEWAL`, `LAPSE`,
        `CANCEL`, `RECORD_VERIFY`, `RECORD_REJECT`, `RECORD_RESUBMIT`,
        `RECORD_SUPERSEDE`, `GUARDIAN_LINK`, `GUARDIAN_REVOKE`, `CONTACT_ADD`,
        `CONTACT_REMOVE`, `DIRECTIVE_STORE`, `DIRECTIVE_RELEASE`,
        `DIRECTIVE_REVOKE`, `ORDER_CONFIRM`, `ORDER_ENGRAVE`, `ORDER_SHIP`,
        `ORDER_CANCEL`, `ACCESS_GRANT`, `ACCESS_RATE_FLAG`, `WANDERING_OPEN`,
        `WANDERING_RESOLVE`, `DISPUTE_OPEN`, `DISPUTE_CLAIM`, `DISPUTE_RETURN`,
        `DISPUTE_RESOLVE`, and `DISPUTE_DISMISS`."

        Design: Corner/endpoints/audit_trail_records_business_actions
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="AU-1", product_name="Audit Band",
                              base_price_cents=1000, max_engrave_chars=20)
        member = enroll_member(full_name="Abe Audit", email="abe@x.com", dob="1982-02-02", api=api)
        add_contact(member["id"], api=api, contact_name="C",
                    phone="+15550000001", priority_rank=1)
        place_order(member["id"], product["id"], api=api,
                    engraving_text="Abe", engrave_mode="MANUAL")

        resp = api.list_member_audit_events(member["id"], make_member_headers(member["id"]))
        events, _ = validate_paginated(resp)
        actions = [e["action"] for e in events]
        assert "ENROLL" in actions
        assert "CONTACT_ADD" in actions
        contact_add = next(e for e in events if e["action"] == "CONTACT_ADD")
        assert contact_add["actor_role"] == "Member"
        assert contact_add["actor_id"] == member["id"]
        created_ats = [e["created_at"] for e in events]
        assert created_ats == sorted(created_ats), "events are ordered by created_at ascending"

    def test_audit_trail_records_renewal_action(self, api):
        """PRD §2.9: "Machine action names include `ENROLL`, `RENEWAL`, `LAPSE`,
        `CANCEL`, `RECORD_VERIFY`, `RECORD_REJECT`, `RECORD_RESUBMIT`,
        `RECORD_SUPERSEDE`, `GUARDIAN_LINK`, `GUARDIAN_REVOKE`, `CONTACT_ADD`,
        `CONTACT_REMOVE`, `DIRECTIVE_STORE`, `DIRECTIVE_RELEASE`,
        `DIRECTIVE_REVOKE`, `ORDER_CONFIRM`, `ORDER_ENGRAVE`, `ORDER_SHIP`,
        `ORDER_CANCEL`, `ACCESS_GRANT`, `ACCESS_RATE_FLAG`, `WANDERING_OPEN`,
        `WANDERING_RESOLVE`, `DISPUTE_OPEN`, `DISPUTE_CLAIM`, `DISPUTE_RETURN`,
        `DISPUTE_RESOLVE`, and `DISPUTE_DISMISS`."

        Design: Corner/endpoints/audit_trail_records_business_actions
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        validate_success(
            api.renew_member(member["id"], {"amount_paid_cents": 4000}, make_member_headers(member["id"]))
        )
        resp = api.list_member_audit_events(member["id"], make_member_headers(member["id"]))
        events, _ = validate_paginated(resp)
        actions = [e["action"] for e in events]
        assert "ENROLL" in actions
        assert "RENEWAL" in actions
