"""RBAC corners: the launch-plan field-level role split, peer-role resource
ownership with shared reads, and ownership-scoped quote withdrawal.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_manufacturer,
    create_partner,
    create_quote,
    create_retail_partner_payload,
    evaluate_quote,
    make_manufacturer_rep_headers,
    read_launch_plan,
    set_clock,
    setup_draft_plan,
    setup_sourcing_product,
    validate_error,
    validate_success,
    withdraw_quote,
)

_PM = TEST_USERS["product_manager_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]
_MARKETING = TEST_USERS["marketing_lead_headers"]


def test_launch_plan_patch_field_level_role_split(api):
    """PRD §2.1: "A product-plan update carrying `status` or `variant`
    requires `ProductManager`, while one carrying `sampling_status` or
    `sample_budget_cents` requires `MarketingLead`; mixing the two field
    groups in a single call is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.8: "The marketing lead may move `sampling_status` from `NONE` to
    `PLANNED` while the plan is in `QUANTITY_LOCKED`, `APPROVED`, or
    `EXECUTED` — any other plan state is rejected with `ERR_INVALID_STATE`..."
    ProductManager carrying sampling_status: 403. MarketingLead carrying
    status/variant: 403. MarketingLead carrying sampling_status passes the
    role gate and fails the state gate (409) on the DRAFT plan.

    Design: Corner/rbac/launch_plan_patch_field_level_role_split
    """
    ctx = setup_draft_plan()
    plan_id = ctx["plan"]["id"]

    validate_error(
        api.patch_launch_plan(plan_id, {"sampling_status": "PLANNED"}, _PM),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.patch_launch_plan(
            plan_id, {"status": "QUANTITY_LOCKED", "variant": "DEMAND"}, _MARKETING
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.patch_launch_plan(plan_id, {"sampling_status": "PLANNED"}, _MARKETING),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    plan = read_launch_plan(plan_id)
    assert plan["status"] == "DRAFT"
    assert plan["sampling_status"] == "NONE"


def test_sourcing_lead_cannot_create_retail_partner_but_can_read(api):
    """PRD §2.1: "Once authenticated, a request whose role is not authorized
    for the endpoint — or for the particular field group it attempts to write
    — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`RetailPlanner` — onboards retail partners and maintains their
    shelf capacities, schedules and drives line reviews, proposes and commits
    planogram slots, and approves or rejects discontinuation reviews."
    The SourcingLead create is a 403 while the same role's read of the
    planner-owned partner succeeds.

    Design: Corner/rbac/sourcing_lead_cannot_create_retail_partner_but_can_read
    """
    set_clock()
    partner = create_partner()

    response = api.create_retail_partner(
        create_retail_partner_payload(
            name="Intruder Beauty", banner_code="IB", category_capacities={"EYES": 4}
        ),
        _SOURCING,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    read = validate_success(api.get_retail_partner(partner["id"], _SOURCING))
    assert read["id"] == partner["id"]


def test_quote_withdraw_restricted_to_the_owning_manufacturer_rep(api):
    """PRD §2.1: "On the quote lifecycle, a withdrawal requires
    `ManufacturerRep` acting for its own manufacturer, while every other
    status target requires `SourcingLead`."
    PRD §3.5: "From `SUBMITTED` or `UNDER_EVALUATION`, the manufacturer's own
    `ManufacturerRep` may withdraw the quote, moving it to `WITHDRAWN`."
    SecondSource's UNDER_EVALUATION quote: FastLab's rep is 403, the
    SourcingLead is 403, and SecondSource's own rep succeeds.

    Design: Corner/rbac/quote_withdraw_restricted_to_owning_manufacturer_rep
    """
    ctx = setup_sourcing_product()
    create_quote(ctx["product"]["id"], ctx["manufacturer"]["id"])
    foreign = create_manufacturer(
        name="SecondSource Labs", capabilities=["EYES"], base_lead_time_weeks=6
    )
    quote_b = create_quote(
        ctx["product"]["id"], foreign["id"], unit_cost_cents=210
    )
    evaluate_quote(quote_b["id"])

    validate_error(
        api.patch_cost_quote(
            quote_b["id"],
            {"status": "WITHDRAWN"},
            make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.patch_cost_quote(quote_b["id"], {"status": "WITHDRAWN"}, _SOURCING),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    withdrawn = withdraw_quote(quote_b["id"], foreign["id"])
    assert withdrawn["status"] == "WITHDRAWN"
