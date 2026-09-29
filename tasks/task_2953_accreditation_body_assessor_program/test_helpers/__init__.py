"""Test infrastructure for the Accreditation Body Assessor Program API.

Stage 1 helpers only: no test cases live here.

Modules
-------
constants   : role names, enum member spellings, rates and nominal windows
api_errors  : the error-id catalogue and its HTTP status mapping
types       : light structural aliases for the JSON documents under test
test_users  : header builders for the seven roles, including the four
              entity-backed identities that must resolve to a real row
api_client  : one method per endpoint in section 4 of the PRD
factories   : request-payload builders with PRD-default values
assertions  : domain assertions (envelope shapes, ledgers, instants)
fixtures    : composite multi-call scenario builders
"""
