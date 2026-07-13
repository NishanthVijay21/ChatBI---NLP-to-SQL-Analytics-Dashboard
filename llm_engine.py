"""
llm_engine.py
"""

import json
import os
from openai import OpenAI

MODEL_NAME = "@cf/zai-org/glm-5.2" 

SYSTEM_PROMPT = """You are a data analyst assistant. The user has loaded the following tables into DuckDB:

{schemas}

Your job is to convert a natural language request into a DuckDB SQL query plus a decision about how to present the result.

Output rules:
1. Always output raw JSON only — no markdown fences, no preamble.
2. The JSON must match this exact schema:
   {{"sql": "...", "mode": "chart" | "table", "chart": {{...}} | null, "note": "...",
     "explanation": {{"columns_used": [{{"column": "...", "role": "..."}}],
                       "aggregation": "...", "reasoning": "..."}}}}

Field rules:
- "sql": valid DuckDB SELECT (or WITH ... SELECT). Read-only — no DROP/DELETE/INSERT/UPDATE/ALTER.
  Can reference any combination of the tables listed above.
- "mode": choose "table" when the request is about cleaning, transforming, casting, inspecting,
  previewing, or filtering data and a chart would add no value.
  Choose "chart" when the user asks to visualize, plot, show a graph, or explore trends.
  When in doubt, default to "chart" with a sensible aggregation.
- "chart": required when mode == "chart". A Vega-Lite v5 spec WITHOUT a "data" key (data is
  injected separately). Field names in "encoding" MUST match the SQL column aliases exactly.
  Set null when mode == "table".
- "note": one plain-English sentence describing what was done.
- "explanation": always include, even for simple queries. An object with:
  - "columns_used": array of {{"column": <source column name>, "role": <one of "time dimension",
    "measure", "category", "filter", "join key", "identifier">}} covering the columns that
    mattered for answering the question (usually 2-5 — skip incidental ones).
  - "aggregation": the aggregation applied, written like "SUM(sales) grouped by month", or
    "none" if the query returns raw/unaggregated rows.
  - "reasoning": one or two plain-English sentences on why these columns/joins/filters were
    chosen to answer the question.

Extra SQL guidance:
- For cross-table queries, use proper JOIN syntax referencing table names as listed above.
- For transformations (cast float to int, trim strings, etc.), express them in the SELECT list
  using CAST / TRY_CAST / TRIM / COALESCE / CASE etc. Never mutate the source table.
- Keep chart result sets small (aggregate or LIMIT 500).
"""

MERGE_SYSTEM_PROMPT = """You are a data analyst. The user has these DuckDB tables:

{schemas}

Write a single DuckDB SQL SELECT (or WITH ... SELECT) that joins or unions these tables as the
user describes. Output ONLY the raw SQL string — no JSON, no markdown, no explanation."""

INSIGHTS_SYSTEM_PROMPT = """You are a data analyst. You are given precomputed statistics for
a table named "{table_name}" — row/column counts, data-quality flags, numeric column totals,
top categorical contributors, and month-over-month trends where available.

Write 3 to 6 short "key insight" bullet points a business user would care about at a glance.

Rules:
- Every bullet must be directly supported by a number in the stats below — never invent,
  estimate, or round in a way that changes a figure that isn't present.
- Keep each bullet under ~20 words, and lead with the concrete number or percentage.
- Prefer trends, top contributors, and data-quality flags (missing values, duplicates) over
  restating raw row/column counts.
- If the stats are too sparse to say anything interesting, return fewer bullets — never pad
  with generic filler like "the data looks clean".
- Output raw JSON only, no markdown fences, matching exactly: {{"insights": ["...", "..."]}}

STATS:
{stats}
"""

class LLMEngine:
    def __init__(self, api_key: str | None = None):
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
        
        self.client = OpenAI(
            base_url=base_url,
            api_key=os.environ.get("CLOUDFLARE_API_TOKEN")
        )

    # ---------------------------------------------------------------- main plan

    def get_query_plan(self, user_question: str, schemas_description: str) -> dict:
        system = SYSTEM_PROMPT.format(schemas=schemas_description)

        response = self.client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_question}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        raw = response.choices[0].message.content.strip()
        cleaned = self._strip_fences(raw)

        try:
            plan = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Model returned unparseable output: {e}\n\nRaw: {raw[:400]}")

        if not plan.get("sql", "").strip():
            raise ValueError("Model response did not include a SQL query.")

        plan.setdefault("mode", "chart")
        plan.setdefault("chart", None)
        plan.setdefault("note", "")

        explanation = plan.get("explanation")
        if not isinstance(explanation, dict):
            explanation = {}
        explanation.setdefault("columns_used", [])
        explanation.setdefault("aggregation", "")
        explanation.setdefault("reasoning", "")
        if not isinstance(explanation["columns_used"], list):
            explanation["columns_used"] = []
        explanation["columns_used"] = [
            c for c in explanation["columns_used"] if isinstance(c, dict) and c.get("column")
        ]
        plan["explanation"] = explanation

        if plan["mode"] == "table":
            plan["chart"] = None

        return plan

    # --------------------------------------------------------------- merge plan

    def get_merge_sql(self, user_description: str, schemas_description: str) -> str:
        system = MERGE_SYSTEM_PROMPT.format(schemas=schemas_description)

        response = self.client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_description}
            ],
            temperature=0.1
        )

        raw = response.choices[0].message.content.strip()
        sql = self._strip_fences(raw)
        return sql

    # ---------------------------------------------------------- key insights

    def get_key_insights(self, table_name: str, stats: dict) -> list[str]:
        """
        Turn a precomputed stats dict (see insights_engine.compute_table_stats)
        into a short list of plain-English "key insight" bullets. The LLM is
        only allowed to phrase numbers that are already in `stats`.
        """
        system = INSIGHTS_SYSTEM_PROMPT.format(
            table_name=table_name,
            stats=json.dumps(stats, default=str),
        )

        response = self.client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Give me the key insights for `{table_name}`."},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        cleaned = self._strip_fences(raw)

        try:
            data = json.loads(cleaned)
            insights = data.get("insights", [])
            if not isinstance(insights, list) or not insights:
                raise ValueError("no insights in response")
            return [str(x).strip() for x in insights if str(x).strip()][:6]
        except (json.JSONDecodeError, ValueError):
            # fall back to treating each non-empty line as a bullet
            lines = [ln.strip("-•* ").strip() for ln in cleaned.splitlines() if ln.strip()]
            return lines[:6] if lines else ["No insights could be generated for this table."]

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        return text.strip()
