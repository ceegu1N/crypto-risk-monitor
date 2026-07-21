"""One-off maintenance command for correcting historical quote volume."""

import argparse

from app.collector import rebuild_quote_volume, report_result
from app.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebaixa candles encerrados e corrige o volume financeiro da cotação"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="quantidade de dias históricos a reprocessar (padrão: 90)",
    )
    args = parser.parse_args(argv)

    result = rebuild_quote_volume(get_settings(), days=args.days)
    report_result(result)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
