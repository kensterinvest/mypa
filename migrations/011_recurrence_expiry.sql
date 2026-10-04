-- 011 — repeating reminders + expiry alerts.
--
-- reminders.repeat        : rule string ("weekly", "every 2 weeks", …), NULL = one-off
-- reminders.repeat_anchor : first occurrence; later ones are computed from it
--                           in the user's tz so they don't drift
-- expiry_alerts           : which "ends in N days" pushes went out, so each
--                           threshold fires once per (item, end date). A
--                           renewed contract (new end date) alerts again.

ALTER TABLE reminders ADD COLUMN repeat TEXT;
ALTER TABLE reminders ADD COLUMN repeat_anchor DATETIME;

CREATE TABLE IF NOT EXISTS expiry_alerts (
    item_id   INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    end_date  TEXT    NOT NULL,
    days      INTEGER NOT NULL,
    sent_at   TEXT    NOT NULL,
    PRIMARY KEY (item_id, end_date, days)
);
