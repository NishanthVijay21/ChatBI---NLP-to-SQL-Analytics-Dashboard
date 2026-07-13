"""
chart_component.py  — v4
"""

import json
import streamlit.components.v1 as components

COMPONENT_HEIGHT = 430 

MARK_LABELS = {
    "bar": "Bar Chart",
    "line": "Line Chart",
    "point": "Scatter Plot",
    "circle": "Scatter Plot",
    "square": "Scatter Plot",
    "area": "Area Chart",
    "arc": "Pie / Donut Chart",
    "boxplot": "Box Plot",
    "tick": "Tick Chart",
    "rule": "Rule Chart",
    "text": "Text Chart",
    "geoshape": "Map",
    "trail": "Trail Chart",
}


def describe_chart_type(mode: str, chart_spec: dict | None) -> str:
    """
    Human-readable visualization label for the Explainability panel — derived
    straight from the Vega-Lite spec's "mark" so it always matches what's
    actually rendered, rather than trusting the LLM to name it consistently.
    """
    if mode != "chart" or not chart_spec:
        return "Table (no chart)"

    mark = chart_spec.get("mark")
    mark_type = mark.get("type", "") if isinstance(mark, dict) else (mark or "")
    mark_type = str(mark_type).lower().strip()

    if not mark_type:
        return "Chart"
    return MARK_LABELS.get(mark_type, f"{mark_type.title()} Chart")


def render_chart(spec: dict, chart_id: str, title: str = "") -> None:
    spec_json = json.dumps(spec)
    safe_title = title.replace('"', "'").replace("\\", "")[:60]

    html = (
        '<!DOCTYPE html>\n'
        '<html>\n'
        '<head>\n'
        '<meta charset="utf-8"/>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>\n'
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>\n'
        '<style>\n'
        '  * { box-sizing: border-box; margin: 0; padding: 0; }\n'
        '  html, body { width: 100%; height: 100%; background: transparent;\n'
        '               font-family: -apple-system, sans-serif; }\n'
        '  #chart-wrap { width: 100%; padding: 0 8px; }\n'
        '  .toolbar { display: flex; gap: 6px; margin-top: 10px;\n'
        '             flex-wrap: wrap; align-items: center; }\n'
        '  .toolbar span { font-size: 11px; color: #888; margin-right: 2px; }\n'
        '  button { font-size: 11px; padding: 4px 11px; border: 1px solid #ccc;\n'
        '           background: #fff; cursor: pointer; border-radius: 3px; color: #333; }\n'
        '  button:hover { background: #f0f0f0; border-color: #999; }\n'
        '  button.primary { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }\n'
        '  button.primary:hover { background: #333; }\n'
        '  #status { font-size: 11px; color: #666; margin-top: 5px; min-height: 16px; }\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '<div id="chart-wrap">\n'
        '  <div id="CHART_ID_PLACEHOLDER"></div>\n'
        '  <div class="toolbar">\n'
        '    <span>Export:</span>\n'
        '    <button class="primary" onclick="exportPNG()">&#11015; PNG</button>\n'
        '    <button onclick="exportSVG()">&#11015; SVG</button>\n'
        '    <button onclick="exportSinglePDF()">&#11015; PDF</button>\n'
        '  </div>\n'
        '  <div id="status"></div>\n'
        '</div>\n'
        '\n'
        '<script>\n'
        'const SPEC = SPEC_JSON_PLACEHOLDER;\n'
        'const CHART_TITLE = "CHART_TITLE_PLACEHOLDER";\n'
        'const CHART_DIV_ID = "CHART_ID_PLACEHOLDER";\n'
        'let vegaView = null;\n'
        '\n'
        '// Measure the real iframe pixel width so Vega gets a concrete number.\n'
        '// width:"container" silently renders 0px wide inside Streamlit iframes.\n'
        'function iframeWidth() {\n'
        '  return (document.documentElement.clientWidth\n'
        '       || document.body.clientWidth\n'
        '       || 720) - 16;\n'
        '}\n'
        '\n'
        'function embedChart() {\n'
        '  const w = iframeWidth();\n'
        '  SPEC.width   = w;\n'
        '  SPEC.height  = 310;\n'
        '  SPEC.autosize = { type: "fit", contains: "padding" };\n'
        '\n'
        '  vegaEmbed("#" + CHART_DIV_ID, SPEC, {\n'
        '    actions: false,\n'
        '    renderer: "svg"\n'
        '  }).then(result => {\n'
        '    vegaView = result.view;\n'
        '    // Re-measure once the layout settles\n'
        '    setTimeout(() => {\n'
        '      const w2 = iframeWidth();\n'
        '      if (vegaView && Math.abs(w2 - w) > 20) {\n'
        '        vegaView.width(w2).run();\n'
        '      }\n'
        '    }, 350);\n'
        '  }).catch(err => {\n'
        '    setStatus("Chart error: " + err.message);\n'
        '    console.error("vegaEmbed:", err);\n'
        '  });\n'
        '}\n'
        '\n'
        '// Run after DOM is ready\n'
        'if (document.readyState === "loading") {\n'
        '  document.addEventListener("DOMContentLoaded", embedChart);\n'
        '} else {\n'
        '  embedChart();\n'
        '}\n'
        '\n'
        'function setStatus(msg) {\n'
        '  document.getElementById("status").textContent = msg;\n'
        '}\n'
        '\n'
        '// Blob-based download — bare data: URLs >2 MB are silently dropped by browsers\n'
        'function blobDownload(dataUrl, filename) {\n'
        '  return fetch(dataUrl)\n'
        '    .then(r => r.blob())\n'
        '    .then(blob => {\n'
        '      const url = URL.createObjectURL(blob);\n'
        '      const a = document.createElement("a");\n'
        '      a.href = url; a.download = filename;\n'
        '      document.body.appendChild(a); a.click(); document.body.removeChild(a);\n'
        '      setTimeout(() => URL.revokeObjectURL(url), 2000);\n'
        '    });\n'
        '}\n'
        '\n'
        'function safeFilename(s) {\n'
        '  return (s || "chart").replace(/[^a-z0-9]/gi, "_").slice(0, 50);\n'
        '}\n'
        '\n'
        'async function exportPNG() {\n'
        '  if (!vegaView) { setStatus("Chart not ready."); return; }\n'
        '  setStatus("Generating PNG\u2026");\n'
        '  try {\n'
        '    const dataUrl = await vegaView.toImageURL("png", 2);\n'
        '    await blobDownload(dataUrl, safeFilename(CHART_TITLE) + ".png");\n'
        '    setStatus("PNG saved.");\n'
        '  } catch(e) { setStatus("PNG failed: " + e.message); }\n'
        '}\n'
        '\n'
        'async function exportSVG() {\n'
        '  if (!vegaView) { setStatus("Chart not ready."); return; }\n'
        '  setStatus("Generating SVG\u2026");\n'
        '  try {\n'
        '    const svgStr = await vegaView.toSVG();\n'
        '    const blob = new Blob([svgStr], { type: "image/svg+xml" });\n'
        '    const url = URL.createObjectURL(blob);\n'
        '    const a = document.createElement("a");\n'
        '    a.href = url; a.download = safeFilename(CHART_TITLE) + ".svg";\n'
        '    document.body.appendChild(a); a.click(); document.body.removeChild(a);\n'
        '    setTimeout(() => URL.revokeObjectURL(url), 2000);\n'
        '    setStatus("SVG saved.");\n'
        '  } catch(e) { setStatus("SVG failed: " + e.message); }\n'
        '}\n'
        '\n'
        'async function exportSinglePDF() {\n'
        '  if (!vegaView) { setStatus("Chart not ready."); return; }\n'
        '  setStatus("Generating PDF\u2026");\n'
        '  try {\n'
        '    const dataUrl = await vegaView.toImageURL("png", 2);\n'
        '    const img = new Image();\n'
        '    img.src = dataUrl;\n'
        '    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });\n'
        '    const { jsPDF } = window.jspdf;\n'
        '    const W = img.naturalWidth || img.width;\n'
        '    const H = img.naturalHeight || img.height;\n'
        '    const ori = W >= H ? "landscape" : "portrait";\n'
        '    const pdf = new jsPDF({ orientation: ori, unit: "px",\n'
        '                            format: [W, H], compress: true });\n'
        '    pdf.addImage(dataUrl, "PNG", 0, 0, W, H);\n'
        '    pdf.save(safeFilename(CHART_TITLE) + ".pdf");\n'
        '    setStatus("PDF saved.");\n'
        '  } catch(e) { setStatus("PDF failed: " + e.message); }\n'
        '}\n'
        '</script>\n'
        '</body>\n'
        '</html>'
    )

    html = html.replace("CHART_ID_PLACEHOLDER", chart_id)
    html = html.replace("SPEC_JSON_PLACEHOLDER", spec_json)
    html = html.replace("CHART_TITLE_PLACEHOLDER", safe_title)

    components.html(html, height=COMPONENT_HEIGHT, scrolling=False)


def render_dashboard_export_button(chart_specs_with_titles: list) -> None:
    """
    Renders a single 'Export all charts as PDF' button.
    Receives list of {"spec": {...}, "title": "..."} from Python session state.
    Renders each chart in a hidden off-screen div inside this component's own
    iframe — no cross-iframe communication, no window.parent needed.
    """
    if not chart_specs_with_titles:
        return

    payload_json = json.dumps(chart_specs_with_titles)
    n = len(chart_specs_with_titles)

    html = (
        '<!DOCTYPE html>\n'
        '<html>\n'
        '<head>\n'
        '<meta charset="utf-8"/>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>\n'
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>\n'
        '<style>\n'
        '  * { box-sizing: border-box; margin: 0; padding: 0; }\n'
        '  body { font-family: -apple-system, sans-serif; background: transparent; padding: 4px 0; }\n'
        '  button { font-size: 13px; padding: 9px 18px; background: #1a1a1a;\n'
        '           color: #fff; border: none; cursor: pointer;\n'
        '           border-radius: 3px; width: 100%; }\n'
        '  button:hover { background: #333; }\n'
        '  button:disabled { background: #888; cursor: not-allowed; }\n'
        '  #status { font-size: 11px; color: #555; margin-top: 6px;\n'
        '            text-align: center; min-height: 16px; }\n'
        '  #hidden-render { position: fixed; left: -9999px; top: 0;\n'
        '                   width: 800px; visibility: hidden; }\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '<button id="exportBtn" onclick="exportDashboard()">N_PLACEHOLDER chart(s) &#11015; Export all as PDF dashboard</button>\n'
        '<div id="status"></div>\n'
        '<div id="hidden-render"></div>\n'
        '<script>\n'
        'const CHARTS = PAYLOAD_PLACEHOLDER;\n'
        '\n'
        'function setStatus(msg) { document.getElementById("status").textContent = msg; }\n'
        '\n'
        'async function renderSpecToPNG(spec, idx) {\n'
        '  const wrap = document.createElement("div");\n'
        '  wrap.id = "tmp_" + idx;\n'
        '  wrap.style.cssText = "width:800px;height:430px;display:block;";\n'
        '  document.getElementById("hidden-render").appendChild(wrap);\n'
        '\n'
        '  const s = JSON.parse(JSON.stringify(spec));\n'
        '  s.width  = 780;\n'
        '  s.height = 400;\n'
        '  s.autosize = { type: "fit", contains: "padding" };\n'
        '\n'
        '  const result = await vegaEmbed("#tmp_" + idx, s, {\n'
        '    actions: false,\n'
        '    renderer: "svg"\n'
        '  });\n'
        '  await result.view.runAsync();\n'
        '  const dataUrl = await result.view.toImageURL("png", 2);\n'
        '  wrap.remove();\n'
        '  return dataUrl;\n'
        '}\n'
        '\n'
        'async function exportDashboard() {\n'
        '  const btn = document.getElementById("exportBtn");\n'
        '  btn.disabled = true;\n'
        '  if (!CHARTS.length) { setStatus("No charts."); btn.disabled=false; return; }\n'
        '\n'
        '  const { jsPDF } = window.jspdf;\n'
        '  let pdf = null;\n'
        '\n'
        '  for (let i = 0; i < CHARTS.length; i++) {\n'
        '    const { spec, title } = CHARTS[i];\n'
        '    setStatus("Rendering " + (i+1) + " / " + CHARTS.length + ": \\"" + title.slice(0,40) + "\\"...");\n'
        '    try {\n'
        '      const dataUrl = await renderSpecToPNG(spec, i);\n'
        '      const img = new Image();\n'
        '      img.src = dataUrl;\n'
        '      await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });\n'
        '      const W = img.naturalWidth  || 800;\n'
        '      const H = img.naturalHeight || 400;\n'
        '      const pageH = H + 28;\n'
        '      const ori = W >= pageH ? "landscape" : "portrait";\n'
        '      if (!pdf) {\n'
        '        pdf = new jsPDF({ orientation: ori, unit: "px",\n'
        '                          format: [W, pageH], compress: true });\n'
        '      } else {\n'
        '        pdf.addPage([W, pageH], ori);\n'
        '      }\n'
        '      pdf.setFontSize(10); pdf.setTextColor(90,90,90);\n'
        '      pdf.text((title || ("Chart "+(i+1))).slice(0,90), 10, 16);\n'
        '      pdf.addImage(dataUrl, "PNG", 0, 28, W, H);\n'
        '    } catch(e) {\n'
        '      setStatus("Chart " + (i+1) + " failed: " + e.message + " — skipping.");\n'
        '      await new Promise(r => setTimeout(r, 600));\n'
        '    }\n'
        '  }\n'
        '\n'
        '  if (pdf) { pdf.save("querydeck_dashboard.pdf"); }\n'
        '  setStatus(pdf ? "Done \u2014 " + CHARTS.length + " chart(s) exported." : "Nothing exported.");\n'
        '  btn.disabled = false;\n'
        '}\n'
        '</script>\n'
        '</body>\n'
        '</html>'
    )

    html = html.replace("PAYLOAD_PLACEHOLDER", payload_json)
    html = html.replace("N_PLACEHOLDER", str(n))

    components.html(html, height=70, scrolling=False)
