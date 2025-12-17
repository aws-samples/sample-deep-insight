"""
Data Structure Checker

A comprehensive skill for automatically detecting and fixing common data file issues.
Provides a zero-intervention experience - users can input any messy file and get a
clean DataFrame ready for analysis.

Auto-fixes:
- Multi-level/hierarchical headers
- Encoding issues (utf-8, cp949, euc-kr, etc.)
- Empty rows/columns
- Data type inference
- Duplicate column names
- Unicode path issues (Korean/CJK filenames)

Example:
    from skills.data_structure_checker.checker import smart_read

    # Simple usage - handles everything automatically
    df = smart_read('messy_data.xlsx')

    # With report of what was fixed
    df, report = smart_read('messy_data.xlsx', return_report=True)
"""

from __future__ import annotations

import os
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

# Import from the existing reader module
# Handle both relative and absolute imports
try:
    from .reader import (
        MultiLevelReader,
        _resolve_unicode_path,
        read_multi_level,
        analyze_headers,
    )
except ImportError:
    from reader import (
        MultiLevelReader,
        _resolve_unicode_path,
        read_multi_level,
        analyze_headers,
    )


# Common encodings to try for Korean/Asian text
ENCODINGS_TO_TRY = [
    'utf-8',
    'utf-8-sig',  # UTF-8 with BOM
    'cp949',      # Korean Windows
    'euc-kr',     # Korean legacy
    'utf-16',
    'utf-16-le',
    'utf-16-be',
    'gbk',        # Chinese simplified
    'gb2312',
    'big5',       # Chinese traditional
    'shift_jis',  # Japanese
    'euc-jp',
    'iso-8859-1', # Latin-1
]


class DataStructureChecker:
    """
    Comprehensive data structure checker that auto-fixes common issues.
    """

    def __init__(
        self,
        separator: str = '_',
        max_header_rows: int = 5,
        trim_empty: bool = True,
        infer_types: bool = True,
        handle_duplicates: bool = True,
    ):
        """
        Initialize the DataStructureChecker.

        Args:
            separator: Character(s) for joining multi-level headers.
            max_header_rows: Max rows to check for headers.
            trim_empty: Whether to remove empty rows/columns.
            infer_types: Whether to infer and convert data types.
            handle_duplicates: Whether to rename duplicate columns.
        """
        self.separator = separator
        self.max_header_rows = max_header_rows
        self.trim_empty = trim_empty
        self.infer_types = infer_types
        self.handle_duplicates = handle_duplicates
        self._report: dict[str, Any] = {}

    def smart_read(
        self,
        file_path: str | Path,
        sheet_name: str | int = 0,
        return_report: bool = False,
        **kwargs: Any,
    ) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, Any]]:
        """
        Read a file with automatic issue detection and fixing.

        Args:
            file_path: Path to the file.
            sheet_name: Sheet name/index for Excel files.
            return_report: If True, return (DataFrame, report) tuple.
            **kwargs: Additional arguments for pandas reader.

        Returns:
            DataFrame, or (DataFrame, report) if return_report=True.
        """
        self._report = {
            'file_path': str(file_path),
            'timestamp': datetime.now().isoformat(),
            'issues_detected': [],
            'fixes_applied': [],
            'original_shape': None,
            'final_shape': None,
            'encoding_used': None,
            'header_rows': None,
            'columns_renamed': [],
            'empty_rows_removed': 0,
            'empty_cols_removed': 0,
            'type_conversions': {},
        }

        # Step 1: Resolve Unicode path
        file_path = _resolve_unicode_path(file_path)
        if str(file_path) != self._report['file_path']:
            self._report['issues_detected'].append('unicode_path')
            self._report['fixes_applied'].append('Resolved Unicode path normalization')

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.suffix.lower()

        # Step 2: Detect encoding (for CSV/TSV)
        if ext in ['.csv', '.tsv']:
            encoding = self._detect_encoding(file_path)
            self._report['encoding_used'] = encoding
            kwargs['encoding'] = encoding

        # Step 3: Read with multi-level header handling
        reader = MultiLevelReader(
            separator=self.separator,
            max_header_rows=self.max_header_rows,
        )
        df = reader.read(file_path, sheet_name=sheet_name, **kwargs)

        # Get header info
        header_info = reader.get_header_info(file_path, sheet_name)
        self._report['header_rows'] = header_info.get('detected_header_rows', [0])
        self._report['original_shape'] = (
            header_info.get('total_rows', 0),
            header_info.get('total_columns', 0)
        )

        if len(self._report['header_rows']) > 1:
            self._report['issues_detected'].append('multi_level_headers')
            self._report['fixes_applied'].append(
                f"Flattened {len(self._report['header_rows'])}-level headers with '{self.separator}' separator"
            )

        # Step 4: Trim empty rows/columns
        if self.trim_empty:
            df = self._trim_empty(df)

        # Step 5: Handle duplicate columns
        if self.handle_duplicates:
            df = self._handle_duplicate_columns(df)

        # Step 6: Infer and convert types
        if self.infer_types:
            df = self._infer_types(df)

        self._report['final_shape'] = df.shape

        if return_report:
            return df, self._report
        return df

    def _detect_encoding(self, file_path: Path) -> str:
        """
        Auto-detect file encoding by trying multiple encodings.
        """
        # Try to read first few KB to detect encoding
        sample_size = 8192

        for encoding in ENCODINGS_TO_TRY:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read(sample_size)
                return encoding
            except (UnicodeDecodeError, UnicodeError):
                continue

        # Fallback to utf-8 with error handling
        self._report['issues_detected'].append('encoding_detection_failed')
        self._report['fixes_applied'].append('Using utf-8 with error replacement')
        return 'utf-8'

    def _trim_empty(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove completely empty rows and columns.
        """
        original_shape = df.shape

        # Remove rows where all values are NaN
        df = df.dropna(how='all')
        rows_removed = original_shape[0] - df.shape[0]

        # Remove columns where all values are NaN
        df = df.dropna(axis=1, how='all')
        cols_removed = original_shape[1] - df.shape[1]

        if rows_removed > 0 or cols_removed > 0:
            self._report['issues_detected'].append('empty_rows_or_columns')
            self._report['fixes_applied'].append(
                f"Removed {rows_removed} empty rows and {cols_removed} empty columns"
            )
            self._report['empty_rows_removed'] = rows_removed
            self._report['empty_cols_removed'] = cols_removed

        return df

    def _handle_duplicate_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Rename duplicate column names by adding suffixes.
        """
        cols = df.columns.tolist()
        seen = {}
        new_cols = []
        renamed = []

        for col in cols:
            if col in seen:
                seen[col] += 1
                new_name = f"{col}_{seen[col]}"
                new_cols.append(new_name)
                renamed.append((col, new_name))
            else:
                seen[col] = 0
                new_cols.append(col)

        if renamed:
            df.columns = new_cols
            self._report['issues_detected'].append('duplicate_columns')
            self._report['fixes_applied'].append(
                f"Renamed {len(renamed)} duplicate columns"
            )
            self._report['columns_renamed'] = renamed

        return df

    def _infer_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Infer and convert data types for each column.
        """
        conversions = {}

        for col in df.columns:
            original_dtype = str(df[col].dtype)

            # Skip if already numeric or datetime
            if df[col].dtype in ['int64', 'float64', 'datetime64[ns]']:
                continue

            # Try numeric conversion
            if df[col].dtype == 'object':
                # Try to convert to numeric
                numeric_col = pd.to_numeric(df[col], errors='coerce')
                non_null_original = df[col].notna().sum()
                non_null_numeric = numeric_col.notna().sum()

                # If most values convert successfully (>80%), use numeric
                if non_null_original > 0 and (non_null_numeric / non_null_original) > 0.8:
                    df[col] = numeric_col
                    conversions[col] = f"{original_dtype} -> {df[col].dtype}"
                    continue

                # Try datetime conversion for date-like strings
                if self._looks_like_date(df[col]):
                    try:
                        df[col] = pd.to_datetime(df[col], errors='coerce')
                        if df[col].notna().sum() > 0:
                            conversions[col] = f"{original_dtype} -> datetime64"
                    except Exception:
                        pass

        if conversions:
            self._report['issues_detected'].append('type_inference')
            self._report['fixes_applied'].append(
                f"Converted data types for {len(conversions)} columns"
            )
            self._report['type_conversions'] = conversions

        return df

    def _looks_like_date(self, series: pd.Series) -> bool:
        """
        Check if a series contains date-like strings.
        """
        sample = series.dropna().head(10)
        if len(sample) == 0:
            return False

        date_patterns = [
            r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',  # 2024-01-15 or 2024/01/15
            r'\d{1,2}[-/]\d{1,2}[-/]\d{4}',  # 15-01-2024 or 15/01/2024
            r'\d{4}\.\d{1,2}\.\d{1,2}',      # 2024.01.15
        ]

        import re
        for val in sample:
            if isinstance(val, str):
                for pattern in date_patterns:
                    if re.match(pattern, val.strip()):
                        return True
        return False

    def diagnose(
        self,
        file_path: str | Path,
        sheet_name: str | int = 0,
    ) -> dict[str, Any]:
        """
        Diagnose a file without reading full data.
        Returns detected issues and recommendations.
        """
        file_path = _resolve_unicode_path(file_path)
        ext = file_path.suffix.lower()

        diagnosis = {
            'file_path': str(file_path),
            'file_exists': file_path.exists(),
            'file_extension': ext,
            'issues': [],
            'recommendations': [],
        }

        if not file_path.exists():
            diagnosis['issues'].append('file_not_found')
            return diagnosis

        # Check encoding for CSV
        if ext in ['.csv', '.tsv']:
            encoding = self._detect_encoding(file_path)
            if encoding != 'utf-8':
                diagnosis['issues'].append(f'non_utf8_encoding:{encoding}')
                diagnosis['recommendations'].append(
                    f"File uses {encoding} encoding, will auto-convert"
                )

        # Check headers
        reader = MultiLevelReader(separator=self.separator)
        header_info = reader.get_header_info(file_path, sheet_name)

        if header_info.get('header_count', 1) > 1:
            diagnosis['issues'].append('multi_level_headers')
            diagnosis['recommendations'].append(
                f"Detected {header_info['header_count']}-level headers, will flatten"
            )

        diagnosis['header_info'] = header_info

        return diagnosis


def smart_read(
    file_path: str | Path,
    separator: str = '_',
    return_report: bool = False,
    sheet_name: str | int = 0,
    **kwargs: Any,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, Any]]:
    """
    Read a file with automatic issue detection and fixing.

    This is the main entry point for the data-structure-checker skill.
    It handles all common data file issues automatically:
    - Multi-level headers → flattened
    - Encoding issues → auto-detected
    - Empty rows/columns → trimmed
    - Data types → inferred
    - Duplicate columns → renamed
    - Unicode paths → resolved

    Args:
        file_path: Path to the file to read.
        separator: Character(s) for joining multi-level headers (default: '_').
        return_report: If True, return (DataFrame, report) tuple.
        sheet_name: Sheet name/index for Excel files.
        **kwargs: Additional arguments for pandas reader.

    Returns:
        DataFrame ready for analysis, or (DataFrame, report) if return_report=True.

    Example:
        >>> df = smart_read('data.xlsx')
        >>> df, report = smart_read('data.xlsx', return_report=True)
        >>> print(report['fixes_applied'])
    """
    checker = DataStructureChecker(separator=separator)
    return checker.smart_read(
        file_path,
        sheet_name=sheet_name,
        return_report=return_report,
        **kwargs,
    )


def diagnose(
    file_path: str | Path,
    sheet_name: str | int = 0,
) -> dict[str, Any]:
    """
    Diagnose a file's structure without reading full data.

    Args:
        file_path: Path to the file.
        sheet_name: Sheet name/index for Excel files.

    Returns:
        Dictionary with detected issues and recommendations.
    """
    checker = DataStructureChecker()
    return checker.diagnose(file_path, sheet_name)


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python checker.py <file_path> [--diagnose]")
        sys.exit(1)

    file_path = sys.argv[1]

    if '--diagnose' in sys.argv:
        result = diagnose(file_path)
        print("Diagnosis:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    else:
        df, report = smart_read(file_path, return_report=True)
        print(f"Shape: {df.shape}")
        print(f"\nFixes Applied:")
        for fix in report['fixes_applied']:
            print(f"  - {fix}")
        print(f"\nColumns ({len(df.columns)}):")
        for col in df.columns[:10]:
            print(f"  - {col}")
        if len(df.columns) > 10:
            print(f"  ... and {len(df.columns) - 10} more")
