"""Actions for Device Doctor."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState, OperationNotAllowed
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, SERVICE_RELOAD_PROBLEMS
from .coordinator import KIND_ENTRY, DeviceDoctorConfigEntry


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def reload_problems(call: ServiceCall) -> ServiceResponse:
        """Reload every integration with a confirmed problem."""
        entry: DeviceDoctorConfigEntry | None = next(
            (
                entry
                for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.state is ConfigEntryState.LOADED
            ),
            None,
        )
        if entry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_loaded"
            )

        problems = [
            problem
            for problem in entry.runtime_data.data.confirmed.values()
            if problem.kind == KIND_ENTRY
        ]
        reloaded: list[str] = []
        failed: list[str] = []
        for problem in problems:
            try:
                ok = await hass.config_entries.async_reload(problem.entry_id)
            except OperationNotAllowed:
                ok = False
            (reloaded if ok else failed).append(problem.title)

        if call.return_response:
            return {"reloaded": reloaded, "failed": failed}
        return None

    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD_PROBLEMS,
        reload_problems,
        supports_response=SupportsResponse.OPTIONAL,
    )
