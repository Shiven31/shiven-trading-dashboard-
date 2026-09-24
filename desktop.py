"""Simple launch file for the optimized order-block dashboard."""

from GOX25_Z25_multitimeframe_dashboard import app


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
