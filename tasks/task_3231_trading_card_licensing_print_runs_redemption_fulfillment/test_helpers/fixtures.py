"""Composite setup helpers for the trading-card platform.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server restarts with an empty database before each
test. Helpers use get_success_data() internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    allocation_line,
    create_allocation_payload,
    create_artwork_approval_payload,
    create_card_set_payload,
    create_license_payload,
    create_print_run_decision_payload,
    create_product_line_payload,
    create_quality_claim_payload,
    create_redemption_payload,
    create_signing_session_payload,
)
from .test_users import TEST_USERS, make_licensor_approver_headers


def _h(name: str) -> dict:
    return TEST_USERS[name]


def setup_clock(to_iso8601: str = C.CLOCK_START):
    """Advance the server's logical clock. The clock never reads real time."""
    resp = api_client.set_clock(to_iso8601, _h("platform_admin_headers"))
    return get_success_data(resp)


def advance_clock(api, to_iso8601: str):
    """Move the logical clock to a specific instant (PRD 2.4).

    Temporal gates are all evaluated against this value, so helpers that must
    clear one derive the target instant from the resource itself rather than
    assuming the default startup instant is late enough.
    """
    return get_success_data(
        api.set_clock(to_iso8601, _h("platform_admin_headers"))
    )


def create_license_raw(api, **overrides):
    resp = api.create_license(
        create_license_payload(**overrides), _h("licensing_manager_headers")
    )
    return get_success_data(resp)


def create_active_license(api, **overrides):
    """Register a license and take it live. Returns the ACTIVE license."""
    lic = create_license_raw(api, **overrides)
    resp = api.activate_license(lic["id"], _h("licensing_manager_headers"))
    return get_success_data(resp)


def create_product_line_raw(api, license_id, **overrides):
    resp = api.create_product_line(
        create_product_line_payload(license_id=license_id, **overrides),
        _h("product_manager_headers"),
    )
    return get_success_data(resp)


def create_line_ready(api, license_id, **overrides):
    """Create a line and move it into READY_FOR_APPROVAL."""
    line = create_product_line_raw(api, license_id, **overrides)
    resp = api.ready_product_line(line["id"], _h("product_manager_headers"))
    return get_success_data(resp)


def approve_artwork_for_set(api, set_id, license_id, artwork_code="ART-BASE-001",
                            submitted_on="2026-08-25T00:00:00Z",
                            decided_on="2026-08-26T00:00:00Z"):
    """Submit one artwork piece to a licensor and approve it as that licensor."""
    resp = api.submit_artwork(
        set_id,
        create_artwork_approval_payload(
            approver_id=license_id, artwork_code=artwork_code, submitted_on=submitted_on
        ),
        _h("product_manager_headers"),
    )
    art = get_success_data(resp)
    resp = api.decide_artwork(
        art["id"],
        {"decision": "APPROVE", "decided_on": decided_on},
        make_licensor_approver_headers(license_id),
    )
    return get_success_data(resp)


def create_card_set_raw(api, line_id, **overrides):
    resp = api.create_card_set(
        create_card_set_payload(product_line_id=line_id, **overrides),
        _h("product_manager_headers"),
    )
    return get_success_data(resp)


def approve_card_set(api, set_id, expected_version):
    resp = api.approve_card_set(
        set_id,
        {"expected_card_set_version": expected_version},
        _h("product_manager_headers"),
    )
    return resp


def submit_card_set_for_review(api, set_id):
    """Move a card set out of DRAFT and into UNDER_REVIEW.

    PRD 3.2: "A set meeting those conditions moves to `UNDER_REVIEW`", and the
    approval transition is `UNDER_REVIEW` -> `APPROVED`. The submission is
    therefore a required hop, not an optional one. It also advances the set's
    own `version`, so callers must approve against the version the submission
    returned (or re-read the set) rather than the version read before it.
    """
    return get_success_data(
        api.submit_card_set(set_id, _h("product_manager_headers"))
    )


def build_approved_set(api, *, license_id=None, license_overrides=None,
                       line_overrides=None, set_overrides=None,
                       line_ready=True, artwork=True):
    """License (created here or supplied) + line + approved card set.

    Returns a dict with keys: license, line, card_set. The license is
    activated; the line is moved to READY_FOR_APPROVAL when `line_ready`; the
    set is submitted and approved. When `artwork` is True one artwork piece is
    approved first so the submission precondition is satisfied.
    """
    license_overrides = license_overrides or {}
    line_overrides = line_overrides or {}
    set_overrides = set_overrides or {}

    if license_id is None:
        license_obj = create_active_license(api, **license_overrides)
        license_id = license_obj["id"]
    else:
        license_obj = get_success_data(
            api.get_license(license_id, _h("licensing_manager_headers"))
        )

    line = create_product_line_raw(api, license_id, **line_overrides)
    if line_ready:
        line = get_success_data(
            api.ready_product_line(line["id"], _h("product_manager_headers"))
        )

    card_set = create_card_set_raw(api, line["id"], **set_overrides)
    if artwork:
        approve_artwork_for_set(api, card_set["id"], license_id)

    # PRD 3.2: submission moves the set DRAFT -> UNDER_REVIEW, and approval's
    # source state is UNDER_REVIEW, so the submit hop is mandatory here.
    card_set = submit_card_set_for_review(api, card_set["id"])
    resp = approve_card_set(api, card_set["id"], card_set["version"])
    card_set = get_success_data(resp)
    return {"license": license_obj, "line": line, "card_set": card_set}


def freeze_print_run(api, card_set, line, *, authority="BRAND_DIRECTIVE",
                     declared_quantity=12000, announced=True,
                     demand_multiplier=1.0, proposed_on="2026-09-05T00:00:00Z",
                     expected_line_version=None, approve=True):
    """Propose (and optionally approve) a print-run decision for a set."""
    line_version = (
        expected_line_version
        if expected_line_version is not None
        else line["version"]
    )
    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority=authority,
            proposed_against_line_version=line_version,
            demand_multiplier=demand_multiplier,
            declared_quantity=declared_quantity,
            announced=announced,
            proposed_on=proposed_on,
        ),
        _h("production_planner_headers"),
    )
    decision = get_success_data(resp)
    if approve:
        resp = api.approve_print_run_decision(
            decision["id"],
            {
                "expected_card_set_version": card_set["version"],
                "expected_product_line_version": line_version,
            },
            _h("production_planner_headers"),
        )
        decision = get_success_data(resp)
    return decision


def publish_pack_configuration(api, set_id, *, config_serial=1,
                               base_packs=10, insert_packs=0, premium_packs=0):
    """Propose and publish one pack configuration on an approved set."""
    resp = api.create_pack_configuration(
        {
            "card_set_id": set_id,
            "config_serial": config_serial,
            "base_packs": base_packs,
            "insert_packs": insert_packs,
            "premium_packs": premium_packs,
        },
        _h("product_manager_headers"),
    )
    config = get_success_data(resp)
    resp = api.publish_pack_configuration(config["id"], _h("product_manager_headers"))
    return get_success_data(resp)


def build_packed_out_line(api, *, signer_name=C.DEFAULT_SIGNER_NAME,
                          quantity_delivered=200, autograph_planned_count=200,
                          declared_quantity=12000, run_planned_on=None,
                          signer_kind="PLAYER_ASSOCIATION",
                          pack_out_line=True, pack_out_set=True,
                          redemption_code=None, estimated_value_cents=400000,
                          redemption_opened_on=C.CLOCK_START):
    """Drive license + line + set all the way to PACKED_OUT.

    Walks: active license -> line -> ready -> approved set -> frozen run ->
    (optional) signing session shipped and completed -> set production ->
    line production -> line packout -> set packout. Returns a dict with
    license, line, card_set and session (None when no autograph stock is used).
    """
    license_obj = create_active_license(api)
    line_overrides = {"cases_printed": C.DEFAULT_CASES_PRINTED}
    if run_planned_on:
        line_overrides["run_planned_on"] = run_planned_on
    line = create_line_ready(api, license_obj["id"], **line_overrides)

    card_set = create_card_set_raw(
        api,
        line["id"],
        autograph_planned_count=autograph_planned_count,
        print_run_quantity=500,
    )
    # PRD 3.2: submission requires at least one APPROVED artwork piece, and the
    # set cannot be approved without having been submitted first.
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    set_v0 = get_success_data(api.submit_card_set(
        card_set["id"], _h("product_manager_headers")
    ))["version"]
    card_set = get_success_data(approve_card_set(api, card_set["id"], set_v0))

    line = get_success_data(
        api.get_product_line(line["id"], _h("product_manager_headers"))
    )
    freeze_print_run(
        api,
        card_set,
        line,
        declared_quantity=declared_quantity,
        announced=True,
    )
    card_set = get_success_data(
        api.get_card_set(card_set["id"], _h("production_planner_headers"))
    )

    redemption = None
    if redemption_code:
        # PRD 3.4: completing the session fulfils every ISSUED redemption that
        # matches the session's signer and one of its allocation lines, so a
        # redemption issued before completion lands in FULFILLED.
        redemption = get_success_data(
            api.issue_redemption(
                card_set["id"],
                create_redemption_payload(
                    redemption_code=redemption_code,
                    signer_name=signer_name,
                    estimated_value_cents=estimated_value_cents,
                    opened_on=redemption_opened_on,
                ),
                _h("redemption_analyst_headers"),
            )
        )

    session = None
    if quantity_delivered:
        resp = api.create_signing_session(
            create_signing_session_payload(
                signer_name=signer_name,
                signer_kind=signer_kind,
                license_id=license_obj["id"],
                allocation_lines=[
                    allocation_line(card_set["id"], quantity_delivered=quantity_delivered)
                ],
            ),
            _h("signing_coordinator_headers"),
        )
        session = get_success_data(resp)
        get_success_data(
            api.prepare_signing_stock(session["id"], _h("signing_coordinator_headers"))
        )
        # PRD 3.4: shipping is gated on the calendar — the clock must be at or
        # after the session's derived ship_date before the stock can move.
        # ship_date is derived as scheduled_on less the shipping lead time, so
        # advance the logical clock to it rather than assuming the default
        # startup instant already clears the gate.
        advance_clock(api, session["ship_date"])
        get_success_data(
            api.ship_signing_stock(session["id"], _h("signing_coordinator_headers"))
        )
        session = get_success_data(
            api.complete_signing_session(
                session["id"],
                {"signer_attendance": "ATTENDED"},
                _h("authentication_officer_headers"),
            )
        )

    get_success_data(
        api.start_card_set_production(card_set["id"], _h("production_planner_headers"))
    )
    line = get_success_data(
        api.start_product_line_production(line["id"], _h("production_planner_headers"))
    )
    if pack_out_line:
        line = get_success_data(
            api.pack_out_product_line(line["id"], _h("production_planner_headers"))
        )
    if pack_out_set:
        # PRD 3.2: packing a set out "requires the set to carry at least one
        # published pack configuration", so publish one before the packout hop.
        # The standard configuration (cards_per_pack 10) is published as a
        # single base-pack line.
        publish_pack_configuration(
            api, card_set["id"], config_serial=1, base_packs=10
        )
        if pack_out_line:
            # PRD 3.2: packing a set out requires the parent line to have
            # already reached PACKED_OUT, so the line hop always precedes it.
            card_set = get_success_data(
                api.pack_out_card_set(card_set["id"], _h("production_planner_headers"))
            )
    card_set = get_success_data(
        api.get_card_set(card_set["id"], _h("production_planner_headers"))
    )
    scenario = {
        "license": license_obj,
        "line": line,
        "card_set": card_set,
        "session": session,
        "redemption": redemption,
    }
    return scenario


def build_ready_to_ship_allocation(api, *, channel="HOBBY", quantity_allocated=10,
                                   effective_price_cents=72000, mark_utf=True,
                                   ship=False, quality_claim_affected=None,
                                   **packout_overrides):
    """Packed-out line plus one allocation (UTF by default).

    With `quality_claim_affected` set, one approved quality claim of that many
    affected cards is filed against the line's set before the allocation is
    created, so the recall loop has evidence to read. Returns a dict with
    license, line, card_set, session and allocation.
    """
    packout_overrides.setdefault("pack_out_set", False)
    scenario = build_packed_out_line(api, **packout_overrides)
    if quality_claim_affected is not None:
        scenario["claim"] = build_approved_quality_claim(
            api, scenario["card_set"]["id"], affected_quantity=quality_claim_affected
        )
    resp = api.create_allocation(
        create_allocation_payload(
            product_line_id=scenario["line"]["id"],
            channel=channel,
            quantity_allocated=quantity_allocated,
            effective_price_cents=effective_price_cents,
        ),
        _h("distribution_manager_headers"),
    )
    allocation = get_success_data(resp)
    if ship:
        # PRD 3.8: SHIPPED is reached from UTF, so a scenario that needs a
        # shipped allocation marks it unable-to-fill first. Shipping is itself
        # gated on the calendar — the clock must be at or after the parent
        # line's run_planned_on before the allocation moves.
        if allocation["status"] == "RESERVED":
            allocation = get_success_data(
                api.mark_allocation_utf(
                    allocation["id"], _h("distribution_manager_headers")
                )
            )
        advance_clock(api, scenario["line"]["run_planned_on"])
        allocation = get_success_data(
            api.ship_allocation(allocation["id"], _h("distribution_manager_headers"))
        )
    elif mark_utf:
        allocation = get_success_data(
            api.mark_allocation_utf(
                allocation["id"], _h("distribution_manager_headers")
            )
        )
    scenario["allocation"] = allocation
    return scenario


def build_fulfilled_redemption(api, *, estimated_value_cents=400000,
                               opened_on=C.CLOCK_START,
                               redemption_code="RDM-9001",
                               extra_issued_redemption=None,
                               **packout_overrides):
    """A redemption that a signer's session completion has already fulfilled.

    The set is deliberately left un-packed-out so that the line-level packout
    is still ahead. Returns a dict with license, line, card_set, session and
    redemption.
    """
    # The line is deliberately left un-packed-out: pack-out closes every
    # FULFILLED redemption under the line, so the redemption has to still be
    # FULFILLED for the caller to observe (or compensate) it.
    packout_overrides.setdefault("pack_out_set", False)
    packout_overrides.setdefault("pack_out_line", False)
    scenario = build_packed_out_line(
        api,
        redemption_code=redemption_code,
        estimated_value_cents=estimated_value_cents,
        redemption_opened_on=opened_on,
        **packout_overrides
    )
    if extra_issued_redemption:
        # PRD 3.2: pack-out "closes every redemption under the line's sets that
        # is in FULFILLED status" — an ISSUED redemption is deliberately left
        # untouched, which needs a second redemption that is still live.
        scenario["issued_redemption"] = get_success_data(
            api.issue_redemption(
                scenario["card_set"]["id"],
                create_redemption_payload(
                    redemption_code=extra_issued_redemption,
                    signer_name=packout_overrides.get("signer_name", C.DEFAULT_SIGNER_NAME),
                    estimated_value_cents=estimated_value_cents,
                    opened_on=opened_on,
                ),
                _h("redemption_analyst_headers"),
            )
        )
    return scenario


def build_approved_quality_claim(api, set_id, *, affected_quantity=40,
                                 severity="MINOR", filed_on=C.CLOCK_START,
                                 claim_type="MISPRINT"):
    """File, open review on and approve one quality claim against a set."""
    resp = api.file_quality_claim(
        set_id,
        create_quality_claim_payload(
            claim_type=claim_type,
            severity=severity,
            affected_quantity=affected_quantity,
            filed_on=filed_on,
        ),
        _h("quality_analyst_headers"),
    )
    claim = get_success_data(resp)
    get_success_data(api.open_claim_review(claim["id"], _h("quality_analyst_headers")))
    resp = api.approve_quality_claim(claim["id"], _h("quality_analyst_headers"))
    return get_success_data(resp)


def issue_plain_redemption(api, *, estimated_value_cents=400000,
                           opened_on=C.CLOCK_START, redemption_code="RDM-5001",
                           need_license=False, **set_overrides):
    """Active license + ready line + approved set + one ISSUED redemption."""
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], **set_overrides)
    # PRD 3.2: an APPROVED artwork piece is the precondition for submission.
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    resp = api.issue_redemption(
        card_set["id"],
        create_redemption_payload(
            redemption_code=redemption_code,
            estimated_value_cents=estimated_value_cents,
            opened_on=opened_on,
        ),
        _h("redemption_analyst_headers"),
    )
    redemption = get_success_data(resp)
    if need_license:
        return license_obj, line, card_set, redemption
    return card_set["id"], redemption


def build_redemption_near_deadline(api, *, estimated_value_cents=400000,
                                   opened_on=C.CLOCK_START,
                                   redemption_code="RDM-5001"):
    """One redemption sitting inside its consumer deadline window."""
    return issue_plain_redemption(
        api, estimated_value_cents=estimated_value_cents, opened_on=opened_on,
        redemption_code=redemption_code
    )