"""DataUpdateCoordinator — battery optimization engine."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, UPDATE_INTERVAL,
    CONF_BATTERY_SOC, CONF_BATTERY_CAPACITY, CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_RESERVE_SOC, CONF_PV_POWER, CONF_PV_FORECAST_TODAY,
    CONF_GRID_IMPORT, CONF_GRID_EXPORT, CONF_HOUSE_CONSUMPTION,
    CONF_BATTERY_CHARGE_MODE, CONF_BATTERY_DISCHARGE_MODE,
    CONF_BATTERY_CHARGE_POWER, CONF_PUN_SENSOR,
    CONF_PUN_HIGH_THRESHOLD, CONF_PUN_LOW_THRESHOLD,
    CONF_WALLBOX_ENABLED, CONF_WALLBOX_POWER,
    CONF_AC_ENABLED, CONF_AC_CLIMATE_ENTITY, CONF_AC_TEMP_THRESHOLD,
    CONF_OUTDOOR_TEMP_SENSOR, CONF_MORNING_PEAK_START, CONF_MORNING_PEAK_END,
    CONF_MORNING_PEAK_MIN_SOC, CONF_HOURLY_CONSUMPTION_WH,
    DEFAULT_HOURLY_CONSUMPTION, DEFAULT_BATTERY_RESERVE_SOC,
    DEFAULT_PUN_HIGH, DEFAULT_PUN_LOW,
    STATE_IDLE, STATE_CHARGING, STATE_DISCHARGING, STATE_HOLDING,
)

_LOGGER = logging.getLogger(__name__)


def _float_state(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """Safely read a numeric state from HA."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown", ""):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def _time_to_minutes(time_str: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = map(int, time_str.split(":"))
    return h * 60 + m


class BatteryOptimizerCoordinator(DataUpdateCoordinator):
    """Core coordinator: reads sensors, runs strategy, exposes state."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL),
        )
        self._config = config
        self._manual_override: bool = False
        self._manual_mode: str | None = None

    # ─── Public properties ────────────────────────────────────────────────

    @property
    def manual_override(self) -> bool:
        return self._manual_override

    def set_manual_override(self, enabled: bool, mode: str | None = None) -> None:
        self._manual_override = enabled
        self._manual_mode = mode
        self.hass.async_create_task(self.async_request_refresh())

    # ─── Data fetch ───────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Called every UPDATE_INTERVAL minutes by HA scheduler."""
        try:
            return await self.hass.async_add_executor_job(self._compute)
        except Exception as err:
            raise UpdateFailed(f"Battery optimizer error: {err}") from err

    def _compute(self) -> dict[str, Any]:
        cfg = self._config
        now = dt_util.now()
        now_minutes = now.hour * 60 + now.minute

        # ── Read sensors ──────────────────────────────────────────────────
        soc        = _float_state(self.hass, cfg.get(CONF_BATTERY_SOC))
        pv_power   = _float_state(self.hass, cfg.get(CONF_PV_POWER)) or 0.0
        pv_forecast= _float_state(self.hass, cfg.get(CONF_PV_FORECAST_TODAY))
        grid_import= _float_state(self.hass, cfg.get(CONF_GRID_IMPORT)) or 0.0
        grid_export= _float_state(self.hass, cfg.get(CONF_GRID_EXPORT)) or 0.0
        house_cons = _float_state(self.hass, cfg.get(CONF_HOUSE_CONSUMPTION))
        pun_price  = _float_state(self.hass, cfg.get(CONF_PUN_SENSOR))
        outdoor_t  = _float_state(self.hass, cfg.get(CONF_OUTDOOR_TEMP_SENSOR))

        # ── Wallbox load ──────────────────────────────────────────────────
        wallbox_power = 0.0
        if cfg.get(CONF_WALLBOX_ENABLED):
            wallbox_power = _float_state(self.hass, cfg.get(CONF_WALLBOX_POWER)) or 0.0

        # ── AC load estimation ────────────────────────────────────────────
        ac_active = False
        if cfg.get(CONF_AC_ENABLED) and cfg.get(CONF_AC_CLIMATE_ENTITY):
            ac_state = self.hass.states.get(cfg[CONF_AC_CLIMATE_ENTITY])
            ac_active = ac_state is not None and ac_state.state not in (
                "off", "unavailable", "unknown"
            )
        ac_temp_ok = (
            outdoor_t is not None
            and outdoor_t >= cfg.get(CONF_AC_TEMP_THRESHOLD, 28.0)
        )

        # ── Estimated base consumption ─────────────────────────────────────
        base_consumption_w = cfg.get(CONF_HOURLY_CONSUMPTION_WH, DEFAULT_HOURLY_CONSUMPTION)
        ac_extra_w = 1500.0 if (ac_active and ac_temp_ok) else 0.0
        estimated_load_w = (house_cons * 1000 if house_cons else base_consumption_w) + ac_extra_w

        # ── Net PV surplus ────────────────────────────────────────────────
        net_surplus_w = pv_power - estimated_load_w - wallbox_power

        # ── Strategy parameters ───────────────────────────────────────────
        pun_high  = cfg.get(CONF_PUN_HIGH_THRESHOLD, DEFAULT_PUN_HIGH)
        pun_low   = cfg.get(CONF_PUN_LOW_THRESHOLD, DEFAULT_PUN_LOW)
        min_soc   = cfg.get(CONF_BATTERY_MIN_SOC, 10)
        reserve   = cfg.get(CONF_BATTERY_RESERVE_SOC, DEFAULT_BATTERY_RESERVE_SOC)
        capacity  = cfg.get(CONF_BATTERY_CAPACITY, 13.5)

        peak_start = _time_to_minutes(cfg.get(CONF_MORNING_PEAK_START, "07:00"))
        peak_end   = _time_to_minutes(cfg.get(CONF_MORNING_PEAK_END, "08:00"))
        peak_min_soc = cfg.get(CONF_MORNING_PEAK_MIN_SOC, 40)

        in_morning_peak = peak_start <= now_minutes < peak_end

        # ── Decide strategy ───────────────────────────────────────────────
        if self._manual_override:
            recommended = self._manual_mode or STATE_HOLDING
            reason = "Manual override"
        elif soc is None:
            recommended = STATE_HOLDING
            reason = "SOC unavailable — holding"
        elif soc <= min_soc:
            recommended = STATE_CHARGING
            reason = f"SOC {soc:.0f}% at minimum — force charge"
        elif in_morning_peak and soc >= peak_min_soc:
            # High-value discharge window
            pun_ok = pun_price is None or pun_price >= pun_high
            if pun_ok:
                recommended = STATE_DISCHARGING
                reason = f"Morning peak window, SOC {soc:.0f}%, PUN {'N/A' if pun_price is None else f'{pun_price:.3f}€'}"
            else:
                recommended = STATE_HOLDING
                reason = f"Morning peak but PUN too low ({pun_price:.3f}€ < {pun_high}€)"
        elif net_surplus_w > 200 and soc < (100 - reserve):
            # PV surplus available: charge if PUN is low or midday
            is_midday = 9 * 60 <= now_minutes <= 17 * 60
            if is_midday or (pun_price is not None and pun_price <= pun_low):
                recommended = STATE_CHARGING
                reason = f"PV surplus {net_surplus_w:.0f}W, charging from solar"
            else:
                recommended = STATE_HOLDING
                reason = f"PV surplus {net_surplus_w:.0f}W but waiting for better PUN window"
        elif pun_price is not None and pun_price >= pun_high and soc > reserve:
            recommended = STATE_DISCHARGING
            reason = f"High PUN {pun_price:.3f}€, discharging (SOC {soc:.0f}%)"
        elif pun_price is not None and pun_price <= pun_low and soc < 90:
            recommended = STATE_CHARGING
            reason = f"Low PUN {pun_price:.3f}€, cheap charging"
        else:
            recommended = STATE_IDLE
            reason = "No profitable action identified"

        # ── Estimated hours until depletion ───────────────────────────────
        hours_remaining: float | None = None
        if soc is not None and estimated_load_w > 0:
            usable_kwh = (soc - min_soc) / 100.0 * capacity
            if recommended == STATE_DISCHARGING and usable_kwh > 0:
                hours_remaining = (usable_kwh * 1000) / max(estimated_load_w, 1)

        return {
            "soc": soc,
            "pv_power_w": pv_power,
            "pv_forecast_kwh": pv_forecast,
            "net_surplus_w": net_surplus_w,
            "estimated_load_w": estimated_load_w,
            "wallbox_power_w": wallbox_power,
            "ac_active": ac_active,
            "pun_price": pun_price,
            "grid_import_w": grid_import,
            "grid_export_w": grid_export,
            "recommended_mode": recommended,
            "strategy_reason": reason,
            "manual_override": self._manual_override,
            "hours_remaining": hours_remaining,
            "last_update": now.isoformat(),
        }
