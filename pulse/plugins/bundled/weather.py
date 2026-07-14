"""description="Reports current weather for a city (mock)" """
__permissions__ = ["tools.register", "memory.write"]

from pulse.tools.base import Tool, ToolResult


class WeatherTool(Tool):
    name = "get_weather"
    description = "Get the current weather for a city (mock). Args: city."
    parameters = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}

    def run(self, city: str = "", **kwargs) -> ToolResult:
        return ToolResult(ok=True, output=f"Sunny, 22°C in {city} (mock)")


def register(runtime) -> None:
    runtime.tools.register(WeatherTool())
    runtime.memory.add_note("weather plugin loaded")
