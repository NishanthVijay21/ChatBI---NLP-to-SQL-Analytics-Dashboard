"""
insights_engine.py
Computes a compact, JSON-serializable statistical profile of a table so an LLM
can phrase it into "Key Insights" bullets without inventing any numbers.

Design principle: every figure the LLM is allowed to mention must already be
present in the dict returned by `compute_table_stats`. The LLM's job is only
to pick the most interesting facts and phrase them in plain English.
"""

import numpy as np
import pandas as pd


def _to_native(value):
    """Convert numpy/pandas scalar types to plain Python types for json.dumps."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _detect_date_column(df: pd.DataFrame) -> str | None:
    """Return the best candidate date/time column, or None if none looks date-like."""
    best_col, best_score = None, 0.0
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            return col
        if s.dtype == object or pd.api.types.is_string_dtype(s):
            try:
                parsed = pd.to_datetime(s, errors="coerce")
            except Exception:
                continue
            score = parsed.notna().mean() if len(s) else 0
            if score > 0.8 and score > best_score:
                best_col, best_score = col, score
    return best_col


def compute_table_stats(df: pd.DataFrame, max_categories: int = 8) -> dict:
    """
    Produce a compact summary of a dataframe: row/column counts, data-quality
    flags, numeric column totals, top categorical contributors, and
    month-over-month trends (including decline/increase streaks) for any
    numeric column when a date-like column is present.
    """
    stats: dict = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "duplicate_rows": int(df.duplicated().sum()) if len(df) else 0,
        "missing_cells": int(df.isna().sum().sum()) if len(df) else 0,
    }

    if df.empty:
        return stats

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    # ---- numeric column summaries
    numeric_summary = {}
    for col in numeric_cols:
        s = df[col].dropna()
        if s.empty:
            continue
        numeric_summary[col] = {
            "sum": _to_native(s.sum()),
            "mean": _to_native(round(s.mean(), 2)),
            "min": _to_native(s.min()),
            "max": _to_native(s.max()),
        }
    if numeric_summary:
        stats["numeric_summary"] = numeric_summary

    # ---- categorical top values (share of rows, and share of a numeric total)
    categorical_summary = {}
    primary_numeric = numeric_cols[0] if numeric_cols else None
    for col in categorical_cols:
        s = df[col].dropna()
        if s.empty or s.nunique() > 50:
            continue  # skip likely-ID / high-cardinality columns
        value_counts = s.value_counts().head(max_categories)
        entry = {
            "top_value": str(value_counts.index[0]),
            "top_value_row_share_pct": _to_native(round(100 * value_counts.iloc[0] / len(s), 1)),
            "unique_count": int(s.nunique()),
        }
        if primary_numeric:
            grouped = df.groupby(col)[primary_numeric].sum().sort_values(ascending=False)
            total = grouped.sum()
            if total:
                entry[f"top_value_by_{primary_numeric}"] = str(grouped.index[0])
                entry[f"top_value_by_{primary_numeric}_share_pct"] = _to_native(
                    round(100 * grouped.iloc[0] / total, 1)
                )
        categorical_summary[col] = entry
    if categorical_summary:
        stats["categorical_summary"] = categorical_summary

    # ---- month-over-month trend, if a date-like column exists
    date_col = _detect_date_column(df)
    if date_col and numeric_cols:
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        tmp = df.copy()
        tmp["_period"] = parsed.dt.to_period("M")
        trend = {}
        for col in numeric_cols[:5]:
            monthly_sum = tmp.groupby("_period")[col].sum().dropna()
            monthly_mean = tmp.groupby("_period")[col].mean().dropna()
            if len(monthly_sum) < 2:
                continue

            first, last = monthly_sum.iloc[0], monthly_sum.iloc[-1]
            pct_change = ((last - first) / first * 100) if first else None

            # streak of consecutive month-over-month moves in the mean,
            # counted backwards from the most recent month
            diffs = monthly_mean.diff().dropna()
            streak_dir, streak_len = None, 0
            for d in diffs.iloc[::-1]:
                direction = "decline" if d < 0 else ("increase" if d > 0 else "flat")
                if streak_dir is None:
                    streak_dir, streak_len = direction, 1
                elif direction == streak_dir:
                    streak_len += 1
                else:
                    break

            trend[col] = {
                "date_column": date_col,
                "first_period": str(monthly_sum.index[0]),
                "last_period": str(monthly_sum.index[-1]),
                "sum_first_period": _to_native(round(first, 2)),
                "sum_last_period": _to_native(round(last, 2)),
                "sum_pct_change_first_to_last": (
                    _to_native(round(pct_change, 1)) if pct_change is not None else None
                ),
                "recent_mean_streak_direction": streak_dir,
                "recent_mean_streak_length_months": streak_len,
            }
        if trend:
            stats["time_trend"] = trend

    return stats
