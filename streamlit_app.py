#!/usr/bin/env python3
"""Interactive Streamlit app for GEX Dashboard with auto-refresh."""

import asyncio
import time
from datetime import datetime
import streamlit as st
from src.services.option_parser import OptionParser
from src.services.gex_calculator import GEXCalculator
from plot_gex import fetch_data, create_single_page_dashboard, parse_price_history

# ============================================================================
# Page Configuration
# ============================================================================

st.set_page_config(
    page_title="GEX Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# Auto-Refresh Timer (5 minutes)
# ============================================================================

REFRESH_INTERVAL = 300  # 5 minutes in seconds

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

current_time = time.time()
time_since_refresh = current_time - st.session_state.last_refresh

if time_since_refresh >= REFRESH_INTERVAL:
    st.session_state.last_refresh = current_time
    st.rerun()

# ============================================================================
# Styling
# ============================================================================

st.markdown(
    """
    <style>
    [data-testid="stMetric"] { text-align: center; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# Title & Description
# ============================================================================

st.title("📊 GEX Dashboard - Gamma Exposure Analysis")
st.markdown(
    "Real-time options gamma exposure visualization with support/resistance heatmap."
)

# ============================================================================
# Sidebar Controls
# ============================================================================

st.sidebar.markdown("## Settings")

ticker = st.sidebar.text_input(
    "Stock Ticker",
    value="SPY",
    help="Enter stock ticker symbol (e.g., SPY, QQQ, TSLA)",
).upper()

expiration = st.sidebar.selectbox(
    "Expiration Filter",
    ["next-friday", "today", "two-fridays"],
    help="Which option expiration dates to include",
)

chart_type = st.sidebar.selectbox(
    "Chart Type",
    ["ohlc4", "candlestick"],
    format_func=lambda x: "OHLC/4 Average (Default)" if x == "ohlc4" else "Candlestick (Full OHLC)",
    help="Price chart visualization type",
)

# ============================================================================
# Real-Time Refresh Countdown Timer
# ============================================================================

# Create placeholders for timer and timestamps
timer_placeholder = st.sidebar.empty()
timestamps_placeholder = st.sidebar.empty()

# Update timer in real-time every second
import threading

def update_timer():
    """Update the countdown timer every second"""
    while True:
        current_time = time.time()
        time_since_refresh = current_time - st.session_state.last_refresh

        if time_since_refresh >= REFRESH_INTERVAL:
            # Time to refresh
            st.session_state.last_refresh = current_time
            st.rerun()

        # Calculate time until refresh
        seconds_remaining = REFRESH_INTERVAL - time_since_refresh
        minutes = int(seconds_remaining // 60)
        seconds = int(seconds_remaining % 60)

        # Get last updated and next update times
        last_updated = datetime.fromtimestamp(st.session_state.last_refresh)
        next_update = datetime.fromtimestamp(st.session_state.last_refresh + REFRESH_INTERVAL)

        # Update the timer placeholder
        timer_placeholder.markdown(
            f"**⏱️ Auto-refresh in:** {minutes}:{seconds:02d}"
        )

        # Update the timestamps placeholder
        timestamps_placeholder.markdown(
            f"📊 Last updated: {last_updated.strftime('%H:%M:%S')}\n\n"
            f"⏰ Next update: {next_update.strftime('%H:%M:%S')}"
        )

        # Sleep for 0.1 seconds and check again
        time.sleep(0.1)

# Start timer thread (only if not already running)
if "timer_thread" not in st.session_state:
    st.session_state.timer_thread = threading.Thread(target=update_timer, daemon=True)
    st.session_state.timer_thread.start()

# ============================================================================
# Data Fetching with Caching
# ============================================================================

@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_and_process_data(ticker: str, expiration: str):
    """Fetch option data and process it."""
    try:
        # Fetch data from API
        try:
            spot_price, chain_data, history_data = asyncio.run(
                fetch_data(ticker, expiration)
            )
        except RuntimeError:
            # Handle asyncio.run() in already-running event loop (Streamlit issue)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            spot_price, chain_data, history_data = loop.run_until_complete(
                fetch_data(ticker, expiration)
            )
            loop.close()

        if not chain_data:
            st.error(f"❌ No option chain data received for {ticker}")
            return None, None, None, None, None

        # Parse contracts
        contracts = OptionParser.parse_option_chain(ticker, chain_data)

        if not contracts:
            st.error(f"❌ No contracts parsed from chain data")
            return None, None, None, None, None

        # Calculate GEX
        calculator = GEXCalculator()
        snapshot = calculator.calculate_gex(contracts, spot_price)

        if not snapshot or not snapshot.levels:
            st.error(f"❌ No gamma data available - contracts may lack required fields")
            return None, None, None, None, None

        # Extract strike_data
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

        return spot_price, snapshot, contracts, strike_data, history_data

    except Exception as e:
        import traceback
        st.error(f"❌ Error fetching data: {str(e)}")
        st.error(f"📋 Details: {traceback.format_exc()}")
        return None, None, None, None, None


# ============================================================================
# Main Display Logic
# ============================================================================

# Add "Generate" button in sidebar
if st.sidebar.button("🔄 Generate Dashboard", width="stretch"):
    st.session_state.generate_clicked = True

# Generate on load or button click
if not hasattr(st.session_state, "generate_clicked"):
    st.session_state.generate_clicked = True

if st.session_state.generate_clicked:
    with st.spinner(f"📡 Fetching data for {ticker}..."):
        spot_price, snapshot, contracts, strike_data, history_data = (
            fetch_and_process_data(ticker, expiration)
        )

        if spot_price is not None and snapshot is not None:
            # Display summary metrics
            st.sidebar.markdown("---")
            st.sidebar.markdown("### Summary")

            col1, col2 = st.sidebar.columns(2)
            with col1:
                st.metric("Spot Price", f"${spot_price:.2f}")
            with col2:
                st.metric("Strikes Analyzed", len(snapshot.levels))

            # Create and display dashboard
            st.markdown("---")

            try:
                fig = create_single_page_dashboard(
                    ticker,
                    spot_price,
                    snapshot,
                    contracts,
                    strike_data,
                    history_data,
                    chart_type,
                )

                # Display with full width
                st.plotly_chart(fig, width="stretch")

                # Display legend
                st.markdown("---")
                st.markdown("### Chart Legend")

                col1, col2, col3 = st.columns(3)

                with col1:
                    st.markdown(
                        """
                    **Chart 1: Price + Gamma Heatmap**
                    - 🟢 GREEN heatmap = Support (positive gamma)
                    - 🔴 RED heatmap = Resistance (negative gamma)
                    - ⚪ WHITE line = OHLC/4 average price
                    """
                    )

                with col2:
                    st.markdown(
                        """
                    **Chart 2: Net Gamma Exposure**
                    - 📊 Bar chart by strike
                    - 🟢 GREEN bars = Bullish zones
                    - 🔴 RED bars = Bearish zones
                    - 🟡 GOLD bars = Extremes
                    """
                    )

                with col3:
                    st.markdown(
                        """
                    **Chart 3: GEX Analysis**
                    - 🔵 CYAN line = Total gamma
                    - 🟢 GREEN area = Call gamma
                    - 🔴 RED area = Put gamma
                    - ⚪ WHITE line = Current price
                    """
                    )

            except Exception as e:
                st.error(f"❌ Error creating dashboard: {str(e)}")

        else:
            st.warning(f"⚠️ Could not fetch data for {ticker}. Please check the ticker symbol.")

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: gray; font-size: 0.85em;'>
    GEX Dashboard • Gamma Exposure Analysis • Auto-refreshes every 5 minutes
    </div>
    """,
    unsafe_allow_html=True,
)
