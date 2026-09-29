"""State-machine corners: initial states, refused edges, and cross-entity fan-out.

Every test in this module translates exactly one instance of the CORNER design
index, section ``state_machines``. The section covers three families:

* **Initial states.** ``every_child_aggregate_starts_in_its_declared_initial_state``
  creates seven child aggregates off one ``STRUCTURING`` deal and pins seven
  distinct initial labels.
* **Refused edges.** ``submit_structure_twice_rejected``,
  ``undertaking_activate_twice_rejected``, ``section_approve_twice_rejected``,
  ``official_statement_submit_for_review_from_in_review_rejected``,
  ``enhancement_commit_after_withdrawal_rejected``,
  ``respond_info_before_any_information_request_rejected``,
  ``rating_presentation_cancel_twice_rejected``,
  ``order_period_open_from_closed_rejected``, ``order_cancel_after_cancel_rejected``,
  ``cancelled_deal_locks_out_all_further_transitions`` and
  ``closing_document_execute_twice_rejected`` each pin the entity's own
  ``*_INVALID_STATE`` code, and each pins the fields a refused edge must leave
  untouched.
* **Valid edges and cross-entity fan-out.**
  ``submit_structure_moves_draft_to_structuring_and_fixes_par``,
  ``cancel_cascades_to_every_child_aggregate_in_one_call``,
  ``clock_advance_promotes_only_presentations_whose_end_has_passed``,
  ``activating_a_second_undertaking_supersedes_the_first``,
  ``creating_a_new_official_statement_supersedes_its_predecessor`` and
  ``opening_an_order_period_requires_the_deal_to_be_in_a_pricing_state`` pin the
  writes a successful hop makes on entities whose identifiers never appear in the
  request.

Setup is delegated to ``test_helpers.fixtures`` and every URL, enum literal,
error id, instant and bound comes from ``test_helpers``; nothing is re-derived
here.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLOSING_DOC_ALREADY_EXECUTED,
    ERR_DEAL_INVALID_STATE,
    ERR_ENHANCEMENT_INVALID_STATE,
    ERR_ORDER_INVALID_STATE,
    ERR_ORDER_PERIOD_INVALID_STATE,
    ERR_OS_INVALID_STATE,
    ERR_PRESENTATION_INVALID_STATE,
    ERR_RATING_ENGAGEMENT_INVALID_STATE,
    ERR_SECTION_INVALID_STATE,
    ERR_UNDERTAKING_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_money,
    assert_pagination,
    assert_par_identity,
    assert_timestamps_equal,
    assert_version_advanced,
    ids_of,
)
from test_helpers.constants import (
    CANONICAL_EXPECTED_PAR_USD,
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    CLOCK_EPOCH,
    plus_days,
    plus_hours,
)
from test_helpers.test_users import (
    BOND_COUNSEL_REVIEWER_ID,
    make_bond_counsel_headers,
)
from test_helpers.types import (
    CascadeReason,
    DealStatus,
    DisclosureClearance,
    DocType,
    EngagementStatus,
    EnhancementStatus,
    ExecutionStatus,
    MemberRole,
    OfficialStatementStatus,
    OrderPeriodStatus,
    OrderStatus,
    PresentationStatus,
    RatingBasis,
    ReviewStatus,
    SaleMethod,
    UndertakingStatus,
)

# --- The design index's worked instants, derived from the clock epoch ---------
# The order-book day: 2026-08-05, with a 13:00-17:00 institutional window and the
# clock parked at 14:00, strictly inside it.
BOOK_DAY = plus_days(CLOCK_EPOCH, 4)
PERIOD_OPENS_AT = plus_hours(BOOK_DAY, 13)
PERIOD_CLOSES_AT = plus_hours(BOOK_DAY, 17)
INSIDE_THE_WINDOW = plus_hours(BOOK_DAY, 14)

# The rating-presentation day: 2026-08-03, two slots 120 minutes apart, which
# clears the sixty-minute per-agency buffer of PRD section 3.5.
PRESENTATION_DAY = plus_days(CLOCK_EPOCH, 2)
FIRST_SLOT_STARTS_AT = plus_hours(PRESENTATION_DAY, 9)
FIRST_SLOT_ENDS_AT = plus_hours(PRESENTATION_DAY, 10)
SECOND_SLOT_STARTS_AT = plus_hours(PRESENTATION_DAY, 12)
SECOND_SLOT_ENDS_AT = plus_hours(PRESENTATION_DAY, 13)

# A presentation well beyond the order-book day, so it is still SCHEDULED when the
# cancellation cascade reaches it.
LATE_SLOT_STARTS_AT = plus_hours(plus_days(CLOCK_EPOCH, 9), 9)
LATE_SLOT_ENDS_AT = plus_hours(plus_days(CLOCK_EPOCH, 9), 10)

# --- The design index's worked reason strings --------------------------------
FIRST_CANCELLATION_REASON = "Analyst travel cancelled."
SECOND_CANCELLATION_REASON = "Duplicate cancellation."
WITHDRAWAL_REASON = "Provider downgraded before pricing."
DEAL_CANCELLATION_REASON = "Council rescinded the authorizing ordinance."
SECOND_DEAL_CANCELLATION_REASON = "Second cancellation attempt."
CASCADE_CANCELLATION_REASON = "Market disruption; the council withdrew the issue."
FIRST_SIGNATORY_NAME = "R. Vance, Managing Director"
SECOND_SIGNATORY_NAME = "Someone Else"

# A third `BondCounsel` identity, so the second approval attempt is not the first
# approver retrying and not the author self-approving (PRD sections 2.8, 3.4).
SECOND_REVIEWER_HEADERS = make_bond_counsel_headers("bc-second-reviewer-0003")


# ---------------------------------------------------------------------------
# Module-local readers
# ---------------------------------------------------------------------------
def _read_deal(ctx):
    return fx.read_deal(ctx.client, ctx.deal_id, ctx.compliance_headers)


def _read_tranche(ctx, tranche_id):
    return get_success_data(
        ctx.client.get_maturity_tranche(tranche_id, ctx.compliance_headers), 200
    )


def _read_statement(ctx, statement_id):
    return get_success_data(
        ctx.client.get_official_statement(statement_id, ctx.compliance_headers), 200
    )


def _read_section(ctx, section_id):
    return get_success_data(
        ctx.client.get_os_section(section_id, ctx.compliance_headers), 200
    )


def _read_engagement(ctx, engagement_id):
    return get_success_data(
        ctx.client.get_rating_engagement(engagement_id, ctx.compliance_headers), 200
    )


def _read_presentation(ctx, presentation_id):
    return get_success_data(
        ctx.client.get_presentation(presentation_id, ctx.compliance_headers), 200
    )


def _read_order(ctx, order_id):
    return get_success_data(ctx.client.get_order(order_id, ctx.compliance_headers), 200)


def _read_document(ctx, document_id):
    return get_success_data(
        ctx.client.get_closing_document(document_id, ctx.compliance_headers), 200
    )


def _read_undertaking(ctx, undertaking_id):
    """Undertakings have no individual read, so find the row in its deal listing."""
    rows, _ = validate_paginated(
        ctx.client.list_deal_undertakings(ctx.deal_id, ctx.compliance_headers)
    )
    matches = [row for row in rows if row["id"] == undertaking_id]
    assert matches, f"undertaking {undertaking_id!r} missing from its deal listing"
    return matches[0]


def _read_enhancement(ctx, enhancement_id):
    """Enhancements have no individual read either; use the deal listing."""
    rows, _ = validate_paginated(
        ctx.client.list_deal_credit_enhancements(ctx.deal_id, ctx.compliance_headers)
    )
    matches = [row for row in rows if row["id"] == enhancement_id]
    assert matches, f"enhancement {enhancement_id!r} missing from its deal listing"
    return matches[0]


def _read_member(ctx, member_id):
    rows, _ = validate_paginated(
        ctx.client.list_deal_syndicate_members(ctx.deal_id, ctx.compliance_headers)
    )
    matches = [row for row in rows if row["id"] == member_id]
    assert matches, f"syndicate member {member_id!r} missing from its deal listing"
    return matches[0]


# ---------------------------------------------------------------------------
# Module-local setup
# ---------------------------------------------------------------------------
def _seven_children_of_one_structuring_deal(client):
    """Create one of every child aggregate off a single STRUCTURING deal.

    The order matters only for the official statement, whose creation is
    version-guarded; ``fx.with_drafting_statement`` re-reads the deal for its
    ``version`` immediately beforehand.
    """
    ctx = fx.structuring_deal(client)
    ctx.enhancement = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.tranche_ids[0]], ctx.advisor_headers
    )
    ctx.undertaking = fx.draft_undertaking(client, ctx.deal_id, ctx.counsel_headers)
    ctx.engagement = fx.request_rating(client, ctx.deal_id, ctx.advisor_headers)
    ctx.presentation = fx.schedule_presentation(
        client,
        ctx.engagement["id"],
        ctx.advisor_headers,
        FIRST_SLOT_STARTS_AT,
        FIRST_SLOT_ENDS_AT,
    )
    ctx.period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(PERIOD_OPENS_AT, PERIOD_CLOSES_AT),
    )
    fx.with_drafting_statement(ctx)
    ctx.section = fx.add_section(
        client, ctx.statement_id, f.material_risk_section_payload()
    )
    return ctx


def _draft_deal_with_a_senior_manager(client):
    """A DRAFT deal whose only seat holds the whole underwriting liability.

    While the deal is DRAFT its ``par_amount_usd`` is still zero, so the seat's
    ``liability_par_usd`` has nothing to be computed from yet -- which is exactly
    what submitting the structure back-fills.
    """
    ctx = fx.draft_deal(client)
    ctx.senior_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
    )
    ctx.member_id = ctx.senior_member["id"]
    return ctx


# ---------------------------------------------------------------------------
# state_machines / every_child_aggregate_starts_in_its_declared_initial_state
# ---------------------------------------------------------------------------
def test_every_child_aggregate_starts_in_its_own_declared_initial_state(client):
    """PRD 3.4: "The new statement begins with `status` `DRAFTING`, `draft_round` 1,
    `mandatory_sections_approved` false, and `posted_preliminary_at`,
    `posted_final_at`, and `revision_reason` all null."

    Design: Corner/state_machines/every_child_aggregate_starts_in_its_declared_initial_state
    """
    ctx = _seven_children_of_one_structuring_deal(client)

    # PRD 3.3: "A new proposal is created with `status` `PROPOSED`, with
    # `insured_debt_service_usd`, `premium_usd`, and `withdrawal_reason` all null."
    assert ctx.enhancement["status"] == EnhancementStatus.PROPOSED

    # PRD 3.4: "A new undertaking has `status` `DRAFT`."
    assert ctx.undertaking["status"] == UndertakingStatus.DRAFT

    # PRD 3.5: "A new engagement starts with `status` `REQUESTED`,
    # `assigned_analyst_user_id` null, `info_request_count` at zero, and
    # `latest_information_request`, `assigned_rating`, and `outlook` all null."
    assert ctx.engagement["status"] == EngagementStatus.REQUESTED
    assert ctx.engagement["info_request_count"] == 0
    assert ctx.engagement["assigned_analyst_user_id"] is None

    # PRD 3.5: "A new presentation begins with `status` `SCHEDULED` and
    # `cancellation_reason` null"
    assert ctx.presentation["status"] == PresentationStatus.SCHEDULED
    assert ctx.presentation["cancellation_reason"] is None

    # PRD 3.7: "A new period has `status` `SCHEDULED`, `allotment_run_count` zero,
    # `orders_received_count` and `allotted_order_count` zero, and `reopen_reason` null."
    assert ctx.period["status"] == OrderPeriodStatus.SCHEDULED
    assert ctx.period["allotment_run_count"] == 0
    assert ctx.period["orders_received_count"] == 0
    assert ctx.period["allotted_order_count"] == 0

    assert ctx.statement["status"] == OfficialStatementStatus.DRAFTING
    assert ctx.statement["draft_round"] == 1
    assert ctx.statement["mandatory_sections_approved"] is False

    # PRD 3.4: "The server sets `review_status` to `DRAFT`, records
    # `authored_by_user_id` from `X-User-ID`, leaves `approved_by_user_id` null"
    assert ctx.section["review_status"] == ReviewStatus.DRAFT
    assert ctx.section["approved_by_user_id"] is None


# ---------------------------------------------------------------------------
# state_machines / submit_structure_moves_draft_to_structuring_and_fixes_par
# ---------------------------------------------------------------------------
def test_submit_structure_freezes_the_par_amount_and_initialises_every_tranche(client):
    """PRD 3.2: "`Deal.par_amount_usd` is set to the sum of the maturities'
    `principal_amount_usd`. Every maturity of the deal has its `par_unsold_usd`
    initialised to its own `principal_amount_usd` and its `par_allotted_usd`
    initialised to zero, so the par identity holds from the outset."

    Design: Corner/state_machines/submit_structure_moves_draft_to_structuring_and_fixes_par
    """
    ctx = _draft_deal_with_a_senior_manager(client)
    assert _read_deal(ctx)["status"] == DealStatus.DRAFT

    deal = validate_success(
        client.submit_structure(ctx.deal_id, None, ctx.advisor_headers), 200
    )

    assert deal["status"] == DealStatus.STRUCTURING
    assert_money(deal["par_amount_usd"], CANONICAL_EXPECTED_PAR_USD, "par_amount_usd")
    # Freezing the schedule is not the branching decision: PRD 3.2 leaves
    # "its `sale_method` and its `gross_spread_basis` are both `UNDETERMINED`" alone.
    assert deal["sale_method"] == SaleMethod.UNDETERMINED

    tranches = fx.list_tranches(client, ctx.deal_id, ctx.compliance_headers)
    assert len(tranches) == 2
    for tranche in tranches:
        assert_money(tranche["par_allotted_usd"], 0, "par_allotted_usd")
        assert_money(
            tranche["par_unsold_usd"], CANONICAL_TRANCHE_PRINCIPAL_USD, "par_unsold_usd"
        )
        assert_par_identity(tranche)


def test_submit_structure_back_fills_the_senior_managers_liability_par(client):
    """PRD 3.2: "And every syndicate member of the deal whose `status` is `ACTIVE`
    has its `liability_par_usd` set to its `liability_pct` divided by one hundred,
    multiplied by the deal's newly known `par_amount_usd`, rounded half up to two
    decimal places."

    Design: Corner/state_machines/submit_structure_moves_draft_to_structuring_and_fixes_par
    """
    ctx = _draft_deal_with_a_senior_manager(client)
    # PRD 3.6: "otherwise it starts at zero and is filled in when the structure is
    # submitted."
    assert_money(ctx.senior_member["liability_par_usd"], 0, "liability_par_usd")

    validate_success(client.submit_structure(ctx.deal_id, None, ctx.advisor_headers), 200)

    member = _read_member(ctx, ctx.member_id)
    assert_money(
        member["liability_par_usd"], CANONICAL_EXPECTED_PAR_USD, "liability_par_usd"
    )
    # PRD 3.6: "A new seat has `status` `ACTIVE` and `takedown_credit_usd` zero"
    assert_money(member["takedown_credit_usd"], 0, "takedown_credit_usd")


# ---------------------------------------------------------------------------
# state_machines / submit_structure_twice_rejected
# ---------------------------------------------------------------------------
def test_a_second_submit_structure_is_refused_and_leaves_the_par_amount_alone(
    client, structuring_deal
):
    """PRD 3.2: "Submitting the structure is the `MunicipalAdvisor`'s act of freezing
    the schedule, and it advances the deal from `DRAFT` to `STRUCTURING`."

    Design: Corner/state_machines/submit_structure_twice_rejected
    """
    ctx = structuring_deal
    assert ctx.deal["status"] == DealStatus.STRUCTURING

    validate_error(
        client.submit_structure(ctx.deal_id, None, ctx.advisor_headers),
        ERR_DEAL_INVALID_STATE,
    )

    deal = _read_deal(ctx)
    assert deal["status"] == DealStatus.STRUCTURING
    assert_money(deal["par_amount_usd"], CANONICAL_EXPECTED_PAR_USD, "par_amount_usd")


# ---------------------------------------------------------------------------
# state_machines / undertaking_activate_twice_rejected
# ---------------------------------------------------------------------------
def test_activating_an_already_active_undertaking_is_refused(client, draft_deal):
    """PRD 3.4: "Activating one is an `IssuerOfficial` act: the undertaking must be in
    `DRAFT`, or the request is refused with `ERR_UNDERTAKING_INVALID_STATE`, and the
    deal must not be `CLOSED` or `CANCELLED`, or it is refused with
    `ERR_DEAL_INVALID_STATE`."

    Design: Corner/state_machines/undertaking_activate_twice_rejected
    """
    ctx = fx.with_active_undertaking(draft_deal)
    assert ctx.undertaking["status"] == UndertakingStatus.ACTIVE

    validate_error(
        client.activate_undertaking(ctx.undertaking_id, None, ctx.issuer_headers),
        ERR_UNDERTAKING_INVALID_STATE,
    )

    # Re-activating itself must not be mistaken for the supersession cascade that
    # activating a *different* undertaking runs.
    undertaking = _read_undertaking(ctx, ctx.undertaking_id)
    assert undertaking["status"] == UndertakingStatus.ACTIVE


# ---------------------------------------------------------------------------
# state_machines / section_approve_twice_rejected
# ---------------------------------------------------------------------------
def test_approving_an_already_approved_section_keeps_the_first_approver(
    client, draft_deal
):
    """PRD 3.4: "The section's `review_status` must be either `DRAFT` or
    `NEEDS_REVISION`; a section already `APPROVED` cannot be approved again and
    reports `ERR_SECTION_INVALID_STATE`."

    Design: Corner/state_machines/section_approve_twice_rejected
    """
    ctx = fx.with_drafting_statement(draft_deal)
    section = fx.add_section(client, ctx.statement_id, f.material_risk_section_payload())
    approved = fx.approve_section(client, section["id"])
    assert approved["review_status"] == ReviewStatus.APPROVED
    assert approved["approved_by_user_id"] == BOND_COUNSEL_REVIEWER_ID

    validate_error(
        client.approve_section(section["id"], None, SECOND_REVIEWER_HEADERS),
        ERR_SECTION_INVALID_STATE,
    )

    # PRD 3.4: "each record `approved_by_user_id` from `X-User-ID`" -- but only on a
    # hop that actually happens, so the audit trail keeps the first approver.
    stored = _read_section(ctx, section["id"])
    assert stored["review_status"] == ReviewStatus.APPROVED
    assert stored["approved_by_user_id"] == BOND_COUNSEL_REVIEWER_ID


# ---------------------------------------------------------------------------
# state_machines / official_statement_submit_for_review_from_in_review_rejected
# ---------------------------------------------------------------------------
def test_submitting_a_statement_already_in_review_is_refused_without_a_round(
    client, draft_deal
):
    """PRD 3.4: "The review loop runs `DRAFTING` → `IN_REVIEW` → `REVISION_REQUESTED`
    → `DRAFTING`, and it is bounded."

    Design: Corner/state_machines/official_statement_submit_for_review_from_in_review_rejected
    """
    ctx = fx.with_drafting_statement(draft_deal)
    fx.add_section(client, ctx.statement_id, f.material_risk_section_payload())
    statement = fx.submit_for_review(client, ctx.statement_id)
    assert statement["status"] == OfficialStatementStatus.IN_REVIEW

    validate_error(
        client.submit_for_review(ctx.statement_id, None, ctx.counsel_headers),
        ERR_OS_INVALID_STATE,
    )

    # The refusal is the state check, not the revision cap: no round was consumed.
    stored = _read_statement(ctx, ctx.statement_id)
    assert stored["status"] == OfficialStatementStatus.IN_REVIEW
    assert stored["draft_round"] == 1


# ---------------------------------------------------------------------------
# state_machines / enhancement_commit_after_withdrawal_rejected
# ---------------------------------------------------------------------------
def test_committing_a_withdrawn_enhancement_is_refused_on_its_own_state(
    client, structuring_deal
):
    """PRD 3.3: "Committing is the `IssuerOfficial`'s decision to buy the enhancement,
    and it moves the proposal from `PROPOSED` to `COMMITTED`. A proposal not in
    `PROPOSED` is refused with `ERR_ENHANCEMENT_INVALID_STATE`."

    Design: Corner/state_machines/enhancement_commit_after_withdrawal_rejected
    """
    ctx = structuring_deal
    enhancement = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.tranche_ids[0]], ctx.advisor_headers
    )
    fx.commit_enhancement(client, enhancement["id"], ctx.issuer_headers)
    fx.withdraw_enhancement(
        client, enhancement["id"], ctx.issuer_headers, WITHDRAWAL_REASON
    )

    validate_error(
        client.commit_credit_enhancement(enhancement["id"], None, ctx.issuer_headers),
        ERR_ENHANCEMENT_INVALID_STATE,
    )

    stored = _read_enhancement(ctx, enhancement["id"])
    assert stored["status"] == EnhancementStatus.WITHDRAWN
    assert stored["withdrawal_reason"] == WITHDRAWAL_REASON

    # The withdrawal cascade's reversal stands: the refused commit re-insures nothing.
    tranche = _read_tranche(ctx, ctx.tranche_ids[0])
    assert tranche["is_insured"] is False
    assert tranche["rating_basis"] == RatingBasis.UNDERLYING
    assert_money(
        _read_deal(ctx)["credit_enhancement_premium_usd"],
        0,
        "credit_enhancement_premium_usd",
    )


# ---------------------------------------------------------------------------
# state_machines / respond_info_before_any_information_request_rejected
# ---------------------------------------------------------------------------
def test_responding_to_information_never_requested_is_refused(client, draft_deal):
    """PRD 3.5: "The deal team answers through a `MunicipalAdvisor` who supplies a
    `response_summary`; that returns the engagement from `INFO_REQUESTED` to
    `UNDER_REVIEW`, and an engagement not in `INFO_REQUESTED` reports
    `ERR_RATING_ENGAGEMENT_INVALID_STATE`."

    Design: Corner/state_machines/respond_info_before_any_information_request_rejected
    """
    ctx = draft_deal
    engagement = fx.request_rating(client, ctx.deal_id, ctx.advisor_headers)
    assert engagement["status"] == EngagementStatus.REQUESTED

    validate_error(
        client.respond_info(
            engagement["id"], f.info_response_payload(), ctx.advisor_headers
        ),
        ERR_RATING_ENGAGEMENT_INVALID_STATE,
    )

    stored = _read_engagement(ctx, engagement["id"])
    assert stored["status"] == EngagementStatus.REQUESTED
    assert stored["info_request_count"] == 0
    assert stored["latest_information_request"] is None


# ---------------------------------------------------------------------------
# state_machines / rating_presentation_cancel_twice_rejected
# ---------------------------------------------------------------------------
def test_cancelling_an_already_cancelled_presentation_keeps_the_first_reason(
    client, draft_deal
):
    """PRD 3.5: "The second route is a deliberate cancellation by a `MunicipalAdvisor`
    or an `Underwriter`, which supplies a `cancellation_reason`, moves a `SCHEDULED`
    presentation to the terminal `CANCELLED`, and increments its `version`; a
    presentation not in `SCHEDULED` reports `ERR_PRESENTATION_INVALID_STATE`."

    Design: Corner/state_machines/rating_presentation_cancel_twice_rejected
    """
    ctx = draft_deal
    engagement = fx.request_rating(client, ctx.deal_id, ctx.advisor_headers)
    presentation = fx.schedule_presentation(
        client,
        engagement["id"],
        ctx.advisor_headers,
        FIRST_SLOT_STARTS_AT,
        FIRST_SLOT_ENDS_AT,
    )
    fx.cancel_presentation(
        client, presentation["id"], ctx.advisor_headers, FIRST_CANCELLATION_REASON
    )

    validate_error(
        client.cancel_presentation(
            presentation["id"],
            f.cancellation_payload(SECOND_CANCELLATION_REASON),
            ctx.advisor_headers,
        ),
        ERR_PRESENTATION_INVALID_STATE,
    )

    stored = _read_presentation(ctx, presentation["id"])
    assert stored["status"] == PresentationStatus.CANCELLED
    assert stored["cancellation_reason"] == FIRST_CANCELLATION_REASON


# ---------------------------------------------------------------------------
# state_machines / order_period_open_from_closed_rejected
# ---------------------------------------------------------------------------
def _period_closed_inside_its_own_window(ctx):
    """Schedule the 13:00-17:00 book, park the clock at 14:00, open it and close it.

    Closing with an empty book still counts as a run, and the clock never leaves the
    window, so nothing but the CLOSED -> OPEN edge itself can explain a refusal.
    """
    period = fx.schedule_order_period(
        ctx.client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(PERIOD_OPENS_AT, PERIOD_CLOSES_AT),
    )
    ctx.period_id = period["id"]
    fx.set_clock(ctx.client, INSIDE_THE_WINDOW)
    fx.open_period(ctx.client, ctx.period_id, ctx.underwriter_headers)
    ctx.period = fx.close_period(ctx.client, ctx.period_id, ctx.underwriter_headers)
    return ctx


def test_opening_a_closed_period_is_refused_even_inside_its_window(
    client, competitive_deal
):
    """PRD 3.7: "Opening the book moves a period from `SCHEDULED` to `OPEN` at the hand
    of an `Underwriter` and carries three preconditions."

    Design: Corner/state_machines/order_period_open_from_closed_rejected
    """
    ctx = _period_closed_inside_its_own_window(competitive_deal)
    assert ctx.period["status"] == OrderPeriodStatus.CLOSED

    validate_error(
        client.open_order_period(ctx.period_id, None, ctx.underwriter_headers),
        ERR_ORDER_PERIOD_INVALID_STATE,
    )

    period = fx.read_period(client, ctx.period_id, ctx.compliance_headers)
    assert period["status"] == OrderPeriodStatus.CLOSED
    # PRD 3.7: "closing adds one to the period's `allotment_run_count`" -- and the
    # refused open is not the ComplianceOfficer's reopen in disguise.
    assert period["allotment_run_count"] == 1
    assert period["reopen_reason"] is None


# ---------------------------------------------------------------------------
# state_machines / order_cancel_after_cancel_rejected
# ---------------------------------------------------------------------------
def test_cancelling_an_already_cancelled_order_is_refused(client, negotiated_deal):
    """PRD 3.7: "An `Underwriter` may withdraw a `PENDING` order while the book is
    still `OPEN` and the clock is still before `closes_at` by supplying a
    `cancellation_reason`; the order becomes the terminal `CANCELLED` with
    `par_allotted_usd` zero, `orders_received_count` is recomputed, and both the
    order's and the period's `version` increment."

    Design: Corner/state_machines/order_cancel_after_cancel_rejected
    """
    ctx = negotiated_deal
    period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(PERIOD_OPENS_AT, PERIOD_CLOSES_AT),
    )
    ctx.period_id = period["id"]
    fx.set_clock(client, INSIDE_THE_WINDOW)
    fx.open_period(client, ctx.period_id, ctx.underwriter_headers)
    order = fx.place_order(
        client,
        ctx.period_id,
        ctx.tranche_ids[0],
        ctx.member_ids[0],
        ctx.underwriter_headers,
    )
    fx.cancel_order(client, order["id"], ctx.underwriter_headers)

    validate_error(
        client.cancel_order(
            order["id"],
            f.cancellation_payload(SECOND_CANCELLATION_REASON),
            ctx.underwriter_headers,
        ),
        ERR_ORDER_INVALID_STATE,
    )

    stored = _read_order(ctx, order["id"])
    assert stored["status"] == OrderStatus.CANCELLED
    assert_money(stored["par_allotted_usd"], 0, "par_allotted_usd")

    # The book itself is untouched by the refusal, and the cancelled order stays
    # excluded from the recomputed counter.
    reread = fx.read_period(client, ctx.period_id, ctx.compliance_headers)
    assert reread["status"] == OrderPeriodStatus.OPEN
    assert reread["orders_received_count"] == 0


# ---------------------------------------------------------------------------
# state_machines / cancelled_deal_locks_out_all_further_transitions
# ---------------------------------------------------------------------------
def _cancelled_deal_with_a_draft_undertaking(client):
    """A DRAFT deal carrying a DRAFT undertaking, then cancelled."""
    ctx = fx.draft_deal(client)
    ctx.undertaking = fx.draft_undertaking(client, ctx.deal_id, ctx.counsel_headers)
    ctx.undertaking_id = ctx.undertaking["id"]
    ctx.deal = fx.cancel_deal(
        client, ctx.deal_id, ctx.issuer_headers, DEAL_CANCELLATION_REASON
    )
    assert ctx.deal["status"] == DealStatus.CANCELLED
    return ctx


def _assert_the_deal_is_untouched_by_the_refusal(ctx):
    """CANCELLED is terminal, so a refused edge writes nothing at all."""
    deal = _read_deal(ctx)
    assert deal["status"] == DealStatus.CANCELLED
    assert deal["sale_method"] == SaleMethod.UNDETERMINED
    assert deal["cancellation_reason"] == DEAL_CANCELLATION_REASON
    return deal


def test_a_cancelled_deal_refuses_submit_structure(client):
    """PRD 3.9: "A deal already in `CLOSED` or `CANCELLED` is refused with
    `ERR_DEAL_INVALID_STATE`; note that an `AWARDED` deal is likewise not cancellable,
    since the bonds have been awarded to their purchasers."

    Design: Corner/state_machines/cancelled_deal_locks_out_all_further_transitions
    """
    ctx = _cancelled_deal_with_a_draft_undertaking(client)

    validate_error(
        client.submit_structure(ctx.deal_id, None, ctx.advisor_headers),
        ERR_DEAL_INVALID_STATE,
    )

    _assert_the_deal_is_untouched_by_the_refusal(ctx)


def test_a_cancelled_deal_refuses_the_sale_method_fork(client):
    """PRD 3.6: "Designating the sale method is the branching decision of the whole
    transaction and is taken by a `MunicipalAdvisor` or an `IssuerOfficial` on a deal
    in `STRUCTURING`."

    Design: Corner/state_machines/cancelled_deal_locks_out_all_further_transitions
    """
    ctx = _cancelled_deal_with_a_draft_undertaking(client)

    validate_error(
        client.designate_sale_method(
            ctx.deal_id,
            f.sale_method_payload(SaleMethod.COMPETITIVE),
            ctx.advisor_headers,
        ),
        ERR_DEAL_INVALID_STATE,
    )

    # The state check outranks the re-designation conflict of PRD 3.6, and the fork
    # is never taken.
    _assert_the_deal_is_untouched_by_the_refusal(ctx)


def test_a_cancelled_deal_refuses_undertaking_activation(client):
    """PRD 3.4: "Activating one is an `IssuerOfficial` act: the undertaking must be in
    `DRAFT`, or the request is refused with `ERR_UNDERTAKING_INVALID_STATE`, and the
    deal must not be `CLOSED` or `CANCELLED`, or it is refused with
    `ERR_DEAL_INVALID_STATE`."

    Design: Corner/state_machines/cancelled_deal_locks_out_all_further_transitions
    """
    ctx = _cancelled_deal_with_a_draft_undertaking(client)
    assert ctx.undertaking["status"] == UndertakingStatus.DRAFT

    validate_error(
        client.activate_undertaking(ctx.undertaking_id, None, ctx.issuer_headers),
        ERR_DEAL_INVALID_STATE,
    )

    _assert_the_deal_is_untouched_by_the_refusal(ctx)
    assert _read_undertaking(ctx, ctx.undertaking_id)["status"] == UndertakingStatus.DRAFT


def test_a_cancelled_deal_refuses_a_second_cancellation(client):
    """PRD 3.9: "Cancellation is taken by an `IssuerOfficial` supplying a
    `cancellation_reason`, and it is available from `DRAFT`, `STRUCTURING`,
    `PRICING_COMPETITIVE`, `PRICING_NEGOTIATED`, and `PRICED`."

    Design: Corner/state_machines/cancelled_deal_locks_out_all_further_transitions
    """
    ctx = _cancelled_deal_with_a_draft_undertaking(client)

    validate_error(
        client.cancel_deal(
            ctx.deal_id,
            f.cancellation_payload(SECOND_DEAL_CANCELLATION_REASON),
            ctx.issuer_headers,
        ),
        ERR_DEAL_INVALID_STATE,
    )

    # The stored reason is the first one; a refused cancel never overwrites it.
    _assert_the_deal_is_untouched_by_the_refusal(ctx)


# ---------------------------------------------------------------------------
# state_machines / closing_document_execute_twice_rejected
# ---------------------------------------------------------------------------
def test_executing_an_executed_closing_document_keeps_the_first_signature(
    client, awarded_competitive_deal
):
    """PRD 3.9: "The document must have `execution_status` `PENDING`, or the request is
    refused with `ERR_CLOSING_DOC_ALREADY_EXECUTED`."

    Design: Corner/state_machines/closing_document_execute_twice_rejected
    """
    ctx = awarded_competitive_deal
    # The ISSUE_PRICE_CERTIFICATE's only gates are the signatory role and the deal
    # being AWARDED, so no FINAL_POSTED or handoff prerequisite can mask the state
    # check that this instance is about.
    fx.set_clock(client, INSIDE_THE_WINDOW)
    document = fx.documents_by_type(client, ctx.deal_id, ctx.compliance_headers)[
        DocType.ISSUE_PRICE_CERTIFICATE
    ]
    executed = fx.execute_document(
        client, document["id"], ctx.underwriter_headers, FIRST_SIGNATORY_NAME
    )
    assert executed["execution_status"] == ExecutionStatus.EXECUTED

    validate_error(
        client.execute_closing_document(
            document["id"],
            f.execute_payload(SECOND_SIGNATORY_NAME),
            ctx.underwriter_headers,
        ),
        ERR_CLOSING_DOC_ALREADY_EXECUTED,
    )

    stored = _read_document(ctx, document["id"])
    assert stored["execution_status"] == ExecutionStatus.EXECUTED
    assert stored["signatory_name"] == FIRST_SIGNATORY_NAME
    # PRD 3.9: "`executed_at` set to the current logical clock instant" -- the instant
    # of the first execution, not of the refused second one.
    assert_timestamps_equal(stored["executed_at"], INSIDE_THE_WINDOW, "executed_at")


# ---------------------------------------------------------------------------
# state_machines / cancel_cascades_to_every_child_aggregate_in_one_call
# ---------------------------------------------------------------------------
def _pricing_negotiated_deal_with_one_of_every_child(ctx):
    """One live child of every kind the cancellation cascade has to reach.

    The presentation sits days beyond the order-book window, so the clock move that
    lets the book open cannot promote it to HELD before the cascade arrives.
    """
    client = ctx.client
    ctx.enhancement = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.tranche_ids[0]], ctx.advisor_headers
    )
    ctx.engagement = fx.request_rating(client, ctx.deal_id, ctx.advisor_headers)
    fx.acknowledge_engagement(client, ctx.engagement["id"])
    ctx.presentation = fx.schedule_presentation(
        client,
        ctx.engagement["id"],
        ctx.advisor_headers,
        LATE_SLOT_STARTS_AT,
        LATE_SLOT_ENDS_AT,
    )
    fx.with_drafting_statement(ctx)
    period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(PERIOD_OPENS_AT, PERIOD_CLOSES_AT),
    )
    ctx.period_id = period["id"]
    fx.set_clock(client, INSIDE_THE_WINDOW)
    fx.open_period(client, ctx.period_id, ctx.underwriter_headers)
    ctx.order = fx.place_order(
        client,
        ctx.period_id,
        ctx.tranche_ids[0],
        ctx.member_ids[0],
        ctx.underwriter_headers,
    )
    return ctx


def test_cancelling_the_deal_withdraws_the_disclosure_and_rating_children(
    client, negotiated_deal
):
    """PRD 3.4: "A statement in `DRAFTING`, `IN_REVIEW`, `REVISION_REQUESTED`, or
    `PRELIMINARY_POSTED` becomes the terminal `WITHDRAWN` when the owning deal is
    cancelled, and in that case `Deal.disclosure_clearance` is recomputed to `BLOCKED`
    and the statement's `version` increments."

    Design: Corner/state_machines/cancel_cascades_to_every_child_aggregate_in_one_call
    """
    ctx = _pricing_negotiated_deal_with_one_of_every_child(negotiated_deal)

    deal = validate_success(
        client.cancel_deal(
            ctx.deal_id,
            f.cancellation_payload(CASCADE_CANCELLATION_REASON),
            ctx.issuer_headers,
        ),
        200,
    )
    assert deal["status"] == DealStatus.CANCELLED
    assert deal["cancellation_reason"] == CASCADE_CANCELLATION_REASON

    assert (
        _read_statement(ctx, ctx.statement_id)["status"]
        == OfficialStatementStatus.WITHDRAWN
    )
    assert deal["disclosure_clearance"] == DisclosureClearance.BLOCKED

    # PRD 3.9: "Every rating engagement of the deal in `REQUESTED`, `UNDER_REVIEW`, or
    # `INFO_REQUESTED` becomes `WITHDRAWN`, and every rating presentation with `status`
    # `SCHEDULED` on those engagements becomes `CANCELLED` with `cancellation_reason`
    # recorded as `DEAL_CANCELLED`."
    assert (
        _read_engagement(ctx, ctx.engagement["id"])["status"]
        == EngagementStatus.WITHDRAWN
    )
    presentation = _read_presentation(ctx, ctx.presentation["id"])
    assert presentation["status"] == PresentationStatus.CANCELLED
    assert presentation["cancellation_reason"] == CascadeReason.DEAL_CANCELLED

    # PRD 3.9: "Every credit enhancement of the deal with `status` `PROPOSED` becomes
    # `DECLINED`, and one with `status` `COMMITTED` becomes `WITHDRAWN` with
    # `withdrawal_reason` recorded as `DEAL_CANCELLED`." This one was only PROPOSED.
    assert (
        _read_enhancement(ctx, ctx.enhancement["id"])["status"]
        == EnhancementStatus.DECLINED
    )


def test_cancelling_the_deal_unwinds_the_order_book_and_restores_tranche_par(
    client, negotiated_deal
):
    """PRD 3.9: "Every order of the deal in `PENDING`, `ALLOTTED`,
    `PARTIALLY_ALLOTTED`, or `UNFILLED` becomes `CANCELLED` with `par_allotted_usd` set
    to zero and `cancellation_reason` recorded as `DEAL_CANCELLED`."

    Design: Corner/state_machines/cancel_cascades_to_every_child_aggregate_in_one_call
    """
    ctx = _pricing_negotiated_deal_with_one_of_every_child(negotiated_deal)

    deal = validate_success(
        client.cancel_deal(
            ctx.deal_id,
            f.cancellation_payload(CASCADE_CANCELLATION_REASON),
            ctx.issuer_headers,
        ),
        200,
    )

    order = _read_order(ctx, ctx.order["id"])
    assert order["status"] == OrderStatus.CANCELLED
    assert_money(order["par_allotted_usd"], 0, "par_allotted_usd")
    assert order["cancellation_reason"] == CascadeReason.DEAL_CANCELLED

    # PRD 3.9: "Every order period of the deal in `SCHEDULED`, `OPEN`, or `CLOSED`
    # becomes `CANCELLED`."
    period = fx.read_period(client, ctx.period_id, ctx.compliance_headers)
    assert period["status"] == OrderPeriodStatus.CANCELLED

    # PRD 3.9: "Every maturity tranche of the deal recomputes `par_allotted_usd` to
    # zero and `par_unsold_usd` to its `principal_amount_usd`, and
    # `Deal.par_allotted_total_usd` becomes zero"
    tranches = fx.list_tranches(client, ctx.deal_id, ctx.compliance_headers)
    for tranche in tranches:
        assert_money(tranche["par_allotted_usd"], 0, "par_allotted_usd")
        assert_money(
            tranche["par_unsold_usd"], CANONICAL_TRANCHE_PRINCIPAL_USD, "par_unsold_usd"
        )
        assert_par_identity(tranche)
    assert_money(deal["par_allotted_total_usd"], 0, "par_allotted_total_usd")


# ---------------------------------------------------------------------------
# state_machines / clock_advance_promotes_only_presentations_whose_end_has_passed
# ---------------------------------------------------------------------------
def _two_slots_on_one_agency_day(ctx):
    """Two Moody's slots 120 minutes apart, which clears the sixty-minute buffer."""
    ctx.engagement = fx.request_rating(ctx.client, ctx.deal_id, ctx.advisor_headers)
    ctx.first_slot = fx.schedule_presentation(
        ctx.client,
        ctx.engagement["id"],
        ctx.advisor_headers,
        FIRST_SLOT_STARTS_AT,
        FIRST_SLOT_ENDS_AT,
    )
    ctx.second_slot = fx.schedule_presentation(
        ctx.client,
        ctx.engagement["id"],
        ctx.advisor_headers,
        SECOND_SLOT_STARTS_AT,
        SECOND_SLOT_ENDS_AT,
    )
    return ctx


def test_a_clock_advance_to_exactly_ends_at_promotes_only_the_slot_that_has_ended(
    client, draft_deal
):
    """PRD 3.5: "The ordinary route is the logical clock: whenever the clock is set to
    an instant at or after a `SCHEDULED` presentation's `ends_at`, that presentation is
    promoted to the terminal `HELD` and its `version` increments, and where a single
    clock advance sweeps past several presentations they are promoted in ascending
    order of `ends_at`, ties broken by ascending `created_at`."

    Design: Corner/state_machines/clock_advance_promotes_only_presentations_whose_end_has_passed
    """
    ctx = _two_slots_on_one_agency_day(draft_deal)

    clock = validate_success(
        client.set_clock(FIRST_SLOT_ENDS_AT, ctx.compliance_headers), 200
    )
    # PRD 2.4: "The clock capability responds with the new `current_utc` together with
    # `held_presentation_ids`, the identifiers of the rating presentations that the
    # advance promoted."
    assert_timestamps_equal(clock["current_utc"], FIRST_SLOT_ENDS_AT, "current_utc")
    assert clock["held_presentation_ids"] == [ctx.first_slot["id"]]

    first = _read_presentation(ctx, ctx.first_slot["id"])
    assert first["status"] == PresentationStatus.HELD
    assert first["cancellation_reason"] is None
    assert_version_advanced(first, ctx.first_slot, by=1, label="presentation")

    # The boundary is inclusive on `ends_at` alone: the 12:00-13:00 slot has not ended.
    assert (
        _read_presentation(ctx, ctx.second_slot["id"])["status"]
        == PresentationStatus.SCHEDULED
    )


def test_a_second_clock_advance_promotes_the_later_slot_without_touching_the_first(
    client, draft_deal
):
    """PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row, including mutations that only
    recompute a derived field."

    Design: Corner/state_machines/clock_advance_promotes_only_presentations_whose_end_has_passed
    """
    ctx = _two_slots_on_one_agency_day(draft_deal)
    fx.set_clock(client, FIRST_SLOT_ENDS_AT)
    after_first_advance = _read_presentation(ctx, ctx.first_slot["id"])

    clock = validate_success(
        client.set_clock(SECOND_SLOT_ENDS_AT, ctx.compliance_headers), 200
    )
    assert clock["held_presentation_ids"] == [ctx.second_slot["id"]]

    second = _read_presentation(ctx, ctx.second_slot["id"])
    assert second["status"] == PresentationStatus.HELD
    assert_version_advanced(second, ctx.second_slot, by=1, label="presentation")

    # HELD is terminal: no double promotion and no version churn on the first slot.
    first = _read_presentation(ctx, ctx.first_slot["id"])
    assert first["status"] == PresentationStatus.HELD
    assert_version_advanced(first, after_first_advance, by=0, label="presentation")


# ---------------------------------------------------------------------------
# state_machines / activating_a_second_undertaking_supersedes_the_first
# ---------------------------------------------------------------------------
def test_activating_a_second_undertaking_supersedes_the_first(client, draft_deal):
    """PRD 3.4: "Activation moves the undertaking to `ACTIVE` and moves every other
    undertaking of the same deal that was `ACTIVE` to the terminal `SUPERSEDED`,
    incrementing each affected row's `version`. Exactly one undertaking is therefore
    `ACTIVE` on a deal at any moment."

    Design: Corner/state_machines/activating_a_second_undertaking_supersedes_the_first
    """
    ctx = draft_deal
    first = fx.draft_undertaking(client, ctx.deal_id, ctx.counsel_headers)
    activated_first = fx.activate_undertaking(client, first["id"], ctx.issuer_headers)
    assert activated_first["status"] == UndertakingStatus.ACTIVE
    second = fx.draft_undertaking(
        client,
        ctx.deal_id,
        ctx.counsel_headers,
        annual_report_due_days=150,
        dissemination_agent="Lakeside Fiduciary",
        audited_financials_included=True,
    )

    activated_second = validate_success(
        client.activate_undertaking(second["id"], None, ctx.issuer_headers), 200
    )
    assert activated_second["status"] == UndertakingStatus.ACTIVE

    # The first undertaking is mutated although its identifier never appears in the
    # request that retired it.
    superseded = _read_undertaking(ctx, first["id"])
    assert superseded["status"] == UndertakingStatus.SUPERSEDED
    assert_version_advanced(superseded, activated_first, by=1, label="undertaking")

    rows, meta = validate_paginated(
        client.list_deal_undertakings(
            ctx.deal_id, ctx.compliance_headers, status=UndertakingStatus.ACTIVE
        )
    )
    assert_pagination(meta, total_count=1)
    assert ids_of(rows) == [second["id"]]


# ---------------------------------------------------------------------------
# state_machines / creating_a_new_official_statement_supersedes_its_predecessor
# ---------------------------------------------------------------------------
def test_creating_a_new_official_statement_supersedes_its_predecessor(
    client, draft_deal
):
    """PRD 3.4: "Creation also supersedes the predecessor: any earlier statement on the
    same deal whose `status` is `DRAFTING`, `IN_REVIEW`, or `REVISION_REQUESTED` is
    moved to the terminal `SUPERSEDED` state with its own `version` incremented."

    Design: Corner/state_machines/creating_a_new_official_statement_supersedes_its_predecessor
    """
    ctx = fx.with_drafting_statement(draft_deal)
    first_statement_id = ctx.statement_id
    section = fx.add_section(
        client, first_statement_id, f.material_risk_section_payload()
    )
    fx.approve_section(client, section["id"])
    assert fx.submit_for_review(client, first_statement_id)["status"] == (
        OfficialStatementStatus.IN_REVIEW
    )

    second = fx.start_official_statement(
        client, ctx.deal_id, ctx.counsel_headers, reader_headers=ctx.advisor_headers
    )

    assert second["status"] == OfficialStatementStatus.DRAFTING
    assert second["draft_round"] == 1
    assert second["mandatory_sections_approved"] is False
    assert (
        _read_statement(ctx, first_statement_id)["status"]
        == OfficialStatementStatus.SUPERSEDED
    )
    # Superseding a statement does not rewrite the sections it carried.
    assert _read_section(ctx, section["id"])["review_status"] == ReviewStatus.APPROVED

    # PRD 3.4: "`Deal.disclosure_clearance` is then recomputed against the newly created
    # statement, and the deal's `version` increments." The new statement is DRAFTING
    # with nothing approved, so the deal loses whatever the old one had earned.
    assert _read_deal(ctx)["disclosure_clearance"] == DisclosureClearance.PENDING


# ---------------------------------------------------------------------------
# state_machines / opening_an_order_period_requires_the_deal_to_be_in_a_pricing_state
# ---------------------------------------------------------------------------
def test_opening_the_book_waits_for_the_deal_to_reach_a_pricing_state(
    client, structuring_deal
):
    """PRD 3.7: "The deal must be in `PRICING_COMPETITIVE` or `PRICING_NEGOTIATED`, or
    the request is refused with `ERR_DEAL_INVALID_STATE`; a deal still in `STRUCTURING`
    has not yet chosen how it will sell its bonds and cannot take orders."

    Design: Corner/state_machines/opening_an_order_period_requires_the_deal_to_be_in_a_pricing_state
    """
    ctx = structuring_deal
    # PRD 2.1 puts actor ownership at tier 8, above state legality at tier 11, and an
    # `Underwriter` owns deal-scoped work only through an ACTIVE SyndicateMember seat
    # (the competitive carve-out cannot apply while `sale_method` is UNDETERMINED). The
    # seat therefore has to exist before the deal-state guard can be observed at all.
    fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
    )
    period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(PERIOD_OPENS_AT, PERIOD_CLOSES_AT),
    )
    fx.set_clock(client, INSIDE_THE_WINDOW)

    # The guard lives on the deal, not on the period: the period is SCHEDULED and the
    # clock is inside its window, so neither ERR_ORDER_PERIOD_INVALID_STATE nor
    # ERR_ORDER_PERIOD_WINDOW_CLOSED can explain the refusal.
    validate_error(
        client.open_order_period(period["id"], None, ctx.underwriter_headers),
        ERR_DEAL_INVALID_STATE,
    )
    assert (
        fx.read_period(client, period["id"], ctx.compliance_headers)["status"]
        == OrderPeriodStatus.SCHEDULED
    )

    deal = fx.designate_sale_method(
        client, ctx.deal_id, SaleMethod.NEGOTIATED, ctx.advisor_headers
    )
    assert deal["status"] == DealStatus.PRICING_NEGOTIATED

    # The identical call now succeeds, which isolates the deal-state guard as the sole
    # cause of the first refusal.
    opened = validate_success(
        client.open_order_period(period["id"], None, ctx.underwriter_headers), 200
    )
    assert opened["status"] == OrderPeriodStatus.OPEN
    assert opened["allotment_run_count"] == 0
