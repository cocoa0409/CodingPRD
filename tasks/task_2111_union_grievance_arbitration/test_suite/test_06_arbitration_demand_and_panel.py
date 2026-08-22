"""Demanding arbitration, issuing the strike panel and the alternate-strike cascade."""

from test_helpers import (
    DIRECTOR,
    ApiErrorId,
    advance_to_step3_answered,
    assert_cost_allocation,
    assert_instant,
    assert_panel_strike,
    create_arbitrator,
    file_grievance,
    file_prep_through_briefs,
    grievance_version,
    post_cost_entry,
    read_grievance,
    record_award,
    request_panel,
    schedule_hearing,
    set_clock,
    setup_award_ready_case,
    setup_base,
    setup_demanded_case,
    take_strike,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_ARBITRABLE_CLAUSE = {
    "clause_number": "ART-07",
    "title": "Subcontracting",
    "category": "SUBCONTRACTING",
    "is_arbitrable": False,
}


def _case_at_step3(clause_overrides=None, statement="Discharge without just cause"):
    ctx = setup_base(clause_overrides=clause_overrides)
    ctx["grievance"] = file_grievance(ctx, statement=statement)
    advance_to_step3_answered(ctx)
    return ctx


def test_non_arbitrable_clause_pre_empts_the_expired_demand_window(api):
    """PRD §2.10: "The grievance's cited clause is arbitrable — otherwise
    `ERR_CLAUSE_NOT_ARBITRABLE`, on arbitration demand."
    PRD §3.1: "`is_arbitrable` defaults to true; when it is false no arbitration may ever be
    demanded on a grievance citing that clause, and the attempt is rejected with
    `ERR_CLAUSE_NOT_ARBITRABLE`."

    Design: Difficulty/priority_pair_validation_conflict/clause_arbitrability_beats_demand_deadline
    """
    ctx = _case_at_step3(
        clause_overrides=NON_ARBITRABLE_CLAUSE,
        statement="Bargaining unit work contracted out",
    )
    set_clock("2026-09-20T00:00:00Z")

    grievance = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])
    assert_instant(
        grievance["arbitration_deadline_at"], "2026-09-04T00:00:00Z", "arbitration_deadline_at"
    )

    response = api.create_arbitration_demand(
        ctx["grievance"]["id"],
        {
            "panel_source": "AAA",
            "panel_size": 3,
            "expected_grievance_version": grievance["version"],
        },
        ctx["steward_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CLAUSE_NOT_ARBITRABLE.value)


def test_the_refused_demand_leaves_the_barred_case_untouched(api, analyst_headers):
    """PRD §3.3: "Otherwise, if `current_step` is 3, the latest step has a resolution
    instant, no arbitration demand exists for the grievance, and the clock is strictly past
    `arbitration_deadline_at`, the posture is `BARRED`."
    PRD §3.6: "The grievance's `current_step` must be 3, the cited clause must have
    `is_arbitrable` true, the agreement must still be `ACTIVE`, and the clock must be at or
    before the grievance's `arbitration_deadline_at` — a later demand is rejected with
    `ERR_ARBITRATION_DEMAND_UNTIMELY`."

    Design: Difficulty/priority_pair_validation_conflict/clause_arbitrability_beats_demand_deadline
    """
    ctx = _case_at_step3(
        clause_overrides=NON_ARBITRABLE_CLAUSE,
        statement="Bargaining unit work contracted out",
    )
    set_clock("2026-09-20T00:00:00Z")

    validate_error(
        api.create_arbitration_demand(
            ctx["grievance"]["id"],
            {
                "panel_source": "AAA",
                "panel_size": 3,
                "expected_grievance_version": grievance_version(ctx["grievance"]["id"]),
            },
            ctx["steward_headers"],
        ),
        ApiErrorId.ERR_CLAUSE_NOT_ARBITRABLE.value,
    )

    grievance = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])
    assert grievance["status"] == "ANSWERED"
    assert grievance["timeliness_state"] == "BARRED"

    _, meta = validate_paginated(
        api.list_arbitration_demands(
            analyst_headers, params={"grievance_id": ctx["grievance"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def _demanded_case_with_counsel_cost():
    """Demand in PANEL_ISSUED, one union strike taken, 900000 cents of counsel on the
    ledger and Ben Chan carrying an engagement ceiling of one."""
    ctx = setup_demanded_case(chan_overrides={"max_concurrent_cases": 1})
    post_cost_entry(ctx["grievance"]["id"], "COUNSEL", 900_000, "EMPLOYER")
    ctx["panel"] = request_panel(ctx["demand"]["id"])["panel_arbitrator_ids"]
    take_strike(ctx["demand"]["id"], ctx["alvarez"]["id"], ctx["steward_headers"])
    return ctx


def test_the_last_strike_selects_the_surviving_candidate(api, analyst_headers):
    """PRD §3.6: "When the remainder is exactly 1, the strike is the last one: whether the
    demand was at `PANEL_ISSUED` (a three-member panel's second strike) or at `STRIKING`, it
    moves to `ARBITRATOR_SELECTED`, `selected_arbitrator_id` becomes the one unstruck
    candidate, and `strike_turn` becomes null."
    PRD §3.6: "Each accepted strike writes an immutable strike record carrying its
    `arbitration_demand_id`, its `arbitrator_id`, a `struck_by` party derived from the acting
    role rather than supplied, a 1-based `strike_order` within its demand, and the acting
    operator's `struck_by_user_id`; it increments the demand's `strikes_taken` by 1 and flips
    `strike_turn` to the other party."

    Design: Difficulty/transitive_cascade/final_strike_engages_arbitrator_posts_fee_shifts_cost_posture
    """
    ctx = _demanded_case_with_counsel_cost()

    strike = validate_success(
        api.create_panel_strike(
            ctx["demand"]["id"], {"arbitrator_id": ctx["dowd"]["id"]}, DIRECTOR
        ),
        201,
    )
    assert_panel_strike(strike)
    assert strike["strike_order"] == 2
    assert strike["struck_by"] == "EMPLOYER"

    demand = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], analyst_headers), 200
    )
    assert demand["status"] == "ARBITRATOR_SELECTED"
    assert demand["selected_arbitrator_id"] == ctx["chan"]["id"]
    assert demand["strike_turn"] is None
    assert demand["strikes_taken"] == 2


def test_selection_engages_the_arbitrator_and_fills_their_ceiling(api, administrator_headers):
    """PRD §3.6: "Because the demand entered `ARBITRATOR_SELECTED`, the selected
    arbitrator's `active_case_count` rises by 1 and their `status` is re-derived, which flips
    them from `AVAILABLE` to `FULL` when the ceiling is reached."

    Design: Difficulty/transitive_cascade/final_strike_engages_arbitrator_posts_fee_shifts_cost_posture
    """
    ctx = _demanded_case_with_counsel_cost()
    before = validate_success(api.get_arbitrator(ctx["chan"]["id"], administrator_headers), 200)
    assert before["active_case_count"] == 0
    assert before["status"] == "AVAILABLE"

    take_strike(ctx["demand"]["id"], ctx["dowd"]["id"], DIRECTOR)

    after = validate_success(api.get_arbitrator(ctx["chan"]["id"], administrator_headers), 200)
    assert after["active_case_count"] == 1
    assert after["status"] == "FULL"


def test_selection_posts_the_system_arbitrator_retainer(api, analyst_headers):
    """PRD §3.6: "Because an arbitrator became engaged, a system-origin cost entry is posted
    against the grievance with `category` `ARBITRATOR_FEE`, `bearing_party` `SPLIT` and
    `amount_cents` equal to the arbitrator's `per_diem_cents` multiplied by a two-day
    retainer."

    Design: Difficulty/transitive_cascade/final_strike_engages_arbitrator_posts_fee_shifts_cost_posture
    """
    ctx = _demanded_case_with_counsel_cost()
    take_strike(ctx["demand"]["id"], ctx["dowd"]["id"], DIRECTOR)

    rows, meta = validate_paginated(
        api.list_cost_entries(
            ctx["grievance"]["id"], analyst_headers, params={"category": "ARBITRATOR_FEE"}
        )
    )
    assert meta["total_count"] == 1
    fee = rows[0]
    assert fee["amount_cents"] == 400_000, "200000 per diem times the two-day retainer"
    assert fee["bearing_party"] == "SPLIT"
    assert fee["origin"] == "SYSTEM"
    assert fee["status"] == "POSTED"


def test_the_posted_retainer_steps_the_case_cost_posture(api, analyst_headers):
    """PRD §3.6: "And because a cost entry was posted, the grievance's `total_cost_cents`,
    `union_cost_share_cents` and `employer_cost_share_cents` are re-derived by the allocation
    of §3.9 and its `cost_posture` may step from `COST_OK` to `COST_WATCH` or on to
    `COST_BREACH`."
    PRD §3.9: "Finally, `cost_posture` is derived from the grand total: `COST_OK` at
    1,000,000 cents or less, `COST_WATCH` above that and up to 5,000,000 cents, and
    `COST_BREACH` above that."

    Design: Difficulty/transitive_cascade/final_strike_engages_arbitrator_posts_fee_shifts_cost_posture
    """
    ctx = _demanded_case_with_counsel_cost()

    before = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(before, total=972_000, union=0, employer=972_000)
    assert before["cost_posture"] == "COST_OK"

    take_strike(ctx["demand"]["id"], ctx["dowd"]["id"], DIRECTOR)

    after = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(after, total=1_384_800, union=240_000, employer=1_144_800)
    assert after["cost_posture"] == "COST_WATCH"


def test_panel_request_is_refused_while_the_eligible_pool_is_too_small(api, administrator_headers, analyst_headers):
    """PRD §3.6: "An arbitrator is eligible when all four of the following hold: `is_active`
    is true; `active_case_count` is strictly less than `max_concurrent_cases`; the demand's
    `panel_source` appears in the arbitrator's `panel_memberships`; and
    `earliest_available_at` is at or before ninety days after the demand's `demanded_at`."
    PRD §3.6: "If the eligible pool holds fewer arbitrators than `panel_size`, the request is
    rejected with `ERR_PANEL_POOL_INSUFFICIENT` and nothing at all is written."

    Design: Corner/calculations/panel_selection_ranking_exclusion_and_insufficient_pool
    """
    ctx = setup_base()
    create_arbitrator(full_name="Ruth Alvarez", per_diem_cents=250_000)
    create_arbitrator(full_name="Ben Chan", per_diem_cents=200_000)
    create_arbitrator(full_name="Cara Dowd", per_diem_cents=200_000)
    create_arbitrator(full_name="Dev Patel", per_diem_cents=180_000, is_active=False)
    create_arbitrator(
        full_name="Eve Ross", per_diem_cents=150_000,
        earliest_available_at="2026-12-31T00:00:00Z",
    )
    ctx["grievance"] = file_grievance(ctx, statement="Discharge without just cause")
    advance_to_step3_answered(ctx)
    demand = validate_success(
        api.create_arbitration_demand(
            ctx["grievance"]["id"],
            {
                "panel_source": "AAA",
                "panel_size": 5,
                "expected_grievance_version": grievance_version(ctx["grievance"]["id"]),
            },
            ctx["steward_headers"],
        ),
        201,
    )

    refused = api.request_panel(demand["id"], administrator_headers)
    validate_error(refused, ApiErrorId.ERR_PANEL_POOL_INSUFFICIENT.value)

    unchanged = validate_success(api.get_arbitration_demand(demand["id"], analyst_headers), 200)
    assert unchanged["status"] == "DEMANDED"
    assert unchanged["panel_arbitrator_ids"] == []


def test_panel_is_ranked_by_engagement_then_per_diem_then_creation_order(api, administrator_headers):
    """PRD §3.6: "The eligible pool is ranked by ascending `active_case_count`, then by
    ascending `per_diem_cents`, then by ascending `created_at` as the final tie-break, and the
    first `panel_size` candidates in rank order are stored in `panel_arbitrator_ids` in that
    order."
    PRD §3.6: "A successful issue moves the demand to `PANEL_ISSUED`, sets `strike_turn` to
    `UNION` — the union always strikes first — and leaves `strikes_taken` at 0."

    Design: Corner/calculations/panel_selection_ranking_exclusion_and_insufficient_pool
    """
    ctx = setup_base()
    alvarez = create_arbitrator(full_name="Ruth Alvarez", per_diem_cents=250_000)
    chan = create_arbitrator(full_name="Ben Chan", per_diem_cents=200_000)
    dowd = create_arbitrator(full_name="Cara Dowd", per_diem_cents=200_000)
    patel = create_arbitrator(full_name="Dev Patel", per_diem_cents=180_000, is_active=False)
    ross = create_arbitrator(
        full_name="Eve Ross", per_diem_cents=150_000,
        earliest_available_at="2026-12-31T00:00:00Z",
    )
    ctx["grievance"] = file_grievance(ctx, statement="Discharge without just cause")
    advance_to_step3_answered(ctx)
    demand = validate_success(
        api.create_arbitration_demand(
            ctx["grievance"]["id"],
            {
                "panel_source": "AAA",
                "panel_size": 5,
                "expected_grievance_version": grievance_version(ctx["grievance"]["id"]),
            },
            ctx["steward_headers"],
        ),
        201,
    )

    reinstated = validate_success(
        api.update_arbitrator(patel["id"], {"is_active": True}, administrator_headers), 200
    )
    assert reinstated["status"] == "AVAILABLE"
    validate_success(
        api.update_arbitrator(
            ross["id"], {"earliest_available_at": "2026-08-01T00:00:00Z"}, administrator_headers
        ),
        200,
    )

    issued = validate_success(api.request_panel(demand["id"], administrator_headers), 200)

    assert issued["panel_arbitrator_ids"] == [
        ross["id"], patel["id"], chan["id"], dowd["id"], alvarez["id"]
    ], "ranked by engagement, then per diem, then created_at"
    assert issued["status"] == "PANEL_ISSUED"
    assert issued["strike_turn"] == "UNION"
    assert issued["strikes_taken"] == 0


def test_illegal_panel_size_is_refused_and_the_legal_one_is_accepted(api, analyst_headers):
    """PRD §3.6: "The demand payload names the `panel_source` the candidates will be drawn
    from — `AAA`, `FMCS` or `PERMANENT_UMPIRE` — the `panel_size` of 3, 5 or 7 (any other
    value is rejected with `ERR_INVALID_PANEL_SIZE`), and the mandatory
    `expected_grievance_version` of §2.7."
    PRD §3.6: "Either route creates the demand at `DEMANDED` with `prep_status` at
    `PREP_NOT_STARTED`, stamps `demanded_at` with the clock's current instant, copies the
    grievance's `arbitration_deadline_at` into the demand's `demand_deadline_at` as the record
    of the instant after which the demand would have been untimely, moves the grievance to
    `ARBITRATION_DEMANDED`, and increments the grievance's `version` by 1."

    Design: Corner/validations/arbitration_demand_with_an_illegal_panel_size_is_refused
    """
    ctx = _case_at_step3()
    version = grievance_version(ctx["grievance"]["id"])

    refused = api.create_arbitration_demand(
        ctx["grievance"]["id"],
        {"panel_source": "AAA", "panel_size": 4, "expected_grievance_version": version},
        ctx["steward_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_PANEL_SIZE.value)

    still_answered = read_grievance(ctx["grievance"]["id"])
    assert still_answered["status"] == "ANSWERED"
    assert still_answered["version"] == version

    demand = validate_success(
        api.create_arbitration_demand(
            ctx["grievance"]["id"],
            {"panel_source": "AAA", "panel_size": 3, "expected_grievance_version": version},
            ctx["steward_headers"],
        ),
        201,
    )
    assert demand["status"] == "DEMANDED"
    assert demand["prep_status"] == "PREP_NOT_STARTED"
    assert demand["panel_arbitrator_ids"] == []
    assert_instant(
        demand["demand_deadline_at"], "2026-09-04T00:00:00Z", "demand_deadline_at"
    )
    assert read_grievance(ctx["grievance"]["id"])["status"] == "ARBITRATION_DEMANDED"


def test_demand_after_the_arbitration_window_on_an_arbitrable_clause_is_refused(api, analyst_headers):
    """PRD §3.6: "The grievance's `current_step` must be 3, the cited clause must have
    `is_arbitrable` true, the agreement must still be `ACTIVE`, and the clock must be at or
    before the grievance's `arbitration_deadline_at` — a later demand is rejected with
    `ERR_ARBITRATION_DEMAND_UNTIMELY`."

    Design: Corner/validations/arbitration_demand_after_the_window_on_an_arbitrable_clause_is_refused
    """
    ctx = _case_at_step3()
    set_clock("2026-09-20T00:00:00Z")

    grievance = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])
    assert_instant(
        grievance["arbitration_deadline_at"], "2026-09-04T00:00:00Z", "arbitration_deadline_at"
    )

    response = api.create_arbitration_demand(
        ctx["grievance"]["id"],
        {
            "panel_source": "AAA",
            "panel_size": 3,
            "expected_grievance_version": grievance["version"],
        },
        ctx["steward_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ARBITRATION_DEMAND_UNTIMELY.value)

    after = read_grievance(ctx["grievance"]["id"])
    assert after["status"] == "ANSWERED"
    assert after["timeliness_state"] == "BARRED"
    _, meta = validate_paginated(
        api.list_arbitration_demands(
            analyst_headers, params={"grievance_id": ctx["grievance"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_stale_grievance_version_pre_empts_the_panel_size_check(api):
    """PRD §2.7: "Filing an arbitration demand likewise requires `expected_grievance_version`
    as a non-optional field, and likewise rejects a mismatch against the grievance's current
    `version` with `ERR_STALE_GRIEVANCE_VERSION` (HTTP 412)."
    PRD §2.10: "When a single request would fail several checks, the outcome is not a matter
    of taste: the checks are evaluated strictly in the order below, and the **first** check
    that fails determines the error the caller receives."

    Design: Corner/cross_cutting_layers/occ_rejects_an_arbitration_demand_carrying_a_stale_grievance_version
    """
    ctx = _case_at_step3()
    version = grievance_version(ctx["grievance"]["id"])

    response = api.create_arbitration_demand(
        ctx["grievance"]["id"],
        {"panel_source": "AAA", "panel_size": 4, "expected_grievance_version": version - 1},
        ctx["steward_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_GRIEVANCE_VERSION.value)

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "ANSWERED"
    assert grievance["version"] == version


def test_demand_with_the_current_version_is_accepted_and_bumps_it(api):
    """PRD §2.8: "Four acts additionally increment the parent grievance's `version`
    explicitly, because that counter is the anchor of the optimistic-concurrency checks in
    §2.7: authorizing a settlement offer, filing an arbitration demand, recording an award,
    and the closure of a grievance when its award becomes fully implemented."

    Design: Corner/cross_cutting_layers/occ_rejects_an_arbitration_demand_carrying_a_stale_grievance_version
    """
    ctx = _case_at_step3()
    version = grievance_version(ctx["grievance"]["id"])

    demand = validate_success(
        api.create_arbitration_demand(
            ctx["grievance"]["id"],
            {"panel_source": "AAA", "panel_size": 3, "expected_grievance_version": version},
            ctx["steward_headers"],
        ),
        201,
    )
    assert demand["status"] == "DEMANDED"

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["version"] == version + 1
    assert grievance["status"] == "ARBITRATION_DEMANDED"


def test_panel_and_strike_rejections_guard_the_alternate_strike(api, administrator_headers, analyst_headers):
    """PRD §3.6: "A second attempt to issue a panel on the same demand is rejected with
    `ERR_DEMAND_STATE_INVALID`."
    PRD §3.6: "A strike is taken by a `UnionSteward` for the union or a
    `LaborRelationsDirector` for the employer, and the acting role's party must equal the
    demand's current `strike_turn`, or the strike is rejected with `ERR_NOT_STRIKE_TURN`. The
    payload names the `arbitrator_id` being removed, which must appear in
    `panel_arbitrator_ids` and must not already have been struck on this demand, failing
    otherwise with `ERR_ARBITRATOR_NOT_ON_PANEL`."

    Design: Corner/errors/arbitration_strike_panel_and_award_gate_rejections
    """
    ctx = setup_demanded_case()
    vance = create_arbitrator(full_name="Hugo Vance", per_diem_cents=400_000)

    issued = validate_success(api.request_panel(ctx["demand"]["id"], administrator_headers), 200)
    assert issued["panel_arbitrator_ids"] == [
        ctx["chan"]["id"], ctx["dowd"]["id"], ctx["alvarez"]["id"]
    ]
    assert vance["id"] not in issued["panel_arbitrator_ids"]

    validate_error(
        api.request_panel(ctx["demand"]["id"], administrator_headers),
        ApiErrorId.ERR_DEMAND_STATE_INVALID.value,
    )

    out_of_turn = api.create_panel_strike(
        ctx["demand"]["id"], {"arbitrator_id": ctx["alvarez"]["id"]}, DIRECTOR
    )
    validate_error(out_of_turn, ApiErrorId.ERR_NOT_STRIKE_TURN.value)

    off_panel = api.create_panel_strike(
        ctx["demand"]["id"], {"arbitrator_id": vance["id"]}, ctx["steward_headers"]
    )
    validate_error(off_panel, ApiErrorId.ERR_ARBITRATOR_NOT_ON_PANEL.value)

    demand = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], analyst_headers), 200
    )
    assert demand["strikes_taken"] == 0
    assert demand["strike_turn"] == "UNION"


def test_inverted_hearing_window_is_refused(api, administrator_headers, analyst_headers):
    """PRD §3.8: "The payload carries `hearing_start_at` and `hearing_end_at`, the latter
    strictly after the former or the request is rejected with `ERR_INVALID_HEARING_WINDOW`."

    Design: Corner/errors/arbitration_strike_panel_and_award_gate_rejections
    """
    ctx = setup_demanded_case()
    request_panel(ctx["demand"]["id"])
    take_strike(ctx["demand"]["id"], ctx["alvarez"]["id"], ctx["steward_headers"])
    take_strike(ctx["demand"]["id"], ctx["dowd"]["id"], DIRECTOR)

    response = api.schedule_hearing(
        ctx["demand"]["id"],
        {"hearing_start_at": "2026-10-06T17:00:00Z", "hearing_end_at": "2026-10-05T09:00:00Z"},
        administrator_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_HEARING_WINDOW.value)

    demand = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], analyst_headers), 200
    )
    assert demand["status"] == "ARBITRATOR_SELECTED"
    assert demand["hearing_start_at"] is None


def test_award_gates_refuse_an_early_award_and_a_second_award(api, administrator_headers):
    """PRD §3.8: "The demand must stand at `HEARING_SCHEDULED` and the clock must have
    reached or passed `hearing_end_at`, or the request is rejected with
    `ERR_HEARING_NOT_CONCLUDED`; when both hold, the system advances the demand from
    `HEARING_SCHEDULED` to `HEARD` inside the same request and then on to `AWARDED`."
    PRD §3.8: "No award may already exist on the demand; a second attempt is rejected with
    `ERR_AWARD_STATE_INVALID`."

    Design: Corner/errors/arbitration_strike_panel_and_award_gate_rejections
    """
    ctx = setup_demanded_case()
    request_panel(ctx["demand"]["id"])
    take_strike(ctx["demand"]["id"], ctx["alvarez"]["id"], ctx["steward_headers"])
    take_strike(ctx["demand"]["id"], ctx["dowd"]["id"], DIRECTOR)
    schedule_hearing(ctx["demand"]["id"])

    early = api.create_award(
        ctx["demand"]["id"], {"outcome": "DENIED", "sustained_fraction_bps": 0},
        administrator_headers,
    )
    validate_error(early, ApiErrorId.ERR_HEARING_NOT_CONCLUDED.value)

    set_clock("2026-10-07T00:00:00Z")
    file_prep_through_briefs(ctx["demand"]["id"], exhibit_count=7)
    award = record_award(ctx["demand"]["id"], outcome="DENIED")
    assert award["outcome"] == "DENIED"

    second = api.create_award(
        ctx["demand"]["id"], {"outcome": "SUSTAINED", "sustained_fraction_bps": 10_000},
        administrator_headers,
    )
    validate_error(second, ApiErrorId.ERR_AWARD_STATE_INVALID.value)

    unchanged = validate_success(api.get_award(award["id"], administrator_headers), 200)
    assert unchanged["outcome"] == "DENIED"


def test_panel_strike_listings_are_the_only_channel_onto_the_strike_records(
    api, analyst_headers, administrator_headers
):
    """PRD §2.3: "- Strikes taken on one arbitration demand: ascending `strike_order`."
    PRD §2.5: "Two resource types are exceptions and carry only `id` and `created_at`: a
    `PrecedentCase`, which is immutable reference data once recorded, and a `PanelStrike`,
    which is an immutable event record. Neither has an `updated_at` field and neither has a
    `version` field; those keys are absent from their payloads entirely."

    Design: Corner/endpoints/arbitration_sub_resource_reads_expose_cascade_created_rows
    """
    ctx = setup_award_ready_case()

    rows, meta = validate_paginated(
        api.list_panel_strikes(ctx["demand"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 2
    assert rows[0]["strike_order"] == 1
    assert rows[0]["struck_by"] == "UNION"
    assert rows[1]["strike_order"] == 2
    assert rows[1]["struck_by"] == "EMPLOYER"
    for row in rows:
        assert_panel_strike(row)

    struck, struck_meta = validate_paginated(
        api.list_arbitrator_strike_history(ctx["alvarez"]["id"], administrator_headers)
    )
    assert struck_meta["total_count"] == 1
    assert struck[0]["struck_by"] == "UNION"

    _, survivor_meta = validate_paginated(
        api.list_arbitrator_strike_history(ctx["chan"]["id"], administrator_headers)
    )
    assert survivor_meta["total_count"] == 0, "the survivor was never struck"


def test_award_sub_resource_lists_the_single_recorded_award(api, analyst_headers):
    """PRD §4: "List the award recorded on this demand; the array holds zero or one row.
    Ordered by created_at ASC."
    PRD §3.8: "`outcome` is `SUSTAINED`, `DENIED` or `SPLIT`. `sustained_fraction_bps`
    defaults to 10,000 and must be exactly 10,000 for a `SUSTAINED` outcome, exactly 0 for a
    `DENIED` outcome, and strictly between 0 and 10,000 for a `SPLIT` outcome."

    Design: Corner/endpoints/arbitration_sub_resource_reads_expose_cascade_created_rows
    """
    ctx = setup_award_ready_case()
    award = record_award(ctx["demand"]["id"], outcome="DENIED")

    rows, meta = validate_paginated(
        api.list_demand_awards(ctx["demand"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == award["id"]

    read = validate_success(api.get_award(award["id"], analyst_headers), 200)
    assert read["outcome"] == "DENIED"
    assert read["gross_remedy_cents"] == 0
    assert read["net_remedy_cents"] == 0
