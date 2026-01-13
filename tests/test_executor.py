"""Tests for executor implementation."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from gotn.executor import (
    RetryConfig,
    RetryableError,
    with_retry,
    ClaudeExecutor,
    PromptBuilder,
    ExecutionContext,
)
from gotn.node import (
    Criterion,
    CriterionType,
    DeliverableType,
    Goal,
    NodeMode,
    NodeStatus,
    WorkNode,
)


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_values(self):
        """Default retry config has reasonable values."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0
        assert config.backoff_factor == 2.0

    def test_exponential_backoff(self):
        """Delay increases exponentially with attempts."""
        config = RetryConfig(base_delay=1.0, backoff_factor=2.0, max_delay=100.0)

        assert config.get_delay(0) == 1.0   # 1 * 2^0 = 1
        assert config.get_delay(1) == 2.0   # 1 * 2^1 = 2
        assert config.get_delay(2) == 4.0   # 1 * 2^2 = 4
        assert config.get_delay(3) == 8.0   # 1 * 2^3 = 8

    def test_max_delay_cap(self):
        """Delay is capped at max_delay."""
        config = RetryConfig(base_delay=1.0, backoff_factor=10.0, max_delay=5.0)

        assert config.get_delay(0) == 1.0
        assert config.get_delay(1) == 5.0  # Capped at 5, not 10
        assert config.get_delay(2) == 5.0  # Still capped


class TestWithRetry:
    """Tests for with_retry function."""

    def test_success_on_first_try(self):
        """Succeeds immediately without retries."""
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = with_retry(func, RetryConfig(max_retries=3))
        assert result == "success"
        assert call_count == 1

    def test_success_after_retries(self):
        """Succeeds after some retries."""
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("temporary failure")
            return "success"

        config = RetryConfig(max_retries=3, base_delay=0.01)  # Fast for tests
        result = with_retry(func, config)
        assert result == "success"
        assert call_count == 3

    def test_exhausts_retries(self):
        """Raises after exhausting retries."""
        call_count = 0
        original_error = ValueError("original")

        def func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("always fails", original_error=original_error)

        config = RetryConfig(max_retries=2, base_delay=0.01)
        with pytest.raises(ValueError) as exc_info:
            with_retry(func, config)

        assert call_count == 3  # Initial + 2 retries
        assert exc_info.value is original_error

    def test_timeout_not_retried(self):
        """TimeoutExpired is not retried."""
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            raise subprocess.TimeoutExpired(cmd="test", timeout=1)

        config = RetryConfig(max_retries=3)
        with pytest.raises(subprocess.TimeoutExpired):
            with_retry(func, config)

        assert call_count == 1  # No retries


class TestClaudeExecutorRetryable:
    """Tests for ClaudeExecutor._is_retryable_error."""

    def test_rate_limit_retryable(self):
        """Rate limit errors are retryable."""
        executor = ClaudeExecutor()
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["test"],
            stderr="Error: rate limit exceeded, try again later",
        )
        assert executor._is_retryable_error(error) is True

    def test_connection_error_retryable(self):
        """Connection errors are retryable."""
        executor = ClaudeExecutor()
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["test"],
            stderr="ECONNREFUSED: connection refused",
        )
        assert executor._is_retryable_error(error) is True

    def test_server_error_retryable(self):
        """Server errors (5xx) are retryable."""
        executor = ClaudeExecutor()
        for code in ["500", "502", "503"]:
            error = subprocess.CalledProcessError(
                returncode=1,
                cmd=["test"],
                stderr=f"Server returned {code}",
            )
            assert executor._is_retryable_error(error) is True

    def test_generic_error_not_retryable(self):
        """Generic errors are not retryable."""
        executor = ClaudeExecutor()
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["test"],
            stderr="Invalid argument",
        )
        assert executor._is_retryable_error(error) is False


class TestPromptBuilderCriterionIds:
    """Tests for criterion ID inclusion in prompts."""

    def test_criteria_section_includes_ids(self):
        """Criteria section includes criterion IDs."""
        node = WorkNode(
            id="test-001",
            depth=0,
            mode=NodeMode.EPISTEMIC,
            deliverable_type=DeliverableType.KNOWLEDGE,
            goal=Goal(
                statement="Test goal statement",
                acceptance_criteria=[
                    Criterion(
                        id="crit-abc123",
                        description="First criterion",
                        type=CriterionType.KNOWLEDGE,
                    ),
                    Criterion(
                        id="crit-def456",
                        description="Second criterion",
                        type=CriterionType.KNOWLEDGE,
                        must_pass=True,
                    ),
                ],
            ),
            status=NodeStatus.READY,
        )

        builder = PromptBuilder()
        criteria_section = builder._build_criteria_section(node)

        # Check that IDs are included
        assert "crit-abc123" in criteria_section
        assert "crit-def456" in criteria_section
        # Check that IDs are bolded/emphasized
        assert "**crit-abc123**" in criteria_section

    def test_output_format_lists_valid_ids(self):
        """Output format lists valid criterion IDs."""
        node = WorkNode(
            id="test-001",
            depth=0,
            mode=NodeMode.EPISTEMIC,
            deliverable_type=DeliverableType.KNOWLEDGE,
            goal=Goal(
                statement="Test goal statement",
                acceptance_criteria=[
                    Criterion(
                        id="crit-test1",
                        description="Test criterion",
                        type=CriterionType.KNOWLEDGE,
                    ),
                ],
            ),
            status=NodeStatus.READY,
        )

        builder = PromptBuilder()
        output_section = builder._build_output_format(node)

        # Check that valid IDs are listed
        assert "crit-test1" in output_section
        assert "Valid criterion IDs" in output_section
