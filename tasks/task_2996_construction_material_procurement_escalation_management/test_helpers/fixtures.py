"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its preconditions
from scratch using only endpoints the PRD declares. Setup calls go through
get_success_data() so a broken precondition surfaces as a clear "Setup step failed".

Money is always sent as a JSON number and instants always as full ISO 8601 UTC
instants with three fractional digits.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import iso_add_days, parse_instant, period_of
from .constants import TEST_DEFAULTS
from .factories import (
    cancel_commitment_payload,
    counter_escalation_agreement_payload,
    create_change_order_request_payload,
    create_disruption_event_payload,
    create_escalation_agreement_payload,
    create_index_reading_payload,
    create_material_package_payload,
    create_project_payload,
    create_purchase_commitment_payload,
    create_quote_payload,
    create_storage_arrangement_payload,
    create_storage_document_payload,
    create_substitution_request_payload,
    create_supplier_payload,
    delivery_posture_payload,
    disposition_change_order_payload,
    disposition_substitution_payload,
    propose_escalation_agreement_payload,
    rescind_substitution_payload,
    resubmit_substitution_payload,
    revise_quote_payload,
    revoke_storage_document_payload,
    set_clock_payload,
    suspend_supplier_payload,
)
from .test_users import TEST_USERS, make_supplier_rep_headers

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]
BUYOUT_MANAGER_2 = TEST_USERS["buyout_manager_2_headers"]
PROJECT_EXECUTIVE = TEST_USERS["project_executive_headers"]
DESIGN_ENGINEER = TEST_USERS["design_engineer_headers"]
OWNER_REP = TEST_USERS["owner_rep_headers"]

# Published readings shared by the escalation fixtures (PPI_STEEL_MILL).
DEFAULT_STEEL_READINGS = (
    ("2026-07", 310.00),
    ("2026-08", 322.00),
    ("2026-09", 331.00),
    ("2026-12", 344.50),
)


# ─── Tier 0: single-hop helpers ───────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock and return the clock response payload."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), BUYOUT_MANAGER)
    )


def open_project(**overrides) -> dict:
    return get_success_data(
        api_client.create_project(create_project_payload(**overrides), BUYOUT_MANAGER)
    )


def register_package(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_material_package(
            create_material_package_payload(project_id=project_id, **overrides),
            BUYOUT_MANAGER,
        )
    )


def register_supplier(**overrides) -> dict:
    return get_success_data(
        api_client.create_supplier(create_supplier_payload(**overrides), BUYOUT_MANAGER)
    )


def suspend_supplier(supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.suspend_supplier(
            supplier_id, suspend_supplier_payload(**overrides), PROJECT_EXECUTIVE
        )
    )


def log_disruption_event(supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_disruption_event(
            supplier_id, create_disruption_event_payload(**overrides), BUYOUT_MANAGER
        )
    )


def submit_quote(material_package_id: str, supplier_id: str, **overrides) -> dict:
    """Submit a quote as the SupplierRep that owns `supplier_id` (ownership-gated)."""
    return get_success_data(
        api_client.create_quote(
            create_quote_payload(
                material_package_id=material_package_id,
                supplier_id=supplier_id,
                **overrides,
            ),
            make_supplier_rep_headers(supplier_id),
        )
    )


def revise_quote(quote_id: str, supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.revise_quote(
            quote_id, revise_quote_payload(**overrides), make_supplier_rep_headers(supplier_id)
        )
    )


def publish_reading(index_code: str, period: str, value: float, published_at=None) -> dict:
    return get_success_data(
        api_client.create_index_reading(
            create_index_reading_payload(
                index_code=index_code,
                period=period,
                value=value,
                published_at=published_at or f"{period}-15T00:00:00.000Z",
            ),
            BUYOUT_MANAGER,
        )
    )


def publish_readings(index_code: str, readings) -> list:
    """Publish an iterable of (period, value) pairs for one index code."""
    return [publish_reading(index_code, period, value) for period, value in readings]


def draft_clause(quote_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_escalation_agreement(
            create_escalation_agreement_payload(quote_id=quote_id, **overrides),
            BUYOUT_MANAGER,
        )
    )


def propose_clause(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.propose_escalation_agreement(
            agreement_id, propose_escalation_agreement_payload(**overrides), BUYOUT_MANAGER
        )
    )


def counter_clause(agreement_id: str, supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.counter_escalation_agreement(
            agreement_id,
            counter_escalation_agreement_payload(**overrides),
            make_supplier_rep_headers(supplier_id),
        )
    )


def execute_clause(agreement_id: str) -> dict:
    return get_success_data(
        api_client.execute_escalation_agreement(agreement_id, PROJECT_EXECUTIVE)
    )


def read_project_version(project_id: str) -> int:
    """The project's current `version` — the OCC token a buyout must pin."""
    return get_success_data(api_client.get_project(project_id, BUYOUT_MANAGER))["version"]


def issue_commitment(project_id: str, quote_id: str, **overrides) -> dict:
    """Issue a purchase commitment, pinning the project's freshly read version."""
    payload = create_purchase_commitment_payload(
        quote_id=quote_id,
        expected_project_version=read_project_version(project_id),
        **overrides,
    )
    return get_success_data(api_client.create_purchase_commitment(payload, BUYOUT_MANAGER))


def countersign_commitment(commitment_id: str) -> dict:
    return get_success_data(
        api_client.commit_purchase_commitment(commitment_id, PROJECT_EXECUTIVE)
    )


def move_posture(commitment_id: str, to_posture: str) -> dict:
    return get_success_data(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload(to_posture), BUYOUT_MANAGER
        )
    )


def cancel_commitment(commitment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_purchase_commitment(
            commitment_id, cancel_commitment_payload(**overrides), PROJECT_EXECUTIVE
        )
    )


def arrange_storage(purchase_commitment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_storage_arrangement(
            create_storage_arrangement_payload(
                purchase_commitment_id=purchase_commitment_id, **overrides
            ),
            BUYOUT_MANAGER,
        )
    )


def file_document(arrangement_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_storage_document(
            arrangement_id,
            create_storage_document_payload(**overrides),
            headers or BUYOUT_MANAGER,
        )
    )


def list_documents(arrangement_id: str, params=None) -> list:
    """The document list is the only way to discover a document's identifier."""
    body = api_client.list_storage_documents(arrangement_id, BUYOUT_MANAGER, params=params)
    return get_success_data(body)


def revoke_document(document_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.revoke_storage_document(
            document_id, revoke_storage_document_payload(**overrides), BUYOUT_MANAGER
        )
    )


def raise_substitution(material_package_id: str, proposed_supplier_id: str, **overrides) -> dict:
    headers = overrides.pop("headers", None) or BUYOUT_MANAGER
    return get_success_data(
        api_client.create_substitution_request(
            create_substitution_request_payload(
                material_package_id=material_package_id,
                proposed_supplier_id=proposed_supplier_id,
                **overrides,
            ),
            headers,
        )
    )


def dispose_substitution(request_id: str, disposition: str, **overrides) -> dict:
    return get_success_data(
        api_client.disposition_substitution_request(
            request_id, disposition_substitution_payload(disposition, **overrides), DESIGN_ENGINEER
        )
    )


def resubmit_substitution(request_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.resubmit_substitution_request(
            request_id, resubmit_substitution_payload(**overrides), BUYOUT_MANAGER
        )
    )


def rescind_substitution(request_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.rescind_substitution_request(
            request_id, rescind_substitution_payload(**overrides), BUYOUT_MANAGER
        )
    )


def prepare_change_order(purchase_commitment_id: str, headers=None, **overrides) -> dict:
    """Prepared by the first BuyoutManager operator by default."""
    return get_success_data(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=purchase_commitment_id, **overrides
            ),
            headers or BUYOUT_MANAGER,
        )
    )


def submit_change_order(request_id: str, headers=None) -> dict:
    """Submitted by the SECOND BuyoutManager operator — segregation of duties."""
    return get_success_data(
        api_client.submit_change_order_request(request_id, headers or BUYOUT_MANAGER_2)
    )


def dispose_change_order(request_id: str, disposition: str, **overrides) -> dict:
    return get_success_data(
        api_client.disposition_change_order_request(
            request_id, disposition_change_order_payload(disposition, **overrides), OWNER_REP
        )
    )


# ─── Read-back helpers ────────────────────────────────────────────────────

def read_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, BUYOUT_MANAGER))


def read_package(package_id: str) -> dict:
    return get_success_data(api_client.get_material_package(package_id, BUYOUT_MANAGER))


def read_supplier(supplier_id: str) -> dict:
    return get_success_data(api_client.get_supplier(supplier_id, BUYOUT_MANAGER))


def read_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, BUYOUT_MANAGER))


def read_clause(agreement_id: str) -> dict:
    return get_success_data(
        api_client.get_escalation_agreement(agreement_id, BUYOUT_MANAGER)
    )


def read_commitment(commitment_id: str) -> dict:
    return get_success_data(
        api_client.get_purchase_commitment(commitment_id, BUYOUT_MANAGER)
    )


def read_arrangement(arrangement_id: str) -> dict:
    return get_success_data(
        api_client.get_storage_arrangement(arrangement_id, BUYOUT_MANAGER)
    )


def read_substitution(request_id: str) -> dict:
    return get_success_data(
        api_client.get_substitution_request(request_id, BUYOUT_MANAGER)
    )


def read_change_order(request_id: str) -> dict:
    return get_success_data(
        api_client.get_change_order_request(request_id, BUYOUT_MANAGER)
    )


def read_disruption_events(supplier_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_disruption_events(supplier_id, BUYOUT_MANAGER, params=params)
    )


# ─── Tier 1: the buyout chain ─────────────────────────────────────────────

def build_buyout_scenario(
    *,
    project_overrides=None,
    package_overrides=None,
    supplier_overrides=None,
    quote_overrides=None,
    clause_overrides=None,
    counter_overrides=None,
    commitment_overrides=None,
    index_code=None,
    readings=DEFAULT_STEEL_READINGS,
    clause_stage="EXECUTED",
    attach_clause=True,
    issue=True,
    countersign=True,
) -> dict:
    """Build project → package → supplier → quote → clause → commitment.

    `clause_stage` is one of "NONE", "DRAFT", "PROPOSED", "COUNTERED" or "EXECUTED"
    and drives how far the negotiation is carried. `attach_clause` controls whether the
    commitment references the clause; a flat purchase order sets it False (or uses
    clause_stage="NONE"). Nothing here advances the clock.
    """
    project = open_project(**(project_overrides or {}))
    package = register_package(project["id"], **(package_overrides or {}))
    supplier = register_supplier(**(supplier_overrides or {}))
    code = index_code or package["commodity_index_code"]
    published = publish_readings(code, readings) if readings else []
    quote = submit_quote(package["id"], supplier["id"], **(quote_overrides or {}))

    agreement = None
    if clause_stage != "NONE":
        clause_kwargs = dict(clause_overrides or {})
        clause_kwargs.setdefault("index_code", code)
        agreement = draft_clause(quote["id"], **clause_kwargs)
        if clause_stage in ("PROPOSED", "COUNTERED", "EXECUTED"):
            agreement = propose_clause(agreement["id"])
        if clause_stage == "COUNTERED":
            agreement = counter_clause(
                agreement["id"], supplier["id"], **(counter_overrides or {})
            )
        if clause_stage == "EXECUTED":
            agreement = execute_clause(agreement["id"])

    commitment = None
    if issue:
        commitment_kwargs = dict(commitment_overrides or {})
        if agreement is not None and attach_clause:
            commitment_kwargs.setdefault("escalation_agreement_id", agreement["id"])
        commitment = issue_commitment(project["id"], quote["id"], **commitment_kwargs)
        if countersign:
            commitment = countersign_commitment(commitment["id"])

    return {
        "project": project,
        "package": package,
        "supplier": supplier,
        "quote": quote,
        "agreement": agreement,
        "commitment": commitment,
        "readings": published,
        "index_code": code,
    }


def build_released_scenario(*, release_at="2026-09-10T00:00:00.000Z", **scenario_kwargs) -> dict:
    """A countersigned commitment released for fabrication at `release_at`.

    Release is the step that first recognises escalation, so the clock is moved to a
    month for which a reading has been published before the posture move is requested.
    """
    scenario = build_buyout_scenario(**scenario_kwargs)
    set_clock(release_at)
    scenario["commitment"] = move_posture(scenario["commitment"]["id"], "RELEASED_FOR_FAB")
    scenario["released_at"] = release_at
    return scenario


def build_fabricating_scenario(*, release_at="2026-09-10T00:00:00.000Z", **scenario_kwargs) -> dict:
    """A released commitment moved on to FABRICATING (which touches nothing else)."""
    scenario = build_released_scenario(release_at=release_at, **scenario_kwargs)
    scenario["commitment"] = move_posture(scenario["commitment"]["id"], "FABRICATING")
    return scenario


# ─── Tier 2: storage ──────────────────────────────────────────────────────

def file_mandatory_documents(
    arrangement_id: str,
    stored_value: float,
    *,
    effective_date="2026-09-01T00:00:00.000Z",
    expires_at="2027-09-01T00:00:00.000Z",
    verified=True,
    headers=None,
) -> list:
    """File one verified document of each of the three mandatory types.

    The insurance certificate carries coverage at least the arrangement's stored value,
    without which the filing itself is refused.
    """
    filings = [
        {"doc_type": "BAILMENT_AGREEMENT", "reference_number": "BAIL-2996-0001"},
        {
            "doc_type": "INSURANCE_CERTIFICATE",
            "reference_number": "INS-2996-0001",
            "coverage_amount": stored_value,
        },
        {"doc_type": "LIEN_WAIVER", "reference_number": "LIEN-2996-0001"},
    ]
    documents = []
    for filing in filings:
        documents.append(
            file_document(
                arrangement_id,
                headers=headers,
                effective_date=effective_date,
                expires_at=expires_at,
                verified=verified,
                **filing,
            )
        )
    return documents


def build_documented_storage_scenario(
    *,
    release_at="2026-09-10T00:00:00.000Z",
    stored_from="2026-09-20T00:00:00.000Z",
    planned_release_date="2026-12-31T00:00:00.000Z",
    stored_value=862500.00,
    monthly_storage_rate_pct=0.1875,
    warehouse_name=None,
    arrangement_overrides=None,
    doc_effective_date="2026-09-01T00:00:00.000Z",
    doc_expires_at="2027-09-01T00:00:00.000Z",
    **scenario_kwargs,
) -> dict:
    """An early-buyout commitment at FABRICATING with an ACTIVE, fully documented arrangement.

    The clock is left at `release_at`; the caller moves it to `stored_from` before asking
    for the STORED_OFFSITE posture. Documentation is filed while the arrangement is DRAFT,
    which is what lifts it to ACTIVE / COMPLETE.
    """
    commitment_overrides = dict(scenario_kwargs.pop("commitment_overrides", None) or {})
    commitment_overrides.setdefault("is_early_buyout", True)
    scenario = build_fabricating_scenario(
        release_at=release_at, commitment_overrides=commitment_overrides, **scenario_kwargs
    )

    arrangement_kwargs = dict(arrangement_overrides or {})
    arrangement_kwargs.setdefault("stored_from", stored_from)
    arrangement_kwargs.setdefault("planned_release_date", planned_release_date)
    arrangement_kwargs.setdefault("stored_value", stored_value)
    arrangement_kwargs.setdefault("monthly_storage_rate_pct", monthly_storage_rate_pct)
    if warehouse_name is not None:
        arrangement_kwargs.setdefault("warehouse_name", warehouse_name)
    arrangement = arrange_storage(scenario["commitment"]["id"], **arrangement_kwargs)

    documents = file_mandatory_documents(
        arrangement["id"],
        arrangement_kwargs["stored_value"],
        effective_date=doc_effective_date,
        expires_at=doc_expires_at,
    )
    scenario["arrangement"] = read_arrangement(arrangement["id"])
    scenario["documents"] = documents
    scenario["stored_from"] = arrangement_kwargs["stored_from"]
    return scenario


def build_stored_offsite_scenario(
    *, stored_from="2026-09-20T00:00:00.000Z", **kwargs
) -> dict:
    """A fully documented arrangement with the commitment moved to STORED_OFFSITE.

    The clock is advanced to `stored_from`, which is the earliest instant the posture
    move is permitted.
    """
    scenario = build_documented_storage_scenario(stored_from=stored_from, **kwargs)
    set_clock(stored_from)
    scenario["commitment"] = move_posture(scenario["commitment"]["id"], "STORED_OFFSITE")
    scenario["arrangement"] = read_arrangement(scenario["arrangement"]["id"])
    return scenario


# ─── Tier 3: delivery, final escalation and the owner claim ───────────────

def build_delivered_scenario(
    *,
    release_at="2026-09-10T00:00:00.000Z",
    deliver_at="2026-12-20T00:00:00.000Z",
    **scenario_kwargs,
) -> dict:
    """A commitment carried all the way to DELIVERED with FINAL escalation.

    Delivery is taken from FABRICATING, so the commitment must not be an early buyout.
    `deliver_at` sits in a month for which a reading has been published, because delivery
    demands a reading for exactly the clock month with no look-back.
    """
    scenario = build_fabricating_scenario(release_at=release_at, **scenario_kwargs)
    set_clock(deliver_at)
    scenario["commitment"] = move_posture(scenario["commitment"]["id"], "DELIVERED")
    scenario["delivered_at"] = deliver_at
    return scenario


def build_prepared_change_order_scenario(
    *, claimed_amount=60000.00, change_order_overrides=None, **scenario_kwargs
) -> dict:
    """A DELIVERED commitment with a PREPARED change order against its FINAL escalation."""
    scenario = build_delivered_scenario(**scenario_kwargs)
    change_order_kwargs = dict(change_order_overrides or {})
    change_order_kwargs.setdefault("claimed_amount", claimed_amount)
    scenario["change_order"] = prepare_change_order(
        scenario["commitment"]["id"], **change_order_kwargs
    )
    return scenario


def build_submitted_change_order_scenario(**kwargs) -> dict:
    """A change order carried to SUBMITTED by a second BuyoutManager operator."""
    scenario = build_prepared_change_order_scenario(**kwargs)
    scenario["change_order"] = submit_change_order(scenario["change_order"]["id"])
    return scenario


# ─── Tier 4: suppliers, exposure and substitutions ───────────────────────

def build_exposed_supplier(*, supplier_overrides=None, events=()) -> dict:
    """Register a supplier and log a sequence of disruption events against it.

    `events` is an iterable of payload override dicts, each one a distinct event, so a
    caller can set the effective_date on either side of the clock to separate the
    snapshot exposure reading from the forward-looking one.
    """
    supplier = register_supplier(**(supplier_overrides or {}))
    logged = [log_disruption_event(supplier["id"], **overrides) for overrides in events]
    return {"supplier": supplier, "events": logged}


def build_substitution_scenario(
    *,
    project_overrides=None,
    package_overrides=None,
    incumbent_overrides=None,
    substitute_overrides=None,
    quote_overrides=None,
    request_overrides=None,
    submit_incumbent_quote=True,
) -> dict:
    """A package with an incumbent supplier and a SUBMITTED substitution naming a second one.

    The two suppliers are distinct rows, so the proposed supplier is never the one the
    package is already committed to.
    """
    project = open_project(**(project_overrides or {}))
    package = register_package(project["id"], **(package_overrides or {}))
    incumbent = register_supplier(**(incumbent_overrides or {}))
    substitute_kwargs = dict(substitute_overrides or {})
    substitute_kwargs.setdefault("legal_name", "Cascade Plate & Structural Inc")
    substitute = register_supplier(**substitute_kwargs)

    quote = None
    if submit_incumbent_quote:
        quote = submit_quote(package["id"], incumbent["id"], **(quote_overrides or {}))

    request = raise_substitution(
        package["id"], substitute["id"], **(request_overrides or {})
    )
    return {
        "project": project,
        "package": package,
        "incumbent": incumbent,
        "substitute": substitute,
        "quote": quote,
        "request": request,
    }


def build_contingency_substitution_scenario(
    *,
    event_overrides=None,
    request_overrides=None,
    **scenario_kwargs,
) -> dict:
    """A DISRUPTION_CONTINGENCY substitution bound to an OPEN event on the incumbent.

    The event must belong to the supplier the package is quoted against, which is why the
    incumbent quote is submitted before the event is logged and the request raised.
    """
    project = open_project(**(scenario_kwargs.pop("project_overrides", None) or {}))
    package = register_package(
        project["id"], **(scenario_kwargs.pop("package_overrides", None) or {})
    )
    incumbent = register_supplier(**(scenario_kwargs.pop("incumbent_overrides", None) or {}))
    substitute_kwargs = dict(scenario_kwargs.pop("substitute_overrides", None) or {})
    substitute_kwargs.setdefault("legal_name", "Cascade Plate & Structural Inc")
    substitute = register_supplier(**substitute_kwargs)
    quote = submit_quote(
        package["id"], incumbent["id"], **(scenario_kwargs.pop("quote_overrides", None) or {})
    )
    event = log_disruption_event(incumbent["id"], **(event_overrides or {}))

    request_kwargs = dict(request_overrides or {})
    request_kwargs.setdefault("driver", "DISRUPTION_CONTINGENCY")
    request_kwargs.setdefault("disruption_event_id", event["id"])
    request = raise_substitution(package["id"], substitute["id"], **request_kwargs)
    return {
        "project": project,
        "package": package,
        "incumbent": incumbent,
        "substitute": substitute,
        "quote": quote,
        "event": event,
        "request": request,
    }
