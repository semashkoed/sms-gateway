CREATE TABLE IF NOT EXISTS messages (
    id          text        PRIMARY KEY,
    sender      text        NOT NULL,
    recipient   text        NOT NULL,
    text        text        NOT NULL,
    status      text        NOT NULL,
    reason      text,
    route       text,
    attempts    integer     NOT NULL DEFAULT 0,
    encoding    text        NOT NULL DEFAULT 'gsm7',
    segments    integer     NOT NULL DEFAULT 1,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Для /stats: выборка по времени и группировка по статусу
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON messages (created_at);
CREATE INDEX IF NOT EXISTS messages_recipient_idx  ON messages (recipient);
