from pulse.tools.base import Tool, ToolResult


class WeatherTool(Tool):
    name = "get_weather"
    description = "Get the current weather for a city (example plugin). Args: city."
    parameters = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}

    def run(self, city: str = "", **kwargs) -> ToolResult:
        import urllib.request
        import urllib.parse
        try:
            url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%l:+%c+%t+%w&lang=zh"
            req = urllib.request.Request(url, headers={"User-Agent": "Pulse-Agent/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = resp.read().decode("utf-8", errors="replace").strip()
                return ToolResult(ok=True, output=result)
        except Exception as e:
            return ToolResult(ok=False, error=f"weather fetch failed: {e}")


def register(runtime):
    runtime.tools.register(WeatherTool())
    runtime.memory.add_note("weather plugin loaded")
