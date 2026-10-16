"""One module per agent a component run measures; component_eval.py runs them.

Every module has the same interface:
    LATER_OUTPUTS                      artifacts the agent and every agent after it write (removed before staging)
    prepare(adir, scenario)            once per source run -> ctx
    plant(ctx, adir, staged, k, rng)   -> (record for planted.json, state, one-line summary)
    evaluate(adir, ctx, state)         -> what goes in result.json
    summary(result), table(results)
"""
from . import reporter, validator

COMPONENTS = {"validator": validator, "reporter": reporter}
