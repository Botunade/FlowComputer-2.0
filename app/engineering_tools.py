import json
import numpy as np
import control as ct
import sympy as sp
from pint import UnitRegistry

ureg = UnitRegistry()

def convert_units(value: float, from_unit: str, to_unit: str) -> dict:
    try:
        quantity = value * ureg(from_unit)
        converted = quantity.to(to_unit)
        return {"result": round(converted.magnitude, 6), "unit": str(converted.units)}
    except Exception as e:
        return {"error": str(e)}

TOOL_FUNCTIONS = {
    "convert_units": convert_units,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "convert_units",
            "description": "Convert a numeric value between engineering units (e.g. psi to bar, rpm to rad/s).",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "number"},
                    "from_unit": {"type": "string"},
                    "to_unit": {"type": "string"},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
        },
    }
]

def execute_tool_call(name: str, arguments_json: str) -> str:
    if name not in TOOL_FUNCTIONS:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        args = json.loads(arguments_json)
        result = TOOL_FUNCTIONS[name](**args)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})
