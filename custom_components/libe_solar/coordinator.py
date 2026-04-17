"""DataUpdateCoordinator — battery optimization engine."""
from __future__ import annotations

import logging
from datetime import timedelta
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
    CALIBRATION_MIN_FORECAST_KWH, CALIBRATION_MIN_ACTUAL_KWH,
    CALIBRATION_WEIGHT_MAX,
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

        # ── Calibration state — persisted via Store ───────────────────────
        # Buffer: lista di dict per ogni giorno valido (max CALIBRATION_MAX_DAYS)
        # {date, forecast_5am_kwh, actual_kwh, ratio, weight}
        self._store = Store(hass, version=1, key=CALIBRATION_STORAGE_KEY)
        self._cal_buffer: list[dict] = []
        # Snapshot della previsione alle 5:00 del giorno corrente
        self._forecast_snapshot: dict = {}   # {date: str, value_kwh: float}
        # Guard: evita doppio snapshot e doppio aggiornamento buffer nello stesso giorno
        self._snapshot_done_date: str = ""
        self._buffer_updated_date: str = ""

    # ─── Setup ───────────────────────────────────────────────────────────

    async def async_load_calibration(self) -> None:
        """Load persisted calibration data. Must be called once at integration setup."""
        stored = await self._store.async_load()
        if not stored:
            return
        if isinstance(stored.get("buffer"), list):
            self._cal_buffer = stored["buffer"]
        if isinstance(stored.get("snapshot"), dict):
            self._forecast_snapshot = stored["snapshot"]
            self._snapshot_done_date = stored["snapshot"].get("date", "")
        _LOGGER.debug(
            "[Calibration] Loaded: %d days in buffer, snapshot=%s",
            len(self._cal_buffer),
            self._forecast_snapshot,
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

    def _compute_coefficient(self) -> float:
        """Weighted average of (actual / forecast) over valid buffer days."""
        num = 0.0
        den = 0.0
        for e in self._cal_buffer:
            fc = e.get("forecast_5am_kwh", 0)
            ac = e.get("actual_kwh", 0)
            w  = e.get("weight", 1.0)
            if fc >= CALIBRATION_MIN_FORECAST_KWH and ac > 0:
                num += (ac / fc) * w
                den += w
        return round(num / den, 4) if den > 0 else 1.0

    def _reweight_buffer(self) -> None:
        """Assign linear weights: oldest day → 1.0, newest → CALIBRATION_WEIGHT_MAX."""
        n = len(self._cal_buffer)
        for i, entry in enumerate(self._cal_buffer):
            if n > 1:
                entry["weight"] = round(
                    1.0 + (CALIBRATION_WEIGHT_MAX - 1.0) * i / (n - 1), 4
                )
            else:
                entry["weight"] = CALIBRATION_WEIGHT_MAX

    def _add_to_buffer(self, date_str: str, forecast_5am_kwh: float, actual_kwh: float) -> None:
        """Validate, add entry, trim buffer, reweight."""
        if forecast_5am_kwh < CALIBRATION_MIN_FORECAST_KWH:
            _LOGGER.info(
                "[Calibration] %s skipped — forecast %.2f kWh below %.1f kWh threshold (cloudy day)",
                date_str, forecast_5am_kwh, CALIBRATION_MIN_FORECAST_KWH,
            )
            return
        if actual_kwh < CALIBRATION_MIN_ACTUAL_KWH:
            _LOGGER.info(
                "[Calibration] %s skipped — actual %.2f kWh below %.1f kWh threshold",
                date_str, actual_kwh, CALIBRATION_MIN_ACTUAL_KWH,
            )
            return

        ratio = round(actual_kwh / forecast_5am_kwh, 4)

        # Remove any existing entry for the same date
        self._cal_buffer = [e for e in self._cal_buffer if e.get("date") != date_str]
        self._cal_buffer.append({
            "date": date_str,
            "forecast_5am_kwh": round(forecast_5am_kwh, 2),
            "actual_kwh": round(actual_kwh, 2),
            "ratio": ratio,
            "weight": 1.0,  # will be recalculated
        })

        # Sort ascending by date, keep last N
        self._cal_buffer.sort(key=lambda e: e["date"])
        self._cal_buffer = self._cal_buffer[-CALIBRATION_MAX_DAYS:]

        self._reweight_buffer()

        _LOGGER.info(
            "[Calibration] Buffer updated — %s: forecast=%.2f actual=%.2f ratio=%.4f | "
            "%d days, coeff=%.4f",
            date_str, forecast_5am_kwh, actual_kwh, ratio,
            len(self._cal_buffer), self._compute_coefficient(),
        )

    def _calibration_stats(self) -> dict:
        """Compute derived stats exposed to sensors."""
        valid = [
            e for e in self._cal_buffer
            if e.get("forecast_5am_kwh", 0) >= CALIBRATION_MIN_FORECAST_KWH
            and e.get("actual_kwh", 0) > 0
        ]
        n = len(valid)

        # Last day in buffer
        last = valid[-1] if valid else None

        # 15-day averages
        avg_forecast = round(sum(e["forecast_5am_kwh"] for e in valid) / n, 2) if n else None
        avg_actual   = round(sum(e["actual_kwh"]       for e in valid) / n, 2) if n else None
        avg_ratio    = round(sum(e["ratio"]             for e in valid) / n, 4) if n else None

        return {
            "days_in_buffer": n,
            "last_day_date":          last["date"]              if last else None,
            "last_day_forecast_kwh":  last["forecast_5am_kwh"]  if last else None,
            "last_day_actual_kwh":    last["actual_kwh"]         if last else None,
            "last_day_ratio":         last["ratio"]              if last else None,
            "avg_15d_forecast_kwh":   avg_forecast,
            "avg_15d_actual_kwh":     avg_actual,
            "avg_15d_ratio":          avg_ratio,
            "buffer": valid,  # lista completa per debug / attributi
        }

    # ─── Data fetch ───────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Called every UPDATE_INTERVAL minutes by HA scheduler."""
        try:
            result, save_data = await self.hass.async_add_executor_job(self._compute)
            if save_data:
                await self._store.async_save({
                    "buffer": self._cal_buffer,
                    "snapshot": self._forecast_snapshot,
                })
                _LOGGER.debug("[Calibration] State persisted to storage.")
            return result
        except Exception as err:
            raise UpdateFailed(f"Battery optimizer error: {err}") from err

    def _compute(self) -> tuple[dict[str, Any], bool]:
        """Returns (data_dict, should_persist)."""
        cfg = self._config
        now = dt_util.now()
        now_minutes = now.hour * 60 + now.minute
        today_str = now.strftime("%Y-%m-%d")
        should_persist = False

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

        # ── Calibration: snapshot forecast alle 05:00 ─────────────────────
        # Il sensore forecast cambia durante il giorno (le previsioni si aggiornano).
        # Usiamo il valore delle 05:00 come riferimento stabile per il confronto
        # con la produzione reale a fine giornata.
        if (
            now.hour == 5
            and now.minute < UPDATE_INTERVAL
            and self._snapshot_done_date != today_str
            and pv_forecast is not None
        ):
            self._forecast_snapshot = {
                "date": today_str,
                "value_kwh": round(pv_forecast, 2),
            }
            self._snapshot_done_date = today_str
            should_persist = True
            _LOGGER.info(
                "[Calibration] Forecast snapshot at 05:00 → %.2f kWh", pv_forecast
            )

        # ── Calibration: aggiorna buffer a fine giornata (23:25–23:30) ────
        # Confronta lo snapshot delle 05:00 con la produzione reale del giorno.
        snapshot_today = self._forecast_snapshot.get("date") == today_str
        if (
            now.hour == 23
            and 25 <= now.minute < 30
            and self._buffer_updated_date != today_str
            and snapshot_today
            and pv_actual is not None
        ):
            self._add_to_buffer(
                date_str=today_str,
                forecast_5am_kwh=self._forecast_snapshot["value_kwh"],
                actual_kwh=pv_actual,
            )
            self._buffer_updated_date = today_str
            should_persist = True

        # ── Calibration: coefficiente e previsione corretta ───────────────
        coeff = self._compute_coefficient()
        pv_forecast_calibrated = (
            round(pv_forecast * coeff, 2) if pv_forecast is not None else None
        )
        cal_stats = self._calibration_stats()

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
            pun_ok = pun_price is None or pun_price >= pun_high
            if pun_ok:
                recommended = STATE_DISCHARGING
                reason = f"Morning peak window, SOC {soc:.0f}%, PUN {'N/A' if pun_price is None else f'{pun_price:.3f}€'}"
            else:
                recommended = STATE_HOLDING
                reason = f"Morning peak but PUN too low ({pun_price:.3f}€ < {pun_high}€)"
        elif net_surplus_w > 200 and soc < (100 - reserve):
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
            # Calibration
            "pv_calibration_coefficient": coeff,
            "pv_forecast_snapshot_kwh": self._forecast_snapshot.get("value_kwh"),
            "pv_forecast_snapshot_date": self._forecast_snapshot.get("date"),
            **{f"cal_{k}": v for k, v in cal_stats.items()},
        }, should_persist
