"""Constants for the Raylogic H81 integration."""

DOMAIN = "raylogic_h81"

CONF_IP = "ip"
CONF_PORT = "port"
CONF_START_ADDRESS = "start_address"
CONF_AREA = "area"
CONF_DEVICE_ID = "device_id"
CONF_PANEL_NAME = "name"

# Port hamesha fixed hai - saare Raylogic H81 panels isi TCP port pe hote
# hain, isliye setup form mein ye maanga hi nahi jaata.
DEFAULT_PORT = 5550

# Area aur Device-ID command frame ke fields hain (Docklight capture se
# confirmed). Zyadatar setups mein defaults hi chalte hain - agar kisi
# panel ka Docklight capture alag dikhaye to Options mein override karo.
DEFAULT_AREA = "02"
DEFAULT_DEVICE_ID = 2

PLATFORMS = ["light"]
