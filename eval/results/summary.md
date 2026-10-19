# Benchmark Results Summary
*Generated on results at report.py*

## Experiment 1: RAG Chunk Size vs Document Retrieval Hit@3 (3 Core Docs)
| Chunk Size | Total Queries (n) | Document Hit@3 | 95% Wilson CI | Finding |
| :--- | :--- | :--- | :--- | :--- |
| 300 chars | 30 | **100.0%** | [88.6%, 100.0%] | Uniform 100% document-level hit on 3 core synthetic documents |
| 500 chars | 30 | **100.0%** | [88.6%, 100.0%] | Uniform 100% document-level hit on 3 core synthetic documents |
| 800 chars | 30 | **100.0%** | [88.6%, 100.0%] | Uniform 100% document-level hit on 3 core synthetic documents |

## Experiment 1b: Distractor Corpus & Chunk-Level Retrieval Accuracy (18 Documents)
| Chunk Size | Corpus Docs | Answerable Queries | Chunk Hit@1 | 95% Wilson CI | Chunk Hit@3 | 95% Wilson CI | MRR | Finding |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 300 chars | 18 | 24 | **75.0%** | [55.1%, 88.0%] | **87.5%** | [69.0%, 95.7%] | **0.8056** | Multi-sentence clauses split across boundaries; CIs overlap at n=24 |
| 500 chars | 18 | 24 | **75.0%** | [55.1%, 88.0%] | **91.7%** | [74.2%, 97.7%] | **0.8333** | Multi-sentence clauses split across boundaries; CIs overlap at n=24 |
| 800 chars | 18 | 24 | **83.3%** | [64.1%, 93.3%] | **95.8%** | [79.8%, 99.3%] | **0.8889** | Highest point estimate; 95% CIs overlap across sizes at n=24 (no superiority claim) |

## Experiment 2: Reliability Factorial (JSON Mode x Retry)
| Configuration | Status | n | Repeats | First-Try Validity | 95% CI | Task Success | 95% CI | Mean Latency | Peak Ollama RSS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Canonical Run 1 (`json_on_retry_on`) | Completed | 45 | 1 | **100.0%** | [92.1%, 100.0%] | **80.0%** | [66.2%, 89.1%] | 27.86s* | 2351.3 MB |
| Canonical Run 2 (`json_on_retry_on_rerun`) | Completed | 45 | 1 | **97.8%** | [88.4%, 99.6%] | **80.0%** | [66.2%, 89.1%] | 55.39s* | 2205.5 MB |
| Canonical Pooled (`n=90`, Repeats=2) | Completed | 90 | 2 | **98.9%** | [94.0%, 99.8%] | **80.0%** | [70.6%, 87.0%] | 41.62s* | 2351.3 MB |
| Factorial: `json_on_retry_off` | *not run* | 0 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| Factorial: `json_off_retry_on` | Completed | 45 | 1 | **93.3%** | [82.1%, 97.7%] | **82.2%** | [68.7%, 90.7%] | 23.53s* | 2344.1 MB |
| Factorial: `json_off_retry_off` | Completed | 45 | 1 | **88.9%** | [76.5%, 95.2%] | **66.7%** | [52.1%, 78.6%] | 19.25s* | 2363.0 MB |

*Note on `json_on_retry_off`:* This configuration was not run because with JSON mode active (`json_mode=True`), the model achieved 100% first-try schema validity in Run 1 (45/45 valid, 0 retries required across all items) and 97.8% in Run 2 (where the single invalid item was an Ollama HTTP 500 token repeat limit abort, not a JSON schema error). Because format errors did not occur under JSON mode, running `json_on_retry_off` was omitted to avoid redundant CPU thermal throttling on the 8 GB laptop.

## Paired Exact McNemar Tests (Identical Items)
| Comparison | Common Items (n) | Both Pass | Both Fail | b (Cond 1 Fail, Cond 2 Pass) | c (Cond 1 Pass, Cond 2 Fail) | Total Discordant (b + c) | Exact Two-Sided p-value | Significance (alpha=0.05) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `Canonical Run 1 vs Baseline Prompt` | 45 | 23 | 7 | 2 | 13 | 15 | **0.00739** | **Significant (p < 0.05)** |
| `json_off_retry_on vs json_off_retry_off` | 45 | 29 | 7 | 1 | 8 | 9 | **0.03906** | **Significant (p < 0.05)** *(b+c < 10)* |
| `Canonical Run 1 vs json_off_retry_on` | 45 | 35 | 7 | 2 | 1 | 3 | **1.00000** | Not significant *(b+c < 10)* |
| `Canonical Run 1 vs Canonical Run 2` | 45 | 33 | 6 | 3 | 3 | 6 | **1.00000** | Not significant *(b+c < 10)* |
| `Canonical Run 1 vs Post-Hoc Variant` | 45 | 34 | 3 | 6 | 2 | 8 | **0.28906** | Not significant *(b+c < 10)* |

### Item-Level Flip Table: Canonical Run 1 vs Run 2
Across identical 45 items, exactly **6 items flipped** (Run 1 Pass -> Run 2 Fail: 3; Run 1 Fail -> Run 2 Pass: 3; McNemar p = 1.00000):

| Item ID | Suite | Question | Expected / Ground Truth | Run 1 Outcome | Run 1 Response Summary | Run 2 Outcome | Run 2 Response Summary | Flip Diagnosis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `rag_q09` | rag | What are the exact morning biometric scan window hours ... | `['08:15', '08:35']` | **PASS** | The exact morning biometric scan window hours at K... | **FAIL** | The provided documents do not contain this informa... | Stochastic premature abstention without tool call on Run 2 |
| `rag_q11` | rag | Who is the authorized Controller of Examinations under ... | `['Deshmukh']` | **PASS** | Based on the information provided in the documents... | **FAIL** | The provided documents do not contain this informa... | Stochastic premature abstention without tool call on Run 2 |
| `rag_q13` | rag | What is the minimum passing percentage required specifi... | `['42', 'percent']` | **FAIL** | The provided documents do not contain this informa... | **PASS** | According to the provided documents, the minimum p... | Model recovered from Run 1 premature abstention; searched documents and answered correctly |
| `rag_q14` | rag | What is the registration fee per theoretical credit for... | `['1,150', '1150']` | **FAIL** | I do not know. | **PASS** | The registration fee per theoretical credit for si... | Model recovered from Run 1 premature abstention; searched documents and answered correctly |
| `rag_q20` | rag | What is the daily session cap in minutes for users on C... | `['90', 'minutes']` | **FAIL** | The provided documents do not contain this informa... | **PASS** | The daily session cap in minutes for users on Cybe... | Model recovered from Run 1 premature abstention; searched documents and answered correctly |
| `rag_q30` | rag | What is the fee to reserve a private group study room o... | `['do not know', 'not mentioned', 'no information', 'does not contain', 'cannot find', 'not provided']` | **PASS** | I do not know. | **FAIL** | Error during model communication: Ollama chat erro... | Ollama HTTP 500 token repeat limit abort on Run 2 (transport error; tool_call_valid=False) |

## Failure Cause Classification Across All Configurations
| Configuration | Evaluated (n) | Failed Items | Premature Abstention | Wrong Answer After Retrieval | Wrong Tool | Invalid JSON | Timeout |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Canonical Run 1 (`json_on_retry_on`) | 45 | **9** | 6 | 3 | 0 | 0 | 0 |
| Canonical Run 2 (`json_on_retry_on_rerun`) | 45 | **9** | 4 | 4 | 0 | 1 | 0 |
| Canonical Pooled (`n=90`, Repeats=2) | 90 | **18** | 10 | 7 | 0 | 1 | 0 |
| Factorial: `json_off_retry_on` | 45 | **8** | 5 | 3 | 0 | 0 | 0 |
| Factorial: `json_off_retry_off` | 45 | **15** | 7 | 3 | 0 | 5 | 0 |
| Baseline Prompt (Rules 8 & 9 omitted) | 45 | **20** | 15 | 4 | 0 | 1 | 0 |
| Post-Hoc (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`) | 45 | **5** | 1 | 4 | 0 | 0 | 0 |

### Diagnostic Analysis: Why `rag_q07` Shows `valid=False` with 0 Retries in Baseline Run
In `e3_prompt_baseline.jsonl`, item `rag_q07` records `tool_call_valid=False` with `retries=0`.
Inspection of the raw JSONL trace reveals the recorded answer:
`"Error during model communication: Ollama chat error (HTTP 500): {"error":"prediction aborted, token repeat limit reached"}"`.

**Technical Root Cause:**
1. During text generation, the local Ollama process aborted prediction due to hitting its internal repeat token limit.
2. In `backend/agent.py` (lines 465–479), the HTTP 500 raises an `OllamaError` at the transport layer before any completion string is returned.
3. The agent runner handles this exception by immediately terminating the run and writing the error string into `run.final_answer`.
4. Because the engine aborted before emitting any JSON agent action, `tool_call_valid` evaluated to `False`.
5. The agent retry mechanism (`MAX_FORMAT_RETRIES = 2`) is designed strictly for schema recovery when the model emits malformed JSON during ordinary completion. It is never triggered on engine crashes or HTTP transport errors.
Consequently, zero retries were attempted, resulting in `valid=False` and `retries=0`.

## Latency by Task Type Across Configurations
| Configuration | Total (n) | Overall Mean Latency | RAG Queries | Calculator Tasks | SQL Analytical Tasks | Document Assistant Tasks |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Canonical Run 1 (`json_on_retry_on`) | 45 | **27.86s** | 32.17s | 12.32s | 17.31s | 28.14s |
| Canonical Run 2 (`json_on_retry_on_rerun`) | 45 | **55.39s** | 71.71s | 10.3s | 14.37s | 43.53s |
| Canonical Pooled (`n=90`, Repeats=2) | 90 | **41.62s** | 51.94s | 11.31s | 15.84s | 35.84s |
| Factorial: `json_off_retry_on` | 45 | **23.53s** | 26.28s | 10.46s | 16.21s | 27.46s |
| Factorial: `json_off_retry_off` | 45 | **19.25s** | 20.81s | 10.46s | 10.59s | 27.33s |
| Baseline Prompt (Rules 8 & 9 omitted) | 45 | **16.17s** | 17.82s | 10.22s | 13.73s | 14.69s |
| Post-Hoc (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`) | 45 | **40.06s** | 45.79s | 16.44s | 24.02s | 45.33s |

> **Important Methodology Note on Latency Comparability:**
> Overall aggregate latency means across configurations are **not directly comparable** because abstentions end early. When an agent prematurely abstains without issuing a tool call (such as the 15 premature abstentions in `e3_prompt_baseline`, 6 in Canonical Run 1, and 7 in `json_off_retry_off`), it generates a short negative sentence on Turn 1 in ~10–12 seconds without performing vector searches or database queries. Conversely, configurations that successfully invoke tools perform multi-turn reasoning and retrieval loops lasting 25–70+ seconds. Aggregate mean latencies thus confound execution efficiency with failure-mode dropouts (a configuration with more early-exit failures appears misleadingly 'faster'). Meaningful latency evaluations must be compared per task type and conditioned on multi-turn tool execution.

## Post-Hoc Architectural Variant: REQUIRE_RETRIEVAL_BEFORE_ABSTAIN
*Evaluated as a post-hoc intervention forcing one retrieval before accepting Document Assistant abstentions.*
| Configuration | Status | n | First-Try Validity | 95% CI | Task Success (Strict) | 95% CI | Task Success (Adjudicated) | 95% CI | Mean Latency | Peak Ollama RSS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST-HOC: require_retrieval_before_abstain` | Completed | 45 | **100.0%** | [92.1%, 100.0%] | **88.9%** | [76.5%, 95.2%] | **91.1%** | [79.3%, 96.5%] | 40.06s* | 2335.4 MB |

### Post-Hoc Regressions and Validation Scope
- **Regressions (b=6 gained, c=2 lost):**
  1. `rag_q03`: In the canonical run, the recorded 'pass' was a scorer false positive (the answer contained the name 'Radhakrishnan' while stating the documents did not specify the officer). In post-hoc, the model reached the same negative conclusion without naming the officer, failing the keyword match.
  2. `rag_q21`: In post-hoc, the model relied on generic university priors ('Medical Absence Form', 'Academic Office') instead of conditioning strictly on retrieved text mentioning Form MED-401 and Clause 2.1.
- **Validation Scope:** Validation of this post-hoc intervention was strictly a unit test (`tests/test_require_retrieval_before_abstain.py`) plus the 45-item evaluation benchmark, not a broad multi-domain regression run.