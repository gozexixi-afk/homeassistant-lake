"""Text platform for the APsystems Lake_6 integration."""

from typing import override

from homeassistant.components import persistent_notification
from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ..const import DOMAIN
from .const import (
    LAKE6_MODE_STATE_TIME_OF_USE,
    LAKE6_TOU_TEXT_MAX_LENGTH,
    LAKE6_TOU_TEXT_MAX_RULES,
)
from .coordinator import Lake6ConfigEntry, Lake6Coordinator
from .entity import Lake6Entity
from .tou import async_write_tou_plan, parse_plan, render_plan


def _ignored_power_notice(language: str, rules: list[int]) -> tuple[str, str]:
    """Return the title and body for dropped wattage on `self` rows.

    `persistent_notification.async_create` only takes finished strings, so the
    wording has to be picked here rather than through translations.
    """
    if language.lower().startswith("zh"):
        return (
            "分时计划已自动修正",
            "第 "
            + "、".join(str(rule) for rule in rules)
            + " 条规则的功能是 self（自发自用），该时段设备不使用功率，已按 “-” 下发。",
        )
    return (
        "Time-of-use plan adjusted",
        "Rule "
        + ", ".join(str(rule) for rule in rules)
        + " uses self (no charge or discharge), so the power value was dropped "
        'and sent as "-".',
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Lake6ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lake_6 text platform."""
    add_entities([Lake6TouPlanText(config_entry.runtime_data.coordinator)])


class Lake6TouPlanText(Lake6Entity, TextEntity):
    """The whole time-of-use schedule in one line.

    Home Assistant has no editable table control, so the schedule is carried by
    a single text box: every rule is one `;` separated chunk of five `|`
    separated fields. `tou.parse_plan` is the authority on that grammar; this
    entity only translates its ValueError into a ServiceValidationError.

    It deliberately carries no `entity_category`: the device page renders the
    category-less entities in 控制 first, so the schedule opens at the top
    instead of being buried under 配置.
    """

    _attr_translation_key = "tou_plan"
    _attr_native_max = LAKE6_TOU_TEXT_MAX_LENGTH

    def __init__(self, coordinator: Lake6Coordinator) -> None:
        """Initialize the schedule text box."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.device_id}_tou_plan"

    @property
    @override
    def native_value(self) -> str:
        """Return the current schedule rendered as text."""
        return render_plan(self.coordinator.data.modes.tou_rules) or ""

    @property
    @override
    def available(self) -> bool:
        """Expose the schedule only while it can be shown losslessly.

        `time_cfg` has no effect outside time-of-use mode. It is also hidden
        when the device holds rules this text cannot express, or more rules than
        the 255 character state limit fits: submitting a shortened plan would
        silently delete the rest on the device. An empty schedule stays
        editable so the first rule can still be typed in.
        """
        if not super().available:
            return False
        if self.coordinator.data.modes.operating_mode != LAKE6_MODE_STATE_TIME_OF_USE:
            return False
        rules = self.coordinator.data.modes.tou_rules
        if len(rules) > LAKE6_TOU_TEXT_MAX_RULES:
            return False
        return render_plan(rules) is not None

    @override
    async def async_set_value(self, value: str) -> None:
        """Replace the whole schedule after parsing every rule.

        A power value on a `self` row is dropped instead of rejected: the
        schedule is still valid, the user just filled a field the device never
        reads. The notice afterwards says so, since the box will now show `-`.
        """
        try:
            rows = parse_plan(value)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="tou_invalid_plan",
                translation_placeholders={"error": str(err)},
            ) from err
        await async_write_tou_plan(self.coordinator, rows)
        ignored = [index for index, row in enumerate(rows, 1) if row.power_ignored]
        if ignored:
            title, message = _ignored_power_notice(
                self.hass.config.language, ignored
            )
            persistent_notification.async_create(
                self.hass,
                message,
                title=title,
                notification_id=f"{DOMAIN}_{self.device_id}_tou_power_ignored",
            )
