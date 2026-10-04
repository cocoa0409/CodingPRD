"""API client: one method per endpoint defined in the PRD §4 table.

Every method returns the raw ``requests.Response`` so tests assert on status
codes and envelope contents directly.  The ``/records`` prefix and the shape
of each path live here and nowhere else.

CRITICAL ROUTING FACT: the logical-clock capability lives OUTSIDE the
``/records`` mount (PRD §2.4: "an admin-only test-driving capability ...
living outside the `/records` mount").  ``set_clock`` therefore posts to the
bare path ``/_clock/set_current_utc`` — no prefix — while all 57 business
endpoints go through ``API_PREFIX``.
"""

import os

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # ─── Logical clock (UNPREFIXED — outside the /records mount) ─────────────
    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ─── Agencies ─────────────────────────────────────────────────────────────
    def create_agency(self, payload, headers=None):
        return self.post(API_PREFIX + "/agencies", json=payload, headers=headers)

    def get_agency(self, agency_id, headers=None):
        return self.get("{0}/agencies/{1}".format(API_PREFIX, agency_id), headers=headers)

    # ─── Records schedules ────────────────────────────────────────────────────
    def create_schedule(self, payload, headers=None):
        return self.post(API_PREFIX + "/schedules", json=payload, headers=headers)

    def list_schedules(self, headers=None, params=None):
        return self.get(API_PREFIX + "/schedules", headers=headers, params=params)

    def get_schedule(self, schedule_id, headers=None):
        return self.get("{0}/schedules/{1}".format(API_PREFIX, schedule_id), headers=headers)

    def submit_schedule(self, schedule_id, headers=None):
        return self.post("{0}/schedules/{1}/submit".format(API_PREFIX, schedule_id), headers=headers)

    def appraise_schedule(self, schedule_id, payload, headers=None):
        return self.post("{0}/schedules/{1}/appraise".format(API_PREFIX, schedule_id), json=payload, headers=headers)

    def decide_schedule(self, schedule_id, payload, headers=None):
        return self.post("{0}/schedules/{1}/decide".format(API_PREFIX, schedule_id), json=payload, headers=headers)

    # ─── Transfers ────────────────────────────────────────────────────────────
    def create_transfer(self, payload, headers=None):
        return self.post(API_PREFIX + "/transfers", json=payload, headers=headers)

    def list_transfers(self, headers=None, params=None):
        return self.get(API_PREFIX + "/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers=None):
        return self.get("{0}/transfers/{1}".format(API_PREFIX, transfer_id), headers=headers)

    def submit_transfer_metadata(self, transfer_id, payload, headers=None):
        return self.post("{0}/transfers/{1}/submit-metadata".format(API_PREFIX, transfer_id), json=payload, headers=headers)

    def accession_transfer(self, transfer_id, payload, headers=None):
        return self.post("{0}/transfers/{1}/accession".format(API_PREFIX, transfer_id), json=payload, headers=headers)

    def withdraw_transfer(self, transfer_id, headers=None):
        return self.post("{0}/transfers/{1}/withdraw".format(API_PREFIX, transfer_id), headers=headers)

    # ─── Collections ──────────────────────────────────────────────────────────
    def list_collections(self, headers=None, params=None):
        return self.get(API_PREFIX + "/collections", headers=headers, params=params)

    def get_collection(self, collection_id, headers=None):
        return self.get("{0}/collections/{1}".format(API_PREFIX, collection_id), headers=headers)

    def begin_processing(self, collection_id, headers=None):
        return self.post("{0}/collections/{1}/begin-processing".format(API_PREFIX, collection_id), headers=headers)

    def complete_description(self, collection_id, payload, headers=None):
        return self.post("{0}/collections/{1}/complete-description".format(API_PREFIX, collection_id), json=payload, headers=headers)

    def enqueue_digitization(self, collection_id, headers=None):
        return self.post("{0}/collections/{1}/enqueue-digitization".format(API_PREFIX, collection_id), headers=headers)

    def complete_digitization(self, collection_id, headers=None):
        return self.post("{0}/collections/{1}/complete-digitization".format(API_PREFIX, collection_id), headers=headers)

    def publish_digital(self, collection_id, headers=None):
        return self.post("{0}/collections/{1}/publish-digital".format(API_PREFIX, collection_id), headers=headers)

    def get_digitization_queue(self, headers=None, params=None):
        return self.get(API_PREFIX + "/digitization-queue", headers=headers, params=params)

    # ─── Declassification reviews and equity referrals ────────────────────────
    def create_declass_review(self, payload, headers=None):
        return self.post(API_PREFIX + "/declass-reviews", json=payload, headers=headers)

    def list_declass_reviews(self, headers=None, params=None):
        return self.get(API_PREFIX + "/declass-reviews", headers=headers, params=params)

    def get_declass_review(self, review_id, headers=None):
        return self.get("{0}/declass-reviews/{1}".format(API_PREFIX, review_id), headers=headers)

    def begin_declass_review(self, review_id, headers=None):
        return self.post("{0}/declass-reviews/{1}/begin".format(API_PREFIX, review_id), headers=headers)

    def create_referrals(self, review_id, payload, headers=None):
        return self.post("{0}/declass-reviews/{1}/referrals".format(API_PREFIX, review_id), json=payload, headers=headers)

    def complete_declass_review(self, review_id, payload, headers=None):
        return self.post("{0}/declass-reviews/{1}/complete".format(API_PREFIX, review_id), json=payload, headers=headers)

    def list_equity_referrals(self, headers=None, params=None):
        return self.get(API_PREFIX + "/equity-referrals", headers=headers, params=params)

    def get_equity_referral(self, referral_id, headers=None):
        return self.get("{0}/equity-referrals/{1}".format(API_PREFIX, referral_id), headers=headers)

    def respond_to_referral(self, referral_id, payload, headers=None):
        return self.post("{0}/equity-referrals/{1}/respond".format(API_PREFIX, referral_id), json=payload, headers=headers)

    # ─── Researcher registrations ─────────────────────────────────────────────
    def create_researcher(self, payload, headers=None):
        return self.post(API_PREFIX + "/researchers", json=payload, headers=headers)

    def get_researcher(self, researcher_id, headers=None):
        return self.get("{0}/researchers/{1}".format(API_PREFIX, researcher_id), headers=headers)

    def activate_researcher(self, researcher_id, headers=None):
        return self.post("{0}/researchers/{1}/activate".format(API_PREFIX, researcher_id), headers=headers)

    # ─── Pull requests ────────────────────────────────────────────────────────
    def create_pull_request(self, payload, headers=None):
        return self.post(API_PREFIX + "/pull-requests", json=payload, headers=headers)

    def list_pull_requests(self, headers=None, params=None):
        return self.get(API_PREFIX + "/pull-requests", headers=headers, params=params)

    def get_pull_request(self, pull_id, headers=None):
        return self.get("{0}/pull-requests/{1}".format(API_PREFIX, pull_id), headers=headers)

    def fulfill_pull_request(self, pull_id, headers=None):
        return self.post("{0}/pull-requests/{1}/fulfill".format(API_PREFIX, pull_id), headers=headers)

    def return_pull_request(self, pull_id, headers=None):
        return self.post("{0}/pull-requests/{1}/return".format(API_PREFIX, pull_id), headers=headers)

    # ─── Reproduction requests ────────────────────────────────────────────────
    def create_reproduction_request(self, payload, headers=None):
        return self.post(API_PREFIX + "/reproduction-requests", json=payload, headers=headers)

    def list_reproduction_requests(self, headers=None, params=None):
        return self.get(API_PREFIX + "/reproduction-requests", headers=headers, params=params)

    def get_reproduction_request(self, repro_id, headers=None):
        return self.get("{0}/reproduction-requests/{1}".format(API_PREFIX, repro_id), headers=headers)

    def pay_reproduction_request(self, repro_id, payload, headers=None):
        return self.post("{0}/reproduction-requests/{1}/pay".format(API_PREFIX, repro_id), json=payload, headers=headers)

    def fulfill_reproduction_request(self, repro_id, headers=None):
        return self.post("{0}/reproduction-requests/{1}/fulfill".format(API_PREFIX, repro_id), headers=headers)

    def cancel_reproduction_request(self, repro_id, headers=None):
        return self.post("{0}/reproduction-requests/{1}/cancel".format(API_PREFIX, repro_id), headers=headers)

    # ─── FOIA requests ────────────────────────────────────────────────────────
    def create_foia_request(self, payload, headers=None):
        return self.post(API_PREFIX + "/foia-requests", json=payload, headers=headers)

    def list_foia_requests(self, headers=None, params=None):
        return self.get(API_PREFIX + "/foia-requests", headers=headers, params=params)

    def get_foia_request(self, foia_id, headers=None):
        return self.get("{0}/foia-requests/{1}".format(API_PREFIX, foia_id), headers=headers)

    def adjudicate_foia_request(self, foia_id, payload, headers=None):
        return self.post("{0}/foia-requests/{1}/adjudicate".format(API_PREFIX, foia_id), json=payload, headers=headers)

    def appeal_foia_request(self, foia_id, payload, headers=None):
        return self.post("{0}/foia-requests/{1}/appeal".format(API_PREFIX, foia_id), json=payload, headers=headers)

    def decide_foia_appeal(self, foia_id, payload, headers=None):
        return self.post("{0}/foia-requests/{1}/decide-appeal".format(API_PREFIX, foia_id), json=payload, headers=headers)

    # ─── Presidential restrictions ────────────────────────────────────────────
    def create_presidential_restriction(self, payload, headers=None):
        return self.post(API_PREFIX + "/presidential-restrictions", json=payload, headers=headers)

    def list_presidential_restrictions(self, headers=None, params=None):
        return self.get(API_PREFIX + "/presidential-restrictions", headers=headers, params=params)

    def get_presidential_restriction(self, restriction_id, headers=None):
        return self.get("{0}/presidential-restrictions/{1}".format(API_PREFIX, restriction_id), headers=headers)

    def designate_restriction_representative(self, restriction_id, payload, headers=None):
        return self.post("{0}/presidential-restrictions/{1}/designate".format(API_PREFIX, restriction_id), json=payload, headers=headers)

    def notify_restriction(self, restriction_id, headers=None):
        return self.post("{0}/presidential-restrictions/{1}/notify".format(API_PREFIX, restriction_id), headers=headers)

    def release_restriction(self, restriction_id, headers=None):
        return self.post("{0}/presidential-restrictions/{1}/release".format(API_PREFIX, restriction_id), headers=headers)


api_client = ApiClient()
