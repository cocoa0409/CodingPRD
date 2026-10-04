"""Emergency access: disclosure scope variants, credential expiry windows,
hotline operator rules, rate flagging, suspended-member access, directive
release, and access-event shape."""
from test_helpers import (
    ApiErrorId,
    add_contact,
    add_directive,
    add_responder,
    enroll_member,
    get_member,
    grant_access,
    make_member_headers,
    make_responder_headers,
    set_clock,
    setup_member_with_verified_cognitive_condition,
    validate_error,
    validate_paginated,
    validate_success,
)


def _member_with_contact_and_directive(api, name, email, dob, cognitive=False):
    """Member (+ optional verified cognitive condition) with one contact and one
    EMERGENCY_ONLY STORED directive."""
    member = enroll_member(full_name=name, email=email, dob=dob, api=api)
    if cognitive:
        from test_helpers import add_verified_item
        add_verified_item(
            member["id"], api=api, item_kind="CONDITION", condition_kind="COGNITIVE",
            label="Dementia", detail="Alzheimer's", severity="HIGH", provider_document_ref="doc-cog",
        )
        member = get_member(member["id"], api=api)
    add_contact(member["id"], api=api, contact_name=f"{name} Kin",
                phone="+15550001111", priority_rank=1)
    directive = add_directive(member["id"], api=api, directive_type="DNR",
                              document_ref=f"dnr-{name}", release_scope="EMERGENCY_ONLY")
    return member, directive


class TestDisclosureScopeDualVariant:
    def test_disclosure_scope_standard_vs_cognitive_escalated_same_credential(self, api, admin_headers):
        """PRD §3.6: "The credential tier supplies the base scope: a `BASIC`
        credential discloses the member's conditions, medications, and allergies; a
        `FULL` credential additionally discloses emergency contacts, and discloses
        those advance directives whose `release_scope` is `EMERGENCY_AND_CONTACTS`
        or `FULL` and whose status is `STORED`."
        PRD §3.6: "The wandering/cognitive override then widens the scope: when the
        member's `has_cognitive_condition` is true, directives with `release_scope`
        `EMERGENCY_ONLY` are also disclosed regardless of tier, and contacts are
        disclosed even to a `BASIC` credential."
        PRD §3.6: "`is_escalated` is true exactly when that union exceeds what the
        credential tier alone grants — so the same lookup against a cognitively
        flagged member yields a strictly larger scope with `is_escalated` true."

        Design: Difficulty/dual_variant_calc/disclosure_scope_standard_vs_cognitive_escalated_same_credential
        """
        set_clock(api=api)
        member_a, dir_a = _member_with_contact_and_directive(
            api, "Ann Plain", "ann@x.com", "1990-06-15", cognitive=False
        )
        member_b, dir_b = _member_with_contact_and_directive(
            api, "Bob Cog", "bob@x.com", "1955-03-02", cognitive=True
        )
        assert get_member(member_b["id"], api=api)["has_cognitive_condition"] is True
        responder = add_responder(api=api, agency_name="Metro EMS", credential_code="EMS-B-001",
                                  access_tier="BASIC", expires_on="2027-01-01")

        ev_a = grant_access(responder, member_a, api=api)
        assert sorted(ev_a["disclosed_scope"]) == ["ALLERGIES", "CONDITIONS", "MEDICATIONS"], (
            f"BASIC base scope, no CONTACTS, no DIRECTIVES; got {ev_a['disclosed_scope']}"
        )
        assert ev_a["is_escalated"] is False

        ev_b = grant_access(responder, member_b, api=api)
        scope_b = set(ev_b["disclosed_scope"])
        assert {"CONDITIONS", "MEDICATIONS", "ALLERGIES", "CONTACTS", "DIRECTIVES"} <= scope_b, (
            f"cognitive escalation adds CONTACTS and DIRECTIVES; got {ev_b['disclosed_scope']}"
        )
        assert ev_b["is_escalated"] is True

        dir_a_after = validate_success(api.get_directive(dir_a["id"], admin_headers))
        assert dir_a_after["status"] == "STORED", (
            "EMERGENCY_ONLY excluded for the non-cognitive member"
        )
        dir_b_after = validate_success(api.get_directive(dir_b["id"], admin_headers))
        assert dir_b_after["status"] == "RELEASED", (
            "EMERGENCY_ONLY released under cognitive escalation"
        )

    def test_full_credential_discloses_contacts_without_escalation(self, api, admin_headers):
        """PRD §3.6: "The credential tier supplies the base scope: a `BASIC`
        credential discloses the member's conditions, medications, and allergies; a
        `FULL` credential additionally discloses emergency contacts, and discloses
        those advance directives whose `release_scope` is `EMERGENCY_AND_CONTACTS`
        or `FULL` and whose status is `STORED`."

        Design: Difficulty/dual_variant_calc/disclosure_scope_standard_vs_cognitive_escalated_same_credential
        """
        set_clock(api=api)
        member, _directive = _member_with_contact_and_directive(
            api, "Ann Full", "annf@x.com", "1990-06-15", cognitive=False
        )
        responder = add_responder(api=api, agency_name="Metro EMS", credential_code="EMS-F-001",
                                  access_tier="FULL", expires_on="2027-01-01")
        event = grant_access(responder, member, api=api)
        scope = set(event["disclosed_scope"])
        assert "CONTACTS" in scope, "FULL tier discloses emergency contacts"
        assert "DIRECTIVES" not in scope, (
            "EMERGENCY_ONLY directives are outside the FULL base scope"
        )
        assert event["is_escalated"] is False


class TestCredentialExpiryWindow:
    def test_responder_credential_expiry_date_overlap_with_access_window(self, api):
        """PRD §3.6: "The responder credential behind the presented
        `credential_code` must exist, be `ACTIVE`, and have an `expires_on`
        strictly later than the current logical date — a credential is invalid on
        or after its expiry date. A credential that is unknown, `REVOKED`, or
        expired, or a hotline lookup missing its `operator_id`, fails
        authentication with `ERR_RESPONDER_AUTH_FAILED` (HTTP 403)."

        Design: Difficulty/resource_temporal_overlap/responder_credential_expiry_date_overlap_with_access_window
        """
        set_clock(api=api)
        member = enroll_member(full_name="Omar Overlap", email="omar@x.com", dob="1982-10-10", api=api)
        r1 = add_responder(api=api, agency_name="R1 Agency", credential_code="R1-CODE",
                           access_tier="BASIC", expires_on="2026-09-02")
        r2 = add_responder(api=api, agency_name="R2 Agency", credential_code="R2-CODE",
                           access_tier="BASIC", expires_on="2026-09-03")
        from test_helpers import TEST_USERS
        validate_success(api.revoke_responder(r2["id"], TEST_USERS["platform_admin_headers"]))

        # expires_on - 1 day: GRANTED.
        event = grant_access(r1, member, api=api)
        assert event["outcome"] == "GRANTED"

        # exactly on expires_on: DENIED (exclusive boundary).
        set_clock("2026-09-02T00:00:00Z", api=api)
        resp = api.create_access_event(
            {"credential_code": "R1-CODE", "identifier_code": member["identifier_code"],
             "lookup_method": "IDENTIFIER"},
            make_responder_headers(r1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESPONDER_AUTH_FAILED.value)

        # REVOKED dominates the temporal window even though today < expires_on.
        resp2 = api.create_access_event(
            {"credential_code": "R2-CODE", "identifier_code": member["identifier_code"],
             "lookup_method": "IDENTIFIER"},
            make_responder_headers(r2["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_RESPONDER_AUTH_FAILED.value)

    def test_credential_valid_up_to_day_before_expiry(self, api):
        """PRD §3.6: "The responder credential behind the presented
        `credential_code` must exist, be `ACTIVE`, and have an `expires_on`
        strictly later than the current logical date — a credential is invalid on
        or after its expiry date."

        Design: Difficulty/resource_temporal_overlap/responder_credential_expiry_date_overlap_with_access_window
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        responder = add_responder(api=api, credential_code="EDGE-1", expires_on="2026-09-02")
        # 2026-09-01 < 2026-09-02: still valid.
        event = grant_access(responder, member, api=api)
        assert event["outcome"] == "GRANTED"
        assert event["reason_code"] is None


class TestUnknownIdentifier:
    def test_unknown_identifier_code_access_denied(self, api):
        """PRD §3.6: "If no member carries that code, or the member's status is
        `CANCELLED`, the access is denied with `ERR_MEMBER_NOT_DISCLOSABLE`
        (HTTP 409) — cancelled members are never disclosed."

        Design: Corner/errors/unknown_identifier_code_access_denied_and_logged
        """
        set_clock(api=api)
        responder = add_responder(api=api, agency_name="EmsX", credential_code="EMS-X-1",
                                  access_tier="BASIC", expires_on="2027-01-01")
        resp = api.create_access_event(
            {"credential_code": "EMS-X-1", "identifier_code": "MID-000000",
             "lookup_method": "IDENTIFIER"},
            make_responder_headers(responder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_DISCLOSABLE.value)

    def test_cancelled_member_never_disclosed(self, api):
        """PRD §2.6: "A `CANCELLED` member, by contrast, is never disclosed — see
        §3.6."
        PRD §3.6: "If no member carries that code, or the member's status is
        `CANCELLED`, the access is denied with `ERR_MEMBER_NOT_DISCLOSABLE`
        (HTTP 409) — cancelled members are never disclosed."

        Design: Corner/errors/unknown_identifier_code_access_denied_and_logged
        """
        from test_helpers import TEST_USERS

        set_clock(api=api)
        member = enroll_member(api=api)
        code = member["identifier_code"]
        validate_success(api.cancel_member(member["id"], TEST_USERS["platform_admin_headers"]))
        responder = add_responder(api=api, credential_code="EMS-X-2")
        resp = api.create_access_event(
            {"credential_code": "EMS-X-2", "identifier_code": code, "lookup_method": "IDENTIFIER"},
            make_responder_headers(responder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_DISCLOSABLE.value)


class TestHotlineOperatorRules:
    def _hotline_setup(self, api):
        set_clock(api=api)
        member = enroll_member(full_name="Hank Hotline", email="hank@x.com", dob="1977-07-07", api=api)
        responder = add_responder(api=api, agency_name="EmsH", credential_code="EMS-H-1",
                                  access_tier="FULL", expires_on="2027-01-01")
        return member, responder

    def test_hotline_lookup_requires_operator_id(self, api, hotline_headers):
        """PRD §3.6: "The hotline path requires the operator id and rejects it
        otherwise; the identifier path must carry no operator id at all."
        PRD §3.6: "A credential that is unknown, `REVOKED`, or expired, or a
        hotline lookup missing its `operator_id`, fails authentication with
        `ERR_RESPONDER_AUTH_FAILED` (HTTP 403)."

        Design: Corner/validations/hotline_lookup_requires_operator_id
        """
        member, _responder = self._hotline_setup(api)
        resp = api.create_access_event(
            {"credential_code": "EMS-H-1", "identifier_code": member["identifier_code"],
             "lookup_method": "HOTLINE"},
            hotline_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESPONDER_AUTH_FAILED.value)

    def test_hotline_lookup_with_operator_id_grants_access(self, api, hotline_headers):
        """PRD §3.6: "An emergency access begins when a `Responder` or
        `HotlineOperator` presents a `credential_code`, an `identifier_code`, a
        `lookup_method` of `IDENTIFIER` or `HOTLINE`, and — for the hotline path
        only — an `operator_id`."

        Design: Corner/validations/hotline_lookup_requires_operator_id
        """
        member, _responder = self._hotline_setup(api)
        event = validate_success(
            api.create_access_event(
                {"credential_code": "EMS-H-1", "identifier_code": member["identifier_code"],
                 "lookup_method": "HOTLINE", "operator_id": "op-9"},
                hotline_headers,
            ),
            expected_status=201,
        )
        assert event["lookup_method"] == "HOTLINE"
        assert event["operator_id"] == "op-9"
        assert event["outcome"] == "GRANTED"

    def test_identifier_lookup_with_operator_id_rejected(self, api):
        """PRD §3.6: "The hotline path requires the operator id and rejects it
        otherwise; the identifier path must carry no operator id at all."

        Design: Corner/validations/hotline_lookup_requires_operator_id
        """
        member, responder = self._hotline_setup(api)
        resp = api.create_access_event(
            {"credential_code": "EMS-H-1", "identifier_code": member["identifier_code"],
             "lookup_method": "IDENTIFIER", "operator_id": "op-9"},
            make_responder_headers(responder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestAccessEventShape:
    def test_access_event_is_immutable_no_version_field(self, api, admin_headers):
        """PRD §2.7: "Three resources are append-only logs and carry only `id` and
        `created_at` — both `updated_at` and `version` are absent: `AccessEvent`,
        `Reminder`, and `AuditEvent`."

        Design: Corner/entities/access_event_is_immutable_no_version_field
        """
        set_clock(api=api)
        member = enroll_member(full_name="Amy Audit", email="amy@x.com", dob="1985-01-01", api=api)
        responder = add_responder(api=api, agency_name="Ems", credential_code="EMS-IM-1",
                                  access_tier="BASIC", expires_on="2027-01-01")
        event = grant_access(responder, member, api=api)
        fetched = validate_success(api.get_access_event(event["id"], admin_headers))
        assert "id" in fetched and "created_at" in fetched
        assert "version" not in fetched, "append-only event carries no version"
        assert "updated_at" not in fetched, "append-only event carries no updated_at"

    def test_granted_event_has_null_reason_code_and_scope_subset(self, api, admin_headers):
        """PRD §3.6: "Denied events disclose nothing and carry a `reason_code`
        equal to the denying error id; granted events leave `reason_code` null."

        Design: Corner/entities/access_event_is_immutable_no_version_field
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        responder = add_responder(api=api, credential_code="EMS-IM-2")
        event = grant_access(responder, member, api=api)
        assert event["outcome"] == "GRANTED"
        assert event["reason_code"] is None
        assert set(event["disclosed_scope"]) <= {
            "CONDITIONS", "MEDICATIONS", "ALLERGIES", "CONTACTS", "DIRECTIVES"
        }


class TestAccessRateSoftCap:
    def _eleven_members_and_responder(self, api):
        set_clock(api=api)
        responder = add_responder(api=api, agency_name="City EMS", credential_code="EMS-F-100",
                                  access_tier="FULL", expires_on="2027-01-01")
        members = [
            enroll_member(full_name=f"Cap Member {i}", email=f"cap{i}@x.com",
                          dob=f"1980-01-{i:02d}", api=api)
            for i in range(1, 12)
        ]
        return responder, members

    def _audit_actions_for_member(self, api, member_id):
        from test_helpers import TEST_USERS

        resp = api.list_member_audit_events(member_id, TEST_USERS["platform_admin_headers"])
        events, _ = validate_paginated(resp)
        return [e["action"] for e in events]

    def test_access_rate_soft_cap_flags_at_eleventh_grant_not_tenth(self, api):
        """PRD §3.6: "When that count exceeds ten, the access is still granted, but
        an `AuditEvent` with action `ACCESS_RATE_FLAG` is appended against the
        accessed member; the `AccessEvent` row itself is otherwise untouched — the
        flag lives only in the audit detail. The boundary is strict: a count of
        exactly ten does not flag, while a count of eleven does."

        Design: Difficulty/boundary_precision_check/access_rate_soft_cap_flags_at_eleventh_grant_not_tenth
        """
        responder, members = self._eleven_members_and_responder(api)
        for member in members[:10]:
            event = grant_access(responder, member, api=api)
            assert event["outcome"] == "GRANTED"
        # After ten grants: no ACCESS_RATE_FLAG anywhere.
        for member in members[:10]:
            assert "ACCESS_RATE_FLAG" not in self._audit_actions_for_member(api, member["id"]), (
                "count == 10 is NOT > 10"
            )

        eleventh = grant_access(responder, members[10], api=api)
        assert eleventh["outcome"] == "GRANTED", "soft cap never blocks"
        assert "ACCESS_RATE_FLAG" in self._audit_actions_for_member(api, members[10]["id"]), (
            "the 11th GRANTED access crosses the strict-> threshold"
        )

    def test_access_rate_soft_cap_flags_again_at_twelfth_grant(self, api):
        """PRD §3.6: "When that count exceeds ten, the access is still granted, but
        an `AuditEvent` with action `ACCESS_RATE_FLAG` is appended against the
        accessed member; the `AccessEvent` row itself is otherwise untouched — the
        flag lives only in the audit detail."

        Design: Difficulty/boundary_precision_check/access_rate_soft_cap_flags_at_eleventh_grant_not_tenth
        """
        responder, members = self._eleven_members_and_responder(api)
        twelfth = enroll_member(full_name="Cap Member 12", email="cap12@x.com", dob="1980-01-12", api=api)
        for member in members:
            grant_access(responder, member, api=api)
        assert "ACCESS_RATE_FLAG" in self._audit_actions_for_member(api, members[10]["id"])
        twelfth_event = grant_access(responder, twelfth, api=api)
        assert twelfth_event["outcome"] == "GRANTED"
        assert "ACCESS_RATE_FLAG" in self._audit_actions_for_member(api, twelfth["id"]), (
            "every grant beyond the cap appends ACCESS_RATE_FLAG"
        )


class TestSuspendedMemberAccess:
    def test_suspended_member_record_still_disclosable(self, api):
        """PRD §2.6: "Emergency record access is the deliberate exception. Because
        an engraved identifier must keep working through a billing lapse, access to
        a `SUSPENDED` member's record is still granted under the emergency rules of
        §3.6."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_member_active_and_product_exists_pair
        """
        set_clock(api=api)
        member = enroll_member(full_name="Lena Access", email="lenaa@x.com", dob="1993-04-04", api=api)
        # The credential must outlive the clock advance that lapses the member:
        # an expired credential would fail responder auth before disclosability.
        responder = add_responder(api=api, credential_code="EMS-S-1", expires_on="2028-01-01")
        set_clock("2027-09-02T00:00:00Z", api=api)
        assert get_member(member["id"], api=api)["status"] == "SUSPENDED"
        event = validate_success(
            api.create_access_event(
                {"credential_code": "EMS-S-1", "identifier_code": member["identifier_code"],
                 "lookup_method": "IDENTIFIER"},
                make_responder_headers(responder["id"]),
            ),
            expected_status=201,
        )
        assert event["outcome"] == "GRANTED"

    def test_order_confirm_requires_member_active(self, api):
        """PRD §3.4: "The member must be `ACTIVE`, or the confirm is rejected with
        `ERR_MEMBER_NOT_ACTIVE`."
        PRD §2.6: "Writes that mutate a member's records, orders, contacts,
        directives, wandering cases, or disputes require the member to be
        `ACTIVE`; against a `SUSPENDED` or `CANCELLED` member they are rejected
        with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_member_active_and_product_exists_pair
        """
        from test_helpers import add_product, place_order

        set_clock(api=api)
        product = add_product(api=api, product_sku="CH-S", product_name="Charm",
                              base_price_cents=2500, max_engrave_chars=30)
        member = enroll_member(full_name="Lena Lapse", email="lena@x.com", dob="1993-04-04", api=api)
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="Lena charm", engrave_mode="MANUAL")
        set_clock("2027-09-02T00:00:00Z", api=api)
        fresh = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert fresh["status"] == "SUSPENDED", "clock sweep fired at expiry"
        resp = api.confirm_order(
            member["id"], order["id"],
            {"expected_member_version": fresh["version"]},
            make_member_headers(member["id"]),
        )
        body = resp.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_STALE_VERSION.value, (
            "the version was freshly read; the member-status gate fires instead"
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)
        order_after = validate_success(api.get_order(order["id"], make_member_headers(member["id"])))
        assert order_after["status"] == "PENDING"


class TestAccessAuthPriority:
    def test_state_member_inactive_trumps_safety_responder_auth_on_access(self, api, admin_headers):
        """PRD §2.5: "Business-safety rules specific to the endpoint — emergency
        responder authentication (`ERR_RESPONDER_AUTH_FAILED`), member
        disclosability (`ERR_MEMBER_NOT_DISCLOSABLE`), wandering eligibility
        (`ERR_WANDERING_NOT_ELIGIBLE`), guardian-link validity
        (`ERR_GUARDIAN_LINK_INVALID`), contact priority conflicts
        (`ERR_CONTACT_PRIORITY_CONFLICT`), engraving capacity
        (`ERR_ENGRAVING_OVERFLOW`), dispute eligibility
        (`ERR_RECORD_ITEM_NOT_DISPUTABLE`), renewal funds (`ERR_INSUFFICIENT_FUNDS`),
        and optimistic-concurrency mismatches (`ERR_STALE_VERSION`)."
        PRD §3.6: "A credential that is unknown, `REVOKED`, or expired, or a
        hotline lookup missing its `operator_id`, fails authentication with
        `ERR_RESPONDER_AUTH_FAILED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/state_member_inactive_trumps_safety_responder_auth_on_access
        """
        set_clock(api=api)
        member = enroll_member(full_name="Pat Prio", email="pat@x.com", dob="1979-09-09", api=api)
        code = member["identifier_code"]
        responder = add_responder(api=api, agency_name="Old EMS", credential_code="EMS-OLD-1",
                                  access_tier="FULL", expires_on="2026-08-01")
        validate_success(api.cancel_member(member["id"], admin_headers))

        resp = api.create_access_event(
            {"credential_code": "EMS-OLD-1", "identifier_code": code, "lookup_method": "IDENTIFIER"},
            make_responder_headers(responder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESPONDER_AUTH_FAILED.value)

        # No GRANTED event for the cancelled member; the denial carries the reason code.
        resp_list = api.list_member_access_events(member["id"], admin_headers)
        events, _ = validate_paginated(resp_list)
        assert all(e["outcome"] != "GRANTED" for e in events)
        denied = [e for e in events if e["outcome"] == "DENIED"]
        assert denied, "a DENIED AccessEvent is logged"
        assert denied[0]["reason_code"] == ApiErrorId.ERR_RESPONDER_AUTH_FAILED.value

    def test_valid_credential_on_cancelled_member_is_not_disclosable(self, api, admin_headers):
        """PRD §3.6: "If no member carries that code, or the member's status is
        `CANCELLED`, the access is denied with `ERR_MEMBER_NOT_DISCLOSABLE`
        (HTTP 409) — cancelled members are never disclosed."

        Design: Difficulty/priority_pair_validation_conflict/state_member_inactive_trumps_safety_responder_auth_on_access
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        code = member["identifier_code"]
        responder = add_responder(api=api, credential_code="EMS-OK-1", access_tier="FULL",
                                  expires_on="2027-01-01")
        validate_success(api.cancel_member(member["id"], admin_headers))
        resp = api.create_access_event(
            {"credential_code": "EMS-OK-1", "identifier_code": code, "lookup_method": "IDENTIFIER"},
            make_responder_headers(responder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_DISCLOSABLE.value)


class TestDirectiveReleaseLifecycle:
    def _released_directive_setup(self, api):
        set_clock(api=api)
        member = enroll_member(full_name="Donna Directive", email="donna@x.com", dob="1965-06-06", api=api)
        from test_helpers import add_verified_item
        add_verified_item(
            member["id"], api=api, item_kind="CONDITION", condition_kind="COGNITIVE",
            label="Dementia", detail="d", severity="HIGH", provider_document_ref="doc-dd",
        )
        member = get_member(member["id"], api=api)
        directive = add_directive(member["id"], api=api, directive_type="POLST",
                                  document_ref="polst-d", release_scope="EMERGENCY_ONLY")
        responder = add_responder(api=api, agency_name="EmsD", credential_code="EMS-D-9",
                                  access_tier="BASIC", expires_on="2027-01-01")
        grant_access(responder, member, api=api)
        return member, directive

    def test_terminal_directive_revoke_from_released_works_but_second_revoke_fails(self, api):
        """PRD §3.8: "From `STORED`, the directive moves to `RELEASED` only as a
        side effect of a granted emergency access whose disclosure rules reach it
        (§3.6), and to `REVOKED` when the `Member` or `Guardian` revokes it —
        revocation is also available from `RELEASED`, requires an `ACTIVE` member,
        and appends an `AuditEvent` of action `DIRECTIVE_REVOKE`."

        Design: Corner/state_machines/terminal_directive_revoke_from_released_works_but_second_revoke_fails
        """
        member, directive = self._released_directive_setup(api)
        before = validate_success(api.get_directive(directive["id"], make_member_headers(member["id"])))
        assert before["status"] == "RELEASED", "access released it"

        revoked = validate_success(
            api.revoke_directive(member["id"], directive["id"], make_member_headers(member["id"]))
        )
        assert revoked["status"] == "REVOKED"

        resp = api.revoke_directive(member["id"], directive["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_stored_directive_revocable_directly(self, api):
        """PRD §3.8: "From `STORED`, the directive moves to `RELEASED` only as a
        side effect of a granted emergency access whose disclosure rules reach it
        (§3.6), and to `REVOKED` when the `Member` or `Guardian` revokes it —
        revocation is also available from `RELEASED`, requires an `ACTIVE` member,
        and appends an `AuditEvent` of action `DIRECTIVE_REVOKE`."

        Design: Corner/state_machines/terminal_directive_revoke_from_released_works_but_second_revoke_fails
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        directive = add_directive(member["id"], api=api, directive_type="DNR",
                                  document_ref="dnr-x", release_scope="FULL")
        assert directive["status"] == "STORED"
        revoked = validate_success(
            api.revoke_directive(member["id"], directive["id"], make_member_headers(member["id"]))
        )
        assert revoked["status"] == "REVOKED"
