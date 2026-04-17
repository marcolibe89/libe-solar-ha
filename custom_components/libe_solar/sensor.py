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
        # Calibrazione previsione FV
        PVForecastCalibratedSensor(coordinator, entry),
        PVCalibrationCoefficientSensor(coordinator, entry),
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


# ─── Sensori calibrazione previsione FV ──────────────────────────────────────

class PVForecastCalibratedSensor(_BaseOptimizerSensor):
    """Previsione FV corretta dal coefficiente rolling.

    Usa lo snapshot delle 05:00 moltiplicato per il coefficiente calcolato
    sul buffer storico degli ultimi 15 giorni.
    """

    _attr_name = "Libe Solar PV Forecast Calibrated"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:solar-power"

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_pv_forecast_calibrated"

    @property
    def native_value(self):
        val = self.coordinator.data.get("pv_forecast_calibrated_kwh")
        return round(val, 2) if val is not None else None

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "forecast_grezzo_kwh":       d.get("pv_forecast_kwh"),
            "snapshot_5am_kwh":          d.get("pv_forecast_snapshot_kwh"),
            "snapshot_data":             d.get("pv_forecast_snapshot_date"),
            "coefficiente_applicato":    d.get("pv_calibration_coefficient"),
        }


class PVCalibrationCoefficientSensor(_BaseOptimizerSensor):
    """Coefficiente di calibrazione rolling (produzione reale / stima 5:00).

    Sempre attivo indipendentemente dal manual override e dalla logica di vendita.
    Espone anche il confronto ultimo giorno e le medie 15gg per poter
    osservare il comportamento del modello.
    """

    _attr_name = "Libe Solar PV Calibration Coefficient"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:tune-variant"

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_pv_calibration_coefficient"

    @property
    def native_value(self):
        val = self.coordinator.data.get("pv_calibration_coefficient")
        return round(val, 4) if val is not None else None

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            # Buffer info
            "giorni_nel_buffer":          d.get("cal_days_in_buffer"),
            # Ultimo giorno registrato
            "ultimo_giorno_data":         d.get("cal_last_day_date"),
            "ultimo_giorno_stima_kwh":    d.get("cal_last_day_forecast_kwh"),
            "ultimo_giorno_reale_kwh":    d.get("cal_last_day_actual_kwh"),
            "ultimo_giorno_ratio":        d.get("cal_last_day_ratio"),
            # Medie 15 giorni
            "media_15gg_stima_kwh":       d.get("cal_avg_15d_forecast_kwh"),
            "media_15gg_reale_kwh":       d.get("cal_avg_15d_actual_kwh"),
            "media_15gg_ratio":           d.get("cal_avg_15d_ratio"),
            # Snapshot oggi
            "snapshot_oggi_kwh":          d.get("pv_forecast_snapshot_kwh"),
            "snapshot_oggi_data":         d.get("pv_forecast_snapshot_date"),
            # Buffer completo (per diagnostica/debug)
            "buffer":                     d.get("cal_buffer", []),
        }
