---
name: data-structure-checker
description: This skill should be used when reading any tabular data file (Excel, CSV, Parquet, ODS). It automatically detects and fixes common data issues including multi-level headers, encoding problems, empty rows/columns, and data type mismatches. Returns a clean DataFrame ready for analysis with zero user intervention.
---

# Data Structure Checker

## Overview

A comprehensive skill for automatically detecting and fixing common data file issues. Input any messy file and receive a clean DataFrame ready for analysis - zero intervention required.

**Auto-fixes**:
- Multi-level/hierarchical headers (flattens with separator)
- Encoding issues (utf-8, cp949, euc-kr, etc.)
- Empty rows and columns
- Data type inference and conversion
- Duplicate column names
- Unicode path issues (Korean/CJK filenames)

## When to Use

This skill should be triggered when:
- Reading any Excel files (.xlsx, .xls)
- Reading any CSV/TSV files
- Reading ODS files (OpenDocument)
- Reading Parquet files
- Encountering "Unnamed:" columns in data
- Dealing with multi-level or hierarchical headers
- Processing Korean/Asian language data files

## Usage

### Reading Data Files

To read any tabular data file with automatic issue detection and fixing, execute the `scripts/checker.py` script:

```python
import sys
sys.path.insert(0, 'skills/data-structure-checker/scripts')
from checker import smart_read

# Read file - handles all issues automatically
df = smart_read('data.xlsx')

# Read with report of fixes applied
df, report = smart_read('data.xlsx', return_report=True)
```

### Diagnosing Files

To analyze a file's structure without reading full data:

```python
from checker import diagnose

result = diagnose('data.xlsx')
# Returns: {'issues': ['multi_level_headers'], 'recommendations': [...]}
```

### Command Line

```bash
# Read and display summary
uv run python skills/data-structure-checker/scripts/checker.py data.xlsx

# Diagnose without reading
uv run python skills/data-structure-checker/scripts/checker.py data.xlsx --diagnose
```

## API Reference

### `smart_read(file_path, separator='_', return_report=False, sheet_name=0)`

Main entry point for reading files with automatic issue resolution.

**Parameters**:
- `file_path`: Path to the file (handles Korean/Unicode filenames)
- `separator`: Character(s) for joining multi-level headers (default: `'_'`)
- `return_report`: If True, return `(DataFrame, report)` tuple
- `sheet_name`: Sheet name or index for Excel files

**Returns**:
- `DataFrame` - Clean data ready for analysis
- Or `(DataFrame, report)` if `return_report=True`

### `diagnose(file_path, sheet_name=0)`

Analyze file structure without reading full data.

**Returns**: Dictionary with detected issues and recommendations.

## Report Structure

When `return_report=True`, the report contains:

```python
{
    'file_path': 'data/file.xlsx',
    'timestamp': '2024-12-17T10:30:00',
    'issues_detected': ['multi_level_headers', 'empty_rows_or_columns'],
    'fixes_applied': [
        'Flattened 3-level headers with "_" separator',
        'Removed 2 empty rows and 0 empty columns'
    ],
    'original_shape': (52, 111),
    'final_shape': (49, 111),
    'header_rows': [0, 1, 2],
    'type_conversions': {'score': 'object -> float64'}
}
```

## Issues Handled

### Multi-Level Headers

Detects and flattens hierarchical headers:

**Before**: `응시자 정보 | Unnamed: 1 | Unnamed: 2`

**After**: `응시자 정보_응시코드 | 응시자 정보_성명 | 응시자 정보_부서`

### Encoding Issues

Auto-detects encoding for CSV files:
- UTF-8 (with/without BOM)
- CP949 (Korean Windows)
- EUC-KR (Korean legacy)
- GBK/GB2312 (Chinese)
- Shift_JIS/EUC-JP (Japanese)

### Empty Rows/Columns

Removes rows and columns where all values are NaN.

### Data Type Inference

Converts string columns to appropriate types:
- Numeric strings → float64/int64
- Date strings → datetime64

### Duplicate Columns

Renames duplicates with suffixes: `['score', 'score', 'score']` → `['score', 'score_1', 'score_2']`

### Unicode Path Issues

Handles Korean/CJK filenames with different Unicode normalizations (NFC/NFD).

## Supported Formats

| Extension | Format | Notes |
|-----------|--------|-------|
| `.xlsx` | Excel | Modern Excel format |
| `.xls` | Excel | Legacy Excel format |
| `.csv` | CSV | Auto-detects encoding |
| `.tsv` | TSV | Tab-separated values |
| `.ods` | ODS | OpenDocument Spreadsheet |
| `.parquet` | Parquet | Columnar format |

## Dependencies

Ensure these packages are installed:

```bash
uv pip install openpyxl xlrd odfpy pyarrow
```

## Integration with Deep Insight

To integrate with the coder agent, replace standard pandas read:

```python
# Instead of:
import pandas as pd
df = pd.read_excel('data.xlsx')

# Use:
sys.path.insert(0, 'skills/data-structure-checker/scripts')
from checker import smart_read
df = smart_read('data.xlsx')
```

## Troubleshooting

### File not found with Korean filename
The skill handles Unicode normalization automatically. Verify the file path is correct.

### Unexpected column names
Check the report's `header_rows` field. To specify header rows explicitly:

```python
sys.path.insert(0, 'skills/data-structure-checker/scripts')
from reader import read_multi_level
df = read_multi_level('data.xlsx', header_rows=[0, 1])
```

### Preserve original types
To skip type inference, create `DataStructureChecker` with `infer_types=False`.
