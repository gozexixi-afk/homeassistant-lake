"""Constants for the APsystems Local API integration."""

from logging import Logger, getLogger
from typing import Final

LOGGER: Logger = getLogger(__package__)
DOMAIN = "apsystems"
DEFAULT_PORT = 8050

# 一个 DOMAIN 承载两代设备，靠条目里的 device_type 区分（§3.1）；
# 没有该键的条目是在此之前创建的 EZ1 条目，必须继续按 EZ1 处理
CONF_DEVICE_TYPE: Final = "device_type"
DEVICE_TYPE_EZ1: Final = "ez1"
DEVICE_TYPE_LAKE6: Final = "lake6"
