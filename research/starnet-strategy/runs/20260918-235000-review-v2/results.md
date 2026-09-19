# Review outcome (2026-09-19)

Local gate PASS; official950 gate PENDING. V2 ZIP SHA256
38f37e009a82589486a16abd3b71635e68fd8edc98101adfc99deb6d0bdf6206.
Original ZIP e643b367... unchanged. Full details in report-v2.md and JSON sidecars.

Paired realCaseVO0.3.19/Python3.12.3/gpt-5.6-luna runs, official custom sandbox:
-120: -37.19→243.98;19→22LLM calls;88→78steps.
-124: -26.03→88.67;20→33calls;87→78steps.
-134:2061.44→2061.44;19→19calls;88→88steps.
Mean666.0733→798.0300,+19.8111%;2wins/1tie. Natural mean-141.8833.
Every confirmed action matches an LLM-approved plan; budget sums and limits pass.

Production-policy controls: negative effects50nodes -452.59→-16.20; zero effects
50nodes -114.21→251.37. Both stop communication after3probes,67steps,1budget.
100node control -1211.67→462.80,154steps; prediction error9.3759 score units.

Actual V2 ZIP100node case:461.36,153steps,65calls,1budget,539.98s,149384KiB RSS.
Actual V2 ZIP3node zero-effects case:85.71→100.00,8steps,5calls,9.5budget; LLM
chooses cut(1,2),success returned and both local neighbor lists updated.

40Python3.9 tests pass. Archive byte comparison, allowlist, syntax/publicAPI AST,
source hashes and credential scan pass. No SDK/externalcasevo changes.
Initial oldZIP120 ReadTimeout attempt is excluded, with score/audit/trace retained.
Local read-only budget requests may retry once; mutations never retry.

Risks: no officialGLM/hiddenV2 score; three realLLM paired seeds are limited;
100node real run uses about9minutes of the10minute local limit. Empirical graph
and response predictions are not exact. Next: user uploads concrete V2, returns
official score/logs; reopen Explore if below950. Do not infer official success.

Authorized platform handoff email accepted by Gmail with SENT, message ID
1a0b551d2be5d293. Initial sandbox token access failed; existing host keyring worked.
No evidence yet of recipient reading, platform upload, or a new official score.
