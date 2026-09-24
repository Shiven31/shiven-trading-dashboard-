"""Fast 5-minute, 15-minute and 1-hour GOX25-Z25 strategy dashboard.

Place this file, GOX25_Z25_order_block_backtest.py, and the parquet file in the
same folder. Run this file and open http://127.0.0.1:8050.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from time import time

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dash_table, dcc, html, no_update

from ab import Strategy


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_FILES = {
    "5m": ["GOX25-Z25_5 min.parquet", "GOX25-Z25_5min.parquet"],
    "15m": ["GOX25-Z25_15 min.parquet", "GOX25-Z25_15min.parquet"],
    "1h": ["GOX25-Z25_1 hour.parquet", "GOX25-Z25_1hr.parquet", "GOX25-Z25_60 min.parquet"],
}
TIMEFRAMES = {"5m": 5, "15m": 15, "1h": 60}
WINDOWS = {"500 candles": 500, "2,000 candles": 2000,
           "5,000 candles": 5000, "Entire history": None}
LOOKBACK_OPTIONS = ([{"label": "Entire available history", "value": "ALL"}] +
                    [{"label": f"Last {month} month" + ("" if month == 1 else "s"),
                      "value": str(month)} for month in range(1, 11)])
STRATEGIES = {
    "ORDER_BLOCK": {"label": "Order Block (current strategy)", "engine": Strategy},
}
BASE_PARAMETERS = {"Tick_Size": 0.25, "Tick_Value": 25.0, "Fees": 2.0, "Lots": 1}
PRODUCT_PRESETS = {
    "GOX (current)": (0.25, 25.0),
    "Brent / CL": (0.01, 10.0),
    "RB / HO": (0.0001, 4.5),
    "Custom": None,
}
CACHE = {
    "raw": {}, "results": {}, "sources": {}, "chart_frames": {}, "figures": {},
    "version": 0, "tick_size": 0.25, "tick_value": 25.0,
}

COLORS = {
    "navy": "#183B56", "blue": "#1479FF", "green": "#159A6C",
    "red": "#D64545", "purple": "#7B61A8", "orange": "#EF8A17",
    "muted": "#657786",
}


def normalize_ohlc(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = {"time", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return (df.dropna(subset=["time", "open", "high", "low", "close"])
              .sort_values("time").drop_duplicates("time", keep="last"))


def process_timeframe(data: pd.DataFrame, label: str, source: str,
                      tick_size: float, tick_value: float,
                      minimum_move_ticks: float, maximum_move_ticks: float,
                      lots: int, partial_mode: str, partial_percentages,
                      partial_interval_ticks: float, trailing_enabled: bool,
                      exclude_overnight: bool, strategy_key: str = "ORDER_BLOCK",
                      lookback_months: str = "ALL"):
    """Run one native-timeframe file without resampling it."""
    candles = normalize_ohlc(data).reset_index(drop=True)
    if candles.empty:
        raise ValueError("The selected file has no valid OHLC candles")
    full_start, full_end = candles["time"].min(), candles["time"].max()
    if lookback_months != "ALL":
        cutoff = full_end - pd.DateOffset(months=int(lookback_months))
        candles = candles.loc[candles["time"] >= cutoff].reset_index(drop=True)
    if len(candles) < 2:
        raise ValueError("The selected lookback period contains fewer than two valid candles")
    if strategy_key not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy_key}")
    parameters = {
        **BASE_PARAMETERS,
        "Tick_Size": float(tick_size),
        "Tick_Value": float(tick_value),
        "Minimum_Move_Ticks": float(minimum_move_ticks),
        "Maximum_Move_Ticks": float(maximum_move_ticks),
        "Lots": int(lots),
        "Partial_Mode": partial_mode,
        "Partial_Target_Percentages": partial_percentages or [],
        "Partial_Interval_Ticks": float(partial_interval_ticks),
        "Trailing_SL_Enabled": bool(trailing_enabled),
        "Exclude_Overnight_Trades": bool(exclude_overnight),
    }
    engine = STRATEGIES[strategy_key]["engine"]
    bars, trades, equity, stats = engine(parameters, {}, candles).StrategyBuilder()
    if not trades.empty:
        trades = trades.copy()
        trades.insert(0, "timeframe", label)
        trades["id"] = label + "-" + trades["trade_id"].astype(int).astype(str)
    stats = stats.copy()
    stats.insert(0, "timeframe", label)
    stats.insert(1, "strategy", STRATEGIES[strategy_key]["label"])
    stats.insert(2, "lookback_months", lookback_months)
    stats["full_data_start"] = full_start
    stats["full_data_end"] = full_end
    CACHE["results"][label] = {"bars": bars, "trades": trades, "equity": equity, "stats": stats}
    CACHE["raw"][label] = data.copy()
    CACHE["sources"][label] = source
    CACHE["tick_size"] = float(tick_size)
    CACHE["tick_value"] = float(tick_value)
    CACHE["chart_frames"].clear()
    CACHE["figures"].clear()
    CACHE["version"] = int(time() * 1000)
    return CACHE["version"]


def empty_figure(message="Load a parquet file to begin."):
    fig = go.Figure()
    fig.add_annotation(text=message, x=.5, y=.5, xref="paper", yref="paper",
                       showarrow=False, font={"size": 16, "color": COLORS["muted"]})
    fig.update_layout(template="plotly_dark", paper_bgcolor="#000000",
                      plot_bgcolor="#090909", height=680)
    return fig


def chart_bars_with_window(all_bars: pd.DataFrame, candle_limit):
    """Use sequential candle numbers so closed-market time disappears."""
    if all_bars.empty:
        return all_bars.copy(), None
    bars = all_bars.copy().reset_index(drop=True)
    bars["chart_x"] = range(len(bars))
    initial_range = None
    if candle_limit:
        initial_range = [max(-0.5, len(bars) - candle_limit - 0.5), len(bars) - 0.5]
    return bars, initial_range


def order_block_polygon_trace(frame, bullish):
    selected = frame.loc[frame["bull_order_block"] if bullish else frame["bear_order_block"]]
    if selected.empty:
        return None
    xs, ys = [], []
    for row in selected.itertuples():
        xs.extend([row.chart_x-0.45, row.chart_x+0.45, row.chart_x+0.45,
                   row.chart_x-0.45, row.chart_x-0.45, None])
        ys.extend([row.low, row.low, row.high, row.high, row.low, None])
    color = COLORS["green"] if bullish else COLORS["red"]
    fill = "rgba(21,154,108,.18)" if bullish else "rgba(214,69,69,.18)"
    return go.Scatter(x=xs, y=ys, mode="lines", fill="toself", fillcolor=fill,
                      line={"color": color, "width": 1}, hoverinfo="skip",
                      name="Bull order blocks" if bullish else "Bear order blocks")


def build_market_figure(label: str, candle_limit):
    result = CACHE["results"].get(label)
    if not result:
        return empty_figure()
    all_bars, all_trades = result["bars"], result["trades"]
    cache_key = (CACHE["version"], label, candle_limit)
    if cache_key in CACHE["figures"]:
        return CACHE["figures"][cache_key]
    if cache_key not in CACHE["chart_frames"]:
        CACHE["chart_frames"][cache_key] = chart_bars_with_window(all_bars, candle_limit)
    bars, initial_range = CACHE["chart_frames"][cache_key]
    if bars.empty:
        return empty_figure("No candles are available for this timeframe.")
    start, end = bars["time"].iloc[0], bars["time"].iloc[-1]

    candle_hover = (
        bars["time"].dt.strftime("%Y-%m-%d %H:%M")
        + "<br>Open: " + bars["open"].map(lambda value: f"{value:g}")
        + "<br>High: " + bars["high"].map(lambda value: f"{value:g}")
        + "<br>Low: " + bars["low"].map(lambda value: f"{value:g}")
        + "<br>Close: " + bars["close"].map(lambda value: f"{value:g}")
    )
    fig = go.Figure(go.Candlestick(
        x=bars.chart_x, open=bars.open, high=bars.high, low=bars.low, close=bars.close,
        text=candle_hover, hoverinfo="text",
        name=f"{CACHE['sources'].get(label, 'Market data')} {label}", increasing_line_color=COLORS["green"],
        decreasing_line_color=COLORS["red"],
    ))
    # A bar with O=H=L=C has no visible candle body or wick. Plot a small dot so
    # sparse trade-only files still show every genuine observation accurately.
    flat_mask = (bars["open"].eq(bars["high"]) & bars["high"].eq(bars["low"])
                 & bars["low"].eq(bars["close"]))
    if flat_mask.any():
        fig.add_trace(go.Scattergl(
            x=bars.loc[flat_mask, "chart_x"], y=bars.loc[flat_mask, "close"],
            mode="markers", name="One-price bars",
            marker={"size": 5, "color": "#F5B942", "opacity": .8},
            text=bars.loc[flat_mask, "time"].dt.strftime("%Y-%m-%d %H:%M"),
            hovertemplate="%{text}<br>O=H=L=C: %{y:g}<extra>One-price bar</extra>",
        ))
    for bullish in [True, False]:
        trace = order_block_polygon_trace(bars, bullish)
        if trace:
            fig.add_trace(trace)

    # One lightweight trace marks only the first available candle of each date.
    # This avoids treating every missing trade in a sparse file as a market open.
    trading_date = bars["time"].dt.normalize()
    reopen_mask = trading_date.ne(trading_date.shift(1))
    daily_opens = bars.loc[reopen_mask, "chart_x"]
    y_min, y_max = float(bars["low"].min()), float(bars["high"].max())
    open_x, open_y = [], []
    for open_time in daily_opens:
        open_x.extend([open_time, open_time, None])
        open_y.extend([y_min, y_max, None])
    fig.add_trace(go.Scatter(
        x=open_x, y=open_y, mode="lines", name="Daily market open",
        line={"color": "rgba(101,119,134,.45)", "width": 1, "dash": "dot"},
        hoverinfo="skip",
    ))

    if not all_trades.empty:
        trades = all_trades.copy()
        time_to_x = pd.Series(bars["chart_x"].values, index=bars["time"]).to_dict()
        marker_specs = [
            (trades.loc[trades.side == "LONG"], "entry_time", "entry_price", "Long entry", "triangle-up", COLORS["blue"]),
            (trades.loc[trades.side == "SHORT"], "entry_time", "entry_price", "Short entry", "triangle-down", COLORS["red"]),
            (trades, "exit_time", "exit_price", "Exit", "triangle-left", COLORS["purple"]),
        ]
        for frame, x_col, y_col, name, symbol, color in marker_specs:
            if frame.empty:
                continue
            marker_x = pd.to_datetime(frame[x_col]).map(time_to_x)
            valid = marker_x.notna()
            fig.add_trace(go.Scatter(
                x=marker_x.loc[valid], y=frame.loc[valid, y_col], mode="markers", name=name,
                marker={"symbol": symbol, "size": 11, "color": color,
                        "line": {"color": "white", "width": 1}},
                customdata=frame.loc[valid, ["id", x_col]].astype(str).values,
                hovertemplate="Trade %{customdata[0]}<br>%{customdata[1]}<br>Price %{y:.2f}<extra>"+name+"</extra>",
            ))

    visible_text = "entire history" if candle_limit is None else f"{candle_limit:,}-candle viewing window"
    # Keep enough date labels in every selected viewing window, even though all
    # candles remain loaded and scrollable in the range slider.
    tick_step = max(1, int((candle_limit or len(bars)) / 8))
    tick_values = list(range(0, len(bars), tick_step))
    if tick_values[-1] != len(bars) - 1:
        tick_values.append(len(bars) - 1)
    tick_text = bars.loc[tick_values, "time"].dt.strftime("%Y-%m-%d").tolist()
    raw = CACHE["raw"].get(label)
    raw_rows = len(raw) if raw is not None else len(bars)
    missing_rows = max(0, raw_rows - len(bars))
    quality_note = (f"{visible_text} · {missing_rows:,} blank OHLC rows excluded"
                    if missing_rows else visible_text)
    fig.update_layout(
        title={"text": f"{CACHE['sources'].get(label, 'Market data')} — {label}",
               "x": .01, "xanchor": "left", "y": .98, "yanchor": "top"},
        template="plotly_dark", paper_bgcolor="#000000", plot_bgcolor="#090909",
        font={"color": "#FFFFFF"}, height=700,
        hovermode="closest", uirevision=f"{CACHE['version']}-{label}-{candle_limit}",
        margin={"l": 55, "r": 190, "t": 90, "b": 55},
        xaxis={
            "rangeslider": {"visible": True, "bgcolor": "#111111"}, "type": "linear", "range": initial_range,
            "tickmode": "array", "tickvals": tick_values, "ticktext": tick_text,
            "title": "Continuous candle sequence (closed-market time removed)",
        },
        yaxis={"title": "Spread price", "gridcolor": "#333333"},
        legend={"orientation": "v", "y": 1, "x": 1.01, "xanchor": "left"},
    )
    fig.add_annotation(text=quality_note, x=.01, y=1.035, xref="paper", yref="paper",
                       showarrow=False, xanchor="left", font={"size": 11, "color": "#AEB9C7"})
    CACHE["figures"][cache_key] = fig
    return fig


def metrics(stats):
    if stats.empty:
        return []
    s = stats.iloc[0]
    values = [
        ("Full data start", pd.Timestamp(s.full_data_start).strftime("%Y-%m-%d")),
        ("Full data end", pd.Timestamp(s.full_data_end).strftime("%Y-%m-%d")),
        ("Backtest start", pd.Timestamp(s.data_start).strftime("%Y-%m-%d")),
        ("Backtest end", pd.Timestamp(s.data_end).strftime("%Y-%m-%d")),
        ("Net P&L", f"${s.net_pnl:,.0f}"), ("Win rate", f"{s.win_rate_pct:.2f}%"),
        ("Trades", f"{int(s.total_trades):,}"), ("TP / SL", f"{int(s.take_profit_hits)} / {int(s.stop_loss_hits)}"),
        ("Winning longs", f"{int(s.winning_long_trades):,}"),
        ("Winning shorts", f"{int(s.winning_short_trades):,}"),
        ("Max drawdown", f"${s.max_drawdown:,.0f}"),
        ("Sharpe", "N/A" if pd.isna(s.daily_sharpe_ratio) else f"{s.daily_sharpe_ratio:.2f}"),
        ("Largest profit", f"${s.max_trade_profit:,.0f}"), ("Largest loss", f"${s.max_trade_loss:,.0f}"),
        ("Win streak", f"{int(s.max_profit_streak)}"), ("Loss streak", f"{int(s.max_loss_streak)}"),
        ("Gross P&L", f"${s.gross_pnl:,.0f}"), ("Fees", f"${s.total_fees:,.0f}"),
        ("Order-block move", f"{s.minimum_move_ticks:g} to {s.maximum_move_ticks:g} ticks"),
        ("TP/SL ratio", "Fixed 1:1"),
        ("Lots", f"{int(s.lots)}"),
        ("Partial mode", str(s.partial_mode).title()),
        ("Partial bookings", f"{int(s.partial_bookings):,}"),
        ("Overnight trades removed", f"{int(s.overnight_trades_removed):,}"),
    ]
    return [html.Div([html.Div(a, className="metric-label"), html.Div(b, className="metric-value")],
                     className="metric-card") for a, b in values]


def trade_records(trades):
    if trades.empty:
        return []
    frame = trades.copy()
    for col in ["signal_time", "entry_time", "partial_exit_time", "exit_time"]:
        frame[col] = pd.to_datetime(frame[col]).dt.strftime("%Y-%m-%d %H:%M")
    for col in ["entry_price", "initial_stop_price", "stop_price", "final_stop_price",
                "target_price", "partial_exit_price", "exit_price",
                "gross_pnl", "fees", "net_pnl", "cumulative_pnl",
                "stop_ticks", "take_profit_ticks", "partial_gross_pnl"]:
        if col not in frame:
            continue
        frame[col] = frame[col].round(2)
    return frame.to_dict("records")


def dataset_information():
    """Summarize every uploaded file and any completed order-block run."""
    rows = []
    for label in TIMEFRAMES:
        if label not in CACHE["raw"]:
            continue
        candles = normalize_ohlc(CACHE["raw"][label]).reset_index(drop=True)
        raw_rows = len(CACHE["raw"][label])
        blank_rows = raw_rows - len(candles)
        flat_bars = int((candles.open.eq(candles.high) & candles.high.eq(candles.low)
                         & candles.low.eq(candles.close)).sum())
        interval = Strategy._infer_bar_delta(candles).total_seconds() / 60
        result = CACHE["results"].get(label)
        bull = int(result["bars"]["bull_order_block"].sum()) if result else None
        bear = int(result["bars"]["bear_order_block"].sum()) if result else None
        result_stats = result["stats"].iloc[0] if result else None
        rows.append({
            "slot": label,
            "filename": CACHE["sources"][label],
            "start_date": candles["time"].min().strftime("%Y-%m-%d %H:%M"),
            "end_date": candles["time"].max().strftime("%Y-%m-%d %H:%M"),
            "inferred_minutes": round(interval, 4),
            "candles": len(candles),
            "source_rows": raw_rows,
            "blank_ohlc_rows": blank_rows,
            "one_price_bars": flat_bars,
            "strategy": result_stats.strategy if result is not None else None,
            "lookback_months": result_stats.lookback_months if result is not None else None,
            "backtest_start": (pd.Timestamp(result_stats.data_start).strftime("%Y-%m-%d %H:%M")
                               if result is not None else None),
            "backtest_end": (pd.Timestamp(result_stats.data_end).strftime("%Y-%m-%d %H:%M")
                             if result is not None else None),
            "bull_order_blocks": bull,
            "bear_order_blocks": bear,
            "total_order_blocks": None if result is None else bull + bear,
        })
    return rows


def selected_trade_detail(trade_key):
    if not trade_key or "-" not in str(trade_key):
        return html.Div("Select a table row or chart triangle.", className="notice")
    label, number = str(trade_key).split("-", 1)
    result = CACHE["results"].get(label)
    if not result:
        return html.Div("Trade not found.", className="notice")
    match = result["trades"].loc[result["trades"].trade_id == int(number)]
    if match.empty:
        return html.Div("Trade not found.", className="notice")
    t = match.iloc[0]
    fields = [
        ("Trade", trade_key), ("Side", t.side), ("Entry", f"{t.entry_time} at {t.entry_price:.2f}"),
        ("Exit", f"{t.exit_time} at {t.exit_price:.2f}"),
        ("Initial stop", f"{t.initial_stop_price:.2f}"),
        ("Final stop", f"{t.final_stop_price:.2f}"),
        ("Stop distance", f"{t.stop_ticks:,.2f} ticks"),
        ("Target", f"{t.target_price:.2f}"),
        ("Target distance", f"{t.take_profit_ticks:,.2f} ticks"),
        ("Reason", t.exit_reason),
        ("Lots", int(t.lots)),
        ("Partial bookings", t.partial_exit_details),
        ("Gross P&L", f"${t.gross_pnl:,.2f}"), ("Fees", f"${t.fees:,.2f}"),
        ("Net P&L", f"${t.net_pnl:,.2f}"), ("Cumulative P&L", f"${t.cumulative_pnl:,.2f}"),
    ]
    cards = html.Div([html.Div([html.Div(k, className="detail-label"),
                                html.Div(str(v), className="detail-value")], className="detail-item")
                      for k, v in fields], className="detail-grid")
    bars = result["bars"]
    minutes = float(result["stats"].iloc[0].inferred_bar_minutes)
    window = bars.loc[bars.time.between(pd.Timestamp(t.entry_time)-pd.Timedelta(minutes=minutes*10),
                                        pd.Timestamp(t.exit_time)+pd.Timedelta(minutes=minutes*10))]
    fig = go.Figure(go.Candlestick(x=window.time, open=window.open, high=window.high,
                                   low=window.low, close=window.close, name="Price"))
    fig.add_trace(go.Scatter(x=[t.entry_time], y=[t.entry_price], mode="markers", name="Entry",
                             marker={"symbol": "triangle-up" if t.side == "LONG" else "triangle-down",
                                     "size": 14, "color": COLORS["blue"] if t.side == "LONG" else COLORS["red"]}))
    fig.add_trace(go.Scatter(x=[t.exit_time], y=[t.exit_price], mode="markers", name="Exit",
                             marker={"symbol": "triangle-left", "size": 14, "color": COLORS["purple"]}))
    fig.add_hline(y=t.stop_price, line_dash="dash", line_color=COLORS["red"], annotation_text="Stop")
    fig.add_hline(y=t.target_price, line_dash="dash", line_color=COLORS["green"], annotation_text="Target")
    fig.update_layout(template="plotly_dark", paper_bgcolor="#000000", plot_bgcolor="#090909",
                      height=420, title=f"Trade {trade_key}",
                      xaxis_rangeslider_visible=False, margin={"l": 50, "r": 20, "t": 55, "b": 35})
    return html.Div([cards, dcc.Graph(figure=fig, config={"displaylogo": False})])


app = Dash(__name__)
app.title = "Shiven Trading Setup"

trade_column_ids = ["id", "side", "lots", "entry_time", "entry_price", "initial_stop_price", "stop_ticks",
                    "target_price", "take_profit_ticks", "partial_bookings_count", "partial_exit_details",
                    "partial_gross_pnl", "final_stop_price", "exit_time", "exit_price",
                    "exit_reason", "net_pnl", "cumulative_pnl"]
trade_columns = [
    {"name": "Trade P&L ($)" if column == "net_pnl"
             else "Cumulative P&L ($)" if column == "cumulative_pnl"
             else column.replace("_", " ").title(),
     "id": column}
    for column in trade_column_ids
]
app.layout = html.Div([
    dcc.Interval(id="startup", interval=100, max_intervals=1),
    dcc.Store(id="cache-version"), dcc.Store(id="files-version"),
    html.Div([html.H1("Shiven Trading Setup"),
              html.P("Native-data backtests with automatically inferred candle intervals")], className="header"),
    html.Div([
        html.Div([html.Label("5-minute parquet"), dcc.Upload(
            id="upload-5m", children=html.Div(["Drop or ", html.B("select 5m file")]),
            accept=".parquet", multiple=False, className="upload")]),
        html.Div([html.Label("15-minute parquet"), dcc.Upload(
            id="upload-15m", children=html.Div(["Drop or ", html.B("select 15m file")]),
            accept=".parquet", multiple=False, className="upload")]),
        html.Div([html.Label("1-hour parquet"), dcc.Upload(
            id="upload-1h", children=html.Div(["Drop or ", html.B("select 1h file")]),
            accept=".parquet", multiple=False, className="upload")]),
        html.Div(id="upload-status", className="file-status upload-status"),
    ], className="multi-upload panel"),
    html.Div([html.H2("Data files"), dash_table.DataTable(
        id="dataset-info",
        columns=[{"name": column.replace("_", " ").title(), "id": column} for column in
                 ["slot", "filename", "start_date", "end_date", "inferred_minutes", "candles",
                  "source_rows", "blank_ohlc_rows", "one_price_bars",
                  "strategy", "lookback_months", "backtest_start", "backtest_end",
                  "bull_order_blocks", "bear_order_blocks", "total_order_blocks"]],
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#000000", "color": "white", "fontWeight": "bold"},
        style_cell={"padding": "9px", "textAlign": "right", "backgroundColor": "#101010",
                    "color": "#FFFFFF", "border": "1px solid #333333"},
        style_cell_conditional=[{"if": {"column_id": column}, "textAlign": "left"}
                                for column in ["slot", "filename", "start_date", "end_date",
                                               "strategy", "backtest_start", "backtest_end"]],
    )], className="panel"),
    html.Div([
        html.Div([html.Label("Product preset"), dcc.Dropdown(
            id="product-preset", options=list(PRODUCT_PRESETS),
            value="GOX (current)", clearable=False)]),
        html.Div([html.Label("Tick size"), dcc.Input(
            id="tick-size", type="number", value=0.25, min=0.00000001, step="any", debounce=True)]),
        html.Div([html.Label("Tick value ($ per tick per lot)"), dcc.Input(
            id="tick-value", type="number", value=25.0, min=0.00000001, step="any", debounce=True)]),
        html.Div([html.Label("Minimum order-block move (ticks)"), dcc.Input(
            id="minimum-move-ticks", type="number", value=1, min=0.00000001,
            step="any", debounce=True)]),
        html.Div([html.Label("Maximum order-block move (ticks)"), dcc.Input(
            id="maximum-move-ticks", type="number", value=3, min=0.00000001,
            step="any", debounce=True)]),
        html.Div([html.Label("Total lots"), dcc.Input(
            id="lots", type="number", value=1, min=1, step=1, debounce=True)]),
        html.Div([html.Label("Partial-booking method"), dcc.Dropdown(
            id="partial-mode", options=[
                {"label": "Off / single exit", "value": "OFF"},
                {"label": "Every N profit ticks", "value": "INTERVAL"},
                {"label": "Percentages of final TP", "value": "PERCENT"},
            ], value="OFF", clearable=False)]),
        html.Div([html.Label("Target percentages (one lot each)"), dcc.Dropdown(
            id="partial-percentages", multi=True,
            options=[{"label": f"{value}% of TP", "value": value}
                     for value in [25, 33, 50, 67, 75]],
            value=[25, 50, 75])]),
        html.Div([html.Label("Consecutive booking interval (ticks)"), dcc.Input(
            id="partial-interval-ticks", type="number", value=2, min=0.00000001,
            step="any", debounce=True)]),
        html.Div([html.Label("Trailing stop"), dcc.Checklist(
            id="trailing-enabled",
            options=[{"label": " Trail 1 tick for every 2 profit ticks", "value": "enabled"}],
            value=[])]),
        html.Div([html.Label("Trade holding"), dcc.Checklist(
            id="exclude-overnight",
            options=[{"label": " Exclude trades carried overnight", "value": "exclude"}],
            value=[])]),
    ], className="parameter-controls panel"),
    html.Div([
        html.Div([html.Label("Backtest strategy"), dcc.Dropdown(
            id="strategy-selector",
            options=[{"label": config["label"], "value": key}
                     for key, config in STRATEGIES.items()],
            value="ORDER_BLOCK", clearable=False)]),
        html.Div([html.Label("File to backtest"), dcc.Dropdown(
            id="dataset-to-run", options=[], value=None, clearable=False)]),
        html.Div([html.Label("Backtest history from data end"), dcc.Dropdown(
            id="lookback-months", options=LOOKBACK_OPTIONS,
            value="ALL", clearable=False)]),
        html.Div([html.Label("Chart window"), dcc.Dropdown(
            id="window", options=list(WINDOWS), value="2,000 candles", clearable=False)]),
        html.Button("Run Backtest", id="run-backtest", n_clicks=0, className="run-button"),
        html.Div(id="run-status", className="file-status run-status"),
    ],
             className="controls panel"),
    html.Div(id="metrics", className="metrics-grid"),
    html.Div(dcc.Loading(dcc.Graph(id="market-chart", figure=empty_figure(),
                                  config={"displaylogo": False, "scrollZoom": True}), type="circle"), className="panel"),
    html.Div([html.H2("Trades"), dash_table.DataTable(
        id="trades", columns=trade_columns,
        row_selectable="single", selected_row_ids=[], sort_action="native", filter_action="native",
        page_action="none", virtualization=True, fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "overflowY": "auto", "height": "560px"},
        style_header={"backgroundColor": "#000000", "color": "#FFFFFF", "fontWeight": "bold"},
        style_filter={"backgroundColor": "#FFFFFF", "color": "#000000"},
        style_cell={"padding": "8px", "fontSize": 13, "textAlign": "right",
                    "backgroundColor": "#101010", "color": "#FFFFFF",
                    "border": "1px solid #333333", "minWidth": "90px",
                    "width": "125px", "maxWidth": "200px", "overflow": "hidden",
                    "textOverflow": "ellipsis"},
        style_data_conditional=[
            {"if": {"filter_query": "{net_pnl} > 0"},
             "color": "#06150C", "backgroundColor": "#BDF7CF", "fontWeight": "bold"},
            {"if": {"filter_query": "{net_pnl} < 0"},
             "color": "#210507", "backgroundColor": "#FFC7CC", "fontWeight": "bold"},
            {"if": {"filter_query": "{net_pnl} = 0"},
             "color": "#111111", "backgroundColor": "#F2F2F2"},
            {"if": {"column_id": "partial_exit_details"}, "minWidth": "300px", "maxWidth": "420px",
             "whiteSpace": "normal", "height": "auto"}],
    )], className="panel"),
    html.Div([html.H2("Selected trade"), html.Div(id="trade-detail")], className="panel"),
], className="page")


@app.callback(Output("tick-size", "value"), Output("tick-value", "value"),
              Input("product-preset", "value"))
def apply_product_preset(preset):
    values = PRODUCT_PRESETS.get(preset)
    return values if values is not None else (no_update, no_update)


@app.callback(
    Output("dataset-to-run", "options"), Output("dataset-to-run", "value"),
    Output("upload-status", "children"), Output("files-version", "data"),
    Input("startup", "n_intervals"),
    Input("upload-5m", "contents"), Input("upload-15m", "contents"), Input("upload-1h", "contents"),
    State("upload-5m", "filename"), State("upload-15m", "filename"), State("upload-1h", "filename"),
    State("dataset-to-run", "value"),
)
def load_data(_, contents_5m, contents_15m, contents_1h,
              name_5m, name_15m, name_1h, current_selection):
    try:
        uploads = {
            "5m": (contents_5m, name_5m), "15m": (contents_15m, name_15m),
            "1h": (contents_1h, name_1h),
        }
        triggered = callback_context.triggered_id
        upload_id_to_label = {"upload-5m": "5m", "upload-15m": "15m", "upload-1h": "1h"}

        if triggered == "startup" or triggered is None:
            for label in TIMEFRAMES:
                default_path = next(
                    (SCRIPT_DIR / candidate for candidate in DEFAULT_FILES[label]
                     if (SCRIPT_DIR / candidate).exists()), None
                )
                if default_path:
                    CACHE["raw"][label] = pd.read_parquet(default_path)
                    CACHE["sources"][label] = default_path.name
        elif triggered in upload_id_to_label:
            label = upload_id_to_label[triggered]
            contents, filename = uploads[label]
            if contents:
                _, encoded = contents.split(",", 1)
                CACHE["raw"][label] = pd.read_parquet(io.BytesIO(base64.b64decode(encoded)))
                CACHE["sources"][label] = filename
                CACHE["results"].pop(label, None)
                CACHE["chart_frames"].clear()
                CACHE["figures"].clear()
        if not CACHE["raw"]:
            return [], None, "Upload at least one parquet file.", 0
        options = [
            {"label": f"{label} — {CACHE['sources'][label]}", "value": label}
            for label in TIMEFRAMES if label in CACHE["raw"]
        ]
        available = [option["value"] for option in options]
        selection = current_selection if current_selection in available else available[0]
        status = " | ".join(
            f"{label}: {CACHE['sources'][label]}"
            for label in TIMEFRAMES if label in CACHE["raw"]
        )
        return options, selection, "Available files — " + status, int(time() * 1000)
    except Exception as exc:
        return no_update, no_update, f"Error while loading a file: {exc}", no_update


@app.callback(Output("dataset-info", "data"),
              Input("files-version", "data"), Input("cache-version", "data"))
def update_dataset_information(_, __):
    return dataset_information()


@app.callback(
    Output("cache-version", "data"), Output("run-status", "children"),
    Input("run-backtest", "n_clicks"),
    State("strategy-selector", "value"), State("dataset-to-run", "value"),
    State("lookback-months", "value"), State("tick-size", "value"), State("tick-value", "value"),
    State("minimum-move-ticks", "value"), State("maximum-move-ticks", "value"),
    State("lots", "value"), State("partial-mode", "value"),
    State("partial-percentages", "value"), State("partial-interval-ticks", "value"),
    State("trailing-enabled", "value"),
    State("exclude-overnight", "value"),
    prevent_initial_call=True,
)
def run_selected_backtest(n_clicks, strategy_key, label, lookback_months, tick_size, tick_value,
                          minimum_move_ticks, maximum_move_ticks, lots,
                          partial_mode, partial_percentages, partial_interval_ticks,
                          trailing_enabled, exclude_overnight):
    if not n_clicks:
        return no_update, no_update
    try:
        if label not in CACHE["raw"]:
            raise ValueError("Select an uploaded file before running the backtest")
        if strategy_key not in STRATEGIES:
            raise ValueError("Select a valid backtest strategy")
        if tick_size is None or tick_value is None or tick_size <= 0 or tick_value <= 0:
            raise ValueError("Tick size and tick value must both be positive numbers")
        if (minimum_move_ticks is None or maximum_move_ticks is None
                or minimum_move_ticks <= 0 or maximum_move_ticks < minimum_move_ticks):
            raise ValueError("Order-block range must satisfy 0 < minimum <= maximum")
        if lots is None or int(lots) < 1:
            raise ValueError("Total lots must be at least 1")
        partial_mode = partial_mode or "OFF"
        if int(lots) == 1:
            partial_mode = "OFF"
        if partial_mode == "PERCENT" and not partial_percentages:
            raise ValueError("Select at least one target percentage")
        if partial_mode == "INTERVAL" and (partial_interval_ticks is None or partial_interval_ticks <= 0):
            raise ValueError("Consecutive partial-booking interval must be positive")
        version = process_timeframe(
            CACHE["raw"][label], label, CACHE["sources"][label], tick_size, tick_value,
            minimum_move_ticks, maximum_move_ticks, int(lots), partial_mode,
            partial_percentages or [], float(partial_interval_ticks or 2),
            "enabled" in (trailing_enabled or []),
            "exclude" in (exclude_overnight or []),
            strategy_key, lookback_months or "ALL",
        )
        stats = CACHE["results"][label]["stats"].iloc[0]
        source_rows = len(CACHE["raw"][label])
        blank_rows = source_rows - int(stats.valid_bars)
        message = (
            f"Completed: {STRATEGIES[strategy_key]['label']} on {CACHE['sources'][label]} | inferred interval "
            f"{stats.inferred_bar_minutes:g} minutes | {int(stats.total_trades):,} trades | "
            f"backtest {pd.Timestamp(stats.data_start):%Y-%m-%d} to "
            f"{pd.Timestamp(stats.data_end):%Y-%m-%d} | "
            f"tick size {tick_size:g} | tick value ${tick_value:g} | "
            f"order block {minimum_move_ticks:g}–{maximum_move_ticks:g} ticks inclusive | "
            f"{int(lots)} lots | final TP/SL fixed 1:1 | "
            f"partial mode {partial_mode.lower()} | "
            f"trailing {'on (1 tick per 2 profit ticks)' if 'enabled' in (trailing_enabled or []) else 'off'} | "
            f"overnight removed {int(stats.overnight_trades_removed):,} | "
            f"valid OHLC {int(stats.valid_bars):,}/{source_rows:,}; blank rows excluded {blank_rows:,}"
        )
        return version, message
    except Exception as exc:
        return no_update, f"Backtest error: {exc}"


@app.callback(Output("market-chart", "figure"), Output("trades", "data"),
              Output("metrics", "children"),
              Input("cache-version", "data"), Input("dataset-to-run", "value"), Input("window", "value"))
def update_view(version, label, window_label):
    if not version or label not in CACHE["results"]:
        return empty_figure("Select a file and click Run Backtest."), [], []
    result = CACHE["results"][label]
    return (build_market_figure(label, WINDOWS[window_label]), trade_records(result["trades"]),
            metrics(result["stats"]))


@app.callback(Output("trade-detail", "children"),
              Input("trades", "selected_row_ids"), Input("market-chart", "clickData"))
def show_trade(selected_ids, click_data):
    if callback_context.triggered_id == "market-chart" and click_data:
        key = click_data["points"][0].get("customdata")
        if isinstance(key, (list, tuple)):
            key = key[0]
    else:
        key = selected_ids[0] if selected_ids else None
    return selected_trade_detail(key)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
