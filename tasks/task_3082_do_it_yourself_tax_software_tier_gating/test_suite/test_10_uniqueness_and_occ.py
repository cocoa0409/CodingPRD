"""Uniqueness constraints and the return version increment chain."""
from test_helpers import (
    add_form,
    create_account,
    create_return,
    make_taxpayer_headers,
    seed_catalog,
    setup_return_with_forms,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestFormUniqueness:
    def test_duplicate_active_form_code_rejected(self, api):
        """PRD §3.2: "Two forms with the same `form_code` may not both be
        `ACTIVE` on one return; a duplicate add is rejected with
        `ERR_DUPLICATE_FORM_ON_RETURN` (HTTP 409)."

        Design: Corner/validations/duplicate_form_code_on_same_return_rejected
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("val1")
        )
        resp = api.add_form(
            ret.id, "F1040", 100, ret.version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FORM_ON_RETURN)

    def test_removed_form_code_can_be_readded(self, api):
        """PRD §3.2: "Two forms with the same `form_code` may not both be
        `ACTIVE` on one return; a duplicate add is rejected with
        `ERR_DUPLICATE_FORM_ON_RETURN` (HTTP 409)."

        Design: Corner/validations/duplicate_form_code_on_same_return_rejected
        """
        from test_helpers import remove_form

        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("val1b")
        )
        forms = api.list_forms(ret.id, make_taxpayer_headers(account["id"]))
        form_id = validate_success(forms)[0]["id"]
        remove_form(ret, form_id)
        readded = add_form(ret, "F1040", 250)
        assert readded["status"] == "ACTIVE"
        assert readded["amount_cents"] == 250


class TestUnknownFormCode:
    def test_unregistered_form_code_not_found(self, api):
        """PRD §2.8: "After path resolution, body-referenced catalog resources
        are checked: an unregistered `form_code` yields
        `ERR_FORM_SPEC_NOT_FOUND` and an unregistered `bank_partner_code`
        yields `ERR_BANK_PARTNER_NOT_FOUND`."

        Design: Corner/validations/unknown_form_code_returns_not_found
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(email=unique_email("val4"))
        ret = create_return(account)
        resp = api.add_form(
            ret.id, "SCH_ZZ", 0, ret.version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORM_SPEC_NOT_FOUND)


class TestVersionIncrements:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.4: "The `version` field of a `TaxReturn` is the coordination
        point for the entire return graph. Any mutation that touches the
        return's derived state — adding or removing a form, importing a
        snapshot, selecting a tier, acknowledging or declining an upgrade
        prompt, adding, readying, or removing a state return, creating,
        activating, or voiding a refund-transfer agreement, submitting for
        review, reopening, filing, amending — increments the owning return's
        `version` by 1 and refreshes its `updated_at`, even when the primary
        object of the call is a child resource."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        seed_catalog(tiers=("FREE",), forms=("F1040", "W2_WH"))
        account = create_account(email=unique_email("cc2"))
        headers = make_taxpayer_headers(account["id"])
        ret_resp = api.create_return(account["id"], {"tax_year": 2025}, headers)
        ret = validate_success(ret_resp, expected_status=201)
        assert ret["version"] == 1
        f1 = api.add_form(ret["id"], "F1040", 0, 1, headers)
        validate_success(f1, expected_status=201)
        assert get_return_data(api, ret["id"], headers)["version"] == 2
        f2 = api.add_form(ret["id"], "W2_WH", 100, 2, headers)
        validate_success(f2, expected_status=201)
        assert get_return_data(api, ret["id"], headers)["version"] == 3
        sr = api.add_state_return(
            ret["id"], {"state_code": "CA", "expected_return_version": 3}, headers
        )
        validate_success(sr, expected_status=201)
        assert get_return_data(api, ret["id"], headers)["version"] == 4


def get_return_data(api, return_id, headers):
    from test_helpers import get_success_data

    return get_success_data(api.get_return(return_id, headers))
