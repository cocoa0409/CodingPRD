"""Composite setup builders and pytest fixtures.

The server is restarted with an empty database before every individual test, so
each fixture builds all of the state it needs from scratch through the public
API.  One development pathway runs from opening a brand program all the way to
launching an item, and almost every scenario needs some prefix of it, so that
pathway is expressed once in :func:`build_chain` and every checkpoint fixture is
a named stop along it.

``build_chain(api, upto=N, **overrides)`` runs the first ``N`` steps and returns
a context dictionary carrying every resource it created plus its id.  Overrides
are per-step dictionaries, for example
``build_chain(api, upto=25, program={"dev_budget_cents": 300000})``.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.constants import (
    ACTION_CLOSE,
    ACTION_COMPLETE_RELAUNCH,
    ACTION_START_RELAUNCH,
    AUDIT_ONGOING_QUALITY,
    DECISION_ACCEPT,
    DECISION_CONDITIONAL,
    DECISION_QUALIFY,
    DECISION_SUSPEND,
    DISPOSITION_DISCONTINUE,
    DISPOSITION_REPLACE,
    REVIEW_APPROVE,
    RUN_ONGOING,
    TIER_NBE,
)
from test_helpers.test_users import (
    DESIGNER_HEADERS,
    DIRECTOR_2_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_HEADERS,
    REGULATORY_HEADERS,
    SOURCING_HEADERS,
    make_supplier_headers,
)


# --- Step-level helpers ---------------------------------------------------


def _sub(overrides, key):
    """Return the per-step override dictionary for ``key``."""
    value = overrides.get(key)
    return dict(value) if value else {}


def advance_clock(api, instant, headers=DIRECTOR_HEADERS):
    """Move the logical clock; every role is allowed to set it."""
    return get_success_data(api.set_clock(instant, headers))


def read_item(api, item_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_item(item_id, headers))


def read_gap(api, gap_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_gap(gap_id, headers))


def read_supplier(api, supplier_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_supplier(supplier_id, headers))


def read_cost_model(api, cost_model_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_cost_model(cost_model_id, headers))


def read_specification(api, specification_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_specification(specification_id, headers))


def read_run(api, run_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_production_run(run_id, headers))


def read_artwork_round(api, artwork_round_id, headers=DESIGNER_HEADERS):
    return get_success_data(api.get_artwork_round(artwork_round_id, headers))


def read_claim(api, claim_id, headers=REGULATORY_HEADERS):
    return get_success_data(api.get_label_claim(claim_id, headers))


def read_change_request(api, request_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_change_request(request_id, headers))


def read_budget_ledger(api, program_id, headers=DIRECTOR_HEADERS):
    return get_success_data(api.get_budget_ledger(program_id, headers))


def read_scorecard(api, supplier_id, headers=SOURCING_HEADERS):
    return get_success_data(api.get_scorecard(supplier_id, headers))


# --- The development pathway ---------------------------------------------


def build_chain(api, upto=31, **overrides):
    """Run the first ``upto`` steps of the development pathway.

    Steps: 1 open program, 2 open gap, 3 analyze gap, 4 approve tier,
    5 register supplier, 6 register plant line, 7 schedule capability audit,
    8 finalize audit, 9 qualify supplier, 10 create item, 11 submit cost model,
    12 accept cost model, 13 bench-top study, 14 finalize it, 15 consumer panel,
    16 finalize it, 17 artwork round, 18 generate nutrition panel, 19 label
    claim, 20 approve claim, 21 submit round, 22 approve round, 23 read the
    item's current version, 24 create specification, 25 lock it, 26 schedule a
    first-production run, 27 approve the run, 28 advance the clock past the
    window, 29 complete the run, 30 launch the item, 31 read the cost model's
    current version.
    """
    ctx = {"api": api}

    if upto >= 1:
        ctx["program"] = get_success_data(
            api.create_program(
                f.program_payload(**_sub(overrides, "program")), DIRECTOR_HEADERS
            )
        )
        ctx["program_id"] = ctx["program"]["id"]

    if upto >= 2:
        gap_factory = overrides.get("gap_factory", f.gap_payload)
        ctx["gap"] = get_success_data(
            api.create_gap(
                gap_factory(ctx["program_id"], **_sub(overrides, "gap")),
                SOURCING_HEADERS,
            )
        )
        ctx["gap_id"] = ctx["gap"]["id"]

    if upto >= 3:
        ctx["gap"] = get_success_data(
            api.analyze_gap(
                ctx["gap_id"], _sub(overrides, "analyze"), SOURCING_HEADERS
            )
        )

    if upto >= 4:
        tier = overrides.get("approved_tier", TIER_NBE)
        ctx["approved_tier"] = tier
        ctx["gap"] = get_success_data(
            api.decide_gap_tier(
                ctx["gap_id"],
                f.tier_decision_payload(
                    approved_tier=tier, **_sub(overrides, "tier_decision")
                ),
                DIRECTOR_HEADERS,
            )
        )

    if upto >= 5:
        ctx["supplier"] = get_success_data(
            api.create_supplier(
                f.supplier_payload(ctx["program_id"], **_sub(overrides, "supplier")),
                SOURCING_HEADERS,
            )
        )
        ctx["supplier_id"] = ctx["supplier"]["id"]
        ctx["supplier_headers"] = make_supplier_headers(ctx["supplier_id"])

    if upto >= 6:
        ctx["plant_line"] = get_success_data(
            api.create_plant_line(
                f.plant_line_payload(
                    ctx["supplier_id"], **_sub(overrides, "plant_line")
                ),
                SOURCING_HEADERS,
            )
        )
        ctx["plant_line_id"] = ctx["plant_line"]["id"]

    if upto >= 7:
        ctx["audit"] = get_success_data(
            api.create_plant_audit(
                f.plant_audit_payload(ctx["supplier_id"], **_sub(overrides, "audit")),
                QUALITY_HEADERS,
            )
        )
        ctx["audit_id"] = ctx["audit"]["id"]

    if upto >= 8:
        finalize_factory = overrides.get(
            "audit_finalize_factory", f.audit_finalize_payload
        )
        ctx["audit"] = get_success_data(
            api.finalize_plant_audit(
                ctx["audit_id"],
                finalize_factory(**_sub(overrides, "audit_finalize")),
                QUALITY_HEADERS,
            )
        )

    if upto >= 9:
        decision = overrides.get("qualification_decision", DECISION_QUALIFY)
        ctx["supplier"] = get_success_data(
            api.decide_qualification(
                ctx["supplier_id"],
                f.qualification_payload(
                    decision,
                    basis_audit_id=ctx["audit_id"],
                    **_sub(overrides, "qualification"),
                ),
                DIRECTOR_HEADERS,
            )
        )

    if upto >= 10:
        item_overrides = _sub(overrides, "item")
        item_overrides.setdefault("tier", ctx.get("approved_tier", TIER_NBE))
        ctx["item"] = get_success_data(
            api.create_item(
                f.item_payload(ctx["gap_id"], **item_overrides), SOURCING_HEADERS
            )
        )
        ctx["item_id"] = ctx["item"]["id"]

    if upto >= 11:
        quoting_headers = (
            SOURCING_HEADERS
            if overrides.get("cost_model_by_sourcing")
            else ctx["supplier_headers"]
        )
        ctx["cost_model"] = get_success_data(
            api.create_cost_model(
                f.cost_model_payload(
                    ctx["item_id"],
                    ctx["supplier_id"],
                    **_sub(overrides, "cost_model"),
                ),
                quoting_headers,
            )
        )
        ctx["cost_model_id"] = ctx["cost_model"]["id"]

    if upto >= 12:
        ctx["cost_model"] = get_success_data(
            api.decide_cost_model(
                ctx["cost_model_id"],
                f.cost_model_decision_payload(DECISION_ACCEPT),
                SOURCING_HEADERS,
            )
        )

    if upto >= 13:
        ctx["bench_study"] = get_success_data(
            api.create_study(
                f.bench_top_payload(ctx["item_id"], **_sub(overrides, "bench_study")),
                QUALITY_HEADERS,
            )
        )
        ctx["bench_study_id"] = ctx["bench_study"]["id"]

    if upto >= 14:
        ctx["bench_study"] = get_success_data(
            api.finalize_study(ctx["bench_study_id"], QUALITY_HEADERS)
        )

    if upto >= 15:
        ctx["panel_study"] = get_success_data(
            api.create_study(
                f.consumer_panel_payload(
                    ctx["item_id"], **_sub(overrides, "panel_study")
                ),
                QUALITY_HEADERS,
            )
        )
        ctx["panel_study_id"] = ctx["panel_study"]["id"]

    if upto >= 16:
        ctx["panel_study"] = get_success_data(
            api.finalize_study(ctx["panel_study_id"], QUALITY_HEADERS)
        )

    if upto >= 17:
        ctx["artwork_round"] = get_success_data(
            api.create_artwork_round(
                f.artwork_round_payload(
                    ctx["item_id"], **_sub(overrides, "artwork_round")
                ),
                DESIGNER_HEADERS,
            )
        )
        ctx["artwork_round_id"] = ctx["artwork_round"]["id"]

    if upto >= 18:
        ctx["artwork_round"] = get_success_data(
            api.generate_nutrition_panel(
                ctx["artwork_round_id"],
                DESIGNER_HEADERS,
                _sub(overrides, "nutrition_panel") or None,
            )
        )

    if upto >= 19:
        claim_factory = overrides.get("claim_factory", f.label_claim_payload)
        ctx["claim"] = get_success_data(
            api.create_label_claim(
                claim_factory(ctx["artwork_round_id"], **_sub(overrides, "claim")),
                DESIGNER_HEADERS,
            )
        )
        ctx["claim_id"] = ctx["claim"]["id"]

    if upto >= 20:
        ctx["claim"] = get_success_data(
            api.review_label_claim(
                ctx["claim_id"], f.review_payload(REVIEW_APPROVE), REGULATORY_HEADERS
            )
        )

    if upto >= 21:
        ctx["artwork_round"] = get_success_data(
            api.submit_artwork_round(ctx["artwork_round_id"], DESIGNER_HEADERS)
        )

    if upto >= 22:
        ctx["artwork_round"] = get_success_data(
            api.review_artwork_round(
                ctx["artwork_round_id"],
                f.review_payload(REVIEW_APPROVE),
                REGULATORY_HEADERS,
            )
        )

    if upto >= 23:
        ctx["item"] = read_item(api, ctx["item_id"])
        ctx["item_version"] = ctx["item"]["version"]

    if upto >= 24:
        spec_overrides = _sub(overrides, "specification")
        ctx["specification"] = get_success_data(
            api.create_specification(
                f.specification_payload(
                    ctx["item_id"],
                    ctx["cost_model_id"],
                    ctx["artwork_round_id"],
                    ctx["item_version"],
                    **spec_overrides,
                ),
                SOURCING_HEADERS,
            )
        )
        ctx["specification_id"] = ctx["specification"]["id"]

    if upto >= 25:
        ctx["specification"] = get_success_data(
            api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
        )

    if upto >= 26:
        ctx["run"] = get_success_data(
            api.create_production_run(
                f.production_run_payload(
                    ctx["item_id"],
                    ctx["specification_id"],
                    ctx["plant_line_id"],
                    **_sub(overrides, "run"),
                ),
                SOURCING_HEADERS,
            )
        )
        ctx["run_id"] = ctx["run"]["id"]

    if upto >= 27:
        # A different director approves, because the user who locked the
        # specification may not approve its runs.
        ctx["run"] = get_success_data(
            api.approve_production_run(ctx["run_id"], DIRECTOR_2_HEADERS)
        )

    if upto >= 28:
        advance_clock(api, overrides.get("complete_clock", "2026-09-07T19:00:00Z"))

    if upto >= 29:
        ctx["run"] = get_success_data(
            api.complete_production_run(
                ctx["run_id"],
                f.run_complete_payload(**_sub(overrides, "run_complete")),
                QUALITY_HEADERS,
            )
        )

    if upto >= 30:
        ctx["item"] = get_success_data(api.launch_item(ctx["item_id"], DIRECTOR_HEADERS))

    if upto >= 31:
        ctx["cost_model"] = read_cost_model(api, ctx["cost_model_id"])
        ctx["cost_model_version"] = ctx["cost_model"]["version"]

    return ctx


# --- Side pathways --------------------------------------------------------


def add_second_gap(api, program_id, factory=None, **overrides):
    """Open an additional gap under the same program and take it to TIER_APPROVED."""
    factory = factory or f.single_slot_gap_payload
    tier = overrides.pop("approved_tier", TIER_NBE)
    gap = get_success_data(api.create_gap(factory(program_id, **overrides), SOURCING_HEADERS))
    gap = get_success_data(api.analyze_gap(gap["id"], {}, SOURCING_HEADERS))
    gap = get_success_data(
        api.decide_gap_tier(
            gap["id"], f.tier_decision_payload(approved_tier=tier), DIRECTOR_HEADERS
        )
    )
    return gap


def add_second_supplier(api, program_id, **overrides):
    """Register another supplier under the same program; it opens as PROSPECT."""
    payload = f.supplier_payload(program_id, **overrides)
    payload.setdefault("legal_name", "Ridgeway Snack Co")
    return get_success_data(api.create_supplier(payload, SOURCING_HEADERS))


def qualify_supplier(api, supplier_id, decision=DECISION_QUALIFY, **audit_overrides):
    """Run a capability audit for a supplier and take the qualification decision."""
    finalize_factory = audit_overrides.pop("finalize_factory", f.audit_finalize_payload)
    audit = get_success_data(
        api.create_plant_audit(
            f.plant_audit_payload(supplier_id, **audit_overrides), QUALITY_HEADERS
        )
    )
    audit = get_success_data(
        api.finalize_plant_audit(audit["id"], finalize_factory(), QUALITY_HEADERS)
    )
    supplier = get_success_data(
        api.decide_qualification(
            supplier_id,
            f.qualification_payload(decision, basis_audit_id=audit["id"]),
            DIRECTOR_HEADERS,
        )
    )
    return {"audit": audit, "audit_id": audit["id"], "supplier": supplier}


def add_second_item(api, ctx, **overrides):
    """Add a second item to the chain's gap and award it its own cost model."""
    item = get_success_data(
        api.create_item(
            f.second_item_payload(ctx["gap_id"], **_sub(overrides, "item")),
            SOURCING_HEADERS,
        )
    )
    cost_model = get_success_data(
        api.create_cost_model(
            f.second_supplier_cost_model_payload(
                item["id"], ctx["supplier_id"], **_sub(overrides, "cost_model")
            ),
            make_supplier_headers(ctx["supplier_id"]),
        )
    )
    cost_model = get_success_data(
        api.decide_cost_model(
            cost_model["id"], f.cost_model_decision_payload(DECISION_ACCEPT), SOURCING_HEADERS
        )
    )
    return {
        "item": get_success_data(api.get_item(item["id"], SOURCING_HEADERS)),
        "item_id": item["id"],
        "cost_model": cost_model,
        "cost_model_id": cost_model["id"],
    }


def add_rival_cost_model(api, ctx, **overrides):
    """Submit a competing SUBMITTED quote for the chain's item."""
    return get_success_data(
        api.create_cost_model(
            f.rival_cost_model_payload(ctx["item_id"], ctx["supplier_id"], **overrides),
            make_supplier_headers(ctx["supplier_id"]),
        )
    )


def add_complaint(api, item_id, factory=None, **overrides):
    """Record one complaint, which recomputes the item's trend on the spot."""
    factory = factory or f.complaint_payload
    return get_success_data(
        api.create_complaint(factory(item_id, **overrides), QUALITY_HEADERS)
    )


def add_complaints(api, item_id, count, factory=None, lot_prefix="PL-0801"):
    """Record ``count`` complaints, each with a distinct lot code."""
    recorded = []
    for index in range(count):
        recorded.append(
            add_complaint(
                api,
                item_id,
                factory=factory,
                lot_code=f"{lot_prefix}-{index + 1}",
            )
        )
    return recorded


def open_change_request(api, ctx, factory=None, **overrides):
    """Read the awarded cost model's version, then open a change request on it."""
    factory = factory or f.change_request_payload
    cost_model = read_cost_model(api, ctx["cost_model_id"])
    request = get_success_data(
        api.create_change_request(
            factory(
                ctx["item_id"],
                ctx["cost_model_id"],
                cost_model["version"],
                **overrides,
            ),
            make_supplier_headers(ctx["supplier_id"]),
        )
    )
    return request


def suspend_supplier(api, supplier_id):
    """Send a qualified supplier to SUSPENDED."""
    return get_success_data(
        api.decide_qualification(
            supplier_id, f.qualification_payload(DECISION_SUSPEND), DIRECTOR_HEADERS
        )
    )


def add_ongoing_audit(api, supplier_id, window_start, window_end):
    """Schedule an ongoing-quality audit over an explicit window."""
    return get_success_data(
        api.create_plant_audit(
            f.plant_audit_payload(
                supplier_id,
                audit_type=AUDIT_ONGOING_QUALITY,
                window_start=window_start,
                window_end=window_end,
            ),
            QUALITY_HEADERS,
        )
    )


def add_ongoing_run(api, ctx, window_start, window_end, planned_units=6000, **overrides):
    """Schedule an additional ongoing run on the chain's line."""
    return get_success_data(
        api.create_production_run(
            f.production_run_payload(
                ctx["item_id"],
                ctx["specification_id"],
                ctx["plant_line_id"],
                run_type=RUN_ONGOING,
                window_start=window_start,
                window_end=window_end,
                planned_units=planned_units,
                **overrides,
            ),
            SOURCING_HEADERS,
        )
    )


def start_relaunch(api, program_id):
    return get_success_data(
        api.program_lifecycle(
            program_id, f.program_lifecycle_payload(ACTION_START_RELAUNCH), DIRECTOR_HEADERS
        )
    )


def complete_relaunch(api, program_id):
    return get_success_data(
        api.program_lifecycle(
            program_id,
            f.program_lifecycle_payload(ACTION_COMPLETE_RELAUNCH),
            DIRECTOR_HEADERS,
        )
    )


def close_program(api, program_id):
    return get_success_data(
        api.program_lifecycle(
            program_id, f.program_lifecycle_payload(ACTION_CLOSE), DIRECTOR_HEADERS
        )
    )


def rationalize(api, item_id, disposition=DISPOSITION_DISCONTINUE, replacement_item_id=None):
    payload = f.rationalize_payload(disposition)
    if replacement_item_id is not None:
        payload["replacement_item_id"] = replacement_item_id
    return get_success_data(api.rationalize_item(item_id, payload, DIRECTOR_HEADERS))


# --- Pytest fixtures ------------------------------------------------------
# The database is empty at the start of every test, so each fixture is
# function-scoped and rebuilds its state through the public API.


@pytest.fixture(scope="session")
def api():
    """The shared endpoint client."""
    return api_client


@pytest.fixture
def program(api):
    """An ACTIVE brand program with all four ledger counters at zero."""
    return build_chain(api, upto=1)


@pytest.fixture
def draft_gap(api):
    """A newly opened gap, still DRAFT and unscored."""
    return build_chain(api, upto=2)


@pytest.fixture
def analyzed_gap(api):
    """A scored gap in ANALYZED with a recommended tier but no approved tier."""
    return build_chain(api, upto=3)


@pytest.fixture
def tier_approved_gap(api):
    """A gap whose NBE tier has been approved, so items may be created."""
    return build_chain(api, upto=4)


@pytest.fixture
def prospect_supplier(api):
    """A registered supplier still in PROSPECT with a plant line."""
    return build_chain(api, upto=6)


@pytest.fixture
def finalized_audit(api):
    """A finalized capability audit whose result is PASS at 91.0 percent yield."""
    return build_chain(api, upto=8)


@pytest.fixture
def qualified_supplier(api):
    """A QUALIFIED supplier standing on a PASS capability audit."""
    return build_chain(api, upto=9)


@pytest.fixture
def conditional_supplier(api):
    """A supplier qualified only CONDITIONAL, on a CONDITIONAL audit result."""
    return build_chain(
        api,
        upto=9,
        audit_finalize_factory=f.conditional_audit_finalize_payload,
        qualification_decision=DECISION_CONDITIONAL,
    )


@pytest.fixture
def concept_item(api):
    """An item in CONCEPT and GREEN holding one shelf slot."""
    return build_chain(api, upto=10)


@pytest.fixture
def submitted_cost_model(api):
    """A SUBMITTED quote against a CONCEPT item."""
    return build_chain(api, upto=11)


@pytest.fixture
def sourced_item(api):
    """An ACCEPTED quote that awarded the supplier and moved the item to SOURCED."""
    return build_chain(api, upto=12)


@pytest.fixture
def benchmarked_item(api):
    """Both studies finalized, so the item has cleared its NBE benchmark gate."""
    return build_chain(api, upto=16)


@pytest.fixture
def draft_artwork_round(api):
    """A DRAFT artwork round whose panel has not been generated."""
    return build_chain(api, upto=17)


@pytest.fixture
def valid_panel_round(api):
    """An artwork round whose nutrition panel is generated and VALID."""
    return build_chain(api, upto=18)


@pytest.fixture
def approved_claim_round(api):
    """A DRAFT round carrying one APPROVED claim, ready to submit."""
    return build_chain(api, upto=20)


@pytest.fixture
def in_review_round(api):
    """An artwork round submitted and awaiting regulatory review."""
    return build_chain(api, upto=21)


@pytest.fixture
def packaging_approved_item(api):
    """An approved artwork round has advanced the item to PACKAGING_APPROVED."""
    return build_chain(api, upto=23)


@pytest.fixture
def draft_specification(api):
    """A DRAFT specification pinning the accepted quote and approved round."""
    return build_chain(api, upto=24)


@pytest.fixture
def locked_specification(api):
    """A LOCKED specification: slotting fee committed, retail price written."""
    return build_chain(api, upto=25)


@pytest.fixture
def scheduled_run(api):
    """A SCHEDULED first-production run with its tooling committed."""
    return build_chain(api, upto=26)


@pytest.fixture
def approved_run(api):
    """An APPROVED first-production run, approved by a second director."""
    return build_chain(api, upto=27)


@pytest.fixture
def completed_run(api):
    """A COMPLETED on-time first-production run, clock past the window end."""
    return build_chain(api, upto=29)


@pytest.fixture
def launched_item(api):
    """A LAUNCHED item standing on a completed first-production run."""
    return build_chain(api, upto=30)


@pytest.fixture
def full_chain(api):
    """The whole pathway plus the awarded cost model's current version."""
    return build_chain(api, upto=31)
