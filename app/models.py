import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    ACCEPTED = "accepted"  # прошло фильтры, стоит в очереди на отправку
    REJECTED = "rejected"  # отклонено фильтром или перегрузкой
    SENT = "sent"  # оператор принял сообщение
    FAILED = "failed"  # все операторы маршрута ответили ошибкой


@dataclass
class Message:
    sender: str
    recipient: str
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: Status = Status.ACCEPTED
    reason: str | None = None
    route: str | None = None
    attempts: int = 0
    encoding: str = "gsm7"
    segments: int = 1
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "status": self.status.value,
            "reason": self.reason,
            "route": self.route,
            "attempts": self.attempts,
            "encoding": self.encoding,
            "segments": self.segments,
        }
