# Merged Calendar

A Home Assistant helper that combines several calendars into one read-only calendar entity and shows each real-world event once, even when copies have slightly different titles, times or addresses.

- **Source calendars are never changed.** The merged calendar is built live from them every time it's read.
- **Nothing is lost.** A merged event keeps every distinct line of every copy's details, the most complete address, any alternate titles and addresses, and the times each copy listed.
- **Time rule:** if a copy came from a booking or email (a Gmail-created event, or one with a confirmation/reservation/registration number), its exact time is used; otherwise the earliest start among the copies.

## How duplicates are recognized

Two events are treated as the same only when several independent signals agree:

| Signal | Notes |
| --- | --- |
| Time overlap | Overlap, not equal start times, so a copy padded with travel time still matches |
| Title similarity | After stripping filler ("Reservation", "at", punctuation); tolerant of small spelling differences |
| Address | Street number + street name, ignoring formatting; a clearly different address blocks a merge |
| Confirmation number | A shared booking/reservation/registration number on the same day is enough on its own |

Overlap alone never merges; one-word titles need more than a title match; same-titled events on different days or at different addresses stay separate.

## Setup

Settings → Devices & services → Add integration → **Merged Calendar**, pick the calendars, and use the new `calendar.*` entity anywhere a calendar is accepted (dashboard cards, the iPhone Home Assistant calendar widget, automations). Change the source list later from the integration's **Configure** button.
