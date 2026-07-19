"""
preprocess_ui.py
Streamlit rendering for the automatic preprocessing panel. Keeps a working
copy of the table (a `Preprocessor`) in session_state per table name so
changes accumulate across reruns until the user commits or discards them.
"""

import pandas as pd
import streamlit as st

from preprocess_engine import Preprocessor, profile_dataframe


def _state_key(table_name: str) -> str:
    return f"_preprocessor_{table_name}"


def clear_preprocessor(table_name: str) -> None:
    """Call this whenever a table is dropped/replaced elsewhere in the app."""
    st.session_state.pop(_state_key(table_name), None)


def _get_preprocessor(engine, table_name: str) -> Preprocessor:
    key = _state_key(table_name)
    if key not in st.session_state:
        st.session_state[key] = Preprocessor(engine.get_dataframe(table_name))
    return st.session_state[key]


def _reset_preprocessor(engine, table_name: str) -> None:
    st.session_state[_state_key(table_name)] = Preprocessor(engine.get_dataframe(table_name))


def render_preprocess_panel(engine, table_name: str) -> None:
    pp = _get_preprocessor(engine, table_name)
    df = pp.df
    profile = profile_dataframe(df)

    if not pp.summary.is_empty():
        st.caption("⚠️ You have uncommitted changes below — commit or discard at the bottom of this panel.")

    # ---------------------------------------------------------- headline metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Rows", f"{profile.row_count:,}")
    m2.metric("Columns", profile.column_count)
    m3.metric("Duplicate rows", profile.duplicate_rows)
    m4.metric("Missing cells", int(profile.missing_summary["missing_count"].sum()))

    kind_counts = pd.Series(profile.column_kinds).value_counts()
    st.caption("Column types: " + " · ".join(f"{k}: {v}" for k, v in kind_counts.items()))

    tabs = st.tabs([
        "📋 Report", "🕳 Missing values", "🔁 Duplicates",
        "🔧 Dtype & dates", "📏 Normalize", "🏷 Encode", "✅ Summary",
    ])

    # ══════════════════════════════════════════════════════════ Report
    with tabs[0]:
        kinds_df = pd.DataFrame(
            [{"column": c, "kind": k} for c, k in profile.column_kinds.items()]
        )
        st.dataframe(kinds_df, use_container_width=True, hide_index=True)

        st.markdown("**Missing value summary**")
        st.dataframe(profile.missing_summary, use_container_width=True, hide_index=True)

        outlier_rows = {c: i for c, i in profile.outliers.items() if i["count"] > 0}
        if outlier_rows:
            st.markdown("**Outliers (IQR method)**")
            for col, info in outlier_rows.items():
                c1, c2, c3 = st.columns([2, 3, 1])
                c1.write(f"`{col}`")
                c2.caption(f"{info['count']} outlier(s) · {info['pct']}% · outside [{info['lower']}, {info['upper']}]")
                if c3.button("Remove", key=f"outlier_{table_name}_{col}"):
                    removed = pp.remove_outliers_iqr(col)
                    st.success(f"Removed {removed} outlier row(s) from `{col}`.")
                    st.rerun()
        else:
            st.caption("No outliers detected in numerical columns (IQR method).")

        if profile.dtype_suggestions:
            st.markdown("**Datatype conversion suggestions**")
            st.dataframe(
                pd.DataFrame([{"column": c, **i} for c, i in profile.dtype_suggestions.items()]),
                use_container_width=True, hide_index=True,
            )

        if profile.date_candidates:
            st.markdown("**Possible date columns**")
            st.dataframe(
                pd.DataFrame([{"column": c, **i} for c, i in profile.date_candidates.items()]),
                use_container_width=True, hide_index=True,
            )

    # ══════════════════════════════════════════════════════════ Missing values
    with tabs[1]:
        missing_cols = profile.missing_summary[
            profile.missing_summary["missing_count"] > 0
        ]["column"].tolist()

        if not missing_cols:
            st.success("No missing values in this table.")
        else:
            if st.button("⚡ Auto-handle all missing values", key=f"miss_auto_{table_name}",
                          help="Numeric columns → median · everything else → mode"):
                for col in missing_cols:
                    kind = profile.column_kinds.get(col)
                    pp.handle_missing(col, "median" if kind == "numerical" else "mode")
                st.rerun()

            st.markdown("**Or handle one column at a time**")
            c1, c2, c3 = st.columns([2, 2, 1])
            target_col = c1.selectbox("Column", missing_cols, key=f"miss_col_{table_name}")
            kind = profile.column_kinds.get(target_col)
            options = ["drop", "mean", "median", "mode", "ffill", "bfill"] if kind == "numerical" \
                else ["drop", "mode", "ffill", "bfill"]
            strategy = c2.selectbox("Strategy", options, key=f"miss_strat_{table_name}")
            if c3.button("Apply", key=f"miss_apply_{table_name}", use_container_width=True):
                n = pp.handle_missing(target_col, strategy)
                st.success(f"Handled {n} missing value(s) in `{target_col}` via {strategy}.")
                st.rerun()

    # ══════════════════════════════════════════════════════════ Duplicates
    with tabs[2]:
        st.write(f"Detected **{profile.duplicate_rows}** duplicate row(s).")
        if profile.duplicate_rows > 0:
            if st.button("Remove duplicates", key=f"dup_{table_name}"):
                removed = pp.remove_duplicates()
                st.success(f"Removed {removed} duplicate row(s).")
                st.rerun()
        else:
            st.success("No duplicate rows found.")

    # ══════════════════════════════════════════════════════════ Dtype & dates
    with tabs[3]:
        st.markdown("**Suggested conversions**")
        if profile.dtype_suggestions:
            if st.button("⚡ Apply all suggested conversions", key=f"dtc_all_{table_name}"):
                for col, info in profile.dtype_suggestions.items():
                    pp.convert_dtype(col, info["suggested_type"])
                st.rerun()
            for col, info in profile.dtype_suggestions.items():
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.write(f"`{col}`")
                c2.caption(f"→ {info['suggested_type']} ({info['confidence_pct']}% confident)")
                if c3.button("Convert", key=f"dtc_{table_name}_{col}"):
                    pp.convert_dtype(col, info["suggested_type"])
                    st.rerun()
        else:
            st.caption("No obvious conversions detected.")

        st.markdown("**Suggested date columns**")
        if profile.date_candidates:
            if st.button("⚡ Parse all detected date columns", key=f"date_all_{table_name}"):
                for col in profile.date_candidates:
                    pp.parse_date(col)
                st.rerun()
            for col, info in profile.date_candidates.items():
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.write(f"`{col}`")
                c2.caption(f"{info['parseable_pct']}% parseable as dates")
                if c3.button("Parse", key=f"date_{table_name}_{col}"):
                    pp.parse_date(col)
                    st.rerun()
        else:
            st.caption("No date-like columns detected.")

        st.markdown("**Manual conversion**")
        c1, c2, c3 = st.columns([2, 2, 1])
        manual_col = c1.selectbox("Column", df.columns.tolist(), key=f"manual_col_{table_name}")
        manual_type = c2.selectbox(
            "Target type", ["integer", "float", "string", "boolean", "datetime"],
            key=f"manual_type_{table_name}",
        )
        if c3.button("Convert", key=f"manual_conv_{table_name}", use_container_width=True):
            try:
                pp.convert_dtype(manual_col, manual_type)
                st.rerun()
            except Exception as e:
                st.error(f"Conversion failed: {e}")

    # ══════════════════════════════════════════════════════════ Normalize
    with tabs[4]:
        numeric_cols = [c for c, k in profile.column_kinds.items() if k == "numerical"]
        if not numeric_cols:
            st.caption("No numerical columns to normalize.")
        else:
            c1, c2, c3 = st.columns([2, 2, 1])
            norm_col = c1.selectbox("Column", numeric_cols, key=f"norm_col_{table_name}")
            norm_method = c2.selectbox("Method", ["minmax", "zscore"], key=f"norm_method_{table_name}")
            if c3.button("Normalize", key=f"norm_apply_{table_name}", use_container_width=True):
                pp.normalize(norm_col, norm_method)
                st.rerun()
            st.caption("minmax → scales to [0, 1] · zscore → mean 0, std 1")

    # ══════════════════════════════════════════════════════════ Encode
    with tabs[5]:
        cat_cols = [c for c, k in profile.column_kinds.items() if k == "categorical"]
        if not cat_cols:
            st.caption("No categorical columns to encode.")
        else:
            c1, c2, c3 = st.columns([2, 2, 1])
            enc_col = c1.selectbox("Column", cat_cols, key=f"enc_col_{table_name}")
            enc_method = c2.selectbox("Method", ["onehot", "label"], key=f"enc_method_{table_name}")
            if c3.button("Encode", key=f"enc_apply_{table_name}", use_container_width=True):
                pp.encode(enc_col, enc_method)
                st.rerun()
            st.caption("onehot → one column per category · label → single integer-coded column")

    # ══════════════════════════════════════════════════════════ Summary
    with tabs[6]:
        s = pp.summary
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Rows removed", s.rows_removed)
        s2.metric("Columns converted", len(s.columns_converted))
        s3.metric("Missing values handled", sum(x["count"] for x in s.missing_handled))
        s4.metric("Duplicates removed", s.duplicates_removed)

        if s.missing_handled:
            st.markdown("**Missing value actions**")
            st.dataframe(pd.DataFrame(s.missing_handled), use_container_width=True, hide_index=True)
        if s.columns_converted:
            st.markdown("**Dtype conversions**")
            st.dataframe(pd.DataFrame(s.columns_converted), use_container_width=True, hide_index=True)
        if s.outliers_removed:
            st.markdown("**Outlier removal**")
            st.dataframe(pd.DataFrame(s.outliers_removed), use_container_width=True, hide_index=True)
        if s.columns_normalized:
            st.markdown("**Normalization**")
            st.dataframe(pd.DataFrame(s.columns_normalized), use_container_width=True, hide_index=True)
        if s.columns_encoded:
            st.markdown("**Encoding**")
            st.dataframe(pd.DataFrame(s.columns_encoded), use_container_width=True, hide_index=True)
        if s.is_empty():
            st.caption("No changes applied yet.")

    # ---------------------------------------------------------- preview + commit
    # ---------------------------------------------------------- preview + commit
    st.markdown("#### Preview (working copy — not yet saved)")
    st.dataframe(pp.df.head(50), use_container_width=True, hide_index=True)

    cc1, cc2 = st.columns(2)
    if cc1.button("💾 Overwrite original table", key=f"commit_{table_name}",
                   type="primary", use_container_width=True, disabled=pp.summary.is_empty()):
        engine.replace_table_data(table_name, pp.df)
        _reset_preprocessor(engine, table_name)
        st.success(f"Table `{table_name}` updated.")
        st.rerun()
        
    if cc2.button("↺ Discard working changes", key=f"discard_{table_name}",
                   use_container_width=True, disabled=pp.summary.is_empty()):
        _reset_preprocessor(engine, table_name)
        st.rerun()

    with st.expander("💾 Save as a new table instead", expanded=False):
        c1, c2 = st.columns([3, 1])
        new_table_name = c1.text_input(
            "New table name:", 
            value=f"{table_name}_clean", 
            key=f"new_name_{table_name}"
        )
        if c2.button("Save As", key=f"save_as_{table_name}", use_container_width=True, disabled=pp.summary.is_empty()):
            new_table_name = new_table_name.strip()
            if new_table_name:
                # Initialize the dictionary entry so _refresh_schema doesn't throw a KeyError
                if new_table_name not in engine.tables:
                    engine.tables[new_table_name] = {
                        "filename": f"(cleaned from {table_name})",
                        "schema": [],
                        "row_count": 0,
                    }
                engine.replace_table_data(new_table_name, pp.df)
                
                # Reset the working copy of the original table
                _reset_preprocessor(engine, table_name)
                st.rerun()
            else:
                st.warning("Please provide a valid table name.")