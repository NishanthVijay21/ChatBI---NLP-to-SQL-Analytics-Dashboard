"""
preprocess_engine.py
Automatic data preprocessing: profiling + one-click cleaning transforms.

Pure pandas — no Streamlit, no DuckDB. `DataEngine` pulls a table into a
DataFrame, `Preprocessor` transforms it in memory, and the caller decides
when to push the result back into DuckDB.
"""

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════ profiling

def infer_column_kind(series: pd.Series) -> str:
    """Classify a column as numerical / categorical / datetime / boolean / text."""
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "numerical"

    non_null = series.dropna()
    if non_null.empty:
        return "categorical"

    n_unique = non_null.nunique()
    ratio = n_unique / max(len(non_null), 1)
    # low cardinality (relative or absolute) -> categorical, otherwise free text / id-like
    if ratio < 0.5 or n_unique <= 50:
        return "categorical"
    return "text"


def _is_stringlike(series: pd.Series) -> bool:
    """True for classic object-dtype columns AND pandas' newer dedicated string dtype."""
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)


def detect_date_columns(df: pd.DataFrame, sample_size: int = 200) -> dict:
    """Sample string-like columns and flag ones that look like dates."""
    candidates = {}
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        if not _is_stringlike(df[col]):
            continue
        sample = df[col].dropna().astype(str).head(sample_size)
        if sample.empty:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(sample, errors="coerce")
        pct = float(parsed.notna().mean())
        if pct >= 0.8:
            candidates[col] = {"parseable_pct": round(pct * 100, 1)}
    return candidates


def missing_value_summary(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    rows = []
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        rows.append({
            "column": col,
            "missing_count": n_missing,
            "missing_pct": round(100 * n_missing / total, 2) if total else 0.0,
        })
    return pd.DataFrame(rows)


def detect_outliers_iqr(series: pd.Series, k: float = 1.5) -> dict:
    """IQR-based outlier bounds/count for a numeric series."""
    clean = series.dropna()
    if clean.empty or not pd.api.types.is_numeric_dtype(clean):
        return {"count": 0, "pct": 0.0, "lower": None, "upper": None}

    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return {"count": 0, "pct": 0.0, "lower": float(q1), "upper": float(q3)}

    lower, upper = q1 - k * iqr, q3 + k * iqr
    mask = (clean < lower) | (clean > upper)
    return {
        "count": int(mask.sum()),
        "pct": round(100 * mask.sum() / len(clean), 2),
        "lower": round(float(lower), 4),
        "upper": round(float(upper), 4),
    }


def suggest_dtype_conversions(df: pd.DataFrame) -> dict:
    """Look at object columns and suggest a better-fitting dtype."""
    suggestions = {}
    for col in df.columns:
        if not _is_stringlike(df[col]):
            continue
        sample = df[col].dropna().astype(str).head(200)
        if sample.empty:
            continue

        numeric_parsed = pd.to_numeric(sample, errors="coerce")
        numeric_pct = float(numeric_parsed.notna().mean())
        if numeric_pct >= 0.95:
            is_int = bool((numeric_parsed.dropna() % 1 == 0).all())
            suggestions[col] = {
                "suggested_type": "integer" if is_int else "float",
                "confidence_pct": round(numeric_pct * 100, 1),
            }
            continue

        lowered = sample.str.strip().str.lower()
        bool_set = {"true", "false", "yes", "no", "y", "n"}
        bool_pct = float(lowered.isin(bool_set).mean())
        if bool_pct >= 0.95:
            suggestions[col] = {
                "suggested_type": "boolean",
                "confidence_pct": round(bool_pct * 100, 1),
            }

    return suggestions


@dataclass
class ProfileReport:
    row_count: int
    column_count: int
    column_kinds: dict
    missing_summary: pd.DataFrame
    duplicate_rows: int
    outliers: dict
    dtype_suggestions: dict
    date_candidates: dict


def profile_dataframe(df: pd.DataFrame) -> ProfileReport:
    kinds = {c: infer_column_kind(df[c]) for c in df.columns}
    outliers = {c: detect_outliers_iqr(df[c]) for c, k in kinds.items() if k == "numerical"}

    return ProfileReport(
        row_count=len(df),
        column_count=len(df.columns),
        column_kinds=kinds,
        missing_summary=missing_value_summary(df),
        duplicate_rows=int(df.duplicated().sum()),
        outliers=outliers,
        dtype_suggestions=suggest_dtype_conversions(df),
        date_candidates=detect_date_columns(df),
    )


# ══════════════════════════════════════════════════════════════ transforms

@dataclass
class PreprocessSummary:
    rows_removed: int = 0
    duplicates_removed: int = 0
    columns_converted: list = field(default_factory=list)
    missing_handled: list = field(default_factory=list)
    columns_normalized: list = field(default_factory=list)
    columns_encoded: list = field(default_factory=list)
    outliers_removed: list = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.rows_removed, self.duplicates_removed, self.columns_converted,
            self.missing_handled, self.columns_normalized, self.columns_encoded,
            self.outliers_removed,
        ])


class Preprocessor:
    """
    Wraps a working-copy DataFrame plus a running PreprocessSummary so a UI
    can apply a sequence of one-click cleaning ops and always show the
    cumulative effect before committing back to storage.
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.summary = PreprocessSummary()

    # ---------------------------------------------------------- missing values

    def handle_missing(self, column: str, strategy: str) -> int:
        col = self.df[column]
        n_missing = int(col.isna().sum())
        if n_missing == 0:
            return 0

        if strategy == "drop":
            before = len(self.df)
            self.df = self.df[self.df[column].notna()].reset_index(drop=True)
            removed = before - len(self.df)
            self.summary.rows_removed += removed
        elif strategy == "mean":
            self.df[column] = col.fillna(col.mean())
        elif strategy == "median":
            self.df[column] = col.fillna(col.median())
        elif strategy == "mode":
            mode_vals = col.mode(dropna=True)
            fill = mode_vals.iloc[0] if not mode_vals.empty else None
            self.df[column] = col.fillna(fill)
        elif strategy == "ffill":
            self.df[column] = col.ffill()
        elif strategy == "bfill":
            self.df[column] = col.bfill()
        else:
            raise ValueError(f"Unknown missing-value strategy: {strategy}")

        self.summary.missing_handled.append(
            {"column": column, "strategy": strategy, "count": n_missing}
        )
        return n_missing

    # ---------------------------------------------------------- duplicates

    def remove_duplicates(self) -> int:
        before = len(self.df)
        self.df = self.df.drop_duplicates().reset_index(drop=True)
        removed = before - len(self.df)
        self.summary.duplicates_removed += removed
        self.summary.rows_removed += removed
        return removed

    # ---------------------------------------------------------- dtype conversion

    def convert_dtype(self, column: str, target_type: str) -> None:
        original_dtype = str(self.df[column].dtype)

        if target_type == "integer":
            self.df[column] = pd.to_numeric(self.df[column], errors="coerce").astype("Int64")
        elif target_type == "float":
            self.df[column] = pd.to_numeric(self.df[column], errors="coerce")
        elif target_type == "boolean":
            mapping = {"true": True, "yes": True, "y": True, "1": True,
                       "false": False, "no": False, "n": False, "0": False}
            self.df[column] = (
                self.df[column].astype(str).str.strip().str.lower().map(mapping)
            )
        elif target_type == "string":
            self.df[column] = self.df[column].astype(str)
        elif target_type == "datetime":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.df[column] = pd.to_datetime(self.df[column], errors="coerce")
        else:
            raise ValueError(f"Unknown target type: {target_type}")

        self.summary.columns_converted.append(
            {"column": column, "from": original_dtype, "to": target_type}
        )

    def parse_date(self, column: str) -> None:
        self.convert_dtype(column, "datetime")

    # ---------------------------------------------------------- normalization

    def normalize(self, column: str, method: str = "minmax") -> None:
        col = pd.to_numeric(self.df[column], errors="coerce")
        if method == "minmax":
            lo, hi = col.min(), col.max()
            self.df[column] = (col - lo) / (hi - lo) if hi != lo else 0.0
        elif method == "zscore":
            mu, sigma = col.mean(), col.std()
            self.df[column] = (col - mu) / sigma if sigma else 0.0
        else:
            raise ValueError(f"Unknown normalization method: {method}")
        self.summary.columns_normalized.append({"column": column, "method": method})

    # ---------------------------------------------------------- encoding

    def encode(self, column: str, method: str = "onehot") -> None:
        if method == "onehot":
            dummies = pd.get_dummies(self.df[column], prefix=column)
            self.df = pd.concat([self.df.drop(columns=[column]), dummies], axis=1)
        elif method == "label":
            self.df[column] = self.df[column].astype("category").cat.codes
        else:
            raise ValueError(f"Unknown encoding method: {method}")
        self.summary.columns_encoded.append({"column": column, "method": method})

    # ---------------------------------------------------------- outliers

    def remove_outliers_iqr(self, column: str, k: float = 1.5) -> int:
        info = detect_outliers_iqr(self.df[column], k=k)
        if info["lower"] is None:
            return 0
        before = len(self.df)
        keep = self.df[column].between(info["lower"], info["upper"]) | self.df[column].isna()
        self.df = self.df[keep].reset_index(drop=True)
        removed = before - len(self.df)
        if removed:
            self.summary.rows_removed += removed
            self.summary.outliers_removed.append({"column": column, "count": removed})
        return removed
