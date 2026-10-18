
import json, os
import numpy as np
from datetime import datetime

_calculations = []

def to_python_type(value):
    """Convert numpy/pandas types to Python native types for JSON serialization"""
    if isinstance(value, (np.integer, np.int64)): return int(value)
    elif isinstance(value, (np.floating, np.float64)): return float(value)
    elif isinstance(value, np.ndarray): return value.tolist()
    return value

def track_calculation(calc_id, value, description, formula, source_file="", source_columns=None, importance="medium"):
    _calculations.append({"id": calc_id, "value": to_python_type(value), "description": description,
        "formula": formula, "source_file": source_file,
        "source_columns": source_columns or [], "importance": importance})

def save_calculation_metadata(path="./artifacts/calculation_metadata.json"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                for c in json.load(f).get("calculations", []):
                    existing[c["id"]] = c
        except Exception:
            existing = {}
    for c in _calculations:
        existing[c["id"]] = c
    merged = list(existing.values())
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "calculations": merged}, f, indent=2, ensure_ascii=False)
    print(f"📊 Saved: {path} ({len(merged)} total, +{len(_calculations)} this step)")
