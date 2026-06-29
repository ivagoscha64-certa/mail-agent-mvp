from __future__ import annotations

from dataclasses import dataclass

from mail_agent.models import AgentMode, UnsafeAction


class UnsafeOperationError(RuntimeError):
    """Raised when a disabled mailbox operation is requested."""


@dataclass(frozen=True)
class SafetyPolicy:
    mode: AgentMode = AgentMode.READ_ONLY

    def assert_allowed(self, action: UnsafeAction) -> None:
        if self.mode == AgentMode.READ_ONLY:
            raise UnsafeOperationError(
                f"Action '{action.value}' is blocked in read-only mode."
            )
        raise UnsafeOperationError(f"Unsupported safety mode: {self.mode.value}")

    @property
    def can_read_mail(self) -> bool:
        return True

    @property
    def can_notify_telegram(self) -> bool:
        return True

    @property
    def can_store_local_draft(self) -> bool:
        return True

