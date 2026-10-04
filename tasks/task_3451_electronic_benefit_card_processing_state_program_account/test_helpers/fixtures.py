"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test runs against a server restarted with an
empty database. Setup calls go through `get_success_data`, so a broken
precondition raises a clear "Setup failed" error instead of surfacing as a
confusing assertion inside the behaviour under test.

Ownership threading (PRD §2.1): Cardholder calls carry the real
CaseAccount.id and RetailerSystem calls carry the real Retailer.id, minted via
make_cardholder_headers / make_retailer_system_headers. Opaque operators use
the named identities from test_users (STATE_ADMIN_USER_ID, CSR_USER_A,
CSR_USER_B); segregation-of-duties flows pass csr ids explicitly.

Time is logical (PRD §2.4): fixtures advance time exclusively through the
clock endpoint with explicit ISO-8601 instants, never the wall clock and never
by backdating entity fields. The canonical recipe timeline: contracts and
programs stand up at the server-default clock 2026-09-01T00:00:00Z, spending
activity happens on 2026-09-02, and the first settlement cutoff closes that
day at 2026-09-03T00:00:00Z.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CARD_MAIL_DELAY_HOURS
from .test_users import (
    CSR_USER_A,
    CSR_USER_B,
    TEST_USERS,
    make_cardholder_headers,
    make_cardholder_services_headers,
    make_retailer_system_headers,
)

ADMIN = TEST_USERS["state_admin_headers"]
CSR_A = TEST_USERS["csr_headers"]      # CardholderServices operator csr-a
CSR_B = TEST_USERS["csr_alt_headers"]  # CardholderServices operator csr-b

# Canonical recipe timeline (see module docstring).
DEFAULT_ACTIVITY_CLOCK = "2026-09-02T12:00:00Z"
DEFAULT_CUTOFF_CLOCK = "2026-09-03T00:00:00Z"
DEFAULT_DISASTER_WINDOW = ("2026-09-01", "2026-10-31")

_ALLOTMENTS_DEFAULT = "__default__"


class Ctx(dict):
    """Dict of the entities a fixture built, also reachable as attributes."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


# ---------------------------------------------------------------------------
# ISO-8601 arithmetic on the logical clock (never wall-clock)
# ---------------------------------------------------------------------------

def parse_utc(iso: str) -> datetime:
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))


def format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_plus_hours(iso: str, hours: float) -> str:
    return format_utc(parse_utc(iso) + timedelta(hours=hours))


def iso_plus_days(iso: str, days: float) -> str:
    return format_utc(parse_utc(iso) + timedelta(days=days))


def _earliest_activation_clock(card: Dict[str, Any]) -> str:
    """Soonest safe activation instant: issuance + mail delay + 1h, but never
    before the canonical activity clock (the clock is forward-only)."""
    earliest = parse_utc(card["created_at"]) + timedelta(hours=CARD_MAIL_DELAY_HOURS + 1)
    return format_utc(max(earliest, parse_utc(DEFAULT_ACTIVITY_CLOCK)))


# ---------------------------------------------------------------------------
# Single-call primitives. Each performs exactly one API call as the correct
# role and returns the success payload (`data`); failures raise via
# get_success_data with a setup-flavoured message.
# ---------------------------------------------------------------------------

def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock (StateAdmin-only, unprefixed endpoint)."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_contract(api, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_contract(f.contract_payload(**overrides), ADMIN))


def get_contract(api, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, ADMIN))


def set_contract_status(api, contract_id: str, to: str) -> Dict[str, Any]:
    return get_success_data(api.set_contract_status(contract_id, f.contract_status_payload(to), ADMIN))


def create_program(api, contract_id: str, program_type: str = "FOOD", **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_program(
        f.program_payload(contract_id, program_type=program_type, **overrides), ADMIN))


def list_contract_programs(api, contract_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(api.list_contract_programs(contract_id, ADMIN, params=params or None))


def run_allotment(api, contract_id: str, program_id: str,
                  benefit_month: str = f.DEFAULTS["BENEFIT_MONTH"],
                  amount_cents: int = f.DEFAULTS["ALLOTMENT_AMOUNT_CENTS"]) -> Dict[str, Any]:
    """Bulk posting run. Returns {created_count, skipped_count, posting_ids}."""
    return get_success_data(api.run_allotment(
        contract_id,
        f.allotment_run_payload(program_id, benefit_month=benefit_month, amount_cents=amount_cents),
        ADMIN))


def list_data_deliveries(api, contract_id: str, delivery_type: Optional[str] = None) -> List[Dict[str, Any]]:
    params = {"delivery_type": delivery_type} if delivery_type else None
    return get_success_data(api.list_data_deliveries(contract_id, ADMIN, params=params))


def create_retailer(api, contract_id: str,
                    retailer_name: str = f.DEFAULTS["RETAILER_NAME"],
                    acquirer_reference: str = f.DEFAULTS["ACQUIRER_REFERENCE"]) -> Dict[str, Any]:
    return get_success_data(api.create_retailer(
        f.retailer_payload(contract_id, retailer_name=retailer_name,
                           acquirer_reference=acquirer_reference), ADMIN))


def get_retailer(api, retailer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_retailer(retailer_id, ADMIN))


def set_retailer_status(api, retailer_id: str, to: str) -> Dict[str, Any]:
    return get_success_data(api.set_retailer_status(retailer_id, f.retailer_status_payload(to), ADMIN))


def upload_item_file(api, retailer_id: str,
                     entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Atomic item-file upload as the owning retailer. Default file: one
    food-eligible UPC 111111111111 effective 2026-08-01, open-ended."""
    return get_success_data(api.upload_item_file(
        retailer_id, f.item_file_payload(items=entries),
        make_retailer_system_headers(retailer_id)))


def list_retailer_items(api, retailer_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(api.list_retailer_items(retailer_id, ADMIN, params=params or None))


def create_case(api, contract_id: str,
                case_identifier: str = f.DEFAULTS["CASE_IDENTIFIER"],
                head_of_household_name: str = f.DEFAULTS["HEAD_OF_HOUSEHOLD_NAME"]) -> Dict[str, Any]:
    return get_success_data(api.create_case_account(
        f.case_account_payload(contract_id, case_identifier=case_identifier,
                               head_of_household_name=head_of_household_name), ADMIN))


def get_case(api, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_case_account(case_id, ADMIN))


def set_case_status(api, case_id: str, to: str) -> Dict[str, Any]:
    """OCC-aware case status change: reads the current version first (PRD §2.10)."""
    version = get_case(api, case_id)["version"]
    return get_success_data(api.set_case_status(
        case_id, f.case_status_payload(to, expected_case_account_version=version), ADMIN))


def list_case_purses(api, case_id: str, program_id: Optional[str] = None,
                     **params) -> List[Dict[str, Any]]:
    query = {"case_account_id": case_id}
    if program_id:
        query["program_id"] = program_id
    query.update(params)
    return get_success_data(api.list_purses(ADMIN, params=query))


def get_purse_for_program(api, case_id: str, program_id: str) -> Dict[str, Any]:
    purses = list_case_purses(api, case_id, program_id=program_id)
    if not purses:
        raise RuntimeError(
            f"Setup failed: no purse for case {case_id} and program {program_id}")
    return purses[0]


def get_purse(api, purse_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_purse(purse_id, ADMIN))


def list_ledger(api, purse_id: str, entry_type: Optional[str] = None,
                **params) -> List[Dict[str, Any]]:
    query = dict(params)
    if entry_type:
        query["entry_type"] = entry_type
    return get_success_data(api.list_purse_ledger(purse_id, ADMIN, params=query or None))


def list_postings(api, purse_id: str, posting_status: Optional[str] = None,
                  **params) -> List[Dict[str, Any]]:
    query = dict(params)
    if posting_status:
        query["posting_status"] = posting_status
    return get_success_data(api.list_purse_postings(purse_id, ADMIN, params=query or None))


def issue_card(api, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.create_card(f.card_payload(case_id), CSR_A))


def get_card(api, card_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_card(card_id, ADMIN))


def activate_card(api, card_id: str, case_id: str,
                  pin: str = f.DEFAULTS["PIN"]) -> Dict[str, Any]:
    """Activate as the owning cardholder (X-User-ID == CaseAccount.id)."""
    return get_success_data(api.activate_card(
        card_id, f.activate_card_payload(pin), make_cardholder_headers(case_id)))


def activate_card_as_csr(api, card_id: str, pin: str = f.DEFAULTS["PIN"],
                         csr_user_id: str = CSR_USER_A) -> Dict[str, Any]:
    return get_success_data(api.activate_card(
        card_id, f.activate_card_payload(pin), make_cardholder_services_headers(csr_user_id)))


def replace_card(api, card_id: str, case_id: str) -> Dict[str, Any]:
    """Replace as the owning cardholder; returns the new ISSUED successor card."""
    return get_success_data(api.replace_card(card_id, make_cardholder_headers(case_id)))


def replace_card_as_csr(api, card_id: str, csr_user_id: str = CSR_USER_A) -> Dict[str, Any]:
    return get_success_data(api.replace_card(card_id, make_cardholder_services_headers(csr_user_id)))


def reset_pin_as_csr(api, card_id: str, new_pin: str = f.DEFAULTS["NEW_PIN"],
                     csr_user_id: str = CSR_USER_A) -> Dict[str, Any]:
    return get_success_data(api.reset_pin(
        card_id, f.pin_reset_payload(new_pin=new_pin),
        make_cardholder_services_headers(csr_user_id)))


def reset_pin_as_cardholder(api, card_id: str, case_id: str,
                            new_pin: str = f.DEFAULTS["NEW_PIN"],
                            current_pin: str = f.DEFAULTS["PIN"]) -> Dict[str, Any]:
    return get_success_data(api.reset_pin(
        card_id, f.pin_reset_payload(new_pin=new_pin, current_pin=current_pin),
        make_cardholder_headers(case_id)))


def place_purchase(api, retailer_id: str, card_id: str,
                   items: Optional[List[Dict[str, Any]]] = None,
                   pin: str = f.DEFAULTS["PIN"]) -> Dict[str, Any]:
    """PURCHASE authorization as the owning retailer. Default cart: one unit of
    the food-eligible UPC at 100 cents."""
    return get_success_data(api.create_authorization(
        retailer_id, f.purchase_payload(card_id, pin=pin, items=items),
        make_retailer_system_headers(retailer_id)))


def place_withdrawal(api, retailer_id: str, card_id: str,
                     withdrawal_amount_cents: int = 500,
                     pin: str = f.DEFAULTS["PIN"]) -> Dict[str, Any]:
    return get_success_data(api.create_authorization(
        retailer_id, f.withdrawal_payload(card_id, pin=pin,
                                          withdrawal_amount_cents=withdrawal_amount_cents),
        make_retailer_system_headers(retailer_id)))


def void_authorization(api, txn_id: str, retailer_id: str) -> Dict[str, Any]:
    """Same-day void by the owning retailer (X-User-ID == transaction retailer)."""
    return get_success_data(api.void_authorization(txn_id, make_retailer_system_headers(retailer_id)))


def file_claim(api, case_id: str, card_id: str, authorization_ids: Sequence[str],
               claimed_amount_cents: int, *,
               incident_description: str = f.DEFAULTS["INCIDENT_DESCRIPTION"],
               freeze_purse: bool = True, filer: str = "cardholder",
               csr_user_id: str = CSR_USER_A) -> Dict[str, Any]:
    """File a skimming claim. filer='cardholder' files as the owning case;
    filer='csr' files as the named CardholderServices operator (drives SOD)."""
    payload = f.claim_payload(case_id, card_id, list(authorization_ids), claimed_amount_cents,
                              incident_description=incident_description, freeze_purse=freeze_purse)
    if filer == "cardholder":
        headers = make_cardholder_headers(case_id)
    elif filer == "csr":
        headers = make_cardholder_services_headers(csr_user_id)
    else:
        raise ValueError("filer must be 'cardholder' or 'csr'")
    return get_success_data(api.file_claim(payload, headers))


def list_case_claims(api, case_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(api.list_case_claims(case_id, ADMIN, params=params or None))


def list_case_cards(api, case_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(api.list_case_cards(case_id, ADMIN, params=params or None))


def investigate_claim(api, claim_id: str, csr_user_id: str = CSR_USER_B) -> Dict[str, Any]:
    """FILED -> UNDER_INVESTIGATION by a CSR. Default csr-b so a claim filed by
    csr-a satisfies segregation of duties (PRD §3.8)."""
    return get_success_data(api.set_claim_status(
        claim_id, f.claim_status_payload("UNDER_INVESTIGATION"),
        make_cardholder_services_headers(csr_user_id)))


def adjudicate_claim(api, claim_id: str, to: str = "SUBSTANTIATED", *,
                     substantiated_amount_cents: Optional[int] = None) -> Dict[str, Any]:
    """UNDER_INVESTIGATION -> SUBSTANTIATED / UNSUBSTANTIATED by StateAdmin."""
    return get_success_data(api.set_claim_status(
        claim_id, f.claim_status_payload(to, substantiated_amount_cents=substantiated_amount_cents),
        ADMIN))


def list_batches(api, contract_id: Optional[str] = None, **params) -> List[Dict[str, Any]]:
    query = dict(params)
    if contract_id:
        query["contract_id"] = contract_id
    return get_success_data(api.list_settlement_batches(ADMIN, params=query or None))


def first_batch(api, contract_id: str) -> Dict[str, Any]:
    batches = list_batches(api, contract_id=contract_id)
    if not batches:
        raise RuntimeError(f"Setup failed: no settlement batch for contract {contract_id}")
    return batches[0]


def get_batch(api, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_settlement_batch(batch_id, ADMIN))


def reconcile_batch(api, batch_id: str, actual_settled_cents: int) -> Dict[str, Any]:
    return get_success_data(api.reconcile_batch(
        batch_id, f.reconcile_payload(actual_settled_cents), ADMIN))


def file_dispute(api, batch_id: str, retailer_id: str, disputed_amount_cents: int,
                 reason: str = f.DEFAULTS["DISPUTE_REASON"]) -> Dict[str, Any]:
    """Retailer-filed dispute as the owning retailer (X-User-ID == Retailer.id)."""
    return get_success_data(api.file_dispute(
        f.dispute_payload(batch_id, disputed_amount_cents, reason=reason),
        make_retailer_system_headers(retailer_id)))


def list_batch_disputes(api, batch_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(api.list_batch_disputes(batch_id, ADMIN, params=params or None))


def decide_dispute(api, dispute_id: str, to: str = "UPHELD", *,
                   adjustment_cents: Optional[int] = None) -> Dict[str, Any]:
    return get_success_data(api.set_dispute_status(
        dispute_id, f.dispute_status_payload(to, adjustment_cents=adjustment_cents), ADMIN))


# ---------------------------------------------------------------------------
# Composite fixtures. Each composes the primitives above into the shared
# preambles the design recipes repeat; every knob a test controls is a
# keyword argument with a recipe-matching default.
# ---------------------------------------------------------------------------

def setup_active_contract(api, *, program_types=("FOOD",), contract_overrides=None,
                          program_overrides=None, activate=True) -> Ctx:
    """Contract (+ programs) standing up at the server-default clock.

    program_types: e.g. ("FOOD",), ("FOOD", "CASH"), ("CASH",),
    ("FOOD", "DISASTER"). A DISASTER program defaults to the closed window
    2026-09-01..2026-10-31; per-type overrides go in
    program_overrides={"DISASTER": {...}}. activate=True drives
    CONFIGURING -> ACTIVE (requires at least one program) and returns the
    contract in its post-activation form.
    """
    contract = create_contract(api, **(contract_overrides or {}))
    programs: Dict[str, Any] = {}
    for ptype in program_types:
        overrides = dict((program_overrides or {}).get(ptype, {}))
        if ptype == "DISASTER":
            overrides.setdefault("disaster_window_start", DEFAULT_DISASTER_WINDOW[0])
            overrides.setdefault("disaster_window_end", DEFAULT_DISASTER_WINDOW[1])
        programs[ptype] = create_program(api, contract["id"], program_type=ptype, **overrides)
    if activate:
        contract = set_contract_status(api, contract["id"], "ACTIVE")
    return Ctx(contract=contract, programs=programs)


def add_retailer(api, ctx, *, retailer_name: str = f.DEFAULTS["RETAILER_NAME"],
                 acquirer_reference: str = f.DEFAULTS["ACQUIRER_REFERENCE"],
                 item_entries: Optional[List[Dict[str, Any]]] = None,
                 with_item_file: bool = True, key: str = "retailer") -> Dict[str, Any]:
    """Onboard a retailer into ctx.contract and (optionally) upload its item
    file as that retailer. Stored under ctx[key] ('retailer' by default)."""
    retailer = create_retailer(api, ctx["contract"]["id"], retailer_name=retailer_name,
                               acquirer_reference=acquirer_reference)
    ctx[key] = retailer
    if with_item_file:
        upload_item_file(api, retailer["id"], item_entries)
    return retailer


def add_case(api, ctx, *, case_identifier: str = f.DEFAULTS["CASE_IDENTIFIER"],
             head_of_household_name: str = f.DEFAULTS["HEAD_OF_HOUSEHOLD_NAME"],
             key: str = "case", load_purses: bool = True) -> Dict[str, Any]:
    """Open a case in ctx.contract (one OPEN purse per ACTIVE program).
    For the primary case (key='case') the purses are loaded into
    ctx['purses'] keyed by program type. Additional cases pass a distinct key
    and read purses via get_purse_for_program()."""
    case = create_case(api, ctx["contract"]["id"], case_identifier=case_identifier,
                       head_of_household_name=head_of_household_name)
    ctx[key] = case
    if load_purses and key == "case":
        ctx["purses"] = {
            ptype: get_purse_for_program(api, case["id"], program["id"])
            for ptype, program in ctx["programs"].items()
        }
    return case


def fund_case(api, ctx, *, allotments=_ALLOTMENTS_DEFAULT,
              benefit_month: str = f.DEFAULTS["BENEFIT_MONTH"],
              amount_cents: int = f.DEFAULTS["ALLOTMENT_AMOUNT_CENTS"]) -> Dict[str, Any]:
    """Run one allotment per named program. allotments maps program_type ->
    amount_cents; the default funds every program of the ctx at amount_cents;
    {} or None runs nothing. Returns {program_type: run_data} and stores it on
    ctx['allotment_runs']."""
    if allotments == _ALLOTMENTS_DEFAULT:
        allotments = {ptype: amount_cents for ptype in ctx["programs"]}
    runs: Dict[str, Any] = {}
    for ptype, amount in (allotments or {}).items():
        runs[ptype] = run_allotment(api, ctx["contract"]["id"], ctx["programs"][ptype]["id"],
                                    benefit_month=benefit_month, amount_cents=amount)
    ctx["allotment_runs"] = runs
    return runs


def add_active_card(api, ctx, *, pin: str = f.DEFAULTS["PIN"],
                    activate_at: Optional[str] = None,
                    case_key: str = "case", card_key: str = "card") -> Dict[str, Any]:
    """Issue the initial card (as CardholderServices) at the current clock,
    advance the clock past the mail delay, then activate as the owning
    cardholder. activate_at defaults to issuance + card_mail_delay_hours + 1h,
    floored at the canonical activity clock 2026-09-02T12:00:00Z — always
    forward-moving and always past the mail sweep. Stored under
    ctx[card_key]; the pin under ctx['pin']."""
    case = ctx[case_key]
    card = issue_card(api, case["id"])
    target = activate_at or _earliest_activation_clock(card)
    set_clock(api, target)
    card = activate_card(api, card["id"], case["id"], pin=pin)
    ctx[card_key] = card
    ctx["pin"] = pin
    return card


def place_purchases(api, ctx, specs=None, *, count: Optional[int] = None,
                    unit_price_cents: int = 100, upc: str = f.DEFAULTS["FOOD_UPC"],
                    quantity: int = 1, pin: Optional[str] = None,
                    retailer_key: str = "retailer", card_key: str = "card") -> List[Dict[str, Any]]:
    """Place PURCHASE authorizations as ctx's retailer against ctx's card.

    specs is a list where each element is either a ready list of purchase_item
    dicts or a kwargs dict for a single line item. Without specs, `count`
    purchases of `quantity` x `unit_price_cents` of `upc` are placed.
    Returns the transaction dicts (also stored on ctx['txns'])."""
    retailer = ctx[retailer_key]
    card = ctx[card_key]
    use_pin = pin or ctx.get("pin", f.DEFAULTS["PIN"])
    if specs is None:
        n = count or 1
        specs = [{"upc": upc, "quantity": quantity, "unit_price_cents": unit_price_cents}
                 for _ in range(n)]
    txns: List[Dict[str, Any]] = []
    for spec in specs:
        items = spec if isinstance(spec, list) else [f.purchase_item(**spec)]
        txns.append(place_purchase(api, retailer["id"], card["id"], items=items, pin=use_pin))
    ctx["txns"] = txns
    return txns


def settle_authorizations(api, ctx, *, cutoff_at: str = DEFAULT_CUTOFF_CLOCK) -> List[Dict[str, Any]]:
    """Advance the clock across a settlement cutoff and return the contract's
    batches (ctx['batches']). With the default cutoff hour 0, the canonical
    2026-09-03T00:00:00Z settles every AUTHORIZED transaction of 2026-09-02."""
    set_clock(api, cutoff_at)
    batches = list_batches(api, contract_id=ctx["contract"]["id"])
    ctx["batches"] = batches
    return batches


def setup_pos_ready(api, *, program_types=("FOOD",), contract_overrides=None,
                    program_overrides=None,
                    retailer_name: str = f.DEFAULTS["RETAILER_NAME"],
                    acquirer_reference: str = f.DEFAULTS["ACQUIRER_REFERENCE"],
                    item_entries: Optional[List[Dict[str, Any]]] = None,
                    with_item_file: bool = True,
                    case_identifier: str = f.DEFAULTS["CASE_IDENTIFIER"],
                    head_of_household_name: str = f.DEFAULTS["HEAD_OF_HOUSEHOLD_NAME"],
                    pre_case_clock: Optional[str] = None,
                    allotments=_ALLOTMENTS_DEFAULT,
                    benefit_month: str = f.DEFAULTS["BENEFIT_MONTH"],
                    allotment_amount_cents: int = f.DEFAULTS["ALLOTMENT_AMOUNT_CENTS"],
                    pin: str = f.DEFAULTS["PIN"],
                    activate_at: Optional[str] = None) -> Ctx:
    """The dominant recipe preamble in one call: contract + programs (ACTIVE),
    retailer + item file, case + purses, allotment runs, and an activated card.

    pre_case_clock advances the clock before case creation (first-month
    proration setups). allotments={} skips allotment runs entirely. Returns a
    Ctx with keys: contract, programs, retailer, case, purses, card, pin,
    allotment_runs."""
    ctx = setup_active_contract(api, program_types=program_types,
                                contract_overrides=contract_overrides,
                                program_overrides=program_overrides)
    add_retailer(api, ctx, retailer_name=retailer_name,
                 acquirer_reference=acquirer_reference,
                 item_entries=item_entries, with_item_file=with_item_file)
    if pre_case_clock is not None:
        set_clock(api, pre_case_clock)
    add_case(api, ctx, case_identifier=case_identifier,
             head_of_household_name=head_of_household_name)
    if allotments is not None and allotments != {}:
        fund_case(api, ctx, allotments=allotments, benefit_month=benefit_month,
                  amount_cents=allotment_amount_cents)
    add_active_card(api, ctx, pin=pin, activate_at=activate_at)
    return ctx


def setup_settled_batch(api, *, purchase_specs=None, cutoff_at: str = DEFAULT_CUTOFF_CLOCK,
                        **pos_kwargs) -> Ctx:
    """setup_pos_ready + purchases + one settlement cutoff. ctx gains 'txns',
    'batches', and 'batch' (the first batch of the contract). Default: one
    1000-cent food purchase on 2026-09-02 settled at 2026-09-03T00:00:00Z
    (gross 1000, fee 8, net 992 under default config)."""
    ctx = setup_pos_ready(api, **pos_kwargs)
    if purchase_specs is None:
        purchase_specs = [{"unit_price_cents": 1000}]
    place_purchases(api, ctx, purchase_specs)
    settle_authorizations(api, ctx, cutoff_at=cutoff_at)
    ctx["batch"] = first_batch(api, ctx["contract"]["id"])
    return ctx


def file_claim_on(api, ctx, txns, claimed_amount_cents: int, *,
                  freeze_purse: bool = True,
                  incident_description: str = f.DEFAULTS["INCIDENT_DESCRIPTION"],
                  filer: str = "cardholder", csr_user_id: str = CSR_USER_A,
                  case_key: str = "case", card_key: str = "card") -> Dict[str, Any]:
    """File a skimming claim against ctx's case/card referencing the given
    transaction dicts (a single dict or a list). Stores ctx['claim']."""
    if isinstance(txns, dict):
        txns = [txns]
    case = ctx[case_key]
    card = ctx[card_key]
    claim = file_claim(api, case["id"], card["id"], [t["id"] for t in txns],
                       claimed_amount_cents,
                       incident_description=incident_description,
                       freeze_purse=freeze_purse, filer=filer, csr_user_id=csr_user_id)
    ctx["claim"] = claim
    return claim


def setup_purchase_and_claim(api, *, purchase_price_cents: int = 500,
                             claimed_amount_cents: Optional[int] = None,
                             freeze_purse: bool = False,
                             filer: str = "cardholder", csr_user_id: str = CSR_USER_A,
                             **pos_kwargs) -> Ctx:
    """setup_pos_ready + one purchase + one claim referencing it.
    Covers the claim-lifecycle preambles (investigation, adjudication, SOD,
    case-close gating). ctx gains 'txns' and 'claim'."""
    ctx = setup_pos_ready(api, **pos_kwargs)
    place_purchases(api, ctx, [{"unit_price_cents": purchase_price_cents}])
    file_claim_on(api, ctx, ctx["txns"],
                  claimed_amount_cents if claimed_amount_cents is not None else purchase_price_cents,
                  freeze_purse=freeze_purse, filer=filer, csr_user_id=csr_user_id)
    return ctx


__all__ = [name for name in dir() if not name.startswith("_") and name not in (
    "datetime", "timedelta", "timezone", "Any", "Dict", "List", "Optional",
    "Sequence", "get_success_data", "f", "make_cardholder_headers",
    "make_cardholder_services_headers", "make_retailer_system_headers",
    "TEST_USERS", "CARD_MAIL_DELAY_HOURS")]
