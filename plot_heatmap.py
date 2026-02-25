#!/usr/bin/env python3
"""Generate a volume-based heatmap visualization of candlesticks using Massive API."""

import logging
from datetime import datetime, timedelta

import numpy as np
import streamlit as st
import plotly.graph_objects as go

from src.config.settings import settings
from src.services.massive import MassiveService, MassiveAPIError

logger = logging.getLogger(__name__)

# Configure Streamlit page
st.set_page_config(page_title="Heatmap Generator", layout="wide")

# Supported timeframes for Massive API
SUPPORTED_TIMEFRAMES = {
    "1minute": "1 Minute",
    "3minute": "3 Minutes",
    "5minute": "5 Minutes",
    "10minute": "10 Minutes",
    "15minute": "15 Minutes",
    "30minute": "30 Minutes",
    "1hour": "1 Hour",
    "4hour": "4 Hours",
    "1day": "1 Day",
    "1week": "1 Week",
    "1month": "1 Month",
}


def fetch_candlesticks(
    ticker: str,
    start_date: datetime,
    end_date: datetime,
    timeframe: str,
) -> tuple[list, float]:
    """Fetch candlestick data from Massive API.

    Args:
        ticker: Stock ticker symbol
        start_date: Start date for data
        end_date: End date for data
        timeframe: Timeframe for candlesticks

    Returns:
        Tuple of (candlesticks_list, current_price)
    """
    try:
        if not settings.massive_api_key:
            st.error("❌ MASSIVE_API_KEY not configured in .env file")
            return [], 0

        service = MassiveService(api_key=settings.massive_api_key)

        # Fetch candlesticks
        with st.status("📈 Fetching candlestick data from Massive API..."):
            st.write(f"Ticker: {ticker}")
            st.write(f"Timeframe: {SUPPORTED_TIMEFRAMES[timeframe]}")
            st.write(f"Date Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

            candlestick_data = service.get_candlesticks(
                ticker=ticker,
                timeframe=timeframe,
                from_date=start_date,
                to_date=end_date,
                limit=500000,  # Fetch up to 500k candlesticks with automatic pagination
            )

        # Use last candlestick close as current price
        current_price = 0
        if candlestick_data.candlesticks:
            current_price = candlestick_data.candlesticks[-1].close
            st.success(f"✅ Fetched {len(candlestick_data.candlesticks)} candlesticks")
            return candlestick_data.candlesticks, current_price
        else:
            st.warning(f"⚠️ No candlestick data returned for {ticker}")
            return [], 0

    except MassiveAPIError as e:
        st.error(f"❌ API Error: {str(e)}")
        logger.error(f"Massive API Error: {e}", exc_info=True)
        return [], 0
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        logger.error(f"Error fetching candlesticks: {e}", exc_info=True)
        return [], 0


def create_volume_heatmap(
    ticker: str,
    spot_price: float,
    candlesticks: list,
    timeframe: str,
):
    """Create a volume-based heatmap using Plotly's heatmap.

    Args:
        ticker: Stock ticker symbol
        spot_price: Current spot price
        candlesticks: List of Candlestick objects
        timeframe: Timeframe string for display

    Returns:
        Plotly figure object
    """
    if not candlesticks:
        st.warning("❌ No candle data available")
        return None

    # Extract OHLCV data from candlesticks
    timestamps = [c.timestamp for c in candlesticks]
    opens = [c.open for c in candlesticks]
    highs = [c.high for c in candlesticks]
    lows = [c.low for c in candlesticks]
    closes = [c.close for c in candlesticks]
    volumes = [c.volume for c in candlesticks]

    # Create figure with heatmap
    fig = go.Figure()

    # Create datetime labels for X-axis
    x_labels = [ts.strftime('%Y-%m-%d %H:%M') for ts in timestamps]
    x_indices = list(range(len(timestamps)))

    # Calculate heat scores based on consecutive candle overlap
    # Create fixed price bins across entire range
    all_prices = highs + lows
    min_price = min(all_prices)
    max_price = max(all_prices)
    price_range = max_price - min_price

    # Create 500 price bins for fine granularity
    num_bins = 500
    price_bins = np.linspace(min_price - price_range * 0.05, max_price + price_range * 0.05, num_bins)
    bin_width = price_bins[1] - price_bins[0] if len(price_bins) > 1 else 0.01

    # Track heat at each price bin and which bins were covered by the previous candle
    heat_map = np.zeros(num_bins)  # Heat value for each price bin
    heat_scores = []  # Store the heat for each candle
    previous_candle_bins = set()  # Track which bins were covered by the previous candle

    for i, (high, low) in enumerate(zip(highs, lows)):
        # Find which bins fall within this candle's range
        bins_in_candle = np.where((price_bins >= low) & (price_bins <= high))[0]
        bins_in_candle_set = set(bins_in_candle)

        # Calculate heat for each bin in this candle
        max_heat_in_candle = 0
        heats_for_candle = {}

        for bin_idx in bins_in_candle:
            if bin_idx in previous_candle_bins:
                # This bin was covered by the PREVIOUS candle, increment heat
                heat_map[bin_idx] += 1
            else:
                # This bin was NOT covered by the previous candle, reset to heat 1
                # (even if it was covered by earlier candles, we break the consecutive chain)
                heat_map[bin_idx] = 1

            heats_for_candle[bin_idx] = heat_map[bin_idx]
            max_heat_in_candle = max(max_heat_in_candle, heat_map[bin_idx])

        # For bins that were covered previously but NOT in this candle, reset their heat
        # (they're no longer consecutively covered)
        for bin_idx in previous_candle_bins:
            if bin_idx not in bins_in_candle_set:
                heat_map[bin_idx] = 0

        # Shift heat values: heat 1 becomes 0, heat 2 becomes 1, etc.
        shifted_heats = [max(0, heats_for_candle[b] - 1) for b in bins_in_candle]

        heat_scores.append({
            'bins': bins_in_candle,
            'heats': shifted_heats,
            'avg_heat': np.mean(shifted_heats) if len(shifted_heats) > 0 else 0,
            'max_heat': max(shifted_heats) if shifted_heats else 0
        })

        # Update for next iteration
        previous_candle_bins = bins_in_candle_set

    # Find max heat for color scaling
    all_avg_heats = [score['avg_heat'] for score in heat_scores]
    if all_avg_heats:
        max_heat = max(all_avg_heats)
    else:
        max_heat = 1

    # Always scale from 1 (lowest visible heat) to max_heat for consistent coloring
    min_heat = 1

    # Function to get color based on heat value
    def get_heat_color(heat_value, min_h, max_h):
        """Get RGB color for a given heat value."""
        if max_h == min_h:
            norm = 0.5
        else:
            norm = (heat_value - min_h) / (max_h - min_h)

        colors_rgb = [
            (0, 51, 204),       # Dark blue (heat=1)
            (0, 153, 255),      # Bright blue
            (0, 255, 0),        # Green
            (255, 255, 0),      # Yellow
            (255, 102, 0),      # Orange (max heat)
        ]

        if norm < 0.25:
            r1, g1, b1 = colors_rgb[0]
            r2, g2, b2 = colors_rgb[1]
            t = norm / 0.25
        elif norm < 0.5:
            r1, g1, b1 = colors_rgb[1]
            r2, g2, b2 = colors_rgb[2]
            t = (norm - 0.25) / 0.25
        elif norm < 0.75:
            r1, g1, b1 = colors_rgb[2]
            r2, g2, b2 = colors_rgb[3]
            t = (norm - 0.5) / 0.25
        else:
            r1, g1, b1 = colors_rgb[3]
            r2, g2, b2 = colors_rgb[4]
            t = (norm - 0.75) / 0.25

        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)

        # Clamp values to 0-255 range
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        return f"rgba({r}, {g}, {b}, 0.85)"

    # Add candlestick rectangles with individual heat segments
    for i, (timestamp, high, low, x_label, heat_score) in enumerate(
        zip(timestamps, highs, lows, x_labels, heat_scores)
    ):
        bins_in_candle = heat_score['bins']
        heats_in_candle = heat_score['heats']

        if len(bins_in_candle) == 0:
            continue

        # Group consecutive bins with same heat value into segments
        segments = []  # List of (heat_value, start_idx, end_idx) for bins
        current_heat = heats_in_candle[0]
        start_idx = 0

        for j in range(1, len(heats_in_candle)):
            if heats_in_candle[j] != current_heat:
                # Heat changed, save segment
                segments.append((current_heat, start_idx, j - 1))
                current_heat = heats_in_candle[j]
                start_idx = j

        # Add final segment
        segments.append((current_heat, start_idx, len(heats_in_candle) - 1))

        # Draw a bar for each heat segment (skip heat 0)
        for segment_heat, start_bin_idx, end_bin_idx in segments:
            # Skip heat 0 (no overlap)
            if segment_heat == 0:
                continue

            # Get price range for this segment
            segment_low = price_bins[bins_in_candle[start_bin_idx]]
            segment_high = price_bins[bins_in_candle[end_bin_idx]]

            # Ensure segment covers a meaningful range
            if segment_high <= segment_low:
                segment_high = segment_low + bin_width

            color = get_heat_color(segment_heat, min_heat, max_heat)

            # Add bar for this segment
            fig.add_trace(
                go.Bar(
                    x=[i],
                    y=[segment_high - segment_low],
                    base=segment_low,
                    width=0.7,
                    marker=dict(
                        color=color,
                        line=dict(color="rgba(100, 100, 100, 0.3)", width=0.5),
                    ),
                    name="",
                    hovertemplate=(
                        f"<b>{x_label}</b><br>"
                        f"High: ${segment_high:.2f}<br>"
                        f"Low: ${segment_low:.2f}<br>"
                        f"Heat Score: {segment_heat:.0f}"
                        "<extra></extra>"
                    ),
                    showlegend=False,
                )
            )

    # Create cumulative background heatmap: sum of heat up to each candle position
    # Matrix: rows = price bins, columns = candles, values = cumulative heat
    cumulative_heat_map = np.zeros((num_bins, len(timestamps)))
    previous_candle_bins = set()  # Track which bins were covered in previous candle

    # Build cumulative heat for each candle position
    for candle_idx, candle_score in enumerate(heat_scores):
        # Start with previous candle's cumulative heat
        if candle_idx > 0:
            cumulative_heat_map[:, candle_idx] = cumulative_heat_map[:, candle_idx - 1]

        # Current candle's covered bins
        current_bins_set = set(candle_score['bins'])

        # Add or subtract current candle's heat to covered bins
        for bin_idx, heat in zip(candle_score['bins'], candle_score['heats']):
            if bin_idx in previous_candle_bins:
                # This bin was covered in previous candle - ADD heat (continue chain)
                cumulative_heat_map[bin_idx, candle_idx] += heat
            else:
                # This bin was NOT covered in previous candle - SUBTRACT heat (new section after gap)
                cumulative_heat_map[bin_idx, candle_idx] -= heat
                cumulative_heat_map[bin_idx, candle_idx] = max(0, cumulative_heat_map[bin_idx, candle_idx])

        # Update previous covered bins for next iteration
        previous_candle_bins = current_bins_set

    # Find max for normalization
    max_cumulative_heat = cumulative_heat_map.max()
    if max_cumulative_heat == 0:
        max_cumulative_heat = 1

    # Add cumulative heatmap as background with diverse, intense colors
    fig.add_trace(
        go.Heatmap(
            z=cumulative_heat_map,
            x=x_indices,
            y=np.round(price_bins, 2),
            colorscale=[
                [0.0, "rgba(0, 0, 0, 0)"],           # 0 = transparent
                [0.12, "rgba(25, 0, 100, 0.25)"],    # Dark purple
                [0.25, "rgba(0, 51, 204, 0.35)"],    # Dark blue
                [0.37, "rgba(0, 130, 255, 0.4)"],    # Bright blue
                [0.5, "rgba(0, 255, 0, 0.4)"],       # Green
                [0.62, "rgba(0, 255, 150, 0.4)"],    # Cyan-green
                [0.75, "rgba(255, 255, 0, 0.45)"],   # Yellow
                [0.87, "rgba(255, 100, 0, 0.5)"],    # Orange
                [1.0, "rgba(255, 0, 0, 0.5)"],       # Red (peak)
            ],
            zmin=0,
            zmax=max_cumulative_heat,
            showscale=False,
            hoverinfo="skip",
            name="",
        )
    )

    # Calculate heat-weighted average price for each candle
    heat_weighted_prices = []
    heat_colors = []  # Color based on whether heat is above or below close

    for candle_idx in range(len(timestamps)):
        # Get heat values at this candle position
        heat_column = cumulative_heat_map[:, candle_idx]
        total_heat = heat_column.sum()

        if total_heat > 0:
            # Weighted average price = sum(price * heat) / sum(heat)
            weighted_price = np.sum(price_bins * heat_column) / total_heat
        else:
            # No heat at this candle, use close price
            weighted_price = closes[candle_idx]

        heat_weighted_prices.append(weighted_price)

        # Determine color based on whether heat is above or below close
        close_price = closes[candle_idx]
        if weighted_price > close_price:
            # Heat is above close = GREEN (bullish pressure above)
            heat_colors.append('rgba(0, 255, 0, 0.85)')
        else:
            # Heat is below close = RED (bearish pressure below)
            heat_colors.append('rgba(255, 0, 0, 0.85)')

    # Add heat-weighted average price line with dynamic coloring
    fig.add_trace(
        go.Scatter(
            x=x_indices,
            y=heat_weighted_prices,
            mode='lines+markers',
            name='Heat-Weighted Price',
            line=dict(width=2.5),
            marker=dict(color=heat_colors, size=4),
            hovertemplate="<b>%{customdata}</b><br>Heat-Weighted Price: $%{y:.2f}<extra></extra>",
            customdata=x_labels,
            showlegend=False,
        )
    )

    # Calculate OHLC/4 average for reference
    ohlc4 = [(opens[i] + highs[i] + lows[i] + closes[i]) / 4 for i in range(len(timestamps))]

    # Add OHLC/4 line chart for reference (lighter)
    fig.add_trace(
        go.Scatter(
            x=x_indices,
            y=ohlc4,
            mode='lines',
            name='OHLC/4',
            line=dict(color='rgba(200, 200, 200, 0.4)', width=1),
            hovertemplate="<b>%{customdata}</b><br>OHLC/4: $%{y:.2f}<extra></extra>",
            customdata=x_labels,
            yaxis='y',
            showlegend=False,
        )
    )

    # Add current price line
    fig.add_hline(
        y=spot_price,
        line_dash="dash",
        line_color="white",
        line_width=2,
        annotation_text=f"Current: ${spot_price:.2f}",
        annotation_position="right",
        annotation_font=dict(size=12, color="white"),
    )

    # Update layout with dark theme
    timeframe_label = SUPPORTED_TIMEFRAMES.get(timeframe, timeframe)
    date_range = f"{timestamps[0].strftime('%Y-%m-%d')} to {timestamps[-1].strftime('%Y-%m-%d')}"
    fig.update_layout(
        title=f"<b>{ticker} - Volume Heatmap ({timeframe_label})</b><br><sub>{date_range} | Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</sub>",
        template="plotly_dark",
        plot_bgcolor="#111111",
        paper_bgcolor="#111111",
        font=dict(size=11, color="white"),
        height=700,
        width=1400,
        hovermode="closest",
        barmode="overlay",
    )

    # Create datetime ticks at regular intervals (show up to 8 labels)
    num_ticks = min(8, len(timestamps))
    if num_ticks > 0:
        step = max(1, len(timestamps) // num_ticks)
        tick_indices = list(range(0, len(timestamps), step))
        tick_labels = [timestamps[i].strftime('%m-%d %H:%M') for i in tick_indices]
    else:
        tick_indices = []
        tick_labels = []

    # Update axes - show datetime labels without gaps
    fig.update_xaxes(
        title_text="Time →",
        showgrid=True,
        gridwidth=1,
        gridcolor="rgba(255, 255, 255, 0.1)",
        tickvals=tick_indices,
        ticktext=tick_labels,
        tickfont=dict(size=9, color="white"),
    )
    fig.update_yaxes(
        title_text="Price ($)",
        showgrid=True,
        gridwidth=1,
        gridcolor="rgba(255, 255, 255, 0.1)",
    )

    return fig


def main():
    """Main Streamlit app for heatmap generation."""
    st.title("📊 Volume Heatmap Generator")
    st.markdown("*Generate volume-based heatmap visualizations for any stock using Massive API*")

    # Initialize session state
    if "ticker" not in st.session_state:
        st.session_state.ticker = "SPY"
    if "start_date" not in st.session_state:
        st.session_state.start_date = datetime.now() - timedelta(days=7)
    if "end_date" not in st.session_state:
        st.session_state.end_date = datetime.now()
    if "timeframe" not in st.session_state:
        st.session_state.timeframe = "5minute"

    # Sidebar controls
    st.sidebar.header("⚙️ Configuration")

    # Ticker input
    ticker = st.sidebar.text_input(
        "Stock Ticker",
        value=st.session_state.ticker,
        placeholder="e.g., SPY, AAPL, QQQ",
    ).upper()
    st.session_state.ticker = ticker

    # Date inputs
    st.sidebar.subheader("Date Range")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input(
            "Start Date",
            value=st.session_state.start_date.date(),
        )
        st.session_state.start_date = datetime.combine(start_date, datetime.min.time())

    with col2:
        end_date = st.date_input(
            "End Date",
            value=st.session_state.end_date.date(),
        )
        st.session_state.end_date = datetime.combine(end_date, datetime.max.time())

    # Timeframe selector
    timeframe = st.sidebar.selectbox(
        "Timeframe",
        options=list(SUPPORTED_TIMEFRAMES.keys()),
        format_func=lambda x: SUPPORTED_TIMEFRAMES[x],
        index=list(SUPPORTED_TIMEFRAMES.keys()).index(st.session_state.timeframe),
    )
    st.session_state.timeframe = timeframe

    # Generate button
    if st.sidebar.button("🔄 Generate Heatmap", width="stretch", type="primary"):
        with st.spinner("📈 Generating heatmap..."):
            # Validate inputs
            if not ticker:
                st.error("❌ Please enter a ticker symbol")
                return

            if start_date > end_date:
                st.error("❌ Start date must be before end date")
                return

            # Fetch data
            candlesticks, current_price = fetch_candlesticks(
                ticker=ticker,
                start_date=st.session_state.start_date,
                end_date=st.session_state.end_date,
                timeframe=timeframe,
            )

            if not candlesticks:
                st.error(f"❌ No data available for {ticker}")
                return

            if current_price == 0:
                st.warning("⚠️ Could not fetch current price, using last candle close")

            # Create heatmap
            fig = create_volume_heatmap(
                ticker=ticker,
                spot_price=current_price,
                candlesticks=candlesticks,
                timeframe=timeframe,
            )

            if fig:
                st.success("✅ Heatmap generated successfully!")

                # Display heatmap
                st.plotly_chart(fig, width="stretch")

                # Display summary
                st.markdown("---")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Ticker", ticker)
                with col2:
                    st.metric("Candles", len(candlesticks))
                with col3:
                    st.metric("Current Price", f"${current_price:.2f}")
                with col4:
                    st.metric("Timeframe", SUPPORTED_TIMEFRAMES[timeframe])

                # Data summary
                st.markdown("#### 📊 Data Summary")
                closes = [c.close for c in candlesticks]
                highs = [c.high for c in candlesticks]
                lows = [c.low for c in candlesticks]
                volumes = [c.volume for c in candlesticks]

                summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
                with summary_col1:
                    st.write(f"**High**: ${max(highs):.2f}")
                with summary_col2:
                    st.write(f"**Low**: ${min(lows):.2f}")
                with summary_col3:
                    st.write(f"**Total Volume**: {sum(volumes):,.0f}")
                with summary_col4:
                    st.write(f"**Avg Volume**: {sum(volumes)/len(volumes):,.0f}")


if __name__ == "__main__":
    main()
