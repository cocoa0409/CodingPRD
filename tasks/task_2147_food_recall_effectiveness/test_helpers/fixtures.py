"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only the endpoints the PRD publishes.
Setup calls use the lenient validator so a broken precondition reports as a
setup failure rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_consignee_payload,
    create_cost_entry_payload,
    create_disposition_order_payload,
    create_distribution_record_payload,
    create_firm_payload,
    create_hazard_evaluation_payload,
    create_insurance_claim_payload,
    create_notification_payload,
    create_public_warning_payload,
    create_recall_payload,
    create_retrieval_receipt_payload,
    create_status_report_payload,
)
from .test_users import (
    make_adjuster_headers,
    make_coordinator_headers,
    make_firm_officer_headers,
    make_investigator_headers,
    make_panel_headers,
)

COORD_1 = "coord-1"
COORD_2 = "coord-2"
PANEL_1 = "panel-1"
INV_1 = "inv-1"
ADJ_1 = "adj-1"


def set_clock(to_iso8601: str, headers=None) -> dict:
    """Jump the server's logical clock. Every role may drive the clock."""
    headers = headers or make_coordinator_headers(COORD_1)
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def register_firm(**overrides) -> dict:
    """Register a recalling firm. Registration is a coordinator operation."""
    return get_success_data(
        api_client.create_firm(
            create_firm_payload(**overrides), make_coordinator_headers(COORD_1)
        )
    )


class RecallCase:
    """A single recall case file under construction.

    Identity threading: the acting FirmRecallOfficer's X-User-ID is the owning
    Firm's id, so every firm-side call in this builder uses
    make_firm_officer_headers(self.firm_id).
    """

    def __init__(self, agency="FDA", clock=None, firm=None, firm_overrides=None,
                 **recall_overrides):
        if clock is not None:
            set_clock(clock)
        self.firm = firm if firm is not None else register_firm(**(firm_overrides or {}))
        self.firm_id = self.firm["id"]
        self.officer = make_firm_officer_headers(self.firm_id)
        self.coordinator = make_coordinator_headers(COORD_1)
        self.second_coordinator = make_coordinator_headers(COORD_2)
        self.panel = make_panel_headers(PANEL_1)
        self.investigator = make_investigator_headers(INV_1)
        self.adjuster = make_adjuster_headers(ADJ_1)

        recall_overrides.setdefault("agency", agency)
        self.recall = get_success_data(
            api_client.create_recall(
                create_recall_payload(self.firm_id, **recall_overrides), self.officer
            )
        )
        self.recall_id = self.recall["id"]
        self.consignees = []
        self.distribution_records = []
        self.notifications = []
        self.receipts = []
        self.disposition_orders = []
        self.cost_entries = []
        self.evaluations = []

    # ─── Reads ────────────────────────────────────────

    def read_recall(self) -> dict:
        return get_success_data(api_client.get_recall(self.recall_id, self.coordinator))

    def read_consignee(self, consignee_id) -> dict:
        return get_success_data(api_client.get_consignee(consignee_id, self.coordinator))

    def recall_version(self) -> int:
        return self.read_recall()["version"]

    def consignee_version(self, consignee_id) -> int:
        return self.read_consignee(consignee_id)["version"]

    def status_reports(self) -> list:
        body = api_client.list_status_reports(
            self.recall_id, self.coordinator, params={"limit": 100}
        ).json()
        return body["data"]

    # ─── Hazard evaluation ────────────────────────────

    def file_evaluation(self, expected_recall_version=None, **overrides) -> dict:
        if expected_recall_version is None:
            expected_recall_version = self.recall_version()
        evaluation = get_success_data(
            api_client.create_hazard_evaluation(
                self.recall_id,
                create_hazard_evaluation_payload(expected_recall_version, **overrides),
                self.officer,
            )
        )
        self.evaluations.append(evaluation)
        return evaluation

    def submit_evaluation(self, evaluation_id) -> dict:
        return get_success_data(
            api_client.submit_hazard_evaluation(evaluation_id, self.officer)
        )

    def decide_evaluation(self, evaluation_id, decision="RATIFY", panel_note=None) -> dict:
        payload = {"decision": decision}
        if panel_note is not None:
            payload["panel_note"] = panel_note
        return get_success_data(
            api_client.decide_hazard_evaluation(evaluation_id, payload, self.panel)
        )

    def ratified_evaluation(self, **overrides) -> dict:
        """File → submit → ratify one evaluation and return the ratified row."""
        evaluation = self.file_evaluation(**overrides)
        self.submit_evaluation(evaluation["id"])
        return self.decide_evaluation(evaluation["id"], "RATIFY")

    # ─── Classification ───────────────────────────────

    def classify(self, hazard_class="CLASS_I", coordinator_id=COORD_1) -> dict:
        return get_success_data(
            api_client.classify_recall(
                self.recall_id,
                {"hazard_class": hazard_class},
                make_coordinator_headers(coordinator_id),
            )
        )

    def checkpoint(self, coordinator_id=COORD_1) -> dict:
        return get_success_data(
            api_client.run_checkpoint(
                self.recall_id, make_coordinator_headers(coordinator_id)
            )
        )

    # ─── Distribution tree ────────────────────────────

    def add_consignee(self, name="Metro Distributors", consignee_type="DISTRIBUTOR",
                      parent_consignee_id=None) -> dict:
        payload = create_consignee_payload(name=name, consignee_type=consignee_type)
        if parent_consignee_id is not None:
            payload["parent_consignee_id"] = parent_consignee_id
        consignee = get_success_data(
            api_client.create_consignee(self.recall_id, payload, self.officer)
        )
        self.consignees.append(consignee)
        return consignee

    def add_shipment(self, consignee_id, quantity_shipped, **overrides) -> dict:
        record = get_success_data(
            api_client.create_distribution_record(
                self.recall_id,
                create_distribution_record_payload(
                    consignee_id, quantity_shipped, **overrides
                ),
                self.officer,
            )
        )
        self.distribution_records.append(record)
        return record

    def reconcile(self, record_id, outcome, quantity_confirmed=None,
                  headers=None) -> dict:
        payload = {"outcome": outcome}
        if quantity_confirmed is not None:
            payload["quantity_confirmed"] = quantity_confirmed
        return get_success_data(
            api_client.reconcile_distribution_record(
                record_id, payload, headers or self.officer
            )
        )

    def confirmed_shipment(self, consignee_id, quantity_shipped, **overrides) -> dict:
        record = self.add_shipment(consignee_id, quantity_shipped, **overrides)
        return self.reconcile(record["id"], "CONFIRM")

    # ─── Notification ─────────────────────────────────

    def notify(self, consignee_id, method="EMAIL",
               expected_consignee_version=None) -> dict:
        if expected_consignee_version is None:
            expected_consignee_version = self.consignee_version(consignee_id)
        payload = create_notification_payload(
            consignee_id, expected_consignee_version, method=method
        )
        notification = get_success_data(
            api_client.create_notification(self.recall_id, payload, self.officer)
        )
        self.notifications.append(notification)
        return notification

    def record_delivery(self, notification_id, outcome="DELIVERED") -> dict:
        return get_success_data(
            api_client.record_delivery(
                notification_id, {"outcome": outcome}, self.officer
            )
        )

    def record_response(self, notification_id, outcome="ACKNOWLEDGED",
                        response_note=None) -> dict:
        payload = {"outcome": outcome}
        if response_note is not None:
            payload["response_note"] = response_note
        return get_success_data(
            api_client.record_response(notification_id, payload, self.officer)
        )

    def notify_delivered_and_acknowledged(self, consignee_id, method="EMAIL") -> dict:
        notification = self.notify(consignee_id, method=method)
        self.record_delivery(notification["id"], "DELIVERED")
        return self.record_response(notification["id"], "ACKNOWLEDGED")

    # ─── Retrieval accounting ─────────────────────────

    def file_receipt(self, consignee_id, quantity_returned=0,
                     quantity_destroyed_onsite=0, quantity_held_segregated=0,
                     quantity_unrecoverable=0) -> dict:
        receipt = get_success_data(
            api_client.create_retrieval_receipt(
                self.recall_id,
                create_retrieval_receipt_payload(
                    consignee_id,
                    quantity_returned=quantity_returned,
                    quantity_destroyed_onsite=quantity_destroyed_onsite,
                    quantity_held_segregated=quantity_held_segregated,
                    quantity_unrecoverable=quantity_unrecoverable,
                ),
                self.officer,
            )
        )
        self.receipts.append(receipt)
        return receipt

    def verify_receipt(self, receipt_id, decision="VERIFY",
                       verification_note=None) -> dict:
        payload = {"decision": decision}
        if verification_note is not None:
            payload["verification_note"] = verification_note
        return get_success_data(
            api_client.verify_retrieval_receipt(receipt_id, payload, self.investigator)
        )

    # ─── Disposition custody ──────────────────────────

    def propose_disposition(self, quantity, **overrides) -> dict:
        order = get_success_data(
            api_client.create_disposition_order(
                self.recall_id,
                create_disposition_order_payload(quantity, **overrides),
                self.officer,
            )
        )
        self.disposition_orders.append(order)
        return order

    def authorize_disposition(self, order_id, coordinator_id=COORD_1) -> dict:
        return get_success_data(
            api_client.authorize_disposition_order(
                order_id, make_coordinator_headers(coordinator_id)
            )
        )

    def execute_disposition(self, order_id, certificate_reference="COD-77120") -> dict:
        return get_success_data(
            api_client.execute_disposition_order(
                order_id, {"certificate_reference": certificate_reference}, self.officer
            )
        )

    def verify_disposition(self, order_id, decision="VERIFY",
                           verification_note=None) -> dict:
        payload = {"decision": decision}
        if verification_note is not None:
            payload["verification_note"] = verification_note
        return get_success_data(
            api_client.verify_disposition_order(order_id, payload, self.investigator)
        )

    # ─── Public communication ─────────────────────────

    def draft_warning(self, warning_type="PRESS_RELEASE", drafter_id=COORD_1,
                      **overrides) -> dict:
        return get_success_data(
            api_client.create_public_warning(
                self.recall_id,
                create_public_warning_payload(warning_type=warning_type, **overrides),
                make_coordinator_headers(drafter_id),
            )
        )

    def submit_warning(self, warning_id, coordinator_id=COORD_1) -> dict:
        return get_success_data(
            api_client.submit_public_warning(
                warning_id, make_coordinator_headers(coordinator_id)
            )
        )

    def review_warning(self, warning_id, decision="APPROVE", reviewer_id=COORD_2,
                       review_note=None) -> dict:
        payload = {"decision": decision}
        if review_note is not None:
            payload["review_note"] = review_note
        return get_success_data(
            api_client.review_public_warning(
                warning_id, payload, make_coordinator_headers(reviewer_id)
            )
        )

    def publish_warning(self, warning_id, coordinator_id=COORD_2) -> dict:
        return get_success_data(
            api_client.publish_public_warning(
                warning_id, make_coordinator_headers(coordinator_id)
            )
        )

    def approved_warning(self, warning_type="PRESS_RELEASE", **overrides) -> dict:
        """Draft (coord-1) → submit → approve (coord-2)."""
        warning = self.draft_warning(warning_type=warning_type, **overrides)
        self.submit_warning(warning["id"])
        return self.review_warning(warning["id"], "APPROVE", COORD_2)

    # ─── Status reporting ─────────────────────────────

    def file_status_report(self, period_start, period_end, **overrides) -> dict:
        return get_success_data(
            api_client.create_status_report(
                self.recall_id,
                create_status_report_payload(period_start, period_end, **overrides),
                self.officer,
            )
        )

    def submit_report(self, report_id, narrative="Retrieval progressing.") -> dict:
        return get_success_data(
            api_client.submit_status_report(
                report_id, {"narrative": narrative}, self.officer
            )
        )

    def adjudicate_report(self, report_id, decision="ACCEPT",
                          adjudication_note=None, coordinator_id=COORD_1) -> dict:
        payload = {"decision": decision}
        if adjudication_note is not None:
            payload["adjudication_note"] = adjudication_note
        return get_success_data(
            api_client.adjudicate_status_report(
                report_id, payload, make_coordinator_headers(coordinator_id)
            )
        )

    # ─── Cost and insurance ───────────────────────────

    def file_cost(self, category, amount_cents, description=None) -> dict:
        overrides = {"description": description} if description else {}
        entry = get_success_data(
            api_client.create_cost_entry(
                self.recall_id,
                create_cost_entry_payload(category, amount_cents, **overrides),
                self.officer,
            )
        )
        self.cost_entries.append(entry)
        return entry

    def adjudicate_cost(self, entry_id, decision="ACCEPT", adjudication_note=None,
                        coordinator_id=COORD_1) -> dict:
        payload = {"decision": decision}
        if adjudication_note is not None:
            payload["adjudication_note"] = adjudication_note
        return get_success_data(
            api_client.adjudicate_cost_entry(
                entry_id, payload, make_coordinator_headers(coordinator_id)
            )
        )

    def accepted_cost(self, category, amount_cents, description=None) -> dict:
        entry = self.file_cost(category, amount_cents, description)
        return self.adjudicate_cost(entry["id"], "ACCEPT")

    def open_claim(self, claim_reference="CLM-2026-0001") -> dict:
        return get_success_data(
            api_client.create_insurance_claim(
                self.recall_id,
                create_insurance_claim_payload(claim_reference=claim_reference),
                self.officer,
            )
        )

    def submit_claim(self, claim_id) -> dict:
        return get_success_data(
            api_client.submit_insurance_claim(claim_id, self.officer)
        )

    def adjudicate_claim(self, claim_id, decision="PAY_FULL", **extra) -> dict:
        payload = {"decision": decision}
        payload.update(extra)
        return get_success_data(
            api_client.adjudicate_insurance_claim(claim_id, payload, self.adjuster)
        )

    # ─── Closing the case ─────────────────────────────

    def request_termination(self, root_cause_code="SUPPLIER_INGREDIENT",
                            capa_summary="Supplier decertified; incoming lot testing added.") -> dict:
        return get_success_data(
            api_client.request_termination(
                self.recall_id,
                {"root_cause_code": root_cause_code, "capa_summary": capa_summary},
                self.officer,
            )
        )

    def decide_termination(self, decision="TERMINATE", coordinator_id=COORD_2) -> dict:
        return get_success_data(
            api_client.decide_termination(
                self.recall_id,
                {"decision": decision},
                make_coordinator_headers(coordinator_id),
            )
        )


# ─── Tier 1–2: state progression and hierarchy ────────


def draft_case(agency="FDA", clock=None, **recall_overrides) -> RecallCase:
    """One firm and one recall still in DRAFT."""
    return RecallCase(agency=agency, clock=clock, **recall_overrides)


def classified_case(agency="FDA", hazard_class="CLASS_I", clock=None,
                    evaluation_overrides=None, **recall_overrides) -> RecallCase:
    """Firm → recall → evaluation filed, submitted and ratified → classified."""
    case = RecallCase(agency=agency, clock=clock, **recall_overrides)
    case.ratified_evaluation(**(evaluation_overrides or {}))
    case.classify(hazard_class)
    return case


# ─── Tier 3: lifecycle shortcuts ──────────────────────


def case_with_confirmed_shipment(agency="FDA", hazard_class="CLASS_I",
                                 quantity_shipped=600, clock=None,
                                 lot_code="L-88A", **recall_overrides) -> RecallCase:
    """Classified recall, one tier-1 consignee, one CONFIRMED shipment line."""
    case = classified_case(
        agency=agency, hazard_class=hazard_class, clock=clock,
        lot_codes=[lot_code], **recall_overrides
    )
    consignee = case.add_consignee()
    case.confirmed_shipment(consignee["id"], quantity_shipped, lot_code=lot_code)
    case.c1 = consignee
    case.c1_id = consignee["id"]
    case.d1 = case.distribution_records[0]
    case.d1_id = case.d1["id"]
    return case


def case_in_retrieval_accounting(agency="USDA", quantity_shipped=1000, clock=None,
                                 lot_code="L-42B", **recall_overrides) -> RecallCase:
    """One tier-1 consignee notified, delivered and acknowledged, so the recall
    has auto-advanced out of notification into retrieval accounting."""
    case = case_with_confirmed_shipment(
        agency=agency, hazard_class="CLASS_I", quantity_shipped=quantity_shipped,
        clock=clock, lot_code=lot_code, **recall_overrides
    )
    case.n1 = case.notify_delivered_and_acknowledged(case.c1_id)
    case.n1_id = case.n1["id"]
    return case


# ─── Tier 4: accumulation and threshold targeting ─────


def case_with_verified_receipt(agency="USDA", quantity_shipped=1000,
                               quantity_returned=960, quantity_unrecoverable=40,
                               clock=None, lot_code="L-42B",
                               **recall_overrides) -> RecallCase:
    """Retrieval accounting plus one VERIFIED receipt, which is what carries the
    recall into effectiveness review once the target is met."""
    case = case_in_retrieval_accounting(
        agency=agency, quantity_shipped=quantity_shipped, clock=clock,
        lot_code=lot_code, **recall_overrides
    )
    receipt = case.file_receipt(
        case.c1_id,
        quantity_returned=quantity_returned,
        quantity_unrecoverable=quantity_unrecoverable,
    )
    case.rr1 = case.verify_receipt(receipt["id"], "VERIFY")
    case.rr1_id = receipt["id"]
    return case


# ─── Tier 5: finalization and terminal state ──────────


def case_in_termination_requested(clock="2026-09-01T00:00:00Z",
                                  root_cause_code="SUPPLIER_INGREDIENT",
                                  capa_summary="Supplier decertified; incoming lot testing added.",
                                  dispose_units=None) -> RecallCase:
    """Full lifecycle up to TERMINATION_REQUESTED with no open disposition order."""
    case = case_with_verified_receipt(clock=clock)
    if dispose_units:
        order = case.propose_disposition(dispose_units)
        case.authorize_disposition(order["id"])
        case.execute_disposition(order["id"])
        case.verify_disposition(order["id"], "VERIFY")
        case.do1_id = order["id"]
    case.request_termination(root_cause_code, capa_summary)
    return case


def terminated_case(clock="2026-09-01T00:00:00Z") -> RecallCase:
    """Full lifecycle through TERMINATED, for post-termination lockdown tests."""
    case = case_in_termination_requested(
        clock=clock, root_cause_code="PROCESS_DEVIATION",
        capa_summary="Cook step validated.",
    )
    case.decide_termination("TERMINATE", COORD_2)
    return case
