"""Shared by the component modules: what the Reporter and the Auditor write, staging, numbers."""
import shutil

# Written by the Reporter and the Auditor: removed before staging any component
# that runs before them, so it starts where it would in a full run.
REPORTER_AND_AUDITOR = ["final_report*", "report*.docx", "audit_*", "code/reporter_*", "code/svg_docx.py",
                        "code/audit_*", "cache/audit_*"]


class NothingToPlant(Exception):
    """The source run has nothing this component can plant in."""


def copy_before(src, dest, later_outputs):
    """Copy a saved run's artifacts without what the component and the agents after it wrote."""
    shutil.copytree(src, dest, symlinks=False)
    for pattern in later_outputs:
        for p in dest.glob(pattern):
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
