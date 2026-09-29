"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so that a test may assert on the
status code and on the envelope, rather than on a pre-digested value.  The
``/athletics`` prefix and the shape of each path live here and nowhere else.

``canonical_instant`` exists because PRD section 2.4 promises ISO 8601 UTC
timestamps with *exactly three* fractional-second digits.  Any expected
instant a test carries is normalised through it before comparison so that a
server rendering the same instant with a different fractional width is
compared on value rather than on spelling.
"""

import os
import re

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ─── Donors ───────────────────────────────────────────────────────────

    def create_donor(self, payload, headers=None):
        return self.post(API_PREFIX + "/donors", json=payload, headers=headers)

    def list_donors(self, headers=None, params=None):
        return self.get(API_PREFIX + "/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers=None):
        return self.get(
            "{0}/donors/{1}".format(API_PREFIX, donor_id), headers=headers
        )

    def change_donor_status(self, donor_id, payload, headers=None):
        return self.post(
            "{0}/donors/{1}/status-change".format(API_PREFIX, donor_id),
            json=payload,
            headers=headers,
        )

    def link_household(self, donor_id, payload, headers=None):
        return self.post(
            "{0}/donors/{1}/household-link".format(API_PREFIX, donor_id),
            json=payload,
            headers=headers,
        )

    def create_gift(self, donor_id, payload, headers=None):
        return self.post(
            "{0}/donors/{1}/gifts".format(API_PREFIX, donor_id),
            json=payload,
            headers=headers,
        )

    def list_donor_gifts(self, donor_id, headers=None, params=None):
        return self.get(
            "{0}/donors/{1}/gifts".format(API_PREFIX, donor_id),
            headers=headers,
            params=params,
        )

    def list_donor_point_transfers(self, donor_id, headers=None, params=None):
        return self.get(
            "{0}/donors/{1}/point-transfers".format(API_PREFIX, donor_id),
            headers=headers,
            params=params,
        )

    def renew_season_ticket(self, donor_id, payload, headers=None):
        return self.post(
            "{0}/donors/{1}/season-ticket-renewals".format(API_PREFIX, donor_id),
            json=payload,
            headers=headers,
        )

    # ─── Gifts ────────────────────────────────────────────────────────────

    def settle_gift(self, gift_id, payload, headers=None):
        return self.post(
            "{0}/gifts/{1}/settle".format(API_PREFIX, gift_id),
            json=payload,
            headers=headers,
        )

    # ─── Point recalculations ─────────────────────────────────────────────

    def create_recalculation(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/point-recalculations", json=payload, headers=headers
        )

    def get_recalculation(self, recalculation_id, headers=None):
        return self.get(
            "{0}/point-recalculations/{1}".format(API_PREFIX, recalculation_id),
            headers=headers,
        )

    def run_recalculation(self, recalculation_id, payload=None, headers=None):
        return self.post(
            "{0}/point-recalculations/{1}/run".format(API_PREFIX, recalculation_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def send_communications(self, recalculation_id, payload=None, headers=None):
        return self.post(
            "{0}/point-recalculations/{1}/send-communications".format(
                API_PREFIX, recalculation_id
            ),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def certify_recalculation(self, recalculation_id, payload, headers=None):
        return self.post(
            "{0}/point-recalculations/{1}/certify".format(
                API_PREFIX, recalculation_id
            ),
            json=payload,
            headers=headers,
        )

    def get_retention_analysis(self, recalculation_id, headers=None, params=None):
        return self.get(
            "{0}/point-recalculations/{1}/retention-analysis".format(
                API_PREFIX, recalculation_id
            ),
            headers=headers,
            params=params,
        )

    def list_recalculation_selection_events(
        self, recalculation_id, headers=None, params=None
    ):
        return self.get(
            "{0}/point-recalculations/{1}/selection-events".format(
                API_PREFIX, recalculation_id
            ),
            headers=headers,
            params=params,
        )

    def create_selection_event(self, recalculation_id, payload, headers=None):
        return self.post(
            "{0}/point-recalculations/{1}/selection-events".format(
                API_PREFIX, recalculation_id
            ),
            json=payload,
            headers=headers,
        )

    # ─── Point ledger ─────────────────────────────────────────────────────

    def list_point_ledger_entries(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/point-ledger-entries", headers=headers, params=params
        )

    def get_point_ledger_entry(self, entry_id, headers=None):
        return self.get(
            "{0}/point-ledger-entries/{1}".format(API_PREFIX, entry_id),
            headers=headers,
        )

    # ─── Point disputes ───────────────────────────────────────────────────

    def create_dispute(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/point-disputes", json=payload, headers=headers
        )

    def list_disputes(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/point-disputes", headers=headers, params=params
        )

    def get_dispute(self, dispute_id, headers=None):
        return self.get(
            "{0}/point-disputes/{1}".format(API_PREFIX, dispute_id), headers=headers
        )

    def review_dispute(self, dispute_id, payload=None, headers=None):
        return self.post(
            "{0}/point-disputes/{1}/review".format(API_PREFIX, dispute_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def request_dispute_info(self, dispute_id, payload, headers=None):
        return self.post(
            "{0}/point-disputes/{1}/request-info".format(API_PREFIX, dispute_id),
            json=payload,
            headers=headers,
        )

    def provide_dispute_info(self, dispute_id, payload, headers=None):
        return self.post(
            "{0}/point-disputes/{1}/provide-info".format(API_PREFIX, dispute_id),
            json=payload,
            headers=headers,
        )

    def decide_dispute(self, dispute_id, payload, headers=None):
        return self.post(
            "{0}/point-disputes/{1}/decide".format(API_PREFIX, dispute_id),
            json=payload,
            headers=headers,
        )

    # ─── Point transfers ──────────────────────────────────────────────────

    def create_point_transfer(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/point-transfers", json=payload, headers=headers
        )

    def transfer_policy_decision(self, transfer_id, payload, headers=None):
        return self.post(
            "{0}/point-transfers/{1}/policy-decision".format(API_PREFIX, transfer_id),
            json=payload,
            headers=headers,
        )

    def approve_point_transfer(self, transfer_id, payload=None, headers=None):
        return self.post(
            "{0}/point-transfers/{1}/approve".format(API_PREFIX, transfer_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def reverse_point_transfer(self, transfer_id, payload, headers=None):
        return self.post(
            "{0}/point-transfers/{1}/reverse".format(API_PREFIX, transfer_id),
            json=payload,
            headers=headers,
        )

    # ─── Sections and seats ───────────────────────────────────────────────

    def create_section(self, payload, headers=None):
        return self.post(API_PREFIX + "/sections", json=payload, headers=headers)

    def list_sections(self, headers=None, params=None):
        return self.get(API_PREFIX + "/sections", headers=headers, params=params)

    def get_section(self, section_id, headers=None):
        return self.get(
            "{0}/sections/{1}".format(API_PREFIX, section_id), headers=headers
        )

    def create_seat(self, section_id, payload, headers=None):
        return self.post(
            "{0}/sections/{1}/seats".format(API_PREFIX, section_id),
            json=payload,
            headers=headers,
        )

    def list_section_seats(self, section_id, headers=None, params=None):
        return self.get(
            "{0}/sections/{1}/seats".format(API_PREFIX, section_id),
            headers=headers,
            params=params,
        )

    def reprice_section(self, section_id, payload, headers=None):
        return self.post(
            "{0}/sections/{1}/reprice".format(API_PREFIX, section_id),
            json=payload,
            headers=headers,
        )

    def section_renovation(self, section_id, payload, headers=None):
        return self.post(
            "{0}/sections/{1}/renovation".format(API_PREFIX, section_id),
            json=payload,
            headers=headers,
        )

    def get_pricing_sensitivity(self, section_id, headers=None, params=None):
        return self.get(
            "{0}/sections/{1}/pricing-sensitivity".format(API_PREFIX, section_id),
            headers=headers,
            params=params,
        )

    def get_seat(self, seat_id, headers=None):
        return self.get("{0}/seats/{1}".format(API_PREFIX, seat_id), headers=headers)

    # ─── Seat assignments ─────────────────────────────────────────────────

    def list_seat_assignments(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/seat-assignments", headers=headers, params=params
        )

    def get_seat_assignment(self, assignment_id, headers=None):
        return self.get(
            "{0}/seat-assignments/{1}".format(API_PREFIX, assignment_id),
            headers=headers,
        )

    def set_occupancy(self, assignment_id, payload, headers=None):
        return self.post(
            "{0}/seat-assignments/{1}/occupancy".format(API_PREFIX, assignment_id),
            json=payload,
            headers=headers,
        )

    def set_billing(self, assignment_id, payload, headers=None):
        return self.post(
            "{0}/seat-assignments/{1}/billing".format(API_PREFIX, assignment_id),
            json=payload,
            headers=headers,
        )

    # ─── Selection events and slots ───────────────────────────────────────

    def get_selection_event(self, event_id, headers=None):
        return self.get(
            "{0}/selection-events/{1}".format(API_PREFIX, event_id), headers=headers
        )

    def publish_slots(self, event_id, payload=None, headers=None):
        return self.post(
            "{0}/selection-events/{1}/publish-slots".format(API_PREFIX, event_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def gate_selection_event(self, event_id, payload, headers=None):
        return self.post(
            "{0}/selection-events/{1}/gate".format(API_PREFIX, event_id),
            json=payload,
            headers=headers,
        )

    def list_selection_slots(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/selection-slots", headers=headers, params=params
        )

    def get_selection_slot(self, slot_id, headers=None):
        return self.get(
            "{0}/selection-slots/{1}".format(API_PREFIX, slot_id), headers=headers
        )

    def pick_seat(self, slot_id, payload, headers=None):
        return self.post(
            "{0}/selection-slots/{1}/pick".format(API_PREFIX, slot_id),
            json=payload,
            headers=headers,
        )

    def forfeit_slot(self, slot_id, payload, headers=None):
        return self.post(
            "{0}/selection-slots/{1}/forfeit".format(API_PREFIX, slot_id),
            json=payload,
            headers=headers,
        )

    # ─── Relocation requests ──────────────────────────────────────────────

    def create_relocation_request(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/relocation-requests", json=payload, headers=headers
        )

    def list_relocation_requests(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/relocation-requests", headers=headers, params=params
        )

    def get_relocation_request(self, request_id, headers=None):
        return self.get(
            "{0}/relocation-requests/{1}".format(API_PREFIX, request_id),
            headers=headers,
        )

    def decide_relocation_request(self, request_id, payload, headers=None):
        return self.post(
            "{0}/relocation-requests/{1}/decide".format(API_PREFIX, request_id),
            json=payload,
            headers=headers,
        )
