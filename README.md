# Home Assistant - Dual Mode Generic Thermostat with range support

From [@zacs](https://github.com/zacs)
> Special thanks to [shandoosheri](https://community.home-assistant.io/t/heat-cool-generic-thermostat/76443) for getting this to work on older versions of Home Assistant, which gave me an easy blueprint to follow. And thanks [@kevinvincent](https://github.com/kevinvincent) for writing a nice `custom_component` readme for me to fork.

This component is a straightfoward fork of the Zac's `dualmode_generic`.

## Installation (Manual)
1. Download this repository as a ZIP (green button, top right) and unzip the archive
2. Copy `/custom_components/dualmode_generic` to your `<config_dir>/custom_components/` directory
   * You will need to create the `custom_components` folder if it does not exist
   * On Hassio the final location will be `/config/custom_components/dualmode_generic`
   * On Hassbian the final location will be `/home/homeassistant/.homeassistant/custom_components/dualmode_generic`

## Configuration
Add the following to your configuration file

```yaml
climate:
  - platform: dualmode_generic
    name: My Thermostat
    heater: switch.heater
    cooler: switch.fan
    target_sensor: sensor.my_temp_sensor
    reverse_cycle: true
```

The component shares the same configuration variables as the standard `generic_thermostat`, with three exceptions:
* A `cooler` variable has been added where you can specify the `entity_id` of your switch for a cooling unit (AC, fan, etc).
* If the cooling and heating unit are the same device (e.g. a reverse cycle air conditioner) setting `reverse_cycle` to `true` will ensure the device isn't switched off entirely when switching modes
* The `ac_mode` variable has been removed, since it makes no sense for this use case.
* Rather that `target_temp`, this component uses `target_temp_low` for when activate heating and `target_temp_high` for when to activate cooling

Refer to the [Generic Thermostat documentation](https://www.home-assistant.io/components/generic_thermostat/) for details on the rest of the variables. This component doesn't change their functionality.

## Behavior

* The thermostat will follow standard mode-based behavior: if set to "cool," the only switch which can be activated is the `cooler`. Vice versa is also true. It also supports the `HEAT_COOL` mode where either will be activated if the temperature goes outside of the range set by their respective targets.

* Keepalive logic has been updated to be aware of the mode in current use, so should function as expected.

* While `heater`/`cooler` are documented to be `switch`es, they can also be `input_boolean`s if necessary.


## Reporting an Issue
1. Setup your logger to print debug messages for this component using:
```yaml
logger:
  default: info
  logs:
    custom_components.dualmode_generic: debug
```
2. Restart HA
3. Verify you're still having the issue
4. File an issue in this Github Repository containing your HA log (Developer section > Info > Load Full Home Assistant Log)
   * You can paste your log file at pastebin https://pastebin.com/ and submit a link.
   * Please include details about your setup (Pi, NUC, etc, docker?, HASSOS?)
   * The log file can also be found at `/<config_dir>/home-assistant.log`
