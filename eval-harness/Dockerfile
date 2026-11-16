# Build on the existing managed-agentcore image to preserve analysis invocations.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG CODE_REVISION=unknown
ENV EVAL_CODE_REVISION=${CODE_REVISION}
COPY --chown=1000:1000 runtime.py /app/eval-harness/runtime.py
COPY --chown=1000:1000 graders/rules.py /app/eval-harness/graders/rules.py
COPY --chown=1000:1000 graders/factcheck.py /app/eval-harness/graders/factcheck.py
COPY --chown=1000:1000 graders/judge.py /app/eval-harness/graders/judge.py
COPY --chown=1000:1000 pairwise.py /app/eval-harness/pairwise.py

CMD ["opentelemetry-instrument", "python", "/app/eval-harness/runtime.py"]
