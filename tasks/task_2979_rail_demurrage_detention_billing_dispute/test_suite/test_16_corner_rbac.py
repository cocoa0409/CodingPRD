"""Queue B - corner section ``rbac``.

Eight instances covering the four authorization bands of PRD 2.8 in the order
the ladder runs them: the role header (band 1), the user identifier (band 2),
per-operation role authority (band 3) and consignee ownership (band 4), plus the
segregation-of-duties bar (band 24) and the quiet narrowing that replaces a 403
on list endpoints.

Every rejection here is paired with the identical call from an entitled caller,
so no test can pass because the operation is broken for everyone.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CUSTOMER_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_error_meta_is_minimal,
    assert_fields_present,
    assert_pagination_meta,
    assert_subset_equal,
    error_id_of,
    ids_of,
)
from test_helpers.constants import (
    CHARGE_FINAL,
    CHARGE_PROVISIONAL,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_RELEASE_AT,
    CYCLE_B_GROSS_CENTS,
    DECISION_ALLOWED,
    DECISION_PENDING,
    DISPUTE_APPEALED,
    DISPUTE_DECIDED,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_RELEASED,
    MOVEMENT_VOIDED,
    ROLE_CUSTOMER,
    ROLE_RAILROAD_AGENT,
    TARIFF_STATUS_DRAFT,
)
from test_helpers.test_users import (
    ADMIN,
    OFFICER,
    adjudicator_pair,
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_adjudicator_headers,
    make_customer_headers,
)

# A claim well inside the 47550-cent reference invoice, so no ceiling band can
# be what answers any of these calls.
RBAC_CLAIM_CENTS = 20000

VOID_BY_THE_WRONG_LADDER = "Cancelled by the adjudicator."
ADMIN_WRITE_OFF = "Written off by the back office."

DISPUTE_BODY_FIELDS = (
    "id",
    "customer_id",
    "invoice_id",
    "scope",
    "grounds",
    "narrative",
    "claimed_credit_cents",
    "allowed_credit_cents",
    "allowance_pct",
    "status",
    "decision",
    "round_number",
    "info_request_count",
    "target_charge_count",
    "evidence_weight",
    "submitted_at",
    "adjudication_due_at",
    "first_level_adjudicator_id",
    "appeal_adjudicator_id",
)


# ===========================================================================
# instance: read_with_no_role_header_is_unauthenticated_before_it_is_not_found
# ===========================================================================
def test_the_role_header_is_checked_before_the_path_id_is_resolved(api):
    """401 at an unreal id, so the caller learns nothing about which ids exist.

    PRD 2.1: "A request whose `X-User-Role` header is absent, present but an
    empty string, or present but carrying any value other than those five is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before any
    path parameter is resolved, so an unauthenticated request aimed at an
    identifier that does not exist returns 401 and never 404 - the caller learns
    nothing about which identifiers are real."

    Design: Corner/rbac/read_with_no_role_header_is_unauthenticated_before_it_is_not_found
    """
    absent = api.get_customer(NON_EXISTENT_UUID, headers_without_role())
    validate_error(absent, ERR_UNAUTHENTICATED)
    assert absent.status_code == 401
    assert error_id_of(absent) != ERR_CUSTOMER_NOT_FOUND
    assert_error_meta_is_minimal(absent)

    # An undeclared but syntactically fine role name fails the same band: this
    # is a header check, not a per-operation role check.
    undeclared = api.get_customer(NON_EXISTENT_UUID, headers_with_undeclared_role())
    validate_error(undeclared, ERR_UNAUTHENTICATED)
    assert undeclared.status_code == 401

    blank = api.get_customer(NON_EXISTENT_UUID, headers_with_blank_role())
    validate_error(blank, ERR_UNAUTHENTICATED)
    assert blank.status_code == 401

    # The control that gives the three rejections their meaning: with a
    # recognised role the very same id resolves, and 404 is what the ladder
    # would have said had band 1 not answered first.
    missing = api.get_customer(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing, ERR_CUSTOMER_NOT_FOUND)
    assert missing.status_code == 404


# ===========================================================================
# instance: customer_action_with_no_user_id_header_is_unauthenticated
# ===========================================================================
def test_a_customer_action_without_a_user_id_is_401_and_not_400(api):
    """The role is right; the identity the ownership check needs is missing.

    PRD 2.1: "`X-User-ID` is required on every endpoint whose acting role is
    `Customer` or `DemurrageAdjudicator`, and its absence or emptiness on such an
    endpoint is also `ERR_UNAUTHENTICATED` (HTTP 401) rather than a schema
    error."

    Design: Corner/rbac/customer_action_with_no_user_id_header_is_unauthenticated
    """
    world = fx.reference_world(api)
    cycle = fx.actually_placed_cycle(api, world)
    assert cycle["movement_status"] == MOVEMENT_ACTUALLY_PLACED

    payload = f.release_payload(CYCLE_A_RELEASE_AT)
    anonymous = api.release(cycle["id"], payload, headers_without_user_id(ROLE_CUSTOMER))
    validate_error(anonymous, ERR_UNAUTHENTICATED)
    assert anonymous.status_code == 401
    # Not the schema band: the body it carried is the very body that succeeds
    # below.
    assert anonymous.status_code != 400
    assert_error_meta_is_minimal(anonymous)

    empty = api.release(cycle["id"], payload, headers_with_blank_user_id(ROLE_CUSTOMER))
    validate_error(empty, ERR_UNAUTHENTICATED)
    assert empty.status_code == 401

    frozen = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        frozen,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "released_at": None,
            "version": cycle["version"],
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_PROVISIONAL

    # The band names two roles only, so the same omission is harmless for a
    # RailroadAgent, whose identifier PRD 2.1 never persists or compares.
    read = api.get_placement_cycle(
        cycle["id"], headers_without_user_id(ROLE_RAILROAD_AGENT)
    )
    assert get_success_data(read)["id"] == cycle["id"]

    released = get_success_data(
        api.release(cycle["id"], payload, world["customer_headers"])
    )
    assert_subset_equal(
        released,
        {"movement_status": MOVEMENT_RELEASED, "released_at": CYCLE_A_RELEASE_AT},
    )


# ===========================================================================
# instance: billing_admin_cannot_decide_a_dispute
# ===========================================================================
def test_the_back_office_cannot_forgive_the_charge_it_raised(api):
    """The dispute is genuinely reviewable and the payload is valid.

    PRD 2.1: "the money ladder (creating, issuing and closing invoices, creating
    and reconciling average agreements, applying credit holds, voiding cycles,
    and driving the logical clock) belongs entirely to `BillingAdmin`, while the
    adjudication ladder (analysing bunching claims, beginning review, requesting
    information, and deciding disputes) belongs entirely to
    `DemurrageAdjudicator`. No role appears on both."

    Design: Corner/rbac/billing_admin_cannot_decide_a_dispute
    """
    world = fx.reference_world(api)
    fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    headers_a, adj_a, _headers_b, _adj_b = adjudicator_pair("c9r3")
    dispute = fx.under_review_dispute(
        api, invoice, world["customer_id"], RBAC_CLAIM_CENTS, adj_a
    )
    assert_subset_equal(
        dispute,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "first_level_adjudicator_id": adj_a,
            "decision": DECISION_PENDING,
        },
    )

    payload = f.decide_payload(
        DECISION_ALLOWED, 1, decision_rationale=ADMIN_WRITE_OFF
    )
    refused = api.decide_dispute(dispute["id"], payload, ADMIN)
    validate_error(refused, ERR_ROLE_FORBIDDEN)
    assert refused.status_code == 403
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_dispute(api, dispute["id"])
    assert_subset_equal(
        frozen,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "decision": DECISION_PENDING,
            "allowed_credit_cents": 0,
            "allowance_pct": None,
            "version": dispute["version"],
        },
    )

    # The identical payload from the entitled ladder is accepted.
    decided = get_success_data(api.decide_dispute(dispute["id"], payload, headers_a))
    assert_subset_equal(
        decided,
        {
            "status": DISPUTE_DECIDED,
            "decision": DECISION_ALLOWED,
            "allowed_credit_cents": RBAC_CLAIM_CENTS,
        },
    )


# ===========================================================================
# instance: adjudicator_cannot_void_the_cycle_it_just_credited
# ===========================================================================
def test_the_adjudicator_cannot_make_the_whole_cycle_disappear(api):
    """The mirror image: void is the back office's, so the credit ladder is barred.

    PRD 2.1: "A caller whose role does not appear in the authorized-role list for
    the operation it invoked is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403),
    and that rejection happens before the service checks whether the identifiers
    in the request exist - so a `RailroadAgent` attempting to create an invoice
    against a fabricated consignee identifier receives 403 and learns nothing about
    the identifier."

    Design: Corner/rbac/adjudicator_cannot_void_the_cycle_it_just_credited
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge, {"status": CHARGE_FINAL, "gross_amount_cents": CYCLE_A_GROSS_CENTS}
    )

    payload = f.void_payload(void_reason=VOID_BY_THE_WRONG_LADDER)
    refused = api.void_cycle(
        cycle["id"], payload, make_adjudicator_headers("adj-c9r4-a")
    )
    validate_error(refused, ERR_ROLE_FORBIDDEN)
    assert refused.status_code == 403
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        frozen,
        {"movement_status": MOVEMENT_RELEASED, "version": cycle["version"]},
    )
    still_final = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        still_final,
        {"status": CHARGE_FINAL, "gross_amount_cents": CYCLE_A_GROSS_CENTS},
    )

    voided = get_success_data(api.void_cycle(cycle["id"], payload, ADMIN))
    assert voided["movement_status"] == MOVEMENT_VOIDED


# ===========================================================================
# instance: customer_cannot_release_another_customers_car
# ===========================================================================
def test_a_second_consignee_cannot_release_the_first_consignees_car(api):
    """Right role, releasable cycle, wrong consignee: only the ownership band bites.

    PRD 2.1: "When `X-User-Role` is `Customer` and the request addresses a
    specific resource, `X-User-ID` must resolve to the consignee that owns it, or
    the request fails with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Ownership resolves
    along a declared chain: a placement cycle is owned by the consignee it names".

    Design: Corner/rbac/customer_cannot_release_another_customers_car
    """
    world = fx.reference_world(api)
    stranger = fx.make_customer(api)
    assert stranger["id"] != world["customer_id"]

    cycle = fx.actually_placed_cycle(api, world)
    assert cycle["customer_id"] == world["customer_id"]

    payload = f.release_payload(CYCLE_A_RELEASE_AT)
    refused = api.release(
        cycle["id"], payload, make_customer_headers(stranger["id"])
    )
    validate_error(refused, ERR_NOT_RESOURCE_OWNER)
    # 403 and not 404: the cycle is real, and the stranger is told so.
    assert refused.status_code == 403
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        frozen,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "released_at": None,
            "version": cycle["version"],
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_PROVISIONAL

    released = get_success_data(
        api.release(cycle["id"], payload, world["customer_headers"])
    )
    assert released["movement_status"] == MOVEMENT_RELEASED


# ===========================================================================
# instance: first_level_adjudicator_cannot_take_the_appeal
# ===========================================================================
def test_the_first_level_adjudicator_is_barred_from_the_appeal(api):
    """The bar is against the stored identity, so it follows the dispute.

    PRD 2.1: "The adjudicator identified by a dispute's
    `first_level_adjudicator_id` may not begin the review of, nor decide, that
    same dispute's second round; either attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The bar attaches to the stored
    first-level identifier and therefore follows the dispute rather than the
    session - a third adjudicator who never touched round one is free to take the
    appeal, and the round-one adjudicator remains free to work every other
    dispute in the system."

    Design: Corner/rbac/first_level_adjudicator_cannot_take_the_appeal
    """
    world = fx.reference_world(api)
    fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    headers_a, adj_a, headers_b, adj_b = adjudicator_pair("c9r6")

    decided = fx.decided_dispute(
        api, invoice, world["customer_id"], RBAC_CLAIM_CENTS, adj_a
    )
    assert_subset_equal(
        decided,
        {"status": DISPUTE_DECIDED, "first_level_adjudicator_id": adj_a},
    )
    appealed = fx.appealed_dispute(api, decided["id"], world["customer_id"])
    assert_subset_equal(
        appealed,
        {
            "status": DISPUTE_APPEALED,
            "round_number": 2,
            "first_level_adjudicator_id": adj_a,
            "appeal_adjudicator_id": None,
        },
    )

    refused = api.begin_review(decided["id"], headers_a)
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES)
    assert refused.status_code == 403
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_dispute(api, decided["id"])
    assert_subset_equal(
        frozen,
        {
            "status": DISPUTE_APPEALED,
            "round_number": 2,
            "appeal_adjudicator_id": None,
            # The failed call did not quietly reassign the stored identity, so
            # the bar still has something to compare against.
            "first_level_adjudicator_id": adj_a,
            "version": appealed["version"],
        },
    )

    reviewed = get_success_data(api.begin_review(decided["id"], headers_b))
    assert_subset_equal(
        reviewed,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "round_number": 2,
            "first_level_adjudicator_id": adj_a,
            "appeal_adjudicator_id": adj_b,
        },
    )


# ===========================================================================
# instance: customer_charge_list_is_silently_scoped_rather_than_forbidden
# ===========================================================================
def test_a_consignees_charge_list_is_narrowed_rather_than_refused(api):
    """A Customer list call is a 200 over fewer rows, never a 403.

    PRD 2.1: "List operations behave differently and more quietly: a `Customer`-role
    caller is silently narrowed to its own rows rather than being refused, so a
    consignee listing placement cycles, charges, invoices, disputes or complaints
    simply never sees another shipper's data - and supplying a `customer_id`
    filter naming a different consignee yields an empty result rather than an
    error."

    Design: Corner/rbac/customer_charge_list_is_silently_scoped_rather_than_forbidden
    """
    world = fx.reference_world(api)
    own_cycle = fx.released_cycle_a(api, world)
    stranger = fx.make_customer(api)
    stranger_world = dict(
        world,
        customer=stranger,
        customer_id=stranger["id"],
        customer_headers=make_customer_headers(stranger["id"]),
    )
    # The stranger's car needs its own industry track: PRD 3.5 re-derives the
    # facility's `last_switch_at` from Cycle A's 2026-08-10T16:00Z release, which
    # would otherwise sit after Cycle B's 2026-08-07T12:00Z actual placement and
    # trip the PRD 3.4 switch-buffer guard during setup.
    stranger_track = fx.make_industry_track(api)
    other_cycle = fx.released_cycle_b(
        api, stranger_world, facility_id=stranger_track["id"]
    )

    own_charge = fx.charge_of_cycle(api, own_cycle["id"])
    other_charge = fx.charge_of_cycle(api, other_cycle["id"])
    assert own_charge["gross_amount_cents"] == CYCLE_A_GROSS_CENTS
    assert other_charge["gross_amount_cents"] == CYCLE_B_GROSS_CENTS

    scoped = api.list_charges(world["customer_headers"], {"limit": 10, "offset": 0})
    assert scoped.status_code == 200
    rows = get_success_data(scoped)
    # total_count reports the scoped set, not the global one.
    assert_pagination_meta(
        scoped.json()["meta"], limit=10, offset=0, total_count=1, has_more=False
    )
    assert ids_of(rows) == [own_charge["id"]]
    assert rows[0]["gross_amount_cents"] == CYCLE_A_GROSS_CENTS

    everything = api.list_charges(ADMIN, {"limit": 10, "offset": 0})
    all_rows = get_success_data(everything)
    assert_pagination_meta(
        everything.json()["meta"], limit=10, offset=0, total_count=2, has_more=False
    )
    assert sorted(ids_of(all_rows)) == sorted([own_charge["id"], other_charge["id"]])
    assert sorted(row["gross_amount_cents"] for row in all_rows) == [
        CYCLE_B_GROSS_CENTS,
        CYCLE_A_GROSS_CENTS,
    ]

    # A filter pointing straight at the other shipper's cycle is answered with
    # an empty page rather than a refusal.
    filtered = api.list_charges(
        world["customer_headers"],
        {"placement_cycle_id": other_cycle["id"], "limit": 10, "offset": 0},
    )
    assert filtered.status_code == 200
    assert get_success_data(filtered) == []
    assert_pagination_meta(
        filtered.json()["meta"], total_count=0, has_more=False
    )


# ===========================================================================
# instance: regulatory_officer_can_read_a_dispute_but_cannot_review_it
# ===========================================================================
def test_the_regulator_reads_the_dispute_it_may_not_review(api):
    """One caller, 200 on the read side and 403 on the write side.

    PRD 4: `GET /demurrage/disputes/{id}` is authorized for "`Customer`,
    `DemurrageAdjudicator`, `RegulatoryOfficer`, `BillingAdmin`".  The begin-review
    row is authorized for "`DemurrageAdjudicator`" alone; only
    "`RegulatoryOfficer`" appears on the tariff-rule-set create row.

    Design: Corner/rbac/regulatory_officer_can_read_a_dispute_but_cannot_review_it
    """
    # The world's published tariff was itself drafted by the RegulatoryOfficer,
    # the only role §4 lets near POST /demurrage/tariff-rule-sets.
    world = fx.reference_world(api)
    fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    dispute = fx.submitted_dispute(
        api, invoice, world["customer_id"], RBAC_CLAIM_CENTS
    )
    assert dispute["status"] == DISPUTE_SUBMITTED

    read = api.get_dispute(dispute["id"], OFFICER)
    body = get_success_data(read)
    assert_subset_equal(
        body,
        {
            "status": DISPUTE_SUBMITTED,
            "claimed_credit_cents": RBAC_CLAIM_CENTS,
            "round_number": 1,
            "first_level_adjudicator_id": None,
        },
    )
    # The officer's read is the whole row, not a redacted projection: it is
    # byte-for-byte the body the back office sees.
    assert body == fx.get_dispute(api, dispute["id"])
    assert_fields_present(body, DISPUTE_BODY_FIELDS)
    assert_common_fields(body)

    refused = api.begin_review(dispute["id"], OFFICER)
    validate_error(refused, ERR_ROLE_FORBIDDEN)
    assert refused.status_code == 403
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_dispute(api, dispute["id"])
    assert_subset_equal(
        frozen,
        {
            "status": DISPUTE_SUBMITTED,
            "first_level_adjudicator_id": None,
            "version": dispute["version"],
        },
    )

    # The write side the officer does own, and which the back office does not.
    barred = api.create_tariff_rule_set(f.tariff_payload(), ADMIN)
    validate_error(barred, ERR_ROLE_FORBIDDEN)
    assert barred.status_code == 403

    drafted = get_success_data(api.create_tariff_rule_set(f.tariff_payload(), OFFICER), 201)
    assert drafted["status"] == TARIFF_STATUS_DRAFT
