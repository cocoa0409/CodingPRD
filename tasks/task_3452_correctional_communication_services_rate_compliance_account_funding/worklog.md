# Worklog — task_3452_correctional_communication_services_rate_compliance_account_funding

## Step 1: Create task directory — 2026-10-02T06:21:00.000Z

Task directory pre-allocated per command args; verified `./tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/workspace/` exists. No new index computed, no other task_* directory created.

## Step 2: Scaffold generation — 2026-10-02

Wrote SCAFFOLD.yaml (13 entities, 67 endpoints, 53 errors, 12 state machines, 10 calculations, 2 OCC concurrency rules, 6 roles), SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rules x 2 = 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (40 active instances + 3 excluded_because stubs across all 9 taxonomy sections). scaffold_lint.py verdict: clean lint (789 calls scanned, 0 violations). All formula-derived assert literals precomputed by code (commission 153/141, refunds 400/700, cutoff charges 250/242, booth-minutes 1440/1410).

### Step 2 subagent summary (verbatim)

All three artifacts are complete, lint-clean, and cross-audited. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/SCAFFOLD.yaml` (1699 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1623 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/SCAFFOLD_CORNER_DESIGN.yaml` (2495 lines)

## Counts

| Artifact | Count |
|---|---|
| Entities | 13 |
| Endpoints | 67 (incl. unprefixed `POST /_clock/set_current_utc`, default `2026-09-01T00:00:00Z`) |
| Error codes | 53 |
| State machines | 12 (Account and RecipientNumber carry parallel dimensions) |
| Calculations | 10, plus 3 named compensating invariants |
| Roles | 6 (2 entity-backed: AccountHolder→Account, RecipientParty→RecipientNumber) |
| §1.8 difficulty instances | 18 (9 rules × 2) |
| §1.9 corner instances | 43 (40 active + 3 `excluded_because` stubs) |
| Lint | **VERDICT: clean lint** — 789 recipe calls scanned, 0 violations |

## Design decisions (the "much harder than expert" levers)

- **Archetype**: compliance_audit × pricing_engine; flat topology; segregation-of-duties role model (refund decider ≠ payer, enforced by X-User-ID comparison across roles).
- **Dual-variant calcs on different domains**: commission GROSS vs NET (identical ledger → 153 vs 141 cents) and refund SIMPLE_BALANCE vs LIFO_NET selected by jurisdiction (identical ledger → 400 vs 700 cents).
- **Combinatorial modes (a) and (b)**: call charge nesting `min(schedule, current cap)` + `ceil` minutes + `floor` affordability cutoff (charge 250 vs truncated 242 with BALANCE_EXHAUSTED); commission aggregate-rounding pinned (153, not the per-line 154).
- **Two interval semantics for Rule 8**: inmate half-open overlap (adjacency allowed) vs facility aggregate sweep with ±turnover-buffer expansion (a session disjoint under raw overlap is rejected).
- **Cascades with pinned ordering**: inmate release refunds sessions/messages *before* the DEBIT auto-close snapshot (balance_at_closure 1000, not 485); refund mark-paid chains RefundRequest → ledger → Account derived fields.
- **OCC**: schedule activation on `FacilityContract.version`, cap amendment on `RegulatoryCap.version`.
- **Escheatment**: deny → unclaimed → dormancy scan (≥ boundary) → notice → claim window (≥ boundary) → remit or claim, with a closure-balance partition invariant (balance == refunded + escheated + retained + frozen + unclaimed).
- All formula-derived assert literals were precomputed with Python before writing.

## Caveats / process notes

- **Endpoint count is 67** (lumen-loop flagship class). This exceeds the 40-endpoint threshold known to break impl-gen (Step 6) unless the generation prompt pre-constrains it (one file per message, per-domain modules, no-truncation, self-smoke-test) — the orchestrator should apply that guidance downstream.
- Two heredoc seam corruptions (junk `YAML_EOF` lines embedded at chunk boundaries) were caught by parse-after-every-append and surgically removed; a fixture bug (LOCAL vs INTERSTATE rate invalidating the refundable==0 math) was caught in the setup-chain replay and fixed. Final replay of every chain against §1.2/§1.4/§1.6 plus a grounds/name/stub audit all pass clean.

## Step 3: Copy shared files — 2026-10-02T07:48:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: PRD generation — 2026-10-02T08:25:00.000Z

### Step 4 subagent summary (verbatim)

The PRD is complete and all three hard contracts pass. Final summary:

## Deliverable

**`/home/ubuntu/github/CodingPRD/tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/workspace/PRD.md` — 375 lines**

## Sections covered

- **§1 Introduction** (3 paragraphs: regulatory business context → system scope → the two governing principles)
- **§2 Global Specifications** (10 subsections): 2.1 roles/identity (6 roles, entity-backed `AccountHolder`/`RecipientParty` vs 4 opaque roles), 2.2 response envelope (verified byte-identical to `section-2.2-response-structure.md`), 2.3 pagination + per-endpoint filter enumeration, 2.4 logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback, mounted **outside** `/comm-services` per scaffold), 2.5 common properties + append-only `FundingTransaction` exception (no `updated_at`/`version`), 2.6 integer-cents precision + charge-time minimum + non-retroactivity, 2.7 OCC (both rules, `ERR_STALE_VERSION`/412, no race framing), 2.8 the 10 validation tiers as an explicit ordered list with the two scaffold-named outrankings (`ERR_NUMBER_BLOCKED` > `ERR_INSUFFICIENT_BALANCE`; `ERR_INMATE_SESSION_OVERLAP` > capacity/daily-limit), 2.9 left-to-right 404 resolution (all 12 ids), 2.10 the three conservation invariants.
- **§3 Business Logic** (9 subsections, lifecycle-grouped): facility/cap baseline, contracts & schedules, inmates/accounts/deposits, recipients/consent/privilege, calls, messaging, video visitation, release/closure/refund adjudication (incl. full SIMPLE_BALANCE vs LIFO_NET and SoD pairings), escheatment/complaints/regulatory summary (incl. GROSS vs NET commission with pinned aggregate-then-round-half-up order).
- **§4 Endpoint table**: 67 rows (including the unprefixed `/_clock/set_current_utc`), 4 columns only; verified 67/67 scaffold endpoints present.
- **§5 Error catalogue**: 53 rows, 2 columns only; all 53 ids also appear in §2/§3 prose (verified mechanically).

## Hard contract reports

```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].request_body/input (incl. query params): 80 required, 80 present, 0 missing
- endpoints[].path_params: 1 required (id), 1 present
- (additionally verified: all 20 computed-read output field names present)
Status: PASS

Rule coverage check:
- validations[] priority: 10 tiers checked, 10 expressed in ordered §2.8 prose, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (endpoint + expected_contract_version / expected_regulatory_cap_version + ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (reconstruction-safe prose, ceil/floor/half-up named), 0 missing
- validations[] conditions: all 53 error_ids matchable in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to scopes: 67 checked, expressed (incl. release cascade's pinned 3-step order), 0 missing
- entities[].fields[] structured content: defaults (10/2), nullability, 6-digit code, 1000 chars, 15-minute floor, 7-day escalation age all expressed, 0 missing
- sibling-branch symmetry: 12 groups checked (SIMPLE_BALANCE/LIFO_NET, GROSS/NET, COMPLETED/NO_SHOW, VERIFY/REVOKE, APPROVE/DENY, PREPAID-DEBIT/COLLECT cutoffs, REQUESTED vs CONFIRMED cancel, both close sources, both claim sources, both revoke sources, both facility-activate sources), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 560
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Silences (scaffold under-specifications I did not invent answers for)

1. **`e164_number` uniqueness** per account has no nominated error id — stated descriptively, no rejection semantics invented.
2. **Rate-schedule creation on a `TERMINATED` contract** is forbidden by the endpoint description but has no error id — stated without one.
3. **Release auto-close vs in-flight `CONNECTED` call**: the cascade auto-closes `DEBIT` accounts, but the close precondition (`ERR_ACCOUNT_HAS_ACTIVE_CALLS`) interaction is unspecified; PRD transcribes the cascade as scaffolded.
4. **Affordability division by zero** when `applied_per_minute_cents` is 0 — scaffold silent.
5. **Lifecycle-guard errors** (`ERR_ACCOUNT_HAS_*`, `ERR_SESSION_NOT_CANCELLABLE`, `ERR_REFUND_NOT_PAYABLE`, `ERR_ESCHEAT_NOT_CLAIMABLE`, `ERR_CAP_NOT_CONFIGURED`, `ERR_STALE_VERSION`) belong to no validation-priority tier in the scaffold — PRD places them with their workflows and assigns no tier.

## Ambiguities noticed

- Validation tier 4 (request shape) includes `ERR_VERIFICATION_CODE_INVALID`/`ERR_CONSENT_REQUIRED`, which are checked *before* existence (tier 5) even though code-matching requires loading the entity — transcribed faithfully as scaffolded.
- `AccountHolder` complaint ownership ("own facility/subject" in the roles table) is loosely defined; PRD renders it as filing only against the hosting facility with only own-account subjects attached — a judgment call the test generator should be aware of.
- The `FundingTransaction` description's "negative CLOSURE_FEE when LIFO fee refund exceeds closure fee" is dense; PRD decodes it as: the settling `CLOSURE_FEE` entry at disbursement is a *credit* exactly when restored deposit fees exceed the closure fee.

## Step 5a: Test helpers generation — 2026-10-02T08:50:00.000Z

### Step 5a subagent summary (verbatim)

Stage 1 is complete. All nine helper files are written, syntax-checked, and import-verified with no server running.

## Files written (all under `…/task_3452_correctional_communication_services_rate_compliance_account_funding/test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `types.py` | 452 | 23 enums (all state machines + parallel dimensions) + 13 TypedDicts; `FundingTransaction` correctly omits `updated_at`/`version` per PRD §2.5 |
| `api_errors.py` | 132 | `ApiErrorId` (all 49 PRD §5 ids) + `HTTP_STATUS_CODES`, registered with `set_error_http_status_map` at import |
| `constants.py` | 63 | 13 PRD-verbatim literals only (see audit below) |
| `api_client.py` | 385 | `ApiClient(GenericApiClient)` — **67/67 endpoints, exact match** against the PRD §4 table (normalized path-param diff); clock exposed at the unprefixed `/_clock/set_current_utc`; base URL from `API_BASE_URL` env via the framework, no hardcoded port |
| `assertions.py` | 328 | 13 per-entity asserters + `assert_account_balance_invariant` (PREPAID/DEBIT ≥ 0, COLLECT ≥ −limit), `assert_closure_balance_partition`, `assert_ledger_balance` |
| `factories.py` | 248 | Payload factories; defaults form a cap-compliant standard environment (rates ≤ caps); counter-unique booking numbers and E.164 numbers |
| `test_users.py` | 95 | 8 `TEST_USERS` entries with **distinct X-User-IDs** (verified), incl. alt FacilityStaff/ComplianceOfficer for SoD pairings; `make_account_holder_headers`/`make_recipient_party_headers` for entity-backed identity, `make_*` builders for all six roles |
| `fixtures.py` | 640 | Clock helpers (all dates derived from the `2026-09-01T00:00:00Z` default, none earlier), Tier-1 entity builders, and composites: `setup_active_facility`, `setup_funded_account`, `setup_call_ready_account`, `setup_account_with_confirmed_session`, `setup_closed_account_with_refund`, `setup_denied_refund_account`, `setup_dormant_account`, `setup_notice_sent_account`, `setup_remitted_account`, `setup_claimed_account`, `setup_paid_refund_account`, `file_complaint`, `setup_complaint_under_review` |
| `__init__.py` | 44 | Barrel export (174 public names verified) |

## Verification results
- Per-file `ast.parse`: all pass; `compileall` sweep clean.
- Package-graph smoke check (no server, no pytest): all 8 submodules + barrel import OK.
- Endpoint coverage: PRD table 67/67 exact match after path-param normalization (the raw diff was the known `{id}` vs `{account_id}` false alarm).
- Pure-function checks: time helpers reproduce the design indices' exact boundary dates (`+30d` → 2026-10-01, `+7d` → 2026-09-08, notice 2026-10-01 `+45d` → 2026-11-15); factory defaults all within caps; ledger assertion fires on a `version` field as required.
- No "scaffold"/section references in any generated file.

## Constants self-audit — all 13 PASS
`2026-09-01T00:00:00Z`, `/_clock/set_current_utc`, `/comm-services`, `7` ("seven days"), `15` ("fifteen minutes"), `1000` ("1000 characters"), `6` ("six-digit"), `10` ("defaults to 10"), `2` ("defaults to 2"), pagination `10/1/100/0` — every literal greps in `workspace/PRD.md` (7/15/6 match the PRD's word forms; flagged in the file docstring).

## PRD ambiguities resolved (Stage 2 / Step 7 take note)
1. **Contract-activation version bump**: PRD §2.5 ("version increments on every mutation") vs. design recipes that activate a schedule with the pre-activation contract version. `setup_active_facility` re-GETs the contract after activation and uses the fresh version — correct under both readings.
2. **`reference_id` key presence**: PRD calls it "optional … (null for deposits)" — assertion checks the value only when present, never demands the key.
3. **`verification_code` after verify**: PRD only guarantees it on the create response; the asserter accepts null-or-six-digit, and `create_verified_recipient` carries the creation code forward for re-verify/unblock flows.
4. **SoD officer pairing defaults**: `decide_refund` defaults to officer-1, `mark_refund_paid` to officer-2 (alt), so the payer ≠ decider rule holds automatically; explicit `officer_id=` overrides support the violation tests (e.g. `fs-1` requester vs `fs-1` decider).
5. **Escheat boundaries**: `setup_dormant_account(scan_at_exact_boundary=…)` advances to exactly `unclaimed_since + dormancy_days` (or one day short); `setup_remitted_account` remits at exactly `notice + claim_window_days`.
6. **DEBIT-account deposits**: default to AccountHolder headers built from `account["id"]` (ownership compares the account id, not the inmate id); `as_staff=True` mirrors the release-cascade recipes.
7. **Header-stripping test support**: all client methods accept `headers=None` (framework maps to `{}`) for the missing-header-beats-404 case.

No `test_suite/` or `test_*.py` files were created — that is Stage 2's scope, against these frozen helpers.

### Orchestrator note (Step 5a verification)
Hand-back claimed "49 PRD §5 ids" in api_errors.py; orchestrator diffed error-id sets: PRD 53 = helpers 53, symmetric diff empty. File is complete; the "49" was a prose miscount.

## Step 5b: Test suite generation — 2026-10-02T09:40:00.000Z

### Step 5b subagent summary (verbatim)

Stage 2 complete. The suite is fully generated, collects cleanly, and passes both mandatory audits.

## Files written (12 files, 2942 lines) — all under `/home/ubuntu/github/CodingPRD/tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/test_suite/`

| File | Lines | Tests |
|---|---|---|
| conftest.py | 71 | — |
| test_01_corner_entities.py | 227 | 6 |
| test_02_corner_state_machines.py | 231 | 6 |
| test_03_corner_calculations.py | 174 | 4 |
| test_04_corner_validations.py | 214 | 6 |
| test_05_corner_endpoints_and_consistency.py | 132 | 4 |
| test_06_corner_errors.py | 472 | 11 |
| test_07_corner_rbac.py | 99 | 3 |
| test_08_difficulty_pricing_math.py | 266 | 8 |
| test_09_difficulty_state_machines_cascades.py | 283 | 8 |
| test_10_difficulty_priority_boundary_dependency.py | 452 | 12 |
| test_11_difficulty_overlap_invariants.py | 321 | 8 |

conftest.py wires the frozen helpers: session-scoped `api` fixture (runner-owned `API_BASE_URL`), one fixture per role from TEST_USERS, and an autouse per-test logical-clock pin to the PRD §2.4 default via the unprefixed `/_clock/set_current_utc`.

## Emitted vs skipped
- **Emitted: 76 tests** — 36 difficulty (all 18 §1.8 instances × 2, the mandatory minimum) + 40 corner (all 40 active §1.9 instances × 1).
- **Skipped: 0.** Every non-stub instance passed the PRD-first two-condition filter; all asserted literals (153/141 commission divergence, 400/700 SIMPLE_BALANCE vs LIFO_NET refunds, 250/242 charge cutoffs, 875/100 partition, dormancy/claim-window/escalation boundaries, etc.) are pinned by verbatim PRD formulas.
- The 3 `excluded_because` stubs (`layer_optimistic_concurrency_*`, `layer_cascading_side_effects_*`, `layer_dual_variant_calculation_*`) got no tests, per spec.
- No `skip`/`skipif`/`xfail` markers anywhere.

## Collection check (last lines)
```
tasks/.../test_11_difficulty_overlap_invariants.py::test_cancel_restores_booth_minutes_to_budget
76 tests collected in 0.23s
```
0 collection errors. Every file also passed `ast.parse` immediately after writing.

## AST tag audit
58 expected tags (18 Difficulty + 40 Corner), **58 emitted, 0 missing, 0 underfilled, 0 unknown/mismatched, 0 stub-tagged, 0 untagged**. Each difficulty instance has exactly 2 tests; each corner instance exactly 1.

## PRD-citation pass
117 quoted PRD passages across 76 docstrings; every one contains a ≥8-word substring surviving a literal grep of PRD.md (one §4 paraphrase in test_07 was caught and replaced with verbatim §3.5/§3.6 prose).

## Adjudication notes (local relaxations, documented in-test)
- Absolute `version` literals from the recipes (e.g. "c_v + 2") were re-derived as relative increments (`v+1` per mutation/activation), since PRD §2.5/§2.7 pin the increment but not the initial value; every schedule activation re-reads the contract version first, making the OCC tests robust to whether contract activation itself bumps the version. The `version == 1` sub-assertion in the facility-defaults instance was dropped on the same ground (defaults/ONBOARDING/server-minted-field claims remain asserted).
- Timestamp equality assertions (`connected_at`, `escalated_at`, `unclaimed_since`) pin the exact logical-clock instant via prefix compare, tolerating optional millisecond formatting ("three fractional digits", §2.5).
- The wrong-code verification test derives a guaranteed-different code from the server-issued one instead of a hardcoded literal (eliminates a 1-in-10⁶ flake).

### Orchestrator note (Step 5b verification)
Orchestrator re-ran `python3 -m pytest test_suite --collect-only -q` independently: **76 tests collected in 0.22s, 0 errors** — hand-back claim confirmed.

## Step 6: Implementation generation — 2026-10-02T10:20:00.000Z

### Step 6 subagent summary (verbatim)

All done. The implementation is complete and verified. Final report:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Guarded `pip install` (no-op when flask present), `exec python3 app.py`, foreground |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 73 | Flask app, blueprint registration, unprefixed `POST /_clock/set_current_utc`, envelope-shaped 404/405/500 handlers |
| `core.py` | 364 | ApiError, logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback), in-memory DB (empty at boot, no seeding), envelope helpers, auth (X-User-ID/X-User-Role, six roles), request validators, pagination (limit/offset, default 10, 1–100) |
| `calc.py` | 230 | refund_payout (SIMPLE_BALANCE / fee-restoring LIFO_NET), call_charge (ceil minutes, floor affordability, cutoff), capacity sweep (half-open, buffered), daily count, commission (aggregate-then-round-half-up), regulatory summary |
| `routes_facilities.py` | 150 | 8 endpoints incl. dormancy scan, video-availability, regulatory-summary |
| `routes_caps.py` | 99 | cap CRUD + OCC-guarded PUT (412) |
| `routes_contracts.py` | 141 | contract CRUD, activate (cap/commission/one-active checks), terminate (schedule supersession), nested schedule create |
| `routes_schedules.py` | 86 | schedule get/list, OCC activation (contract version bump, supersede prior) |
| `routes_inmates.py` | 134 | booking (IN_CUSTODY booking-number uniqueness), release cascade in pinned 3-step order |
| `routes_accounts.py` | 350 | accounts, deposits (201, two ledger entries), suspend/resume, close (3 guards, snapshot, RefundRequest iff refundable>0), escheat notice/remit/claim, ledger |
| `routes_recipients.py` | 155 | register (6-digit code, attorney auto-PRIVILEGE_REQUESTED), verify (= unblock path), request-block, privilege-decision |
| `routes_calls.py` | 160 | connect (tier-ordered gates, pinned min() rates, recording exemption), end (0→NOT_CONNECTED no entry; >0→cutoff billing) |
| `routes_video.py` | 245 | create (window/15-min/max/same-date checks), confirm (overlap > capacity > daily-limit precedence, charge), cancel (refund, not-cancellable guard), close-out |
| `routes_messages.py` | 135 | create (charge at PENDING_REVIEW), review (exact-reversal refund) |
| `routes_refunds.py` | 121 | decide (SoD, deny→unclaimed), mark-paid (SoD, REFUND_PAYOUT + settling CLOSURE_FEE) |
| `routes_complaints.py` | 152 | file (AccountHolder facility/subject scoping), start-review, resolve (mandatory note), escalate (7-day min age) |

All 67 scaffold endpoints are implemented. Isolation rule respected: no test-suite/design files were read (grep confirms zero references).

## compileall
`python3 -m compileall -q .` → clean, plus per-file `ast.parse` after every write (one garbled line in `routes_refunds.py` was caught and fixed mid-build).

## Self-smoke-test transcript (no test suite used; own server on dynamic ports, killed by saved PID afterwards)
Three boots, all happy-path + error-path checks passed, including: facility create 201 with `created_at=2026-09-01T00:00:00.000Z`; clock set 200 echoing canonical form; schedule activation OCC (`expected=99` → **412**, `expected=2` → 200, contract v2→3); deposit 10000 → balance **9950** (fee min(100,50)); call pins rate 25/conn 250, 61s → 2 min, total 300; duration 0 → NOT_CONNECTED, no ledger entry; message charge 200 + reject refund (balance invariant holds); video confirm charge 200; **ERR_INMATE_SESSION_OVERLAP beats capacity/daily-limit**; capacity exceeded with 1 booth; daily limit; release cascade (DEBIT auto-close B=4950 with refunds inside snapshot, refundable=5000 via intact-deposit fee restore, settling **CLOSURE_FEE +50 credit** — the PRD's unusual case); escheatment deny→unclaimed→dormancy scan at exact boundary (flagged=1)→claim→pay (partition 9100/150/0/0) and notice→early remit **ERR_CLAIM_WINDOW_OPEN**→remit at exact boundary (escheated 1850, retained 100); SoD both directions (self-decide 403, payer==decider 403, payer≠decider PAID); **ERR_NUMBER_BLOCKED beats ERR_INSUFFICIENT_BALANCE**; deposit==fee → 422, fee+1 → 201 nets 1; affordability cutoff `BALANCE_EXHAUSTED` billable 14 total 600; cap amend stale 412 / success v2; escalation too early at 6d, allowed at exactly 7d; summary (revenue 900, avg round(900/16)=56, GROSS commission consistent, cap_breach_count=2 after downward amendment); 404 envelope shape, 400 no-headers, 403 wrong-role, 403 cross-account ownership, list pagination meta.

## PRD ambiguities resolved (for Steps 8/9 alignment)
1. **`meta.api_request_timestamp` source** — logical clock (PRD §2.4: every server-stamped timestamp reads it; deterministic).
2. **Initial `version`** — 1, +1 per mutation (initial value unpinned).
3. **Pagination bounds** — non-integer / limit∉[1,100] / offset<0 → `ERR_INVALID_REQUEST` 400 (min/max stated, error behavior unstated).
4. **Tier-4 vs tier-5 interleave** — entity-free shape checks (parse, end>start, same-date, 15-min floor, required fields, enums) before 404s; entity-*dependent* shape checks (visiting window, max_session_minutes, verification-code match) necessarily after the entity loads.
5. **Verify check order** — code match then consent (scaffold precondition order); both 422.
6. **Ownership vs 404** — pure id-comparison ownership (`/accounts/{id}/*`, body `account_id`) at tier 3 before existence; FK-based ownership (video cancel, complaint subject call) requires the load, so 404 first.
7. **Call connect tier order** — `ERR_NO_ACTIVE_RATE_SCHEDULE` (tier 6) before consent errors (tier 7), following §2.8 tiers over §3.5 prose order.
8. **Tier-10 internal order** — `ERR_ACCOUNT_INMATE_MISMATCH` before `ERR_INSUFFICIENT_BALANCE` (§3.5 prose: "Finally, the account must be able to afford…").
9. **Privileged numbers still require VERIFIED + consent** — tier-7 text is unconditional; "gates every non-privileged call" read as rationale.
10. **Video confirm requires an ACTIVE schedule** (`ERR_NO_ACTIVE_RATE_SCHEDULE`) to price the fee; checked at tier 6.
11. **No cross-account binding on `recipient_number_id`** in calls (no PRD rule/error id).
12. **Account creation has no facility/inmate state gates** and no facility↔inmate binding check (none specified).
13. **Schedule create on TERMINATED contract** → `ERR_INVALID_STATE` (no error id named; `ERR_CONTRACT_NOT_ACTIVE` is catalogued as activation-specific).
14. **Duplicate e164 within an account** → `ERR_INVALID_REQUEST` 400 (catalog has no duplicate-number error).
15. **Decide recomputes with close-time inputs** — closure fee and refund_method pinned internally at close so later cap amendments don't drift the recomputation ("same formula and inputs as at closure").
16. **Release auto-close bypasses the three close guards** (PRD states it unconditionally; cascade steps 1–2 already clear sessions/messages).
17. **Regulatory summary with no ACTIVE contract** → `commission_basis: null`, `commission_accrued_cents: 0`; no cap row → `cap_breach_count: 0`; dormancy scan with no cap flags nothing.
18. **`retained_fees_cents` derived** as `B − refunded − escheated − balance_cents`, which keeps the closure-balance partition exact at every point (0 after deny-with-unclaimed; can go negative in the LIFO fee-restore case, matching the pinned formula).
19. **`unclaimed_since` → null** when the unclaimed balance zeroes (remit / claim-paid), per "null while 0".
20. **ESCHEAT_CLAIM `refund_method_applied` → null** (no jurisdiction variant used; payout is the unclaimed balance).
21. **Cascade message rejection** sets `reviewed_by_user_id='system'`, `review_note=null`.
22. **Verify on an already-VERIFIED, unblocked number** → `ERR_INVALID_STATE` (no self-loop in the state machine; re-verification cycle exists only for blocked numbers).
23. **Zero-amount CALL_CHARGE not appended** (endpoint table: "when > 0"); NOT_CONNECTED → `billable_minutes=0, total_charge_cents=0`. MESSAGE_CHARGE always appended.
24. **Clock endpoint echoes the canonical 3-fractional-digit UTC form** of the supplied instant.
25. **Capacity sweep spans all CONFIRMED sessions of the facility** (not just same-date), so buffered intervals crossing midnight are exact; daily limit counts by `scheduled_start` UTC date.
26. **`collect_credit_limit_cents` stored null for non-COLLECT** ("simply ignored").
27. **Unknown paths/methods** return envelope-shaped off-catalog errors (`ERR_NOT_FOUND` 404/405, `ERR_INTERNAL` 500) — no test should hit these.

## Scaffold/PRD contradictions found
None of substance — the documents agree on all pinned orderings, variants, and boundaries. Two presentational overlaps worth noting: `ERR_SESSION_IN_PAST` appears in both tier 4 and tier 8 (implemented as tier-4-positioned at create, tier-8-positioned at confirm, matching each context's listing); and scaffold tier 10's error-id listing order conflicts with PRD §3.5's prose on binding-vs-affordability — resolved per the PRD-prose rule (item 8 above).

### Orchestrator note (Step 6 verification)
Verified independently: 16 files + start.sh present; start.sh is foreground `exec python3 app.py` with guarded pip install; app.py binds `0.0.0.0:$PORT`; clock default `2026-09-01T00:00:00Z` present in core.py; clock route unprefixed at `/_clock/set_current_utc`; routes under `/comm-services`; constants spot-check (7-day escalation, 15-min floor, 1000-char cap) matches PRD.

## Step 7: Test-fix iterate loop — 2026-10-02T11:05:00.000Z

Iteration 1 sweep: 72/76 in all 8 rounds; union of failures was 4 deterministic tests (no flakiness).

### Adjudication (per-test, STEP 1/2/3 protocol)
- `test_immediate_consistency_write_response_matches_followup_read` (test_05) — PRD §2.5 verbatim ("version ... increments by one on every mutation") + §2.7 ("advances the contract's version by one" per activation request, a multi-write request) uniquely pin one version advance per mutation request. Test faithful (relative v+1 assertion). IMPLEMENTATION BUG: `append_ledger` touched the account per ledger row, so the two-row deposit yielded +2.
- `test_mark_paid_sets_account_refund_fields` / `test_mark_paid_appends_payout_and_settling_fee_entries` (test_09) — PRD §3.8/§2.10 cover the asserted formula and partition. TEST BUG: both tests hardcoded the design recipe's geometry (deposit 1000 → balance 975 → refundable 875) but invoked the fixture with its default deposit 1025 (balance 1000 → refundable 900). Fixed by passing `deposit_amount=1000` to match the asserted literals.
- `test_close_with_zero_refundable_creates_no_refund_request` (test_10) — PRD §3.8 covers the CLOSURE_FEE zeroing assertion. TEST BUG: `NameError: get_ledger` — the helper exists in test_helpers.fixtures and is exported, but test_10 omitted it from its import list. Added the import.

No tests deleted; every failing test traced to a verbatim PRD rule with unique derivability.

### Fixes applied
- test_suite/test_10_difficulty_priority_boundary_dependency.py — added `get_ledger` to the test_helpers import (missing import; the CLOSURE_FEE ledger assertion is PRD §3.8-verbatim).
- test_suite/test_09_difficulty_state_machines_cascades.py — both mark-paid tests now call `setup_paid_refund_account(deposit_amount=1000)`, aligning the fixture geometry with the hardcoded 975/875/100 assertions (and with the design recipe's deposit of 1000).
- workspace/implementation/core.py — `append_ledger` no longer calls `touch(account)`: a FundingTransaction row is its own versionless resource (PRD §2.5), and the account's version must advance exactly once per mutation request, not per appended row.
- workspace/implementation/routes_accounts.py — `create_deposit` now touches the account once after appending the DEPOSIT + DEPOSIT_FEE pair.
- workspace/implementation/routes_calls.py — `end_call` touches the account once when a CALL_CHARGE is appended.
- workspace/implementation/routes_messages.py — `create_message` touches the account once after MESSAGE_CHARGE; `review_message` REJECT branch touches once after MESSAGE_REFUND.
- workspace/implementation/routes_video.py — `confirm_session` touches once after VIDEO_CHARGE; `cancel_session` CONFIRMED branch touches once after VIDEO_REFUND.
- workspace/implementation/routes_inmates.py — release cascade tracks refund-receiving accounts and touches exactly once each account not auto-closed in step 3 (closed accounts already advance once inside `close_account`, which retains its single final touch; `remit_escheat` and `mark_paid` likewise keep their single final touch).

### Final verification
8-round parallel sweep (`--isolation per-test-server`): **all 8 rounds 76/76 passed, 0 failed, 0 errors**. results.1.json … results.8.json retained in workspace/implementation/.

### Orchestrator note (Step 7 verification)
Independently verified: all 8 `results.{1..8}.json` present in workspace/implementation/ (mtimes 10:53), each `passed=76 total=76 failed=0`. Step 7 totals: 2 iterations, 0 deletions, 2 test_suite fixes, 0 test_helpers fixes, implementation fixes in core.py + routes_accounts.py + routes_calls.py + routes_messages.py + routes_video.py + routes_inmates.py (single-version-advance-per-mutation-request consolidation). Implementation/ fixes occurred ⇒ Step 8 NOT skipped.

## Step 8: PRD finalization — 2026-10-02T11:20:00.000Z

### Step 8 subagent summary (verbatim)

Verification complete. PRD_FINALIZED.md exists at the required path and is byte-identical to PRD.md — the correct outcome for this diff, per the verification below.

## Summary on exit

**Line counts / delta**: PRD.md 375 lines, PRD_FINALIZED.md 375 lines, 0.0% delta (identical md5 `521d070e9c13e9ef32f4d50c1d1506e0`).

**Zero edits were made.** Per-item reasoning:

### Item 1 — `append_ledger` no longer touches the account; each route touches the account exactly once per mutation request (core.py + routes_accounts/calls/messages/video/inmates.py)

**Verdict: no PRD edit — the PRD already uniquely determines once-per-request version advance.**

- §2.5 (line 86) scopes the rule to the resource itself: "`updated_at` ... refreshed on every mutation **of the resource**. `version` ... increments by one on every mutation." The unit is a mutation of the versioned resource, i.e. one mutating operation upon it.
- §2.5 (line 88) then carves ledger rows out of the standard set: a `FundingTransaction` is its own resource carrying only `id` + `created_at`, and "ledger rows are never modified or deleted." Appending a ledger row is therefore the *creation of a separate versionless resource*, not a mutation of the account. The per-row-touch reading (the pre-fix bug, +2 for one deposit) requires counting each ledger append as an account mutation, which contradicts §2.5's own data model; the account stores no ledger fields at all (§3.3: balance etc. are "never stored inputs").
- §2.7 supplies the only worked examples and both are multi-write requests advancing "by one" per request: schedule activation supersedes the old schedule + activates the new + stamps `activated_at`, yet "advances the contract's `version` by one" (line 102, echoed §3.2 line 161); cap amendment replaces "any subset" of eight fields yet "advances the row's `version` by one" (line 104, echoed §3.1 line 147). §2.7's preamble ("a parent resource whose version advances as a side effect of **the write**", singular) reinforces it.
- I enumerated every account-version path in `implementation/` (grep of all 40 `touch(` callsites plus a read of each handler): `create_deposit` (2 ledger rows, 1 touch), `end_call` (1 row, 1 touch), `create_message` (1, 1), `review_message` REJECT (1, 1), `confirm_session` (1, 1), `cancel_session` CONFIRMED (1, 1), `close_account` (0–1 rows, 1 final touch, shared by the close route and the release cascade), `mark_paid` (2 rows, 1 touch), `remit_escheat` (2 rows, 1 touch), `decide_refund` DENY-positive (0 rows, 1 touch), `suspend`/`resume`/`send-escheat-notice`/`claim-unclaimed` (1 touch each), `run_dormancy_scan` (1 touch per flagged account per scan request), and the release cascade (each refund-receiving account not auto-closed touched exactly once; auto-closed accounts advance once inside `close_account`). Every path is exactly the §2.5+§2.7 rule: each resource mutated by a request advances once. The implementation now matches the PRD as written; the Step 6 per-row code was the bug, exactly as Step 7 adjudicated.

### Item 2 — test_09 fixture geometry (`deposit_amount=1000` to match hardcoded 975/875/100)

**Verdict: no PRD edit — pure test-side fixture bug.** The asserted literals derive from PRD-pinned formulas (§3.3 deposit nets `amount − fee`; §3.8 `SIMPLE_BALANCE` payout = snapshot − closure fee; §3.8 mark-paid appends REFUND_PAYOUT + settling CLOSURE_FEE per §2.10's partition). The concrete numbers (fee 25, closure fee 100) are test-chosen fixture values, not PRD constants; the test invoked its fixture with a mismatched default deposit (1025 vs its asserted 1000 geometry). PRD §3.8/§2.10 already cover the behavior verbatim.

### Item 3 — test_10 missing `get_ledger` import

**Verdict: no PRD edit — pure test bug (NameError).** The asserted CLOSURE_FEE zeroing is PRD §3.8-verbatim ("a single `CLOSURE_FEE` debit of the entire snapshot zeroes the balance"); the helper existed and was exported, just unimported.

### Pre-edit search log

No edits were committed, so there is no per-edit (a)/(b)/(c) log. For the single candidate edit theme (item 1), the mandatory enumeration was performed as due diligence for the zero-edit verdict: subject = account version advance on ledger-appending requests; paths enumerated and read = `core.py` (`touch`, `append_ledger`, `new_entity`, `new_ledger_entry`), `routes_accounts.py` (all 7 account mutations + `close_account`), `routes_calls.py:139-162`, `routes_messages.py:40-139`, `routes_video.py:150-249`, `routes_inmates.py:72-147` (release cascade incl. the refunded-minus-closed touch set), `routes_refunds.py` (decide/mark-paid), `routes_facilities.py:93-113` (dormancy scan), `routes_schedules.py:75-86` and `routes_caps.py:75-99` (OCC +1 exemplars), plus a PRD-wide grep of `version|mutation|updated_at`. All 16 account-touching paths conform to the once-per-mutating-request rule the PRD already pins, so any PRD rewording here could only add a new mismatch risk with zero alignment benefit.

PRD_FINALIZED.md is in place at `/home/ubuntu/github/CodingPRD/tasks/task_3452_correctional_communication_services_rate_compliance_account_funding/workspace/PRD_FINALIZED.md`, byte-identical to PRD.md, and a fresh implementer reading it alone is already constrained to the shipped behavior on every path Step 7 touched.

### Orchestrator note (Step 8 verification)
`diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical confirmed; both 375 lines. Zero-edit outcome accepted per the explicit pre-authorization in the Step 8 prompt.

## Step 9: PRD completeness scan — 2026-10-02T11:45:00.000Z

### Step 9 subagent summary (verbatim)

Done. `PRD_COMPLETED.md` is written: 375 → 381 lines, +4,021 chars over `PRD_FINALIZED.md`, structure unchanged (no new sections).

**Counts:** 23 ambiguity-pins, 1 mismatch-revision, 2 impl-suspect sites flagged (PRD left unchanged there).

**Changes** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl site}`):

- §2.2 — insert — ambiguity — fallback identifiers: unmatched path/method → `ERR_NOT_FOUND` (404/405), unexpected failure → `ERR_INTERNAL` (500), same envelope — app.py:52-69
- §5 — insert — ambiguity — catalogue rows for `ERR_NOT_FOUND` and `ERR_INTERNAL` — app.py:52-69
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; timestamp ties break by insertion order; `has_more` true iff items remain beyond the page — core.py:343-357
- §2.4 — insert — ambiguity — offset-less datetimes are read as UTC — core.py:73-75
- §2.5 — revise — ambiguity — `version` starts at 1; each resource mutated by a request advances exactly once regardless of side-effect count — core.py:114-145, core.py:161-169
- §2.5 — revise — **mismatch** — `CLOSURE_FEE`-as-credit is not the "single" unusual case: added the second case (closing a `COLLECT` account with a negative snapshot writes the zeroing entry as a credit) — routes_accounts.py:104-107
- §2.7 — insert — ambiguity — OCC stale check sits after shape/existence/state-gate tiers and before payload value re-validation (stale+inactive contract → `ERR_CONTRACT_NOT_ACTIVE`; stale+bad cap value → `ERR_STALE_VERSION`) — routes_schedules.py:44-74, routes_caps.py:73-97
- §2.8 tier 10 — insert — ambiguity — account–inmate binding is checked before fiscal sufficiency (`ERR_ACCOUNT_INMATE_MISMATCH` outranks `ERR_INSUFFICIENT_BALANCE`) — routes_calls.py:80-95, routes_messages.py:69-79, routes_video.py:177-187
- §3.3 — insert — ambiguity — account opening is gated only on facility/inmate existence; no facility-status, custody, or inmate-belongs-to-facility check — routes_accounts.py:112-154
- §3.3 — revise — ambiguity — post-closure `retained_fees_cents` is derived, not stored: snapshot − refunded − escheated − current ledger balance — routes_accounts.py:29-52
- §3.4 — revise — ambiguity — duplicate `e164_number` in an account → `ERR_INVALID_REQUEST`; verification code is zero-padded six digits — routes_recipients.py:40-45, core.py:195-196
- §3.4 — insert — ambiguity — re-verifying an already-`VERIFIED`, unblocked number → `ERR_INVALID_STATE` — routes_recipients.py:105-107
- §3.5 — revise — ambiguity — CallRecord carries `duration_seconds` (null until end); negative `duration_seconds` → `ERR_INVALID_REQUEST` — routes_calls.py:109,143
- §3.5 — insert — ambiguity — a zero applied per-minute rate never truncates the bill — calc.py:105-108
- §3.7 — revise — ambiguity — `duration_minutes` is whole minutes between endpoints, rounded down; creation does not check the account–inmate binding — routes_video.py:108
- §3.7 — revise — ambiguity — confirmation additionally requires the contract's active rate schedule (`ERR_NO_ACTIVE_RATE_SCHEDULE`) and enforces the account–inmate binding (`ERR_ACCOUNT_INMATE_MISMATCH`) before the fiscal check — routes_video.py:152-156,177-179
- §3.7 — revise — ambiguity — video-availability's `date` query parameter is required (`ERR_INVALID_REQUEST` when omitted) — routes_facilities.py:120-123
- §3.8 — revise — ambiguity — paying an escheat-claim request also clears `unclaimed_since` — routes_refunds.py:113-115
- §3.9 — revise — ambiguity — escheat remittance resets `unclaimed_since` to null — routes_accounts.py:303-304
- §3.9 — revise — ambiguity — dormancy scan flags nothing when the jurisdiction has no cap row; noted the two places `unclaimed_since` is cleared — routes_facilities.py:100-108
- §3.9 — revise — ambiguity — escheat-claim requests record the claiming holder as `requested_by_*` and keep `refund_method_applied` null — routes_accounts.py:322-336
- §3.9 — revise — ambiguity — complaint resolve and escalate both require source state `UNDER_REVIEW` (`ERR_INVALID_STATE` otherwise) — routes_complaints.py:126-128,140-142
- §3.9 — revise — ambiguity — `period_start`/`period_end` are required query parameters — routes_facilities.py:143-149
- §3.9 — revise — ambiguity — no active contract → `commission_basis` null, `commission_accrued_cents` zero — calc.py:199-209

**Impl-suspect sites (PRD left unchanged, untested paths):**

1. **§3.5** — PRD: "Either way, the charge is appended to the account's ledger as a `CALL_CHARGE` debit of `total_charge_cents`." Impl (routes_calls.py:156: `if status == "COMPLETED" and total > 0:`) appends no ledger row — and does not advance the account version — when a `COMPLETED` call's total is zero (reachable only with a zero applied per-minute rate and zero connection fee). The PRD's explicit "no ledger entry" contrast for zero-duration calls makes the blanket append a hard contract the impl violates on this edge.
2. **§3.4** — PRD: "Before an inmate can call someone, that someone's number must sit on the account's contact list as a `RecipientNumber`." Impl (routes_calls.py:37-121) never checks `recipient.account_id == account_id` at connect; a verified, unblocked number registered on another account can be called with charges settling on the supplied account. The connect-time guard list in §3.5 omits the check, but the §3.4 invariant is stated flatly.

### Step 9 follow-up: orchestrator adjudication of the 2 impl-suspect sites

Orchestrator adjudicated both sites against the verbatim PRD text, then sent the Step 9 subagent a follow-up (SendMessage, context resumed):

- **Site 1 (§3.5 zero-total COMPLETED call) → AMBIGUITY, pinned to impl.** Rationale: the flat "Either way, the charge is appended" sentence has only the zero-DURATION carve-out explicit (§3.5 line 195; §4 row: "zero duration means unanswered and uncharged"); whether a zero-amount ledger row exists is two-reader divergent. Subagent verified routes_calls.py:143-162 (append + touch both inside `if status == "COMPLETED" and total > 0`) and inserted one sentence at §3.5 line 197:
  > "Should a positive-duration call's computed `total_charge_cents` come out zero — which requires both the applied connection fee and the applied per-minute rate to be zero — no ledger entry is appended, exactly as on the zero-duration path: the account's balance is unchanged and its `version` does not advance, while the call record itself still completes and advances its own version as usual."
  Verified: diff vs pre-edit backup = exactly one changed line (197c197); final PRD_COMPLETED.md = 381 lines / 71,269 chars (+4,415 chars vs PRD_FINALIZED.md). Orchestrator grep-confirmed the sentence and line count.
- **Site 2 (§3.4 cross-account recipient binding at connect) → UNIMPLEMENTABLE AS A GATE, recorded known gap; PRD unchanged, impl unchanged.** Rationale: no catalogued error id for the rejection, §3.5's pinned connect-guard list omits the check, and neither the error nor its validation tier is uniquely derivable — two faithful PRD-only readers diverge on whether it gates and what it raises. Flagging it here preserves the scaffold intent without hacking either side.

**Final Step 9 tallies:** 24 ambiguity-pins, 1 mismatch-revision, 0 remaining impl-suspect sites.

### Orchestrator note (final sweep validity)
`find workspace/implementation test_suite test_helpers -newer results.1.json` over *.py/*.sh → empty: Steps 8/9 touched only workspace/*.md; the 8/8-round 76/76 sweep of record remains valid for the shipped code.
