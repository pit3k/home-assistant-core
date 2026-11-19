"""Tests for Broadlink fans."""

from unittest.mock import call

import broadlink_async as blk

from homeassistant.components.fan import (
    DOMAIN as FAN_DOMAIN,
    SERVICE_SET_PERCENTAGE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_ENTITY_ID, Platform, UnitOfDensity
from homeassistant.core import HomeAssistant

from . import get_device


async def test_lifaair_fan_setup(hass: HomeAssistant) -> None:
    """Test setting up a LIFAair fan."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    mock_api.get_state.return_value = {
        "co2": 425,
        "fan_mode": blk.lifaair.FanMode.AUTO,
        "fan_speed": 50,
        "formaldehyde": 0.03,
        "humidity": 41,
        "pm1": 5,
        "pm2_5": 7,
        "pm10": 9,
        "purifier_online": True,
        "temperature": 24.5,
        "tvoc": 150,
    }

    await device.setup_entry(hass, mock_api=mock_api)

    fan_state = hass.states.async_all(Platform.FAN)[0]
    assert fan_state.state == "on"
    assert fan_state.attributes["preset_mode"] == "auto"
    assert fan_state.attributes["percentage"] == 41

    sensor_states = hass.states.async_all(Platform.SENSOR)
    assert {state.state for state in sensor_states} >= {"0.03", "425", "150"}
    formaldehyde_state = next(state for state in sensor_states if state.state == "0.03")
    assert (
        formaldehyde_state.attributes["device_class"]
        == SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS
    )
    assert (
        formaldehyde_state.attributes["unit_of_measurement"]
        == UnitOfDensity.MILLIGRAMS_PER_CUBIC_METER
    )
    assert hass.states.async_all(Platform.BINARY_SENSOR)[0].state == "on"


async def test_lifaair_purifier_offline(hass: HomeAssistant) -> None:
    """Test the purifier offline state is exposed separately from the station."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    mock_api.get_state.return_value = {
        "fan_mode": None,
        "fan_speed": None,
        "temperature": None,
        "humidity": None,
        "purifier_online": False,
    }

    await device.setup_entry(hass, mock_api=mock_api)

    assert hass.states.async_all(Platform.FAN)[0].state == "unavailable"
    assert hass.states.async_all(Platform.BINARY_SENSOR)[0].state == "off"
    sensor_states = hass.states.async_all(Platform.SENSOR)
    assert len(sensor_states) == 2
    assert {state.state for state in sensor_states} == {"unavailable"}


async def test_lifaair_climate_sensors_unknown_when_online_without_readings(
    hass: HomeAssistant,
) -> None:
    """Test missing climate readings are unknown while the purifier is online."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    mock_api.get_state.return_value = {
        "fan_mode": blk.lifaair.FanMode.AUTO,
        "fan_speed": 30,
        "temperature": None,
        "humidity": None,
        "purifier_online": True,
    }

    await device.setup_entry(hass, mock_api=mock_api)

    sensor_states = hass.states.async_all(Platform.SENSOR)
    assert len(sensor_states) == 2
    assert {state.state for state in sensor_states} == {"unknown"}


async def test_lifaair_fan_turn_on_off(hass: HomeAssistant) -> None:
    """Test that the fan exposes working turn on and turn off services."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    fan_mode = blk.lifaair.FanMode
    mock_api.get_state.return_value = {
        "fan_mode": fan_mode.OFF,
        "fan_speed": 50,
        "purifier_online": True,
    }
    mock_api.set_fan_mode.side_effect = [
        {"fan_mode": fan_mode.AUTO, "fan_speed": 30, "purifier_online": True},
        {"fan_mode": fan_mode.OFF, "fan_speed": 30, "purifier_online": True},
    ]

    await device.setup_entry(hass, mock_api=mock_api)

    fan_entity_id = hass.states.async_all(Platform.FAN)[0].entity_id
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: fan_entity_id},
        blocking=True,
    )
    assert hass.states.get(fan_entity_id).state == "on"

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: fan_entity_id},
        blocking=True,
    )

    assert mock_api.set_fan_mode.await_args_list == [
        call(fan_mode.AUTO),
        call(fan_mode.OFF),
    ]
    assert hass.states.get(fan_entity_id).state == "off"


async def test_lifaair_fan_preset_from_off(hass: HomeAssistant) -> None:
    """Test setting a preset from off starts the fan before changing its mode."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    fan_mode = blk.lifaair.FanMode
    mock_api.get_state.return_value = {
        "fan_mode": fan_mode.OFF,
        "fan_speed": 50,
        "purifier_online": True,
    }
    mock_api.set_fan_mode.return_value = {
        "fan_mode": fan_mode.NIGHT,
        "fan_speed": 10,
        "purifier_online": True,
    }

    await device.setup_entry(hass, mock_api=mock_api)

    fan_state = hass.states.async_all(Platform.FAN)[0]
    assert fan_state.state == "off"

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: fan_state.entity_id, "preset_mode": "night"},
        blocking=True,
    )

    assert mock_api.set_fan_mode.await_args_list == [
        call(fan_mode.AUTO),
        call(fan_mode.NIGHT),
    ]
    assert hass.states.get(fan_state.entity_id).state == "on"


async def test_lifaair_manual_preset_sets_speed(hass: HomeAssistant) -> None:
    """Test the API's manual mode is entered through its speed setter."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    fan_mode = blk.lifaair.FanMode
    mock_api.get_state.return_value = {
        "fan_mode": fan_mode.AUTO,
        "fan_speed": 60,
        "purifier_online": True,
    }
    mock_api.set_fan_speed.return_value = {
        "fan_mode": fan_mode.MANUAL,
        "fan_speed": 60,
        "purifier_online": True,
    }

    await device.setup_entry(hass, mock_api=mock_api)

    fan_state = hass.states.async_all(Platform.FAN)[0]
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: fan_state.entity_id, "preset_mode": "manual"},
        blocking=True,
    )

    mock_api.set_fan_speed.assert_awaited_once_with(60)
    mock_api.set_fan_mode.assert_not_awaited()


async def test_lifaair_manual_preset_with_zero_auto_speed(hass: HomeAssistant) -> None:
    """Test selecting manual while auto is stopped uses the fallback speed."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    fan_mode = blk.lifaair.FanMode
    mock_api.get_state.return_value = {
        "fan_mode": fan_mode.AUTO,
        "fan_speed": 0,
        "purifier_online": True,
    }
    mock_api.set_fan_speed.return_value = {
        "fan_mode": fan_mode.MANUAL,
        "fan_speed": 60,
        "purifier_online": True,
    }

    await device.setup_entry(hass, mock_api=mock_api)

    fan_entity_id = hass.states.async_all(Platform.FAN)[0].entity_id
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: fan_entity_id, "preset_mode": "manual"},
        blocking=True,
    )

    mock_api.set_fan_speed.assert_awaited_once_with(60)
    mock_api.set_fan_mode.assert_not_awaited()


async def test_lifaair_zero_percentage_turns_off(hass: HomeAssistant) -> None:
    """Test zero percent uses OFF mode instead of setting a manual speed."""
    device = get_device("Air purifier")
    mock_api = device.get_mock_api()
    fan_mode = blk.lifaair.FanMode
    mock_api.get_state.return_value = {
        "fan_mode": fan_mode.AUTO,
        "fan_speed": 60,
        "purifier_online": True,
    }
    mock_api.set_fan_mode.return_value = {
        "fan_mode": fan_mode.OFF,
        "fan_speed": 60,
        "purifier_online": True,
    }

    await device.setup_entry(hass, mock_api=mock_api)

    fan_state = hass.states.async_all(Platform.FAN)[0]
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PERCENTAGE,
        {ATTR_ENTITY_ID: fan_state.entity_id, "percentage": 0},
        blocking=True,
    )

    mock_api.set_fan_mode.assert_awaited_once_with(fan_mode.OFF)
    mock_api.set_fan_speed.assert_not_awaited()
    assert hass.states.get(fan_state.entity_id).state == "off"
