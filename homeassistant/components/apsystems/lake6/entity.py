"""Base entity for the APsystems Lake_6 integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from .coordinator import Lake6Coordinator


class Lake6Entity(CoordinatorEntity[Lake6Coordinator]):
    """Base entity shared by every Lake_6 platform.

    Only the device identity is shared here; each platform supplies its own
    entity description and unique id.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: Lake6Coordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.dev_id)},
            manufacturer="APsystems",
            # type 来自 /devices，不做映射：固件报告什么就显示什么（§3.5）
            model=device.device_type,
            serial_number=device.dev_id,
            # 空固件号在 client 层已归一为 None；None 时设备页不出现「固件」行
            sw_version=device.sw_version,
        )

    @property
    def device_id(self) -> str:
        """Return the device id used to build entity unique ids."""
        return self.coordinator.device.dev_id
