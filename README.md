# 🔋 Libe Solar & Electricity Optimization for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/YOUR_USERNAME/libe-solar-ha.svg)](https://github.com/YOUR_USERNAME/libe-solar-ha/releases)
[![Validate HACS](https://github.com/YOUR_USERNAME/libe-solar-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/YOUR_USERNAME/libe-solar-ha/actions/workflows/validate.yml)

Intelligent battery storage optimizer for Home Assistant. Maximizes economic return by aligning charge/discharge behavior with Italian hourly **PUN** (Prezzo Unico Nazionale) pricing, PV production forecasts, wallbox (V2C Trydan) demand, and AC load awareness (Daikin).

---

## Features

- 📈 **PUN-aware strategy** — discharge during high-price windows, charge during low-price periods
- ☀️ **PV forecast integration** — delay charging when sufficient solar is expected
- 🌅 **Morning peak window** — configurable priority discharge slot (default 07:00–08:00)
- 🚗 **Wallbox coordination** — accounts for EV charging load when computing PV surplus
- ❄️ **AC load awareness** — Daikin climate load factored in during hot days
- 🛡️ **Safety reserves** — battery never ends the day fully depleted
- 🖱️ **Full UI configuration** — entity mapping via HACS config flow, no YAML editing required
- 🔄 **Live reconfiguration** — change any entity or threshold from Options without reinstalling

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations** → ⋮ menu → **Custom repositories**
2. Add `https://github.com/YOUR_USERNAME/libe-solar-ha` — category: **Integration**
3. Search for **Libe Solar & Electricity Optimization** and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search *Libe Solar & Electricity Optimization*

### Manual

Copy the `custom_components/libe_solar` folder into your HA `custom_components/` directory, then restart.

---

## Configuration

The setup wizard walks through **6 steps**:

| Step | What you configure |
|------|--------------------|
| 1 – Battery | SOC sensor, capacity, min/reserve SOC, charge/discharge control entities |
| 2 – PV & Grid | PV power, daily forecast, grid import/export, estimated base load |
| 3 – PUN Price | PUN sensor (optional), high/low price thresholds |
| 4 – Strategy | Morning peak window times, minimum SOC for peak discharge |
| 5a – Wallbox | V2C Trydan power sensor and mode entity |
| 5b – AC | Daikin climate entity, outdoor temp sensor, AC activation threshold |

All steps are **reconfigurable** at any time via **Options** without reinstalling.

---

## Exposed Entities

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.libe_solar_status` | sensor | Current recommended mode (`charging`, `discharging`, `idle`, `holding`) |
| `sensor.libe_solar_reason` | sensor | Human-readable explanation of current strategy decision |
| `sensor.libe_solar_net_pv_surplus` | sensor (W) | Net PV surplus after load and wallbox |
| `sensor.libe_solar_estimated_load` | sensor (W) | Estimated total house load (including AC if active) |
| `sensor.libe_solar_hours_remaining` | sensor (h) | Estimated hours of discharge remaining |
| `sensor.libe_solar_pun_price` | sensor (€/kWh) | Current PUN price (mirrors input sensor) |
| `switch.libe_solar_manual_override` | switch | Suspends automatic decisions — manual control |

---

## Strategy Logic

```
06:00  → Forecast check: is today's PV sufficient to cover daily needs?
07:00  → Morning peak window: if SOC ≥ peak_min_soc AND PUN ≥ high_threshold → DISCHARGE
09:00  → Strategy reassessment based on actual PV ramp-up
10–17  → Hourly: net_surplus > 200W AND midday → CHARGE from solar
         PUN ≥ high_threshold AND SOC > reserve → DISCHARGE
         PUN ≤ low_threshold AND SOC < 90% → CHARGE (cheap grid)
         Otherwise → IDLE
```

AC and wallbox loads are subtracted from net PV surplus before any decision.

---

## Supported Inverters

The integration exposes **recommended mode** as a sensor state — it does not directly control the inverter. You connect the `libe_solar_status` sensor to your inverter's control entities via:

- **Automations** triggered on sensor state change
- **Ready-made scripts** for Huawei FusionSolar, SolarEdge Modbus, Fronius, Growatt, GoodWe *(see [INVERTER_CONFIGS.md](INVERTER_CONFIGS.md))*

---

## Requirements

- Home Assistant 2024.1+
- HACS 1.6+
- A battery inverter with a controllable integration in HA

---

## Contributing

PRs and issues welcome. Please open an issue before submitting large changes.

---

## License

MIT
