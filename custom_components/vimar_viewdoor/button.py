"""Momentary pedestrian and driveway gate controls (mapping requires testing)."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .controls import GateCommandError, GateTarget


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GateButton(
                entry, runtime, "pedestrian", "Apri cancelletto", "mdi:gate", "pedestrian_output", 1
            ),
            GateButton(
                entry,
                runtime,
                "driveway",
                "Apri cancello carrabile",
                "mdi:gate-arrow-right",
                "driveway_output",
                2,
            ),
        ]
    )


class GateButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, runtime, key, name, icon, option, default):
        self.entry = entry
        self.runtime = runtime
        self.target_key = key
        self.output_option = option
        self.default_output = default
        self._attr_unique_id = f"{entry.unique_id}_{key}_open"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})

    async def async_press(self):
        if self.runtime.closed:
            raise HomeAssistantError("Integrazione non disponibile.")
        options = self.entry.options
        target = GateTarget(self.target_key, options.get(self.output_option, self.default_output))
        try:
            await self.runtime.press_gate(target, options)
        except GateCommandError as exc:
            raise HomeAssistantError(str(exc)) from None
