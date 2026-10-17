"""Exercise the installed wheel from a temporary working directory, without live sources.

Run with the project's dependency environment and --package-root pointing to a fresh
`uv pip install --no-deps --target ...` directory. No platform or model calls are made.
"""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path


async def verify(package_root: Path) -> None:
    sys.path.insert(0, str(package_root))
    import app

    if not Path(app.__file__).resolve().is_relative_to(package_root):
        raise RuntimeError("Smoke check imported source checkout instead of installed package")

    import httpx

    from app.main import app as application

    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://smoke") as client:
            for path, expected in {
                "/": "商品名称或购物需求",
                "/styles.css": ":root",
                "/app.js": "streamChat",
                "/helpers.mjs": "filterOffers",
                "/stream.mjs": "TextDecoder",
                "/evidence.mjs": "evidencePanel",
                "/favicon.svg": "<svg",
            }.items():
                response = await client.get(path)
                response.raise_for_status()
                if expected not in response.text:
                    raise RuntimeError(f"Installed resource content missing: {path}")
            health = await client.get("/health")
            if health.json() != {"status": "ok"}:
                raise RuntimeError("Health check failed")
            response = await client.post(
                "/api/chat", json={"query": "小米手环9", "data_mode": "sample"}
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("demo") or not result.get("offers"):
                raise RuntimeError("Packaged sample resources are unavailable")
            if not all(offer.get("match_report") for offer in result["offers"]):
                raise RuntimeError("Packaged sample title evidence is missing")
            response = await client.post(
                "/api/chat/stream", json={"query": "小米手环9", "data_mode": "sample"}
            )
            response.raise_for_status()
            if "event: result" not in response.text:
                raise RuntimeError("Packaged streaming endpoint failed")
    print("Installed wheel verified: homepage, static assets, health, sample query and SSE")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.package_root.resolve()
    if not (root / "app" / "main.py").is_file():
        parser.error("--package-root must contain the installed app package")
    with tempfile.TemporaryDirectory(prefix="shopping-package-smoke-") as temporary:
        previous = Path.cwd()
        try:
            os.chdir(temporary)  # Never read the developer's .env or database.
            os.environ["DATABASE_URL"] = f"sqlite:///{temporary}/smoke.db"
            os.environ["WEBBRIDGE_ENABLED"] = "false"
            os.environ["DEMO_MODE"] = "false"
            asyncio.run(verify(root))
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
