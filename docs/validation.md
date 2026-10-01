# Validation

Verified on October 1, 2026 with Python 3.14.3. The implementation supports Python 3.11+.

## Automated checks

- `make test`: 130 passing synthetic unit tests; no live API calls.
- `make baseline`: valid structured output for all 50 supplied submissions.
- `make evals-local`: uses the supplied evaluator's schema, exact decision, and exact issue-category-set metrics with equal weights.
- `make score`: 100.0% local aggregate score; all three metrics passed for all 50 cases.
- `make determinism`: 100% decision stability, JSON validity, and exact output match across ten runs of the supplied default record.
- Additional replay: all 50 submissions repeated three times, with identical complete serialized output, unchanged inputs, and zero semantic requests.
- `make report`: the supplied terminal viewer opened the generated local report and exited normally.
- Isolated Python lint/format checks passed. The supplied runners, viewer, and dataset were preserved.

The sample submissions resolve deterministically, so the score and replay checks involve no model inference. Labels are consulted only by the evaluator. Production code contains no sample IDs, names, fixed dates, or expected labels. Generated reports and outputs remain gitignored.

## Live API limitations

No `OPENAI_API_KEY` was available in the implementation environment. The untouched starter was attempted first; its API requests failed for missing credentials, so it provides no meaningful quality comparison. Initial attempt logs and replay output were retained outside the repository under `/tmp/preop-initial`.

Real semantic-model inference could not be verified without credentials. The original hosted `make evals` invocation was blocked by automatic approval review because it can export patient submissions to the OpenAI Evals service without specific authorization for that transfer. Local scoring completed using the supplied harness instead. No hosted upload occurred.

Responses API schema handling, primary/fallback routing, exact quote validation, incomplete results, and API failures are tested with offline mocks. Hosted scoring requires credentials and explicit authorization for the upload. Ambiguous semantic fixtures also need live-model evaluation before claiming model-backed accuracy or repeatability.

## Regression method

Failures were reduced to general synthetic behaviors: a medication list mistaken for a newer management plan, an unlabelled mmHg recheck in an addendum, and a specialist consultation shortlisted as an H&P without examination evidence. Fixes apply to document meaning and measurement resolution, with no case-specific branches. The final integration evaluation checks the whole dataset for regressions.
