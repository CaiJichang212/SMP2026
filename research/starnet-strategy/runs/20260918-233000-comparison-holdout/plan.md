# Frozen comparison and holdout plan

Development: indices120-125, all six topologies, 50 nodes / budget100.
Screen alternative low-degree calibration on development only. Then freeze the
chosen topology policy and compare indices126-143 in the proxy simulator.
Remote holdout chosen BEFORE observing results: 126,127,134,135,142,143 (one
per topology, covering three new weight/persona regimes and effect permutations).
Compare natural, incumbent heuristic, chosen candidate under identical seed JSON.
The heuristic control is not a faithful replay of original LLM behavior.

Proxy gate: on remote holdout natural and post-action states, mean absolute error
<=5 score units, maximum <=20; report relative errors with near-zero denominator
floor50. Above gate, restrict candidate scope or reopen model calibration.
Selection gate: positive paired mean vs incumbent, at least four of six wins,
natural mean exceeded; report any individual losses. No threshold tuning after
seeing holdout; additional tuning requires fresh held-out indices.

Final real-LLM paired gate: old ZIP and candidate ZIP on fixed seeds120,124,134,
same local model, each n50 budget100. Development cases120/124 test translation
to LLM decisions;134 is held out from development. Cannot infer official950
from any of these. Also n100 smoke and all-negative prompt safety control.
Every heavy run serialized, each limited to600s, single CPU,2500MiB address space.
