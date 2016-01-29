"""
homeassistant.components.zigbee
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sets up and provides access to a ZigBee device and contains generic entity
classes.
"""

import logging
from binascii import unhexlify

from homeassistant.core import JobPriority
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_ON, STATE_OFF
from homeassistant.helpers.entity import Entity, ToggleEntity


DOMAIN = "zigbee"
REQUIREMENTS = ("xbee-helper==0.0.6",)

CONF_DEVICE = "device"
CONF_BAUD = "baud"

DEFAULT_DEVICE = "/dev/ttyUSB0"
DEFAULT_BAUD = 9600
DEFAULT_ADC_MAX_VOLTS = 1.2

# Copied from xbee_helper.const during setup()
GPIO_DIGITAL_OUTPUT_LOW = None
GPIO_DIGITAL_OUTPUT_HIGH = None
ADC_PERCENTAGE = None

DEVICE = None

_LOGGER = logging.getLogger(__name__)


def setup(hass, config):
    """
    Set up the connection to the ZigBee device and instantiate the helper
    class for it.
    """
    global DEVICE
    global GPIO_DIGITAL_OUTPUT_LOW
    global GPIO_DIGITAL_OUTPUT_HIGH
    global ADC_PERCENTAGE

    import xbee_helper.const as xb_const
    from xbee_helper import ZigBee
    from serial import Serial, SerialException

    GPIO_DIGITAL_OUTPUT_LOW = xb_const.GPIO_DIGITAL_OUTPUT_LOW
    GPIO_DIGITAL_OUTPUT_HIGH = xb_const.GPIO_DIGITAL_OUTPUT_HIGH
    ADC_PERCENTAGE = xb_const.ADC_PERCENTAGE

    usb_device = config[DOMAIN].get(CONF_DEVICE, DEFAULT_DEVICE)
    baud = int(config[DOMAIN].get(CONF_BAUD, DEFAULT_BAUD))
    try:
        ser = Serial(usb_device, baud)
    except SerialException as exc:
        _LOGGER.exception("Unable to open serial port for ZigBee: %s", exc)
        return False
    DEVICE = ZigBee(ser)
    hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, close_serial_port)
    return True


def close_serial_port(*args):
    """
    Close the serial port we're using to communicate with the ZigBee.
    """
    DEVICE.zb.serial.close()


class ZigBeeConfig(object):
    """
    Handles the fetching of configuration from the config file for any ZigBee
    entity.
    """
    def __init__(self, config):
        self._config = config
        self._should_poll = config.get("poll", True)

    @property
    def name(self):
        """
        The name given to the entity.
        """
        return self._config["name"]

    @property
    def address(self):
        """
        If an address has been provided, unhexlify it, otherwise return None
        as we're talking to our local ZigBee device.
        """
        address = self._config.get("address")
        if address is not None:
            address = unhexlify(address)
        return address

    @property
    def should_poll(self):
        """
        A bool depicting whether HA should repeatedly poll this device for its
        value.
        """
        return self._should_poll


class ZigBeePinConfig(ZigBeeConfig):
    """
    Handles the fetching of configuration from the config file for a ZigBee
    GPIO pin.
    """
    @property
    def pin(self):
        """
        The GPIO pin number.
        """
        return self._config["pin"]


class ZigBeeDigitalPinConfig(ZigBeePinConfig):
    """
    Handles the fetching of configuration from the config file for a ZigBee
    GPIO pin set to digital in or out.
    """
    def __init__(self, config):
        super(ZigBeeDigitalPinConfig, self).__init__(config)
        self._bool2state, self._state2bool = self.boolean_maps

    @property
    def boolean_maps(self):
        """
        Create dicts to map booleans to pin high/low and vice versa. Depends on
        the config item "on_state" which should be set to "low" or "high".
        """
        if self._config.get("on_state", "").lower() == "low":
            bool2state = {
                True: GPIO_DIGITAL_OUTPUT_LOW,
                False: GPIO_DIGITAL_OUTPUT_HIGH
            }
        else:
            bool2state = {
                True: GPIO_DIGITAL_OUTPUT_HIGH,
                False: GPIO_DIGITAL_OUTPUT_LOW
            }
        state2bool = {v: k for k, v in bool2state.items()}
        return bool2state, state2bool

    @property
    def bool2state(self):
        """
        A dictionary mapping booleans to GPIOSetting objects to translate
        on/off as being pin high or low.
        """
        return self._bool2state

    @property
    def state2bool(self):
        """
        A dictionary mapping GPIOSetting objects to booleans to translate
        pin high/low as being on or off.
        """
        return self._state2bool

# Create an alias so that ZigBeeDigitalOutConfig has a logical opposite.
ZigBeeDigitalInConfig = ZigBeeDigitalPinConfig


class ZigBeeDigitalOutConfig(ZigBeeDigitalPinConfig):
    """
    A subclass of ZigBeeDigitalPinConfig which sets _should_poll to default as
    False instead of True. The value will still be overridden by the presence
    of a 'poll' config entry.
    """
    def __init__(self, config):
        super(ZigBeeDigitalOutConfig, self).__init__(config)
        self._should_poll = config.get("poll", False)


class ZigBeeAnalogInConfig(ZigBeePinConfig):
    """
    Handles the fetching of configuration from the config file for a ZigBee
    GPIO pin set to analog in.
    """
    @property
    def max_voltage(self):
        """
        The voltage at which the ADC will report its highest value.
        """
        return float(self._config.get("max_volts", DEFAULT_ADC_MAX_VOLTS))


class ZigBeeDigitalIn(Entity):
    """
    ToggleEntity to represent a GPIO pin configured as a digital input.
    """
    def __init__(self, hass, config):
        self._config = config
        self._state = False
        # Get initial state
        hass.pool.add_job(
            JobPriority.EVENT_STATE, (self.update_ha_state, True))

    @property
    def name(self):
        return self._config.name

    @property
    def should_poll(self):
        return self._config.should_poll

    @property
    def state(self):
        return STATE_ON if self.is_on else STATE_OFF

    @property
    def is_on(self):
        return self._state

    def update(self):
        """
        Ask the ZigBee device what its output is set to.
        """
        pin_state = DEVICE.get_gpio_pin(
            self._config.pin,
            self._config.address)
        self._state = self._config.state2bool[pin_state]


class ZigBeeDigitalOut(ZigBeeDigitalIn, ToggleEntity):
    """
    Adds functionality to ZigBeeDigitalIn to control an output.
    """
    def _set_state(self, state):
        DEVICE.set_gpio_pin(
            self._config.pin,
            self._config.bool2state[state],
            self._config.address)
        self._state = state
        if not self.should_poll:
            self.update_ha_state()

    def turn_on(self, **kwargs):
        self._set_state(True)

    def turn_off(self, **kwargs):
        self._set_state(False)


class ZigBeeAnalogIn(Entity):
    """
    Entity to represent a GPIO pin configured as an analog input.
    """
    def __init__(self, hass, config):
        self._config = config
        self._value = None
        # Get initial state
        hass.pool.add_job(
            JobPriority.EVENT_STATE, (self.update_ha_state, True))

    @property
    def name(self):
        return self._config.name

    @property
    def should_poll(self):
        return self._config.should_poll

    @property
    def state(self):
        return self._value

    @property
    def unit_of_measurement(self):
        return "%"

    def update(self, *args):
        """
        Get the latest reading from the ADC.
        """
        self._value = DEVICE.read_analog_pin(
            self._config.pin,
            self._config.max_voltage,
            self._config.address,
            ADC_PERCENTAGE)
