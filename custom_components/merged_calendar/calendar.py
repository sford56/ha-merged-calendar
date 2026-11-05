"""The merged calendar entity."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from . import merge
from .const import CONF_CALENDARS, SCAN_INTERVAL, STATE_LOOKAHEAD  # noqa: F401  (SCAN_INTERVAL read by HA)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    # No update_before_add: at startup the source calendars may not be loaded yet.
    # The entity refreshes itself once Home Assistant has fully started.
    async_add_entities([MergedCalendarEntity(entry)])


def _local_iso(value: Any) -> Any:
    """Datetime strings in local time with local offset; dates untouched.

    Sources report datetimes in mixed offsets (some Google events come back in UTC).
    Matching compares calendar days and prints wall-clock times, so everything is put
    in Home Assistant's own time zone first.
    """
    if not isinstance(value, str) or len(value) <= 10:
        return value
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_local(parsed).isoformat()


def _to_dt(value: str) -> date | datetime:
    if len(value) == 10:
        return date.fromisoformat(value)
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(f"bad datetime {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed


def _event_to_calendar_event(ev: dict) -> CalendarEvent:
    return CalendarEvent(
        start=_to_dt(ev["start"]),
        end=_to_dt(ev["end"]),
        summary=ev.get("summary") or "",
        description=ev.get("description") or None,
        location=ev.get("location") or None,
        uid=ev.get("uid"),
    )


class MergedCalendarEntity(CalendarEntity):
    """Read-only calendar showing several calendars with duplicates merged."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:calendar-multiple-check"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_name = entry.data.get(CONF_NAME) or entry.title
        self._attr_unique_id = entry.entry_id
        self._event: CalendarEvent | None = None
        self._merged_count = 0
        self._failed: list[str] = []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        async def _first_refresh(_hass: HomeAssistant) -> None:
            await self.async_update_ha_state(force_refresh=True)

        self.async_on_remove(async_at_started(self.hass, _first_refresh))

    @property
    def _sources(self) -> list[str]:
        return [e for e in self._entry.options.get(CONF_CALENDARS, []) if e != self.entity_id]

    @property
    def event(self) -> CalendarEvent | None:
        return self._event

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "source_calendars": self._sources,
            "merged_duplicates_next_30_days": self._merged_count,
            "unavailable_sources": self._failed,
        }

    async def _fetch(self, start: datetime, end: datetime) -> tuple[dict[str, list[dict]], list[str]]:
        """Read every source calendar; one failing doesn't stop the others."""

        async def one(entity_id: str) -> list[dict]:
            resp = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {"entity_id": entity_id, "start_date_time": start, "end_date_time": end},
                blocking=True,
                return_response=True,
            )
            return list((resp or {}).get(entity_id, {}).get("events", []))

        sources = self._sources
        results = await asyncio.gather(*(one(e) for e in sources), return_exceptions=True)
        by_cal: dict[str, list[dict]] = {}
        failed: list[str] = []
        for entity_id, res in zip(sources, results):
            if isinstance(res, BaseException):
                _LOGGER.warning("Merged calendar %s: could not read %s: %s", self.entity_id, entity_id, res)
                failed.append(entity_id)
                continue
            for i, ev in enumerate(res):
                ev["start"] = _local_iso(ev.get("start"))
                ev["end"] = _local_iso(ev.get("end"))
                ev.setdefault("uid", f"{entity_id}:{ev.get('start')}:{ev.get('summary')}:{i}")
            by_cal[entity_id] = res
        return by_cal, failed

    def _names(self) -> dict[str, str]:
        names = {}
        for entity_id in self._sources:
            st = self.hass.states.get(entity_id)
            names[entity_id] = (st.attributes.get("friendly_name") if st else None) or entity_id
        return names

    async def _merged(self, start: datetime, end: datetime) -> tuple[list[CalendarEvent], int, list[str]]:
        by_cal, failed = await self._fetch(start, end)
        order = [e for e in self._sources if e in by_cal]
        try:
            result = merge.dedupe(by_cal, order, self._names())
            pairs, merged = result["events"], len(result["merged"])
        except Exception:  # never blank the calendar because of the merge step
            _LOGGER.exception("Merged calendar %s: merge failed, showing unmerged events", self.entity_id)
            pairs = [(c, ev) for c in order for ev in by_cal[c]]
            merged = 0
        events: list[CalendarEvent] = []
        for _cal, ev in pairs:
            try:
                events.append(_event_to_calendar_event(ev))
            except (KeyError, ValueError) as err:
                _LOGGER.debug("Skipping unreadable event %s: %s", ev, err)
        events.sort(key=lambda e: (e.start_datetime_local, e.end_datetime_local))
        return events, merged, failed

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        events, _merged, _failed = await self._merged(start_date, end_date)
        return events

    async def async_update(self) -> None:
        now = dt_util.now()
        events, merged, failed = await self._merged(now, now + STATE_LOOKAHEAD)
        self._merged_count = merged
        self._failed = failed
        self._event = next((e for e in events if e.end_datetime_local > now), None)
