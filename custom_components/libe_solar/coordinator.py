"""DataUpdateCoordinator — battery optimization engine."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, UPDATE_INTERVAL,
    CONF_BATTERY_SOC, CONF_BATTERY_CAPACITY, CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_RESERVE_SOC, CONF_PV_POWER, CONF_PV_FORECAST_TODAY,
    CONF_PV_ENERGY_TODAY,
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
    CALIBRATION_STORAGE_KEY, CALIBRATION_MAX_DAYS,
    CALIBRATION_MIN_FORECAST, CALIBRATION_MIN_ACTUAL, CALIBRATION_WEIGHT_MAX,
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

        # Calibration state — persisted across HA restarts via Store
        self._store = Store(hass, version=1, key=CALIBRATION_STORAGE_KEY)
        self._calibration_buffer: list[dict] = []
        self._calibration_saved_date: str = ""

    # ─── Setup ───────────────────────────────────────────────────────────

    async def async_load_calibration(self) -> None:
        """Load calibration buffer from persistent storage. Call once at setup."""
        stored = await self._store.async_load()
        if stored and isinstance(stored.get("buffer"), list):
            self._calibration_buffer = stored["buffer"]
            _LOGGER.debug(
                "[Calibration] Loaded %d days from storage",
                len(self._calibration_buffer),
            )

    # ─── Public properties ────────────────────────────────────────────────

    @property
    def manual_override(self) -> bool:
        return self._manual_override

    def set_manual_override(self, enabled: bool, mode: str | None = None) -> None:
        self._manual_override = enabled
        self._manual_mode = mode
        self.hass.async_create_task(self.async_request_refresh())

    # ─── Calibration helpers ──────────────────────────────────────────────

    def _calibration_coefficient(self) -> float:
        """Weighted average of actual/forecast ratios over the rolling buffer."""
        num = 0.0
        den = 0.0
        for entry in self._calibration_buffer:
            fc = entry.get("forecast_kwh", 0)
            ac = entry.get("actual_kwh", 0)
            w  = entry.get("weight", 1.0)
            if fc > CALIBRATION_MIN_FORECAST and ac > 0:
                num += (ac / fc) * w
                den += w
        return round(num / den, 4) if den > 0 else 1.0

    def _update_calibration_buffer(
        self, forecast_kwh: float, actual_kwh: float, date_str: str
    ) -> None:
        """Add today to the buffer, re-weight all entries, trim to max days."""
        if forecast_kwh < CALIBRATION_MIN_FORECAST or actual_kwh < CALIBRATION_MIN_ACTUAL:
            _LOGGER.debug(
                "[Calibration] Skipping %s — forecast=%.2f kWh actual=%.2f kWh (below threshold)",
                date_str, forecast_kwh, actual_kwh,
            )
            return

        # Remove existing entry for same date if any
        self._calibration_buffer = [
            e for e in self._calibration_buffer if e.get("date") != date_str
        ]

        # Append new entry
        self._calibration_buffer.append({
            "date": date_str,
            "forecast_kwh": round(forecast_kwh, 3),
            "actual_kwh": round(actual_kwh, 3),
            "weight": 1.0,
        })

        # Sort by date ascending, keep last N days
        self._calibration_buffer.sort(key=lambda e: e["date"])
        self._calibration_buffer = self._calibration_buffer[-CALIBRATION_MAX_DAYS:]

        # Re-assign linear weights: oldest → 1.0, newest → CALIBRATION_WEIGHT_MAX
        n = len(self._calibration_buffer)
        for i, entry in enumerate(self._calibration_buffer):
            entry["weight"] = round(
                1.0 + (CALIBRATION_WEIGHT_MAX - 1.0) * i / max(n - 1, 1), 4
            )

        _LOGGER.info(
            "[Calibration] Buffer updated: %d days, coefficient=%.4f",
            n, self._calibration_coefficient(),
        )

    # ─── Data fetch ───────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Called every UPDATE_INTERVAL minutes by HA scheduler."""
        try:
            result = await self.hass.async_add_executor_job(self._compute)

            # Persist calibration buffer if flagged by _compute
            if result.pop("_save_calibration", False):
                await self._store.async_save({"buffer": self._calibration_buffer})
                _LOGGER.debug("[Calibration] Buffer persisted to storage.")

            return result
        except Exception as err:
            raise UpdateFailed(f"Battery optimizer error: {err}") from err

    def _compute(self) -> dict[str, Any]:
        cfg = self._config
        now = dt_util.now()
        now_minutes = now.hour * 60 + now.minute
        today_str = now.strftime("%Y-%m-%d")

        # ── Read sensors ──────────────────────────────────────────────────
        soc         = _float_state(self.hass, cfg.get(CONF_BATTERY_SOC))
        pv_power    = _float_state(self.hass, cfg.get(CONF_PV_POWER)) or 0.0
        pv_forecast = _float_state(self.hass, cfg.get(CONF_PV_FORECAST_TODAY))
        pv_actual   = _float_state(self.hass, cfg.get(CONF_PV_ENERGY_TODAY))
        grid_import = _float_state(self.hass, cfg.get(CONF_GRID_IMPORT)) or 0.0
        grid_export = _float_state(self.hass, cfg.get(CONF_GRID_EXPORT)) or 0.0
        house_cons  = _float_state(self.hass, cfg.get(CONF_HOUSE_CONSUMPTION))
        pun_price   = _float_state(self.hass, cfg.get(CONF_PUN_SENSOR))
        outdoor_t   = _float_state(self.hass, cfg.get(CONF_OUTDOOR_TEMP_SENSOR))

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

        # ── Estimated base consumption ────────────────────────────────────
        base_consumption_w = cfg.get(CONF_HOURLY_CONSUMPTION_WH, DEFAULT_HOURLY_CONSUMPTION)
        ac_extra_w = 1500.0 if (ac_active and ac_temp_ok) else 0.0
        estimated_load_w = (house_cons * 1000 if house_cons else base_consumption_w) + ac_extra_w

        # ── Net PV surplus ────────────────────────────────────────────────
        net_surplus_w = pv_power - estimated_load_w - wallbox_power

        # ── Calibration coefficient & calibrated forecast ─────────────────
        coeff = self._calibration_coefficient()
        pv_forecast_calibrated = (
            round(pv_forecast * coeff, 2) if pv_forecast is not None else None
        )
        calibration_days = sum(
            1 for e in self._calibration_buffer
            if e.get("forecast_kwh", 0) > CALIBRATION_MIN_FORECAST
        )

        # ── End-of-day calibration buffer update (once per day, 23:25–23:30) ─
        save_calibration = False
        if (
            now.hour == 23
            and 25 <= now.minute < 30
            and self._calibration_saved_date != today_str
            and pv_forecast is not None
            and pv_actual is not None
        ):
            self._update_calibration_buffer(pv_forecast, pv_actual, today_str)
            self._calibration_saved_date = today_str
            coeff = self._calibration_coefficient()  # refresh after update
            save_calibration = True

        # ── Strategy parameters ───────────────────────────────────────────
        pun_high     = cfg.get(CONF_PUN_HIGH_THRESHOLD, DEFAULT_PUN_HIGH)
        pun_low      = cfg.get(CONF_PUN_LOW_THRESHOLD, DEFAULT_PUN_LOW)
        min_soc      = cfg.get(CONF_BATTERY_MIN_SOC, 10)
        reserve      = cfg.get(CONF_BATTERY_RESERVE_SOC, DEFAULT_BATTERY_RESERVE_SOC)
        capacity     = cfg.get(CONF_BATTERY_CAPACITY, 13.5)
        peak_start   = _time_to_minutes(cfg.get(CONF_MORNING_PEAK_START, "07:00"))
        peak_end     = _time_to_minutes(cfg.get(CONF_MORNING_PEAK_END, "08:00"))
        peak_min_soc = cfg.get(CONF_MORNING_PEAK_MIN_SOC, 40)

        in_morning_peak = peak_start <= now_minutes < peak_end

        # ── Pure algorithmic decision (always computed, ignores manual override) ─
        algo_mode, algo_reason = self._algorithmic_decision(
            soc=soc,
            net_surplus_w=net_surplus_w,
            pun_price=pun_price,
            in_morning_peak=in_morning_peak,
            now_minutes=now_minutes,
            pun_high=pun_high,
            pun_low=pun_low,
            min_soc=min_soc,
            reserve=reserve,
            peak_min_soc=peak_min_soc,
        )

        # ── Apply manual override on top ──────────────────────────────────
        if self._manual_override:
            recommended = self._manual_mode or STATE_HOLDING
            reason = f"Override manuale attivo (algoritmo: {algo_mode})"
        else:
            recommended = algo_mode
            reason = algo_reason

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
            "pv_forecast_calibrated_kwh": pv_forecast_calibrated,
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
            # Calibration — sempre disponibili indipendentemente dal manual override
            "pv_calibration_coefficient": coeff,
            "pv_calibration_days": calibration_days,
            "pv_forecast_calibrated_kwh": pv_forecast_calibrated,
            # Debug — decisione algoritmica pura, senza override manuale
            "debug_recommended_mode": algo_mode,
            "debug_strategy_reason": algo_reason,
            # Flag interno — consumato da _async_update_data, non esposto
            "_save_calibration": save_calibration,
        }

    def _algorithmic_decision(
        self,
        soc: float | None,
        net_surplus_w: float,
        pun_price: float | None,
        in_morning_peak: bool,
        now_minutes: int,
        pun_high: float,
        pun_low: float,
        min_soc: float,
        reserve: float,
        peak_min_soc: float,
    ) -> tuple[str, str]:
        """Pure algorithmic decision — no manual override, no side effects."""

        if soc is None:
            return STATE_HOLDING, "SOC non disponibile — in attesa"

        if soc <= min_soc:
            return STATE_CHARGING, f"SOC {soc:.0f}% al minimo — carica forzata"

        if in_morning_peak and soc >= peak_min_soc:
            pun_ok = pun_price is None or pun_price >= pun_high
            if pun_ok:
                pun_str = "N/D" if pun_price is None else f"{pun_price:.3f} €/kWh"
                return STATE_DISCHARGING, f"Picco mattutino, SOC {soc:.0f}%, PUN {pun_str}"
            return STATE_HOLDING, f"Picco mattutino ma PUN basso ({pun_price:.3f} < {pun_high} €/kWh)"

        if net_surplus_w > 200 and soc < (100 - reserve):
            is_midday = 9 * 60 <= now_minutes <= 17 * 60
            if is_midday or (pun_price is not None and pun_price <= pun_low):
                return STATE_CHARGING, f"Surplus FV {net_surplus_w:.0f} W — carica da solare"
            return STATE_HOLDING, f"Surplus FV {net_surplus_w:.0f} W — attesa finestra PUN migliore"

        if pun_price is not None and pun_price >= pun_high and soc > reserve:
            return STATE_DISCHARGING, f"PUN alto {pun_price:.3f} €/kWh — scarica (SOC {soc:.0f}%)"

        if pun_price is not None and pun_price <= pun_low and soc < 90:
            return STATE_CHARGING, f"PUN basso {pun_price:.3f} €/kWh — carica conveniente"

        return STATE_IDLE, "Nessuna azione economicamente vantaggiosa"
