"""The three version tokens, the derived totals behind them, and immediate visibility.

Exactly three creates in this system carry a parent version, and each names a
different parent and a different refusal code. Each of them is a write that no
state precondition would have blocked — the second estimate legitimately
supersedes the first, the second base proposal legitimately supersedes the first,
and the subcontract is legitimately written against an awarded package — so the
stale token is the only thing standing between a blind writer and a silent
discard. The last two tests pin what a client may believe from a single response:
four derived totals recomputed on every append, and a ledger figure that agrees
with an independent read by another role.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    AUDITOR_HEADERS,
    CM_HEADERS,
    CM_PM_HEADERS,
    OWNER_HEADERS,
    PO_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_equals,
    assert_fields,
    assert_gmp_identity,
    assert_instant,
    assert_money,
    assert_money_fields,
    assert_null,
    assert_page_meta,
    assert_project_axes,
    factories,
    fixtures,
    ids_of,
    line_by_seq,
    to_decimal,
)
from test_helpers.constants import CLOCK_START

CLINIC = {"name": "Harborview Clinic", "owner_org": "Harborview Health"}
CLINIC_KWARGS = {"project_kwargs": dict(CLINIC)}
SOLICITATION_OPENS = "2026-08-01T00:00:00Z"
SOLICITATION_CLOSES = "2026-08-15T00:00:00Z"
AUGUST = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
PERFORMANCE = ("2026-09-01T00:00:00Z", "2026-12-01T00:00:00Z")


def test_a_second_estimate_for_the_same_milestone_needs_the_token_the_first_consumed(
    api: ApiClient,
) -> None:
    """The refused write consumes nothing, so the client's next read hands it a usable token.

    PRD: "Creating a progressive estimate requires `expected_project_version` to equal the target project's current `version`. If it does not, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). A new estimate for a milestone legitimately supersedes the prior non-reconciled estimate for that same milestone, so no state precondition blocks the second write — the stale-version check is what makes the supersede decision safe."

    PRD: "Because a new estimate for a milestone displaces the previous one, the write also carries `expected_project_version` as described in §2.10, and a successful create increments the project's own `version` by 1."

    PRD: "Filing a newer estimate for the same `project_id` and the same `milestone_code` supersedes its predecessor: any prior estimate of that project and milestone whose status is `DRAFT`, `SUBMITTED` or `RETURNED` moves to `SUPERSEDED`, has its `superseded_by_estimate_id` set to the new row's identifier, and has its `version` incremented."

    PRD: "A freshly registered project arrives at `version` 1 with all four of its state axes at their initial values — `gmp_status` at `PRECONSTRUCTION`, `contingency_posture` at `OPEN`, `audit_status` at `NOT_REQUESTED`, `closeout_status` at `NOT_STARTED` — with `pending_amendment_count` at 0 and with every money field at 0.00."

    Design: Corner/complexity_layers/estimate_creation_rejects_a_project_version_the_client_last_observed_before_a_sibling_write
    """
    project = fixtures.create_project(api, **CLINIC)
    first_token = project["version"]
    sd = fixtures.create_estimate(
        api,
        project["id"],
        milestone_code="SD",
        submitted_cost_of_work=Decimal("1000000.00"),
        expected_project_version=first_token,
    )

    validate_error(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                first_token,
                milestone_code="SD",
                submitted_cost_of_work=Decimal("1010000.00"),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.STALE_PROJECT_VERSION,
        412,
    )

    rows, meta = validate_paginated(
        api.list_estimates(CM_HEADERS, {"project_id": project["id"]})
    )
    assert_page_meta(meta, total_count=1)
    assert ids_of(rows) == [sd["id"]], "the refused write filed nothing"
    assert_null(fixtures.read_estimate(api, sd["id"]), "superseded_by_estimate_id")

    fresh_token = fixtures.project_version(api, project["id"])
    assert fresh_token == first_token + 1, (
        "only the successful first estimate moved the project version"
    )

    second = validate_success(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                fresh_token,
                milestone_code="SD",
                submitted_cost_of_work=Decimal("1010000.00"),
            ),
            CM_HEADERS,
        ),
        201,
    )
    superseded = fixtures.read_estimate(api, sd["id"])
    assert_fields(
        superseded,
        {"status": "SUPERSEDED", "superseded_by_estimate_id": second["id"]},
    )
    assert fixtures.project_version(api, project["id"]) == fresh_token + 1


def test_a_second_base_proposal_needs_the_token_the_first_pricing_produced(
    api: ApiClient,
) -> None:
    """A stale writer would discard four computed money fields it never read.

    PRD: "Creating a base guaranteed-maximum-price proposal likewise requires `expected_project_version` to equal the project's current `version`, and a mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). Because a newer base proposal supersedes the prior draft, under-review or returned proposal, a stale writer would otherwise silently discard pricing it never saw."

    PRD: "As with estimates, a newer base proposal supersedes its predecessor: any prior base proposal of the same project whose status is `DRAFT`, `OWNER_REVIEW` or `RETURNED_FOR_REVISION` moves to `SUPERSEDED` with `superseded_by_proposal_id` set to the new row's identifier and its `version` incremented."

    PRD: "A base proposal is minted with `proposal_type` recorded as `BASE`, `status` at `DRAFT`, `amount_delta` at 0.00 and `change_event_id` null, and the create increments the project's `version` by 1."

    PRD: "Compute a *provisional* fee as the project's `cm_fee_pct` multiplied by that base, rounded half-up to 2 decimal places, and retain it on the proposal as `provisional_fee_amount`."

    PRD: "Compute `insurance_amount` as the project's `insurance_rate` multiplied by the sum of the base and `provisional_fee_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the **binding** `cm_fee_amount` as the project's `cm_fee_pct` multiplied by the sum of the base and `insurance_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the proposal's `gmp_amount` as the exact sum of five already-rounded terms: the base, `insurance_amount`, `cm_fee_amount`, `owner_contingency_amount` and `construction_contingency_amount`."

    Design: Corner/complexity_layers/gmp_proposal_creation_rejects_a_project_version_that_predates_the_pricing_it_would_discard
    """
    project = fixtures.create_project(api, **CLINIC)
    estimate = fixtures.reconciled_estimate(
        api, project["id"], submitted_cost_of_work=Decimal("1000000.00")
    )
    pricing_token = fixtures.project_version(api, project["id"])

    first = validate_success(
        api.create_gmp_proposal(
            factories.gmp_proposal_payload(
                project["id"],
                estimate["id"],
                pricing_token,
                cost_of_work_total=Decimal("1000000.00"),
                general_conditions_total=Decimal("100000.00"),
                owner_contingency_amount=Decimal("50000.00"),
                construction_contingency_amount=Decimal("40000.00"),
            ),
            CM_HEADERS,
        ),
        201,
    )

    validate_error(
        api.create_gmp_proposal(
            factories.gmp_proposal_payload(
                project["id"],
                estimate["id"],
                pricing_token,
                cost_of_work_total=Decimal("1020000.00"),
                general_conditions_total=Decimal("100000.00"),
                owner_contingency_amount=Decimal("50000.00"),
                construction_contingency_amount=Decimal("40000.00"),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.STALE_PROJECT_VERSION,
        412,
    )

    intact = fixtures.read_proposal(api, first["id"])
    assert_fields(intact, {"status": "DRAFT", "proposal_type": "BASE"})
    assert_money_fields(
        intact,
        {
            "provisional_fee_amount": Decimal("44000.00"),
            "insurance_amount": Decimal("11440.00"),
            "cm_fee_amount": Decimal("44457.60"),
            "gmp_amount": Decimal("1245897.60"),
        },
    )
    assert_null(intact, "superseded_by_proposal_id")

    fresh_token = fixtures.project_version(api, project["id"])
    assert fresh_token == pricing_token + 1

    repriced = validate_success(
        api.create_gmp_proposal(
            factories.gmp_proposal_payload(
                project["id"],
                estimate["id"],
                fresh_token,
                cost_of_work_total=Decimal("1020000.00"),
                general_conditions_total=Decimal("100000.00"),
                owner_contingency_amount=Decimal("50000.00"),
                construction_contingency_amount=Decimal("40000.00"),
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_money_fields(
        repriced,
        {
            "provisional_fee_amount": Decimal("44800.00"),
            "insurance_amount": Decimal("11648.00"),
            "cm_fee_amount": Decimal("45265.92"),
            "gmp_amount": Decimal("1266913.92"),
        },
    )
    assert_fields(
        fixtures.read_proposal(api, first["id"]),
        {"status": "SUPERSEDED", "superseded_by_proposal_id": repriced["id"]},
    )
    assert_project_axes(
        fixtures.read_project(api, project["id"]), gmp_status="PRECONSTRUCTION"
    )


def test_a_subcontract_needs_the_package_version_the_award_wrote(
    api: ApiClient,
) -> None:
    """A different parent and a different code: the package, not the project, is the token holder.

    PRD: "Creating a subcontract requires `expected_work_package_version` to equal the target work package's current `version`, and a mismatch is rejected with `ERR_STALE_WORK_PACKAGE_VERSION` (HTTP 412). A replacement subcontract written after a default supersedes the terminated one's committed scope, and the termination cascade rewrites the package's `awarded_amount`, `committed_amount` and `replacement_reserve_amount` behind the client's back; the version the client holds is the only evidence it priced against the current package."

    PRD: "The award advances the package `SOLICITING → AWARDED`, writes `awarded_bid_id` from the supplied `bid_id` and `awarded_amount` from that bid's `base_bid_amount`, advances the winning bid `OPENED → AWARDED`, and moves **every other** bid on that package that is currently `OPENED` to `NOT_AWARDED`."

    PRD: "A new subcontract begins with `contract_status` at `ACTIVE`, `paid_to_date` at 0.00, `unpaid_committed_amount` equal to its `contract_amount`, `replacement_cost_amount` at 0.00, `bond_claim_amount` at 0.00, `bond_recovered_amount` at 0.00, `default_notice_at` null and `cure_count` at 0."

    PRD: "when `bond_required` is false it is initialised to `NOT_APPLICABLE`, a terminal dead axis on which no bond-claim action will ever be accepted."

    PRD: "The write also recounts the parent package's `committed_amount` and increments the package's `version` by 1."

    PRD: "That recount is defined once and used everywhere: a package's `committed_amount` is the sum of `contract_amount` over its subcontracts whose `contract_status` is `ACTIVE`, `DEFAULT_NOTICED` or `COMPLETED`, plus the sum of `paid_to_date` over its subcontracts whose `contract_status` is `TERMINATED_FOR_DEFAULT`."

    Design: Corner/complexity_layers/subcontract_creation_rejects_a_work_package_version_that_predates_the_award
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    package = fixtures.soliciting_package(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
        solicitation_opens_at=SOLICITATION_OPENS,
        solicitation_closes_at=SOLICITATION_CLOSES,
    )
    bid = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("460000.00"),
        bidder_name="Cascade Concrete",
    )
    soliciting_token = fixtures.work_package_version(api, package["id"])

    fixtures.set_clock(api, SOLICITATION_CLOSES)
    validate_success(api.open_bid(bid["id"], PO_HEADERS))
    awarded = validate_success(
        api.award_work_package(
            package["id"], factories.award_payload(bid["id"]), PO_HEADERS
        )
    )
    assert_fields(awarded, {"procurement_status": "AWARDED", "awarded_bid_id": bid["id"]})
    assert_money(awarded["awarded_amount"], Decimal("460000.00"), "awarded_amount")

    validate_error(
        api.create_subcontract(
            factories.subcontract_payload(
                package["id"],
                bid["id"],
                soliciting_token,
                contract_amount=Decimal("460000.00"),
                performance_start=PERFORMANCE[0],
                performance_end=PERFORMANCE[1],
                subcontractor_name="Cascade Concrete",
                bond_required=False,
            ),
            CM_HEADERS,
        ),
        ApiErrorId.STALE_WORK_PACKAGE_VERSION,
        412,
    )
    _rows, meta = validate_paginated(
        api.list_subcontracts(CM_HEADERS, {"work_package_id": package["id"]})
    )
    assert_page_meta(meta, total_count=0)
    assert_money(
        fixtures.read_work_package(api, package["id"])["committed_amount"],
        Decimal("0.00"),
        "committed_amount",
    )

    awarded_token = fixtures.work_package_version(api, package["id"])
    assert awarded_token == soliciting_token + 1, "the award contributed the increment"

    subcontract = validate_success(
        api.create_subcontract(
            factories.subcontract_payload(
                package["id"],
                bid["id"],
                awarded_token,
                contract_amount=Decimal("460000.00"),
                performance_start=PERFORMANCE[0],
                performance_end=PERFORMANCE[1],
                subcontractor_name="Cascade Concrete",
                bond_required=False,
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_fields(
        subcontract,
        {"contract_status": "ACTIVE", "bond_claim_status": "NOT_APPLICABLE"},
    )
    assert_money_fields(
        subcontract,
        {
            "unpaid_committed_amount": Decimal("460000.00"),
            "paid_to_date": Decimal("0.00"),
        },
    )

    committed = fixtures.read_work_package(api, package["id"])
    assert_money(
        committed["committed_amount"], Decimal("460000.00"), "committed_amount"
    )
    assert_fields(committed, {"version": awarded_token + 1})


def _the_split_partitions_the_total(report: dict, where: str) -> None:
    """The disputed split must exhaust the reported total with no residual cent."""
    reported = to_decimal(report["reported_cost_total"])
    parts = to_decimal(report["undisputed_cost_total"]) + to_decimal(
        report["disputed_cost_total"]
    )
    assert reported == parts, (
        f"{where}: reported_cost_total {reported} must equal the split {parts}"
    )


def test_every_append_recomputes_all_four_totals_from_the_stored_lines(
    api: ApiClient,
) -> None:
    """Three appends, three recomputations, and a split that partitions the total every time.

    PRD: "The appended line object exposes `line_seq` set to the report's `line_count` plus 1, together with `work_package_id`, `quantity`, `unit_rate`, `markup_pct`, the computed `line_amount` and `disputed`."

    PRD: "Each line's extended amount is computed and rounded to 2 decimal places, half-up, *before it enters any total*:"

    PRD: "`line_amount = round(quantity × unit_rate × (1 + markup_pct), 2)`"

    PRD: "The report's `reported_cost_total` is then the sum of `line_amount` over every line, `undisputed_cost_total` is the sum of `line_amount` over lines whose `disputed` is false, `disputed_cost_total` is the sum over lines whose `disputed` is true, and `line_count` is the number of entries in `lines`."

    PRD: "Summing the exact unrounded products and rounding once at the end produces a different number, and that number is wrong."

    PRD: "Every subtotal the response exposes must be a sum of the **same** rounded `line_amount` values the response exposes, which guarantees the invariant that `reported_cost_total` equals `undisputed_cost_total` plus `disputed_cost_total` exactly, with no residual cent."

    PRD: "All four figures are recomputed from the rounded line amounts on every append, and the report's `version` increments by 1."

    PRD: "`version` — an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row. A cascade that mutates three rows increments three separate `version` counters."

    Design: Corner/complexity_layers/cost_report_totals_are_recomputed_from_the_stored_lines_on_every_append
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    report = fixtures.cost_report(
        api, executed.id, period_start=AUGUST[0], period_end=AUGUST[1]
    )

    after_first = validate_success(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("100.0000"),
                unit_rate=Decimal("200.0000"),
                markup_pct=Decimal("0.0000"),
                cost_code="03-100",
                disputed=False,
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_equals(after_first, "line_count", 1)
    assert_money(
        line_by_seq(after_first, 1)["line_amount"], Decimal("20000.00"), "line_amount"
    )
    assert_money_fields(
        after_first,
        {
            "reported_cost_total": Decimal("20000.00"),
            "undisputed_cost_total": Decimal("20000.00"),
            "disputed_cost_total": Decimal("0.00"),
        },
    )
    _the_split_partitions_the_total(after_first, "after the first append")

    after_second = validate_success(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("3.0000"),
                unit_rate=Decimal("1234.5678"),
                markup_pct=Decimal("0.1000"),
                cost_code="03-200",
                disputed=True,
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_equals(after_second, "line_count", 2)
    assert_money(
        line_by_seq(after_second, 2)["line_amount"], Decimal("4074.07"), "line_amount"
    )
    assert_money_fields(
        after_second,
        {
            "reported_cost_total": Decimal("24074.07"),
            "undisputed_cost_total": Decimal("20000.00"),
            "disputed_cost_total": Decimal("4074.07"),
        },
    )
    _the_split_partitions_the_total(after_second, "after the second append")

    after_third = validate_success(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("7.0000"),
                unit_rate=Decimal("99.9950"),
                markup_pct=Decimal("0.0000"),
                cost_code="03-300",
                disputed=False,
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_equals(after_third, "line_count", 3)
    assert_money(
        line_by_seq(after_third, 3)["line_amount"], Decimal("699.97"), "line_amount"
    )
    assert_money_fields(
        after_third,
        {
            "reported_cost_total": Decimal("24774.04"),
            "undisputed_cost_total": Decimal("20699.97"),
            "disputed_cost_total": Decimal("4074.07"),
        },
    )
    _the_split_partitions_the_total(after_third, "after the third append")

    auditor_read = validate_success(api.get_cost_report(report["id"], AUDITOR_HEADERS))
    assert_fields(auditor_read, {"status": "OPEN", "line_count": 3, "version": 4})
    assert [line["line_seq"] for line in auditor_read["lines"]] == [1, 2, 3]
    assert_money_fields(
        auditor_read,
        {
            "reported_cost_total": Decimal("24774.04"),
            "undisputed_cost_total": Decimal("20699.97"),
            "disputed_cost_total": Decimal("4074.07"),
        },
    )
    _the_split_partitions_the_total(auditor_read, "on a fresh read")


def test_a_classification_and_its_post_are_already_true_in_their_own_responses(
    api: ApiClient,
) -> None:
    """No settling period: the write's own body is authoritative and another role's read agrees.

    PRD: "Whichever branch is taken, the event advances `UNDER_REVIEW → CLASSIFIED`, its `classification` is written from the payload, `classified_by_user_id` is recorded from the acting `X-User-ID`, `classified_at` is stamped from the logical clock, and both the event's `version` and the project's `version` increment by 1."

    PRD: "A contingency draw is minted with `contingency_type` `CONSTRUCTION`, `origin` `CHANGE_EVENT_CLASSIFICATION`, `status` `REQUESTED`, `amount` equal to the event's `estimated_amount`, `change_event_id` naming this event and `source_subcontract_id` null, with `requires_owner_approval` determined by the approval rule in §3.7 rather than being forced true."

    PRD: "Every draw in the system is minted by a cascade — either the classification of a change event onto one of the two contingency branches described in §3.6, or the termination-for-default cascade described in §3.5 — and listing draws, filterable by `project_id`, by the `change_event_id` that produced them, by the `source_subcontract_id` that produced them, by `contingency_type`, by `origin` and by `status`, is the only channel through which a client discovers one."

    PRD: "If it is `CONSTRUCTION`, `requires_owner_approval` is true when any one of three conditions holds: the draw's `amount` is strictly greater than 50,000.00; or the project's `contingency_posture` at mint time is `CONSTRAINED`; or the draw's `origin` is `SUBCONTRACTOR_DEFAULT_PREMIUM`."

    PRD: "It is permitted from `REQUESTED` only when `requires_owner_approval` is false, and otherwise from `OWNER_APPROVED`; from any other status it draws `ERR_DRAW_STATE_INVALID` (HTTP 409)."

    PRD: "A successful post advances the draw `REQUESTED → POSTED` or `OWNER_APPROVED → POSTED` with identical ledger effects in both cases: `posted_at` is stamped from the logical clock, the drawn pot's remaining balance decreases by the draw's `amount`, and the project's `contingency_drawn_to_cost_total` increases by the same `amount`, leaving `gmp_amount` unmoved."

    PRD: "At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it continues to read that value until it is moved."

    PRD: "Otherwise the posture is `OPEN`."

    PRD: "`gmp_amount` equals the sum of `cost_of_work_budget_total`, `general_conditions_total`, `insurance_amount`, `cm_fee_amount`, `owner_contingency_remaining`, `construction_contingency_remaining`, and `contingency_drawn_to_cost_total`."

    Design: Corner/consistency_model/every_derived_field_a_write_moves_is_visible_in_that_write_s_own_response
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    event = fixtures.event_under_review(
        api,
        executed.id,
        estimated_amount=Decimal("30000.00"),
        origin="FIELD_CONDITION",
        description="temporary dewatering not in the base scope assumption",
        submitter_headers=CM_PM_HEADERS,
    )

    classified = validate_success(
        api.classify_change_event(
            event["id"],
            factories.classify_payload("CONTINGENCY_USE_CONSTRUCTION"),
            OWNER_HEADERS,
        )
    )
    assert_fields(
        classified,
        {"status": "CLASSIFIED", "classification": "CONTINGENCY_USE_CONSTRUCTION"},
    )
    assert_instant(classified["classified_at"], CLOCK_START, "classified_at")

    draws, meta = validate_paginated(
        api.list_draws(
            CM_HEADERS,
            {"project_id": executed.id, "origin": "CHANGE_EVENT_CLASSIFICATION"},
        )
    )
    assert_page_meta(meta, total_count=1)
    minted = draws[0]
    assert_fields(
        minted,
        {
            "contingency_type": "CONSTRUCTION",
            "origin": "CHANGE_EVENT_CLASSIFICATION",
            "status": "REQUESTED",
            "requires_owner_approval": False,
            "change_event_id": event["id"],
        },
    )
    assert_money(minted["amount"], Decimal("30000.00"), "amount")
    assert_null(minted, "source_subcontract_id")

    posted = validate_success(
        api.post_draw(
            minted["id"],
            CM_HEADERS,
            factories.draw_post_payload(
                "dewatering charged to the construction contingency"
            ),
        )
    )
    assert_fields(posted, {"status": "POSTED"})
    assert_instant(posted["posted_at"], CLOCK_START, "posted_at")

    independent = validate_success(api.get_project(executed.id, AUDITOR_HEADERS))
    assert_money_fields(
        independent,
        {
            "construction_contingency_remaining": Decimal("10000.00"),
            "contingency_drawn_to_cost_total": Decimal("30000.00"),
            "owner_contingency_remaining": Decimal("50000.00"),
            "gmp_amount": Decimal("1245897.60"),
        },
    )
    assert_project_axes(independent, contingency_posture="OPEN")
    assert_gmp_identity(independent)
