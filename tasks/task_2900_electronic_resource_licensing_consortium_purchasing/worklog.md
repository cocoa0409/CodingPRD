# Worklog — task_2900_electronic_resource_licensing_consortium_purchasing

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing` and its `workspace/` subdirectory. Index 2900 was pre-assigned by the invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T15:02:19.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the linter is clean.

**Lint verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2900_electronic_resource_licensing_consortium_purchasing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2900_electronic_resource_licensing_consortium_purchasing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2900_electronic_resource_licensing_consortium_purchasing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1397

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing/`)

| file | bytes | lines |
|---|---|---|
| `SCAFFOLD.yaml` | 123,925 | 2,388 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 171,267 | 2,745 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 372,530 | 6,296 |

`workspace/` and `worklog.md` are untouched (both still stamped 13:39). `SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, global_constants, endpoints, errors, roles` — neither design key is present; each design file holds exactly its one top-level key.

**Domain model** — api_prefix `/erm`, 13 entities: Member, Vendor, Product, Trial, FeedbackEntry, Negotiation, Commitment (Member×Product junction), Subscription, AuthConfig, AccessIncident, UsageReport, RenewalDecision, ArchivalDepositCheck. 54 endpoints, 52 error codes, 33 ordered validation rules, 7 calculations (trial endorsement score, member tier price with two variants, cost-per-use, access health score, renewal offer price, archival coverage pct, consortium invoice allocation), 9 state machines. Topology `graph`; state-machine shape `parallel` — Subscription carries independent `contract_status` × `access_status` axes, Negotiation is cyclic (DRAFTING→VENDOR_REVIEW→COUNTERED→DRAFTING, capped by a round limit), RenewalDecision is a branching fork-join (VOTING→{RENEW|CANCEL|RESTRUCTURE}→EXECUTED with divergent side effects, plus REVERTED only for RESTRUCTURE), AccessIncident cycles via REOPENED. 5 roles: ConsortiumAdmin, MemberLibrarian (entity-backed on Member), LicenseNegotiator, VendorRep (entity-backed on Vendor), AccessEngineer, with a segregation-of-duties rule (the negotiator who submitted a round may not sign it). Consistency is immediate; OCC via `expected_subscription_version` on the two §1.6 write endpoints.

**§1.8** — 21 instances across all 9 rule_ids: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9** — 106 instances over all nine sections, 80 with full `test_recipe`s and 26 `excluded_because` stubs pointing at the §1.8 instance that already covers the claim: entities 12 (12/0), state_machines 17 (8/9), calculations 14 (5/9), validations 24 (19/5), endpoints 5 (5/0), errors 22 (22/0), rbac 5 (5/0), cross_cutting_complexity_layers 6 (3/3), consistency_model 1 (1/0). The errors section triggers each HTTP family: ten path-existence 404s, the 401/403 auth-scope set (blank `X-User-ID`, wrong role, member-scope, vendor-scope), six invalid-state 409s across four machines, plus budget-ceiling and notice-deadline 409s; the OCC layer has both §1.6 rules as 412s plus the happy path proving the version bump.

**Key finding worth flagging:** `scaffold_lint.py`'s FK reverse-reachability check (f) only recognises a sub-resource GET when the parent path segment is literally `{id}` (`f"{prefix}/{parent_seg}/{{id}}/"`), so the original descriptive placeholders (`/erm/subscriptions/{subscription_id}/auth-configs`, etc.) produced 4 spurious `FK_REVERSE_UNREACHABLE` violations even though the sub-resource GETs existed and returned `AuthConfig[]` / `RenewalDecision[]` / `ArchivalDepositCheck[]` / `FeedbackEntry[]`. Fixed by normalising every path placeholder to `{id}` (the convention the skill's own endpoint tables and the linter's docstring use) across all three files — 211 + 6 + 59 occurrences, applied only to `/{x_id}` forms so the `${var}` capture placeholders in the design files were untouched. Also corrected the stale header comment at `SCAFFOLD.yaml:42` (was "34 error codes / 7 state machines"; now 52 error codes / 9 state machines / 33 validation rules).

Orchestrator post-step actions: verified all three files exist and parse as YAML with the expected top-level keys. Stripped the leaked difficulty directive line ("Generate task harder than expert level!") plus its trailing blank line from `SCAFFOLD.yaml`'s `scenario:` block scalar so it cannot reach PRD.md via the doc generator (known leak path); `grep -c "harder than expert" SCAFFOLD.yaml` now returns 0. The difficulty directive was passed to the Step 2 subagent only.

## Step 3: Copy shared files — 2026-09-05T15:02:19.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T15:15:15.000Z

Subagent summary (verbatim):

The PRD is complete and all three hard contracts pass mechanically.

## Result

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing/workspace/PRD.md` — **511 lines**

**`## ` sections (all 5 planned sections present):**
```
3:   ## 1. Introduction
11:  ## 2. Global Specifications & System-Wide Principles
199: ## 3. Business Logic & Workflows
393: ## 4. Endpoint Definitions
454: ## 5. Error Code Catalogue
```

**Subsections:** §2.1–§2.11 (11, domain-derived titles: path resolution & rejection order, subscription-aggregate OCC, cents/rounding discipline, logical clock & calendar windows, segregation of duties, committed-spend ledger & standing, cascades & compensating actions), §3.1–§3.9 (9, organised along the purchasing timeline from registration through cancellation).

**Tail confirmation:** the file ends at a real section boundary — the final row of the §5 two-column error table (`` | `ERR_INFLATION_CAP_EXCEEDED` | 422 | ``), mid-nothing, with no audit footer, no contract-report block.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 103 required, 103 present, 0 missing
- endpoints[].request_body/input: 73 required, 73 present, 0 missing
- endpoints[].query_params / path_params / nested object keys / calculation
  output keys / common resource props: 27 required, 27 present, 0 missing
- errors[].id: 52 required, 52 present, 0 missing
- roles[].name: 5 required, 5 present, 0 missing
- state + enum literal values: 93 required, 93 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose as a single explicit
  strict ordering in §2.5 (with two worked masking examples), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint +
  expected_subscription_version + ERR_STALE_SUBSCRIPTION_VERSION + 412 all named,
  framed purely as stale-version, no "simultaneously"/race wording), 0 missing
- state_machines[].transitions: 46 checked across 9 machines, 46 fully expressed
  (from/to named, every precondition paired with its error, every side effect stated), 0 missing
- calculations[]: 7 checked, 7 fully expressed as numbered prose steps with all
  constants embedded and every rounding point pinned, 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 endpoints checked, all side effects and all
  applies_to scopes enumerated (e.g. standing gate named on exactly its 3 operations;
  body-FK existence named on exactly its 7), 0 missing
- entities[].fields[] structured content: 103 checked, defaults/initial values/types/
  null-before semantics reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (ACCEPT|COUNTER, ENDORSED|DECLINED,
  3 decide branches, 3 execute branches, VERIFIED|FAILED, PASS|FAIL probe,
  PLEDGED|CONFIRMED withdraw, DRAFT|VOTING supersede, 2 score variants,
  2 pricing variants), all with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 770
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Other verified invariants:** §2.2 is byte-identical to `section-2.2-response-structure.md`; §4 has exactly 54 rows and 4 columns, with every path and every authorized-role set matching the scaffold exactly (0 mismatches, verified programmatically); §5 has exactly 52 rows and 2 columns; no fuzzy/approximating words remain anywhere in the document. The two withheld design files were never opened, nor was `worklog.md` or any sibling task directory.

Orchestrator post-step verification (anti-truncation guard): PRD.md is 511 lines / 95,244 bytes. `grep -n '^#\{2,3\} '` lists all 5 `##` sections plus §2.1–§2.11 and §3.1–§3.9 in order. `tail -25` ends on the complete final row of the §5 error table, i.e. a real section boundary — NOT truncated mid-sentence, so no regeneration was needed. Leak check `grep -in "expert|scaffold|test_recipe|difficulty"` returns zero hits, confirming the Step 2 difficulty directive did not reach PRD.md.

## Step 6: Generate implementation — 2026-09-05T15:45:14.000Z

Note on ordering: Steps 5 and 6 were launched concurrently in a single orchestrator message (required so the implementation generator is physically unable to read `test_suite/`, which did not exist at its spawn time). Step 6 returned first, so its entry is appended first; the Step 5 entry follows.

Subagent summary (verbatim):

Implementation complete and verified.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing/workspace/implementation/`)

| file | lines |
|---|---|
| `app.py` | 107 |
| `auth.py` | 125 |
| `calc.py` | 341 |
| `envelope.py` | 82 |
| `errors.py` | 126 |
| `services.py` | 225 |
| `shape.py` | 278 |
| `store.py` | 157 |
| `routes/__init__.py` | 1 |
| `routes/registry.py` | 99 |
| `routes/trials.py` | 180 |
| `routes/commitments.py` | 109 |
| `routes/negotiations.py` | 200 |
| `routes/subscriptions.py` | 48 |
| `routes/access.py` | 196 |
| `routes/usage.py` | 72 |
| `routes/renewals.py` | 313 |
| `routes/archival.py` | 102 |
| `routes/clock.py` | 34 |
| `requirements.txt` | 1 |
| `start.sh` (chmod +x) | 19 |

Total 2816 lines. No `__pycache__`, no data files, no stray scratch files in the directory.

## Endpoint parity
`54 / 54` declared endpoints registered — a url_map dump over `/erm*` prints `erm endpoint count: 54`, matching the SCAFFOLD list exactly. `python3 -m py_compile` over all 20 modules prints `COMPILE_OK`. A fresh import shows every one of the 13 store collections empty (`store non-empty collections at boot: ['__builtins__', '_clock']`) — nothing is seeded; the logical clock starts at `2026-08-01T00:00:00Z`.

## Smoke evidence
`bash start.sh` booted in the foreground on a fresh process (random high port, `PORT` exported explicitly), binding all interfaces:

```
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:35551
```

An 85-assertion end-to-end script (`/tmp/task_2900_impl/smoke.py`) ran the full lifecycle against it: **ok=85, FAIL=0, SMOKE_FAILURES: 0**. Representative pairs:

- `GET /health` → `{"data":{"status":"ok"},"meta":{"api_request_id":"req_CIYS4U7757HGZQNB0MCZ","api_request_timestamp":"2026-09-05T15:37:05.079Z"},"response_type":"object"}` (envelope, `req_` + 20 chars, 3-digit ms).
- Rejection ladder: no headers → 401 `ERR_UNAUTHENTICATED`; unknown `/erm/...` path → 404 `ERR_NOT_FOUND`; wrong role → 403 `ERR_ROLE_NOT_PERMITTED`; missing `name` → 422 `ERR_INVALID_REQUEST`; unknown `vendor_id` with an also-invalid body → 404 `ERR_VENDOR_NOT_FOUND` (priority 4 before 6).
- Create/read-back: `POST /erm/members` → 201 with `annual_committed_cents: 0`; `GET /erm/commitments/{id}` reflects the settled reprice (`applied_discount_pct 20.0`, `tier_price_cents 6000000`, participants 2) versus the committed projection at pledge time.
- Calculations: trial `ENDORSED 84.64`; `cost-per-use` → `{"band":"POOR","cost_per_use_cents":7500,"settled_invoice_total_cents":9000000,"usage_count":1200}`; invoice allocation `7758621 + 1241379 = 9000000`, `residual_cents 0`; incident cascade → `health 52 DEGRADED, degrade_count 1, sla_credit 180000`; renewal offer `8640000` (POOR band, loyalty 450000, SLA 180000); renew execute → term `2027-09-01 → 2028-08-31`, notice `2028-06-02`, `renewal_term_count 1`, SLA reset to 0.
- OCC and archival: `expected_subscription_version` mismatch → 412 `ERR_STALE_SUBSCRIPTION_VERSION`; agency mismatch → 422; attested 80 vs deposited 98 → 409 `ERR_ARCHIVAL_COUNT_DISCREPANCY` with no state change (a following `attest` then correctly 409 `ERR_ARCHIVAL_CHECK_INVALID_STATE`); in-tolerance low coverage → `FAILED 92.0`, re-attest from FAILED → `VERIFIED 97.0`.
- Cancellation path: contract `CANCELLED` / access `POST_CANCELLATION`, commitments released, member ledger back to `0 IN_GOOD_STANDING`.
- Pagination: `limit=1&limit=1&offset=0` → `meta {limit:1, offset:0, total_count:2, has_more:true}`; `limit=0` → 422 `ERR_INVALID_REQUEST`.

The smoke server was killed by PID only (last PID 3449648, confirmed terminated); no broad `pkill` was ever used, and all scratch files live in `/tmp/task_2900_impl/`.

One note for the record: the two 409s in the archival block were smoke-script modelling errors on my side, not implementation defects — `verify` raises the priority-29 discrepancy before any transition, so the check stays `ATTESTED`, where `attest` is inadmissible per the ArchivalDepositCheck state machine. The script was corrected; `routes/archival.py` was not changed.

## Step 5: Generate unit tests — 2026-09-05T16:55:07.000Z

Subagent summary (verbatim):

Test generation for task 2900 is complete and verified.

## Output (both at the task root, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing/test_helpers/` — 9 files, 2497 lines
`__init__.py` 44 · `api_client.py` 273 · `api_errors.py` 132 · `assertions.py` 418 · `constants.py` 158 · `factories.py` 302 · `fixtures.py` 744 · `test_users.py` 80 · `types.py` 346

`.../test_suite/` — 12 files, 4693 lines
`conftest.py` 73 · `test_01_registry_and_catalogue.py` 389 (13 tests) · `test_02_authentication_and_role_access.py` 431 (19) · `test_03_trial_lifecycle_and_endorsement.py` 400 (11) · `test_04_negotiation_rounds_and_signing.py` 368 (10) · `test_05_commitment_pricing_and_member_ledger.py` 479 (11) · `test_06_signing_cascade_and_activation.py` 448 (9) · `test_07_usage_and_invoicing.py` 340 (10) · `test_08_access_configuration_and_incidents.py` 513 (9) · `test_09_renewal_voting_and_offer.py` 402 (9) · `test_10_renewal_execution_and_restructuring.py` 452 (11) · `test_11_cancellation_and_archival_deposit.py` 398 (10)

## Counts

- **122 tests total**, each with exactly one `Design:` tag as the last docstring line.
- **42 Difficulty tags** covering all **21** non-stub §1.8 instances, exactly 2 tests each (trigger outcome + derivable complement).
- **80 Corner tags**, all unique, covering all **80** non-stub §1.9 instances. The 26 `excluded_because:` stubs were not translated.
- Emitted tag set cross-checked programmatically against both rosters: zero emitted tags missing from the yaml, zero roster instances unemitted.

## SKIPPED instances

**None.** Every non-stub instance passed the PRD-first two-condition filter. Two required reframing rather than weakening: `verifying_auth_before_activation_...` and `fourth_overlapping_binding_...` both presumed auth-config creation has no contract-state gate, but PRD §3.6 requires `contract_status == ACTIVE` to configure authentication — so the first test creates the binding while ACTIVE and then drives the contract to `NOTICE_GIVEN` before probing, and the second relies on all four subscriptions being ACTIVE (the realm-capacity outcome is unaffected). Asserted outcomes are unchanged in both.

## Verification run

- `python3 -m py_compile` on all 21 .py files: clean; `__pycache__` removed.
- Citation checker over `test_suite/test_*.py`: `bad citations: 0` (every `PRD: "…"` block is a whitespace-normalised verbatim substring of `workspace/PRD.md`).
- AST audit: no unused imports anywhere (removed two stragglers found in files 02 and 04), no `sys.path` shims, no envelope double-unwrapping, no occurrence of the word "scaffold".
- Nothing was created, read or written inside `workspace/implementation/`; `worklog.md` untouched; scratch confined to `/tmp/task_2900_tests/`.

Two notes for the next stage: archival checks and renewal decisions have no GET-single endpoint, so tests read them back via module-local `_only_check` / `_read_decision` listing helpers; and `test_11` proves the priority-14-over-18 masking by adding a *second* archival check (PRD §2.6 "a new check supersedes the value of an earlier `FAILED` check") rather than re-attesting the failed one, which the 5-title tolerance would forbid.

Orchestrator post-step verification: `test_helpers/` and `test_suite/` both landed at the task root (not under `workspace/`) — `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/`, so no stray test directories needed moving before Step 7.

## Step 7: Run tests and iterate — 2026-09-05T17:16:46.000Z

Subagent summary (verbatim):

The artifact was already green on the first sweep — no fixes were needed.

## Summary

**Iterations run:** 1 (a single full 8-round parallel stability sweep; no fix cycle was required).

**Final sweep — per-round results** (all rounds, 122 tests each, `--isolation per-test-server`, ~220s wall each, run concurrently under `setsid`):

| Round | passed | failed | errors | skipped | total |
|---|---|---|---|---|---|
| 1 | 122 | 0 | 0 | 0 | 122 |
| 2 | 122 | 0 | 0 | 0 | 122 |
| 3 | 122 | 0 | 0 | 0 | 122 |
| 4 | 122 | 0 | 0 | 0 | 122 |
| 5 | 122 | 0 | 0 | 0 | 122 |
| 6 | 122 | 0 | 0 | 0 | 122 |
| 7 | 122 | 0 | 0 | 0 | 122 |
| 8 | 122 | 0 | 0 | 0 | 122 |

**Tests deleted:** none. No test failed in any round, so no PRD-silence or unique-derivability adjudication was triggered.

**Fixes applied to `test_suite/`:** none.
**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none.

**Verification beyond the pass counts** (guarding against a green-looking-but-hollow result):
- All 8 `results.$i.json` are fresh (written 17:00, sweep launched 16:56 into an empty results dir that `sweep.sh` had `rm -f`'d) and each reports `errors: 0, skipped: 0` with 122 per-test `passed` entries — not an aggregate-only claim.
- 122 collected == 122 `def test_` functions across the 12 suite files, so nothing was silently uncollected.
- No `pytest.mark.skip` / `xfail` / `skipif` anywhere in `test_suite/` or `test_helpers/`.
- `implementation/` has no `sqlite`, `open(`, `json.dump`, `pickle`, or `/tmp` reference — storage is in-memory dicts only, so `start.sh` re-invocation wipes all state (this matters because the sweep reboots the server per test and every round still passed).
- No stray `test_helpers/`/`test_suite/` under `workspace/`; both live at the task root.
- `worklog.md` untouched (mtime still 16:55, pre-dating my first action), and the only file I created was the empty scratch dir `/tmp/task_2900_fix/`.

**Notes for the caller:** I read the PRD and the full implementation (all 11 modules plus the 10 route files) while the sweep ran, to be ready to diagnose. Two implementation details are defensible-but-worth-knowing, and neither is currently exercised by a failing test, so I left both alone per the "never add/remove what tests don't require" rule: `auth.authenticate()` treats a whitespace-only header as empty (PRD only says "present but empty"), and `decide`'s CANCEL branch checks the subscription's contract state before quorum (PRD priority 8 does precede priority 20, so this reading is consistent with §2.5). Exiting on a clean 8-round sweep.

Orchestrator independent verification (the known failure mode is a subagent claiming a clean sweep with no artifacts behind it): the orchestrator itself parsed all 8 `workspace/implementation/results.$i.json` files with `json.load` and confirmed `passed == total == 122` in every one of rounds 1–8. The sweep ran via the pre-written `workspace/sweep.sh` launched under `setsid nohup`, so the backgrounded rounds could not be reaped by unrelated foreground Bash calls; no round showed the `Terminated` / same-instant-death signature.

## Step 8: Finalize PRD — 2026-09-05T17:16:46.000Z

SKIPPED, per the skill's explicit skip condition. Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. With no Step 7 diff to hand off, there is no `<step_7_diff>` focus list for a finalizer to work from, so no subagent was spawned and no `PRD_FINALIZED.md` was produced. This is the legitimate outcome, not a failure: it means `PRD.md` as generated already determined every behavior the 122 tests exercise. Step 9 therefore starts from `PRD.md` rather than `PRD_FINALIZED.md`, and Step 9 (which always runs) remains the full PRD-vs-implementation completeness scan.

## Step 9: Complete PRD — 2026-09-05T17:44:28.000Z

Orchestrator decision, recorded because it is a judgement call made without a user to consult: Step 9 was run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, rather than as a single subagent. The implementation is ~2,800 lines across 20 modules and the PRD is 511 dense lines; a single subagent attempting the exhaustive walk tends to run out of working context and return a `PRD_COMPLETED.md` that is byte-identical to its source — i.e. a scan that never actually landed. Partitioning by implementation module keeps each pass's reading load bounded while still covering every module exactly once. Pass 1 performed the `cp` from `PRD.md` (Step 8 was skipped, so there is no `PRD_FINALIZED.md`); passes 2 and 3 were explicitly forbidden from re-copying, so all three passes' edits accumulate. Partition: pass 1 = the cross-cutting core (`app.py`, `envelope.py`, `auth.py`, `errors.py`, `shape.py`, `store.py`, `services.py`, `calc.py`); pass 2 = `routes/registry.py`, `trials.py`, `commitments.py`, `clock.py`, `subscriptions.py`; pass 3 = `routes/negotiations.py`, `access.py`, `usage.py`, `renewals.py`, `archival.py`.

**Aggregate result: 60 edits — 56 ambiguity-pins, 5 mismatch-revisions** (pass 1: 21 + 2; pass 2: 14 + 2; pass 3: 21 + 1). `PRD.md` 511 lines / 95,244 chars → `PRD_COMPLETED.md` 511 lines / 118,225 chars (**+22,981 chars, +24.1%**), every edit in-paragraph: no lines added or removed, no new sections, heading list byte-identical, §4/§5 table row counts unchanged.

### Pass 1 subagent summary (verbatim)

Pass 1 complete.

## Files

- Source: `.../workspace/PRD.md` — 511 lines, 95,244 chars
- Output: `.../workspace/PRD_COMPLETED.md` — 511 lines, 105,067 chars (**+9,823 chars**, 23 lines revised in place, no lines added or removed, no new sections; tail still ends on `| ERR_INFLATION_CAP_EXCEEDED | 422 |`)

## Counts

- ambiguity-pins: 21
- mismatch-revisions: 2 (both on the tier-price fairness-ceiling / floor contradiction)

## Changes

- §2.1 — revise — ambiguity — whitespace-only headers equal empty; role names matched exactly/case-sensitively with no trimming; `X-User-ID` carried verbatim; auth gates only the `/erm` prefix, `GET /` and `GET /health` are unauthenticated — auth.py:29-38, app.py:43-55
- §2.1 — insert — ambiguity — the server never resolves `X-User-ID` to a row; an entity-backed id naming nothing is still authenticated and fails later at scope or FK — auth.py:115-125
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total), freshly minted per response — store.py:109-111
- §2.2 — revise — ambiguity — `api_request_timestamp` is real wall clock, not the logical clock, rendered `YYYY-MM-DDTHH:MM:SS.sssZ` — store.py:40-46, envelope.py:14-18
- §2.2 — revise — ambiguity — 5xx responses use the identical error envelope shape — app.py:79-88
- §2.3 — revise — ambiguity — pagination violations are `ERR_INVALID_REQUEST` (422); non-integer `limit`/`offset` rejected but whitespace stripped; offset past `total_count` legal; undeclared query params ignored; filters compared verbatim so unmatched values yield an empty page — envelope.py:45-68
- §2.3 — insert — ambiguity — `created_at` ties broken by server insertion order (millisecond precision makes ties real) — store.py:155-157
- §2.4 — revise — ambiguity — `id` is a random v4 UUID in canonical lowercase 8-4-4-4-12 form; `created_at`/`updated_at` come from the real wall clock, unaffected by clock advances — store.py:40-46, 105-106
- §2.4 — insert — ambiguity — nothing is seeded; a fresh server holds no rows — store.py:1-34
- §2.4 — insert — ambiguity — a write landing on the value already held bumps neither `updated_at` nor `version` (re-pricing to the same price is a total no-op), with the §2.6 subscription bump as the explicit exception — store.py:134-143, services.py:70-86, routes/archival.py:43
- §2.5 — insert — ambiguity — unmatched path → `ERR_NOT_FOUND` (404), undeclared method → `ERR_METHOD_NOT_ALLOWED` (405), both after auth but before the role check; trailing slash not significant — app.py:63-78, app.py:21
- §2.5 — insert — ambiguity — a non-string body FK is reported as not-found, not as a shape error; an absent or null FK falls through to priority 6 — auth.py:58-61
- §2.5 — insert — ambiguity — five shape conventions: unknown keys ignored; missing/unparsable body reads as `{}` (non-object body is 422); explicit `null` counts as absent (required → missing, optional → default); types checked not coerced, with integer fields tolerating a zero-fraction float only; required strings non-blank after trim (stored unstripped), optional strings may be empty, enums exact/case-sensitive — shape.py:43-102
- §2.7 — insert — ambiguity — inbound percentages stored verbatim, never re-rounded or refused for >2 decimals; computed percentages render as JSON numbers with trailing zeros dropped (`15.0`, `95.0`) — shape.py:128-144, calc.py:87-89, routes/archival.py:101, routes/trials.py:114
- §2.8 — revise — ambiguity — accepted `to_iso8601` syntax (optional fraction, `Z`/offset/naive→UTC), normalisation to UTC, unparsable value is a priority-6 shape error decided before monotonicity, `current_utc` truncated to 3 fractional digits, equal instant accepted; logical clock reaches output only via `current_utc` and `cast_at` — store.py:49-73, routes/clock.py:19-33
- §3.1 — revise — ambiguity — both tier-band fields required; `discount_pct` must be 0–100 inclusive — shape.py:246-278
- §3.2 — revise — ambiguity — criterion `weight_pct` must be non-negative; sum judged on exact decimals (33.33+33.33+33.34 = 100); a zero weight is legal — shape.py:210-243
- §3.3 step 6 — revise — **mismatch** — the "no member ever pays more than sixty percent" claim now yields to the step-7 floor — calc.py:192-194
- §3.3 step 7 — insert — **mismatch** — the 150,000-cent floor is applied last and wins outright over the fairness ceiling — calc.py:194
- §3.5 — revise — ambiguity — activation sweep completes over the whole table before expiry begins, both lists ascending, so one advance can carry a row to `EXPIRED` and list its `id` in both arrays; a no-op advance returns two empty lists — services.py:206-225
- §3.7 cost-per-use — revise — ambiguity — window ends compared as `YYYY-MM` strings, so an `as_of_month` before the start is an empty window, not an error; zero-request rows also produce `NO_USE` — calc.py:209-234
- §3.7 invoice allocation — insert — ambiguity — a line is named even when the residual is 0; with no `CONFIRMED` commitment, `lines` is empty, `residual_cents` equals `total_cents` and `residual_assigned_commitment_id` is null — calc.py:287-341
- §5 intro — insert — ambiguity — the table omits the transport-level `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) codes; table rows themselves untouched — errors.py:65-67

## Scan coverage

Scanned exhaustively: `app.py`, `envelope.py`, `auth.py`, `errors.py`, `shape.py`, `store.py`, `services.py`, `calc.py`. Read for context only (no edits driven by their endpoint-specific behavior): all of `routes/*.py` — used only to verify that cross-cutting claims (filter semantics, FK-before-scope ordering, `versioned=False` ledger rows, `float()` conversion of two-decimal percentages, `opt_string` usage) hold everywhere before wording them. All endpoint-specific behavior left to passes 2 and 3.

Notes for the later passes: the §5 error table was intentionally left byte-identical; the errors.py HTTP status map matches §5 exactly for every catalogued code (no mismatch there). One thing deliberately NOT pinned, as it is practically unreachable and the current wording ("that flip") already implies it: `services.apply_ledger_delta` only reports a *new* transition into `OVER_COMMITTED`, so a member already over-committed does not re-fire the DRAFT-trial withdrawal hop.

### Pass 2 subagent summary (verbatim)

Pass 2 complete. Verification: `PRD_COMPLETED.md` is still 511 lines, tail still ends on `| ERR_INFLATION_CAP_EXCEEDED | 422 |`, `PRD.md` and `implementation/` are byte- and mtime-untouched. I did **not** re-copy the file and did not touch pass 3's route files.

**Size before → after:** 511 lines / 105,067 chars → 511 lines / 109,765 chars (+4,698). Accumulated diff grew from 88 → 132 diff lines; changed-line hunks 23 → 32 (34 changed lines: pass 1's 23, of which I revised 4, plus 11 newly touched).

**Counts:** 16 edits — 14 ambiguity-pins, 2 mismatch-revisions.

- §2.8 — revise — mismatch — clock syntax was stated as a full `YYYY-MM-DDTHH:MM:SS` stamp; impl also accepts minute-precision and bare `YYYY-MM-DD` (read as midnight UTC) — `store.py:49-62` (`datetime.fromisoformat`)
- §3.3 — revise — mismatch — "Two gates precede a pledge" was misleading (there are three); now "beyond the member-standing gate of §2.10, which is evaluated first, two further gates" — `routes/commitments.py:29-46`
- §3.1 — insert — ambiguity — registry is not keyed on `name`; duplicate member/vendor/product names are accepted — `routes/registry.py:19,42,67`
- §3.1 — insert — ambiguity — a tier band stores/echoes exactly `min_participants` + `discount_pct` (further keys dropped); `min_participants` accepts an integral JSON number — `shape.py:256-277`
- §3.2 — insert — ambiguity — trial `start_date`/`end_date` must be real calendar dates (`2026-02-30` → 422) and setup enforces **no** ordering between them; an inverted/zero-length window is accepted — `shape.py:165-174`, `routes/trials.py:39-40`
- §3.2 — insert — ambiguity — a criterion stores/echoes exactly `code` + `weight_pct`; further keys dropped — `shape.py:240`
- §3.2 — insert — ambiguity — open-trial's three guards run in order status → standing → window, so the window check (also `ERR_TRIAL_INVALID_STATE`) sits *after* priority 9; `DRAFT` + `OVER_COMMITTED` + expired window reports `ERR_MEMBER_OVER_COMMITTED` — `routes/trials.py:90-99`
- §3.2 — insert — ambiguity — closing carries no temporal condition; an `ACTIVE` trial closes at any clock date — `routes/trials.py:109-110`
- §3.2 — insert — ambiguity — `criterion_code` is shape-validated only as a non-empty string, so a value outside the six codes is `ERR_UNKNOWN_CRITERION`, not `ERR_INVALID_REQUEST`, and the status check precedes it — `routes/trials.py:147,151-154`
- §3.2 — insert — ambiguity — evaluate reads the *stored* `feedback_count`, does not recount/rewrite the two counters, is not member-scoped and has no temporal condition — `routes/trials.py:124-136`
- §3.3 — insert — ambiguity — `member_id` is the pledge body's only declared field, and no stage of the package's licensing (open negotiation, already-signed subscription) gates a pledge — `routes/commitments.py:22-27`
- §3.3 — insert — ambiguity — `projected_price_cents` is stamped once and never revised when a later pledge moves the count — `routes/commitments.py:41-56`
- §3.3 — insert — ambiguity — a `CONFIRMED` withdrawal is confined to the withdrawing member: no co-participant is re-priced and no other ledger moves despite the participant count falling — `routes/commitments.py:105-108`
- §3.7 — insert — ambiguity — `as_of_month` must be `YYYY-MM` with month 01–12 (else 422, checked before aggregation); cost-per-use is gated by no contract/access state — `routes/subscriptions.py:36-40`, `shape.py:10`
- §3.7 — insert — ambiguity — invoice-allocation line ordering is made total by an insertion-order tiebreak after both `created_at`s; weights read each member's current `fte_count`; no state gate — `calc.py:292-301`
- §3.7 — insert — ambiguity — residual tie-break falls to whichever tied line comes first in the line ordering (strict `>` comparison) — `calc.py:326-334`

Deliberately left alone (pass 1/pass 3 territory or already uniquely pinned): the envelope, error/status map, role table, priority ladder, pagination, identity/version semantics, all seven `calc.py` formulas, the sweep semantics in §3.5, and everything in negotiations/access/usage/renewals/archival.

### Pass 3 subagent summary (verbatim)

Pass 3 complete. All checks pass; I did **not** re-copy the file.

## Verification

| | before pass 3 | after pass 3 |
|---|---|---|
| `PRD_COMPLETED.md` | 511 lines / 109,765 chars | **511 lines / 118,225 chars** (+8,460) |
| `diff PRD.md PRD_COMPLETED.md \| wc -l` | 132 | **214** |

- `PRD.md` untouched: 511 lines / 95,244 chars.
- `cmp -s PRD.md PRD_COMPLETED.md` → **DIFFERS** (good).
- `tail -5` still ends on `| ERR_INFLATION_CAP_EXCEEDED | 422 |`.
- Heading list byte-identical to `PRD.md`; §4/§5 table row count unchanged (110 both files) — no structural damage.

## Counts
**1 mismatch-revision, 21 ambiguity-pins** (22 edits, all in-paragraph).

## Changes
- §3.4 — insert — ambiguity — negotiation create imposes no ordering between `target_term_start`/`target_term_end` and never compares them to the trial window or product — `routes/negotiations.py:35-36`
- §3.4 — insert — ambiguity — submit declares no body fields; revise requires all four `requested_*` and leaves `round_count` and the `granted_*` fields alone (only submit bumps the counter); status check precedes the round budget on both — `routes/negotiations.py:76-89,140-161`
- §3.4 — insert — ambiguity — `accepted_price_cents` also required ≥1; `disposition` selects which price field is read, the other is ignored and the untouched stored price survives — `routes/negotiations.py:109-136`
- §3.4 — insert — ambiguity — `activation_start_date` unconstrained vs the term; the five signing gates' exact order, with the participant gate (`ERR_COMMITMENT_INVALID_STATE`) displaced to last after priorities 10–13; `SIGNED` terminal — `routes/negotiations.py:164-200`
- §3.6 — insert — ambiguity — `ip_ranges` entries validated only as non-blank strings (no CIDR parsing); `proxy_prefix` stored verbatim for non-`EZPROXY`; unlimited bindings per subscription — `routes/access.py:28-34`, `shape.py:184-195`
- §3.6 — insert — ambiguity — realm-capacity count includes the configuring subscription's own `PENDING`/`VERIFIED` bindings (a window overlaps itself) — `routes/access.py:40-52`
- §3.6 — insert — ambiguity — a `PASS` writes `access_status` unconditionally (`DEGRADED → CONFIGURED` too) without touching `degrade_count`/`sla_credit_cents` — `routes/access.py:93-98`
- §3.6 — insert — ambiguity — incident reporting is gated by no state on either subscription axis — `routes/access.py:105-129`
- §3.6 — insert — ambiguity — reopen retains `root_cause_code` while clearing `remedy_code` — `routes/access.py:188-192`
- §3.7 — revise — ambiguity — the term window is the subscription's *current* `term_start`/`term_end` (renewal retro-invalidates old months); duplicate scan spans all rows; filing ungated by axis state — `routes/usage.py:33-43`
- §3.8 — insert — ambiguity — `titles_out`/`titles_in` accepted regardless of `recommended_action` and validated only as strings; `recommended_action` never binds `resolved_action`; decision creation ungated by axis state — `routes/renewals.py:40-46`
- §3.8 — insert — ambiguity — open-vote gate order (contract state then confirmed-participant, `ERR_COMMITMENT_INVALID_STATE`) — `routes/renewals.py:98-107`
- §3.8 — insert — ambiguity — `ballot` is a free non-blank string, only exact `YES` counts; duplicate check precedes the participant check — `routes/renewals.py:124-139`
- §3.8 — insert — ambiguity — `quorum_met` is a stored flag recomputed only on ballot cast; decide reads it without re-deriving — `routes/renewals.py:147-151,185`
- §3.8 — insert — ambiguity — renew and restructure branches inspect no subscription state at decide time — `routes/renewals.py:177-194`
- §3.8 — **revise — mismatch** — the cancel branch is **not** precondition-free: it requires `contract_status == ACTIVE`, checked *before* quorum (priority 8 vs 20) — `routes/renewals.py:181-186`
- §3.8 — insert — ambiguity — `delta_price_cents` is a signed integer (negative/zero accepted); the decide body carries no title arrays — `routes/renewals.py:174`, `renewals.py:155-165`
- §3.8 — insert — ambiguity — renewal roll anchors both new dates on the *old* `term_end`; "plus one year" degenerates 29 Feb → 28 Feb — `calc.py:107-112`, `routes/renewals.py:215-224`
- §3.8 — insert — ambiguity — restructure adds `delta_price_cents` with no price floor; access gate precedes the title floor — `routes/renewals.py:254-266`
- §3.8 — insert — ambiguity — revert refuses non-executed/non-restructure/already-reverted decisions and consults neither the access axis nor the title floor — `routes/renewals.py:295-312`
- §3.9 — insert — ambiguity — archival check creation ungated by axis state, unlimited checks per subscription/agency, attest+verify usable after cancellation/expiry — `routes/archival.py:15-44,84-102`
- §3.9 — insert — ambiguity — `PENDING`/`FAILED` are the only attest origins; `ATTESTED` and `VERIFIED` both give `ERR_ARCHIVAL_CHECK_INVALID_STATE` — `routes/archival.py:74-75`

## Closing coherence check (all three passes)
No contradictions found. Two spots needed care and were handled inside my own wording rather than by rewriting prior work:
1. **Sign-gate and open-vote orderings vs §2.5's "the ordering above is authoritative."** My two order pins place `ERR_COMMITMENT_INVALID_STATE` later than a literal reading of priority 8 would. I anchored the signing case explicitly to the existing precedent §3.2 already sets (the trial-opening window check displaced past priority 9), so §2.5 and §3.4 now read as rule-plus-documented-displacement rather than as two conflicting claims.
2. **§3.8's ballot paragraph** (pre-existing, from the original PRD) presents the participant check before the duplicate check, while §2.5 priorities 21/22 order them the other way — which is what the implementation does. I pinned the evaluation order explicitly in-paragraph instead of reordering the two existing sentences; the paragraph is slightly redundant now but not contradictory. **Reporting, not silently rewriting:** if a future pass wants tighter prose, that pair of sentences is the place.

No edit touched `PRD.md`, `worklog.md`, or any scaffold file; no scratch files were left behind.

### Orchestrator final verification

- `wc -l -c`: `PRD.md` 511 / 95,244; `PRD_COMPLETED.md` 511 / 118,225.
- `cmp -s PRD.md PRD_COMPLETED.md` → DIFFERS (the byte-identical failure mode, which would mean the scan never ran, did NOT occur).
- `diff PRD.md PRD_COMPLETED.md | wc -l` → 214.
- `grep -c '^#'` equal in both files — no headings added or lost.
- `tail -3 PRD_COMPLETED.md` still ends on the complete final §5 error-table row `| ERR_INFLATION_CAP_EXCEEDED | 422 |` — not truncated.
- Leak check `grep -in "scaffold|test_recipe|harder than expert"` on `PRD_COMPLETED.md` → zero hits.
- Re-parsed all 8 `workspace/implementation/results.$i.json`: still 122/122 in every round (the passing sweep artifacts are preserved alongside the completed PRD; note that Step 9 edits documentation only and touches no code, so the sweep result stands).
- Only one `worklog.md` exists, at the task root; `workspace/` contains exactly `INSTRUCTION.md`, `PRD.md`, `PRD_COMPLETED.md`, `implementation/`, plus the orchestrator's `sweep.sh` and its `sweep.log`. No stray test directories under `workspace/`. `PRD_FINALIZED.md` is legitimately absent (Step 8 skipped).

Pipeline complete through Step 9.
