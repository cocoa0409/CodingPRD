"""School partnerships: creation round-trip, listing pagination, agreement and
data-sharing state machines, the OCC-guarded amendment loop, and the
per-school-rounded cost-share rollup."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
    make_school_liaison_headers,
)


class TestSchoolCreation:
    def test_school_create_roundtrip(self, api):
        """PRD §3.2: "A school is governed by two independent state dimensions,
        both starting at `DRAFT`: `agreement_status` for the partnership
        agreement itself, and `data_sharing_status` for the student outcome
        data-sharing agreement with the district."

        Design: Corner/entities/school_create_roundtrip
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        created = validate_success(
            api.create_school(factories.school_payload(site["id"]), SITE_DIRECTOR_HEADERS), 201
        )
        school = validate_success(api.get_school(created["id"], PROGRAM_MANAGER_HEADERS))

        assert school["agreement_status"] == "DRAFT"
        assert school["data_sharing_status"] == "DRAFT"
        assert school["team_size"] == 3
        assert school["annual_cost_share_cents"] == 400_000
        assert set(school["service_scope"]) == {"ATTENDANCE_SUPPORT", "MATH_TUTORING"}
        assert school["site_id"] == site["id"]

    def test_schools_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the start of the
        result set and defaults to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/schools_list_pagination_envelope
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        for name, size, cost in (("Riverton Elementary", 3, 400_000), ("East Middle", 4, 250_000), ("West High", 5, 300_000)):
            fixtures.create_school(
                api, site["id"], name=name, team_size=size,
                service_scope=["LITERACY_TUTORING"], annual_cost_share_cents=cost,
            )

        page1, meta1 = validate_paginated(
            api.list_site_schools(site["id"], SITE_DIRECTOR_HEADERS, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_site_schools(site["id"], SITE_DIRECTOR_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], "pages must be disjoint"


class TestAgreementMachine:
    def test_school_terminated_lockdown_rejected(self, api):
        """PRD §3.2: "Termination — `ACTIVE` or `SUSPENDED` to `TERMINATED`, by
        a `SiteDirector` — is the heavy cascade, and it runs in three linked
        steps."
        PRD §2.8: "whether the target resource's current state permits the
        requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/school_terminated_lockdown_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])

        terminated = validate_success(
            api.transition_school(
                school["id"], {"to_status": "TERMINATED", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
            )
        )
        assert terminated["agreement_status"] == "TERMINATED"

        # No transition leaves the terminal state.
        blocked = api.transition_school(
            school["id"], {"to_status": "SUSPENDED", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

    def test_school_activate_requires_data_sharing(self, api):
        """PRD §3.2: "Activation — `SIGNED` to `ACTIVE` — is a `SiteDirector`
        action with two preconditions: the school's `data_sharing_status` must
        be `SIGNED` (else `ERR_DATA_SHARING_NOT_SIGNED`), and the site must be
        `ACTIVE` (else `ERR_INVALID_STATE`)."

        Design: Corner/validations/school_activate_requires_data_sharing
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_school(api, site["id"])
        fixtures.sign_agreement(api, school["id"])

        blocked = api.transition_school(
            school["id"], {"to_status": "ACTIVE", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_DATA_SHARING_NOT_SIGNED.value)

        after = get_success_data(api.get_school(school["id"], SITE_DIRECTOR_HEADERS))
        assert after["agreement_status"] == "SIGNED"

    def test_team_create_requires_active_agreement(self, api):
        """PRD §3.4: "Creation requires the site to be `ACTIVE` and the
        school's agreement to be `ACTIVE` — otherwise
        `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Corner/validations/team_create_requires_active_agreement
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_school(api, site["id"])
        fixtures.sign_data_sharing(api, school["id"])
        fixtures.sign_agreement(api, school["id"])

        # SIGNED is not ACTIVE: the cross-entity gate fires before any team exists.
        blocked = api.create_team(factories.team_payload(school["id"], name="Team Early"), SITE_DIRECTOR_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    def test_liaison_sign_other_school_rejected(self, api):
        """PRD §3.2: "A `SchoolLiaison` whose `X-User-ID` equals the school's
        `id` moves the agreement from `DRAFT` to `SIGNED`; any other liaison
        identity is rejected with `ERR_NOT_ENTITY_OWNER`."

        Design: Corner/validations/liaison_sign_other_school_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school_a = fixtures.create_school(api, site["id"], name="Riverton Elementary")
        school_b = fixtures.create_school(
            api, site["id"], name="Bay School", service_scope=["MATH_TUTORING"], annual_cost_share_cents=300_000
        )

        blocked = api.transition_school(
            school_b["id"],
            {"to_status": "SIGNED", "dimension": "AGREEMENT"},
            make_school_liaison_headers(school_a["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_NOT_ENTITY_OWNER.value)

        after = get_success_data(api.get_school(school_b["id"], SITE_DIRECTOR_HEADERS))
        assert after["agreement_status"] == "DRAFT"


class TestVersionAndAmendment:
    def test_version_increments_on_each_mutation(self, api):
        """PRD §2.5: "`version` is an integer that starts at 1 and increments
        by 1 on every mutation, again including cascaded ones; it is the basis
        for optimistic concurrency control."

        Design: Corner/cross_cutting_layers/version_increments_on_each_mutation
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_school(api, site["id"])

        v1 = get_success_data(api.get_school(school["id"], SITE_DIRECTOR_HEADERS))
        assert v1["version"] == 1

        v2 = fixtures.sign_data_sharing(api, school["id"])
        assert v2["version"] == 2

        v3 = fixtures.sign_agreement(api, school["id"])
        assert v3["version"] == 3

        v4 = fixtures.activate_agreement(api, school["id"])
        assert v4["version"] == 4

    def test_occ_school_amend_stale_version_rejected(self, api):
        """PRD §2.7: "Amending a school's agreement requires
        `expected_school_version` matching the school's current `version`. If
        another writer has advanced the school's version since the client last
        read it — by amending it or by driving an agreement transition — the
        amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), because the
        client's view of the agreement terms is stale."

        Design: Corner/cross_cutting_layers/occ_school_amend_stale_version_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        current_version = school["version"]

        stale = api.amend_school(
            school["id"], {"expected_school_version": current_version - 1, "team_size": 5}, SITE_DIRECTOR_HEADERS
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

        fresh = api.amend_school(
            school["id"], {"expected_school_version": current_version, "team_size": 5}, SITE_DIRECTOR_HEADERS
        )
        amended = validate_success(fresh)
        assert amended["agreement_status"] == "AMENDMENT_REVIEW"
        assert amended["team_size"] == 5

    def test_derived_cost_share_reconciles_after_amendment(self, api):
        """PRD §3.2: "The amendment may revise `team_size`,
        `annual_cost_share_cents`, or `service_scope`; the revised values take
        effect immediately, the school's `version` increments by 1, the
        agreement moves to `AMENDMENT_REVIEW`, and the cost-share rollup is
        recomputed with the amended amount."

        Design: Corner/cross_cutting_layers/derived_cost_share_reconciles_after_amendment"""
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])

        pre = fixtures.get_site(api, site["id"])
        assert pre["cost_share_installment_1_cents"] == 200_000
        assert pre["cost_share_total_cents"] == 400_000

        amended = validate_success(
            api.amend_school(
                school["id"],
                {"expected_school_version": school["version"], "annual_cost_share_cents": 450_000},
                SITE_DIRECTOR_HEADERS,
            )
        )
        assert amended["agreement_status"] == "AMENDMENT_REVIEW"

        # AMENDMENT_REVIEW stays in the input set with the amended amount.
        mid = fixtures.get_site(api, site["id"])
        assert mid["cost_share_installment_1_cents"] == 225_000
        assert mid["cost_share_total_cents"] == 450_000

        # Liaison confirmation does not double-apply the amendment.
        get_success_data(
            api.transition_school(
                school["id"],
                {"to_status": "ACTIVE", "dimension": "AGREEMENT"},
                make_school_liaison_headers(school["id"]),
            )
        )
        post = fixtures.get_site(api, site["id"])
        assert post["cost_share_installment_1_cents"] == 225_000
        assert post["cost_share_total_cents"] == 450_000


class TestCostShareRounding:
    def test_cost_share_round_per_school_then_sum(self, api):
        """PRD §3.2: "Rounding is pinned to happen per school before any
        summation; rounding the summed amount instead would produce different
        cents and is forbidden."

        Design: Difficulty/combinatorial_formula/cost_share_round_per_school_then_sum
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        school_a = fixtures.create_school(
            api, site["id"], name="North Elementary", service_scope=["ATTENDANCE_SUPPORT"],
            annual_cost_share_cents=333_333,
        )
        fixtures.sign_agreement(api, school_a["id"])
        school_b = fixtures.create_school(
            api, site["id"], name="South Elementary", service_scope=["MATH_TUTORING"],
            annual_cost_share_cents=666_667,
        )
        fixtures.sign_agreement(api, school_b["id"])
        # School C stays DRAFT and is excluded from the input set.
        fixtures.create_school(
            api, site["id"], name="Draft Academy", service_scope=["LITERACY_TUTORING"],
            annual_cost_share_cents=111_111,
        )

        site_read = fixtures.get_site(api, site["id"])
        # Per-school round-half-up first: 166667 + 333334. Sum-then-round would
        # give 500000.
        assert site_read["cost_share_installment_1_cents"] == 500_001
        # Each school keeps the remainder cent: 166666 + 333333.
        assert site_read["cost_share_installment_2_cents"] == 499_999
        assert site_read["cost_share_total_cents"] == 1_000_000

    def test_cost_share_draft_school_excluded_then_enters_on_signing(self, api):
        """PRD §3.2: "For each school of the site whose agreement is `SIGNED`,
        `ACTIVE`, `AMENDMENT_REVIEW`, or `COMPLETED` — `DRAFT` and
        `TERMINATED` schools are excluded — the first installment is half of
        that school's `annual_cost_share_cents`, rounded half up to a whole
        cent, and the second installment is the remainder of the annual amount
        after subtracting that school's first installment."
        PRD §3.2: "The rollup is recomputed whenever a school is created,
        whenever an agreement enters or leaves the qualifying set (signing,
        activation, amendment review, completion, termination), and whenever
        an amendment changes `annual_cost_share_cents`."

        Design: Difficulty/combinatorial_formula/cost_share_round_per_school_then_sum"""
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        school_a = fixtures.create_school(
            api, site["id"], name="North Elementary", service_scope=["ATTENDANCE_SUPPORT"],
            annual_cost_share_cents=333_333,
        )
        fixtures.sign_agreement(api, school_a["id"])
        school_b = fixtures.create_school(
            api, site["id"], name="South Elementary", service_scope=["MATH_TUTORING"],
            annual_cost_share_cents=666_667,
        )
        fixtures.sign_agreement(api, school_b["id"])
        school_c = fixtures.create_school(
            api, site["id"], name="Draft Academy", service_scope=["LITERACY_TUTORING"],
            annual_cost_share_cents=111_111,
        )

        before = fixtures.get_site(api, site["id"])
        assert before["cost_share_total_cents"] == 1_000_000

        # Signing the DRAFT school moves it into the input set: its per-school
        # installments are round_half_up(111111 x 0.5) = 55556 and 55555.
        fixtures.sign_agreement(api, school_c["id"])
        after = fixtures.get_site(api, site["id"])
        assert after["cost_share_installment_1_cents"] == 555_557
        assert after["cost_share_installment_2_cents"] == 555_554
        assert after["cost_share_total_cents"] == 1_111_111


class TestAgreementCycles:
    def test_amendment_and_manual_suspension_loops(self, api):
        """PRD §3.2: "The amendment may revise `team_size`,
        `annual_cost_share_cents`, or `service_scope`; the revised values take
        effect immediately, the school's `version` increments by 1, the
        agreement moves to `AMENDMENT_REVIEW`, and the cost-share rollup is
        recomputed with the amended amount."
        PRD §3.2: "Confirmation — returning the agreement from
        `AMENDMENT_REVIEW` to `ACTIVE` — belongs to the school's own
        `SchoolLiaison` (ownership-checked as at signing, and requiring
        `data_sharing_status` still `SIGNED`, else
        `ERR_DATA_SHARING_NOT_SIGNED`)."

        Design: Difficulty/non_linear_state_machine/school_agreement_amendment_and_suspension_cycle"""
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])

        amended = validate_success(
            api.amend_school(
                school["id"], {"expected_school_version": school["version"], "team_size": 5}, SITE_DIRECTOR_HEADERS
            )
        )
        assert amended["agreement_status"] == "AMENDMENT_REVIEW"

        confirmed = validate_success(
            api.transition_school(
                school["id"], {"to_status": "ACTIVE", "dimension": "AGREEMENT"},
                make_school_liaison_headers(school["id"]),
            )
        )
        assert confirmed["agreement_status"] == "ACTIVE"

        suspended = validate_success(
            api.transition_school(
                school["id"], {"to_status": "SUSPENDED", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
            )
        )
        assert suspended["agreement_status"] == "SUSPENDED"

        resumed = validate_success(
            api.transition_school(
                school["id"], {"to_status": "ACTIVE", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
            )
        )
        assert resumed["agreement_status"] == "ACTIVE"

    def test_data_sharing_expiry_force_suspends_and_re_sign_does_not_resume(self, api):
        """PRD §3.2: "A `SiteDirector` may move an `ACTIVE` agreement to
        `SUSPENDED`, and the same transition happens automatically whenever
        the school's data sharing lapses to `EXPIRED` — including from
        `AMENDMENT_REVIEW`, which likewise falls to `SUSPENDED` on expiry."
        PRD §3.2: "Resumption — `SUSPENDED` back to `ACTIVE` — is a
        `SiteDirector` action requiring data sharing to be `SIGNED` again;
        re-signing data sharing on its own deliberately does not resume the
        agreement."

        Design: Difficulty/non_linear_state_machine/school_agreement_amendment_and_suspension_cycle"""
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])

        expired = validate_success(
            api.transition_school(
                school["id"], {"to_status": "EXPIRED", "dimension": "DATA_SHARING"},
                make_school_liaison_headers(school["id"]),
            )
        )
        assert expired["data_sharing_status"] == "EXPIRED"
        assert expired["agreement_status"] == "SUSPENDED"

        re_signed = validate_success(
            api.transition_school(
                school["id"], {"to_status": "SIGNED", "dimension": "DATA_SHARING"},
                make_school_liaison_headers(school["id"]),
            )
        )
        assert re_signed["data_sharing_status"] == "SIGNED"
        assert re_signed["agreement_status"] == "SUSPENDED"

        resumed = validate_success(
            api.transition_school(
                school["id"], {"to_status": "ACTIVE", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
            )
        )
        assert resumed["agreement_status"] == "ACTIVE"
