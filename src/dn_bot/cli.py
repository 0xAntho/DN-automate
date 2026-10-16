"""Point d'entrée en ligne de commande : `dn-bot scan`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

from dn_bot.config import load_config
from dn_bot.exchanges import build_readers
from dn_bot.scanner.report import format_result
from dn_bot.scanner.runner import Scanner
from dn_bot.storage import Storage


async def _scan(config_path: str, once: bool) -> None:
    config = load_config(config_path)
    readers = build_readers(config.exchanges)
    storage = Storage(config.database_path) if config.database_path else None
    scanner = Scanner(config, readers, storage)
    try:
        if once:
            print(format_result(await scanner.scan_once()))
        else:
            await scanner.run_forever(lambda r: print(format_result(r), end="\n\n", flush=True))
    finally:
        for reader in readers.values():
            await reader.aclose()
        if storage is not None:
            storage.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dn-bot")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="scanner les opportunités (lecture seule, aucun ordre)")
    scan.add_argument("--config", default="config.toml")
    scan.add_argument("--once", action="store_true", help="un seul passage puis sortie")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "scan":
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(_scan(args.config, args.once))


if __name__ == "__main__":
    main()
