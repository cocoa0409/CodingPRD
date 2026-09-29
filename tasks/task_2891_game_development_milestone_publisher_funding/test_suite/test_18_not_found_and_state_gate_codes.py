"""Every path-scoped not-found code, and the milestone/build state gates that
each answer with their own code.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers.constants import ALPHA_PASSING_METRICS
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    record_accepted_review,
    record_rejected_review,
    setup_registry,
    setup_single_alpha,
    submit_build,
)

# Syntactically valid version-4 UUIDs that were never issued by the server.
MISSING_STUDIO = "00000000-0000-4000-8000-000000000001"
MISSING_PUBLISHER = "00000000-0000-4000-8000-000000000002"
MISSING_PUBLISHER_USER = "00000000-0000-4000-8000-000000000003"
MISSING_BUILD = "00000000-0000-4000-8000-000000000004"
MISSING_REVIEW = "00000000-0000-4000-8000-000000000005"
MISSING_PAYMENT = "00000000-0000-4000-8000-000000000006"
MISSING_CHANGE_ORDER = "00000000-0000-4000-8000-000000000007"
MISSING_ENGAGEMENT = "00000000-0000-4000-8000-000000000008"
MISSING_INVOICE = "00000000-0000-4000-8000-000000000009"
MISSING_STATEMENT = "00000000-0000-4000-8000-00000000000a"
MISSING_ENGAGEMENT_PARENT = "00000000-0000-4000-8000-00000000000b"
MISSING_MILESTONE = "00000000-0000-4000-8000-00000000000c"


def test_corner_every_path_scoped_not_found_code_carries_its_own_error_id(api):
    """Each path segment reports the not-found error of its own resource type, and
    the two nested read paths resolve their parent before answering.

    PRD §2.9 says "Where a path contains an identifier, the server resolves that
    identifier before it examines the request body or any business rule, and
    reports the not-found error belonging to that path segment's own resource
    type." PRD §2.10 then names each one: rule 7 `ERR_STUDIO_NOT_FOUND`, rule 8
    `ERR_PUBLISHER_NOT_FOUND`, rule 9 `ERR_PUBLISHER_USER_NOT_FOUND`, rule 11
    "A milestone identifier in the path resolves, on the milestone read, its
    build listing and its budget summary — `ERR_MILESTONE_NOT_FOUND`", rule 12
    `ERR_BUILD_NOT_FOUND`, rule 13 `ERR_REVIEW_NOT_FOUND`, rule 14
    `ERR_PAYMENT_NOT_FOUND`, rule 15 `ERR_CHANGE_ORDER_NOT_FOUND`, rule 16 "An
    engagement identifier in the path resolves, on the engagement read, its
    invoice listing, completion and cancellation — `ERR_ENGAGEMENT_NOT_FOUND`",
    rule 17 `ERR_INVOICE_NOT_FOUND` and rule 18 `ERR_STATEMENT_NOT_FOUND`.

    Design: Corner/errors/corner_every_path_scoped_not_found_code_is_reachable
    """
    # The registry is populated first, so "the table is empty" cannot pass for a miss.
    reg = setup_registry(api)
    assert reg.studio_id and reg.publisher_id and reg.finance_id

    validate_error(api.get_studio(MISSING_STUDIO, reg.admin), "ERR_STUDIO_NOT_FOUND", 404)
    validate_error(
        api.get_publisher(MISSING_PUBLISHER, reg.admin), "ERR_PUBLISHER_NOT_FOUND", 404
    )
    validate_error(
        api.get_publisher_user(MISSING_PUBLISHER_USER, reg.admin),
        "ERR_PUBLISHER_USER_NOT_FOUND",
        404,
    )
    validate_error(api.get_build(MISSING_BUILD, reg.admin), "ERR_BUILD_NOT_FOUND", 404)
    validate_error(api.get_review(MISSING_REVIEW, reg.admin), "ERR_REVIEW_NOT_FOUND", 404)
    validate_error(api.get_payment(MISSING_PAYMENT, reg.admin), "ERR_PAYMENT_NOT_FOUND", 404)
    validate_error(
        api.get_change_order(MISSING_CHANGE_ORDER, reg.admin), "ERR_CHANGE_ORDER_NOT_FOUND", 404
    )
    validate_error(
        api.get_engagement(MISSING_ENGAGEMENT, reg.admin), "ERR_ENGAGEMENT_NOT_FOUND", 404
    )
    validate_error(api.get_invoice(MISSING_INVOICE, reg.admin), "ERR_INVOICE_NOT_FOUND", 404)
    validate_error(
        api.get_royalty_statement(MISSING_STATEMENT, reg.admin), "ERR_STATEMENT_NOT_FOUND", 404
    )
    # A reverse-lookup sub-collection resolves its parent instead of answering [].
    validate_error(
        api.list_engagement_invoices(MISSING_ENGAGEMENT_PARENT, reg.admin),
        "ERR_ENGAGEMENT_NOT_FOUND",
        404,
    )
    # The computed read resolves the milestone before it computes anything.
    validate_error(
        api.get_budget_summary(MISSING_MILESTONE, reg.admin), "ERR_MILESTONE_NOT_FOUND", 404
    )


def test_corner_milestone_and_build_state_gates_each_report_their_own_code(api):
    """A stale build, a milestone that has left delivery, an accepted milestone and
    a restricted posture each answer with their own distinct code.

    PRD §3.5 pins two of them: "the reviewed build must be the current one: a
    build whose `gate_state` has become `SUPERSEDED`, equivalently one whose
    `build_number` is no longer the milestone's `latest_build_number`, is refused
    with `ERR_BUILD_SUPERSEDED`", and "The milestone must currently be
    `UNDER_REVIEW`, and anything else — including a second attempt to review a
    build whose milestone has already moved on — is
    `ERR_MILESTONE_NOT_UNDER_REVIEW`." PRD §3.4 pins the delivery gate: "The
    milestone must be open for delivery, meaning its `status` is `DEFINED`,
    `IN_DEVELOPMENT` or `CURE_PENDING`; anything else, and in particular a
    milestone already `UNDER_REVIEW`, `ACCEPTED`, `BREACHED` or `CANCELLED`, is
    `ERR_MILESTONE_NOT_OPEN_FOR_BUILD`." PRD §3.7 pins the amendability gate: "a
    target that is `ACCEPTED`, `BREACHED` or `CANCELLED` is
    `ERR_MILESTONE_NOT_AMENDABLE`." Finally PRD §2.6 says the posture "is
    `RESTRICTED` when `accepted_value_cents` has reached or passed thirty percent
    of `funding_pool_cents`" and PRD §3.2 says "Once the agreement's
    `funding_posture` has become `RESTRICTED`, fresh milestones are refused
    outright with `ERR_FUNDING_POSTURE_RESTRICTED`" — a rule PRD §2.10 ranks at
    30, ahead of rule 59, "The milestone's funding fits the pool, on milestone
    creation — `ERR_AGREEMENT_FUNDING_EXCEEDED`", which the same call also
    violates.

    Design: Corner/errors/corner_milestone_and_build_state_gates_each_report_their_own_code
    """
    scenario = setup_single_alpha(
        api, contractor_budget_cents=0, acceptance_criteria=DEFAULT_CRITERIA_1
    )
    reg = scenario.reg
    milestone_id = scenario.m1["id"]
    build_1 = submit_build(reg, milestone_id, 1, ALPHA_PASSING_METRICS)
    record_rejected_review(reg, build_1["id"], "2026-08-01", 9, 10)
    build_2 = submit_build(reg, milestone_id, 2, ALPHA_PASSING_METRICS)
    assert build_2["gate_state"] == "PASSED", build_2

    # The milestone IS under review, so the stale-build rule is the first to fire.
    validate_error(
        api.create_review(
            f.accepted_review_payload(build_1["id"], "2026-08-01", 11, 12), reg.reviewer
        ),
        "ERR_BUILD_SUPERSEDED",
        409,
    )
    assert (
        validate_success(api.get_build(build_1["id"], reg.dev))["gate_state"] == "SUPERSEDED"
    )

    validate_error(
        api.create_build(
            f.build_payload(milestone_id, 3, 80.00, 97.00, 65.00, 2), reg.dev
        ),
        "ERR_MILESTONE_NOT_OPEN_FOR_BUILD",
        409,
    )
    assert scenario.read_milestone(milestone_id)["latest_build_number"] == 2

    record_accepted_review(reg, build_2["id"], "2026-08-01", 13, 14)
    accepted = scenario.read_milestone(milestone_id)
    assert accepted["status"] == "ACCEPTED", accepted
    assert accepted["accepted_at"] is not None, accepted
    agreement = scenario.read_agreement()
    assert agreement["accepted_value_cents"] == 3600000, agreement
    assert agreement["funding_posture"] == "RESTRICTED", agreement

    validate_error(
        api.create_review(
            f.rejected_review_payload(build_2["id"], "2026-08-01", 15, 16), reg.reviewer
        ),
        "ERR_MILESTONE_NOT_UNDER_REVIEW",
        409,
    )

    validate_error(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, milestone_id, "FUNDING_UPLIFT",
                agreement["version"], "Extra polish on an accepted milestone",
                requested_amount_cents=100000, ship_date_delta_days=0,
            ),
            reg.dev,
        ),
        "ERR_MILESTONE_NOT_AMENDABLE",
        409,
    )
    orders = get_success_data(
        api.list_change_orders(reg.finance, {"agreement_id": scenario.agreement_id})
    )
    assert orders == [], f"a change order was written for an accepted milestone: {orders}"

    # Restriction outranks the funding-fit rule, which this call also violates.
    validate_error(
        api.create_milestone(
            f.milestone_payload(
                scenario.agreement_id, 2, "Late addition", "BETA", 10000, 0,
                ["Slipped in after acceptance"],
            ),
            reg.dev,
        ),
        "ERR_FUNDING_POSTURE_RESTRICTED",
        409,
    )
    rows = get_success_data(
        api.list_milestones(reg.dev, {"agreement_id": scenario.agreement_id})
    )
    assert len(rows) == 1, f"the restricted milestone was written: {rows}"
