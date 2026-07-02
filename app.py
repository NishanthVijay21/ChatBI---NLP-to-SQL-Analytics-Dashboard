"""
app.py
"""

import io
import os
import json
import zipfile

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from data_engine import DataEngine
from llm_engine import LLMEngine
from chart_component import render_chart, render_dashboard_export_button

load_dotenv()
st.set_page_config(page_title="Querydeck", page_icon="◧", layout="wide")


# ──────────────────────────────────────────── session state
def _init_state():
    defaults = {
        "engine": DataEngine(),
        "llm": None,
        "history": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

engine: DataEngine = st.session_state.engine


def get_llm() -> LLMEngine:
    if st.session_state.llm is None:
        st.session_state.llm = LLMEngine()  
    return st.session_state.llm


# ──────────────────────────────────────────── sidebar
with st.sidebar:
    st.markdown("## ◧ Querydeck")

    st.markdown("### Setup")
    if os.environ.get("CLOUDFLARE_API_TOKEN"):
        st.success("🔒 Secured by Cloudflare Workers AI")
    else:
        st.warning("⚠️ Missing Cloudflare credentials in .env file.")

    st.divider()

    st.markdown("### Datasets")
    uploaded_files = st.file_uploader(
        "Upload CSV or Excel files",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    for uf in (uploaded_files or []):
        file_key = f"loaded_{uf.name}_{uf.size}"
        if file_key not in st.session_state:
            try:
                tname = engine.load_file(uf, uf.name)
                st.session_state[file_key] = tname
                st.success(f"Loaded **{uf.name}** → `{tname}`")
            except Exception as e:
                st.error(f"Failed to load {uf.name}: {e}")

    if engine.tables:
        st.markdown("**Loaded tables**")
        for tname, meta in list(engine.tables.items()):
            col1, col2 = st.columns([3, 1])
            col1.markdown(f"`{tname}` — {meta['row_count']:,} rows")
            if col2.button("✕", key=f"drop_{tname}", help=f"Remove {tname}"):
                engine.drop_table(tname)
                st.rerun()
    else:
        st.info("No datasets loaded yet.")

    st.divider()

    st.markdown("### Merge tables")
    if len(engine.tables) >= 2:
        merge_desc = st.text_area(
            "Describe the join",
            placeholder="e.g. inner join sales and customers on region",
            height=90,
            label_visibility="collapsed",
        )
        merge_name = st.text_input("Result table name", value="merged")
        if st.button("Run merge", use_container_width=True):
            if merge_desc.strip():
                with st.spinner("Writing merge SQL…"):
                    try:
                        sql = get_llm().get_merge_sql(
                            merge_desc, engine.all_schemas_description()
                        )
                        engine.merge_tables(sql, merge_name)
                        st.success(f"Created table `{merge_name}`")
                        st.code(sql, language="sql")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Merge failed: {e}")
            else:
                st.warning("Describe the join first.")
    else:
        st.caption("Upload ≥ 2 datasets to enable merging.")

    st.divider()

    # ── data-only exports (Python side — no pixel access needed)
    chart_turns = [
        t for t in st.session_state.history
        if t.get("result_df") is not None and (t.get("plan") or {}).get("mode") == "chart"
    ]
    if chart_turns:
        st.markdown("### Data exports")

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, turn in enumerate(chart_turns):
                csv_bytes = turn["result_df"].to_csv(index=False).encode()
                label = turn["question"][:40].replace(" ", "_").replace("/", "-")
                zf.writestr(f"chart_{i+1}_{label}.csv", csv_bytes)
        zip_buf.seek(0)
        st.download_button(
            "⬇ All chart data (ZIP of CSVs)",
            data=zip_buf,
            file_name="querydeck_data.zip",
            mime="application/zip",
            use_container_width=True,
        )

        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            for i, turn in enumerate(chart_turns):
                sheet_label = f"Chart {i+1}"
                df = turn["result_df"]
                # Write question as first row, then data below it
                question_df = pd.DataFrame({"Question": [turn["question"]]})
                question_df.to_excel(writer, sheet_name=sheet_label, index=False, startrow=0)
                df.to_excel(writer, sheet_name=sheet_label, index=False, startrow=2)
        excel_buf.seek(0)
        st.download_button(
            "⬇ All chart data (Excel workbook)",
            data=excel_buf,
            file_name="querydeck_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.caption("Chart images → use the PNG/PDF buttons next to each chart below.")


# ──────────────────────────────────────────── main area
st.markdown("## Querydeck")
st.caption("Ask in plain English — charts or result tables depending on what you need.")

if not engine.tables:
    st.info("Upload a CSV or Excel file from the sidebar to get started.")
    st.stop()

# ── schema expanders
with st.expander("Loaded schemas", expanded=False):
    for tname, meta in engine.tables.items():
        st.markdown(f"**`{tname}`** — {meta['row_count']:,} rows · _{meta['filename']}_")
        if meta["schema"]:
            schema_df = pd.DataFrame(meta["schema"]).rename(columns={
                "name": "column", "type": "type",
                "sample": "sample value", "null_pct": "null %",
            })
            st.dataframe(schema_df, use_container_width=True, hide_index=True)

# ── query box
with st.form("query_form", clear_on_submit=True):
    question = st.text_area(
        "Ask something",
        height=80,
        label_visibility="collapsed",
        placeholder=(
            "e.g. show monthly revenue as a bar chart  ·  "
            "cast the price column to integer  ·  "
            "show top 10 customers by total spend"
        ),
    )
    submitted = st.form_submit_button("Run", use_container_width=True)

if submitted and question.strip():
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        st.error("Missing Cloudflare API Token in your .env file.")
    else:
        turn = {"question": question.strip(), "plan": None, "result_df": None, "error": None}

        with st.spinner("Planning query…"):
            try:
                plan = get_llm().get_query_plan(
                    user_question=turn["question"],
                    schemas_description=engine.all_schemas_description(),
                )
                turn["plan"] = plan
            except Exception as e:
                turn["error"] = f"Couldn't get a query plan: {e}"

        if turn["plan"] is not None:
            try:
                turn["result_df"] = engine.run_query(turn["plan"]["sql"])
            except Exception as e:
                turn["error"] = f"SQL execution failed: {e}"

        st.session_state.history.append(turn)
        st.rerun()


# ──────────────────────────────────────────── thread (newest first)
dashboard_charts = []
for i, turn in enumerate(reversed(st.session_state.history)):
    if (
        (turn.get("plan") or {}).get("mode") == "chart"
        and turn.get("result_df") is not None
        and not turn.get("error")
        and (turn.get("plan") or {}).get("chart")
    ):
        global_idx = len(st.session_state.history) - 1 - i
        spec = dict(turn["plan"]["chart"])
        spec["data"] = {"values": turn["result_df"].to_dict(orient="records")}
        spec.setdefault("$schema", "https://vega.github.io/schema/vega-lite/v5.json")
        dashboard_charts.append({"spec": spec, "title": turn["question"]})

if dashboard_charts:
    render_dashboard_export_button(dashboard_charts)
    st.markdown("")

for i, turn in enumerate(reversed(st.session_state.history)):
    global_idx = len(st.session_state.history) - 1 - i

    st.markdown("---")
    st.markdown(f"**{turn['question']}**")

    plan = turn.get("plan") or {}

    with st.expander("Generated SQL", expanded=False):
        st.code(plan.get("sql", "(none)"), language="sql")

    if turn.get("error"):
        st.error(turn["error"])
        continue

    result_df: pd.DataFrame | None = turn.get("result_df")
    if result_df is None or result_df.empty:
        st.warning("Query returned no rows.")
        continue

    note = plan.get("note", "")
    mode = plan.get("mode", "chart")
    caption = f"{note} · {len(result_df):,} row(s)" if note else f"{len(result_df):,} row(s)"

    # ── TABLE mode
    if mode == "table":
        st.dataframe(result_df, use_container_width=True, hide_index=True)
        st.caption(caption)
        csv_bytes = result_df.to_csv(index=False).encode()
        label = turn["question"][:30].replace(" ", "_")
        st.download_button(
            "⬇ Download result as CSV",
            data=csv_bytes,
            file_name=f"{label}.csv",
            mime="text/csv",
            key=f"csv_dl_{global_idx}",
        )

        with st.expander("💾 Save as New Dataset", expanded=False):
            c1, c2 = st.columns([3, 1])
            new_table = c1.text_input(
                "Table name:",
                key=f"save_name_{global_idx}",
                placeholder="e.g. clean_sales",
            )
            if c2.button("Save", key=f"save_btn_{global_idx}", use_container_width=True):
                if new_table.strip():
                    try:
                        engine.merge_tables(plan["sql"], new_table.strip())
                        st.success(f"Saved as table `{new_table.strip()}`")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving table: {e}")
                else:
                    st.warning("Please enter a table name.")

    # ── CHART mode
    else:
        chart_spec = dict(plan.get("chart") or {})
        if not chart_spec:
            st.dataframe(result_df, use_container_width=True, hide_index=True)
            st.caption("(No chart spec returned — showing raw data.)")
        else:
            chart_spec["data"] = {"values": result_df.to_dict(orient="records")}
            chart_spec.setdefault("$schema", "https://vega.github.io/schema/vega-lite/v5.json")

            chart_id = f"chart_{global_idx}"
            render_chart(
                spec=chart_spec,
                chart_id=chart_id,
                title=turn["question"],
            )
            st.caption(caption)

            spec_bytes = json.dumps(chart_spec, indent=2).encode()
            label = turn["question"][:30].replace(" ", "_")
            st.download_button(
                "⬇ Vega-Lite spec (JSON)",
                data=spec_bytes,
                file_name=f"{label}_spec.json",
                mime="application/json",
                key=f"spec_dl_{global_idx}",
            )

        with st.expander("Result data", expanded=False):
            st.dataframe(result_df, use_container_width=True, hide_index=True)