from llmbench.telemetry_reporting import system_power_rows


def test_system_power_rows_render_missing_sensors_as_unavailable_not_zero():
    profile = {
        "benchmarks": {
            "generation": {
                "telemetry": {
                    "cpu": {
                        "avg_util_percent": 50.0,
                        "max_util_percent": 80.0,
                        "avg_frequency_mhz": None,
                        "min_frequency_mhz": None,
                        "max_frequency_mhz": None,
                        "avg_temperature_c": None,
                        "max_temperature_c": None,
                        "avg_package_power_w": None,
                        "max_package_power_w": None,
                        "energy_wh": None,
                    },
                    "gpus": [],
                    "power": {
                        "scope": "measured_components",
                        "coverage": [],
                        "avg_component_power_w": None,
                        "max_component_power_w": None,
                        "component_energy_wh": None,
                        "wall_power_w": None,
                        "wall_energy_wh": None,
                    },
                }
            }
        }
    }

    rows = system_power_rows(profile)
    text = "\n".join(value for *_rest, value in rows)

    assert "nicht verfuegbar" in text
    assert "0.00 W" not in text
    assert "0.000 Wh" not in text


def test_system_power_rows_only_render_wall_power_when_really_present():
    base = {
        "scope": "measured_components",
        "coverage": ["cpu_package", "gpu:0"],
        "avg_component_power_w": 500.0,
        "max_component_power_w": 550.0,
        "component_energy_wh": 10.0,
        "wall_power_w": None,
        "wall_energy_wh": None,
    }
    profile = {
        "benchmarks": {
            "generation": {
                "telemetry": {"power": dict(base)},
            }
        }
    }

    rows = system_power_rows(profile)
    assert not any(component == "Wall-Power" for _kind, component, _metric, _value in rows)

    profile["benchmarks"]["generation"]["telemetry"]["power"]["wall_power_w"] = 610.0
    rows = system_power_rows(profile)
    assert any(
        component == "Wall-Power" and metric == "Leistung" and value == "610.00 W"
        for _kind, component, metric, value in rows
    )
