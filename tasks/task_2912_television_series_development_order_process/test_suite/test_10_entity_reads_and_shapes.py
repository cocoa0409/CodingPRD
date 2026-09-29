"""Entity shapes: computed fields, declared defaults, immutability and foreign keys.

Every resource in the contract declares which of its fields the client supplies and
which the server computes. These tests pin the computed side, the declared initial
states, the pagination envelope of the listings and the resolution order of the
body foreign keys.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CHAIN_OF_TITLE_CLEAN,
    CONTINGENCY_PENDING,
    DEV_ABANDONED,
    DEV_ACTIVE_DEVELOPMENT,
    DEV_PILOT_ORDERED,
    EXCLUSIVITY_HOLDING_DEAL,
    GUILD_TIER_LOW,
    HOLDING_ACTIVE,
    PITCH_SUBMITTED,
    POSTURE_OPEN,
    PRODUCTION_ORDERED,
    RIGHTS_RESULT_CLEAR,
    TERM_IN_TERM,
    TIER_STANDARD,
    TURNAROUND_EXERCISED,
    TURNAROUND_NONE,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
    platform_admin_headers,
)

BO = {"full_name": "Bo Nakamura", "guild_minimum_tier": GUILD_TIER_LOW, "quote_per_step_cents": 2000000}
CYD = {"full_name": "Cyd Okonkwo", "guild_minimum_tier": GUILD_TIER_LOW, "quote_per_step_cents": 2000000}


def _meta(response):
    return response.json()["meta"]


def test_a_standard_agency_reports_a_computed_cap_and_no_usage_yet(api):
    """effective_submission_cap and submissions_used_count are computed, never accepted as input.

    PRD 3.1: "A `STANDARD` agency gets exactly its `annual_submission_cap`." and
    "A newly registered agency has used nothing, so `submissions_used_count`
    begins at 0."

    Design: Corner/entities/agency_creation_returns_computed_effective_cap_and_zero_usage
    """
    response = api.create_agency(f.agency_payload(), platform_admin_headers())
    created = validate_success(response, 201)

    a.assert_response_type(response, "object")
    meta = _meta(response)
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert isinstance(meta["api_request_timestamp"], str) and meta["api_request_timestamp"]

    assert created["name"] == "Halcyon Talent Partners"
    assert created["agency_code"] == "HAL"
    assert created["relationship_tier"] == TIER_STANDARD
    assert created["packaging_allowed"] is True
    assert created["annual_submission_cap"] == 5
    assert created["effective_submission_cap"] == 5, "STANDARD takes the stored cap unchanged"
    assert created["submissions_used_count"] == 0, "no pitch has been submitted yet"

    a.assert_common_fields(created)
    a.assert_created_version_one(created)


def test_a_fresh_slate_reports_a_zeroed_ledger_and_an_open_posture(api):
    """With no deals, holds, pilots or negotiations every derived slate figure is zero.

    PRD 3.1: "All of the ledger figures described in 2.8 start at zero on a fresh
    slate."

    Design: Corner/entities/slate_retrieval_returns_a_zeroed_ledger_and_open_posture
    """
    ctx = fx.bootstrap(api)

    response = api.get_slate(ctx.slate_id, finance_controller_headers())
    slate = validate_success(response)
    a.assert_response_type(response, "object")

    a.assert_slate_dollar_ledger(
        slate, committed=0, reserved=0, writeoff=0, recouped=0, available=400000000
    )
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=0, available=20, posture=POSTURE_OPEN
    )
    assert slate["episode_capacity"] == 20
    a.assert_created_version_one(slate)


def test_the_writer_listing_narrows_to_one_agency_and_then_pages(api):
    """Two writers on one agency, one on another: the filter returns two, limit 1 returns one.

    PRD 2.3: "`has_more` is true exactly when `offset` plus the number of rows
    returned in `data` is still less than `total_count`."

    Design: Corner/entities/writer_listing_filters_by_agency_and_honours_limit_and_offset
    """
    hal = fx.create_agency(api)["id"]
    mrd = validate_success(
        api.create_agency(f.rival_agency_payload(), platform_admin_headers()), 201
    )["id"]

    ada = fx.create_writer(api, hal)["id"]
    bo = fx.create_writer(api, hal, dict(BO))["id"]
    cyd = fx.create_writer(api, mrd, dict(CYD))["id"]

    response = api.list_writers(
        platform_admin_headers(), {"agency_id": hal, "limit": 10, "offset": 0}
    )
    rows, meta = validate_paginated(response)
    a.assert_response_type(response, "array")
    assert len(rows) == 2, "only the two Halcyon writers match the filter"
    a.assert_pagination_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
    assert {row["id"] for row in rows} == {ada, bo}
    assert all(row["agency_id"] == hal for row in rows)
    assert cyd not in {row["id"] for row in rows}, "the rival agency's writer is filtered out"

    first_page, page_meta = validate_paginated(
        api.list_writers(
            platform_admin_headers(), {"agency_id": hal, "limit": 1, "offset": 0}
        )
    )
    assert len(first_page) == 1
    a.assert_pagination_meta(page_meta, limit=1, offset=0, total_count=2, has_more=True)


def test_reading_a_script_deal_that_does_not_exist_is_a_404_not_an_empty_200(api):
    """A well-formed UUID naming no row is a not-found error.

    PRD 2.6: "Each entity has its own not-found code: ... `ERR_SCRIPT_DEAL_NOT_FOUND`
    ... all with HTTP status 404."

    Design: Corner/entities/script_deal_retrieval_with_an_unknown_id_returns_not_found
    """
    missing = api.get_script_deal(NON_EXISTENT_UUID, business_affairs_headers())
    validate_error(missing, e.ERR_SCRIPT_DEAL_NOT_FOUND, 404)
    a.assert_error_meta_present(missing)


def test_a_script_deal_without_a_guaranteed_step_count_is_rejected_and_writes_nothing(api):
    """guaranteed_step_count has no default, so omitting it is an invalid request.

    PRD 2.11 priority 9: "The request body is well formed: required fields
    present, ... and the guaranteed step count between 1 and the number of
    submitted steps - else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/script_deal_create_missing_required_guaranteed_step_count_rejected
    """
    ctx = build_scenario(api, "project")

    payload = f.script_deal_payload(ctx.project_id, ctx.writer_id)
    payload.pop("guaranteed_step_count")

    rejected = api.create_script_deal(payload, business_affairs_headers())
    validate_error(rejected, e.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_script_deals(
            business_affairs_headers(), {"project_id": ctx.project_id, "limit": 10, "offset": 0}
        )
    )
    assert rows == [], "the rejected body must not leave a deal behind"
    a.assert_pagination_meta(meta, total_count=0)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=0, available=400000000)


def test_a_fresh_pitch_takes_every_declared_default(api):
    """Status, coverage round, score and recommendation are all server-set at submission.

    PRD 3.2: "A fresh pitch has `status` `SUBMITTED`, a `coverage_round` of 0, and
    a null `coverage_score` and null `recommendation`."

    Design: Corner/entities/pitch_creation_stamps_submitted_status_and_zero_coverage_round
    """
    ctx = fx.bootstrap(api)

    created = validate_success(
        api.create_pitch(
            f.pitch_payload(ctx.agency_id, ctx.slate_id), agency_rep_headers(ctx.agency_id)
        ),
        201,
    )

    assert created["status"] == PITCH_SUBMITTED
    assert created["coverage_round"] == 0
    assert created["coverage_score"] is None
    assert created["recommendation"] is None
    assert created["packaging_elements"] == []
    assert created["underlying_ip_key"] == "IP-FAULT-LINES"
    a.assert_common_fields(created)
    a.assert_created_version_one(created)


def test_a_new_holding_deal_is_active_in_term_and_reserves_its_cost(api):
    """status, termination_reason and term_state are all computed from the term and the clock.

    PRD 3.3: "it is `ACTIVE` from creation, becomes `TERMINATED` when it is torn
    up, and `termination_reason` is null for as long as the deal remains
    `ACTIVE`." and "`IN_TERM` while today is on or after `term_start_date` and
    still before `term_end_date`".

    Design: Corner/entities/holding_deal_creation_stamps_active_status_and_null_termination_reason
    """
    ctx = build_scenario(api, "writer")

    created = validate_success(
        api.create_holding_deal(
            f.holding_deal_payload(
                ctx.writer_id,
                ctx.slate_id,
                annual_cost_cents=2000000,
                start_date="2026-07-01",
                end_date="2027-07-01",
            ),
            business_affairs_headers(),
        ),
        201,
    )

    assert created["status"] == HOLDING_ACTIVE
    assert created["termination_reason"] is None
    assert created["term_state"] == TERM_IN_TERM, "the clock reads 2026-08-01, inside the term"
    a.assert_cents(created["annual_cost_cents"], 2000000, "annual_cost_cents")
    a.assert_created_version_one(created)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, reserved=2000000, available=398000000)

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["exclusivity_status"] == EXCLUSIVITY_HOLDING_DEAL


def test_the_pilot_budget_variance_is_measured_against_the_slates_pattern_budget(api):
    """33000000 against a 32000000 pattern is 312 bps once the remainder is discarded.

    PRD 3.5: "`budget_variance_bps`, computed as the pilot's `budget_cents` less
    the slate's `pattern_budget_per_episode_cents`, multiplied by 10000, divided by
    that same pattern budget with the remainder discarded".

    Design: Corner/entities/pilot_order_budget_variance_bps_is_computed_against_the_pattern_budget
    """
    ctx = build_scenario(api, "script_complete")

    ordered = validate_success(
        api.create_pilot_order(
            f.pilot_order_payload(ctx.project_id, budget_cents=33000000),
            development_exec_headers(),
        ),
        201,
    )

    # 1000000 * 10000 / 32000000 is 312.5, and the remainder is discarded.
    assert ordered["budget_variance_bps"] == 312
    assert ordered["production_status"] == PRODUCTION_ORDERED
    assert ordered["casting_status"] == CONTINGENCY_PENDING
    assert ordered["location_status"] == CONTINGENCY_PENDING
    assert ordered["collapsed_reason"] is None

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_ORDERED
    a.assert_cents(
        project["cumulative_dev_cost_cents"], 37375000, "cumulative_dev_cost_cents"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=37375000, available=362625000)


def test_a_chain_of_title_value_outside_the_declared_set_is_refused(api):
    """A chain of title reported as MESSY is outside the declared set, so nothing is filed.

    PRD 3.2: "the `chain_of_title_status` that the search returned - one of
    `CLEAN`, `DISPUTED` or `UNKNOWN`".

    Design: Corner/entities/rights_check_with_an_unknown_chain_of_title_enum_returns_invalid_request
    """
    ctx = build_scenario(api, "pitch")

    rejected = api.file_rights_check(
        ctx.pitch_id,
        f.rights_check_payload(chain_of_title_status="MESSY"),
        business_affairs_headers(),
    )
    validate_error(rejected, e.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_rights_checks(ctx.pitch_id, business_affairs_headers())
    )
    assert rows == [], "a rejected clearance body files nothing"
    a.assert_pagination_meta(meta, total_count=0)


def test_a_filed_clearance_carries_no_version_and_no_updated_at(api):
    """The rights check is the contract's one immutable record: id and created_at only.

    PRD 2.5: "A rights check is an immutable clearance record: it carries only
    `id` and `created_at`. It has no `updated_at` and no `version` at all, because
    nothing in the system ever modifies a filed clearance."

    Design: Corner/entities/rights_check_is_immutable_carrying_no_version_and_no_update_endpoint
    """
    ctx = build_scenario(api, "pitch")
    fx.file_rights_check(api, ctx.pitch_id)

    rows, meta = validate_paginated(
        api.list_rights_checks(ctx.pitch_id, business_affairs_headers())
    )
    assert len(rows) == 1
    a.assert_pagination_meta(meta, total_count=1)

    filed = rows[0]
    a.assert_immutable_record_fields(filed)
    assert filed["chain_of_title_status"] == CHAIN_OF_TITLE_CLEAN
    assert filed["result"] == RIGHTS_RESULT_CLEAR, "CLEAN yields CLEAR"
    assert filed["quiet_period_end_date"] == "2026-05-30", (
        "the quiet buffer runs 90 calendar days beyond holdback_end_date 2026-03-01"
    )


def test_a_clearance_filed_under_a_pitch_that_does_not_exist_is_a_404(api):
    """The clearance is a nested child, so the parent path id is resolved first.

    PRD 2.6: "Identifiers in a URL path are resolved strictly left to right, and
    the first identifier that does not resolve determines the 404 response."

    Design: Corner/entities/rights_check_filed_under_an_unknown_pitch_returns_pitch_not_found
    """
    rejected = api.file_rights_check(
        NON_EXISTENT_UUID, f.rights_check_payload(), business_affairs_headers()
    )
    validate_error(rejected, e.ERR_PITCH_NOT_FOUND, 404)


def test_a_real_writer_with_a_bogus_project_reports_the_project_as_missing(api):
    """Body foreign keys resolve in the order agency, slate, writer, project.

    PRD 2.6: "Any of `agency_id`, `slate_id`, `writer_id`, `project_id` or
    `negotiation_id` that names a row which does not exist produces that entity's
    not-found error."

    Design: Corner/entities/script_deal_naming_an_unknown_project_id_returns_project_not_found
    """
    ctx = build_scenario(api, "writer")

    rejected = api.create_script_deal(
        f.script_deal_payload(NON_EXISTENT_UUID, ctx.writer_id),
        business_affairs_headers(),
    )
    validate_error(rejected, e.ERR_PROJECT_NOT_FOUND, 404)


def test_the_turnaround_successor_points_back_at_the_project_it_replaced(api):
    """The successor is reverse-reachable from the abandoned project it descends from.

    PRD 3.9: "a successor project is created in the same request: it carries
    `predecessor_project_id` pointing at the abandoned project, `pitch_id` and
    `slate_id` copied from it, a `title` equal to the submitted `successor_title`,
    `dev_status` `ACTIVE_DEVELOPMENT` and `turnaround_status` `NONE`."

    Design: Corner/entities/turnaround_successor_project_links_back_to_its_predecessor
    """
    ctx = fx.turnaround_offered(api, "deal")

    successor = validate_success(
        api.exercise_turnaround(
            ctx.project_id,
            f.turnaround_exercise_payload("Fault Lines Redux"),
            business_affairs_headers(),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_projects(
            business_affairs_headers(),
            {"predecessor_project_id": ctx.project_id, "limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 1
    a.assert_pagination_meta(meta, total_count=1)

    found = rows[0]
    assert found["id"] == successor["id"], "the exercise response is the successor itself"
    assert found["predecessor_project_id"] == ctx.project_id
    assert found["title"] == "Fault Lines Redux"
    assert found["pitch_id"] == ctx.pitch_id
    assert found["slate_id"] == ctx.slate_id
    assert found["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    assert found["turnaround_status"] == TURNAROUND_NONE
    a.assert_cents(found["writeoff_cents"], 0, "successor writeoff_cents")
    a.assert_cents(
        found["cumulative_dev_cost_cents"], 0, "successor cumulative_dev_cost_cents"
    )

    predecessor = validate_success(
        api.get_project(ctx.project_id, business_affairs_headers())
    )
    assert predecessor["dev_status"] == DEV_ABANDONED
    assert predecessor["turnaround_status"] == TURNAROUND_EXERCISED
    a.assert_cents(predecessor["writeoff_cents"], 4375000, "writeoff_cents")
    # Zero whole months elapsed, so no interest; 4375000 sits in the first handling
    # tier, so the payment is 4375000 + 0 + 250000.
    a.assert_cents(
        predecessor["recoupment_paid_cents"], 4625000, "recoupment_paid_cents"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(
        slate, committed=0, writeoff=4375000, recouped=4625000, available=400250000
    )
