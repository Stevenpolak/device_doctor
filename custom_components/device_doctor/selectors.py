"""Selectors shared by the repair flow and the rule flow."""

from __future__ import annotations

from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import ALLOWED_OFFLINE_SECONDS, ALWAYS


def allowed_offline_selector(include_always: bool = True) -> SelectSelector:
    """Pick how long something may be offline (labels in translations)."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                key
                for key in ALLOWED_OFFLINE_SECONDS
                if include_always or key != ALWAYS
            ],
            translation_key="allowed_offline",
            mode=SelectSelectorMode.LIST,
        )
    )
