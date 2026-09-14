# P11 prompt-learning entry validation

The research checker assembled the canonical single-file entry and changed
only the three P11 qualification metadata constants in the imported temporary
module. It did not replace the qualification function or controller. All
reports identify `unreleased_candidate_assembly=true` and
`final_zip_execution=false`; final ZIP evidence must run without metadata
injection.

The test case is the consumed `er_balanced` graph with prompt corrections
`[-5,15,10]`. Prompt values are supplied only to the environment. The policy
receives public scan and communication returns.

## Clean real target run

The real injected LLM and public custom-seed sandbox completed with:

- selected prompt ID 2 after probes `1,2,3` on one node;
- probe budget 6 and 32 later prompt-2 dispatches;
- 86/86 accepted model choices, zero fallback and zero transport errors;
- zero action, P8 planning, P11 planning, and P11 runtime errors;
- one action per host step and public response error 0;
- public score `746.76`, local replay `746.7619440524936`.

Report: `p11-research-entry-real-remote-clean-er-prompt2-20260914.json`,
SHA-256 `e01cd49c74bbfa7a36da06ba94aab44de2409074b3ce95fac5234814f56a4182`.

An earlier real run completed the same actions and score but had one model
transport error, one deterministic fallback, and 85 accepted choices. It is
retained as fallback evidence and is not used as the clean release-seal run:
`p11-research-entry-real-remote-er-prompt2-20260914.json`, SHA-256
`3992ca57307eb653897cd1da5da12eea67075dafb53d32be05e5a1b3417d0f90`.

## Python compatibility

The same valid mock ranker and seed produced exactly
`746.7619440524936` and action SHA-256
`1aae7c69c5bffa93a6eabe19d1c08b42e23db705d623a93e56be71db83e65fbb`
under both Python 3.9.25 / NetworkX 3.1 / real local CaseVO and the modern
Python 3.12.3 / NetworkX 3.6.1 environment. Both used model SHA-256
`1dff3faf3057a199e1b68f526380e57dfc65a1a5e185a8320fa344eca8c99e97`,
selected prompt 2, spent 6 probe budget, dispatched prompt 2 32 times, and had
zero action or planning errors. The commander config's P11 field was removed
before construction in both runs, proving activation uses compiled
qualification metadata rather than preservation of an optional host field.

Reports:

- `p11-research-entry-python39-clean-er-prompt2-20260914.json`, SHA-256
  `61f6d173a54d2cf5f4bcce0a0cdc81661ebe206451fb004a3d63761c2439f57c`
- `p11-research-entry-modern-clean-er-prompt2-20260914.json`, SHA-256
  `a038ee9ab75b4a09fbdff7e1d5e3d6bcd7ccddd3a27fb0aac000e1773763d1fe`

## LLM failure path

With the LLM unavailable, all 86 model choices used deterministic fallback.
The runtime still executed the legal `1,2,3` probe sequence, selected prompt 2,
and dispatched it 32 times, producing the same action hash and exact local
score with zero runtime/action/planning errors. Invalid model output therefore
does not permanently disable learning or turn P11 into behavior identical to
fixed prompt 1.

Report: `p11-research-entry-unavailable-clean-er-prompt2-20260914.json`,
SHA-256 `76e3c26491e43fffc3da55431767ca975c4ec0555e215b8d4a176e70a8f30916`.

The research checker SHA-256 was
`15a768df3b57a7593acb4b1f04781756e07a8f402c2560a5c86a4bc7efb1181b`.
The frozen P11 runtime SHA-256 was
`98ae3471bd5eb9d024bd96ac678f19a6807877cccb45df53622b70a614880612`.
