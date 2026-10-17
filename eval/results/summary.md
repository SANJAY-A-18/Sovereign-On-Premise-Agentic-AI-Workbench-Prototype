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
| 300 chars | 18 | 24 | **75.0%** | [55.1%, 88.0%] | **87.5%** | [69.0%, 95.7%] | **0.8056** | Multi-sentence clauses split across boundaries |
| 500 chars | 18 | 24 | **75.0%** | [55.1%, 88.0%] | **91.7%** | [74.2%, 97.7%] | **0.8333** | Multi-sentence clauses split across boundaries |
| 800 chars | 18 | 24 | **83.3%** | [64.1%, 93.3%] | **95.8%** | [79.8%, 99.3%] | **0.8889** | Chunk 800 achieves highest chunk-level recall and MRR |

## Experiment 2: Reliability Factorial (JSON Mode x Retry)
| Configuration | Status | n | First-Try Validity | 95% CI | Task Success | 95% CI | Mean Latency |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `json_on_retry_on` | Completed | 45 | **100.0%** | [92.1%, 100.0%] | **80.0%** | [66.2%, 89.1%] | 27.86s |
| `json_on_retry_off` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A |
| `json_off_retry_on` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A |
| `json_off_retry_off` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A |

## Experiment 3: Prompt Variant (Baseline vs Hardened)
| Variant | Status | n | First-Try Validity | 95% CI | Task Success | 95% CI |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Hardened (Rules 8 & 9) | Completed | 45 | **100.0%** | [92.1%, 100.0%] | **80.0%** | [66.2%, 89.1%] |
| Baseline (Rules 8 & 9 omitted) | *not run* | 0 | N/A | N/A | N/A | N/A |

## Post-Hoc Architectural Variant: REQUIRE_RETRIEVAL_BEFORE_ABSTAIN
*Evaluated as a post-hoc intervention forcing one retrieval before accepting Document Assistant abstentions.*
| Configuration | Status | n | First-Try Validity | 95% CI | Task Success | 95% CI | Mean Latency |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST-HOC: require_retrieval_before_abstain` | Completed | 45 | **100.0%** | [92.1%, 100.0%] | **88.9%** | [76.5%, 95.2%] | 40.06s |

### Paired McNemar Test: Pre-registered Canonical vs Post-Hoc Variant
**Paired McNemar Test:** `Pre-registered Canonical (json_on_retry_on)` vs `Post-Hoc (require_retrieval_before_abstain)` (n = 45 common runs)
- Concordant: Both Pass = 34, Both Fail = 3
- Discordant: (Pre-registered Canonical (json_on_retry_on) Fail, Post-Hoc (require_retrieval_before_abstain) Pass) = 6 | (Pre-registered Canonical (json_on_retry_on) Pass, Post-Hoc (require_retrieval_before_abstain) Fail) = 2
- Discordant total: 8
- Exact Two-Sided McNemar p-value: **0.28906**
> *Note on Sample Size:* Discordant pair count (b + c = 8) is too small (< 10) to draw statistically definitive conclusions.

## Failure Analysis Breakdown (Canonical Pre-registered Run)
Total failed items: **9 / 45** (Task Success Rate: **80.0%**)

| Item ID | Suite | Question | Expected Keyword / Ground Truth | Model Answer | Failure Cause |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `rag_q08` | rag | How many hours of supervised library study remediation are m... | `['18', 'hours']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q13` | rag | What is the minimum passing percentage required specifically... | `['42', 'percent']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q14` | rag | What is the registration fee per theoretical credit for sitt... | `['1,150', '1150']` | I do not know.... | **Premature Abstention Without Tool Call** |
| `rag_q19` | rag | What is the daily overdue fine rate per volume starting from... | `['40']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q20` | rag | What is the daily session cap in minutes for users on Cyber ... | `['90', 'minutes']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q22` | rag | A student arrived late for their exam. At what point is hall... | `['20', '45']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q23` | rag | Can undergraduate students take out rare manuscripts from Wi... | `['cannot', 'CLRC-SEC-9']` | Undergraduate students are not allowed to take out rare manuscripts fr... | **Wrong Answer After Retrieval** |
| `rag_q27` | rag | What is the passing score percentage required for foreign la... | `['do not know', 'not mentioned', 'no information', 'does not contain', 'cannot find', 'not provided']` | According to the regulations provided in the documents, the passing sc... | **Wrong Answer After Retrieval** |
| `agent_doc_03` | agent | Under the library charter, what is the infraction penalty fe... | `['3,200', '3200']` | The provided documents do not contain this information.... | **Wrong Answer After Retrieval** |