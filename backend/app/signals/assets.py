"""Turning the pair written in a message into the asset name Quotex uses."""

from __future__ import annotations

from app.domain.enums import AssetSuffixMode

OTC_SUFFIX = "_otc"


def quotex_asset(base_asset: str, mode: AssetSuffixMode, *, otc_mentioned: bool) -> str:
    """`EURUSD` or `EURUSD_otc`, by the group's choice.

    OTC: always the OTC market (groups that trade weekends/off-hours). NONE: always the real market.
    AUTO: OTC only when the message itself says OTC. The old bot guessed from the letters of the
    pair, which is exactly what this replaces with an explicit per-group setting.
    """
    wants_otc = mode is AssetSuffixMode.OTC or (mode is AssetSuffixMode.AUTO and otc_mentioned)
    return f"{base_asset}{OTC_SUFFIX}" if wants_otc else base_asset
