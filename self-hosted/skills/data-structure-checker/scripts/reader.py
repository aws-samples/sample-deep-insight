"""
Multi-Level Header Reader

A utility module for reading tabular files with multi-level (hierarchical) headers.
Supports Excel (.xlsx, .xls), CSV, ODS, and Parquet formats.

The module detects multi-level headers automatically and flattens them using
a configurable separator (default: '_').

Example:
    # Original headers:
    #   Row 0: 응시자 정보 | NaN | NaN | 종합 | NaN
    #   Row 1: 응시코드 | 성명 | 부서 | 추천 | 등급

    # Flattened headers:
    #   응시자 정보_응시코드 | 응시자 정보_성명 | 응시자 정보_부서 | 종합_추천 | 종합_등급
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

import pandas as pd


def _resolve_unicode_path(file_path: str | Path) -> Path:
    """
    Resolve file path handling Unicode normalization differences.

    Some filesystems (especially on macOS) use NFD normalization for filenames,
    while Python strings typically use NFC. This function tries both forms
    to find the actual file.
    """
    file_path = Path(file_path)

    # Try original path first
    if file_path.exists():
        return file_path

    # Try with different Unicode normalizations
    path_str = str(file_path)

    # Try NFC normalization
    nfc_path = Path(unicodedata.normalize('NFC', path_str))
    if nfc_path.exists():
        return nfc_path

    # Try NFD normalization
    nfd_path = Path(unicodedata.normalize('NFD', path_str))
    if nfd_path.exists():
        return nfd_path

    # If parent exists, try to find matching file in parent directory
    parent = file_path.parent
    if parent.exists():
        target_name = file_path.name
        target_nfc = unicodedata.normalize('NFC', target_name)
        target_nfd = unicodedata.normalize('NFD', target_name)

        for actual_file in parent.iterdir():
            actual_name = actual_file.name
            if actual_name == target_name:
                return actual_file
            if unicodedata.normalize('NFC', actual_name) == target_nfc:
                return actual_file
            if unicodedata.normalize('NFD', actual_name) == target_nfd:
                return actual_file

    # Return original path (will fail with FileNotFoundError later)
    return file_path


class MultiLevelReader:
    """Reader for tabular files with multi-level headers."""

    SUPPORTED_FORMATS = {
        '.xlsx': 'excel',
        '.xls': 'excel',
        '.csv': 'csv',
        '.tsv': 'csv',
        '.ods': 'ods',
        '.parquet': 'parquet',
        '.pq': 'parquet',
    }

    def __init__(
        self,
        separator: str = '_',
        max_header_rows: int = 5,
        encoding: str = 'utf-8',
    ):
        """
        Initialize the MultiLevelReader.

        Args:
            separator: Character(s) used to join multi-level header names.
            max_header_rows: Maximum number of rows to consider as potential headers.
            encoding: Default encoding for CSV files.
        """
        self.separator = separator
        self.max_header_rows = max_header_rows
        self.encoding = encoding

    def read(
        self,
        file_path: str | Path,
        header_rows: int | list[int] | Literal['auto'] = 'auto',
        sheet_name: str | int = 0,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """
        Read a file with multi-level headers and return a DataFrame with flattened columns.

        Args:
            file_path: Path to the file to read.
            header_rows: Number of header rows, list of row indices, or 'auto' for detection.
            sheet_name: Sheet name or index for Excel/ODS files.
            **kwargs: Additional arguments passed to the underlying pandas reader.

        Returns:
            DataFrame with flattened column names.

        Raises:
            ValueError: If file format is not supported.
            FileNotFoundError: If file does not exist.
        """
        file_path = _resolve_unicode_path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported file format: {ext}. "
                f"Supported formats: {list(self.SUPPORTED_FORMATS.keys())}"
            )

        format_type = self.SUPPORTED_FORMATS[ext]

        # Read raw data to detect headers
        raw_df = self._read_raw(file_path, format_type, sheet_name, **kwargs)

        # Determine header rows
        if header_rows == 'auto':
            header_rows = self._detect_header_rows(raw_df)
        elif isinstance(header_rows, int):
            header_rows = list(range(header_rows))

        # Re-read with proper header specification
        df = self._read_with_headers(
            file_path, format_type, header_rows, sheet_name, **kwargs
        )

        # Flatten multi-level columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = self._flatten_columns(df.columns)
        else:
            # Single-level but may need cleaning from auto-detection
            df.columns = self._clean_column_names(df.columns)

        return df

    def _read_raw(
        self,
        file_path: Path,
        format_type: str,
        sheet_name: str | int = 0,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Read file without header processing for inspection."""
        kwargs_copy = kwargs.copy()
        kwargs_copy['header'] = None

        if format_type == 'excel':
            return pd.read_excel(file_path, sheet_name=sheet_name, **kwargs_copy)
        elif format_type == 'csv':
            encoding = kwargs_copy.pop('encoding', self.encoding)
            sep = kwargs_copy.pop('sep', ',' if file_path.suffix == '.csv' else '\t')
            return pd.read_csv(file_path, encoding=encoding, sep=sep, **kwargs_copy)
        elif format_type == 'ods':
            return pd.read_excel(file_path, sheet_name=sheet_name, engine='odf', **kwargs_copy)
        elif format_type == 'parquet':
            # Parquet files typically don't have multi-level headers in the same way
            df = pd.read_parquet(file_path, **kwargs_copy)
            return df

        raise ValueError(f"Unknown format type: {format_type}")

    def _read_with_headers(
        self,
        file_path: Path,
        format_type: str,
        header_rows: list[int],
        sheet_name: str | int = 0,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Read file with specified header rows."""
        kwargs_copy = kwargs.copy()
        kwargs_copy['header'] = header_rows if len(header_rows) > 1 else header_rows[0]

        if format_type == 'excel':
            return pd.read_excel(file_path, sheet_name=sheet_name, **kwargs_copy)
        elif format_type == 'csv':
            encoding = kwargs_copy.pop('encoding', self.encoding)
            sep = kwargs_copy.pop('sep', ',' if file_path.suffix == '.csv' else '\t')
            return pd.read_csv(file_path, encoding=encoding, sep=sep, **kwargs_copy)
        elif format_type == 'ods':
            return pd.read_excel(file_path, sheet_name=sheet_name, engine='odf', **kwargs_copy)
        elif format_type == 'parquet':
            return pd.read_parquet(file_path, **kwargs_copy)

        raise ValueError(f"Unknown format type: {format_type}")

    def _detect_header_rows(self, raw_df: pd.DataFrame) -> list[int]:
        """
        Automatically detect the number of header rows.

        Detection strategy:
        1. Header rows have no actual numeric values (only strings)
        2. Data rows have a mix of strings and numeric values
        3. Data rows may contain ID-like patterns (hex codes, alphanumeric IDs)
        4. Consider fill density transitions (header rows often sparser)
        """
        if raw_df.empty:
            return [0]

        header_candidates = []
        total_cols = len(raw_df.columns)

        for row_idx in range(min(self.max_header_rows, len(raw_df))):
            row = raw_df.iloc[row_idx]
            analysis = self._analyze_row(row)

            # A row is a header if:
            # 1. It has no numeric values (actual int/float types)
            # 2. It has no ID-like patterns (hex strings, UUIDs)
            # 3. OR it's very sparse (header categories)
            is_header = (
                analysis['numeric_count'] == 0 and
                analysis['id_like_count'] == 0
            )

            # Also consider sparse rows with all strings as headers
            fill_ratio = analysis['non_null_count'] / total_cols
            if fill_ratio < 0.5 and analysis['numeric_count'] == 0:
                is_header = True

            if is_header:
                header_candidates.append(row_idx)
            else:
                # Found first data row, stop looking
                break

        # If no headers detected, assume first row is header
        if not header_candidates:
            return [0]

        return header_candidates

    def _analyze_row(self, row: pd.Series) -> dict[str, int]:
        """
        Analyze a row and return counts of different value types.

        Returns dict with:
        - non_null_count: Number of non-null values
        - string_count: Number of string values
        - numeric_count: Number of actual numeric values (int/float types)
        - id_like_count: Number of ID-like strings (hex codes, alphanumeric)
        """
        non_null_values = row.dropna()

        string_count = 0
        numeric_count = 0
        id_like_count = 0

        for val in non_null_values:
            if isinstance(val, (int, float)):
                # Actual numeric type
                numeric_count += 1
            elif isinstance(val, str):
                # Check if it's an ID-like string
                if self._is_id_like(val):
                    id_like_count += 1
                string_count += 1

        return {
            'non_null_count': len(non_null_values),
            'string_count': string_count,
            'numeric_count': numeric_count,
            'id_like_count': id_like_count,
        }

    def _is_id_like(self, val: str) -> bool:
        """
        Check if a string looks like an ID (hex code, UUID, alphanumeric ID).

        ID patterns:
        - Hex strings: at least 8 chars, all hex digits
        - UUID-like: contains hyphens with alphanumeric segments
        - Long alphanumeric: 10+ chars, mix of letters and digits
        """
        if not val or len(val) < 8:
            return False

        val_clean = val.strip()

        # Check for hex-like strings (at least 16 chars of hex)
        if len(val_clean) >= 16:
            try:
                int(val_clean, 16)
                return True
            except ValueError:
                pass

        # Check for UUID-like patterns (8-4-4-4-12 or similar)
        if '-' in val_clean:
            parts = val_clean.split('-')
            if len(parts) >= 3:
                if all(p.isalnum() for p in parts if p):
                    return True

        # Check for long alphanumeric strings that look like IDs
        if len(val_clean) >= 16 and val_clean.isalnum():
            has_digit = any(c.isdigit() for c in val_clean)
            has_letter = any(c.isalpha() for c in val_clean)
            if has_digit and has_letter:
                return True

        return False

    def _is_header_row(self, row: pd.Series) -> bool:
        """
        Determine if a row looks like a header row.
        (Kept for backwards compatibility, uses _analyze_row internally)
        """
        analysis = self._analyze_row(row)
        return analysis['numeric_count'] == 0 and analysis['id_like_count'] == 0

    def _flatten_columns(self, columns: pd.MultiIndex) -> list[str]:
        """
        Flatten MultiIndex columns into single-level column names.

        Handles:
        - NaN values (from merged cells) - propagates parent value
        - Unnamed columns - removes or propagates parent
        - Duplicate separators - cleans up
        """
        flattened = []

        # Get number of levels
        n_levels = columns.nlevels

        # Forward-fill parent names for merged cells
        prev_names = [None] * n_levels

        for col_tuple in columns:
            parts = []

            for level_idx, name in enumerate(col_tuple):
                # Handle NaN and Unnamed columns
                if pd.isna(name) or (isinstance(name, str) and name.startswith('Unnamed:')):
                    # Use previous name at this level if available
                    if prev_names[level_idx] is not None:
                        name = prev_names[level_idx]
                    else:
                        name = None
                else:
                    prev_names[level_idx] = name

                if name is not None:
                    parts.append(str(name).strip())

            # Remove duplicates (parent == child case)
            unique_parts = []
            for part in parts:
                if not unique_parts or unique_parts[-1] != part:
                    unique_parts.append(part)

            # Join with separator
            col_name = self.separator.join(unique_parts) if unique_parts else f"Column_{len(flattened)}"

            flattened.append(col_name)

        # Handle duplicate column names
        flattened = self._handle_duplicate_names(flattened)

        return flattened

    def _clean_column_names(self, columns: pd.Index) -> list[str]:
        """Clean single-level column names."""
        cleaned = []

        for col in columns:
            if pd.isna(col) or (isinstance(col, str) and col.startswith('Unnamed:')):
                cleaned.append(f"Column_{len(cleaned)}")
            else:
                cleaned.append(str(col).strip())

        return self._handle_duplicate_names(cleaned)

    def _handle_duplicate_names(self, names: list[str]) -> list[str]:
        """Add suffixes to duplicate column names."""
        seen = {}
        result = []

        for name in names:
            if name in seen:
                seen[name] += 1
                result.append(f"{name}_{seen[name]}")
            else:
                seen[name] = 0
                result.append(name)

        return result

    def get_header_info(
        self,
        file_path: str | Path,
        sheet_name: str | int = 0,
    ) -> dict[str, Any]:
        """
        Analyze a file and return information about its header structure.

        Args:
            file_path: Path to the file.
            sheet_name: Sheet name or index for Excel/ODS files.

        Returns:
            Dictionary with header analysis information.
        """
        file_path = _resolve_unicode_path(file_path)
        ext = file_path.suffix.lower()
        format_type = self.SUPPORTED_FORMATS.get(ext)

        if format_type is None:
            return {'error': f'Unsupported format: {ext}'}

        raw_df = self._read_raw(file_path, format_type, sheet_name)
        detected_headers = self._detect_header_rows(raw_df)

        # Get header content
        header_content = []
        for idx in detected_headers:
            if idx < len(raw_df):
                row_data = raw_df.iloc[idx].tolist()
                header_content.append({
                    'row_index': idx,
                    'values': row_data,
                    'non_null_count': sum(1 for v in row_data if pd.notna(v)),
                })

        return {
            'file_path': str(file_path),
            'format': format_type,
            'total_rows': len(raw_df),
            'total_columns': len(raw_df.columns),
            'detected_header_rows': detected_headers,
            'header_count': len(detected_headers),
            'header_content': header_content,
        }


def read_multi_level(
    file_path: str | Path,
    separator: str = '_',
    header_rows: int | list[int] | Literal['auto'] = 'auto',
    sheet_name: str | int = 0,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Convenience function to read a file with multi-level headers.

    Args:
        file_path: Path to the file to read.
        separator: Character(s) used to join multi-level header names.
        header_rows: Number of header rows, list of row indices, or 'auto'.
        sheet_name: Sheet name or index for Excel/ODS files.
        **kwargs: Additional arguments passed to pandas reader.

    Returns:
        DataFrame with flattened column names.

    Example:
        >>> df = read_multi_level('data.xlsx')
        >>> df = read_multi_level('data.csv', separator='/', header_rows=2)
    """
    reader = MultiLevelReader(separator=separator)
    return reader.read(file_path, header_rows=header_rows, sheet_name=sheet_name, **kwargs)


def analyze_headers(
    file_path: str | Path,
    sheet_name: str | int = 0,
) -> dict[str, Any]:
    """
    Analyze a file's header structure.

    Args:
        file_path: Path to the file.
        sheet_name: Sheet name or index for Excel/ODS files.

    Returns:
        Dictionary with header analysis information.
    """
    reader = MultiLevelReader()
    return reader.get_header_info(file_path, sheet_name)


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python reader.py <file_path> [--analyze]")
        sys.exit(1)

    file_path = sys.argv[1]

    if '--analyze' in sys.argv:
        info = analyze_headers(file_path)
        print("Header Analysis:")
        for key, value in info.items():
            print(f"  {key}: {value}")
    else:
        df = read_multi_level(file_path)
        print(f"Shape: {df.shape}")
        print(f"\nColumns ({len(df.columns)}):")
        for col in df.columns:
            print(f"  - {col}")
        print(f"\nFirst 5 rows:")
        print(df.head())
