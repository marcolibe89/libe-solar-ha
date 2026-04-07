"""Switch platform — manual override for Libe Solar & Electricity Optimization."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([ManualOverrideSwitch(coordinator, entry)])


class ManualOverrideSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to suspend automatic optimization (manual override)."""

    _attr_name = "Libe Solar Manual Override"
    _attr_icon = "mdi:hand-back-right"

    def __init__(self, coordinator: BatteryOptimizerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def unique_id(self):
        return f"{self._entry.entry_id}_manual_override"

    @property
    def is_on(self) -> bool:
        return self.coordinator.manual_override

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_manual_override(True)

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_manual_override(False)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Libe Solar & Electricity Optimization",
        }
