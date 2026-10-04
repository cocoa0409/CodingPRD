"""Guardianship, emergency contacts, wandering cases, the dependent-fee formula,
guardian scoping, and membership-fee combinations."""
from test_helpers import (
    ApiErrorId,
    add_contact,
    add_record_item,
    attach_guardian,
    enroll_member,
    get_member,
    list_member_reminders,
    make_guardian_headers,
    make_member_headers,
    set_clock,
    setup_guardian_pair,
    validate_error,
    validate_success,
)


class TestDependentFeeCombinatorial:
    def test_membership_fee_dependent_cognitive_premium_branch_order(self, api):
        """PRD §3.1: "When the member being enrolled or renewed is administered —
        meaning they hold an `ACTIVE` `GuardianLink` as the dependent — the base is
        multiplied by a dependent factor of one-half, with the product rounded
        half-up to whole cents immediately after the multiplication. When the
        member's `has_cognitive_condition` is true at renewal time, a flat
        cognitive-service surcharge of 1000 cents is added. The evaluation order is
        pinned: the dependent factor is applied to the base and rounded first, and
        only then is the cognitive surcharge added; the dependent factor never
        amplifies the surcharge."
        PRD §3.2: "A **reactivation** moves `SUSPENDED` back to `ACTIVE`: the new
        `expires_on` is the current logical date plus the tier's term."

        Design: Difficulty/combinatorial_formula/membership_fee_dependent_cognitive_premium_branch_order
        """
        from test_helpers import add_verified_item

        set_clock(api=api)
        guardian = enroll_member(full_name="Gail Guardian", email="gail@x.com", dob="1975-04-10", api=api)
        dependent = enroll_member(full_name="Dan Dependent", email="dan@x.com",
                                  dob="2015-08-20", tier="PREMIUM", api=api)
        attach_guardian(dependent["id"], guardian["id"], relation_label="mother", api=api)
        gh = make_guardian_headers(guardian["id"])
        add_verified_item(
            dependent["id"], actor_headers=gh, api=api, item_kind="CONDITION",
            condition_kind="COGNITIVE", label="Autism", detail="non-verbal",
            severity="HIGH", provider_document_ref="doc-d1",
        )
        assert get_member(dependent["id"], api=api)["has_cognitive_condition"] is True

        # Lapse: PREMIUM term is 24 months from 2026-09-01, expiry 2028-09-01.
        set_clock("2028-09-02T00:00:00Z", api=api)
        assert get_member(dependent["id"], api=api)["status"] == "SUSPENDED"

        # Fee = round_half_up(7500 * 0.5) + 1000 == 4750.
        renewed = validate_success(
            api.renew_member(dependent["id"], {"amount_paid_cents": 4750}, gh)
        )
        assert renewed["status"] == "ACTIVE", "SUSPENDED -> ACTIVE on renewal"
        assert renewed["wallet_credit_cents"] == 0, (
            "wallet applied first; payment covers the remainder"
        )
        assert renewed["expires_on"] == "2030-09-02", (
            f"renewal date + 24 PREMIUM term months, got {renewed['expires_on']}"
        )
        renewal_reminders = [
            r for r in list_member_reminders(dependent["id"], api=api)
            if r["reminder_kind"] == "RENEWAL" and r["status"] == "PENDING"
        ]
        assert len(renewal_reminders) == 1, "a new PENDING RENEWAL reminder is anchored"
        assert renewal_reminders[0]["due_on"] == "2030-08-03", (
            f"expires_on - 30 days, got {renewal_reminders[0]['due_on']}"
        )

    def test_dependent_renewal_one_cent_short_of_factored_fee_fails(self, api):
        """PRD §3.2: "The funds test is the same in both directions: the member's
        `wallet_credit_cents` plus the supplied `amount_paid_cents` must cover the
        renewal fee for their tier — computed exactly as in §3.1, including the
        dependent factor when an active guardianship exists and the cognitive
        surcharge when the member's `has_cognitive_condition` flag is currently
        true. A shortfall is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/membership_fee_dependent_cognitive_premium_branch_order
        """
        from test_helpers import add_verified_item

        set_clock(api=api)
        guardian = enroll_member(full_name="Gail Two", email="gail2@x.com", dob="1975-04-10", api=api)
        dependent = enroll_member(full_name="Dan Two", email="dan2@x.com",
                                  dob="2015-08-20", tier="PREMIUM", api=api)
        attach_guardian(dependent["id"], guardian["id"], relation_label="mother", api=api)
        gh = make_guardian_headers(guardian["id"])
        add_verified_item(
            dependent["id"], actor_headers=gh, api=api, item_kind="CONDITION",
            condition_kind="COGNITIVE", label="Autism", detail="non-verbal",
            severity="HIGH", provider_document_ref="doc-d1",
        )
        set_clock("2028-09-02T00:00:00Z", api=api)
        # Fee is 4750: one cent short must fail, proving the factored+surcharged fee.
        resp = api.renew_member(dependent["id"], {"amount_paid_cents": 4749}, gh)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
        assert get_member(dependent["id"], api=api)["status"] == "SUSPENDED"


class TestGuardianDelegatedAuthority:
    def test_guardian_delegated_authority_acts_for_dependent(self, api):
        """PRD §2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is also the
        `id` of a `Member` — the administering adult. A `Guardian` acting on a
        dependent's resource must hold an `ACTIVE` `GuardianLink` whose
        `guardian_member_id` equals `X-User-ID` and whose `member_id` equals the
        path's `memberId`; otherwise the request is rejected with
        `ERR_GUARDIANSHIP_REQUIRED` (HTTP 403)."
        PRD §3.8: "While `ACTIVE`, the link both delegates the dependent's
        self-service operations to the guardian (§2.1) and, at renewal time, halves
        the dependent's base fee via the dependent factor of §3.1."

        Design: Corner/rbac/guardian_delegated_authority_acts_for_dependent
        """
        set_clock(api=api)
        guardian = enroll_member(full_name="Gma", email="gma@x.com", dob="1960-01-01", api=api)
        dependent = enroll_member(full_name="Grandkid", email="gk@x.com", dob="2018-01-01", api=api)
        attach_guardian(dependent["id"], guardian["id"], relation_label="grandmother", api=api)
        gh = make_guardian_headers(guardian["id"])

        item = validate_success(
            api.create_record_item(
                dependent["id"],
                {"item_kind": "ALLERGY", "label": "Peanuts", "detail": "severe",
                 "severity": "CRITICAL", "provider_document_ref": "doc-pn"},
                gh,
            ),
            expected_status=201,
        )
        contact = validate_success(
            api.create_contact(
                dependent["id"],
                {"contact_name": "Gma", "phone": "+15550007777", "priority_rank": 1},
                gh,
            ),
            expected_status=201,
        )
        assert item["member_id"] == dependent["id"], (
            "created under the dependent, not the guardian"
        )
        assert contact["member_id"] == dependent["id"]

    def test_guardian_can_renew_dependent_membership(self, api):
        """PRD §3.8: "While `ACTIVE`, the link both delegates the dependent's
        self-service operations to the guardian (§2.1) and, at renewal time, halves
        the dependent's base fee via the dependent factor of §3.1."
        PRD §3.2: "A `Member` or their `Guardian` initiates renewal by paying
        `amount_paid_cents`."

        Design: Corner/rbac/guardian_delegated_authority_acts_for_dependent
        """
        set_clock(api=api)
        guardian, dependent, _link = setup_guardian_pair(api=api)
        gh = make_guardian_headers(guardian["id"])
        # Dependent STANDARD fee with dependent factor: round_half_up(4000 * 0.5) = 2000.
        renewed = validate_success(
            api.renew_member(dependent["id"], {"amount_paid_cents": 2000}, gh)
        )
        assert renewed["status"] == "ACTIVE"
        assert renewed["expires_on"] == "2028-09-01"


class TestGuardianLinkValidity:
    def test_guardian_link_rejects_self_link_and_minor_guardian(self, api, admin_headers):
        """PRD §3.8: "Three constraints guard creation, and a violation of any is
        rejected with `ERR_GUARDIAN_LINK_INVALID` (HTTP 409): the guardian must be
        an `ACTIVE` member whose `member_type` is `ADULT`; the guardian must differ
        from the dependent — self-links are forbidden; and the dependent must not
        already have another `ACTIVE` link."

        Design: Corner/validations/guardian_link_rejects_self_link_and_minor_guardian
        """
        set_clock(api=api)
        dependent = enroll_member(full_name="Dep One", email="dep1@x.com", dob="2016-05-05", api=api)
        kid = enroll_member(full_name="Kid Two", email="kid2@x.com", dob="2015-05-05", api=api)
        resp_self = api.create_guardian_link(
            dependent["id"],
            {"guardian_member_id": dependent["id"], "relation_label": "self"},
            admin_headers,
        )
        validate_error(resp_self, ApiErrorId.ERR_GUARDIAN_LINK_INVALID.value)
        resp_minor = api.create_guardian_link(
            dependent["id"],
            {"guardian_member_id": kid["id"], "relation_label": "sibling"},
            admin_headers,
        )
        validate_error(resp_minor, ApiErrorId.ERR_GUARDIAN_LINK_INVALID.value)

    def test_second_active_link_for_same_dependent_rejected(self, api, admin_headers):
        """PRD §3.8: "Three constraints guard creation, and a violation of any is
        rejected with `ERR_GUARDIAN_LINK_INVALID` (HTTP 409): the guardian must be
        an `ACTIVE` member whose `member_type` is `ADULT`; the guardian must differ
        from the dependent — self-links are forbidden; and the dependent must not
        already have another `ACTIVE` link."

        Design: Corner/validations/guardian_link_rejects_self_link_and_minor_guardian
        """
        set_clock(api=api)
        g1 = enroll_member(full_name="G One", email="g1@x.com", dob="1960-01-01", api=api)
        g2 = enroll_member(full_name="G Two", email="g2@x.com", dob="1961-01-01", api=api)
        dependent = enroll_member(full_name="Dep Three", email="dep3@x.com", dob="2016-05-05", api=api)
        attach_guardian(dependent["id"], g1["id"], relation_label="mother", api=api)
        resp = api.create_guardian_link(
            dependent["id"],
            {"guardian_member_id": g2["id"], "relation_label": "father"},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_GUARDIAN_LINK_INVALID.value)


class TestGuardianScoping:
    def test_guardian_write_requires_active_guardianlink_on_member_pair(self, api, admin_headers):
        """PRD §2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is also the
        `id` of a `Member` — the administering adult. A `Guardian` acting on a
        dependent's resource must hold an `ACTIVE` `GuardianLink` whose
        `guardian_member_id` equals `X-User-ID` and whose `member_id` equals the
        path's `memberId`; otherwise the request is rejected with
        `ERR_GUARDIANSHIP_REQUIRED` (HTTP 403)."
        PRD §3.8: "The link starts `ACTIVE` and is revoked either explicitly by a
        `PlatformAdmin` or by the member-cancel cascade, moving to the terminal
        `REVOKED` state with an `AuditEvent` of action `GUARDIAN_REVOKE`."

        Design: Difficulty/cross_entity_state_dependency/guardian_write_requires_active_guardianlink_on_member_pair
        """
        set_clock(api=api)
        guardian = enroll_member(full_name="Hal Guard", email="hal@x.com", dob="1968-06-06", api=api)
        dependent = enroll_member(full_name="Dot Dep", email="dot@x.com", dob="2017-02-14", api=api)
        link = attach_guardian(dependent["id"], guardian["id"], relation_label="uncle", api=api)
        gh = make_guardian_headers(guardian["id"])

        ok_item = validate_success(
            api.create_record_item(
                dependent["id"],
                {"item_kind": "CONDITION", "label": "Asthma", "detail": "inhaler",
                 "severity": "MEDIUM", "provider_document_ref": "doc-a"},
                gh,
            ),
            expected_status=201,
        )

        validate_success(api.revoke_guardian_link(link["id"], admin_headers))
        resp = api.create_record_item(
            dependent["id"],
            {"item_kind": "ALLERGY", "label": "Nuts", "detail": "severe",
             "severity": "CRITICAL", "provider_document_ref": "doc-n"},
            gh,
        )
        validate_error(resp, ApiErrorId.ERR_GUARDIANSHIP_REQUIRED.value)

        item_after = validate_success(
            api.get_record_item(dependent["id"], ok_item["id"], make_member_headers(dependent["id"]))
        )
        assert item_after["status"] == "PENDING_VERIFICATION", (
            "the pre-revoke item is untouched by the revocation"
        )

    def test_revoked_guardian_cannot_add_contact_either(self, api, admin_headers):
        """PRD §2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is also the
        `id` of a `Member` — the administering adult. A `Guardian` acting on a
        dependent's resource must hold an `ACTIVE` `GuardianLink` whose
        `guardian_member_id` equals `X-User-ID` and whose `member_id` equals the
        path's `memberId`; otherwise the request is rejected with
        `ERR_GUARDIANSHIP_REQUIRED` (HTTP 403)."

        Design: Difficulty/cross_entity_state_dependency/guardian_write_requires_active_guardianlink_on_member_pair
        """
        set_clock(api=api)
        guardian, dependent, link = setup_guardian_pair(api=api)
        gh = make_guardian_headers(guardian["id"])
        validate_success(api.revoke_guardian_link(link["id"], admin_headers))
        resp = api.create_contact(
            dependent["id"],
            {"contact_name": "Revoked", "phone": "+15550001212", "priority_rank": 1},
            gh,
        )
        validate_error(resp, ApiErrorId.ERR_GUARDIANSHIP_REQUIRED.value)


class TestContactPriority:
    def test_contact_priority_conflict_rejected(self, api):
        """PRD §3.8: "The rank must be unique among the member's contacts whose
        status is `ACTIVE`; a collision is rejected with
        `ERR_CONTACT_PRIORITY_CONFLICT` (HTTP 409). Removal is soft: a `Member` or
        `Guardian` removes a contact, moving it `ACTIVE` → `REMOVED` — the row
        stays for audit history — with `AuditEvent` actions `CONTACT_ADD` and
        `CONTACT_REMOVE` bracketing the lifecycle."

        Design: Corner/validations/contact_priority_conflict_rejected
        """
        set_clock(api=api)
        member = enroll_member(full_name="Connie Contact", email="connie@x.com", dob="1981-01-01", api=api)
        mh = make_member_headers(member["id"])
        first = add_contact(member["id"], api=api, contact_name="First",
                            phone="+15551111111", priority_rank=1)
        resp = api.create_contact(
            member["id"],
            {"contact_name": "Second", "phone": "+15552222222", "priority_rank": 1},
            mh,
        )
        validate_error(resp, ApiErrorId.ERR_CONTACT_PRIORITY_CONFLICT.value)

        removed = validate_success(api.remove_contact(member["id"], first["id"], mh))
        assert removed["status"] == "REMOVED"
        third = validate_success(
            api.create_contact(
                member["id"],
                {"contact_name": "Third", "phone": "+15553333333", "priority_rank": 1},
                mh,
            ),
            expected_status=201,
        )
        assert third["priority_rank"] == 1, "REMOVED contacts don't hold the rank"

    def test_distinct_ranks_for_active_contacts_coexist(self, api):
        """PRD §3.8: "The rank must be unique among the member's contacts whose
        status is `ACTIVE`; a collision is rejected with
        `ERR_CONTACT_PRIORITY_CONFLICT` (HTTP 409)."

        Design: Corner/validations/contact_priority_conflict_rejected
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        c1 = add_contact(member["id"], api=api, contact_name="One", phone="+15550000001", priority_rank=1)
        c2 = add_contact(member["id"], api=api, contact_name="Two", phone="+15550000002", priority_rank=2)
        assert c1["status"] == "ACTIVE" and c2["status"] == "ACTIVE"


class TestWanderingCaseOverlap:
    def _cognitive_member(self, api):
        set_clock(api=api)
        member = enroll_member(full_name="Wanda Wander", email="wanda@x.com", dob="1950-01-20", api=api)
        from test_helpers import add_verified_item
        add_verified_item(
            member["id"], api=api, item_kind="CONDITION", condition_kind="COGNITIVE",
            label="Alzheimers", detail="wander risk", severity="CRITICAL",
            provider_document_ref="doc-w",
        )
        return get_member(member["id"], api=api)

    def test_one_open_wandering_case_blocks_second_overlapping_case(self, api, hotline_headers):
        """PRD §3.8: "Two eligibility constraints are enforced together, with
        violations rejected as `ERR_WANDERING_NOT_ELIGIBLE` (HTTP 409): the
        member's `has_cognitive_condition` must be true, and the member must not
        already have an `OPEN` case — at most one open case per member."
        PRD §3.8: "Resolution, by the same two roles, requires an `outcome` of
        `REUNITED` or `OTHER`, stamps `resolved_at`, moves the case `OPEN` →
        `RESOLVED`, and appends an `AuditEvent` of action `WANDERING_RESOLVE`."

        Design: Difficulty/resource_temporal_overlap/one_open_wandering_case_blocks_second_overlapping_case
        """
        member = self._cognitive_member(api)
        case1 = validate_success(
            api.create_wandering_case(member["id"], {"opened_via": "HOTLINE_ESCALATION"}, hotline_headers),
            expected_status=201,
        )
        resp = api.create_wandering_case(member["id"], {"opened_via": "SELF_REPORT"}, hotline_headers)
        validate_error(resp, ApiErrorId.ERR_WANDERING_NOT_ELIGIBLE.value)

        resolved = validate_success(
            api.resolve_wandering_case(member["id"], case1["id"], {"outcome": "REUNITED"}, hotline_headers)
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"], "resolved_at set at resolution"

        case2 = validate_success(
            api.create_wandering_case(member["id"], {"opened_via": "SELF_REPORT"}, hotline_headers),
            expected_status=201,
        )
        assert case2["status"] == "OPEN", (
            "interval closed -> capacity freed, even on the same logical day"
        )

    def test_wandering_case_requires_cognitive_condition(self, api, hotline_headers):
        """PRD §3.8: "Two eligibility constraints are enforced together, with
        violations rejected as `ERR_WANDERING_NOT_ELIGIBLE` (HTTP 409): the
        member's `has_cognitive_condition` must be true, and the member must not
        already have an `OPEN` case — at most one open case per member."

        Design: Difficulty/resource_temporal_overlap/one_open_wandering_case_blocks_second_overlapping_case
        """
        set_clock(api=api)
        member = enroll_member(full_name="No Cog", email="nocog@x.com", dob="1950-01-20", api=api)
        resp = api.create_wandering_case(member["id"], {"opened_via": "SELF_REPORT"}, hotline_headers)
        validate_error(resp, ApiErrorId.ERR_WANDERING_NOT_ELIGIBLE.value)
