"""Config flow for Libe Solar & Electricity Optimization."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_BATTERY_SOC, CONF_BATTERY_CAPACITY, CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_RESERVE_SOC, CONF_PV_POWER, CONF_PV_FORECAST_TODAY,
    CONF_GRID_IMPORT, CONF_GRID_EXPORT, CONF_HOUSE_CONSUMPTION,
    CONF_BATTERY_CHARGE_MODE, CONF_BATTERY_DISCHARGE_MODE,
    CONF_BATTERY_CHARGE_POWER, CONF_PUN_SENSOR,
    CONF_PUN_HIGH_THRESHOLD, CONF_PUN_LOW_THRESHOLD,
    CONF_WALLBOX_ENABLED, CONF_WALLBOX_STATUS, CONF_WALLBOX_POWER,
    CONF_WALLBOX_MODE, CONF_AC_ENABLED, CONF_AC_CLIMATE_ENTITY,
    CONF_AC_TEMP_THRESHOLD, CONF_OUTDOOR_TEMP_SENSOR,
    CONF_MORNING_PEAK_START, CONF_MORNING_PEAK_END,
    CONF_MORNING_PEAK_MIN_SOC, CONF_HOURLY_CONSUMPTION_WH,
    DEFAULT_BATTERY_CAPACITY, DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_RESERVE_SOC, DEFAULT_PUN_HIGH, DEFAULT_PUN_LOW,
    DEFAULT_MORNING_PEAK_START, DEFAULT_MORNING_PEAK_END,
    DEFAULT_MORNING_PEAK_MIN_SOC, DEFAULT_HOURLY_CONSUMPTION,
    DEFAULT_AC_TEMP_THRESHOLD,
)


def _sensor_selector(unit: str | None = None):
    """Return a sensor entity selector."""
    return selector.selector({"entity": {"domain": "sensor"}})


def _number_selector(min_val: float, max_val: float, step: float = 0.01, unit: str = ""):
    return selector.selector({
        "number": {"min": min_val, "max": max_val, "step": step, "unit_of_measurement": unit, "mode": "box"}
    })


def _time_selector():
    return selector.selector({"time": {}})


def _entity_selector(domains: list[str]):
    return selector.selector({"entity": {"domain": domains}})


# ─── Step schemas ────────────────────────────────────────────────────────────

STEP_BATTERY_SCHEMA = vol.Schema({
    vol.Required(CONF_BATTERY_SOC): _sensor_selector(),
    vol.Required(CONF_BATTERY_CAPACITY, default=DEFAULT_BATTERY_CAPACITY):
        _number_selector(1, 50, 0.1, "kWh"),
    vol.Required(CONF_BATTERY_MIN_SOC, default=DEFAULT_BATTERY_MIN_SOC):
        _number_selector(5, 30, 1, "%"),
    vol.Required(CONF_BATTERY_RESERVE_SOC, default=DEFAULT_BATTERY_RESERVE_SOC):
        _number_selector(10, 50, 1, "%"),
    vol.Required(CONF_BATTERY_CHARGE_MODE): _entity_selector(["select", "input_select", "number", "input_number"]),
    vol.Optional(CONF_BATTERY_DISCHARGE_MODE): _entity_selector(["select", "input_select", "number", "input_number"]),
    vol.Optional(CONF_BATTERY_CHARGE_POWER): _entity_selector(["number", "input_number"]),
})

STEP_PV_SCHEMA = vol.Schema({
    vol.Required(CONF_PV_POWER): _sensor_selector(),
    vol.Optional(CONF_PV_FORECAST_TODAY): _sensor_selector(),
    vol.Optional(CONF_HOUSE_CONSUMPTION): _sensor_selector(),
    vol.Optional(CONF_GRID_IMPORT): _sensor_selector(),
    vol.Optional(CONF_GRID_EXPORT): _sensor_selector(),
    vol.Required(CONF_HOURLY_CONSUMPTION_WH, default=DEFAULT_HOURLY_CONSUMPTION):
        _number_selector(100, 5000, 50, "Wh"),
})

STEP_PUN_SCHEMA = vol.Schema({
    vol.Optional(CONF_PUN_SENSOR): _sensor_selector(),
    vol.Required(CONF_PUN_HIGH_THRESHOLD, default=DEFAULT_PUN_HIGH):
        _number_selector(0.01, 1.0, 0.01, "€/kWh"),
    vol.Required(CONF_PUN_LOW_THRESHOLD, default=DEFAULT_PUN_LOW):
        _number_selector(0.001, 0.5, 0.001, "€/kWh"),
})

STEP_STRATEGY_SCHEMA = vol.Schema({
    vol.Required(CONF_MORNING_PEAK_START, default=DEFAULT_MORNING_PEAK_START): _time_selector(),
    vol.Required(CONF_MORNING_PEAK_END, default=DEFAULT_MORNING_PEAK_END): _time_selector(),
    vol.Required(CONF_MORNING_PEAK_MIN_SOC, default=DEFAULT_MORNING_PEAK_MIN_SOC):
        _number_selector(20, 80, 1, "%"),
})

STEP_WALLBOX_SCHEMA = vol.Schema({
    vol.Required(CONF_WALLBOX_ENABLED, default=False): selector.selector({"boolean": {}}),
    vol.Optional(CONF_WALLBOX_STATUS): _sensor_selector(),
    vol.Optional(CONF_WALLBOX_POWER): _sensor_selector(),
    vol.Optional(CONF_WALLBOX_MODE): _entity_selector(["select", "input_select", "number", "input_number", "switch"]),
})

STEP_AC_SCHEMA = vol.Schema({
    vol.Required(CONF_AC_ENABLED, default=False): selector.selector({"boolean": {}}),
    vol.Optional(CONF_AC_CLIMATE_ENTITY): _entity_selector(["climate"]),
    vol.Optional(CONF_OUTDOOR_TEMP_SENSOR): _sensor_selector(),
    vol.Required(CONF_AC_TEMP_THRESHOLD, default=DEFAULT_AC_TEMP_THRESHOLD):
        _number_selector(15, 45, 0.5, "°C"),
})


class BatteryOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow for Libe Solar & Electricity Optimization."""

    VERSION = 1
    _data: dict = {}

    async def async_step_user(self, user_input=None):
        """Step 1: Battery sensors & control entities."""
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_pv()
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_BATTERY_SCHEMA,
            errors=errors,
            description_placeholders={"step": "1/5"},
        )

    async def async_step_pv(self, user_input=None):
        """Step 2: PV & grid sensors."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_pun()
        return self.async_show_form(
            step_id="pv",
            data_schema=STEP_PV_SCHEMA,
            description_placeholders={"step": "2/5"},
        )

    async def async_step_pun(self, user_input=None):
        """Step 3: PUN price settings."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_strategy()
        return self.async_show_form(
            step_id="pun",
            data_schema=STEP_PUN_SCHEMA,
            description_placeholders={"step": "3/5"},
        )

    async def async_step_strategy(self, user_input=None):
        """Step 4: Strategy parameters (peak windows, thresholds)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_wallbox()
        return self.async_show_form(
            step_id="strategy",
            data_schema=STEP_STRATEGY_SCHEMA,
            description_placeholders={"step": "4/5"},
        )

    async def async_step_wallbox(self, user_input=None):
        """Step 5a: Wallbox (V2C Trydan) — optional."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_ac()
        return self.async_show_form(
            step_id="wallbox",
            data_schema=STEP_WALLBOX_SCHEMA,
            description_placeholders={"step": "5a/5"},
        )

    async def async_step_ac(self, user_input=None):
        """Step 5b: AC (Daikin) — optional."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="Libe Solar & Electricity Optimization",
                data=self._data,
            )
        return self.async_show_form(
            step_id="ac",
            data_schema=STEP_AC_SCHEMA,
            description_placeholders={"step": "5b/5"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BatteryOptimizerOptionsFlow(config_entry)


class BatteryOptimizerOptionsFlow(config_entries.OptionsFlow):
    """Options flow — allows reconfiguring entities and parameters after setup."""

    def __init__(self, config_entry):
        self._entry = config_entry
        self._data = dict(config_entry.data)
        self._data.update(config_entry.options)

    async def async_step_init(self, user_input=None):
        """Present a menu of option groups."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["battery", "pv", "pun", "strategy", "wallbox", "ac"],
        )

    # Each sub-step mirrors the config flow but pre-fills current values

    async def async_step_battery(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        schema = self._prefill(STEP_BATTERY_SCHEMA)
        return self.async_show_form(step_id="battery", data_schema=schema)

    async def async_step_pv(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(step_id="pv", data_schema=self._prefill(STEP_PV_SCHEMA))

    async def async_step_pun(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(step_id="pun", data_schema=self._prefill(STEP_PUN_SCHEMA))

    async def async_step_strategy(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(step_id="strategy", data_schema=self._prefill(STEP_STRATEGY_SCHEMA))

    async def async_step_wallbox(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(step_id="wallbox", data_schema=self._prefill(STEP_WALLBOX_SCHEMA))

    async def async_step_ac(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(step_id="ac", data_schema=self._prefill(STEP_AC_SCHEMA))

    def _prefill(self, schema: vol.Schema) -> vol.Schema:
        """Return schema with current values as defaults."""
        description_fields = {}
        for key in schema.schema:
            key_str = key.schema if hasattr(key, "schema") else str(key)
            if key_str in self._data:
                description_fields[key_str] = self._data[key_str]

        new_schema = {}
        for key, validator in schema.schema.items():
            key_str = key.schema if hasattr(key, "schema") else str(key)
            if key_str in self._data:
                if isinstance(key, vol.Required):
                    new_schema[vol.Required(key_str, default=self._data[key_str])] = validator
                else:
                    new_schema[vol.Optional(key_str, default=self._data[key_str])] = validator
            else:
                new_schema[key] = validator
        return vol.Schema(new_schema)
