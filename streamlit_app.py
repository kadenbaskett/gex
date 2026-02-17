#!/usr/bin/env python3
"""Interactive Streamlit app for GEX Dashboard with auto-refresh."""

import asyncio
import time
import streamlit as st
from src.config.settings import settings
from src.services.option_parser import OptionParser
from src.services.gex_calculator import GEXCalculator
from plot_gex import fetch_data, create_single_page_dashboard

# ============================================================================
# Page Configuration
# ============================================================================

st.set_page_config(
    page_title="GEX Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# Auto-Refresh Timer
# ============================================================================

REFRESH_INTERVAL = 300  # 5 minutes in seconds

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

current_time = time.time()
time_since_refresh = current_time - st.session_state.last_refresh

if time_since_refresh >= REFRESH_INTERVAL:
    st.session_state.last_refresh = current_time
    st.rerun()

# Display refresh countdown in sidebar
minutes_until_refresh = (REFRESH_INTERVAL - time_since_refresh) / 60
st.sidebar.markdown(f"**Auto-refresh in:** {minutes_until_refresh:.1f} min")

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
    ["candlestick", "ohlc"],
    format_func=lambda x: "Candlestick (Full OHLC)" if x == "candlestick" else "OHLC/4 Average",
    help="Price chart visualization type",
)

# ============================================================================
# Data Fetching with Caching
# ============================================================================

@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_and_process_data(ticker: str, expiration: str):
    """Fetch option data and process it."""
    try:
        # Fetch data from API
        spot_price, chain_data = asyncio.run(
            fetch_data(ticker, expiration)
        )

        # Parse contracts
        contracts = OptionParser.parse_option_chain(ticker, chain_data)

        # Calculate GEX
        calculator = GEXCalculator()
        snapshot = calculator.calculate_gex(contracts, spot_price)

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

        return spot_price, snapshot, contracts, strike_data

    except Exception as e:
        st.error(f"❌ Error fetching data: {str(e)}")
        return None, None, None, None


# ============================================================================
# Main Display Logic
# ============================================================================

# Add "Generate" button in sidebar
if st.sidebar.button("🔄 Generate Dashboard", use_container_width=True):
    st.session_state.generate_clicked = True

# Generate on load or button click
if not hasattr(st.session_state, "generate_clicked"):
    st.session_state.generate_clicked = True

if st.session_state.generate_clicked:
    with st.spinner(f"📡 Fetching data for {ticker}..."):
        spot_price, snapshot, contracts, strike_data = (
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
                )

                # Display with full width
                st.plotly_chart(fig, use_container_width=True)

                # Display legend
                st.markdown("---")
                st.markdown("### Chart Legend")

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(
                        """
                    **Chart 1: Gamma Exposure Analysis**
                    - 🔵 CYAN line = Total gamma exposure
                    - 🟢 GREEN area = Call gamma (Bullish)
                    - 🔴 RED area = Put gamma (Bearish)
                    - ⚪ WHITE line = Current price
                    """
                    )

                with col2:
                    st.markdown(
                        """
                    **Chart 2: Net Gamma Exposure**
                    - 📊 Bar chart by strike
                    - 🟢 GREEN bars = Bullish (support)
                    - 🔴 RED bars = Bearish (resistance)
                    - 🟡 GOLD bars = Extremes
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
