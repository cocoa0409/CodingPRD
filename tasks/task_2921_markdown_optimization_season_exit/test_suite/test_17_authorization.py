"""Identity rules: the blank header that precedes everything, the flat role
peerage, the entity-backed store manager, and the two separations of duty.
"""

from test_helpers import NON_EXISTENT_UUID, validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import (
    accept_payload,
    approve_payload,
    salvage_order_payload,
    item_payload,
    post_signage_payload,
    recognize_payload,
    season_payload,
)
from test_helpers.test_users import (
    ANALYST_TWO_HEADERS,
    BLANK_ROLE_HEADERS,
    BLANK_USER_ID_HEADERS,
    DIRECTOR_ONE_ID,
    DIRECTOR_TWO_ID,
    make_analyst_headers,
    make_director_headers,
    make_store_manager_headers,
)


class TestBlankIdentityIsUnauthenticated:
    """Rule 1 outranks the role check and the not-found check alike."""

    def test_blank_headers_are_refused_on_reads_and_writes(self, api, analyst):
        """PRD 2.1: "If either header is absent or present but empty, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the
        request is examined."

        Design: Corner/rbac/blank_identity_headers_are_unauthenticated_not_unauthorized
        """
        sc = fx.base_scenario(api)

        blank_role_read = api.list_items(
            BLANK_ROLE_HEADERS, {"season_id": sc.season["id"]}
        )
        validate_error(blank_role_read, "ERR_UNAUTHENTICATED", 401)

        blank_role_write = api.create_item(
            item_payload(sc.season["id"], sku="B-2002"), BLANK_ROLE_HEADERS
        )
        validate_error(blank_role_write, "ERR_UNAUTHENTICATED", 401)

        blank_user_read = api.get_item(sc.item["id"], BLANK_USER_ID_HEADERS)
        validate_error(blank_user_read, "ERR_UNAUTHENTICATED", 401)

    def test_the_blank_header_write_stored_nothing(self, api, analyst):
        """PRD 2.7: "Authentication: `X-User-ID` and `X-User-Role` are present and
        non-empty, else `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/blank_identity_headers_are_unauthenticated_not_unauthorized
        """
        sc = fx.base_scenario(api)
        validate_error(
            api.create_item(
                item_payload(sc.season["id"], sku="B-2002"), BLANK_ROLE_HEADERS
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        _rows, meta = validate_paginated(
            api.list_items(analyst, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 1


class TestTheFiveRolesArePeers:
    """No role inherits another's operations."""

    def test_each_role_is_refused_the_operations_it_does_not_own(
        self, api, analyst, director, controller
    ):
        """PRD 2.1: "If both headers are present but the value of `X-User-Role` is not one
        of the five declared role names, or is a declared role that the requested operation
        does not list as authorized, the request is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/every_role_is_locked_out_of_the_other_roles_exclusive_operations
        """
        sc = fx.planned_scenario(api)
        fx.add_rung(api, sc.plan["id"], 1, "2026-10-19", 22.57)
        fx.submit_plan(api, sc.plan["id"])
        store_manager = make_store_manager_headers(sc.store_0101["id"])

        validate_error(
            api.create_season(season_payload(code="XX27-TEST"), analyst),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.approve_markdown_plan(sc.plan["id"], approve_payload(), analyst),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.post_signage(NON_EXISTENT_UUID, post_signage_payload(), director),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.recognize_vendor_claim(NON_EXISTENT_UUID, recognize_payload(), director),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.create_disposition_order(
                salvage_order_payload(sc.season["id"], sc.item["id"], 10, 300),
                controller,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.list_vendor_claims(store_manager, {"markdown_plan_id": sc.plan["id"]}),
            "ERR_UNAUTHORIZED",
            403,
        )

        assert fx.read_plan(api, sc.plan["id"])["status"] == "SUBMITTED"
        _rows, meta = validate_paginated(api.list_seasons(analyst))
        assert meta["total_count"] == 1

    def test_the_role_that_owns_the_operation_still_succeeds(self, api, analyst, director):
        """PRD 4: "A role absent from a row's list receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/every_role_is_locked_out_of_the_other_roles_exclusive_operations
        """
        sc = fx.planned_scenario(api)
        fx.add_rung(api, sc.plan["id"], 1, "2026-10-19", 22.57)
        fx.submit_plan(api, sc.plan["id"])
        validate_error(
            api.approve_markdown_plan(sc.plan["id"], approve_payload(), analyst),
            "ERR_UNAUTHORIZED",
            403,
        )

        approved = validate_success(
            api.approve_markdown_plan(sc.plan["id"], approve_payload(), director)
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == DIRECTOR_ONE_ID

        _rows, meta = validate_paginated(
            api.list_disposition_orders(analyst, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 0


def _store_and_zone_executions(api):
    """One ``STORE``-scope execution owned by store 0101 and one ``ZONE``-scope
    execution owned by nobody, both ``SCHEDULED`` with ``PENDING`` signage.
    """
    sc = fx.approved_plan_scenario(api)
    sc["step2"] = fx.add_rung(api, sc.plan["id"], 2, "2026-11-02", 32.50)
    sc["exec_store"] = fx.schedule_execution(
        api,
        sc.plan["id"],
        sc.step1["id"],
        sc.west_zone["id"],
        "STORE",
        "2026-10-19",
        200,
        store_id=sc.store_0101["id"],
    )
    sc["exec_zone"] = fx.schedule_execution(
        api, sc.plan["id"], sc.step2["id"], sc.west_zone["id"], "ZONE", "2026-11-02", 100
    )
    return sc


class TestStoreScopeSignageBelongsToItsStore:
    """The ownership comparison is conditional on ``execution_scope``."""

    def test_a_foreign_store_manager_cannot_post_a_store_scope_execution(self, api):
        """PRD 2.1: "Concretely, when a store manager posts signage for an execution whose
        `execution_scope` is `STORE`, the execution's `store_id` must equal the acting
        `X-User-ID`, and a mismatch is rejected with `ERR_STORE_NOT_OWNED` (HTTP 403);
        chain-scope and zone-scope executions carry no `store_id` at all and may be posted
        by any store manager."

        Design: Corner/rbac/store_scope_signage_is_restricted_to_the_owning_store_manager
        """
        sc = _store_and_zone_executions(api)

        response = api.post_signage(
            sc.exec_store["id"],
            post_signage_payload(),
            make_store_manager_headers(sc.store_0202["id"]),
        )
        validate_error(response, "ERR_STORE_NOT_OWNED", 403)

        untouched = fx.read_execution(api, sc.exec_store["id"])
        assert untouched["signage_status"] == "PENDING"
        assert untouched["posted_at"] is None
        assert untouched["posted_by_user_id"] is None
        assert untouched["signage_due_date"] == "2026-10-12"

        owner_post = fx.post_signage(api, sc.exec_store["id"], sc.store_0101["id"])
        assert owner_post["signage_status"] == "POSTED"
        assert owner_post["posted_by_user_id"] == sc.store_0101["id"]

    def test_the_same_refused_manager_may_post_the_zone_scope_execution(self, api):
        """PRD 2.7: "Store ownership on signage posting: for a `STORE`-scope execution the
        posting store manager's `X-User-ID` must equal the execution's `store_id`, else
        `ERR_STORE_NOT_OWNED` (403). Chain-scope and zone-scope executions carry no
        `store_id` and may be posted by any store manager."

        Design: Corner/rbac/store_scope_signage_is_restricted_to_the_owning_store_manager
        """
        sc = _store_and_zone_executions(api)
        validate_error(
            api.post_signage(
                sc.exec_store["id"],
                post_signage_payload(),
                make_store_manager_headers(sc.store_0202["id"]),
            ),
            "ERR_STORE_NOT_OWNED",
            403,
        )
        assert sc.exec_zone["store_id"] is None

        posted = fx.post_signage(api, sc.exec_zone["id"], sc.store_0202["id"])
        assert posted["signage_status"] == "POSTED"
        assert posted["posted_by_user_id"] == sc.store_0202["id"]
        assert posted["signage_due_date"] == "2026-10-26"


class TestSegregationOfDutiesComparesTwoDifferentThings:
    """One error id, two comparisons: user id on the plan, role on the offer."""

    def test_the_plan_approval_compares_user_ids(self, api):
        """PRD 2.1: "The merchandise director who approves a markdown plan must not be the
        analyst recorded in the plan's `created_by_user_id`."

        Design: Corner/rbac/segregation_of_duties_is_by_user_on_plans_and_by_role_on_agreements
        """
        sc = fx.certified_scenario(api)
        author = make_analyst_headers(DIRECTOR_ONE_ID)
        plan = fx.create_plan(
            api, sc.season["id"], sc.item["id"], sc.estimate["id"], headers=author
        )
        assert plan["created_by_user_id"] == DIRECTOR_ONE_ID
        fx.add_rung(api, plan["id"], 1, "2026-11-16", 22.57, headers=author)
        fx.submit_plan(api, plan["id"], headers=author)

        response = api.approve_markdown_plan(
            plan["id"], approve_payload(), make_director_headers(DIRECTOR_ONE_ID)
        )
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

        refused = fx.read_plan(api, plan["id"])
        assert refused["status"] == "SUBMITTED"
        assert refused["approved_by_user_id"] is None

        approved = validate_success(
            api.approve_markdown_plan(
                plan["id"], approve_payload(), make_director_headers(DIRECTOR_TWO_ID)
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == DIRECTOR_TWO_ID

    def test_the_offer_acceptance_compares_roles(self, api, vendor_rep):
        """PRD 3.8: "In both directions the acting role must differ from
        `last_offer_by_role`, and an attempt to accept one's own terms is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_is_by_user_on_plans_and_by_role_on_agreements
        """
        sc = fx.base_scenario(api)
        agreement = fx.create_agreement(api, sc.season["id"])
        assert agreement["status"] == "PROPOSED"
        assert agreement["last_offer_by_role"] == "PricingAnalyst"

        response = api.accept_allowance_agreement(
            agreement["id"], accept_payload(), ANALYST_TWO_HEADERS
        )
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

        refused = fx.read_agreement(api, agreement["id"])
        assert refused["status"] == "PROPOSED"
        assert refused["agreed_share_pct"] is None

        accepted = validate_success(
            api.accept_allowance_agreement(agreement["id"], accept_payload(), vendor_rep)
        )
        assert accepted["status"] == "AGREED"
        assert accepted["agreed_share_pct"] == 25.00
        assert accepted["funding_cap_cents"] == 100000
        assert accepted["remaining_cap_cents"] == 100000
        assert accepted["recognized_total_cents"] == 0
