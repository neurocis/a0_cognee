import subprocess
import sys


def execute(**kwargs):
    """Health check and setup verification for Cognee plugin.

    Steps:
    1. Ensure dependencies are installed
    2. Verify aiohttp is importable
    3. Test connectivity to Cognee server
    """
    results = []

    # Step 1: Install dependencies
    try:
        from pathlib import Path

        req_file = Path(__file__).parent / "requirements.txt"
        if req_file.exists():
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        results.append("✅ Dependencies installed")
    except Exception as e:
        results.append(f"❌ Dependency install failed: {e}")
        return "\n".join(results)

    # Step 2: Verify aiohttp import
    try:
        import aiohttp  # noqa: F401

        results.append("✅ aiohttp is available")
    except ImportError:
        results.append("❌ aiohttp not available after install")
        return "\n".join(results)

    # Step 3: Test Cognee connectivity
    try:
        agent = kwargs.get("agent", None)
        context = kwargs.get("context", None)
        if agent and context:
            from helpers.cognee_helper import get_base_url, is_configured

            if not is_configured(agent):
                results.append(
                    "⚠️ Cognee not fully configured. "
                    "Set COGNEE_BASE_URL in Settings → Secrets."
                )
            else:
                import asyncio
                import aiohttp as _aiohttp

                base_url = get_base_url(agent)

                async def _check():
                    async with _aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{base_url}/api/health", timeout=_aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            return resp.status

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            status = pool.submit(
                                lambda: asyncio.run(_check())
                            ).result(timeout=10)
                    else:
                        status = loop.run_until_complete(_check())

                    if status == 200:
                        results.append(f"✅ Cognee server reachable at {base_url}")
                    else:
                        results.append(
                            f"⚠️ Cognee server returned status {status} at {base_url}"
                        )
                except Exception as e:
                    results.append(f"❌ Cannot reach Cognee server at {base_url}: {e}")
        else:
            results.append("⚠️ No agent/context available — skipping connectivity check")
    except Exception as e:
        results.append(f"❌ Connectivity check error: {e}")

    return "\n".join(results)
