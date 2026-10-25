"""On-demand camera images through Home Assistant's authenticated camera API."""

import logging
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN, INPUTS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VimarCamera(entry, runtime, *item) for item in INPUTS])


class VimarCamera(Camera):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, entry, runtime, input_id, key, name):
        super().__init__()
        self.stream_options = {"rtsp_transport": "tcp"}
        self.runtime = runtime
        self.input_id = input_id
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name="Vimar View Door",
            manufacturer="Vimar",
            model="K42955 (experimental)",
        )

    async def async_camera_image(self, width=None, height=None):
        try:
            image = await self.runtime.image(self.input_id)
        except Exception:
            # Exceptions from the protocol can carry credentials: never log them.
            _LOGGER.warning("View Door image unavailable on input %s", self.input_id)
            return None
        return image

    async def stream_source(self):
        return await self.runtime.stream_source(self.input_id)
