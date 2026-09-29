"""
Composite fixtures for the Label Distribution Recoupment API.

The runner restarts the server before every individual test, so every test opens
against an empty database. Everything a test needs must therefore be built here
from scratch, and only through endpoints the PRD declares.

The module is organised in five tiers:

  Tier 1  ``mk_*`` / ``do_*`` / ``read_*`` - one call each, asserted 2xx.
  Tier 2  ``given_distributor_and_artist``, ``given_draft_deal``,
          ``given_executed_deal``, ``given_released_catalog`` - the entity
          hierarchy down to a marketable release.
  Tier 3  ``given_active_agreement``, ``given_rate_cards``,
          ``given_submitted_report``, ``given_accepted_report``,
          ``given_shipped_run``, ``given_settled_spend``,
          ``given_prepared_statement``, ``given_issued_statement``,
          ``given_finalized_statement`` - full-lifecycle shortcuts.
  Tier 4  ``given_recouped_deal``, ``given_run_with_returns``,
          ``given_liquidated_run`` - accumulation and threshold targeting.
  Tier 5  ``given_terminated_deal``, ``given_expired_deal``,
          ``given_post_term_collection_deal``, ``given_closed_deal``,
          ``given_superseded_agreement`` - finalization and terminal states.

Tier 2 upward all speak the same **ctx** dictionary. A composite receives a ctx,
adds its own keys and returns the same dict, so chains read naturally:

    ctx = given_released_catalog(api)
    ctx = given_active_agreement(api, ctx)
    ctx = given_accepted_report(api, ctx)

Standard ctx keys: ``distributor``/``dist_id``, ``artist``/``artist_id``,
``deal``/``deal_id``, ``release``/``release_id``, ``releases`` (list),
``agreement``/``agreement_id``, ``agreements``, ``rate_cards``,
``report``/``report_id``, ``lines``, ``run``/``run_id``, ``spend``/``spend_id``,
``statement``/``statement_id``, ``partner_headers``, ``artist_headers``.

Each composite is one phase of the spine and never re-runs a phase an earlier
call already completed, so reusing a helper on a second entity cannot invalidate
the precondition the first one established.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    AMENDMENT_DECISION_ACCEPT,
    BASIS_VARIANT_FINAL,
    DEFAULT_CLOCK_INSTANT,
    RESOLUTION_DENIED,
    SPEND_DECISION_APPROVE,
    TIER_PREMIUM,
)
from .test_users import (
    ANALYST,
    BIZ_AFFAIRS,
    BIZ_AFFAIRS_2,
    LABEL_ADMIN,
    LABEL_ADMIN_2,
    USER_ANALYST,
    USER_BIZ_AFFAIRS,
    USER_BIZ_AFFAIRS_2,
    make_artist_headers,
    make_partner_headers,
)

# ===========================================================================
# Tier 1 - single-call primitives. Each asserts a 2xx and returns `data`.
# ===========================================================================


def do_set_clock(api, to_iso8601: str, headers=LABEL_ADMIN) -> dict:
    """PRD 2.5: LabelAdmin-only clock control. Sends a full instant."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), headers))


def mk_distributor(api, headers=LABEL_ADMIN, **kw) -> dict:
    return get_success_data(api.create_distributor(f.distributor_payload(**kw), headers))


def mk_artist(api, headers=LABEL_ADMIN, **kw) -> dict:
    return get_success_data(api.create_artist(f.artist_payload(**kw), headers))


def mk_deal(api, distributor_id: str, headers=LABEL_ADMIN, **kw) -> dict:
    return get_success_data(
        api.create_deal(f.deal_payload(distributor_id, **kw), headers)
    )


def mk_release(
    api, deal_id: str, primary_artist_id: str, headers=LABEL_ADMIN, **kw
) -> dict:
    return get_success_data(
        api.create_release(f.release_payload(deal_id, primary_artist_id, **kw), headers)
    )


def do_execute_deal(
    api, deal_id: str, headers=LABEL_ADMIN, advance_payment_reference="WIRE-2026-0031"
) -> dict:
    return get_success_data(
        api.execute_deal(
            deal_id, f.execute_payload(advance_payment_reference), headers
        )
    )


def do_release_to_market(
    api, release_id: str, actual_release_date: str = "2026-02-01", headers=LABEL_ADMIN
) -> dict:
    return get_success_data(
        api.release_to_market(
            release_id, f.release_to_market_payload(actual_release_date), headers
        )
    )


def mk_rate_card(api, headers=LABEL_ADMIN, **kw) -> dict:
    return get_success_data(api.create_rate_card(f.rate_card_payload(**kw), headers))


def mk_agreement(
    api, artist_id: str, release_id: str, headers=LABEL_ADMIN, **kw
) -> dict:
    return get_success_data(
        api.create_agreement(f.agreement_payload(artist_id, release_id, **kw), headers)
    )


def do_activate_agreement(api, agreement_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.activate_agreement(agreement_id, headers))


def do_propose_amendment(
    api,
    agreement_id: str,
    proposed_royalty_rate_pct,
    proposed_advance_amount_cents: int,
    headers=LABEL_ADMIN,
) -> dict:
    return get_success_data(
        api.propose_amendment(
            agreement_id,
            f.propose_amendment_payload(
                proposed_royalty_rate_pct, proposed_advance_amount_cents
            ),
            headers,
        )
    )


def do_resolve_amendment(
    api, agreement_id: str, decision: str = AMENDMENT_DECISION_ACCEPT, headers=BIZ_AFFAIRS
) -> dict:
    return get_success_data(
        api.resolve_amendment(
            agreement_id, f.resolve_amendment_payload(decision), headers
        )
    )


def mk_spend(api, release_id: str, headers=LABEL_ADMIN, **kw) -> dict:
    return get_success_data(
        api.create_spend(f.spend_payload(release_id, **kw), headers)
    )


def do_submit_spend(api, spend_id: str, headers=LABEL_ADMIN, **kw) -> dict:
    return get_success_data(
        api.submit_spend(spend_id, headers, f.submit_spend_payload(**kw))
    )


def do_decide_spend(
    api,
    spend_id: str,
    decision: str = SPEND_DECISION_APPROVE,
    headers=BIZ_AFFAIRS,
    **kw
) -> dict:
    return get_success_data(
        api.decide_spend(spend_id, f.decide_spend_payload(decision, **kw), headers)
    )


def do_settle_spend(
    api, spend_id: str, settled_amount_cents: int, headers=LABEL_ADMIN
) -> dict:
    return get_success_data(
        api.settle_spend(
            spend_id, f.settle_spend_payload(settled_amount_cents), headers
        )
    )


def mk_report(api, deal_id: str, partner_headers, **kw) -> dict:
    return get_success_data(
        api.create_report(f.report_payload(deal_id, **kw), partner_headers)
    )


def mk_line(api, report_id: str, release_id: str, partner_headers, **kw) -> dict:
    return get_success_data(
        api.append_line(report_id, f.line_payload(release_id, **kw), partner_headers)
    )


def do_submit_report(api, report_id: str, partner_headers) -> dict:
    return get_success_data(api.submit_report(report_id, partner_headers))


def do_accept_report(
    api, report_id: str, expected_deal_version: int, headers=ANALYST
) -> dict:
    return get_success_data(
        api.accept_report(
            report_id, f.accept_report_payload(expected_deal_version), headers
        )
    )


def do_dispute_report(
    api,
    report_id: str,
    expected_deal_version: int,
    dispute_reason: str,
    headers=ANALYST,
) -> dict:
    return get_success_data(
        api.dispute_report(
            report_id,
            f.dispute_report_payload(expected_deal_version, dispute_reason),
            headers,
        )
    )


def mk_run(api, release_id: str, distributor_id: str, headers=LABEL_ADMIN, **kw) -> dict:
    return get_success_data(
        api.create_run(f.run_payload(release_id, distributor_id, **kw), headers)
    )


def do_manufacture(
    api, run_id: str, units_manufactured: int, headers=LABEL_ADMIN
) -> dict:
    return get_success_data(
        api.manufacture_run(run_id, f.manufacture_payload(units_manufactured), headers)
    )


def do_ship(
    api,
    run_id: str,
    units_shipped: int,
    wholesale_unit_price_cents: int,
    partner_headers,
) -> dict:
    return get_success_data(
        api.ship_run(
            run_id,
            f.ship_payload(units_shipped, wholesale_unit_price_cents),
            partner_headers,
        )
    )


def do_record_returns(api, run_id: str, returned_units: int, partner_headers) -> dict:
    return get_success_data(
        api.record_returns(
            run_id, f.record_returns_payload(returned_units), partner_headers
        )
    )


def do_liquidate(
    api, run_id: str, expected_run_version: int, liquidation_pct, headers=ANALYST
) -> dict:
    return get_success_data(
        api.liquidate_reserve(
            run_id, f.liquidate_payload(expected_run_version, liquidation_pct), headers
        )
    )


def do_void_liquidation(
    api, run_id: str, expected_run_version: int, headers=ANALYST
) -> dict:
    return get_success_data(
        api.void_liquidation(
            run_id, f.void_liquidation_payload(expected_run_version), headers
        )
    )


def mk_statement(api, artist_agreement_id: str, headers=ANALYST, **kw) -> dict:
    return get_success_data(
        api.create_statement(f.statement_payload(artist_agreement_id, **kw), headers)
    )


def do_prepare_statement(api, statement_id: str, headers=ANALYST) -> dict:
    return get_success_data(api.prepare_statement(statement_id, headers))


def do_issue_statement(api, statement_id: str, headers=BIZ_AFFAIRS) -> dict:
    return get_success_data(api.issue_statement(statement_id, headers))


def do_object(
    api,
    statement_id: str,
    artist_headers,
    objection_reason_code: str,
    objection_disputed_amount_cents: int,
    objection_narrative: str,
) -> dict:
    return get_success_data(
        api.object_statement(
            statement_id,
            f.object_payload(
                objection_reason_code,
                objection_disputed_amount_cents,
                objection_narrative,
            ),
            artist_headers,
        )
    )


def do_resolve_objection(
    api,
    statement_id: str,
    resolution: str = RESOLUTION_DENIED,
    objection_adjustment_cents: Optional[int] = None,
    headers=BIZ_AFFAIRS,
) -> dict:
    return get_success_data(
        api.resolve_objection(
            statement_id,
            f.resolve_objection_payload(resolution, objection_adjustment_cents),
            headers,
        )
    )


def do_finalize_statement(api, statement_id: str, headers=BIZ_AFFAIRS) -> dict:
    return get_success_data(api.finalize_statement(statement_id, headers))


def do_request_audit(
    api,
    statement_id: str,
    artist_headers,
    audit_scope_period_start: str,
    audit_scope_period_end: str,
    auditor_name: str = "Harrow & Vance",
) -> dict:
    return get_success_data(
        api.request_audit(
            statement_id,
            f.request_audit_payload(
                audit_scope_period_start, audit_scope_period_end, auditor_name
            ),
            artist_headers,
        )
    )


def do_conclude_audit(
    api, statement_id: str, findings_adjustment_cents: int, headers=BIZ_AFFAIRS
) -> dict:
    return get_success_data(
        api.conclude_audit(
            statement_id,
            f.conclude_audit_payload(findings_adjustment_cents),
            headers,
        )
    )


def do_terminate_deal(api, deal_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.terminate_deal(deal_id, headers))


def do_expire_deal(api, deal_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.expire_deal(deal_id, headers))


def do_enter_post_term_collection(api, deal_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.enter_post_term_collection(deal_id, headers))


def do_close_deal(api, deal_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.close_deal(deal_id, headers))


# --- reads -----------------------------------------------------------------


def read_distributor(api, distributor_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_distributor(distributor_id, headers))


def read_artist(api, artist_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_artist(artist_id, headers))


def read_deal(api, deal_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_deal(deal_id, headers))


def read_release(api, release_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_release(release_id, headers))


def read_agreement(api, agreement_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_agreement(agreement_id, headers))


def read_spend(api, spend_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_spend(spend_id, headers))


def read_report(api, report_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_report(report_id, headers))


def read_run(api, run_id: str, headers=LABEL_ADMIN) -> dict:
    return get_success_data(api.get_run(run_id, headers))


def read_statement(api, statement_id: str, headers=ANALYST) -> dict:
    return get_success_data(api.get_statement(statement_id, headers))


def read_report_lines(api, report_id: str, headers=LABEL_ADMIN, **params) -> List[dict]:
    return get_success_data(api.list_report_lines(report_id, headers, params or None))


def read_release_lines(api, release_id: str, headers=LABEL_ADMIN, **params) -> List[dict]:
    return get_success_data(
        api.list_release_revenue_lines(release_id, headers, params or None)
    )


def read_recoupment_summary(
    api, deal_id: str, variant: Optional[str] = None, headers=ANALYST
) -> dict:
    return get_success_data(api.get_recoupment_summary(deal_id, headers, variant))


def deal_version(api, deal_id: str, headers=LABEL_ADMIN) -> int:
    """GET /distribution-deals/{id} is "the source of the version value echoed
    into expected_deal_version"."""
    return read_deal(api, deal_id, headers)["version"]


def run_version(api, run_id: str, headers=LABEL_ADMIN) -> int:
    """GET /physical-runs/{id} is "the source of the version value echoed into
    expected_run_version"."""
    return read_run(api, run_id, headers)["version"]


# ===========================================================================
# Tier 2 - entity hierarchy: counterparties -> deal -> catalog
# ===========================================================================


def given_distributor_and_artist(
    api,
    *,
    clock: Optional[str] = None,
    distributor_kw: Optional[Dict[str, Any]] = None,
    artist_kw: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Register the two outside parties. "Before anything can be accounted, the
    two outside parties must exist as records."

    ``clock`` sets the logical clock first; leave it None to run against the
    PRD's own starting instant of 2026-08-01T00:00:00Z.
    """
    if clock is not None:
        do_set_clock(api, clock)
    distributor = mk_distributor(api, **(distributor_kw or {}))
    artist = mk_artist(api, **(artist_kw or {}))
    return {
        "clock": clock or DEFAULT_CLOCK_INSTANT,
        "distributor": distributor,
        "dist_id": distributor["id"],
        "partner_headers": make_partner_headers(distributor["id"]),
        "artist": artist,
        "artist_id": artist["id"],
        "artist_headers": make_artist_headers(artist["id"]),
    }


def given_draft_deal(
    api,
    *,
    ctx: Optional[Dict[str, Any]] = None,
    clock: Optional[str] = None,
    distributor_kw: Optional[Dict[str, Any]] = None,
    artist_kw: Optional[Dict[str, Any]] = None,
    deal_kw: Optional[Dict[str, Any]] = None,
    releases: Optional[Sequence[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """A DRAFT deal that already carries its releases.

    "releases are registered against the draft before it is signed", because
    execution "must already carry at least one release whose status is PLANNED or
    RELEASED". ``releases`` is a sequence of ``release_payload`` kwargs; when it
    is None a single digital release is registered.
    """
    if ctx is None:
        ctx = given_distributor_and_artist(
            api, clock=clock, distributor_kw=distributor_kw, artist_kw=artist_kw
        )
    deal = mk_deal(api, ctx["dist_id"], **(deal_kw or {}))
    ctx["deal"] = deal
    ctx["deal_id"] = deal["id"]

    specs = list(releases) if releases is not None else [{}]
    made = [mk_release(api, deal["id"], ctx["artist_id"], **spec) for spec in specs]
    ctx["releases"] = made
    ctx["release"] = made[0]
    ctx["release_id"] = made[0]["id"]
    return ctx


def given_executed_deal(
    api,
    *,
    ctx: Optional[Dict[str, Any]] = None,
    clock: Optional[str] = None,
    distributor_kw: Optional[Dict[str, Any]] = None,
    artist_kw: Optional[Dict[str, Any]] = None,
    deal_kw: Optional[Dict[str, Any]] = None,
    releases: Optional[Sequence[Dict[str, Any]]] = None,
    advance_payment_reference: str = "WIRE-2026-0031"
) -> Dict[str, Any]:
    """DRAFT -> EXECUTED, leaving every release in PLANNED."""
    if ctx is None or "deal_id" not in ctx:
        ctx = given_draft_deal(
            api,
            ctx=ctx,
            clock=clock,
            distributor_kw=distributor_kw,
            artist_kw=artist_kw,
            deal_kw=deal_kw,
            releases=releases,
        )
    ctx["deal"] = do_execute_deal(
        api, ctx["deal_id"], advance_payment_reference=advance_payment_reference
    )
    return ctx


def given_released_catalog(
    api,
    *,
    ctx: Optional[Dict[str, Any]] = None,
    clock: Optional[str] = None,
    distributor_kw: Optional[Dict[str, Any]] = None,
    artist_kw: Optional[Dict[str, Any]] = None,
    deal_kw: Optional[Dict[str, Any]] = None,
    releases: Optional[Sequence[Dict[str, Any]]] = None,
    actual_release_date: str = "2026-02-01",
    release_indexes: Optional[Sequence[int]] = None,
    advance_payment_reference: str = "WIRE-2026-0031"
) -> Dict[str, Any]:
    """An EXECUTED deal whose releases have gone to market.

    ``release_indexes`` selects which of ``ctx["releases"]`` to promote; the
    default promotes every one of them. A release left out stays PLANNED, which
    is what the termination cascade's "every release still in PLANNED - one that
    never went to market - moves straight to REVERTED" arm needs.
    """
    ctx = given_executed_deal(
        api,
        ctx=ctx,
        clock=clock,
        distributor_kw=distributor_kw,
        artist_kw=artist_kw,
        deal_kw=deal_kw,
        releases=releases,
        advance_payment_reference=advance_payment_reference,
    )
    indexes = (
        list(release_indexes)
        if release_indexes is not None
        else list(range(len(ctx["releases"])))
    )
    for index in indexes:
        ctx["releases"][index] = do_release_to_market(
            api, ctx["releases"][index]["id"], actual_release_date
        )
    ctx["release"] = ctx["releases"][0]
    ctx["release_id"] = ctx["releases"][0]["id"]
    ctx["deal"] = read_deal(api, ctx["deal_id"])
    return ctx


# ===========================================================================
# Tier 3 - full-lifecycle shortcuts
# ===========================================================================


def given_active_agreement(
    api,
    ctx: Dict[str, Any],
    *,
    release_index: int = 0,
    artist_id: Optional[str] = None,
    agreement_kw: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Draft one agreement and activate it, seeding the artist-side ledger."""
    release = ctx["releases"][release_index]
    agreement = mk_agreement(
        api,
        artist_id or ctx["artist_id"],
        release["id"],
        **(agreement_kw or {})
    )
    agreement = do_activate_agreement(api, agreement["id"])
    ctx.setdefault("agreements", []).append(agreement)
    ctx["agreement"] = agreement
    ctx["agreement_id"] = agreement["id"]
    return ctx


def given_rate_cards(
    api, ctx: Dict[str, Any], cards: Optional[Sequence[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Publish the rate book the report submission will price against.

    ``cards`` is a sequence of ``rate_card_payload`` kwargs. The default
    publishes one open-ended STRM/US/PREMIUM card at 4,000 micros effective from
    the start of 2026.
    """
    specs = list(cards) if cards is not None else [{}]
    made = [mk_rate_card(api, **spec) for spec in specs]
    ctx.setdefault("rate_cards", []).extend(made)
    return ctx


def given_submitted_report(
    api,
    ctx: Dict[str, Any],
    *,
    report_kw: Optional[Dict[str, Any]] = None,
    lines: Optional[Sequence[Dict[str, Any]]] = None,
    cards: Optional[Sequence[Dict[str, Any]]] = None,
    publish_cards: bool = True
) -> Dict[str, Any]:
    """Open a report, append its lines and submit it, which is the pricing event.

    ``lines`` is a sequence of dicts; each may carry ``release_index`` (default 0)
    plus any ``line_payload`` kwargs. Set ``publish_cards=False`` when the rate
    book has already been published by an earlier call.
    """
    if publish_cards:
        given_rate_cards(api, ctx, cards)

    report = mk_report(api, ctx["deal_id"], ctx["partner_headers"], **(report_kw or {}))
    specs = list(lines) if lines is not None else [{}]
    made_lines = []
    for spec in specs:
        spec = dict(spec)
        index = spec.pop("release_index", 0)
        made_lines.append(
            mk_line(
                api,
                report["id"],
                ctx["releases"][index]["id"],
                ctx["partner_headers"],
                **spec
            )
        )
    report = do_submit_report(api, report["id"], ctx["partner_headers"])
    ctx.setdefault("reports", []).append(report)
    ctx["report"] = report
    ctx["report_id"] = report["id"]
    ctx["lines"] = made_lines
    return ctx


def given_accepted_report(
    api,
    ctx: Dict[str, Any],
    *,
    report_kw: Optional[Dict[str, Any]] = None,
    lines: Optional[Sequence[Dict[str, Any]]] = None,
    cards: Optional[Sequence[Dict[str, Any]]] = None,
    publish_cards: bool = True,
    accept_headers=ANALYST
) -> Dict[str, Any]:
    """Everything ``given_submitted_report`` does, then acceptance - which runs
    the five-hop advance cascade. The deal version is read immediately before the
    accept so the echo is always fresh."""
    if "report_id" not in ctx or report_kw is not None or lines is not None:
        ctx = given_submitted_report(
            api,
            ctx,
            report_kw=report_kw,
            lines=lines,
            cards=cards,
            publish_cards=publish_cards,
        )
    version = deal_version(api, ctx["deal_id"])
    ctx["report"] = do_accept_report(
        api, ctx["report_id"], version, headers=accept_headers
    )
    ctx["deal"] = read_deal(api, ctx["deal_id"])
    return ctx


def given_shipped_run(
    api,
    ctx: Dict[str, Any],
    *,
    release_index: int = 0,
    run_kw: Optional[Dict[str, Any]] = None,
    units_manufactured: int = 1200,
    units_shipped: int = 1000,
    wholesale_unit_price_cents: int = 900,
    returned_units: Optional[int] = None
) -> Dict[str, Any]:
    """Plan, manufacture and ship a physical run, optionally recording returns.

    The default 1,200 manufactured against 1,000 shipped satisfies the inventory
    obligation: 200 retained clears the 50-unit floor.
    """
    release = ctx["releases"][release_index]
    run = mk_run(api, release["id"], ctx["dist_id"], **(run_kw or {}))
    do_manufacture(api, run["id"], units_manufactured)
    run = do_ship(
        api,
        run["id"],
        units_shipped,
        wholesale_unit_price_cents,
        ctx["partner_headers"],
    )
    if returned_units is not None:
        run = do_record_returns(api, run["id"], returned_units, ctx["partner_headers"])
    ctx.setdefault("runs", []).append(run)
    ctx["run"] = run
    ctx["run_id"] = run["id"]
    return ctx


def given_settled_spend(
    api,
    ctx: Dict[str, Any],
    *,
    release_index: int = 0,
    spend_kw: Optional[Dict[str, Any]] = None,
    settled_amount_cents: Optional[int] = None,
    stop_after: str = "SETTLED"
) -> Dict[str, Any]:
    """Walk a marketing spend DRAFT -> SUBMITTED -> APPROVED -> SETTLED.

    ``stop_after`` may be ``"DRAFT"``, ``"SUBMITTED"``, ``"APPROVED"`` or
    ``"SETTLED"``. The requester is label-admin-01 and the decider is
    label-admin-02 acting as BusinessAffairs, so segregation of duties is
    satisfied ("the operator who asked for the money cannot be the one who grants
    it").
    """
    release = ctx["releases"][release_index]
    spend = mk_spend(api, release["id"], **(spend_kw or {}))
    if stop_after != "DRAFT":
        spend = do_submit_spend(api, spend["id"], headers=LABEL_ADMIN)
    if stop_after in ("APPROVED", "SETTLED"):
        spend = do_decide_spend(
            api, spend["id"], SPEND_DECISION_APPROVE, headers=BIZ_AFFAIRS
        )
    if stop_after == "SETTLED":
        amount = (
            settled_amount_cents
            if settled_amount_cents is not None
            else spend["amount_cents"]
        )
        spend = do_settle_spend(api, spend["id"], amount)
    ctx.setdefault("spends", []).append(spend)
    ctx["spend"] = spend
    ctx["spend_id"] = spend["id"]
    return ctx


def given_prepared_statement(
    api,
    ctx: Dict[str, Any],
    *,
    statement_kw: Optional[Dict[str, Any]] = None,
    prepare_headers=ANALYST
) -> Dict[str, Any]:
    """Open a statement and prepare it, which runs the marketing cap and the
    full net-payable waterfall."""
    statement = mk_statement(api, ctx["agreement_id"], **(statement_kw or {}))
    statement = do_prepare_statement(api, statement["id"], headers=prepare_headers)
    ctx.setdefault("statements", []).append(statement)
    ctx["statement"] = statement
    ctx["statement_id"] = statement["id"]
    return ctx


def given_issued_statement(
    api,
    ctx: Dict[str, Any],
    *,
    statement_kw: Optional[Dict[str, Any]] = None,
    prepare_headers=ANALYST,
    issue_headers=BIZ_AFFAIRS
) -> Dict[str, Any]:
    """A FINAL statement published to the artist, opening the objection window.

    The preparer is analyst-01 and the issuer is biz-affairs-01 so that "whoever
    computed the statement may not publish it" is satisfied.
    """
    spec = dict(statement_kw or {})
    spec.setdefault("basis_variant", BASIS_VARIANT_FINAL)
    ctx = given_prepared_statement(
        api, ctx, statement_kw=spec, prepare_headers=prepare_headers
    )
    ctx["statement"] = do_issue_statement(
        api, ctx["statement_id"], headers=issue_headers
    )
    return ctx


def given_finalized_statement(
    api,
    ctx: Dict[str, Any],
    *,
    statement_kw: Optional[Dict[str, Any]] = None,
    prepare_headers=ANALYST,
    issue_headers=BIZ_AFFAIRS,
    finalize_clock: Optional[str] = None,
    finalize_headers=BIZ_AFFAIRS
) -> Dict[str, Any]:
    """ISSUED -> FINALIZED, the only transition that debits the artist ledgers.

    Finalization "requires the logical clock to be strictly past
    objection_deadline", so pass ``finalize_clock`` as an instant beyond the
    deadline the issue stamped.
    """
    ctx = given_issued_statement(
        api,
        ctx,
        statement_kw=statement_kw,
        prepare_headers=prepare_headers,
        issue_headers=issue_headers,
    )
    if finalize_clock is not None:
        do_set_clock(api, finalize_clock)
    ctx["statement"] = do_finalize_statement(
        api, ctx["statement_id"], headers=finalize_headers
    )
    return ctx


# ===========================================================================
# Tier 4 - accumulation and threshold targeting
# ===========================================================================


def given_recouped_deal(
    api,
    ctx: Dict[str, Any],
    *,
    stream_count: int = 250000,
    report_kw: Optional[Dict[str, Any]] = None,
    cards: Optional[Sequence[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Accept one report large enough to clear the whole advance, so that
    "when the recomputation leaves unrecouped_advance_cents at exactly 0, the
    deal's recoupment_status flips UNRECOUPED -> RECOUPED" has fired.

    Caller sizes ``stream_count`` against the deal's ``advance_amount_cents``;
    the helper does not guess.
    """
    return given_accepted_report(
        api,
        ctx,
        report_kw=report_kw,
        lines=[{"stream_count": stream_count, "tier": TIER_PREMIUM}],
        cards=cards,
    )


def given_run_with_returns(
    api,
    ctx: Dict[str, Any],
    *,
    release_index: int = 0,
    run_kw: Optional[Dict[str, Any]] = None,
    units_manufactured: int = 1200,
    units_shipped: int = 1000,
    wholesale_unit_price_cents: int = 900,
    returned_units: int = 250
) -> Dict[str, Any]:
    """A SHIPPED run carrying a chosen cumulative returns figure, which is how a
    test lands the run on a specific escalation tier: "a returns_rate of 0.2500
    or above lifts the baseline by 0.1500, otherwise a returns_rate of 0.1000 or
    above lifts it by 0.0500"."""
    return given_shipped_run(
        api,
        ctx,
        release_index=release_index,
        run_kw=run_kw,
        units_manufactured=units_manufactured,
        units_shipped=units_shipped,
        wholesale_unit_price_cents=wholesale_unit_price_cents,
        returned_units=returned_units,
    )


def given_liquidated_run(
    api,
    ctx: Dict[str, Any],
    *,
    release_index: int = 0,
    run_kw: Optional[Dict[str, Any]] = None,
    units_manufactured: int = 1200,
    units_shipped: int = 1000,
    wholesale_unit_price_cents: int = 900,
    returned_units: Optional[int] = None,
    liquidation_pct: Any = "0.4000"
) -> Dict[str, Any]:
    """A SHIPPED run with part of its reserve released. The version echo is read
    immediately before the liquidation so it is never stale."""
    ctx = given_shipped_run(
        api,
        ctx,
        release_index=release_index,
        run_kw=run_kw,
        units_manufactured=units_manufactured,
        units_shipped=units_shipped,
        wholesale_unit_price_cents=wholesale_unit_price_cents,
        returned_units=returned_units,
    )
    version = run_version(api, ctx["run_id"])
    ctx["run"] = do_liquidate(api, ctx["run_id"], version, liquidation_pct)
    return ctx


# ===========================================================================
# Tier 5 - finalization and terminal states
# ===========================================================================


def given_terminated_deal(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """The for-cause fork EXECUTED -> TERMINATION_NOTICE, which runs the
    release / agreement / statement three-hop cascade."""
    ctx["deal"] = do_terminate_deal(api, ctx["deal_id"])
    return ctx


def given_expired_deal(
    api, ctx: Dict[str, Any], *, clock_after_term: Optional[str] = None
) -> Dict[str, Any]:
    """The natural-expiry fork EXECUTED -> EXPIRED, which "may only be taken once
    the term has actually run out: the logical clock's calendar date must be
    strictly after term_end_date"."""
    if clock_after_term is not None:
        do_set_clock(api, clock_after_term)
    ctx["deal"] = do_expire_deal(api, ctx["deal_id"])
    return ctx


def given_post_term_collection_deal(
    api,
    ctx: Dict[str, Any],
    *,
    fork: str = "TERMINATE",
    clock_after_term: Optional[str] = None
) -> Dict[str, Any]:
    """Reach the diamond's join point from either fork. ``fork`` is
    ``"TERMINATE"`` or ``"EXPIRE"``."""
    if fork == "EXPIRE":
        ctx = given_expired_deal(api, ctx, clock_after_term=clock_after_term)
    else:
        ctx = given_terminated_deal(api, ctx)
    ctx["deal"] = do_enter_post_term_collection(api, ctx["deal_id"])
    return ctx


def given_closed_deal(
    api,
    ctx: Dict[str, Any],
    *,
    fork: str = "TERMINATE",
    clock_after_term: Optional[str] = None,
    clock_after_collection: Optional[str] = None
) -> Dict[str, Any]:
    """POST_TERM_COLLECTION -> CLOSED. Closure requires that "the logical clock's
    calendar date must be strictly after post_term_collection_end_date", so pass
    ``clock_after_collection`` beyond that date."""
    ctx = given_post_term_collection_deal(
        api, ctx, fork=fork, clock_after_term=clock_after_term
    )
    if clock_after_collection is not None:
        do_set_clock(api, clock_after_collection)
    ctx["deal"] = do_close_deal(api, ctx["deal_id"])
    return ctx


def given_superseded_agreement(
    api,
    ctx: Dict[str, Any],
    *,
    release_index: int = 0,
    successor_kw: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Activate a successor that chains to ``ctx["agreement"]``, moving the
    predecessor ACTIVE -> SUPERSEDED and carrying both balances forward.

    Leaves ``ctx["predecessor"]`` on the old agreement and points
    ``ctx["agreement"]`` at the successor.
    """
    predecessor_id = ctx["agreement_id"]
    spec = dict(successor_kw or {})
    spec["supersedes_agreement_id"] = predecessor_id
    ctx = given_active_agreement(api, ctx, release_index=release_index, agreement_kw=spec)
    ctx["predecessor"] = read_agreement(api, predecessor_id)
    return ctx
