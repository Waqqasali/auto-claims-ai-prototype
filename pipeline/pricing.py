"""Costing. STUBBED pricing source.

In production this is a live integration with a parts and labor pricing
database or the carrier's negotiated vendor price lists.

This is deliberately stubbed rather than built. The integration is
conventional systems work — an API client, a data mapping, a cache — and it
demonstrates no product judgment. Spending prototype budget here would
displace the components where the actual uncertainty lives.

Not AI. Price lookup is a table read. Using a model to guess prices would be
strictly worse than a table, and unauditable besides.

The `priced` flag matters downstream: a line item the costing stage cannot
price is a signal that the assessment stage produced something unusual, and
it feeds the cross-stage agreement component of the confidence score.
"""

import json
import os

from config import DATA_DIR
from pipeline.models import LineItem

_CACHE: dict | None = None


def _table() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(os.path.join(DATA_DIR, "price_table.json"), encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def price_line(item: LineItem) -> LineItem:
    """STUB BOUNDARY. Replace this body with a pricing API call."""
    table = _table()
    key = f"{item.operation}|{item.panel}"
    entry = table["operations"].get(key)

    if entry is None:
        item.price = None
        item.priced = False
        return item

    total = (
        entry["part"]
        + entry["labour_hours"] * table["labour_rate_per_hour"]
        + entry["paint_hours"] * table["paint_rate_per_hour"]
    )
    item.price = round(total, 2)
    item.priced = True
    return item


def price_all(items: list[LineItem]) -> list[LineItem]:
    return [price_line(i) for i in items]


def agreement_score(items: list[LineItem]) -> float:
    """Cross-stage agreement: what share of identified line items could be priced?

    Against a complete production catalogue, an item the pricing stage cannot
    resolve means the assessment stage produced an operation or panel
    combination outside the expected vocabulary, which is a reason to trust the
    whole assessment less. Against this stub catalogue it can also be a simple
    gap: CLM-1007's rocker panel repair is one, since the stub carries no rocker
    operations while real estimating databases do. Either way the total is
    incomplete, and the score says so.
    """
    if not items:
        return 0.0
    return round(sum(1 for i in items if i.priced) / len(items), 3)


IS_STUBBED = True
STUB_NOTE = (
    "Flat indicative rates from a local table. No regional variation, no "
    "vehicle-specific part numbers, no DRP-negotiated rates, no parts "
    "availability. Totals are illustrative and should not be read as accurate."
)
