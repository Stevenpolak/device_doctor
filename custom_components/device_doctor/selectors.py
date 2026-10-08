"""Selectors shared by the repair flow and the rule flow."""

from __future__ import annotations

from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import ALLOWED_OFFLINE_SECONDS


def allowed_offline_selector() -> SelectSelector:
    """Pick how long something may be offline (labels in translations)."""
    return SelectSelector(
        SelectSelectorConfig(
            options=list(ALLOWED_OFFLINE_SECONDS),
            translation_key="allowed_offline",
            mode=SelectSelectorMode.LIST,
        )
    )
