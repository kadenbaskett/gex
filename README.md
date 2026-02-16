# Schwab GEX Streaming

Stream real-time options data and calculate Gamma Exposure (GEX) levels using the Schwab API.

## Overview

This project connects to the Charles Schwab streaming API to fetch option chain data and calculate gamma exposure levels by strike price. Gamma exposure measures the sensitivity of delta to changes in the underlying price—a key metric for options traders and market makers.

**Gamma Exposure Formula:**
```
GEX = gamma × open_interest × 100 × spot_price²
```

## Features

- **Real-time streaming** of option chain data via Schwab WebSocket API
- **Gamma exposure calculation** separated by calls, puts, and total
- **Top strikes view** sorted by absolute gamma exposure
- **Clean architecture** with separation of concerns
- **Async/await** for non-blocking I/O
- **Type hints** throughout for IDE support
- **Unit tests** for calculations and parsing

## Project Structure

```
schwab-gex/
├── src/
│   ├── config/           # Settings and configuration
│   ├── models/           # Pydantic data models
│   ├── services/         # Business logic (GEX calculation, parsing)
│   ├── streaming/        # Schwab API client
│   └── main.py           # CLI entry point
├── tests/                # Unit tests
├── pyproject.toml        # Python package config
├── .env.example          # Example environment variables
└── README.md             # This file
```

## Setup

### 1. Prerequisites

- Python 3.11+
- Schwab account with API access
- Schwab API credentials

### 2. Install Dependencies

```bash
pip install -e ".[dev]"
```

Or with poetry:
```bash
poetry install
```

### 3. Create Schwab App Credentials

1. Log in to your Schwab account
2. Go to Developer Center → Apps
3. Create a new application
4. Note your:
   - API Key
   - App Secret
   - Callback URL (can be https://localhost:8888/callback)

### 4. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```
SCHWAB_API_KEY=your_api_key
SCHWAB_APP_SECRET=your_app_secret
SCHWAB_CALLBACK_URL=https://localhost:8888/callback
SCHWAB_TOKEN_PATH=token.json
STREAM_REFRESH_INTERVAL=5
LOG_LEVEL=INFO
```

### 5. Authenticate (First Time)

The first time you run the app, it will guide you through Schwab OAuth authentication and save the token to `token.json`.

## Usage

### Basic Usage

Stream GEX data for a ticker:

```bash
python -m src.main --ticker SPY
```

Output example:
```
============================================================
Ticker: SPY
Spot: $502.13
Updated: 14:23:45
============================================================

Strike     Total GEX            Call GEX              Put GEX
---------------------------------------------------------------
$500.00    12,400,000.00        8,900,000.00         3,500,000.00
$505.00    9,200,000.00         7,100,000.00         2,100,000.00
$510.00    -6,100,000.00        2,200,000.00         -8,300,000.00
...
```

### With Options

```bash
# Save snapshot every 30 seconds
python -m src.main --ticker QQQ --save-interval 30
```

This will save snapshots to `gex_snapshot.json`.

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src

# Run specific test
pytest tests/test_gex.py::TestGEXCalculation::test_calculate_gex_full
```

## API Reference

### GEXCalculator

```python
from src.services.gex_calculator import GEXCalculator
from src.models.option_models import OptionContract

# Calculate gamma exposure
snapshot = GEXCalculator.calculate_gex(contracts, spot_price=502.0)

# Access results
for strike, level in snapshot.levels.items():
    print(f"Strike {strike}: Total GEX = {level.total_gex}")

# Get top strikes
top_10 = snapshot.top_strikes(n=10)

# Filter to ATM range
filtered = GEXCalculator.filter_strikes(snapshot, range_multiplier=20)
```

### OptionParser

```python
from src.services.option_parser import OptionParser

# Parse Schwab response
contracts = OptionParser.parse_option_chain("SPY", raw_schwab_data)

# Extract spot price
spot = OptionParser.extract_spot_price(raw_schwab_data)
```

### SchwabStreamClient

```python
from src.streaming.schwab_stream import SchwabStreamClient

client = SchwabStreamClient("SPY")

# Stream option data
async for contracts, spot_price in client.stream_options():
    print(f"Got {len(contracts)} contracts at {spot_price}")
```

## Data Models

### OptionContract
```python
@dataclass
ticker: str              # Stock ticker
strike: float            # Strike price
expiration: datetime     # Option expiration
gamma: float             # Greek gamma value
open_interest: int       # Number of open contracts
option_type: OptionType  # CALL or PUT
```

### GammaLevel
```python
strike: float        # Strike price
call_gex: float      # Call gamma exposure
put_gex: float       # Put gamma exposure
total_gex: float     # Sum of call and put
```

### GammaSnapshot
```python
ticker: str                              # Ticker symbol
timestamp: datetime                      # When snapshot was taken
spot_price: float                        # Current spot price
levels: dict[float, GammaLevel]         # GEX by strike
```

## Extending the Project

### Add Database Storage

```python
from sqlalchemy import create_engine

# Store snapshots in database
engine = create_engine("postgresql://...")
snapshot.to_sql(engine, table_name="gamma_snapshots")
```

### Add REST API

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/gex/{ticker}")
async def get_gex(ticker: str):
    # Stream GEX and return latest snapshot
    pass
```

### Add Dashboard

Visualize gamma levels with:
- Plotly for interactive charts
- Streamlit for quick UI
- React with WebSocket connection

### Add Multiple Tickers

```python
import asyncio

async def main():
    tasks = [
        GEXStreamApp(ticker).start()
        for ticker in ["SPY", "QQQ", "IWM"]
    ]
    await asyncio.gather(*tasks)
```

## Architecture Notes

### Streaming Layer (`streaming/`)
- Handles Schwab WebSocket connection
- No calculations
- Passes raw data to services
- Manages reconnection logic

### Services Layer (`services/`)
- **OptionParser**: Converts raw Schwab data to OptionContract objects
- **GEXCalculator**: Implements gamma exposure formula, strike filtering, aggregation

### Models Layer (`models/`)
- **OptionContract**: Single option with all Greeks and pricing
- **GammaLevel**: GEX aggregated by strike
- **GammaSnapshot**: Complete market snapshot with all strikes

### Config Layer (`config/`)
- Environment variable management
- Logging setup
- Settings validation

## Troubleshooting

### Connection Failed
- Check SCHWAB_API_KEY and SCHWAB_APP_SECRET
- Verify callback URL matches your app settings
- Delete token.json and re-authenticate

### No Data Received
- Verify ticker symbol is valid
- Check market hours (streaming data may be limited outside 9:30am-4:00pm ET)
- Review logs with LOG_LEVEL=DEBUG

### Import Errors
- Ensure Python 3.11+: `python --version`
- Reinstall dependencies: `pip install -e ".[dev]"`

## License

MIT

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Disclaimer

This tool is for educational and research purposes. Options trading involves significant risk. Always consult a financial advisor before making trading decisions. Past performance does not guarantee future results.
