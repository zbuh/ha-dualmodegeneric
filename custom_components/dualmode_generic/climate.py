"""
Adds support for generic thermostat units that have both heating and cooling.

Originally based on the script at this thread:
https://community.home-assistant.io/t/heat-cool-generic-thermostat/76443/2

Modified to better conform to modern Home Assistant custom_component style.

Modified again to support HEAT_COOL mode and a target range
Removed PRESET_AWAY as I don't need it, may reimplement it later
"""
import asyncio
import logging

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateDevice
from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE,
    ATTR_TARGET_TEMP_LOW,
    ATTR_TARGET_TEMP_HIGH,
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_TARGET_TEMPERATURE_RANGE,
    PRESET_NONE,
    PRESET_AWAY,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, callback
from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.3
DEFAULT_NAME = "Generic Thermostat"

CONF_HEATER = "heater"
CONF_COOLER = "cooler"
CONF_REVERSE_CYCLE = "reverse_cycle"
CONF_SENSOR = "target_sensor"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP_HIGH = "target_temp_high"
CONF_TARGET_TEMP_LOW = "target_temp_low"
CONF_MIN_DUR = "min_cycle_duration"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_PRECISION = "precision"
SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE_RANGE

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HEATER): cv.entity_id,
        vol.Required(CONF_COOLER): cv.entity_id,
        vol.Required(CONF_SENSOR): cv.entity_id,
        vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
        vol.Optional(CONF_MIN_DUR): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_REVERSE_CYCLE, default=False): cv.boolean,
        vol.Optional(CONF_COLD_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(CONF_HOT_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(CONF_TARGET_TEMP_HIGH): vol.Coerce(float),
        vol.Optional(CONF_TARGET_TEMP_LOW): vol.Coerce(float),
        vol.Optional(CONF_INITIAL_HVAC_MODE): vol.In(
            [HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_OFF, HVAC_MODE_HEAT_COOL]
        ),
        vol.Optional(CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    name = config.get(CONF_NAME)
    heater_entity_id = config.get(CONF_HEATER)
    cooler_entity_id = config.get(CONF_COOLER)
    sensor_entity_id = config.get(CONF_SENSOR)
    reverse_cycle = config.get(CONF_REVERSE_CYCLE)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp_high = config.get(CONF_TARGET_TEMP_HIGH)
    target_temp_low = config.get(CONF_TARGET_TEMP_LOW)
    min_cycle_duration = config.get(CONF_MIN_DUR)
    cold_tolerance = config.get(CONF_COLD_TOLERANCE)
    hot_tolerance = config.get(CONF_HOT_TOLERANCE)
    initial_hvac_mode = config.get(CONF_INITIAL_HVAC_MODE)
    precision = config.get(CONF_PRECISION)
    unit = hass.config.units.temperature_unit

    async_add_entities(
        [
            GenericThermostat(
                name,
                heater_entity_id,
                cooler_entity_id,
                sensor_entity_id,
                reverse_cycle,
                min_temp,
                max_temp,
                target_temp_high,
                target_temp_low,
                min_cycle_duration,
                cold_tolerance,
                hot_tolerance,
                initial_hvac_mode,
                precision,
                unit,
            )
        ]
    )


class GenericThermostat(ClimateDevice, RestoreEntity):
    """Representation of a Generic Thermostat device."""

    def __init__(
        self,
        name,
        heater_entity_id,
        cooler_entity_id,
        sensor_entity_id,
        reverse_cycle,
        min_temp,
        max_temp,
        target_temp_high,
        target_temp_low,
        min_cycle_duration,
        cold_tolerance,
        hot_tolerance,
        initial_hvac_mode,
        precision,
        unit,
    ):
        """Initialize the thermostat."""
        self._name = name
        self.heater_entity_id = heater_entity_id
        self.cooler_entity_id = cooler_entity_id
        self.sensor_entity_id = sensor_entity_id
        self.reverse_cycle = reverse_cycle
        self.min_cycle_duration = min_cycle_duration
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance
        self._hvac_mode = initial_hvac_mode
        self._temp_precision = precision
        self._hvac_list = [
            HVAC_MODE_COOL,
            HVAC_MODE_HEAT,
            HVAC_MODE_OFF,
            HVAC_MODE_HEAT_COOL,
        ]
        self._active = False
        self._cur_temp = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temp_high = target_temp_high
        self._target_temp_low = target_temp_low
        self._unit = unit
        self._support_flags = SUPPORT_FLAGS

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        async_track_state_change(
            self.hass, self.sensor_entity_id, self._async_sensor_changed
        )
        async_track_state_change(
            self.hass, self.heater_entity_id, self._async_switch_changed
        )
        async_track_state_change(
            self.hass, self.cooler_entity_id, self._async_switch_changed
        )

        @callback
        def _async_startup(event):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(sensor_state)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        old_state = await self.async_get_last_state()
        if old_state is not None:

            ## If we have a previously saved temperature
            if old_state.attributes.get(ATTR_TARGET_TEMP_LOW) is None:
                if self._hvac_mode == HVAC_MODE_COOL:
                    self._target_temp_low = self.max_temp
                else:
                    self._target_temp_low = self.min_temp
                _LOGGER.warning(
                    "Undefined target low temperature," "falling back to %s",
                    self._target_temp_low,
                )
            else:
                self._target_temp_low = float(
                    old_state.attributes[ATTR_TARGET_TEMP_LOW]
                )

                ## If we have a previously saved temperature
            if old_state.attributes.get(ATTR_TARGET_TEMP_HIGH) is None:
                if self._hvac_mode == HVAC_MODE_COOL:
                    self._target_temp_high = self.max_temp
                else:
                    self._target_temp_high = self.min_temp
                _LOGGER.warning(
                    "Undefined target high temperature," "falling back to %s",
                    self._target_temp_high,
                )
            else:
                self._target_temp_high = float(
                    old_state.attributes[ATTR_TARGET_TEMP_HIGH]
                )

            if old_state.attributes.get(ATTR_PRESET_MODE) == PRESET_AWAY:
                self._is_away = True
            if not self._hvac_mode and old_state.state:
                self._hvac_mode = old_state.state

        else:
            # No previous state, try and restore defaults
            if self._target_temp_high is None:
                self._target_temp_high = self.max_temp
            if self._target_temp_low is None:
                self._target_temp_low = self.min_temp

            # Set default state to off
            if not self._hvac_mode:
                self._hvac_mode = HVAC_MODE_OFF

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVAC_MODE_OFF:
            return CURRENT_HVAC_OFF
        if not self._is_device_active:
            return CURRENT_HVAC_IDLE
        if self._hvac_mode == HVAC_MODE_COOL:
            return CURRENT_HVAC_COOL
        if self._hvac_mode == HVAC_MODE_HEAT:
            return CURRENT_HVAC_HEAT
        if self._hvac_mode == HVAC_MODE_HEAT_COOL:
            if self.hass.states.is_state(self.heater_entity_id, STATE_ON):
                return CURRENT_HVAC_HEAT
            elif self.hass.states.is_state(self.cooler_entity_id, STATE_ON):
                return CURRENT_HVAC_COOL
            else:
                return CURRENT_HVAC_IDLE
        return CURRENT_HVAC_IDLE

    @property
    def target_temperature_high(self):
        """Return the temperature we try to reach."""
        return self._target_temp_high

    @property
    def target_temperature_low(self):
        """Return the temperature we try to reach."""
        return self._target_temp_low

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        if hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
            if self._is_device_active and not self.reverse_cycle:
                await self._async_cooler_turn_off()
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_COOL:
            self._hvac_mode = HVAC_MODE_COOL
            if self._is_device_active and not self.reverse_cycle:
                await self._async_heater_turn_off()
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_HEAT_COOL:
            self._hvac_mode = HVAC_MODE_HEAT_COOL
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_OFF:
            self._hvac_mode = HVAC_MODE_OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
                await self._async_cooler_turn_off()
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.schedule_update_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        self._target_temp_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        self._target_temp_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        await self._async_control_heating(force=True)
        await self.async_update_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    async def _async_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return
        if new_state == "unavailable":
            return

        self._async_update_temp(new_state)
        await self._async_control_heating()
        await self.async_update_ha_state()

    @callback
    def _async_switch_changed(self, entity_id, old_state, new_state):
        """Handle heater switch state changes."""
        if new_state is None:
            return
        self.async_schedule_update_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            self._cur_temp = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_control_heating(self, force=False):
        _LOGGER.debug("running _async_control_heating")
        """Check if we need to turn heating on or off."""
        async with self._temp_lock:
            if not self._active and None not in (
                self._cur_temp,
                self._target_temp_high,
                self._target_temp_low,
            ):
                self._active = True
                _LOGGER.info(
                    "Obtained current and target temperature. "
                    "Generic thermostat active. %s, %s, %s",
                    self._cur_temp,
                    self._target_temp_low,
                    self._target_temp_high,
                )

            if not self._active:
                _LOGGER.debug("not active")
                return

            if self._hvac_mode == HVAC_MODE_OFF:
                _LOGGER.debug("Mode is off")
                return

            if not force:
                _LOGGER.debug("force = false")
                # If the `force` argument is True, we
                # ignore `min_cycle_duration`.
                if self.min_cycle_duration:
                    _LOGGER.debug("min_cycle_duration = false")

                    if self._is_device_active:
                        current_state = STATE_ON
                    else:
                        current_state = HVAC_MODE_OFF
                    long_enough_cool = condition.state(
                        self.hass,
                        self.cooler_entity_id,
                        current_state,
                        self.min_cycle_duration,
                    )
                    long_enough_heat = condition.state(
                        self.hass,
                        self.heater_entity_id,
                        current_state,
                        self.min_cycle_duration,
                    )
                    if not (long_enough_cool or long_enough_heat):
                        _LOGGER.debug("not long enough")
                        return

            too_cold = self._target_temp_low - self._cur_temp >= self._cold_tolerance
            too_hot = self._cur_temp - self._target_temp_high >= self._hot_tolerance
            cool_enough = self._target_temp_high - self._cur_temp >= self._hot_tolerance
            warm_enough = self._cur_temp - self._target_temp_low >= self._cold_tolerance

            _LOGGER.debug(
                "States: too_cold=%s too_hot=%s cool_enough=%s warm_enough=%s",
                too_cold,
                too_hot,
                cool_enough,
                warm_enough,
            )
            _LOGGER.debug("Mode: %s, %s", self._hvac_mode, self._is_device_active)
            if self._is_device_active:  # when to turn off
                if cool_enough and self._hvac_mode in [
                    HVAC_MODE_COOL,
                    HVAC_MODE_HEAT_COOL,
                ]:
                    _LOGGER.info("Turning off cooler %s", self.cooler_entity_id)
                    await self._async_cooler_turn_off()
                if warm_enough and self._hvac_mode in [
                    HVAC_MODE_HEAT,
                    HVAC_MODE_HEAT_COOL,
                ]:
                    _LOGGER.info("Turning off heater %s", self.heater_entity_id)
                    await self._async_heater_turn_off()
            else:  # when to turn on
                if too_hot and (
                    self._hvac_mode == HVAC_MODE_COOL
                    or self._hvac_mode == HVAC_MODE_HEAT_COOL
                ):
                    _LOGGER.info("Turning on cooler %s", self.cooler_entity_id)
                    await self._async_cooler_turn_on()
                elif too_cold and (
                    self._hvac_mode == HVAC_MODE_HEAT
                    or self._hvac_mode == HVAC_MODE_HEAT_COOL
                ):
                    _LOGGER.info("Turning on heater %s", self.heater_entity_id)
                    await self._async_heater_turn_on()

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        return self.hass.states.is_state(
            self.heater_entity_id, STATE_ON
        ) or self.hass.states.is_state(self.cooler_entity_id, STATE_ON)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_ON, data)

    async def _async_heater_turn_off(self):
        """Turn heater toggleable device off."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_OFF, data)

    async def _async_cooler_turn_on(self):
        """Turn cooler toggleable device on."""
        data = {ATTR_ENTITY_ID: self.cooler_entity_id}
        await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_ON, data)

    async def _async_cooler_turn_off(self):
        """Turn cooler toggleable device off."""
        data = {ATTR_ENTITY_ID: self.cooler_entity_id}
        await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_OFF, data)
