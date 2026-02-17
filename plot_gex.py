#!/usr/bin/env python3
"""Generate GEX charts (price/gamma, net GEX, and gamma exposure) in one script."""

import asyncio
import argparse
import pytz
from datetime import datetime, timedelta
from src.config.settings import settings
from src.services.option_parser import OptionParser
from src.services.gex_calculator import GEXCalculator, get_next_friday, get_two_fridays_from_today, ExpirationFilter
from plotly.subplots import make_subplots
import plotly.graph_objects as go


async def fetch_data(ticker: str, expiration_type: str = "next-friday"):
    """Fetch option data and price history from Schwab API."""
    from schwab.auth import client_from_token_file

    client = client_from_token_file(
        token_path=str(settings.token_path),
        api_key=settings.schwab_api_key,
        app_secret=settings.schwab_app_secret,
        asyncio=True,
    )

    # Get quote
    print("1️⃣  Fetching quote...")
    quote_response = await client.get_quote(ticker)
    quote_data = quote_response.json()
    spot_price = float(
        quote_data.get(ticker, {})
        .get("quote", {})
        .get("lastPrice", quote_data.get(ticker, {}).get("extended", {}).get("lastPrice", 0))
    )
    print(f"   Spot: ${spot_price:.2f}\n")

    # Get 5-minute price history (last 7 days)
    print("2️⃣  Fetching 5-minute price history...")
    try:
        eastern = pytz.timezone('US/Eastern')
        end_time = datetime.now(eastern)
        start_time = end_time - timedelta(days=7)

        history_response = await client.get_price_history_every_five_minutes(
            ticker,
            start_datetime=start_time,
            end_datetime=end_time
        )
        history_data = history_response.json()
        print(f"   Status: {history_response.status_code}\n")
    except Exception as e:
        print(f"   ⚠️  Warning: Could not fetch price history: {e}\n")
        history_data = {}

    # Get option chain
    print("3️⃣  Fetching option chain...")

    # Determine expiration date based on filter
    if expiration_type == "today":
        to_date = datetime.now().date() + timedelta(days=1)
        print(f"   Expiration filter: Today (before {to_date})")
    elif expiration_type == "two-fridays":
        to_date = get_two_fridays_from_today().date() + timedelta(days=1)
        print(f"   Expiration filter: Two Fridays out (before {to_date})")
    else:  # next-friday (default)
        to_date = get_next_friday().date() + timedelta(days=1)
        print(f"   Expiration filter: Next Friday (before {to_date})")

    chain_response = await client.get_option_chain(
        symbol=ticker,
        to_date=to_date,
        strike_count=50,
    )
    chain_data = chain_response.json()
    print(f"   Status: {chain_response.status_code}\n")

    return spot_price, chain_data, history_data


def calculate_ohlc4(opens, highs, lows, closes):
    """Calculate OHLC/4 average for each candle."""
    return [(o + h + l + c) / 4 for o, h, l, c in zip(opens, highs, lows, closes)]


def parse_price_history(history_data):
    """Extract OHLC and timestamp data from price history."""
    candles = history_data.get("candles", [])
    if not candles:
        return [], [], [], [], []

    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []

    for candle in candles:
        timestamps.append(datetime.fromtimestamp(candle["datetime"] / 1000))
        opens.append(candle["open"])
        highs.append(candle["high"])
        lows.append(candle["low"])
        closes.append(candle["close"])

    return timestamps, opens, highs, lows, closes


def create_single_page_dashboard(ticker: str, spot_price: float, snapshot, contracts, strike_data, history_data=None, chart_type="ohlc4"):
    """Create GEX dashboard with price chart, gamma heatmap, net GEX, and GEX analysis."""

    strikes = sorted(snapshot.levels.keys())
    total_gex = [snapshot.levels[s].total_gex for s in strikes]
    call_gex = [snapshot.levels[s].call_gex for s in strikes]
    put_gex = [snapshot.levels[s].put_gex for s in strikes]
    net_gex = [snapshot.levels[s].total_gex / 1_000_000 for s in strikes]

    # Find Gamma Peak and Trough
    gamma_peak_strike = max(strikes, key=lambda s: abs(snapshot.levels[s].total_gex))
    gamma_trough_strike = min(strikes, key=lambda s: abs(snapshot.levels[s].total_gex))

    # Debug info
    print(f"\n🔍 Debug Info:")
    print(f"   Total strikes: {len(strikes)}")
    print(f"   Unique strikes: {len(set(strikes))}")

    closest_strike_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
    closest_strike = strikes[closest_strike_idx]
    print(f"   Current price: ${spot_price:.2f}")
    print(f"   Closest strike: ${closest_strike:.2f}")
    print(f"   Net GEX at current strike: ${net_gex[closest_strike_idx]:.2f}M")
    print(f"   Gamma Peak: ${gamma_peak_strike:.2f}")
    print(f"   Gamma Trough: ${gamma_trough_strike:.2f}\n")

    # Create subplots: 3 rows, 1 column
    fig = make_subplots(
        rows=3, cols=1,
        subplot_titles=("Price + Gamma Heatmap", "Net Gamma Exposure by Strike", "Gamma Exposure Analysis"),
        vertical_spacing=0.12,
        row_heights=[0.4, 0.3, 0.3],
    )

    # === ROW 1: Price Chart + Gamma Heatmap ===
    # Parse price history
    timestamps, opens, highs, lows, closes = parse_price_history(history_data) if history_data else ([], [], [], [], [])

    if timestamps:
        # Add heatmap for gamma levels as background
        # Create heatmap grid: strikes as rows, timestamps as columns, gamma as values
        heatmap_z = []
        for strike in strikes:
            heatmap_z.append([snapshot.levels[strike].total_gex / 1_000_000] * len(timestamps))

        fig.add_trace(
            go.Heatmap(
                x=timestamps,
                y=strikes,
                z=heatmap_z,
                colorscale=[
                    [0.0, "rgba(255, 0, 0, 0.3)"],      # Negative (min) = RED (bearish/resistance)
                    [0.5, "rgba(17, 17, 17, 0)"],       # Neutral = transparent
                    [1.0, "rgba(0, 255, 0, 0.3)"]       # Positive (max) = GREEN (bullish/support)
                ],
                showscale=False,
                hoverinfo="skip",
                name="",
                zmid=0,  # Explicitly center the colorscale at zero
            ),
            row=1, col=1
        )

        # Add price chart (candlestick or OHLC/4)
        if chart_type == "candlestick":
            fig.add_trace(
                go.Candlestick(
                    x=timestamps,
                    open=opens,
                    high=highs,
                    low=lows,
                    close=closes,
                    name="Price",
                    increasing_line_color="green",
                    decreasing_line_color="red",
                ),
                row=1, col=1
            )
        else:  # ohlc4
            ohlc4_prices = calculate_ohlc4(opens, highs, lows, closes)
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=ohlc4_prices,
                    name="Price (OHLC/4)",
                    mode="lines",
                    line=dict(color="white", width=2),
                    hovertemplate="<b>%{x}</b><br>Price: $%{y:.2f}<extra></extra>",
                ),
                row=1, col=1
            )

    # === ROW 2: Net Gamma Exposure Bar Chart ===
    # Find extremes for coloring
    min_net_gex_strike = min(strikes, key=lambda s: snapshot.levels[s].total_gex)
    max_net_gex_strike = max(strikes, key=lambda s: snapshot.levels[s].total_gex)

    # Determine colors
    colors = []
    for s in strikes:
        if s == min_net_gex_strike or s == max_net_gex_strike:
            colors.append("rgba(184, 150, 42, 0.8)")  # Gold for extremes
        elif snapshot.levels[s].total_gex > 0:
            colors.append("rgba(0, 200, 0, 0.8)")  # Green for bullish
        else:
            colors.append("rgba(200, 0, 0, 0.8)")  # Red for bearish

    fig.add_trace(
        go.Bar(
            y=[f"${s:.2f}" for s in strikes],
            x=net_gex,
            orientation="h",
            marker=dict(color=colors),
            name="Net GEX",
            hovertemplate="<b>Strike: %{y}</b><br>Net GEX: %{x:.1f}M<extra></extra>",
            showlegend=False,
        ),
        row=2, col=1
    )

    # Add zero line
    fig.add_vline(x=0, line_dash="solid", line_color="gray", line_width=1, row=2, col=1)

    # === ROW 3: GEX Analysis Line Chart ===
    fig.add_trace(
        go.Scatter(
            x=strikes,
            y=total_gex,
            name="Total GEX",
            mode="lines+markers",
            line=dict(color="cyan", width=3),
            marker=dict(size=6),
            hovertemplate="<b>Strike: $%{x:.2f}</b><br>Total GEX: %{y:,.0f}<extra></extra>",
        ),
        row=3, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=strikes,
            y=call_gex,
            name="Call Gamma (Bullish)",
            mode="lines",
            fill="tozeroy",
            line=dict(color="green", width=1),
            fillcolor="rgba(0, 255, 0, 0.2)",
            hovertemplate="<b>Strike: $%{x:.2f}</b><br>Call GEX: %{y:,.0f}<extra></extra>",
        ),
        row=3, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=strikes,
            y=put_gex,
            name="Put Gamma (Bearish)",
            mode="lines",
            fill="tozeroy",
            line=dict(color="red", width=1),
            fillcolor="rgba(255, 0, 0, 0.2)",
            hovertemplate="<b>Strike: $%{x:.2f}</b><br>Put GEX: %{y:,.0f}<extra></extra>",
        ),
        row=3, col=1
    )

    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1, row=3, col=1)

    # Add current spot price line
    fig.add_vline(
        x=spot_price,
        line_dash="solid",
        line_color="white",
        line_width=2,
        annotation_text=f"Current: ${spot_price:.2f}",
        annotation_position="top right",
        annotation_font=dict(size=10, color="white"),
        row=3, col=1
    )

    # Update layout
    fig.update_layout(
        title_text=f"<b>{ticker} - Gamma Exposure Dashboard</b><br><sub>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</sub>",
        height=1400,
        template="plotly_dark",
        plot_bgcolor="#111111",
        paper_bgcolor="#111111",
        font=dict(size=11, color="white"),
        barmode="overlay",
        legend=dict(
            x=0.01,
            y=0.98,
            bgcolor="rgba(17, 17, 17, 0.9)",
            bordercolor="white",
            borderwidth=1,
        ),
        hovermode="closest",
    )

    # Update axes
    fig.update_xaxes(title_text="Strike Price ($)", row=3, col=1)
    fig.update_xaxes(title_text="Net GEX (Millions $)", row=2, col=1)
    # Hide time scale on price chart (both label and ticks)
    fig.update_xaxes(showticklabels=False, ticks="", row=1, col=1)
    fig.update_yaxes(title_text="Gamma Exposure ($)", row=3, col=1)
    fig.update_yaxes(title_text="Strike Price", row=2, col=1)

    # Grid styling
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="rgba(255, 255, 255, 0.1)")
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="rgba(255, 255, 255, 0.1)")

    return fig


async def main(ticker: str = "SPY", expiration: str = "next-friday", chart_type: str = "ohlc4"):
    """Generate GEX dashboard."""
    ticker = ticker.upper()

    print("\n" + "=" * 60)
    print(f"Generating GEX charts for {ticker}...")
    print("=" * 60 + "\n")

    try:
        # Fetch data
        spot_price, chain_data, history_data = await fetch_data(ticker, expiration)

        # Parse contracts
        print("4️⃣  Parsing contracts...")
        contracts = OptionParser.parse_option_chain(ticker, chain_data)

        # Extract strike data
        strike_data = {}
        for contract in contracts:
            strike = contract.strike
            if strike not in strike_data:
                strike_data[strike] = {
                    "call_price": None,
                    "put_price": None,
                    "call_gamma": 0,
                    "put_gamma": 0,
                }

            if contract.option_type.value == "CALL":
                strike_data[strike]["call_price"] = contract.last_price
                strike_data[strike]["call_gamma"] = contract.gamma
            else:
                strike_data[strike]["put_price"] = contract.last_price
                strike_data[strike]["put_gamma"] = contract.gamma

        print(f"   Parsed: {len(contracts)} contracts at {len(strike_data)} strikes\n")

        # Calculate GEX
        print("5️⃣  Calculating GEX...")
        calculator = GEXCalculator()
        snapshot = calculator.calculate_gex(contracts, spot_price)
        print(f"   Calculated GEX for {len(snapshot.levels)} strikes\n")

        # Create dashboard
        print("6️⃣  Creating visualizations...\n")
        fig = create_single_page_dashboard(ticker, spot_price, snapshot, contracts, strike_data, history_data, chart_type)

        print(f"   ✅ Dashboard ready\n")
        print(f"   🌐 Opening dashboard in browser...\n")
        fig.show()

        # Print summary
        print("=" * 60)
        print("✅ DASHBOARD GENERATED SUCCESSFULLY!")
        print("=" * 60)
        print(f"\nTicker: {ticker}")
        print(f"Spot Price: ${spot_price:.2f}")
        print(f"Strikes Analyzed: {len(snapshot.levels)}")
        print(f"\nDashboard is opening in your default browser...")
        print("(Charts are displayed in browser, not saved to disk)")

        print("\nChart Legend:")
        print("  Chart 1 (Price + Gamma Heatmap):")
        print("  • 🟢 GREEN heatmap = Support (positive gamma)")
        print("  • 🔴 RED heatmap = Resistance (negative gamma)")
        print("  • ⚪ WHITE line = OHLC/4 average price")
        print("\n  Chart 2 (Net Gamma Exposure):")
        print("  • 📊 Bar chart by strike")
        print("  • 🟢 GREEN bars = Bullish zones")
        print("  • 🔴 RED bars = Bearish zones")
        print("  • 🟡 GOLD bars = Extremes")
        print("\n  Chart 3 (GEX Analysis):")
        print("  • 🔵 CYAN line = Total gamma")
        print("  • 🟢 GREEN area = Call gamma")
        print("  • 🔴 RED area = Put gamma")
        print("  • ⚪ WHITE line = Current price")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate GEX analysis charts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python plot_gex.py                              # Default: SPY, next Friday
  python plot_gex.py --ticker QQQ                # QQQ, next Friday
  python plot_gex.py -t AAPL -e today            # AAPL, today's expiration
  python plot_gex.py -t SPY --chart-type candlestick  # Candlestick chart
        """,
    )
    parser.add_argument(
        "--ticker",
        "-t",
        type=str,
        default="SPY",
        help="Stock ticker symbol (default: SPY)",
    )
    parser.add_argument(
        "--expiration",
        "-e",
        type=str,
        choices=["today", "next-friday", "two-fridays"],
        default="next-friday",
        help="Expiration filter (default: next-friday)",
    )
    parser.add_argument(
        "--chart-type",
        type=str,
        choices=["ohlc4", "candlestick"],
        default="ohlc4",
        help="Price chart type (default: ohlc4)",
    )

    args = parser.parse_args()
    asyncio.run(main(ticker=args.ticker, expiration=args.expiration, chart_type=args.chart_type))
