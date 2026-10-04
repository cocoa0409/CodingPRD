"""Optimistic concurrency: stale return version at claim intake."""
from test_helpers import (
    TEST_USERS,
    create_notice,
    create_product,
    create_return,
    file_return,
    setup_office_preparer_client,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestStaleVersionOnClaimIntake:
    def test_stale_expected_return_version_rejected(self, api):
        """PRD §2.6: "A claim-intake request must carry
        `expected_return_version`, the version of the target tax return the
        client last read; if the return's current `version` differs — for
        example because the return was re-quoted by an office operator after
        the client fetched it — the intake is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than attaching a claim to a
        return the caller no longer recognizes."

        The version captured at creation goes stale after a re-quoting PATCH;
        intake with the stale version fails with 412.

        Design: Corner/validations/stale_version_on_claim_intake
        """
        office, preparer, client = setup_office_preparer_client()
        ret = create_return(client["id"], office["id"], preparer["id"],
                            components=["1040_SIMPLE"])
        stale_version = ret["version"]
        validate_success(
            api.patch_return(ret["id"], {"components": ["1040_ITEMIZED"]}, OM), 200)
        file_return(ret["id"])
        create_product(ret["id"], tier="STANDARD")
        notice = create_notice(ret["id"])
        res = api.create_claim(
            {"return_id": ret["id"], "notice_id": notice["id"],
             "expected_return_version": stale_version}, CM)
        validate_error(res, "ERR_STALE_VERSION")
