"""Constants for Libe Solar & Electricity Optimization integration."""

DOMAIN = "libe_solar"
PLATFORMS = ["sensor", "switch"]

# Config / Options keys
CONF_BATTERY_SOC           = "battery_soc_sensor"
CONF_BATTERY_CAPACITY      = "battery_capacity_kwh"
CONF_BATTERY_MIN_SOC       = "battery_min_soc_pct"
CONF_BATTERY_RESERVE_SOC   = "battery_reserve_soc_pct"

CONF_PV_POWER              = "pv_power_sensor"
CONF_PV_FORECAST_TODAY     = "pv_forecast_today_sensor"

CONF_GRID_IMPORT           = "grid_import_sensor"
CONF_GRID_EXPORT           = "grid_export_sensor"
CONF_HOUSE_CONSUMPTION     = "house_consumption_sensor"

CONF_BATTERY_CHARGE_MODE   = "battery_charge_mode_entity"
CONF_BATTERY_DISCHARGE_MODE= "battery_discharge_mode_entity"
CONF_BATTERY_CHARGE_POWER  = "battery_charge_power_entity"

CONF_PUN_SENSOR            = "pun_current_price_sensor"
CONF_PUN_HIGH_THRESHOLD    = "pun_high_threshold_eur"
CONF_PUN_LOW_THRESHOLD     = "pun_low_threshold_eur"

# Optional: Wallbox (V2C Trydan)
CONF_WALLBOX_ENABLED       = "wallbox_enabled"
CONF_WALLBOX_STATUS        = "wallbox_status_sensor"
CONF_WALLBOX_POWER         = "wallbox_power_sensor"
CONF_WALLBOX_MODE          = "wallbox_mode_entity"

# Optional: AC (Daikin)
CONF_AC_ENABLED            = "ac_enabled"
CONF_AC_CLIMATE_ENTITY     = "ac_climate_entity"
CONF_AC_TEMP_THRESHOLD     = "ac_outdoor_temp_threshold"
CONF_OUTDOOR_TEMP_SENSOR   = "outdoor_temp_sensor"

# Strategy parameters
CONF_MORNING_PEAK_START    = "morning_peak_start"
CONF_MORNING_PEAK_END      = "morning_peak_end"
CONF_MORNING_PEAK_MIN_SOC  = "morning_peak_min_soc_pct"
CONF_HOURLY_CONSUMPTION_WH = "estimated_hourly_consumption_wh"

# Defaults
DEFAULT_BATTERY_CAPACITY    = 13.5
DEFAULT_BATTERY_MIN_SOC     = 10
DEFAULT_BATTERY_RESERVE_SOC = 20
DEFAULT_PUN_HIGH            = 0.12
DEFAULT_PUN_LOW             = 0.04
DEFAULT_MORNING_PEAK_START  = "07:00"
DEFAULT_MORNING_PEAK_END    = "08:00"
DEFAULT_MORNING_PEAK_MIN_SOC= 40
DEFAULT_HOURLY_CONSUMPTION  = 500
DEFAULT_AC_TEMP_THRESHOLD   = 28.0

# States
STATE_IDLE       = "idle"
STATE_CHARGING   = "charging"
STATE_DISCHARGING= "discharging"
STATE_HOLDING    = "holding"

# Coordinator update interval (minutes)
UPDATE_INTERVAL = 5

# PV calibration
CONF_PV_ENERGY_TODAY       = "pv_energy_today_sensor"
CALIBRATION_STORAGE_KEY    = f"{DOMAIN}_calibration_buffer"
CALIBRATION_MAX_DAYS       = 15
CALIBRATION_MIN_FORECAST   = 2.0   # kWh — giorni sotto soglia esclusi dal buffer
CALIBRATION_MIN_ACTUAL     = 0.5   # kWh — produzione reale minima accettabile
CALIBRATION_WEIGHT_MAX     = 2.0   # peso giorno più recente vs peso giorno più vecchio (1.0)
