import pytest

from mail_agent.models import AgentMode, UnsafeAction
from mail_agent.safety import SafetyPolicy, UnsafeOperationError


@pytest.mark.parametrize("action", list(UnsafeAction))
def test_read_only_blocks_unsafe_actions(action):
    policy = SafetyPolicy(AgentMode.READ_ONLY)

    with pytest.raises(UnsafeOperationError):
        policy.assert_allowed(action)


def test_read_only_allows_safe_local_capabilities():
    policy = SafetyPolicy(AgentMode.READ_ONLY)

    assert policy.can_read_mail is True
    assert policy.can_notify_telegram is True
    assert policy.can_store_local_draft is True

