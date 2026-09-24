"""Generic order-block backtest entry point used by desktop.py.

The full reusable strategy engine is kept in
GOX25_Z25_order_block_backtest.py. This filename is provided because the VS
Code project uses ab.py. Running this file directly performs the five-minute
backtest and creates the formatted Excel report. The multi-timeframe dashboard
also imports Strategy from this file.
"""

from GOX25_Z25_order_block_backtest import Strategy, main

__all__ = ["Strategy"]


if __name__ == "__main__":
    main()
