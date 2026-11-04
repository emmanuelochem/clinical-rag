"""Pre-download and load model weights (embeddings + reranker). Run at image build time:

    python -m app.warmup
"""

import asyncio

from app.config import get_settings
from app.services import build_services


def main() -> None:
    svc = build_services(get_settings())
    print(asyncio.run(svc.warm_up()))


if __name__ == "__main__":
    main()
