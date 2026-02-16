"""One-time Schwab OAuth authentication to create token.json"""

from schwab.auth import client_from_login_flow
from src.config.settings import settings


def authenticate() -> bool:
    """Authenticate with Schwab OAuth and save token."""
    print("\n" + "=" * 60)
    print("Schwab OAuth Authentication")
    print("=" * 60)
    print("\nThis will open your browser for Schwab login.")
    print("After login, you'll be redirected to your callback URL.")
    print("\n")

    try:
        # Create authenticated client via OAuth login flow
        # NOTE: This is NOT async - it opens browser and waits for redirect
        client = client_from_login_flow(
            api_key=settings.schwab_api_key,
            app_secret=settings.schwab_app_secret,
            callback_url=settings.schwab_callback_url,
            token_path=str(settings.token_path),
            asyncio=True,  # Client will support async calls
        )

        print("\n✅ Authentication successful!")
        print(f"Token saved to: {settings.token_path}")
        print("\nYou can now run:")
        print("  python -m src.main --ticker SPY")
        return True

    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")
        print("\nTroubleshooting:")
        print("1. Verify SCHWAB_API_KEY in .env is correct")
        print("2. Verify SCHWAB_APP_SECRET in .env is correct")
        print("3. Verify SCHWAB_CALLBACK_URL matches your app settings")
        print(f"\nYour settings:")
        print(f"  API Key: {settings.schwab_api_key[:10]}...")
        print(f"  Callback URL: {settings.schwab_callback_url}")
        return False


if __name__ == "__main__":
    success = authenticate()
    exit(0 if success else 1)
