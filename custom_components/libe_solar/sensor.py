"""Sensor platform for Libe Solar & Electricity Optimization."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BatteryOptimizerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BatteryOptimizerCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        BatteryOptimizerStatusSensor(coordinator, entry),
        BatteryOptimizerReasonSensor(coordinator, entry),
        BatteryOptimizerNetSurplusSensor(coordinator, entry),
        BatteryOptimizerHoursRemainingSensor(coordinator, entry),
        BatteryOptimizerEstimatedLoadSensor(coordinator, entry),
        BatteryOptimizerPunSensor(coordinator, entry),
    ])


class _BaseOptimizerSensor(CoordinatorEntity, SensorEntity):
    """Shared base for all optimizer sensors."""

    def __init__(self, coordinator: BatteryOptimizerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Libe Solar & Electricity Optimization",
            "manufacturer": "Community",
            "model": "Libe Solar & Electricity Optimization",
            "sw_version": "1.0.0",
        }


class BatteryOptimizerStatusSensor(_BaseOptimizerSensor):
    _attr_name = "Libe Solar Status"
    _attr_icon = "mdi:battery-charging-outline"

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_status"

    @property
    def native_value(self):
        return self.coordinator.data.get("recommended_mode")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "manual_override": d.get("manual_override"),
            "last_update": d.get("last_update"),
            "ac_active": d.get("ac_active"),
            "wallbox_power_w": d.get("wallbox_power_w"),
        }


class BatteryOptimizerReasonSensor(_BaseOptimizerSensor):
    _attr_name = "Libe Solar Reason"
    _attr_icon = "mdi:text-box-outline"

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_reason"

    @property
    def native_value(self):
        return self.coordinator.data.get("strategy_reason")


class BatteryOptimizerNetSurplusSensor(_BaseOptimizerSensor):
    _attr_name = "Libe Solar Net PV Surplus"
    _attr_native_unit_of_measurement = "W"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:solar-power"

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_net_surplus"

    @property
    def native_value(self):
        return self.coordinator.data.get("net_surplus_w")


class BatteryOptimizerHoursRemainingSensor(_BaseOptimizerSensor):
    _attr_name = "Libe Solar Hours Remaining"
    _attr_native_unit_of_measurement = "h"
    _attr_icon = "mdi:clock-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_hours_remaining"

    @property
    def native_value(self):
        val = self.coordinator.data.get("hours_remaining")
        return round(val, 1) if val is not None else None


class BatteryOptimizerEstimatedLoadSensor(_BaseOptimizerSensor):
    _attr_name = "Libe Solar Estimated Load"
    _attr_native_unit_of_measurement = "W"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-lightning-bolt"

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_estimated_load"

    @property
    def native_value(self):
        return self.coordinator.data.get("estimated_load_w")


class BatteryOptimizerPunSensor(_BaseOptimizerSensor):
    _attr_name = "Libe Solar PUN Price"
    _attr_native_unit_of_measurement = "€/kWh"
    _attr_icon = "mdi:currency-eur"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_pun_price"

    @property
    def native_value(self):
        val = self.coordinator.data.get("pun_price")
        return round(val, 4) if val is not None else None
