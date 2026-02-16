#!/usr/bin/env python3
"""Generate GEX charts (price/gamma and gamma exposure) in one script."""

import asyncio
import argparse
import json
from datetime import datetime, timedelta
from src.config.settings import settings
from src.services.option_parser import OptionParser
from src.services.gex_calculator import GEXCalculator, get_next_friday, get_two_fridays_from_today, ExpirationFilter
from plotly.subplots import make_subplots
import plotly.graph_objects as go


async def fetch_data(ticker: str, expiration_type: str = "next-friday"):
    """Fetch option data from Schwab API."""
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

    # Get option chain
    print("2️⃣  Fetching option chain...")

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

    return spot_price, chain_data


def create_single_page_dashboard(ticker: str, spot_price: float, snapshot, contracts, strike_data):
    """Create both GEX charts in a single browser tab with subplots."""

    strikes = sorted(snapshot.levels.keys())
    total_gex = [snapshot.levels[s].total_gex for s in strikes]
    call_gex = [snapshot.levels[s].call_gex for s in strikes]
    put_gex = [snapshot.levels[s].put_gex for s in strikes]
    net_gex = [snapshot.levels[s].total_gex / 1_000_000 for s in strikes]

    # Find Gamma Peak (strongest influence) and Gamma Trough (weakest influence)
    # Using absolute value to find magnitude, not direction
    gamma_peak_strike = max(strikes, key=lambda s: abs(snapshot.levels[s].total_gex))
    gamma_trough_strike = min(strikes, key=lambda s: abs(snapshot.levels[s].total_gex))

    # Debug: Check for duplicates and show current price strike data
    print(f"\n🔍 Debug Info:")
    print(f"   Total strikes: {len(strikes)}")
    print(f"   Unique strikes: {len(set(strikes))}")

    # Find and show current price strike
    closest_strike_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
    closest_strike = strikes[closest_strike_idx]
    print(f"   Current price: ${spot_price:.2f}")
    print(f"   Closest strike: ${closest_strike:.2f}")
    print(f"   Net GEX at current strike: ${net_gex[closest_strike_idx]:.2f}M")
    print(f"   Gamma Peak: ${gamma_peak_strike:.2f}")
    print(f"   Gamma Trough: ${gamma_trough_strike:.2f}\n")

    # Create subplots: 2 rows, 1 column
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("Gamma Exposure (GEX) Analysis", "Net Gamma Exposure by Strike"),
        vertical_spacing=0.15,
    )

    # === LEFT CHART: GEX Line Chart ===
    # Add total GEX line
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
        row=1, col=1
    )

    # Add call GEX (green shaded area)
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
        row=1, col=1
    )

    # Add put GEX (red shaded area)
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
        row=1, col=1
    )

    # Add zero line for top chart
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="gray",
        line_width=1,
        row=1, col=1
    )

    # Add current spot price line for top chart
    fig.add_vline(
        x=spot_price,
        line_dash="solid",
        line_color="white",
        line_width=2,
        annotation_text=f"Current: ${spot_price:.2f}",
        annotation_position="top right",
        annotation_font=dict(size=10, color="white"),
        row=1, col=1
    )

    # Add Gamma Peak line (dashed cyan)
    fig.add_vline(
        x=gamma_peak_strike,
        line_dash="dash",
        line_color="cyan",
        line_width=2,
        annotation_text=f"Gamma Peak: ${gamma_peak_strike:.2f}",
        annotation_position="top",
        annotation_font=dict(size=9, color="cyan"),
        row=1, col=1
    )

    # Add Gamma Trough line (dashed red)
    fig.add_vline(
        x=gamma_trough_strike,
        line_dash="dash",
        line_color="red",
        line_width=2,
        annotation_text=f"Gamma Trough: ${gamma_trough_strike:.2f}",
        annotation_position="bottom",
        annotation_font=dict(size=9, color="red"),
        row=1, col=1
    )

    # === BOTTOM CHART: Wall Analysis Bar Chart ===
    # Find extremes (most negative and most positive net GEX)
    min_net_gex_strike = min(strikes, key=lambda s: snapshot.levels[s].total_gex)
    max_net_gex_strike = max(strikes, key=lambda s: snapshot.levels[s].total_gex)

    # Determine colors: red for negative, green for positive, gold for extremes
    colors = []
    for s in strikes:
        if s == min_net_gex_strike or s == max_net_gex_strike:
            colors.append("rgba(255, 215, 0, 0.9)")  # Gold for extremes
        elif snapshot.levels[s].total_gex < 0:
            colors.append("rgba(255, 0, 0, 0.7)")  # Red for negative
        else:
            colors.append("rgba(0, 255, 0, 0.7)")  # Green for positive

    # Add net GEX bars
    fig.add_trace(
        go.Bar(
            x=net_gex,
            y=[f"${s:.2f}" for s in strikes],
            name="Net GEX",
            orientation="h",
            marker=dict(color=colors),
            hovertemplate="<b>Strike: %{y}</b><br>Net GEX: %{x:.1f}M<extra></extra>",
            showlegend=False,
        ),
        row=2, col=1
    )

    # Add zero line (center divider) for bottom chart
    fig.add_vline(
        x=0,
        line_dash="solid",
        line_color="gray",
        line_width=2,
        row=2, col=1
    )

    # Add horizontal highlight at current spot price
    closest_strike = min(strikes, key=lambda s: abs(s - spot_price))
    closest_strike_str = f"${closest_strike:.2f}"

    # Find index to create a band across the current price row
    strike_idx = list(strikes).index(closest_strike)
    if strike_idx > 0:
        band_start = f"${strikes[strike_idx - 1]:.2f}"
    else:
        band_start = closest_strike_str

    if strike_idx < len(strikes) - 1:
        band_end = f"${strikes[strike_idx + 1]:.2f}"
    else:
        band_end = closest_strike_str

    # Add horizontal line at current spot price
    fig.add_hline(
        y=closest_strike_str,
        line_dash="solid",
        line_color="white",
        line_width=2,
        row=2, col=1
    )

    # Add Gamma Peak line (dashed cyan)
    gamma_peak_str = f"${gamma_peak_strike:.2f}"
    fig.add_hline(
        y=gamma_peak_str,
        line_dash="dash",
        line_color="cyan",
        line_width=2,
        row=2, col=1
    )

    # Add Gamma Trough line (dashed red)
    gamma_trough_str = f"${gamma_trough_strike:.2f}"
    fig.add_hline(
        y=gamma_trough_str,
        line_dash="dash",
        line_color="red",
        line_width=2,
        row=2, col=1
    )

    # Update layout
    fig.update_layout(
        title_text=f"<b>{ticker} - Gamma Exposure Dashboard</b><br><sub>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</sub>",
        height=1400,
        template="plotly_dark",
        font=dict(size=11),
        barmode="overlay",  # Ensure bars overlay, not stack
        legend=dict(
            x=0.01,
            y=0.98,
            bgcolor="rgba(17, 17, 17, 0.9)",
            bordercolor="white",
            borderwidth=1,
        ),
        hovermode="closest",
    )

    # Update x-axes
    fig.update_xaxes(title_text="Strike Price ($)", row=1, col=1)
    fig.update_xaxes(title_text="Net GEX (Millions $)", row=2, col=1)

    # Update y-axes
    fig.update_yaxes(title_text="Gamma Exposure ($)", row=1, col=1)
    fig.update_yaxes(title_text="Strike Price", row=2, col=1)

    # Grid styling
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="rgba(255, 255, 255, 0.1)")
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="rgba(255, 255, 255, 0.1)")

    return fig




async def main(ticker: str = "SPY", expiration: str = "next-friday"):
    """Generate both GEX charts."""
    ticker = ticker.upper()

    print("\n" + "=" * 60)
    print(f"Generating GEX charts for {ticker}...")
    print("=" * 60 + "\n")

    try:
        # Fetch data
        spot_price, chain_data = await fetch_data(ticker, expiration)

        # Parse contracts
        print("3️⃣  Parsing contracts...")
        contracts = OptionParser.parse_option_chain(ticker, chain_data)

        # Extract price data
        strike_data = {}
        for contract in contracts:
            strike = contract.strike
            if strike not in strike_data:
                strike_data[strike] = {
                    'call_price': None,
                    'put_price': None,
                    'call_gamma': 0,
                    'put_gamma': 0,
                }

            if contract.option_type.value == 'CALL':
                strike_data[strike]['call_price'] = contract.last_price
                strike_data[strike]['call_gamma'] = contract.gamma
            else:
                strike_data[strike]['put_price'] = contract.last_price
                strike_data[strike]['put_gamma'] = contract.gamma

        print(f"   Parsed: {len(contracts)} contracts at {len(strike_data)} strikes\n")

        # Calculate GEX
        print("4️⃣  Calculating GEX...")
        calculator = GEXCalculator()
        snapshot = calculator.calculate_gex(contracts, spot_price)
        print(f"   Calculated GEX for {len(snapshot.levels)} strikes\n")

        # Create combined dashboard
        print("5️⃣  Creating visualizations...\n")

        fig = create_single_page_dashboard(ticker, spot_price, snapshot, contracts, strike_data)

        print(f"   ✅ Dashboard ready\n")

        # Open in browser (without saving)
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
        print("  • CYAN line = Total Gamma Exposure")
        print("  • GREEN area = Call gamma (Bullish zones)")
        print("  • RED area = Put gamma (Bearish zones)")
        print("  • Dashed line = Zero/Flip point")
        print("  • WHITE line = Current spot price")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate GEX analysis charts (price/gamma + gamma exposure)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python plot_gex.py                           # Default: SPY, next Friday
  python plot_gex.py --ticker QQQ             # QQQ, next Friday
  python plot_gex.py -t AAPL -e today         # AAPL, today's expiration
  python plot_gex.py -t MSFT -e two-fridays   # MSFT, two Fridays out
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

    args = parser.parse_args()
    asyncio.run(main(ticker=args.ticker, expiration=args.expiration))
