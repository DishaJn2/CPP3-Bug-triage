import time
from abc import ABC, abstractmethod


class BaseAgent(ABC):
    step_name: str = "base_agent"

    @abstractmethod
    async def run(self, context: dict) -> dict:
        pass

    async def safe_run(self, context: dict) -> tuple[dict, int]:
        start = time.monotonic()
        try:
            context = await self.run(context)
        except Exception as e:
            self._add_error(context, f"{self.step_name} failed: {str(e)}")
        duration_ms = int((time.monotonic() - start) * 1000)
        return context, duration_ms

    def _add_error(self, context: dict, message: str) -> None:
        if "errors" not in context:
            context["errors"] = {}
        context["errors"][self.step_name] = message
