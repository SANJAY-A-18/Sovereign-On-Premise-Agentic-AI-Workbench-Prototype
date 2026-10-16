# Benchmark Results Summary
*Generated on results at report.py*

## Experiment 1: RAG Chunk Size vs Retrieval Hit@3
| Chunk Size | Total Queries (n) | Retrieval Hit@3 | 95% Wilson CI | Finding |
| :--- | :--- | :--- | :--- | :--- |
| 300 chars | 30 | **100.0%** | [88.6%, 100.0%] | Retrieval hit rate is uniform across tested chunk sizes |
| 500 chars | 30 | **100.0%** | [88.6%, 100.0%] | Retrieval hit rate is uniform across tested chunk sizes |
| 800 chars | 30 | **100.0%** | [88.6%, 100.0%] | Retrieval hit rate is uniform across tested chunk sizes |

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

## Paired Hypothesis Tests (McNemar Exact)
*Paired McNemar test requires at least two paired runs over identical items.*