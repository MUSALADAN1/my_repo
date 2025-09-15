# bot_core/analytics/report.py
"""
Interactive HTML Backtest Report Generator (Plotly inline)

Reads:
 - folder/metrics.json
 - folder/trade_log.csv
 - folder/equity_curve.csv
 - optional images: equity_curve.png, drawdown.png, strategy_equity_curves.png

Produces: folder/report.html with interactive Plotly charts + searchable trade table + CSV/JSON download.
"""
from typing import Dict, Any, Optional
import os
import json
import pandas as pd
import string

# ---------------------- HTML template (use $ placeholders for string.Template) ----------------------
TEMPLATE_STR = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Backtest Report - $title</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    :root{
      --bg:#0f1724; --card:#0b1220; --muted:#94a3b8; --accent:#06b6d4;
      --good:#16a34a; --bad:#ef4444; --text:#e6eef6; --glass: rgba(255,255,255,0.02);
      --radius:12px;
    }
    html,body{height:100%;margin:0;background:linear-gradient(180deg,#071226 0%, #031226 100%);color:var(--text);font-family:Inter, "Segoe UI", Roboto, Arial, sans-serif;}
    .container{max-width:1200px;margin:22px auto;padding:18px;background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));border-radius:14px;box-shadow:0 8px 30px rgba(2,6,23,0.6);}
    header{display:flex;align-items:center;justify-content:space-between;gap:12px}
    h1{margin:0;font-size:1.25rem}
    .meta{color:var(--muted);font-size:0.9rem}
    .grid{display:grid;grid-template-columns: 1fr 420px;gap:20px;margin-top:18px;}
    .card{background:var(--card);padding:14px;border-radius:var(--radius);box-shadow:0 6px 18px rgba(2,6,23,0.6);border:1px solid rgba(255,255,255,0.02);}
    .metrics table{width:100%;border-collapse:collapse}
    .metrics th{background:transparent;color:var(--muted);text-transform:uppercase;font-size:0.75rem;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.03)}
    .metrics td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.02);color:var(--text)}
    .img-wrap img{width:100%;height:auto;border-radius:8px;border:1px solid rgba(255,255,255,0.03)}
    .small{font-size:0.85rem;color:var(--muted)}
    .controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
    input.search{padding:8px;border-radius:8px;border:1px solid rgba(255,255,255,0.04);background:transparent;color:var(--text);min-width:220px}
    select.filter{padding:8px;border-radius:8px;border:1px solid rgba(255,255,255,0.04);background:transparent;color:var(--text)}
    button.btn{padding:8px 10px;border-radius:8px;border:none;background:var(--accent);color:#012;cursor:pointer;font-weight:600}
    .flex{display:flex;gap:8px;align-items:center}
    table.report{width:100%;border-collapse:collapse;font-size:0.92rem}
    table.report thead th{padding:8px;border-bottom:1px solid rgba(255,255,255,0.03);text-align:left}
    table.report td{padding:8px;border-bottom:1px solid rgba(255,255,255,0.03)}
    .pos{color:var(--good);font-weight:600}
    .neg{color:var(--bad);font-weight:600}
    @media (max-width:980px){ .grid{grid-template-columns:1fr} .controls{flex-direction:column;align-items:stretch} }
    .spark { height: 36px; width: 120px; display:inline-block; vertical-align:middle; }
  </style>
  <!-- Plotly CDN -->
  <script src="https://cdn.plot.ly/plotly-2.29.1.min.js"></script>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Backtest Report — $title</h1>
        <div class="meta">Generated at: $ts</div>
      </div>
      <div class="flex">
        <div class="small">Equity points: <strong>$equity_count</strong></div>
        <div class="small">Trades: <strong>$trade_count</strong></div>
      </div>
    </header>

    <div class="grid">
      <div class="card metrics">
        <h2>Key metrics</h2>
        <div class="section">
          <table>
            <tbody>
              $metrics_rows
            </tbody>
          </table>
        </div>

        <div class="section">
          <h3>Per-strategy performance</h3>
          <div class="img-wrap small">$strategy_img</div>
          <div style="height:12px"></div>
          $per_strategy_table
        </div>
      </div>

      <div class="card">
        <h2>Interactive Charts</h2>
        <div id="equity_plot" style="height:260px;"></div>
        <div style="height:8px"></div>
        <div id="drawdown_plot" style="height:160px;"></div>
        <div style="height:8px"></div>
        <div id="strategy_plot" style="height:240px;"></div>

        <div class="section">
          <h3>Trade Log</h3>
          <div class="controls">
            <input class="search" id="searchBox" placeholder="Search trades (strategy, type, symbol)..." />
            <select id="strategyFilter" class="filter">
              <option value="">All strategies</option>
              $strategy_options
            </select>
            <button class="btn" id="resetBtn">Reset</button>
            <div style="flex:1"></div>
            <a class="btn" id="downloadCSV" href="$trade_log_path" download>Download CSV</a>
            <button class="btn" id="downloadJSON">Download JSON</button>
          </div>

          <div id="tradeTableWrap">$trade_table</div>
        </div>
      </div>
    </div>

    <footer style="margin-top:18px;color:var(--muted);font-size:0.86rem">
      Generated by your trading bot framework.
    </footer>
  </div>

<script>
/* Embedded JSON data (populated by server-side) */
const EQUITY_SERIES = __EQUITY_JSON__;
const DRAWDOWN_SERIES = __DRAWDOWN_JSON__;
const PER_STRATEGY = __STRATEGY_JSON__;

/* Plot equity curve */
function renderEquity() {
  const x = EQUITY_SERIES.map(p => p.ts);
  const y = EQUITY_SERIES.map(p => p.value);
  const trace = { x, y, mode: 'lines+markers', name: 'Equity', line: {width:2}, hovertemplate: '%{x}<br>Equity: %{y:.2f}<extra></extra>' };
  const layout = { margin:{t:10,l:40,r:20,b:40}, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)' };
  Plotly.newPlot('equity_plot', [trace], layout, {responsive:true});
}

/* Plot drawdown */
function renderDrawdown() {
  const x = DRAWDOWN_SERIES.map(p => p.ts);
  const y = DRAWDOWN_SERIES.map(p => p.value);
  const trace = { x, y, fill:'tozeroy', name:'Drawdown', hovertemplate:'%{x}<br>Drawdown: %{y:.4f}<extra></extra>' };
  const layout = { margin:{t:10,l:40,r:20,b:40}, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)' };
  Plotly.newPlot('drawdown_plot', [trace], layout, {responsive:true});
}

/* Combined per-strategy multi-line chart */
function renderStrategyCombined() {
  const traces = [];
  for (const [k, series] of Object.entries(PER_STRATEGY)) {
    if (!Array.isArray(series) || series.length === 0) continue;
    const x = series.map(p => p.ts);
    const y = series.map(p => p.value);
    traces.push({ x, y, mode: 'lines', name: k, hovertemplate: '%{x}<br>%{y:.6f}<extra>' + k + '</extra>' });
  }
  if(traces.length === 0) {
    const el = document.getElementById('strategy_plot');
    if(el) el.innerHTML = '<div class="small">No per-strategy series found.</div>';
    return;
  }
  const layout = { margin:{t:20,l:40,r:20,b:40}, legend:{orientation:'h'}, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)' };
  Plotly.newPlot('strategy_plot', traces, layout, {responsive:true});
}

/* small sparklines per-strategy */
function renderSparklines() {
  for (const [strat, series] of Object.entries(PER_STRATEGY)) {
    const container = document.getElementById('spark_' + strat);
    if(!container) continue;
    if(!(Array.isArray(series) && series.length>0)) continue;
    const trace = { x: series.map(p=>p.ts), y: series.map(p=>p.value), mode:'lines', hoverinfo:'none', line:{width:1} };
    Plotly.newPlot(container, [trace], {margin:{t:2,l:2,r:2,b:2}, xaxis:{visible:false}, yaxis:{visible:false}}, {staticPlot:true,responsive:false});
  }
}

/* UI: search/filter and JSON download */
function initUI() {
  const searchBox = document.getElementById("searchBox");
  const strategyFilter = document.getElementById("strategyFilter");
  const resetBtn = document.getElementById("resetBtn");
  const tableWrap = document.getElementById("tradeTableWrap");
  const jsonBtn = document.getElementById("downloadJSON");
  if(!tableWrap) return;
  const table = tableWrap.querySelector("table");
  if(!table) return;

  function renderFiltered(){
    const q = (searchBox.value || "").toLowerCase();
    const strat = (strategyFilter.value || "").toLowerCase();
    const rows = table.querySelectorAll("tbody tr");
    rows.forEach(r=>{
      const text = r.innerText.toLowerCase();
      const matchQ = !q || text.indexOf(q) !== -1;
      const matchStrat = !strat || (r.getAttribute("data-strategy")||"").toLowerCase() === strat;
      r.style.display = (matchQ && matchStrat) ? "" : "none";
    });
  }

  searchBox.addEventListener("input", renderFiltered);
  strategyFilter.addEventListener("change", renderFiltered);
  resetBtn.addEventListener("click", ()=>{ searchBox.value=""; strategyFilter.value=""; renderFiltered(); });

  jsonBtn.addEventListener("click", function(){
    const rows = Array.from(table.querySelectorAll("tbody tr")).filter(r => r.style.display !== "none");
    const headers = Array.from(table.querySelectorAll("thead th")).map(h => h.innerText);
    const data = rows.map(r => {
      const cells = Array.from(r.querySelectorAll("td"));
      const obj = {};
      cells.forEach((c,i)=> obj[headers[i]] = c.innerText);
      return obj;
    });
    const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "$title-trade_log.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });
}

document.addEventListener("DOMContentLoaded", function(){
  try { renderEquity(); } catch(e){}
  try { renderDrawdown(); } catch(e){}
  try { renderStrategyCombined(); } catch(e){}
  try { renderSparklines(); } catch(e){}
  try { initUI(); } catch(e){}
});
</script>
</body>
</html>
"""

# ---------------------- Helper functions ----------------------

def _render_metrics_table(metrics: Dict[str, Any]) -> str:
    if not metrics:
        return "<tr><td colspan='2'>No metrics found</td></tr>"
    rows = []
    for k in sorted(metrics.keys()):
        v = metrics[k]
        rows.append(f"<tr><th class='k'>{k}</th><td>{v}</td></tr>")
    return "\n".join(rows)


def _render_trade_table(trade_csv_path: str, max_rows: int = 200) -> str:
    if not os.path.exists(trade_csv_path):
        return "<p class='small'>No trade log found.</p>"
    try:
        df = pd.read_csv(trade_csv_path)
    except Exception as e:
        return f"<p class='small'>Failed to read trade log: {e}</p>"

    if df.empty:
        return "<p class='small'>Trade log is empty.</p>"

    df_show = df.head(max_rows)
    html = ["<table class='report'><thead><tr>"]
    for c in df_show.columns:
        html.append(f"<th>{c}</th>")
    html.append("</tr></thead><tbody>")
    for _, row in df_show.iterrows():
        strat_attr = row.get("strategy", "")
        html.append(f"<tr data-strategy=\"{strat_attr}\">")
        for c in df_show.columns:
            cell = row.get(c, "")
            html.append(f"<td>{cell}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    return "\n".join(html)


def _render_per_strategy_table(per_strategy: Optional[Dict[str, Dict[str, Any]]]) -> str:
    """Return HTML table for per-strategy metrics and include a spark div for each strategy."""
    if not per_strategy:
        return "<p class='small'>No per-strategy data available.</p>"
    html = ["<table class='report'><thead><tr>",
            "<th>Strategy</th><th>Trades</th><th>Total PnL</th><th>Win %</th><th>Avg Win</th><th>Avg Loss</th><th>Gross Profit</th><th>Gross Loss</th><th>Spark</th>",
            "</tr></thead><tbody>"]
    for strat, s in sorted(per_strategy.items(), key=lambda kv: (kv[0] if isinstance(kv, tuple) else kv)):
        if isinstance(s, dict):
            num = int(s.get("num_trades", 0) or 0)
            total_pnl = float(s.get("total_pnl", 0.0) or 0.0)
            wins = int(s.get("num_wins", s.get("wins", 0) or 0))
            losses = int(s.get("num_losses", s.get("losses", 0) or 0))
            avg_win = float(s.get("avg_win", 0.0) or 0.0)
            avg_loss = float(s.get("avg_loss", 0.0) or 0.0)
            gross_profit = float(s.get("gross_profit", 0.0) or 0.0)
            gross_loss = float(s.get("gross_loss", 0.0) or 0.0)
        else:
            num = 0; total_pnl=0; wins=0; losses=0; avg_win=0; avg_loss=0; gross_profit=0; gross_loss=0

        win_pct = (wins / max(1, (wins + losses))) * 100.0 if (wins + losses) > 0 else 0.0
        safe_name = str(strat).replace(" ", "_").replace("/", "_").replace("\\", "_")
        html.append("<tr data-strategy=\"{}\">".format(str(safe_name)))
        html.append(f"<td>{str(strat)}</td>")
        html.append(f"<td>{num}</td>")
        html.append(f"<td class='pos' data-sort='{total_pnl:.6f}'>{total_pnl:.6f}</td>")
        html.append(f"<td>{win_pct:.1f}%</td>")
        html.append(f"<td>{avg_win:.6f}</td>")
        html.append(f"<td>{avg_loss:.6f}</td>")
        html.append(f"<td>{gross_profit:.6f}</td>")
        html.append(f"<td>{gross_loss:.6f}</td>")
        html.append(f"<td><div id='spark_{safe_name}' class='spark'></div></td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    return "\n".join(html)


def _build_equity_and_drawdown(folder: str):
    eq_path = os.path.join(folder, "equity_curve.csv")
    if not os.path.exists(eq_path):
        return [], []
    try:
        df = pd.read_csv(eq_path, index_col=0, parse_dates=True)
        col = df.columns[0] if len(df.columns) > 0 else None
        if col is None:
            return [], []
        equity = df[col].astype(float).ffill().ffill().fillna(0.0)
        equity.index = pd.to_datetime(equity.index)
        equity_points = [{"ts": idx.isoformat(), "value": float(v)} for idx, v in equity.items()]
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, 1.0)
        dd_points = [{"ts": idx.isoformat(), "value": float(v)} for idx, v in dd.items()]
        return equity_points, dd_points
    except Exception:
        return [], []


def _build_per_strategy_series(folder: str, equity_timestamps: list) -> Dict[str, list]:
    trade_csv = os.path.join(folder, "trade_log.csv")
    if not os.path.exists(trade_csv):
        return {}
    try:
        df = pd.read_csv(trade_csv, parse_dates=["time"], low_memory=False)
    except Exception:
        try:
            df = pd.read_csv(trade_csv, low_memory=False)
        except Exception:
            return {}

    if "pnl" not in df.columns:
        df["pnl"] = 0.0

    if "strategy" not in df.columns:
        df["strategy"] = "unknown"

    try:
        equity_idx = pd.to_datetime(equity_timestamps) if equity_timestamps else pd.DatetimeIndex([])
    except Exception:
        equity_idx = pd.DatetimeIndex([])

    result = {}
    groups = df.groupby("strategy")
    for strat, g in groups:
        if "time" in g.columns:
            g_sorted = g.sort_values("time")
            trade_series = pd.Series(data=g_sorted["pnl"].astype(float).values, index=pd.to_datetime(g_sorted["time"]))
            trade_cum = trade_series.groupby(level=0).sum().cumsum()
            if not equity_idx.empty:
                re = trade_cum.reindex(equity_idx, method="ffill").fillna(0.0)
                arr = [{"ts": idx.isoformat(), "value": float(v)} for idx, v in zip(re.index, re.values)]
            else:
                arr = [{"ts": t.isoformat(), "value": float(v)} for t, v in zip(pd.to_datetime(g_sorted["time"]), trade_cum.values)]
        else:
            g_sorted = g.reset_index(drop=True)
            csum = g_sorted["pnl"].astype(float).cumsum()
            arr = [{"ts": str(i), "value": float(v)} for i, v in enumerate(csum)]
        safe_name = str(strat).replace(" ", "_").replace("/", "_").replace("\\", "_")
        result[safe_name] = arr
    return result


def generate_html_report(folder: str = "demo_results", out_filename: Optional[str] = None) -> str:
    folder = os.path.abspath(folder)
    if out_filename is None:
        out_filename = os.path.join(folder, "report.html")
    else:
        out_filename = os.path.abspath(out_filename)

    metrics_path = os.path.join(folder, "metrics.json")
    trade_csv = os.path.join(folder, "trade_log.csv")
    equity_png = os.path.join(folder, "equity_curve.png")
    drawdown_png = os.path.join(folder, "drawdown.png")
    strategy_png = os.path.join(folder, "strategy_equity_curves.png")

    metrics = {}
    if os.path.exists(metrics_path):
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        except Exception:
            metrics = {}

    metrics_rows_html = _render_metrics_table(metrics)
    equity_img_tag = f"<img src='{os.path.basename(equity_png)}' alt='Equity curve' />" if os.path.exists(equity_png) else "<p class='small'>No equity image found.</p>"
    drawdown_img_tag = f"<img src='{os.path.basename(drawdown_png)}' alt='Drawdown' />" if os.path.exists(drawdown_png) else "<p class='small'>No drawdown image found.</p>"
    strategy_img_tag = f"<img src='{os.path.basename(strategy_png)}' alt='Strategy curves' />" if os.path.exists(strategy_png) else "<p class='small'>No per-strategy curve image found. Run scripts/plot_strategy_curves.py to generate.</p>"

    trade_table_html = _render_trade_table(trade_csv)

    equity_count = metrics.get("equity_points") if isinstance(metrics, dict) and "equity_points" in metrics else ""
    try:
        if (not equity_count) and os.path.exists(os.path.join(folder, "equity_curve.csv")):
            equity_count = len(pd.read_csv(os.path.join(folder, "equity_curve.csv"), index_col=0))
    except Exception:
        equity_count = equity_count or ""
    trade_count = metrics.get("num_trades") if isinstance(metrics, dict) and "num_trades" in metrics else ""
    try:
        if (not trade_count) and os.path.exists(trade_csv):
            trade_count = len(pd.read_csv(trade_csv))
    except Exception:
        trade_count = trade_count or ""

    equity_points, dd_points = _build_equity_and_drawdown(folder)
    equity_json = json.dumps(equity_points)
    dd_json = json.dumps(dd_points)

    equity_ts = [p["ts"] for p in equity_points] if equity_points else []
    per_strategy_series = _build_per_strategy_series(folder, equity_ts)
    strategy_json = json.dumps(per_strategy_series)

    strategy_options_html = ""
    for strat in sorted(per_strategy_series.keys()):
        strategy_options_html += f"<option value=\"{strat}\">{strat}</option>\n"

    per_strategy_html = _render_per_strategy_table(metrics.get("per_strategy") if isinstance(metrics, dict) else None)

    mapping = {
        "title": os.path.basename(folder),
        "ts": pd.Timestamp.now().isoformat(),
        "metrics_rows": metrics_rows_html,
        "strategy_img": strategy_img_tag,
        "per_strategy_table": per_strategy_html,
        "strategy_options": strategy_options_html,
        "equity_count": equity_count,
        "trade_count": trade_count,
        "trade_log_path": trade_csv,
        "trade_table": trade_table_html
    }

    tmpl = string.Template(TEMPLATE_STR)
    html = tmpl.safe_substitute(mapping)

    # embed JSON into the placeholders
    html = html.replace("__EQUITY_JSON__", equity_json).replace("__DRAWDOWN_JSON__", dd_json).replace("__STRATEGY_JSON__", strategy_json)

    os.makedirs(os.path.dirname(out_filename), exist_ok=True)
    with open(out_filename, "w", encoding="utf-8") as f:
        f.write(html)

    return out_filename
