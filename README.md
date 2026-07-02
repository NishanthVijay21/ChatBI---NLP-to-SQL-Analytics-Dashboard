# ChatBI---NLP-to-SQL-Analytics-Dashboard ◧
**Serverless NLP-to-SQL Analytics & Visualization Engine**

OmniQuery AI is a full-stack, AI-powered Business Intelligence copilot that allows users to query complex, multi-table datasets using plain English. It autonomously translates natural language into highly optimized DuckDB SQL and renders interactive Vega-Lite visualizations directly in the browser. 

Designed with performance and infrastructure cost in mind, OmniQuery utilizes a custom client-side rendering pipeline to generate multi-page PDF presentation dashboards with zero backend server bloat.

## ✨ Key Features
* **NLP-to-SQL Execution:** Powered by Cloudflare Workers AI (GLM-5.2), seamlessly translating conversational prompts into valid, read-only SQL queries.
* **In-Memory Data Engine:** Utilizes DuckDB for zero-latency cross-table joins, dynamic schema extraction, and instant aggregations.
* **Secure Query Sandbox:** Implements strict regex-based SQL validation to block prompt injection and destructive commands (DROP, DELETE, UPDATE).
* **Client-Side Rendering:** Bypasses framework iframe constraints using custom JavaScript (`window.parent`) to render charts and stitch multi-page PDFs directly in the browser, eliminating heavy server-side graphics processing.
* **Dynamic Data Workspaces:** Clean, filter, or merge uploaded CSV/Excel files and instantly save the transformed outputs as new, queryable baseline datasets.

## 🛠️ Tech Stack
* **Frontend:** Streamlit, JavaScript, HTML/CSS, jsPDF
* **Visualization:** Vega-Lite, Vega-Embed
* **Backend:** Python 3, DuckDB, Pandas
* **AI / LLM:** Cloudflare Workers AI (GLM-5.2), OpenAI Python SDK
