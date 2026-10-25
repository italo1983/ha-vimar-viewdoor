"""Local image integration for Vimar View Door kits."""

from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP
from .const import DOMAIN
from .runtime import DeviceRuntime

PLATFORMS = [Platform.CAMERA, Platform.BUTTON]


async def async_setup_entry(hass, entry):
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = DeviceRuntime(hass, entry.data)

    async def stop(_event):
        await hass.data[DOMAIN][entry.entry_id].close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        runtime = hass.data[DOMAIN][entry.entry_id]
        await runtime.close()
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
