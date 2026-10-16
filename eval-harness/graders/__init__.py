"""Rule-based graders for a single Deep Insight run folder.

Each grader takes the run's artifacts directory and returns a flat dict of
metrics (numbers or booleans) plus a `details` list for humans. Graders never
raise on a missing or malformed artifact: they report it as a metric instead,
so a broken run still produces a comparable score row.
"""
