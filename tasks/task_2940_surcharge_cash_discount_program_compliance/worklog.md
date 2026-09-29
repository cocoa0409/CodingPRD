# Worklog — task_2940_surcharge_cash_discount_program_compliance

## Step 1: Create task directory — 2026-09-05T19:19:30.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2940_surcharge_cash_discount_program_compliance/` and `workspace/` (index pre-assigned by the invocation; no scan of ./tasks/ performed).

## Step 2: Generate Scaffold — 2026-09-05T21:02:22.000Z

Subagent summary (verbatim):

Step 2 for task 2940 is complete. All three scaffold artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2940_surcharge_cash_discount_program_compliance/`, and the lint verdict is clean.

**Lint (verbatim)**
```
Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     106
  Calls scanned (§1.8+§1.9):  1392

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files**
- `SCAFFOLD.yaml` (132K) — §1.0–§1.7 only; top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`. Neither design key is present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (124K) — single key `scaffold_difficulty_design`; 9 rule_ids × 2 = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (432K, 7029 lines) — single key `scaffold_corner_design`; 124 instances (106 full recipes + 18 `excluded_because` stubs, all with no `test_recipe`).

**Declared surface (§1.1–§1.7):** 11 entities, 7 state machines, 2 concurrency rules, 13 calculations, 41 validations, 49 endpoints, 55 errors, 6 roles. Expert; layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`; topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

**§1.9 breadth walk (all 9 guide sections present)**
| section | instances | stubs |
|---|---|---|
| entities | 15 | 0 |
| state_machines | 18 | 2 |
| calculations | 24 | 8 |
| validations | 23 | 4 |
| endpoints | 6 | 0 |
| errors | 15 | 0 |
| rbac | 11 | 0 |
| cross_cutting_complexity_layers | 10 | 4 |
| consistency_model | 2 | 0 |

**Coverage audit**
- Errors: 55 declared, **55** asserted as `data.error_id == ERR_*` somewhere in §1.8+§1.9; 0 missing, 0 undeclared extras. (The last gap, `ERR_TERMINAL_PROGRAM_MISMATCH`, was only reachable behind the priority-84 program-state check, so I added `sale_booked_against_a_sibling_draft_program_is_rejected` — an ENFORCING terminal citing a DRAFT sibling program.)
- Every guide row is instantiated per section, including the flat-topology extras (FK validation, cross-reference integrity), all four active complexity layers (both declared `concurrency_rules` get an OCC stale-version test using their own `write_endpoint`/`occ_field`, plus a version-monotonicity instance proving registration `decision`/`effectuate` do **not** bump `SurchargeProgram.version`), both segregation-of-duties pairs (activate vs. attest, refund create vs. issue), and both `immediate`-consistency claims.
- All 18 stub `difficulty_instance` citations resolve to real `rule_id / name` pairs in §1.8; all 141 instance names across the two design files are unique; no schema-foreign keys on any instance.

**Two things worth flagging to the orchestrator**
1. `scenario:` was written verbatim as instructed, so it still begins with the line `Generate task harder than expert level!`. Per the known leak path, that line should be stripped before Step 3/4 so it cannot reach PRD.md.
2. Scratch cleanup removed only `.scratch/step2`; the parent `.scratch/` directory is intact (now empty), and `worklog.md` / `workspace/` were left untouched.

Orchestrator note: acted on flag (1) — stripped the `Generate task harder than expert level!` line (and its trailing blank line) from the `scenario:` block of SCAFFOLD.yaml. Re-parsed the file with yaml.safe_load afterwards: valid, 13 top-level keys intact, 0 remaining occurrences of the directive across all three scaffold files.

## Step 3: Copy Shared Files — 2026-09-05T21:02:28.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T21:15:50.000Z

Subagent summary (verbatim):

PRD generated and all three hard contracts pass.

**Output:** `workspace/PRD.md` — **496 lines / 100,543 bytes**, ending at a complete section boundary (the last row of the §5 error table, `ERR_REMEDIATION_REFUNDS_PENDING | 409`; verified by re-reading the final 40 lines).

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Users, Roles, and Access Control · 2.2 API Response Structure (byte-verbatim, copied by `cat` from the canonical source file; `diff` shows only one added trailing newline) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps, and Version Counters · 2.5 The Logical Clock · 2.6 Path Resolution and Foreign-Key Existence · 2.7 Optimistic Concurrency on Parent Records · 2.8 Percentages, Cents, and Rounding Discipline · 2.9 The Order of Rejection · 2.10 Segregation of Duties · 2.11 Cascade Integrity and Conserved Quantities
- §3 Business Logic — 3.1 Jurisdictional Law Variance and the Prohibition Cascade · 3.2 Merchant Onboarding and the Documented-Cost Chain · 3.3 Program Construction: Pinning, Scope, and the Effective Cap · 3.4 The Rate Table and Its Separation Rules · 3.5 Network Registration and the Notice Period · 3.6 Disclosure Artifacts and Program Readiness · 3.7 The Program Lifecycle and Its Cascades · 3.8 Terminals: Configuration, Enforcement, and the Quarantine Cycle · 3.9 Capturing a Sale: Rate Selection and Dual-Variant Pricing · 3.10 Complaints, Exposure Scoring, and the Remediation Order · 3.11 Remediation Refunds, Ledger Compensation, and the Reporting Surfaces
- §4 Endpoint Definitions (49 rows, 4 columns) · §5 Error Code Catalogue (55 rows, 2 columns)

**Coverage:** 11 entities and all 96 distinct field names; 49 endpoints; 55 error IDs (all mentioned in §2/§3 narrative, none with a conditions column in §5); 7 state machines with all 34 transitions incl. the `ComplaintCase` dual dimension and both `RESTORE` branches; all 13 calculations in operator-free prose (incl. the pinned average-ticket → documented-cost → effective-cap chain, three-way cap minimum, credit-only rate selection with rank/tie-break, the three pricing arms, both exposure-score methods, per-line-vs-pooled settlement divergence, and both closed-vs-half-open window conventions); all 40 validation rows rendered as an explicit 40-step rejection ladder with each rule's `applies_to` scope enumerated; both `concurrency_rules` (write op + `expected_program_version` / `expected_merchant_version` + `ERR_STALE_*_VERSION` + 412); all 6 roles with `identity` translated (2 entity-backed, 4 opaque).

**Contract reports**

```
Field coverage check:
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints[].request_body (incl. occ_field): 53 required, 53 present, 0 missing
- endpoints[].query_params + computed output keys: 39 required, 39 present, 0 missing
Status: PASS   (two passes; pass 2 added Program activated_at/activated_by_user_id nulls and ComplaintCase initial nulls)
```
```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 34 checked, 34 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields[] structured content: 96 checked, 96 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (activation arms, RESTORE A/B, void arms, registration decisions, exposure methods, ledger increase/decrease/restore), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1045
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Zero fuzzy words (`approximately`/`roughly`/`conservatively`/…), zero pseudocode operators, and zero occurrences of `difficulty`, `expert level`, `benchmark`, `test suite`, or `scaffold`. The two withheld design files were never opened. Scratch dir `.scratch/step4` removed; parent `.scratch/` left in place.

Orchestrator verification (truncation guard): independently ran `wc -l` (496), `tail -25`, and `grep -n '^#'` on PRD.md. The file ends on the final row of the §5 error table — a real section boundary, not mid-sentence — and all five top-level sections (§1–§5) plus all 11 §2 and 11 §3 subsections are present. `grep -in "expert level|difficulty|scaffold|test_recipe"` returned zero matches. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T21:50:44.000Z

Subagent summary (verbatim):

Implementation complete.

**Location:** `workspace/implementation/`

**Modules (3,061 lines total, all `py_compile` clean):**

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `exec python3 app.py`, guarded pip install, `$PORT`, foreground (chmod +x) |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 64 | `create_app()`, 9 blueprints, ApiError/HTTPException/Exception handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 86 | in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), id/ts/`_seq` helpers |
| `errors.py` | 81 | `ApiError` + HTTP status + default message for all 56 error ids |
| `envelope.py` | 93 | `meta`/`response_type`/`data`, list meta, pagination params (limit 10/1..100) |
| `validation.py` | 165 | body parsing (Decimal-safe), coercers, `round_half_up`/`round_cents` |
| `auth.py` | 169 | `X-User-ID`/`X-User-Role`, 6 roles, ownership, action-role tables, 404 resolvers |
| `calc.py` | 232 | constants, documented cost, effective cap, disclosure readiness, exposure scores, ledgers |
| `serialize.py` | 217 | per-entity serializers with read-time derived aggregates |
| `cascades.py` | 138 | suspend/withdraw/remediation/prohibition/re-permission/close-bubble cascades |
| `listing.py` | 54 | conjunctive filters + paginated list responses |
| `routes_jurisdictions.py` | 150 | jurisdictions, law changes, clock control |
| `routes_merchants.py` | 164 | merchants, cost documentation (OCC), terminal provisioning |
| `routes_programs.py` | 390 | programs, PATCH, activation ladder, status actions, exposure + settlement summaries |
| `routes_rates.py` | 251 | rate rules (buffer/tier/cap), network registrations, decision, effectuate |
| `routes_artifacts.py` | 108 | disclosure artifact draft/attest with overlap check |
| `routes_terminals.py` | 135 | configure, ENFORCE/QUARANTINE/RESTORE |
| `routes_transactions.py` | 204 | sale capture, rate-rule selection, three pricing arms |
| `routes_complaints.py` | 185 | complaint cases, investigation + remediation actions |
| `routes_refunds.py` | 164 | refund create/issue/void with ledger movements |

**Endpoints: 49 implemented — an exact set match against the 49 rows of PRD §4** (verified programmatically via `app.url_map` vs. the PRD endpoint table; zero missing, zero extra).

**Smoke verification** (three suites, all against a live server): full happy path (cost doc → program → rate rules → registration/ack/effectuate → artifacts → activation → terminal enforce → sale → complaint → substantiate → remediation → refund/issue/close); the cash-discount arm (2.19% → discount 219, cash price 9781, total 10000); OCC 412 on both `expected_program_version` and `expected_merchant_version`; rate-window buffer boundaries (0d and 28d rejected, 30d accepted, other brand unconstrained); debit exclusion and debit-surcharge prohibition; `ERR_SURCHARGE_AMOUNT_MISMATCH` and `ERR_RECEIPT_LINE_ITEM_REQUIRED`; SoD 403s on activation and refund issuance; law-change prohibition cascade (program → DISABLED/JURISDICTION_PROHIBITION, terminal → QUARANTINED/PROGRAM_DISABLED) and re-permission cascade (→ SUSPENDED/OPERATOR_SUSPENSION with cap recomputed to the new jurisdiction cap); withdrawal cascade; settlement/exposure summaries restricted to the 4 non-merchant roles; pagination validation (`limit=0`/`limit=101` → 400) and 401/403/404 paths.

**No persistence, no seeding:** storage is module-level dicts only; a final clean boot on port 39418 returned `GET /jurisdictions` with `total_count: 0`, confirming the store is empty on every `start.sh` invocation.

**Cleanup:** both smoke servers were killed by their recorded PIDs only (`pkill -P <pid>; kill <pid>` — never a broad pkill); `ss -ltnp` confirms ports 39417 and 39418 are free. `.scratch/step6` was removed; the sibling `.scratch/step5` is untouched. `__pycache__` and the temp boot log were deleted, leaving 21 source files. The test suite directories, difficulty/corner design files, and sibling task dirs were never read.

## Step 5: Generate Unit Tests — 2026-09-05T22:30:09.000Z

Subagent summary (verbatim):

Step 5 is complete. Both output directories are at the **task root** (`test_helpers/` and `test_suite/`); nothing named `test_helpers` or `test_suite` exists under `workspace/`.

## Files written

**`test_helpers/`** (1,963 lines): `__init__.py` 37, `api_client.py` 215, `api_errors.py` 123, `assertions.py` 310, `constants.py` 80, `factories.py` 279, `fixtures.py` 672, `test_users.py` 65, `types.py` 382

**`test_suite/`** (5,388 lines, 45 of them `conftest.py`) — queue B in `test_01`–`test_10`, queue A in `test_11`–`test_15`:

| file | lines | tests |
|---|---|---|
| test_01_entities_and_field_contracts | 416 | 15 |
| test_02_registration_and_artifact_state | 293 | 8 |
| test_03_program_and_case_cascades | 293 | 8 |
| test_04_documented_cost_and_effective_cap | 389 | 8 |
| test_05_pricing_windows_and_reporting | 354 | 8 |
| test_06_statutory_and_rate_table_validations | 324 | 10 |
| test_07_capture_and_refund_validations | 293 | 9 |
| test_08_not_found_uniqueness_and_envelopes | 323 | 15 |
| test_09_endpoint_surfaces_and_immediate_consistency | 360 | 8 |
| test_10_role_gates_concurrency_and_cascades | 590 | 17 |
| test_11_dual_variant_pricing_and_settlement | 322 | 6 |
| test_12_program_cycle_and_statutory_cascades | 202 | 6 |
| test_13_complaint_dimensions_and_exposure | 245 | 6 |
| test_14_rejection_order_and_boundaries | 288 | 8 |
| test_15_gates_windows_and_refund_compensation | 451 | 11 |

**143 tests total.** Every `.py` file compiles (`python3 -m py_compile`), every file has ≥5 tests.

## Design-index coverage

- **Queue A (difficulty):** 18 / 18 instances translated, **0 skipped**; every instance carries ≥2 tests (37 tests).
- **Queue B (corner):** 106 / 106 non-stub instances translated, **0 skipped** (106 tests — exactly one test per instance).
- The 18 `excluded_because:` stubs were not translated; all 18 of their `difficulty_instance:` cross-references resolve to real queue-A instances.
- Tag audit: 143 tests, 143 `Design:` lines, one per test, zero duplicates, zero pointing at a stub or a non-existent instance. Every quoted PRD citation (≥40 chars) survives a literal substring match against `workspace/PRD.md`.

**Skip list: empty.**

## Four design/PRD conflicts resolved in favour of the PRD

I translated these instances but asserted the PRD-derived value rather than the yaml's, instead of skipping:

1. `Corner/endpoints/disclosure_artifact_creation_links_the_operators_own_program` — yaml asserts `disclosure_ready == true` on a DRAFT program; §3.3 says a new program starts `false` and nothing recomputes readiness on *drafting*. Assertion dropped; rest of the instance translated.
2. `Corner/consistency_model/activation_response_already_carries_the_recomputed_cap_and_readiness` — yaml asserts `version == 4`; the PRD never says whether effectuation bumps the *program* version, so the test asserts `before + 1` per §3.7.
3. `Corner/cross_cutting_complexity_layers/cardholder_case_below_the_remediation_threshold_leaves_the_program_active` — yaml asserts `ag_exposure_score == 0.00` and `posture_multiplier == 1.0`, but its own setup builds a PERMISSIVE AZ jurisdiction and §3.10's AG method counts every substantiated case regardless of source: 20 × 0.5 = **10.00**, posture **0.5**. Asserted those.
4. `Corner/cross_cutting_complexity_layers/registration_revocation_cascades_three_levels_and_skips_the_configured_terminal` — yaml asserts the untouched terminal's `quarantine_reason == null`; the PRD enumerates `NONE`. Asserted `"NONE"` (same resolution already used in `test_03`).

## Two latent bugs fixed in already-written files

- `test_helpers/fixtures.py`: `setup_draft_program` had no `**kwargs`, so the five existing call sites in `test_13`, `test_14` and `test_15` that pass `legal_name=` / `mcc=` would have died with `TypeError` at collection time. It now accepts `**merchant_overrides` and forwards them to `setup_merchant_with_documentation`. I re-audited every `setup_*` call in the suite: all surplus kwargs (`serial_prefix`, `rate_pct`, `product_tier`, `effective_to`) resolve to declared parameters further down the chain.
- `test_09`: two citations were labelled §2.8 (rounding discipline) when the sentence lives in §2.11 (cascade integrity); corrected.

Scratch space `.scratch/step5/` was removed; the parent `.scratch/` was left in place. The suite has never been executed against an implementation — I did not read, list or grep `workspace/implementation/`.

## Step 7: Run Tests and Iterate — 2026-09-05T22:51:44.000Z

Subagent summary (verbatim):

Confirmed: `implementation/` and `worklog.md` untouched (mtimes 21:33–22:30, before my 22:39 edits). Only 5 files in `test_suite/` changed.

## Summary

**Iterations run:** 2 (sweep → fix batch → sweep).

**Final per-round results:** rounds 1–8 all **143 / 143 passed**. Iteration 1 was 137/143 in all 8 rounds — the same 6 tests failed deterministically in every round, so there was no flakiness or load-induced noise to chase.

**Tests deleted:** none. All 6 failures were test-artifact defects, not PRD-silence, so nothing met the deletion criterion.

**Fixes applied to `test_helpers/`:** none — the fixtures, factories, header builders and assertion library were all PRD-faithful. Every defect was at a `test_suite/` call site.

**Fixes applied to `test_suite/`:**

- `test_04_documented_cost_and_effective_cap.py` :: `test_re_permission_propagates_the_new_statutory_cap_into_the_program` — the setup called `apply_law_change(jurisdiction_id, False)` on an AZ jurisdiction carrying `surcharge_cap_pct` 4.0. PRD §3.1 re-evaluates cap coherence against the post-change picture, so turning surcharging off while leaving a cap in place is correctly `ERR_JURISDICTION_CAP_REQUIRED`. Added `surcharge_cap_pct=None`, matching the six sibling call sites in test_12 (minority-call-site drift).
- `test_05_pricing_windows_and_reporting.py` :: `test_a_clock_landing_exactly_on_expiry_leaves_the_program_unready` — removed the single assertion that a *rejected* activation persists `disclosure_ready == false`. PRD §2.11 states a failing request "changes nothing", so a PRD-faithful reader legitimately computes readiness transiently for the §2.9 step-32 gate and persists it only on success. Not uniquely derivable; the covered assertions (half-open upper bound → `ERR_DISCLOSURE_INCOMPLETE`, artifacts stay `ATTESTED` with `expired_reason` `NONE`, status/`activated_at` unmoved) were all kept per the partial-coverage rule.
- `test_06_statutory_and_rate_table_validations.py` :: `test_activation_needs_a_rate_rule_for_every_effective_network` — the setup submitted a second (MASTERCARD) registration on a program already in `PENDING_REGISTRATION`. PRD §3.5 says twice and verbatim that submission is available only from `DRAFT` and any other state is `ERR_INVALID_PROGRAM_STATE`. Rebuilt the setup PRD-legally: one VISA registration driven to `EFFECTIVE`, with the program's only rate rule priced on MASTERCARD, which reaches the same §2.9 step-30 brand-coverage rule the test targets.
- `test_11_dual_variant_pricing_and_settlement.py` :: `test_second_cost_document_freezes_the_realised_average_ticket_and_lowers_the_cap` and `test_rate_rule_at_the_superseded_cost_is_rejected_once_the_program_repins` — both PATCHed the `ACTIVE` program that had captured the sales, which PRD §3.3 forbids ("Attempting the same update on a program in `ACTIVE`… is rejected with `ERR_INVALID_PROGRAM_STATE`"). Each now re-pins a `DRAFT` sibling program created on the same merchant against the first document while it is still `ACTIVE`, preserving the full documented-cost chain assertions (average ticket 5308, `documented_cost_pct` 2.1784, re-pinned cap 2.1784, and the `ERR_SURCHARGE_CAP_EXCEEDED` refusal of a 2.19 rate against the lowered cap).
- `test_10_role_gates_concurrency_and_cascades.py` :: `test_the_officer_who_attested_the_signage_cannot_activate` — `TypeError: string indices must be integers`; the test iterated the `attest_disclosures` return value (an `artifact_type` → artifact mapping) directly instead of `.values()`. Fixed to `artifacts.values()`.

**Fixes applied to `implementation/`:** none. Every implementation behaviour under investigation traced to a verbatim PRD sentence — the §3.1 cap-coherence re-evaluation, the §3.5 DRAFT-only registration gate (with §2.9 uniqueness at step 11 correctly pre-empting the step-13 state gate, which is why the duplicate-registration test passed throughout), the §3.3 pre-activation-only partial update, and the §2.11 "fails and changes nothing" discipline. No PRD-required check was removed or weakened, and no test was skipped, xfailed, or downgraded from an exact `error_id` assertion.

Orchestrator verification: independently inspected all 8 `workspace/implementation/results.$i.json` files (all written 22:44). Every round reports `passed=143, failed=0, total=143, errors=0`. Clean sweep confirmed, not merely claimed.

Step 8 gating decision: the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met — Step 7 applied 6 `test_suite/` fixes across 5 files, including one assertion removal for a §2.11 unique-derivability collapse. Step 8 therefore runs. Note that with 0 `implementation/` fixes, a byte-identical or near-identical PRD_FINALIZED.md is a legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-05T23:00:48.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` differs from `PRD.md` by exactly one inserted sentence (one edited line out of 496 — 0% line-count delta, ~1 line touched = 0.2% of the file).

## Change

- **§3.1 (Jurisdictional Law Variance, law-change paragraph)** — *insert* — pinned that a law-change body naming `surcharge_cap_pct` explicitly as `null` is a *restatement* that clears the stored ceiling (as opposed to an omission, which keeps the current cap). Impl: `routes_jurisdictions.py:104-110` (`MISSING` → keep current, explicit `None` → clear, value → parse) and `:122` (`_check_cap_coherence` against the post-change picture).

Trace to `<step_7_diff>`: item 1 (`test_04 :: test_re_permission_propagates_the_new_statutory_cap_into_the_program`). The fix added `surcharge_cap_pct=None` to the `apply_law_change(..., False)` call; `factories.law_change_payload` puts the key in the body as JSON `null`, so the fix's legality depends entirely on null-clearing. PRD said only "flags not named in the request keep their current values" and had no global null-vs-omitted rule anywhere in §2 or §4 — and since PRD forbids auto-nulling the cap when permission is withdrawn, an implementer reading `null` as "not named" (the convention the §3.3 partial update actually uses) could never legally turn surcharging off. Genuine, behaviorally consequential silence.

### Pre-edit search log (this edit)
- **(a) Subject:** null vs omitted semantics for `surcharge_cap_pct` in a law-change request body, and what "not named" means.
- **(b) Paths enumerated/read:** `routes_jurisdictions.py` `_cap` (:25-28), `_check_cap_coherence` (:31-36), `create_jurisdiction` cap resolution (:52-53, where `MISSING` and `None` are equivalent), `apply_law_change` cap resolution (:104-110), coherence call site (:122), persistence (:125-130) and both cascade triggers (:132-135); the sibling restatable fields loop and posture (:113-120); `validation.py` `field`/`require_present`/`as_bool`/`as_enum`/`as_decimal` (null handling — explicit `null` on any of the boolean/posture fields is `ERR_INVALID_REQUEST` at step 8, *not* "keep current"); `routes_programs.py` `patch_program` (:155-162, where explicit `null` deliberately means "not supplied" — a different endpoint); `calc.effective_surcharge_cap` (:105-108, a null cap drops out of the min); `serialize.py:21`; grep for `surcharge_cap_pct` across all impl modules.
- **(c) Wording adjustment:** deliberately scoped the sentence to `surcharge_cap_pct` alone and dropped a drafted clause asserting that the other restatable fields "have no null form / reject one at the request-shape step". Both because that claim is outside the Step 7 site's scope and because a generalized "explicit null restates" sentence would have contradicted the boolean/posture paths (400) and `patch_program`'s opposite convention. Also said nothing about how a cleared cap participates in `effective_cap_pct`, to avoid narrowing `calc.effective_surcharge_cap`.

## Items that correctly produced no edit
- **test_04 cap coherence itself** — PRD §3.1 already says verbatim that a change turning surcharging off "while leaving a cap in place" is `ERR_JURISDICTION_CAP_REQUIRED`; impl matches exactly.
- **test_05 rejected activation / `disclosure_ready`** — the deleted assertion contradicts §2.11 ("it fails and changes nothing"); impl gates step 32 on a freshly computed `calc.disclosure_readiness` (`routes_programs.py:214-218`) and persists via `recompute_disclosure_ready` only on success (:268, :310), while terminal enforcement reads the stored flag (`routes_terminals.py:84`, :102) — exactly the fresh-vs-stored contrast §3.6 ¶271 already draws. Determinate; no edit.
- **test_06 second registration from `PENDING_REGISTRATION`** — §3.5 states the DRAFT-only gate twice, and §2.9 fixes uniqueness (step 11) before the state gate (step 13); `routes_rates.py:139-147` matches both.
- **test_11 PATCH on `ACTIVE`** — §3.3 names `ACTIVE` explicitly in the `ERR_INVALID_PROGRAM_STATE` list; `routes_programs.py:171-173` matches. The re-pinning/documented-cost chain the fixed tests assert is fully determined by §3.2/§3.3 (and `calc.average_ticket_snapshot`'s outcome filter is a no-op, since all three capture outcomes are approvals).
- **test_10 `.values()` TypeError** — pure test-artifact bug against a `test_helpers` return shape; no API surface involved.

Orchestrator verification: ran `diff PRD.md PRD_FINALIZED.md` — a single changed line (201), the §3.1 law-change paragraph, adding the null-vs-omitted `surcharge_cap_pct` sentence. Both files 496 lines. Scope respected; no other section touched.

## Step 9: Complete PRD — 2026-09-05T23:27:07.000Z

Orchestrator decision: ran the completeness scan as THREE sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than a single subagent. Rationale: the implementation is ~3,000 lines across 21 modules and a single-agent full scan has previously produced a byte-identical no-op output. Pass 1 owned the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from re-copying (that would silently destroy the prior pass's edits). Partition: pass 1 = app/store/errors/envelope/validation/auth/listing/serialize; pass 2 = calc/cascades/routes_jurisdictions/routes_merchants/routes_programs; pass 3 = routes_rates/routes_artifacts/routes_terminals/routes_transactions/routes_complaints/routes_refunds. Each pass could READ unassigned modules for consistency but only edit for its own.

### Pass 1 summary (verbatim)

Pass 1 complete.

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed as the first action (verified byte-identical before editing).

**Counts after edits:** PRD_FINALIZED.md 496 lines / 100,843 chars → PRD_COMPLETED.md 496 lines / 104,934 chars (**+4,067 chars, 0 new lines**). 13 lines changed (15, 53, 60, 82, 84, 86, 90, 106, 124, 136, 141, 336, 382) — all in-paragraph inserts/revisions, no new sections, no table or code-fence touched.

**Classification:** 11 ambiguity-pins, 2 mismatch-revisions.

**Changes**
- §2.2 (error envelope) — revise — mismatch — PRD claimed the error envelope covers "4xx status codes" only; impl uses the same envelope for the HTTP 500 an unhandled fault produces, carrying `ERR_INVALID_REQUEST` — `app.py:50`
- §2.6 (path resolution) — revise — mismatch — PRD's "each entity has its own not-found code" was a false universal: `BrandRateRule` has none and an unresolvable rate-rule id reports `ERR_PROGRAM_NOT_FOUND` — `auth.py:144`
- §2.1 (headers) — insert — ambiguity — header values are trimmed before the presence/emptiness/role checks, so a whitespace-only header counts as empty — `auth.py:40`
- §2.2 (`api_request_timestamp`) — insert — ambiguity — meta timestamp comes from real wall-clock time, not the logical clock — `envelope.py:19`
- §2.3 (pagination) — insert — ambiguity — non-integer `limit`/`offset` → 400; empty-string parameter falls back to default; whitespace tolerated; `offset` unbounded above and an over-range offset yields an empty page with `has_more` false — `envelope.py:69`, `envelope.py:92`
- §2.3 (ordering) — insert — ambiguity — with the clock frozen, `created_at` ties are common; ties break by creation sequence, making the order total and stable — `store.py:84`
- §2.3 (filters) — insert — ambiguity — blank filter treated as absent, undefined query params ignored, and an unmatchable enum/boolean filter value selects nothing (200, empty `data`, `total_count` 0) rather than 400 — `listing.py:11`, `listing.py:38`
- §2.4 (identity) — insert — ambiguity — any undeclared body field is dropped, not just a client-supplied `id` — `validation.py:38`
- §2.8 (rounding) — insert — ambiguity — percentages/cents serialise as bare JSON numbers with trailing zeros insignificant (2.1900 → `2.19`) — `envelope.py:30`
- §2.9 step 3 — insert — ambiguity — an unrecognised `action`/`decision` is not an action-role failure; it falls through to step 8 as `ERR_INVALID_REQUEST` — `auth.py:80`
- §2.9 step 8 — insert — ambiguity — required-field `null` counts as absent; missing/malformed/non-object body is a step-8 defect and nowhere earlier; numbers accept numeric strings while booleans must be real JSON booleans and excess decimal places are rejected; instants accept a bare date (midnight UTC), naive = UTC, offsets converted — `validation.py:19,44,60,97,137`
- §3.9 (capture) — insert — ambiguity — pins the transaction representation's exact field set, including the echoed `requested_surcharge_cents`/`receipt_line_present` and the absence of `updated_at`/`version` — `serialize.py:159`
- §4 (endpoint preamble) — insert — ambiguity — trailing slash accepted; unknown path/method answered with the standard envelope carrying `ERR_INVALID_REQUEST` at 404/405, not a not-found-family code — `app.py:29,45`

**Modules scanned and already fully pinned (no edit needed):** `errors.py` (all 55 `error_id → status` entries diff clean against the §5 table, both directions; default messages are free prose the PRD does not pin) and `auth.py`'s role list, action-role tables, ownership and complaint-channel rules (they match §2.1/§2.9 exactly — only the two behaviours above needed pinning). `store.py`'s clock default, UUID ids, 3-digit `Z` timestamps, 24-hour day arithmetic and version/`updated_at` discipline were already pinned by §2.4/§2.5; `serialize.py` field sets for all ten versioned entities already matched §3 prose exactly (only `Transaction` was under-specified).

**Consistency checks done (read-only, no edits):** confirmed all body foreign keys pass through `as_string` first, so `_lookup`'s non-string branch is unreachable and I did *not* claim a 404 for a wrong-typed FK; confirmed every numeric field routes through `as_int`/`as_decimal` with `max_decimals=4`, every boolean through `as_bool`, and every instant (including the settlement-summary query bounds) through `as_instant`, so the step-8 universals hold across `routes_*.py`.

### Pass 2 summary (verbatim)

**No re-copy performed.** I edited `PRD_COMPLETED.md` in place with 14 targeted `Edit` calls (12 substantive changes + 3 self-corrections to my own new wording). All 12 of pass 1's inserted sentences verified still present afterwards (grep count 1 each).

| | before | after |
|---|---|---|
| lines | 496 | 496 (no new paragraphs/sections) |
| chars | 104,934 | 109,653 |

**Counts: 5 mismatch-revisions, 7 ambiguity-pins.**

Mismatches (PRD asserted something impl does not do):
- **§2.4 (line 96) — revise — mismatch** — "a cascade that changes a parent's derived fields bumps the parent's `version`" was false: a `Merchant` whose `enforcing_terminal_count` shifts is never versioned (census is read-derived); pinned that merchant `version` moves on exactly three writes (cost-doc filing, sale capture, issue/void-issued refund). `cascades.py:13-38`, corroborated by no `touch(merchant)` in `routes_terminals.py`.
- **§3.3 (line 223) — revise — mismatch** — dropped "must be in state `ACTIVE` at the moment of pinning"; creation accepts a `SUPERSEDED` document, staleness being judged only at ladder step 25. `routes_programs.py:89-103`.
- **§3.6 (line 271) — revise — mismatch** — "four moments" was wrong on both sides: the bubble-up out of `REMEDIATION` is a fifth, and the withdrawal cascade is not one. `cascades.py:103` / `cascades.py:77-86`.
- **§3.6 (line 273) — revise — mismatch** — "In both cases the program's `disclosure_ready` is recomputed" — only the remediation cascade does; withdrawal expires artifacts and leaves the flag true. `cascades.py:77-86`.
- **§3.7 (line 277) — revise — mismatch** — "`disable_reason` always explains why it is not `ACTIVE`" — `withdraw_program` never writes `disable_reason`, so a program withdrawn from `ACTIVE`/`DRAFT` is `WITHDRAWN` with `NONE`. `cascades.py:77-86`.

Ambiguities (PRD silent):
- **§2.5 (line 102) — insert — ambiguity** — the clock may be moved backwards; unconstrained instant, 200 either way. `routes_jurisdictions.py:140-150`.
- **§2.7 (line 118) — insert — ambiguity** — both `expected_*_version` fields are integers ≥ 0; a negative value is a 400 at ladder step 8, not a 412. `routes_merchants.py:80`, `routes_programs.py:153`.
- **§3.3 (line 233) — insert — ambiguity** — an optional PATCH field sent as explicit `null` counts as absent; a version-only PATCH is a no-op that still recomputes the cap and bumps `version`; the replacement doc need not be `ACTIVE`. `routes_programs.py:155-186`.
- **§3.7 (line 281) — insert — ambiguity** — the two activation precondition lists are ordered by subject, not by evaluation: §2.9's ladder decides, so segregation (15) beats prohibited-structure (16/17) and step 25 follows both. `routes_programs.py:251-261`.
- **§3.7 (line 285) — insert — ambiguity** — status-action `reason` must be 1–500 chars when supplied (empty string ⇒ 400), `null` counts as omitted, and it is discarded rather than persisted. `routes_programs.py:286-287`.
- **§3.7 (line 289) — insert — ambiguity** — withdrawal's terminal disable bumps each terminal's `version` and does **not** rewrite `quarantine_reason`, so a `PROGRAM_SUSPENDED` terminal reaches `DISABLED` still carrying that reason. `cascades.py:31-38`.
- **§3.11 (line 372) — insert — ambiguity** — settlement window: empty-string bound = omitted, unparseable = 400, the two bounds are never compared (inverted window ⇒ 200 with all zeros); scope is the sale's own stored `program_id`, not a terminal's later re-binding. `routes_programs.py:347-359`.

**Assigned modules found already fully pinned (no edit traceable to them):**
- **`calc.py`** — every constant (5000, 3.0, 10.0, 20/8/100/30, source and posture multipliers, 10/20/30-day response windows), the two-step documented-cost derivation and its rounding order, the average-ticket snapshot including the `occurred_at <= clock` bound and the no-transactions fallback, the effective-cap min, the half-open artifact window, both exposure methods with ceiling-after-rounding, and every ledger/census formula were already uniquely pinned by §2.8, §3.2, §3.3, §3.6, §3.10, §3.11.
- **`routes_merchants.py`** — merchant creation and defaults, cost-doc field ranges and stamping, the supersede chain, and terminal-provisioning defaults were all already pinned (its only contribution was the shared version-field range item).
- **`routes_jurisdictions.py`** — jurisdiction registration, the cap-coherence rule on both halves, law-change restatement-vs-omission semantics (including explicit `null` clearing the cap), and both the prohibition and re-permission cascades were already pinned; only the clock endpoint was silent.

One thing I deliberately did **not** write: `effective_surcharge_cap` skips a null statutory cap rather than treating it as binding, but I traced every `recompute_cap` call site and found the null-cap case unreachable (the `CASH_DISCOUNT` arm short-circuits, and every surcharge-arm caller has already asserted `surcharge_permitted`, which coherence makes imply a non-null cap), so pinning it would have invented behavior the service cannot exhibit.

### Pass 3 summary (verbatim)

Done. Structural check passed.

**No re-copy performed** — I edited `workspace/PRD_COMPLETED.md` in place with 19 targeted `Edit` calls across 15 lines. All 25 lines changed by passes 1 and 2 are still present and untouched (full-file diff vs `PRD_FINALIZED.md` now shows exactly 40 changed lines = 25 prior + 15 mine).

- Before: 496 lines / 109,653 chars → After: **496 lines / 114,298 chars**
- **Ambiguity-pins: 15. Mismatch-revisions: 4.**

### Changes
- §3.5 — revise — mismatch — dropped the claim that submission checks the jurisdiction's `surcharge_permitted`; impl checks only `SURCHARGE` + `DRAFT`, and a prohibition arrives via the §3.1 cascade leaving the program `DISABLED`, so the refusal is `ERR_INVALID_PROGRAM_STATE` — routes_rates.py:145
- §3.5 — insert — ambiguity — a submission naming a `CASH_DISCOUNT` program is `ERR_INVALID_PROGRAM_STATE` whatever its status — routes_rates.py:145
- §3.5 — insert — ambiguity — uniqueness (step 11) is judged before the program-state gate (step 13): same-network repeat → `ERR_DUPLICATE_NETWORK_REGISTRATION`, other network → `ERR_INVALID_PROGRAM_STATE` — routes_rates.py:139-147
- §3.5 — insert — ambiguity — `decision_note` is 1–1,000 chars; omitted or explicit `null` leaves it null — routes_rates.py:197-212
- §3.5 — revise — mismatch — removed "a program can hold one effective registration and one still inside its notice period"; the `DRAFT`-only submission gate makes a second registration unreachable — routes_rates.py:145
- §3.6 — insert — ambiguity — drafting is permitted against a program in any status (`WITHDRAWN` included) and moves no program field — routes_artifacts.py:22-49
- §3.6 — insert — ambiguity — attestation consults only the artifact's own state (no program-status gate, no merchant-ownership requirement) — routes_artifacts.py:52-89
- §3.8 — revise — mismatch — configuration is also permitted from `ENFORCING` (dropping the terminal back to `CONFIGURED`); `DISABLED` is the only refusing state — routes_terminals.py:36-38
- §3.8 — insert — ambiguity — `bin_table_version` is 1–100 chars — routes_terminals.py:32
- §3.8 — insert — ambiguity — configure precedence: terminal `DISABLED` then `WITHDRAWN` program (step 13) then cross-merchant (step 21) — routes_terminals.py:36-44
- §3.8 — insert — ambiguity — terminal-action `note` is 1–1,000 chars, `null` = omitted, validated then discarded — routes_terminals.py:68-70
- §3.8 — insert — ambiguity — on `ENFORCE`, debit exclusion (step 19) answers ahead of readiness (step 32) — routes_terminals.py:81-86
- §3.9 — insert — ambiguity — capture gates are judged in ladder order 14/16/20/21 with the credit-only rule at 18 between; a `CASH_DISCOUNT` capture consults no jurisdictional permission flag — routes_transactions.py:92-116
- §3.9 — revise — mismatch — "`created_at` is the only tie-break" was false: rules sharing `effective_from` and `created_at` are broken by filing sequence (`_seq`) — routes_transactions.py:38
- §3.10 — insert — ambiguity — investigation `note` is 1–2,000 chars and discarded — routes_complaints.py:100-102
- §3.10 — insert — ambiguity — `reviewed_by_user_id` is written by `REVIEW` alone; substantiate/dismiss never write it — routes_complaints.py:111-131
- §3.10 — insert — ambiguity — `plan_summary` is 1–2,000 chars; supplied on `ACCEPT_PLAN`/`CLOSE` it is bound-checked then discarded — routes_complaints.py:151-158
- §3.11 — insert — ambiguity — issuance precedence: case `remediation_state`, then refund state, then segregation of duties — routes_refunds.py:92-101
- §3.11 — insert — ambiguity — void precedence: already-`VOIDED` (`ERR_INVALID_REFUND_STATE`) beats the closed-case check — routes_refunds.py:125-134

### Assigned modules already fully pinned (no edit)
- `routes_rates.py` rate-rule half (§3.4): validation ranges, the whole-day gap/overlap-zero convention, the buffer→tier→cap check order, cap equality passing, `WITHDRAWN`-only refusal, program version bump and filters all matched PRD exactly.
- `routes_refunds.py` creation path (§3.11 ¶1): FK/state/scope/remainder/duplicate order and the ISSUED-only remainder definition were already pinned; only the issue/void precedence needed pinning.
- `routes_complaints.py` scoring/cascade/bubble-up paths (§3.10) matched impl exactly (thresholds, which scores each action recomputes, blocking-case test, readiness requirement).

### Final-pass structural check
`PRD_COMPLETED.md` is **496 lines**, its `grep -n '^#'` heading list is **byte-identical** to `PRD_FINALIZED.md`'s (all 33 headings, same line numbers — no section dropped or shifted), and the file still ends at the final §5 row `| ERR_REMEDIATION_REFUNDS_PENDING | 409 |`, not mid-sentence.

### Orchestrator verification of Step 9

- `wc -lc`: PRD.md 496/100,543 → PRD_FINALIZED.md 496/100,843 → PRD_COMPLETED.md 496/114,298. PRD_COMPLETED.md is NOT byte-identical to its source (the known silent-no-op failure mode): 40 changed lines, +13,455 chars over PRD_FINALIZED.md.
- Heading lists of PRD_FINALIZED.md and PRD_COMPLETED.md diff clean; file ends at the final §5 error-table row.
- Combined totals across the three passes: 33 ambiguity-pins, 11 mismatch-revisions, 0 new sections, 0 new lines.
- `implementation/` mtimes are all 21:21–21:34 — unchanged by Steps 8 and 9, and predating the 22:44 clean sweep. The 8×143/143 result therefore still certifies the exact implementation that PRD_COMPLETED.md documents; no re-sweep required.
- Leak check on PRD_COMPLETED.md for "expert level" / "scaffold": 0 matches.

PIPELINE COMPLETE.
