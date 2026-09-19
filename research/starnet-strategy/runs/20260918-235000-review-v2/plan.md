# Review: actual ZIP / CaseVO / real LLM

Compare untouched old ZIP (e643b367...) against V2 (38f37e00...) on120/124/134,
same gpt-5.6-luna provider, realCaseVO0.3.19/Python3.12, official sandbox custom
seeds, budget100, max120. Local Python3.9 unit/ZIP checks separately.
Every child has singleCPU,2500MiB virtual limit,600s deadline. Log all LLM calls,
steps,budget,HTTP,score,natural,usage,RSS,time,hashes and stopreason.

Initial old-ZIP120 attempt aborted at step10 with ReadTimeout,9 completed scans,
no intervention,95.5budget. Exclude from strategy averages; raw logs preserved.
Diagnostic improvement limited to local test transport: log failing endpoint and
allow one retry of read-only get_budget. Never retry scan/comm/cut/shield/evaluate
or reuse an uncertain session. New paired runs under raw/pairs/ start fresh.

36 Python3.9 tests pass; newZIP allowlist/AST/syntax/secret checks pass. Existing
oldZIP hash verified unchanged. Extra boundary runs follow paired verification.

Boundary extension: final TopologyBook (noLLM controls) on50-node negative144,
zero145,and100-node151; actualZIP/realLLM on100-node151 and three-node zero-prompt
path[100,0,0] to exercise cut authorization without forcing a choice. Variants
are not pooled into main50-node paired means. Original reserved144-161 standard
holdout was not selected on; viewed variants count as exposure for future work.
