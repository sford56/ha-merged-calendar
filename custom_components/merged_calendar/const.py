"""Constants for Merged Calendar."""

from datetime import timedelta

DOMAIN = "merged_calendar"
CONF_CALENDARS = "calendars"
DEFAULT_NAME = "Calendar (merged)"

# How far ahead the entity looks to find its current/next event (its state).
STATE_LOOKAHEAD = timedelta(days=30)
SCAN_INTERVAL = timedelta(minutes=15)
