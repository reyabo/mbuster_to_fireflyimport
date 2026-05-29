"""Parser registry and dispatch.

New export formats are added by implementing :class:`BaseParser` and listing
the class here.
"""

from __future__ import annotations

from ..models import ExportType, ParseResult
from .base import BaseParser, ParseError
from .cospend_json import CospendJsonParser
from .moneybuster_csv import MoneyBusterCsvParser

# Concrete parsers, ordered for auto-detection (most specific first).
_PARSERS: list[type[BaseParser]] = [CospendJsonParser, MoneyBusterCsvParser]

# Which parser classes are eligible for a given explicit export type.
_BY_TYPE: dict[ExportType, list[type[BaseParser]]] = {
    ExportType.json: [CospendJsonParser],
    ExportType.cospend: [CospendJsonParser, MoneyBusterCsvParser],
    ExportType.csv: [MoneyBusterCsvParser],
    ExportType.moneybuster: [MoneyBusterCsvParser],
}


def parse(
    content: bytes, filename: str = "", export_type: ExportType = ExportType.auto
) -> ParseResult:
    """Parse ``content`` into a :class:`ParseResult`, choosing a parser by type
    or by sniffing."""

    if export_type == ExportType.auto:
        for parser_cls in _PARSERS:
            if parser_cls.sniff(content, filename):
                return parser_cls().parse(content, filename)
        raise ParseError(
            "Format nicht erkannt. Bitte den Exporttyp explizit wählen "
            "(MoneyBuster/Cospend CSV oder Cospend JSON)."
        )

    candidates = _BY_TYPE.get(export_type, _PARSERS)
    # Prefer a candidate that sniffs positively, else use the first candidate.
    for parser_cls in candidates:
        if parser_cls.sniff(content, filename):
            return parser_cls().parse(content, filename)
    return candidates[0]().parse(content, filename)


__all__ = ["parse", "ParseError", "BaseParser"]
