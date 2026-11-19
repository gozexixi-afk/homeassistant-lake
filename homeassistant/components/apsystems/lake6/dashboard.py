"""Provision the Lovelace dashboard the Lake_6 controls ship with.

The device page groups entities by `entity_category` and sorts each group by
the localized display name, so the order the product spec asks for cannot be
expressed there. The integration therefore creates one storage dashboard of
its own: it is written once after the entities exist and is never touched
again, so later edits in the UI stick.

Home Assistant only reads the dashboard list while it starts, so the panel is
registered with the frontend directly here. That way it appears and disappears
with the Lake_6 device instead of waiting for the next restart.
"""

import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.components.lovelace.dashboard import LovelaceStorage
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .card_layout import DASHBOARD_ICON, DASHBOARD_TITLE, build_config
from .coordinator import Lake6ConfigEntry

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "lake-control"

# `LovelaceStorage` 与 `DashboardsCollection` 都用版本 1（§§ lovelace/dashboard.py）
_STORE_VERSION = 1
_CONFIG_STORAGE_KEY = f"lovelace.{DASHBOARD_URL_PATH}"
_DASHBOARDS_STORAGE_KEY = "lovelace_dashboards"

_DASHBOARD_ITEM: dict[str, Any] = {
    "id": DASHBOARD_URL_PATH,
    "icon": DASHBOARD_ICON,
    "title": DASHBOARD_TITLE,
    "url_path": DASHBOARD_URL_PATH,
    "require_admin": False,
    "show_in_sidebar": True,
    "mode": "storage",
}


async def async_provision_dashboard(
    hass: HomeAssistant, entry: Lake6ConfigEntry, device_id: str
) -> None:
    """Create the bundled dashboard once the entities are registered.

    Called after the platforms are forwarded, because the card needs the real
    `entity_id`s. An existing configuration means the panel is already there —
    either created here before or edited by the user — and is left untouched.
    """
    config_store = Store[dict[str, Any]](hass, _STORE_VERSION, _CONFIG_STORAGE_KEY)
    if await config_store.async_load() is not None:
        return

    registry = er.async_get(hass)
    entity_ids = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    config = build_config(device_id, entity_ids)
    if config is None:
        # 平台还没全部建好时不要落半成品，下次 setup 再来
        _LOGGER.debug(
            "Lake_6 skipped the bundled dashboard: entities are still registering"
        )
        return

    await config_store.async_save({"config": config})

    dashboards_store = Store[dict[str, Any]](
        hass, _STORE_VERSION, _DASHBOARDS_STORAGE_KEY
    )
    dashboards = await dashboards_store.async_load() or {"items": []}
    items = dashboards.setdefault("items", [])
    if not any(item.get("url_path") == DASHBOARD_URL_PATH for item in items):
        items.append(_DASHBOARD_ITEM)
        await dashboards_store.async_save(dashboards)

    if _async_show_panel(hass):
        _LOGGER.info("Lake_6 created the %s dashboard", DASHBOARD_TITLE)
    else:
        _LOGGER.info(
            "Lake_6 created the %s dashboard; restart Home Assistant to show it "
            "in the sidebar",
            DASHBOARD_TITLE,
        )


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Drop the bundled dashboard once no Lake_6 device is left.

    Lovelace removes the panel from its own storage collection, which is private
    to that integration, so the same three steps are repeated here: hide the
    sidebar entry, delete the stored config and drop the dashboard list item.
    """
    frontend.async_remove_panel(hass, DASHBOARD_URL_PATH, warn_if_unknown=False)

    lovelace_data = hass.data.get(LOVELACE_DATA)
    storage = (
        lovelace_data.dashboards.pop(DASHBOARD_URL_PATH, None)
        if lovelace_data is not None
        else None
    )
    if storage is not None:
        # 与 lovelace 删除面板时一致，连带删掉 lovelace.lake-control 存储
        await storage.async_delete()
    else:
        await Store[dict[str, Any]](
            hass, _STORE_VERSION, _CONFIG_STORAGE_KEY
        ).async_remove()

    dashboards_store = Store[dict[str, Any]](
        hass, _STORE_VERSION, _DASHBOARDS_STORAGE_KEY
    )
    dashboards = await dashboards_store.async_load()
    if dashboards is None:
        return

    items = dashboards.get("items", [])
    remaining = [
        item for item in items if item.get("url_path") != DASHBOARD_URL_PATH
    ]
    if len(remaining) == len(items):
        return

    dashboards["items"] = remaining
    await dashboards_store.async_save(dashboards)
    _LOGGER.info("Lake_6 removed the %s dashboard", DASHBOARD_TITLE)


def _async_show_panel(hass: HomeAssistant) -> bool:
    """Put the panel in the sidebar without waiting for a restart.

    Returns False while Lovelace is not set up, in which case the next start
    picks the dashboard up from storage as before.
    """
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        return False
    if frontend.async_panel_exists(hass, DASHBOARD_URL_PATH):
        return True

    lovelace_data.dashboards[DASHBOARD_URL_PATH] = LovelaceStorage(
        hass, dict(_DASHBOARD_ITEM)
    )
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        frontend_url_path=DASHBOARD_URL_PATH,
        require_admin=_DASHBOARD_ITEM["require_admin"],
        show_in_sidebar=_DASHBOARD_ITEM["show_in_sidebar"],
        sidebar_title=DASHBOARD_TITLE,
        sidebar_icon=DASHBOARD_ICON,
        config={"mode": MODE_STORAGE},
        update=False,
    )
    return True
