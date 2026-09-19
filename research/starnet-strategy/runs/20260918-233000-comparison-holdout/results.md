# Comparison results

18 proxy-simulation holdout seeds: candidate638.6145 vs incumbent607.1704,
mean+31.4441;12wins,4ties,2losses; worst-40.5552 on132. All scores exceed natural.

Preregistered official sandbox subset126,127,134,135,142,143:
natural-375.9433, incumbent636.7650, candidate666.4450, mean+29.6800;
4wins,1tie,1loss. Worst-22.54 on135 (1804.12 ->1781.58). Candidate steps<=87,
LLM calls0; budgets0-1; no failures. ProxyMAE0.3322/max1.7318 over18states.
Raw traces and complete metrics: metadata.json and raw/remote.jsonl.

Both selection and proxy gates pass, but loss inspection finds incomplete
response-uncertainty handling: shield32 on135 had nominal future advantage0.544,
small relative to uncertainty about future communication. Reopen Explore for
robust communication-tail stress rather than treating model estimates as exact.
This inspected holdout is now development evidence for subsequent refinements;
new holdout144-161 reserved in next plan. Original ZIP still preserved.
