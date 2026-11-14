"""Circuit Breaker Pattern for Media Providers in Nova Autopilot v8.0.

Prevents pipeline hanging on repeated third-party API timeouts or network outages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from nova.logging_setup import logger

T = TypeVar("T")


@dataclass
class CircuitState:
    failure_count: int = 0
    last_failure_time: float = 0.0
    state: str = "CLOSED"  # CLOSED (healthy), OPEN (tripped/bypassed), HALF_OPEN
    recovery_timeout: float = 300.0  # 5 minutes
    failure_threshold: int = 3


class CircuitBreakerManager:
    """Manages circuit breakers across multiple external providers."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 300.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.circuits: dict[str, CircuitState] = {}

    def get_circuit(self, provider: str) -> CircuitState:
        if provider not in self.circuits:
            self.circuits[provider] = CircuitState(
                failure_threshold=self.failure_threshold,
                recovery_timeout=self.recovery_timeout,
            )
        return self.circuits[provider]

    def is_available(self, provider: str) -> bool:
        c = self.get_circuit(provider)
        if c.state == "OPEN":
            # Check if recovery timeout has elapsed
            if time.time() - c.last_failure_time > c.recovery_timeout:
                c.state = "HALF_OPEN"
                logger.info(f"Circuit for provider '{provider}' transitioned to HALF_OPEN (probing recovery).")
                return True
            return False
        return True

    def record_success(self, provider: str) -> None:
        c = self.get_circuit(provider)
        c.failure_count = 0
        c.state = "CLOSED"

    def record_failure(self, provider: str, error_msg: str = "") -> None:
        c = self.get_circuit(provider)
        c.failure_count += 1
        c.last_failure_time = time.time()

        if c.failure_count >= c.failure_threshold:
            c.state = "OPEN"
            logger.warning(
                f"[bold red]Circuit breaker OPEN for provider '{provider}'[/bold red] after {c.failure_count} consecutive failures ({error_msg}). "
                f"Bypassing provider for {c.recovery_timeout}s."
            )


# Global singleton instance
provider_circuit_breaker = CircuitBreakerManager()
