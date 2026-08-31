"""Writer engagements, the milestone ladder and the conserved fee ledger."""

from test_helpers import (
    BA_APPROVER,
    BA_PAYER,
    EXEC_ALPHA,
    ApiErrorId,
    assert_milestone_payment,
    assert_milestone_schedule_reconciles,
    attach_engagement,
    approve_milestone,
    create_engagement,
    create_option,
    create_project,
    create_property,
    create_writer,
    deliver,
    fetch_engagement,
    fetch_milestone,
    fetch_option,
    fetch_project,
    fetch_writer,
    make_clear_property,
    make_writer_headers,
    milestone_of_type,
    milestones_for_engagement,
    project_version,
    set_clock,
    setup_clear_property_with_active_option,
    setup_development_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# The milestone schedule
# ==========================================================================


def _production_rewrite_ready_to_attach():
    set_clock("2026-09-01T00:00:00Z")
    return setup_development_pipeline(
        genre="THRILLER",
        title="Nine Bridges",
        engagement_type="PRODUCTION_REWRITE",
        total_fee_cents=7_500_001,
        writer_name="W1 Ferrante",
        attach=False,
    )


def test_milestone_lines_are_floored_and_the_remainder_goes_to_the_largest_share(api):
    """PRD 3.7: "First, every line's `gross_amount_cents` is computed as
    `total_fee_cents` multiplied by that line's `percentage_bps`, divided by ten
    thousand, and **floored** — never rounded."
    PRD 3.7: "Then the remainder, being `total_fee_cents` less the sum of all the
    floored lines, is pushed in its entirety into exactly one line: the line with the
    largest `percentage_bps`."
    PRD 3.7: "The invariant this protects is that the sum of `gross_amount_cents`
    across an engagement's milestones equals its `total_fee_cents` exactly, always."

    Design: Difficulty/combinatorial_formula/milestone_floor_per_line_then_remainder_to_largest_share
    """
    ctx = _production_rewrite_ready_to_attach()
    attach_engagement(ctx["engagement"]["id"])

    rows = {
        row["milestone_type"]: row
        for row in milestones_for_engagement(ctx["engagement"]["id"])
    }
    for row in rows.values():
        assert_milestone_payment(row)

    commencement = rows["COMMENCEMENT"]
    assert commencement["sequence_index"] == 0
    assert commencement["percentage_bps"] == 3334
    assert commencement["gross_amount_cents"] == 2_500_501, (
        "the 1-cent remainder lands on the largest-share line"
    )
    assert commencement["status"] == "DUE"

    rewrite = rows["REWRITE_DELIVERY"]
    assert rewrite["sequence_index"] == 1
    assert rewrite["percentage_bps"] == 3333
    assert rewrite["gross_amount_cents"] == 2_499_750
    assert rewrite["status"] == "SCHEDULED"

    bonus = rows["PRODUCTION_BONUS"]
    assert bonus["sequence_index"] == 2
    assert bonus["percentage_bps"] == 3333
    assert bonus["gross_amount_cents"] == 2_499_750
    assert bonus["status"] == "SCHEDULED"

    assert_milestone_schedule_reconciles(rows.values(), 7_500_001)


def test_attachment_moves_the_writer_and_project_ledgers_and_the_development_axis(api):
    """PRD 3.7: "Attachment generates the engagement's milestone payments from a
    template selected by `engagement_type`, sets `milestone_count` to the number of
    lines in that template, adds `total_fee_cents` to both the writer's
    `committed_fee_cents` and the project's `committed_writer_fee_cents`, increments
    the writer's `active_engagement_count` by one, and advances the project's
    development axis as Section 3.6 describes."
    PRD 3.6: "On the development axis: attaching an engagement of type
    `ORIGINAL_DRAFT`, `REWRITE` or `PRODUCTION_REWRITE` takes `SETUP → WRITING`, and
    this is admissible while the rights axis holds either `OPTIONED` or `OWNED`."

    Design: Difficulty/combinatorial_formula/milestone_floor_per_line_then_remainder_to_largest_share
    """
    ctx = _production_rewrite_ready_to_attach()

    resp = api.attach_engagement(ctx["engagement"]["id"], EXEC_ALPHA)
    data = validate_success(resp, 200)

    assert data["status"] == "ATTACHED"
    assert data["milestone_count"] == 3

    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["committed_fee_cents"] == 7_500_001
    assert writer["paid_fee_cents"] == 0

    project = fetch_project(ctx["project"]["id"])
    assert project["committed_writer_fee_cents"] == 7_500_001
    assert project["development_status"] == "WRITING"


def test_milestone_remainder_tie_break_goes_to_the_lowest_sequence_index(api):
    """PRD 3.7: "When two lines share the largest `percentage_bps`, the remainder goes
    to the one with the lowest `sequence_index`; neither `created_at` nor `id` is ever
    consulted."
    PRD 3.6: "Attaching a `POLISH` engagement takes `DRAFT_DELIVERED → POLISH`, and
    delivering that polish takes `POLISH → POLISH_DELIVERED`."

    Design: Corner/calculations/milestone_remainder_tie_break_lowest_sequence_index_on_polish
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(
        genre="DRAMA", title="Polish Pass", pay_commencement=True,
        deliver_first_draft=True,
    )
    polisher = create_writer(name="W2 Okonjo", quote_cents=3_000_000)
    polish = create_engagement(
        ctx["project"]["id"],
        polisher["id"],
        engagement_type="POLISH",
        total_fee_cents=3_000_001,
        start_date="2027-01-10",
        end_date="2027-03-10",
    )

    resp = api.attach_engagement(polish["id"], EXEC_ALPHA)
    data = validate_success(resp, 200)

    assert data["status"] == "ATTACHED"
    assert data["milestone_count"] == 2

    commencement = milestone_of_type(polish["id"], "COMMENCEMENT")
    assert commencement["sequence_index"] == 0
    assert commencement["gross_amount_cents"] == 1_500_001
    assert commencement["status"] == "DUE"

    delivery = milestone_of_type(polish["id"], "POLISH_DELIVERY")
    assert delivery["sequence_index"] == 1
    assert delivery["gross_amount_cents"] == 1_500_000
    assert delivery["status"] == "SCHEDULED"

    assert fetch_writer(polisher["id"])["committed_fee_cents"] == 3_000_001
    project = fetch_project(ctx["project"]["id"])
    assert project["development_status"] == "POLISH"
    assert project["committed_writer_fee_cents"] == 13_000_004


def test_list_milestone_payments_returns_the_full_schedule_in_sequence_order(api):
    """PRD 2.3: "The single exception is the milestone-payment collection, which is
    ordered by `sequence_index` ascending so that a writer's payment ladder reads in
    the order it must be settled."
    PRD 3.7: "Each row also gets a `due_on` date, being the engagement's `start_date`
    advanced by a fixed offset in days chosen by milestone step: `COMMENCEMENT` is due
    on the start date itself, at zero days; `FIRST_DRAFT_DELIVERY` at 84 days — twelve
    weeks; `FIRST_DRAFT_ACCEPTANCE` at 98 days — fourteen weeks; `REWRITE_DELIVERY` at
    56 days — eight weeks; `POLISH_DELIVERY` at 28 days — four weeks; and
    `PRODUCTION_BONUS` at 120 days."

    Design: Corner/endpoints/list_milestone_payments_returns_full_schedule_ordered_by_sequence_index
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(genre="DRAMA", title="Schedule Read", attach=True)

    resp = api.list_milestone_payments(
        BA_APPROVER, {"engagement_id": ctx["engagement"]["id"]}
    )
    rows, meta = validate_paginated(resp)

    assert meta["total_count"] == 3
    assert [row["sequence_index"] for row in rows] == [0, 1, 2]
    assert rows[0]["milestone_type"] == "COMMENCEMENT"
    assert rows[0]["percentage_bps"] == 3000
    assert rows[0]["gross_amount_cents"] == 3_000_000
    assert rows[0]["status"] == "DUE"
    assert rows[0]["due_on"] == "2026-09-05"

    assert rows[1]["milestone_type"] == "FIRST_DRAFT_DELIVERY"
    assert rows[1]["percentage_bps"] == 4000
    assert rows[1]["gross_amount_cents"] == 4_000_003
    assert rows[1]["status"] == "SCHEDULED"
    assert rows[1]["due_on"] == "2026-11-28"

    assert rows[2]["milestone_type"] == "FIRST_DRAFT_ACCEPTANCE"
    assert rows[2]["percentage_bps"] == 3000
    assert rows[2]["gross_amount_cents"] == 3_000_000
    assert rows[2]["status"] == "SCHEDULED"
    assert rows[2]["due_on"] == "2026-12-12"


# ==========================================================================
# Fiscal gates on proposal and attachment
# ==========================================================================


def test_guild_minimum_violation_on_engagement_create(api):
    """PRD 3.7: "The guild minimum: when the writer's `guild_member` is true,
    `guild_minimum_cents` is the floor for that engagement type — seventy-five
    thousand dollars (7,500,000 cents) for an `ORIGINAL_DRAFT`, fifty thousand dollars
    (5,000,000 cents) for a `REWRITE`, twenty-five thousand dollars (2,500,000 cents)
    for a `POLISH`, and fifty thousand dollars (5,000,000 cents) for a
    `PRODUCTION_REWRITE` — and a `total_fee_cents` below that floor is refused with
    `ERR_GUILD_MINIMUM_VIOLATION`."
    PRD 3.7: "When the writer is not a guild member, `guild_minimum_cents` is 0 and
    the test cannot fail."

    Design: Corner/validations/guild_minimum_violation_on_engagement_create
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_clear_property_with_active_option(genre="DRAMA", title="Scale Floor")
    project = create_project(
        ctx["property"]["id"], ctx["option"]["id"], budget_cents=2_000_000_000
    )
    non_guild = create_writer(
        name="W2 Non Guild", guild_member=False, quote_cents=7_000_000
    )
    non_guild_engagement = create_engagement(
        project["id"], non_guild["id"], total_fee_cents=7_000_000
    )
    guild_writer = create_writer(name="W1 Guild", guild_member=True, quote_cents=7_000_000)

    resp = api.create_writer_engagement(
        {
            "project_id": project["id"],
            "writer_id": guild_writer["id"],
            "engagement_type": "ORIGINAL_DRAFT",
            "total_fee_cents": 7_000_000,
            "start_date": "2026-09-05",
            "end_date": "2027-01-05",
            "expected_project_version": project_version(project["id"]),
        },
        EXEC_ALPHA,
    )
    validate_error(resp, ApiErrorId.ERR_GUILD_MINIMUM_VIOLATION, 422)

    stored = fetch_engagement(non_guild_engagement["id"])
    assert stored["status"] == "PROPOSED"
    assert stored["guild_minimum_cents"] == 0

    _, meta = validate_paginated(
        api.list_writer_engagements(EXEC_ALPHA, {"writer_id": guild_writer["id"]})
    )
    assert meta["total_count"] == 0


def test_second_attach_breaching_the_aggregate_writer_cap_is_refused(api):
    """PRD 3.7: "The budget headroom test: the project's `committed_writer_fee_cents`
    plus the proposed `total_fee_cents` must be at or below the project's
    `writer_budget_cap_cents` — the bound is inclusive, so a proposal landing exactly
    on the cap is admissible — and a proposal that would breach it is refused with
    `ERR_BUDGET_EXCEEDED`."
    PRD 3.7: "The headroom test is applied again at attachment, because siblings may
    have attached in the meantime."
    PRD 3.7: "The project's `committed_writer_fee_cents` is the sum of
    `total_fee_cents` across its engagements in `ATTACHED`, `ACTIVE` or `COMPLETED`
    status; engagements still `PROPOSED` and engagements already `TERMINATED` consume
    no headroom."

    Design: Corner/validations/second_attach_exceeds_writer_budget_cap_aggregate_check
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_clear_property_with_active_option(
        genre="DRAMA", title="Tight Budget",
        option_overrides={
            "option_fee_cents": 1_000_000, "purchase_price_cents": 20_000_000,
        },
    )
    project = create_project(
        ctx["property"]["id"], ctx["option"]["id"], budget_cents=100_000_000
    )
    first_writer = create_writer(name="W1 Ferrante", quote_cents=8_000_000)
    second_writer = create_writer(name="W2 Okonjo", quote_cents=8_000_000)
    # Two different engagement types, so neither proposal supersedes the other.
    first = create_engagement(
        project["id"], first_writer["id"], engagement_type="ORIGINAL_DRAFT",
        total_fee_cents=8_000_000,
    )
    second = create_engagement(
        project["id"], second_writer["id"], engagement_type="REWRITE",
        total_fee_cents=8_000_000,
    )
    attach_engagement(first["id"])

    resp = api.attach_engagement(second["id"], EXEC_ALPHA)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, 409)

    stored_project = fetch_project(project["id"])
    assert stored_project["writer_budget_cap_cents"] == 12_000_000
    assert stored_project["committed_writer_fee_cents"] == 8_000_000
    assert fetch_engagement(first["id"])["status"] == "ATTACHED"
    assert fetch_engagement(second["id"])["status"] == "PROPOSED"
    assert fetch_writer(second_writer["id"])["committed_fee_cents"] == 0
    assert milestones_for_engagement(second["id"]) == []


# ==========================================================================
# Attachment gated by the linked option agreement
# ==========================================================================


def _project_on_a_merely_drafted_option():
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Unpapered")
    option = create_option(prop["id"])
    project = create_project(prop["id"], option["id"], budget_cents=2_000_000_000)
    writer = create_writer(name="W1 Ferrante")
    engagement = create_engagement(project["id"], writer["id"])
    return {
        "property": prop, "option": option, "project": project,
        "writer": writer, "engagement": engagement,
    }


def test_attach_is_refused_while_the_linked_option_is_only_drafted(api):
    """PRD 3.7: "The project's linked option agreement must be in `ACTIVE`, `EXTENDED`
    or `EXERCISED` status, or the attachment is refused with `ERR_OPTION_NOT_ACTIVE` —
    this is the practical consequence of allowing a project to be stood up against a
    merely drafted agreement."
    PRD 3.6: "Notably, the agreement need not be executed yet: a project may be stood
    up against a still-`DRAFTED` agreement, and the consequence is felt later, when no
    writer may be attached until that agreement has been executed."

    Design: Difficulty/cross_entity_state_dependency/engagement_attach_gated_by_option_agreement_status
    """
    ctx = _project_on_a_merely_drafted_option()

    resp = api.attach_engagement(ctx["engagement"]["id"], EXEC_ALPHA)
    validate_error(resp, ApiErrorId.ERR_OPTION_NOT_ACTIVE, 409)

    assert fetch_option(ctx["option"]["id"])["status"] == "DRAFTED"
    assert fetch_engagement(ctx["engagement"]["id"])["status"] == "PROPOSED"


def test_refused_attachment_generates_no_milestones_and_no_ledger_movement(api):
    """PRD 3.7: "Attachment generates the engagement's milestone payments from a
    template selected by `engagement_type`, sets `milestone_count` to the number of
    lines in that template, adds `total_fee_cents` to both the writer's
    `committed_fee_cents` and the project's `committed_writer_fee_cents`, increments
    the writer's `active_engagement_count` by one, and advances the project's
    development axis as Section 3.6 describes."

    Design: Difficulty/cross_entity_state_dependency/engagement_attach_gated_by_option_agreement_status
    """
    ctx = _project_on_a_merely_drafted_option()

    resp = api.attach_engagement(ctx["engagement"]["id"], EXEC_ALPHA)
    validate_error(resp, ApiErrorId.ERR_OPTION_NOT_ACTIVE, 409)

    assert milestones_for_engagement(ctx["engagement"]["id"]) == []
    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["committed_fee_cents"] == 0
    assert writer["active_engagement_count"] == 0
    assert fetch_project(ctx["project"]["id"])["development_status"] == "SETUP"


# ==========================================================================
# Writer concurrency
# ==========================================================================


def _writer_with_two_overlapping_attachments():
    set_clock("2026-09-01T00:00:00Z")
    writer = create_writer(name="W1 Ferrante")
    engagements = []
    projects = []
    windows = (
        ("2026-09-05", "2027-01-05"),
        ("2026-10-01", "2027-02-01"),
        ("2026-11-01", "2027-03-01"),
    )
    for index, (start_date, end_date) in enumerate(windows, start=1):
        base = setup_clear_property_with_active_option(
            genre="DRAMA", title=f"Slot {index}"
        )
        project = create_project(
            base["property"]["id"], base["option"]["id"], budget_cents=2_000_000_000
        )
        engagement = create_engagement(
            project["id"], writer["id"], total_fee_cents=10_000_000,
            start_date=start_date, end_date=end_date,
        )
        if index < 3:
            attach_engagement(engagement["id"])
        engagements.append(engagement)
        projects.append(project)
    return {"writer": writer, "engagements": engagements, "projects": projects}


def test_third_overlapping_attachment_is_refused_as_over_commitment(api):
    """PRD 3.7: "Count the writer's other engagements — excluding the candidate itself
    — whose status is `ATTACHED` or `ACTIVE` and whose window intersects the
    candidate's, where two closed windows intersect when the incumbent's `start_date`
    is on or before the candidate's `end_date` and the candidate's `start_date` is on
    or before the incumbent's `end_date`."
    PRD 3.7: "The attachment is admissible when that count is at most one; a second
    overlapping incumbent — which would make three concurrent engagements — is refused
    with `ERR_WRITER_OVERCOMMITTED`."

    Design: Difficulty/resource_temporal_overlap/writer_aggregate_concurrency_cap_rejects_third_overlapping_attach
    """
    ctx = _writer_with_two_overlapping_attachments()

    resp = api.attach_engagement(ctx["engagements"][2]["id"], EXEC_ALPHA)
    validate_error(resp, ApiErrorId.ERR_WRITER_OVERCOMMITTED, 409)

    assert fetch_engagement(ctx["engagements"][0]["id"])["status"] == "ATTACHED"
    assert fetch_engagement(ctx["engagements"][1]["id"])["status"] == "ATTACHED"
    assert fetch_engagement(ctx["engagements"][2]["id"])["status"] == "PROPOSED"


def test_two_concurrent_engagements_are_admitted_and_the_third_writes_nothing(api):
    """PRD 3.7: "Engagement windows are closed date intervals, and the studio allows a
    writer to carry at most two overlapping commitments at once."
    PRD 3.7: "Engagements in `PROPOSED`, `COMPLETED` or `TERMINATED` status occupy no
    capacity."

    Design: Difficulty/resource_temporal_overlap/writer_aggregate_concurrency_cap_rejects_third_overlapping_attach
    """
    ctx = _writer_with_two_overlapping_attachments()

    resp = api.attach_engagement(ctx["engagements"][2]["id"], EXEC_ALPHA)
    validate_error(resp, ApiErrorId.ERR_WRITER_OVERCOMMITTED, 409)

    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["active_engagement_count"] == 2
    assert writer["committed_fee_cents"] == 20_000_000

    assert milestones_for_engagement(ctx["engagements"][2]["id"]) == []
    third_project = fetch_project(ctx["projects"][2]["id"])
    assert third_project["development_status"] == "SETUP"
    assert third_project["committed_writer_fee_cents"] == 0


# ==========================================================================
# Approving and paying milestones
# ==========================================================================


def test_paying_the_commencement_milestone_activates_the_engagement(api):
    """PRD 3.7: "Payment stamps the logical clock into `paid_at`, moves
    `gross_amount_cents` out of the writer's `committed_fee_cents` and into their
    `paid_fee_cents`, and — when the paid row is the `sequence_index` 0 line — takes
    the engagement `ATTACHED → ACTIVE`."
    PRD 3.7: "Every generated row starts in `SCHEDULED` status, except that attachment
    immediately drives the `sequence_index` 0 row — always the `COMMENCEMENT` line —
    to `DUE`."

    Design: Corner/state_machines/paying_commencement_milestone_activates_engagement_and_moves_ledger
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(genre="DRAMA", title="Commencement", attach=True)
    commencement = milestone_of_type(ctx["engagement"]["id"], "COMMENCEMENT")
    approve_milestone(commencement["id"])

    resp = api.pay_milestone_payment(commencement["id"], BA_PAYER)
    data = validate_success(resp, 200)

    assert data["status"] == "PAID"
    assert data["gross_amount_cents"] == 3_000_000
    from test_helpers import assert_instant_equals

    assert_instant_equals(data["paid_at"], "2026-09-01T00:00:00Z", "paid_at")
    assert data["due_on"] == "2026-09-05"

    assert fetch_engagement(ctx["engagement"]["id"])["status"] == "ACTIVE"
    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["committed_fee_cents"] == 7_000_003
    assert writer["paid_fee_cents"] == 3_000_000
    assert writer["active_engagement_count"] == 1


def test_approving_a_later_milestone_first_returns_sequence_violation(api):
    """PRD 3.7: "Business affairs approves a milestone that is `DUE`, and the approval
    is admissible only when every milestone on the same engagement with a lower
    `sequence_index` is already in `PAID` or `VOIDED` status; otherwise the request is
    refused with `ERR_MILESTONE_SEQUENCE_VIOLATION`."
    PRD 3.7: "The matching milestone on the engagement moves `SCHEDULED → DUE`, which
    is admissible while the engagement is `ATTACHED` or `ACTIVE`, and the project's
    development axis advances: a `FIRST_DRAFT_DELIVERY` takes the project `WRITING →
    DRAFT_DELIVERED`, and a `POLISH_DELIVERY` takes it `POLISH → POLISH_DELIVERED`."

    Design: Corner/validations/approve_out_of_order_milestone_returns_sequence_violation
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(
        genre="DRAMA", title="Out Of Order", attach=True, deliver_first_draft=True
    )
    first_draft = milestone_of_type(ctx["engagement"]["id"], "FIRST_DRAFT_DELIVERY")
    commencement = milestone_of_type(ctx["engagement"]["id"], "COMMENCEMENT")

    resp = api.approve_milestone_payment(first_draft["id"], BA_APPROVER)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_SEQUENCE_VIOLATION, 409)

    stored = fetch_milestone(first_draft["id"])
    assert stored["status"] == "DUE"
    assert stored["sequence_index"] == 1
    assert stored["gross_amount_cents"] == 4_000_003
    assert fetch_milestone(commencement["id"])["status"] == "DUE"
    assert fetch_engagement(ctx["engagement"]["id"])["status"] == "ATTACHED"
    assert fetch_project(ctx["project"]["id"])["development_status"] == "DRAFT_DELIVERED"


def test_milestone_payer_cannot_be_the_approver(api):
    """PRD 2.9: "The paying business-affairs user's `X-User-ID` must differ from the
    `approved_by_user_id` recorded on the milestone payment."
    PRD 2.9: "Any of these three collisions is rejected with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."

    Design: Corner/rbac/milestone_payer_cannot_be_the_approver
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(genre="DRAMA", title="Two Signatures", attach=True)
    commencement = milestone_of_type(ctx["engagement"]["id"], "COMMENCEMENT")
    approve_milestone(commencement["id"], headers=BA_APPROVER)

    resp = api.pay_milestone_payment(commencement["id"], BA_APPROVER)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    stored = fetch_milestone(commencement["id"])
    assert stored["status"] == "APPROVED"
    assert stored["approved_by_user_id"] == "ba-approver-1"
    assert stored["paid_at"] is None
    assert fetch_engagement(ctx["engagement"]["id"])["status"] == "ATTACHED"
    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["committed_fee_cents"] == 10_000_003
    assert writer["paid_fee_cents"] == 0


def test_writer_cannot_deliver_another_writers_engagement(api):
    """PRD 2.1: "An entity-backed role that acts on a resource belonging to a
    different principal — a reader starting, editing or submitting coverage for
    another reader's assignment, a writer delivering against another writer's
    engagement, or a committee member attempting to vote in someone else's name — is
    rejected with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."
    PRD 3.7: "The engaged writer, and only that writer, records a delivery by naming
    the `milestone_type` delivered."

    Design: Corner/rbac/writer_cannot_deliver_another_writers_engagement
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(genre="DRAMA", title="Not My Draft", attach=True)
    intruder = create_writer(name="W2 Okonjo")

    resp = api.deliver_engagement(
        ctx["engagement"]["id"],
        {"milestone_type": "FIRST_DRAFT_DELIVERY"},
        make_writer_headers(intruder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    assert milestone_of_type(ctx["engagement"]["id"], "FIRST_DRAFT_DELIVERY")[
        "status"
    ] == "SCHEDULED"
    assert fetch_project(ctx["project"]["id"])["development_status"] == "WRITING"
    assert fetch_writer(intruder["id"])["active_engagement_count"] == 0


# ==========================================================================
# Termination: the compensating action for attachment
# ==========================================================================


def test_terminating_an_attached_engagement_voids_every_unpaid_milestone(api):
    """PRD 3.7: "Terminating an attached or active engagement unwinds everything:
    every milestone on it in `SCHEDULED`, `DUE` or `APPROVED` status becomes `VOIDED`,
    the writer's `committed_fee_cents` is reduced by the summed `gross_amount_cents`
    of exactly those voided rows, the writer's `active_engagement_count` decrements by
    one, and the project's `committed_writer_fee_cents` is reduced by the engagement's
    `total_fee_cents`, returning the headroom to the slate."

    Design: Difficulty/compensating_invariant/writer_committed_fee_ledger_conserved_across_attach_then_terminate
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(genre="DRAMA", title="Ledger Zero", attach=True)

    resp = api.terminate_engagement(
        ctx["engagement"]["id"], {"reason": "Creative differences."}, EXEC_ALPHA
    )
    data = validate_success(resp, 200)

    assert data["status"] == "TERMINATED"
    rows = milestones_for_engagement(ctx["engagement"]["id"])
    assert len(rows) == 3
    assert all(row["status"] == "VOIDED" for row in rows)


def test_attach_then_terminate_returns_the_committed_fee_ledger_to_zero(api):
    """PRD 2.10: "A writer's `committed_fee_cents` is the sum of `gross_amount_cents`
    across every milestone payment on that writer's engagements whose status is
    `SCHEDULED`, `DUE` or `APPROVED`; attaching an engagement and then terminating it
    with no payment in between must leave `committed_fee_cents` exactly where it
    started and `paid_fee_cents` unchanged."
    PRD 3.6: "The writer budget cap is a fixed 12 percent of the production budget:
    `writer_budget_cap_cents` is `budget_cents` multiplied by 1200 basis points,
    divided by ten thousand, floored to whole cents."

    Design: Difficulty/compensating_invariant/writer_committed_fee_ledger_conserved_across_attach_then_terminate
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(genre="DRAMA", title="Ledger Zero", attach=True)
    assert fetch_writer(ctx["writer"]["id"])["committed_fee_cents"] == 10_000_003

    validate_success(
        api.terminate_engagement(
            ctx["engagement"]["id"], {"reason": "Creative differences."}, EXEC_ALPHA
        )
    )

    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["committed_fee_cents"] == 0, "the money ledger is conserved"
    assert writer["paid_fee_cents"] == 0
    assert writer["active_engagement_count"] == 0

    project = fetch_project(ctx["project"]["id"])
    assert project["committed_writer_fee_cents"] == 0
    assert project["writer_budget_cap_cents"] == 240_000_000
