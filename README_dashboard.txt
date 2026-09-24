SHIVEN TRADING SETUP — WINDOWS / VS CODE

Keep these files together in C:\Users\shiven.goyal\Desktop\go:
  ab.py
  desktop.py
  GOX25_Z25_order_block_backtest.py
  GOX25_Z25_multitimeframe_dashboard.py
  dashboard_requirements.txt
  assets\dashboard.css
  your parquet data files

1. Open PowerShell in the go folder:
   cd C:\Users\shiven.goyal\Desktop\go

2. Install packages with the same Python used by VS Code:
   & "C:\Program Files\Python314\python.exe" -m pip install -r dashboard_requirements.txt

3. Start the dashboard:
   & "C:\Program Files\Python314\python.exe" desktop.py

4. Open http://127.0.0.1:8050 in a browser.

HOW THE CURRENT VERSION WORKS

- Select or upload the parquet file and click Run Backtest.
- Choose the strategy from Backtest strategy. The current version registers the
  Order Block strategy; future strategies are added in the STRATEGIES registry.
- Choose Entire available history or the last 1 through 10 months. The selected
  period is measured backward from the final valid timestamp in the file.
- The dashboard shows both the complete file date range and the actual backtest
  start/end dates after the selected lookback is applied.
- Order-block movement is inclusive:
      minimum ticks <= movement from the previous open <= maximum ticks
- Bull setup also requires the previous candle to be bearish.
- Bear setup also requires the previous candle to be bullish.
- Final take-profit is always fixed at 1:1 with the initial stop distance.
- Total lots may be 1 or more. One-lot trades automatically use a single exit.
- Partial booking offers two modes, with one lot booked at each level:
      Every N ticks: 2, 4, 6... ticks when the interval is 2.
      Percent of TP: choose any of 25%, 33%, 50%, 67%, and 75%.
- After every partial exit, the stop moves toward entry by:
      cumulative booked profit ticks / remaining lots
- Optional trailing stop advances 1 tick for every 2 favorable ticks.
- Fees are treated as dollars per completed round trip per lot.
- All candles remain available in the chart. The chart uses a continuous candle
  sequence so exchange-closed periods are removed; dotted vertical lines show
  the first available candle of each date. One-price bars (O=H=L=C) are shown
  as gold dots. Blank OHLC rows are excluded and counted in the Data files table.
  Use the lower range slider to scroll through the history.
- The Trades table has a fixed header, vertical scrolling, and virtualized rows.
- The complete trade row is green for profitable trades, red for losing trades,
  and light grey for breakeven trades.
- The interface uses a black-and-white theme. Inputs and dropdowns are white
  with black text so their values remain readable.

The standalone Excel backtest remains available by running:
   & "C:\Program Files\Python314\python.exe" ab.py
