"""Composite setup helpers for the placement lifecycle (PRD §3).

Every helper builds its preconditions from scratch through declared endpoints —
each test starts against an empty database. Setup calls use the lenient
``get_success_data`` validator so a broken precondition surfaces as a setup
failure rather than as a confusing assertion.

The scenario builders return a mutable ``ctx`` dict whose keys are:

``cedent``            the created Cedent row
``reinsurers``        list of created Reinsurer rows (index 0 is the lead market)
``reinsurer``         shorthand for ``reinsurers[0]``
``program``           the created Program row (as returned by its last mutation)
``submission``        the ExposureSubmission row
``layer``             the Layer row
``layers``            list of every Layer created on the program
``market_submissions`` list of MarketSubmission rows
``quotes``            list of Quote rows
``signing_lines``     list of SigningLine rows
``disclosure``        the BrokerageDisclosure row, once created
``cedent_headers``    CedentUnderwriter headers bound to ``cedent["id"]``
``market_headers``    list of ReinsurerUnderwriter headers, one per reinsurer
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CANONICAL_CAT_LAYER, CLOCK, TEST_DEFAULTS
from .factories import (
    advocacy_route_payload,
    counter_payload,
    create_brokerage_disclosure_payload,
    create_cedent_payload,
    create_cession_dispute_payload,
    create_claim_advocacy_payload,
    create_collection_payload,
    create_contract_document_payload,
    create_exposure_submission_payload,
    create_fiduciary_transaction_payload,
    create_layer_payload,
    create_market_submission_payload,
    create_program_payload,
    create_quota_share_layer_payload,
    create_quote_payload,
    create_reinsurer_payload,
    create_xol_layer_payload,
    disclosure_decision_payload,
    firm_order_payload,
    resolve_dispute_payload,
    signoff_payload,
)
from .test_users import (
    TEST_USERS,
    make_cedent_underwriter_headers,
    make_reinsurer_underwriter_headers,
)

api = api_client

ADMIN = TEST_USERS["admin_headers"]
LEAD = TEST_USERS["placement_lead_headers"]
LEAD_2 = TEST_USERS["placement_lead_2_headers"]
ACTUARY = TEST_USERS["actuary_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
ACCOUNTANT_2 = TEST_USERS["accountant_2_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ==========================================================================
# Tier 0 — single-call primitives
# ==========================================================================
def set_clock(current_utc: str = CLOCK["PLACEMENT_START"]) -> Dict[str, Any]:
    """Park the logical clock (PRD §2.4). Always the first call in a chain."""
    return get_success_data(api.set_clock(current_utc, ADMIN))


def create_cedent(**overrides) -> Dict[str, Any]:
    return get_success_data(api.create_cedent(create_cedent_payload(**overrides), ADMIN))


def create_reinsurer(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_reinsurer(create_reinsurer_payload(**overrides), ADMIN)
    )


def create_program(cedent_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_program(create_program_payload(cedent_id, **overrides), LEAD)
    )


def create_exposure_submission(
    program_id: str, cedent_id: Optional[str] = None, headers: Optional[Dict] = None, **overrides
) -> Dict[str, Any]:
    """Create an exposure package. The cedent files its own package (PRD §3.2)."""
    call_headers = headers or (
        make_cedent_underwriter_headers(cedent_id) if cedent_id else LEAD
    )
    return get_success_data(
        api.create_exposure_submission(
            program_id, create_exposure_submission_payload(**overrides), call_headers
        )
    )


def create_layer(program_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_layer(program_id, create_layer_payload(**overrides), LEAD))


def create_quota_share_layer(program_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_layer(program_id, create_quota_share_layer_payload(**overrides), LEAD)
    )


def create_xol_layer(program_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_layer(program_id, create_xol_layer_payload(**overrides), LEAD)
    )


def submit_for_review(submission_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_exposure_for_review(submission_id, LEAD))


def signoff(submission_id: str, decision: str = "SIGNED_OFF", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.signoff_exposure_submission(
            submission_id, signoff_payload(decision, **overrides), ACTUARY
        )
    )


def sign_off_exposure(submission_id: str) -> Dict[str, Any]:
    """submit-for-review then signoff SIGNED_OFF — bubbles the program to SUBMISSION_READY."""
    submit_for_review(submission_id)
    return signoff(submission_id)


def go_to_market(program_id: str) -> Dict[str, Any]:
    return get_success_data(api.go_to_market(program_id, LEAD))


def submit_to_market(
    layer_id: str, reinsurer_id: str, response_deadline: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload = create_market_submission_payload(reinsurer_id, **overrides)
    if response_deadline is not None:
        payload["response_deadline"] = response_deadline
    return get_success_data(api.create_market_submission(layer_id, payload, LEAD))


def quote_on(market_submission_id: str, reinsurer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_quote(
            market_submission_id,
            create_quote_payload(**overrides),
            make_reinsurer_underwriter_headers(reinsurer_id),
        )
    )


def counter_quote(quote_id: str, counter_note: str = "please sharpen the rate") -> Dict[str, Any]:
    return get_success_data(api.counter_quote(quote_id, counter_payload(counter_note), LEAD))


def requote(quote_id: str, reinsurer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.requote(
            quote_id,
            create_quote_payload(**overrides),
            make_reinsurer_underwriter_headers(reinsurer_id),
        )
    )


def current_layer_version(layer_id: str) -> int:
    """Read the layer's live version, as a firm order must do (PRD §2.7)."""
    return get_success_data(api.get_layer(layer_id, LEAD))["version"]


def current_program_version(program_id: str) -> int:
    """Read the program's live version, as a fiduciary booking must do (PRD §2.7)."""
    return get_success_data(api.get_program(program_id, LEAD))["version"]


def firm_order(
    quote_id: str,
    accepted_line_pct: float,
    layer_id: Optional[str] = None,
    expected_layer_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Firm-order a quote, reading the layer version immediately beforehand."""
    if expected_layer_version is None:
        if layer_id is None:
            layer_id = get_success_data(api.get_quote(quote_id, LEAD))["layer_id"]
        expected_layer_version = current_layer_version(layer_id)
    return get_success_data(
        api.firm_order(
            quote_id, firm_order_payload(accepted_line_pct, expected_layer_version), LEAD
        )
    )


def create_disclosure(program_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_brokerage_disclosure(
            program_id, create_brokerage_disclosure_payload(**overrides), ACCOUNTANT
        )
    )


def disclose(disclosure_id: str) -> Dict[str, Any]:
    return get_success_data(api.disclose_brokerage(disclosure_id, ACCOUNTANT))


def decide_disclosure(
    disclosure_id: str, cedent_id: str, decision: str = "ACKNOWLEDGE", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_brokerage_disclosure(
            disclosure_id,
            disclosure_decision_payload(decision, **overrides),
            make_cedent_underwriter_headers(cedent_id),
        )
    )


def acknowledge_disclosure(
    program_id: str, cedent_id: str, brokerage_pct: Optional[float] = None
) -> Dict[str, Any]:
    """create -> disclose -> ACKNOWLEDGE, which flips Program.disclosure_acknowledged."""
    overrides = {} if brokerage_pct is None else {"brokerage_pct": brokerage_pct}
    disclosure = create_disclosure(program_id, **overrides)
    disclose(disclosure["id"])
    return decide_disclosure(disclosure["id"], cedent_id, "ACKNOWLEDGE")


def bind_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api.bind_program(program_id, LEAD))


def settle_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api.settle_program(program_id, ACCOUNTANT))


def sign_down(layer_id: str) -> Dict[str, Any]:
    return get_success_data(api.sign_down_layer(layer_id, LEAD))


def release_line(signing_line_id: str) -> Dict[str, Any]:
    return get_success_data(api.release_signing_line(signing_line_id, LEAD))


def suspend_market(reinsurer_id: str, reason: str = "Rating downgrade") -> Dict[str, Any]:
    return get_success_data(
        api.set_security_status(
            reinsurer_id, {"security_status": "SUSPENDED", "reason": reason}, COMPLIANCE
        )
    )


def set_market_security(reinsurer_id: str, security_status: str, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_security_status(
            reinsurer_id, {"security_status": security_status, "reason": reason}, COMPLIANCE
        )
    )


def suspend_cedent(cedent_id: str, reason: str = "Regulatory review") -> Dict[str, Any]:
    return get_success_data(
        api.suspend_cedent(
            cedent_id, {"status": "SUSPENDED", "suspension_reason": reason}, COMPLIANCE
        )
    )


def file_document(
    program_id: str, document_type: str, wording_reference: Optional[str] = None
) -> Dict[str, Any]:
    reference = wording_reference or f"NW-2026-{document_type}"
    return get_success_data(
        api.create_contract_document(
            program_id, create_contract_document_payload(document_type, reference), LEAD
        )
    )


def agree_wording(program_id: str) -> List[Dict[str, Any]]:
    """File SLIP -> WORDING_DRAFT -> AGREED_WORDING so out-payments may settle."""
    return [
        file_document(program_id, "SLIP"),
        file_document(program_id, "WORDING_DRAFT"),
        file_document(program_id, "AGREED_WORDING"),
    ]


def execute_contract(program_id: str) -> List[Dict[str, Any]]:
    documents = agree_wording(program_id)
    documents.append(file_document(program_id, "EXECUTED_CONTRACT"))
    return documents


def documentation_checkpoint(program_id: str) -> Dict[str, Any]:
    return get_success_data(api.documentation_checkpoint(program_id, COMPLIANCE))


def market_sweep(program_id: str) -> Dict[str, Any]:
    return get_success_data(api.market_sweep(program_id, LEAD))


def withdraw_program(program_id: str, reason: str = "Cedent cancelled the renewal"):
    return get_success_data(api.withdraw_program(program_id, {"reason": reason}, LEAD))


# ==========================================================================
# Fiduciary movements (PRD §3.8)
# ==========================================================================
def book_transaction(
    program_id: str,
    txn_type: str,
    amount_minor: int,
    signing_line_id: Optional[str] = None,
    headers: Optional[Dict] = None,
    expected_program_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Book a movement, reading the program version immediately beforehand."""
    version = (
        expected_program_version
        if expected_program_version is not None
        else current_program_version(program_id)
    )
    payload = create_fiduciary_transaction_payload(txn_type, amount_minor, version)
    if signing_line_id is not None:
        payload["signing_line_id"] = signing_line_id
    return get_success_data(
        api.create_fiduciary_transaction(program_id, payload, headers or ACCOUNTANT)
    )


def approve_transaction(transaction_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Approve with the independent control identity — never the booking identity."""
    return get_success_data(
        api.approve_fiduciary_transaction(transaction_id, headers or COMPLIANCE)
    )


def settle_transaction(transaction_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.settle_fiduciary_transaction(transaction_id, headers or ACCOUNTANT)
    )


def reverse_transaction(transaction_id: str) -> Dict[str, Any]:
    return get_success_data(api.reverse_fiduciary_transaction(transaction_id, COMPLIANCE))


def book_approve_settle(
    program_id: str,
    txn_type: str,
    amount_minor: int,
    signing_line_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Book -> approve -> settle, returning the settled movement."""
    txn = book_transaction(program_id, txn_type, amount_minor, signing_line_id)
    approve_transaction(txn["id"])
    return settle_transaction(txn["id"])


def settle_cedent_receipt(program_id: str, amount_minor: int) -> Dict[str, Any]:
    """Fund the fiduciary account with a settled CEDENT_RECEIPT."""
    return book_approve_settle(program_id, "CEDENT_RECEIPT", amount_minor)


# ==========================================================================
# Claims advocacy (PRD §3.9)
# ==========================================================================
def notify_claim(layer_id: str, cedent_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_claim_advocacy(
            layer_id,
            create_claim_advocacy_payload(**overrides),
            make_cedent_underwriter_headers(cedent_id),
        )
    )


def review_claim(claim_advocacy_id: str) -> Dict[str, Any]:
    return get_success_data(api.review_claim_advocacy(claim_advocacy_id, LEAD))


def withdraw_claim(claim_advocacy_id: str, cedent_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.withdraw_claim_advocacy(
            claim_advocacy_id, make_cedent_underwriter_headers(cedent_id)
        )
    )


def raise_dispute(
    claim_advocacy_id: str,
    reinsurer_id: str,
    signing_line_id: str,
    disputed_minor: int,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cession_dispute(
            claim_advocacy_id,
            create_cession_dispute_payload(signing_line_id, disputed_minor, **overrides),
            make_reinsurer_underwriter_headers(reinsurer_id),
        )
    )


def set_advocacy_route(claim_advocacy_id: str, route: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_advocacy_route(claim_advocacy_id, advocacy_route_payload(route), LEAD)
    )


def resolve_dispute(
    dispute_id: str, resolution: str, settled_minor: int, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.resolve_cession_dispute(
            dispute_id, resolve_dispute_payload(resolution, settled_minor, **overrides), LEAD
        )
    )


def collect(claim_advocacy_id: str, signing_line_id: str, amount_minor: int) -> Dict[str, Any]:
    return get_success_data(
        api.create_collection(
            claim_advocacy_id,
            create_collection_payload(signing_line_id, amount_minor),
            ACCOUNTANT,
        )
    )


def generate_renewal_report(program_id: str) -> Dict[str, Any]:
    return get_success_data(api.create_renewal_report(program_id, ACTUARY))


# ==========================================================================
# Read-back helpers
# ==========================================================================
def read_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_program(program_id, LEAD))


def read_layer(layer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_layer(layer_id, LEAD))


def read_cedent(cedent_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cedent(cedent_id, LEAD))


def read_reinsurer(reinsurer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reinsurer(reinsurer_id, LEAD))


def read_quote(quote_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_quote(quote_id, LEAD))


def read_signing_line(signing_line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_signing_line(signing_line_id, LEAD))


def read_market_submission(market_submission_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_market_submission(market_submission_id, LEAD))


def read_submission(submission_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_exposure_submission(submission_id, LEAD))


def read_advocacy(claim_advocacy_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_claim_advocacy(claim_advocacy_id, LEAD))


def read_dispute(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cession_dispute(dispute_id, LEAD))


def read_transaction(transaction_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fiduciary_transaction(transaction_id, ACCOUNTANT))


def read_disclosure(disclosure_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_brokerage_disclosure(disclosure_id, LEAD))


def list_rows(response) -> List[Dict[str, Any]]:
    """Extract the row list from a collection response."""
    body = response.json()
    assert response.status_code == 200, f"list call failed: {response.text}"
    return body["data"]


# ==========================================================================
# Tier 2 — placement scenario builders
# ==========================================================================
DEFAULT_MARKET_NAMES = [
    "Alpha Re",
    "Bravo Re",
    "Charlie Re",
    "Delta Re",
    "Echo Re",
    "Foxtrot Re",
]

_LAYER_BUILDERS = {
    "CAT": create_layer,
    "CATASTROPHE": create_layer,
    "QUOTA_SHARE": create_quota_share_layer,
    "QS": create_quota_share_layer,
    "XOL": create_xol_layer,
    "EXCESS_OF_LOSS": create_xol_layer,
}


def _new_ctx(cedent: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cedent": cedent,
        "cedent_headers": make_cedent_underwriter_headers(cedent["id"]),
        "reinsurers": [],
        "market_headers": [],
        "layers": [],
        "market_submissions": [],
        "quotes": [],
        "signing_lines": [],
        "documents": [],
        "transactions": [],
        "advocacies": [],
        "disputes": [],
    }


def add_market(ctx: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Register one more reinsurance market and remember its underwriter headers."""
    if "name" not in overrides:
        overrides["name"] = DEFAULT_MARKET_NAMES[len(ctx["reinsurers"])]
    reinsurer = create_reinsurer(**overrides)
    ctx["reinsurers"].append(reinsurer)
    ctx["market_headers"].append(make_reinsurer_underwriter_headers(reinsurer["id"]))
    ctx["reinsurer"] = ctx["reinsurers"][0]
    return reinsurer


def add_layer(ctx: Dict[str, Any], layer_kind: str = "CAT", **overrides) -> Dict[str, Any]:
    layer = _LAYER_BUILDERS[layer_kind](ctx["program"]["id"], **overrides)
    ctx["layers"].append(layer)
    ctx["layer"] = ctx["layers"][0]
    return layer


def refresh(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Re-read program, layers and markets so a test asserts on live rows."""
    ctx["program"] = read_program(ctx["program"]["id"])
    ctx["layers"] = [read_layer(layer["id"]) for layer in ctx["layers"]]
    if ctx["layers"]:
        ctx["layer"] = ctx["layers"][0]
    ctx["reinsurers"] = [read_reinsurer(market["id"]) for market in ctx["reinsurers"]]
    if ctx["reinsurers"]:
        ctx["reinsurer"] = ctx["reinsurers"][0]
    ctx["cedent"] = read_cedent(ctx["cedent"]["id"])
    return ctx


def setup_draft_program(
    layer_kind: str = "CAT",
    layer_overrides: Optional[Dict] = None,
    program_overrides: Optional[Dict] = None,
    submission_overrides: Optional[Dict] = None,
    cedent_overrides: Optional[Dict] = None,
    market_specs: Optional[List[Dict]] = None,
    clock: str = CLOCK["PLACEMENT_START"],
    with_layer: bool = True,
) -> Dict[str, Any]:
    """clock -> cedent -> markets -> program -> exposure package -> layer.

    The program is left in DRAFT with its package in DRAFT (PRD §3.1, §3.2, §3.3).
    """
    set_clock(clock)
    cedent = create_cedent(**(cedent_overrides or {}))
    ctx = _new_ctx(cedent)
    for spec in market_specs if market_specs is not None else [{}]:
        add_market(ctx, **spec)
    ctx["program"] = create_program(cedent["id"], **(program_overrides or {}))
    ctx["submission"] = create_exposure_submission(
        ctx["program"]["id"], cedent["id"], **(submission_overrides or {})
    )
    if with_layer:
        add_layer(ctx, layer_kind, **(layer_overrides or {}))
    return ctx


def setup_submission_ready_program(**kwargs) -> Dict[str, Any]:
    """The DRAFT prologue plus submit-for-review and actuarial sign-off."""
    ctx = setup_draft_program(**kwargs)
    ctx["submission"] = sign_off_exposure(ctx["submission"]["id"])
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def setup_program_in_market(**kwargs) -> Dict[str, Any]:
    """Program taken to market; its layers are still OPEN until a submission goes out."""
    ctx = setup_submission_ready_program(**kwargs)
    ctx["program"] = go_to_market(ctx["program"]["id"])
    return ctx


def send_submission(
    ctx: Dict[str, Any],
    market_index: int = 0,
    layer_index: int = 0,
    response_deadline: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Send one market submission on a layer, moving OPEN -> IN_MARKET the first time."""
    layer = ctx["layers"][layer_index]
    market_submission = submit_to_market(
        layer["id"],
        ctx["reinsurers"][market_index]["id"],
        response_deadline=response_deadline,
        **overrides,
    )
    ctx["market_submissions"].append(market_submission)
    ctx["market_submission"] = ctx["market_submissions"][0]
    return market_submission


def add_quote(
    ctx: Dict[str, Any],
    market_index: int = 0,
    market_submission: Optional[Dict] = None,
    **overrides,
) -> Dict[str, Any]:
    """Quote against a submission as the addressed market."""
    submission = market_submission or ctx["market_submissions"][-1]
    quote = quote_on(submission["id"], ctx["reinsurers"][market_index]["id"], **overrides)
    ctx["quotes"].append(quote)
    ctx["quote"] = ctx["quotes"][0]
    return quote


def setup_quoted_layer(
    quote_overrides: Optional[Dict] = None,
    response_deadline: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """IN_MARKET prologue: program in market, one submission sent, one quote on it."""
    ctx = setup_program_in_market(**kwargs)
    send_submission(ctx, response_deadline=response_deadline)
    add_quote(ctx, **(quote_overrides or {}))
    ctx["layers"] = [read_layer(layer["id"]) for layer in ctx["layers"]]
    ctx["layer"] = ctx["layers"][0]
    return ctx


def place_line(
    ctx: Dict[str, Any],
    market_index: int = 0,
    layer_index: int = 0,
    accepted_line_pct: float = 100.0000,
    offered_line_pct: Optional[float] = None,
    response_deadline: Optional[str] = None,
    quote_overrides: Optional[Dict] = None,
    is_lead: bool = False,
) -> Dict[str, Any]:
    """submission -> quote -> firm order for one market on one layer.

    Returns the created SigningLine and appends every row to ``ctx``.
    """
    overrides = dict(quote_overrides or {})
    overrides.setdefault("offered_line_pct", offered_line_pct or accepted_line_pct)
    overrides.setdefault("is_lead", is_lead)
    market_submission = send_submission(
        ctx, market_index=market_index, layer_index=layer_index,
        response_deadline=response_deadline,
    )
    quote = add_quote(
        ctx, market_index=market_index, market_submission=market_submission, **overrides
    )
    signing_line = firm_order(
        quote["id"], accepted_line_pct, layer_id=ctx["layers"][layer_index]["id"]
    )
    ctx["signing_lines"].append(signing_line)
    ctx["signing_line"] = ctx["signing_lines"][0]
    return signing_line


def place_lines(
    ctx: Dict[str, Any],
    specs: List[Dict[str, Any]],
    layer_index: int = 0,
    response_deadline: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Market one layer to several markets, then firm-order each accepted line.

    ``specs`` is an ordered list of dicts carrying ``market_index``,
    ``accepted_line_pct`` and optionally ``offered_line_pct``,
    ``quote_overrides``, ``is_lead`` and ``response_deadline``.

    Every market submission and quote is issued *before* any firm order,
    because PRD §3.4 admits a market submission only while "the layer must be
    either ``OPEN`` or ``IN_MARKET``" — the first firm order carries the layer
    to ``PARTIALLY_PLACED``, after which no further market submission is legal.
    Returns the signing lines in ``specs`` order.
    """
    prepared: List[Any] = []
    for spec in specs:
        market_index = spec.get("market_index", 0)
        accepted_line_pct = spec["accepted_line_pct"]
        overrides = dict(spec.get("quote_overrides") or {})
        overrides.setdefault(
            "offered_line_pct", spec.get("offered_line_pct") or accepted_line_pct
        )
        overrides.setdefault("is_lead", spec.get("is_lead", False))
        market_submission = send_submission(
            ctx,
            market_index=market_index,
            layer_index=layer_index,
            response_deadline=spec.get("response_deadline", response_deadline),
        )
        quote = add_quote(
            ctx,
            market_index=market_index,
            market_submission=market_submission,
            **overrides,
        )
        prepared.append((quote, accepted_line_pct))

    lines = []
    for quote, accepted_line_pct in prepared:
        signing_line = firm_order(
            quote["id"], accepted_line_pct, layer_id=ctx["layers"][layer_index]["id"]
        )
        ctx["signing_lines"].append(signing_line)
        lines.append(signing_line)
    if ctx["signing_lines"]:
        ctx["signing_line"] = ctx["signing_lines"][0]
    return lines


def setup_firm_ordered_layer(
    accepted_line_pct: float = 100.0000,
    quote_overrides: Optional[Dict] = None,
    response_deadline: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """One market takes the whole layer, so the program reaches FIRM_ORDER."""
    ctx = setup_program_in_market(**kwargs)
    place_line(
        ctx,
        accepted_line_pct=accepted_line_pct,
        offered_line_pct=max(accepted_line_pct, 100.0000),
        response_deadline=response_deadline,
        quote_overrides=quote_overrides,
        is_lead=True,
    )
    return refresh(ctx)


def setup_oversubscribed_layer(
    first_line_pct: float = 60.0000,
    second_line_pct: float = 50.0000,
    market_specs: Optional[List[Dict]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Two markets write 60 + 50, so the written total is 110.0000 (OVERSUBSCRIBED)."""
    specs = market_specs or [{}, {}]
    ctx = setup_program_in_market(market_specs=specs, **kwargs)
    place_lines(
        ctx,
        [
            {
                "market_index": 0,
                "accepted_line_pct": first_line_pct,
                "offered_line_pct": 100.0000,
                "is_lead": True,
            },
            {
                "market_index": 1,
                "accepted_line_pct": second_line_pct,
                "offered_line_pct": 100.0000,
                "is_lead": False,
            },
        ],
    )
    return refresh(ctx)


def setup_signed_down_layer(**kwargs) -> Dict[str, Any]:
    """An oversubscribed layer taken through sign-down to SIGNED_DOWN."""
    ctx = setup_oversubscribed_layer(**kwargs)
    sign_down(ctx["layer"]["id"])
    return refresh(ctx)


def setup_bound_program(
    accepted_line_pct: float = 100.0000,
    brokerage_pct: Optional[float] = None,
    **kwargs,
) -> Dict[str, Any]:
    """The BOUND prologue: firm order -> disclosure acknowledged -> bind (PRD §3.6)."""
    ctx = setup_firm_ordered_layer(accepted_line_pct=accepted_line_pct, **kwargs)
    ctx["disclosure"] = acknowledge_disclosure(
        ctx["program"]["id"],
        ctx["cedent"]["id"],
        brokerage_pct if brokerage_pct is not None else ctx["program"]["brokerage_pct"],
    )
    ctx["program"] = bind_program(ctx["program"]["id"])
    return refresh(ctx)


def setup_bound_program_with_funds(
    receipt_minor: Optional[int] = None, **kwargs
) -> Dict[str, Any]:
    """A bound program whose fiduciary account has been funded by a settled receipt."""
    ctx = setup_bound_program(**kwargs)
    amount = (
        receipt_minor
        if receipt_minor is not None
        else int(ctx["layer"]["quoted_gross_premium_minor"])
    )
    ctx["receipt"] = settle_cedent_receipt(ctx["program"]["id"], amount)
    ctx["transactions"].append(ctx["receipt"])
    return refresh(ctx)


def setup_bound_program_with_agreed_wording(**kwargs) -> Dict[str, Any]:
    """A funded bound program whose documentation has reached WORDING_AGREED."""
    ctx = setup_bound_program_with_funds(**kwargs)
    ctx["documents"] = agree_wording(ctx["program"]["id"])
    return refresh(ctx)


def setup_notified_claim(
    claim_overrides: Optional[Dict] = None, **kwargs
) -> Dict[str, Any]:
    """A bound program with one claim notified against its bound layer (PRD §3.9)."""
    ctx = setup_bound_program(**kwargs)
    advocacy = notify_claim(
        ctx["layer"]["id"], ctx["cedent"]["id"], **(claim_overrides or {})
    )
    ctx["advocacies"].append(advocacy)
    ctx["advocacy"] = advocacy
    return ctx


def setup_disputed_claim(
    disputed_minor: int = 100_000_000,
    claim_overrides: Optional[Dict] = None,
    dispute_overrides: Optional[Dict] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Claim notified -> reviewed -> one cession dispute raised by the writing market."""
    ctx = setup_notified_claim(claim_overrides=claim_overrides, **kwargs)
    review_claim(ctx["advocacy"]["id"])
    dispute = raise_dispute(
        ctx["advocacy"]["id"],
        ctx["reinsurers"][0]["id"],
        ctx["signing_lines"][0]["id"],
        disputed_minor,
        **(dispute_overrides or {}),
    )
    ctx["disputes"].append(dispute)
    ctx["dispute"] = dispute
    ctx["advocacy"] = read_advocacy(ctx["advocacy"]["id"])
    return ctx
