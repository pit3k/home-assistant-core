"""Support for Broadlink air purifiers."""

from typing import Any

from broadlink.purifier import FanMode

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DOMAINS_AND_TYPES
from .device import BroadlinkDevice
from .entity import BroadlinkEntity

MAX_FAN_SPEED = 121


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Broadling fans based on a config entry."""
    device = hass.data[DOMAIN].devices[config_entry.entry_id]

    if device.api.type in DOMAINS_AND_TYPES[Platform.FAN]:
        async_add_entities([LifaAirPurifierFan(device)])


def _fan_percentage_to_speed(percentage: int) -> int:
    return round(MAX_FAN_SPEED * percentage / 100)


def _fan_speed_to_percentage(fan_speed: int) -> int:
    return round(100 * fan_speed / MAX_FAN_SPEED)


def _fan_mode_to_name(fan_mode: FanMode) -> str:
    return fan_mode.name.lower()


def _fan_name_to_mode(fan_mode_name: str) -> FanMode:
    return FanMode[fan_mode_name.upper()]


class LifaAirPurifierFan(BroadlinkEntity, FanEntity):
    """Representation of a Broadlink LIFAair fan entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "lifaair"
    _attr_supported_features = FanEntityFeature.PRESET_MODE | FanEntityFeature.SET_SPEED
    _attr_preset_modes = [
        _fan_mode_to_name(e) for e in FanMode if e not in (FanMode.OFF, FanMode.UNKNOWN)
    ]
    _attr_speed_count = 100

    def __init__(self, device: BroadlinkDevice) -> None:
        """Initialize the LIFAair fan entity."""
        super().__init__(device)
        self._attr_unique_id = device.unique_id

    @callback
    def _update_state(self, data: dict[str, Any]) -> None:
        """Update fan state."""
        fan_mode = data.get("fan_mode")
        self._attr_available = fan_mode is not None
        if self.available:
            self._attr_preset_mode = (
                _fan_mode_to_name(fan_mode) if fan_mode != FanMode.OFF else None
            )

            fan_speed = data.get("fan_speed")
            if fan_speed is not None:
                self._attr_percentage = _fan_speed_to_percentage(fan_speed)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        fan_mode = _fan_name_to_mode(preset_mode)
        if fan_mode == FanMode.MANUAL:
            # Switch to MANUAL mode while preserving current fan speed
            p = self.percentage
            await self.async_set_percentage(p if p is not None else 50)
        else:
            wasSetToAuto = await self._async_turn_on_if_needed()
            if not (wasSetToAuto and fan_mode == FanMode.AUTO):
                await self._async_request(self._device.api.set_fan_mode, fan_mode)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        await self._async_turn_on_if_needed()
        fan_speed = _fan_percentage_to_speed(percentage)
        await self._async_request(self._device.api.set_fan_speed, fan_speed)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan. Use AUTO mode if no mode given. Providing percentag forces MANUAL mode."""
        if percentage is not None:
            await self.async_set_percentage(percentage)
        elif preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        else:
            await self._async_turn_on_if_needed(force=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self._async_request(self._device.api.set_fan_mode, FanMode.OFF)

    async def _async_turn_on_if_needed(self, force: bool = False) -> bool:
        # If the fan is turned off we need to set it to AUTO mode before sending any other commands.
        # Otherwise, fan rejects them with -5 error.
        if force or self.preset_mode is None:
            await self._device.async_request(
                self._device.api.set_fan_mode, FanMode.AUTO
            )
            return True
        return False

    async def _async_request(self, function, *args, **kwargs) -> None:
        # All state setting api calls also return current updated state,
        # so we use it to immediately update HA state without waiting for next refresh.
        data = await self._device.async_request(function, *args, **kwargs)
        self._coordinator.async_set_updated_data(data)
