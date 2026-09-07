from pydantic import BaseModel, Field
from typing import Dict, Any, List

class CircuitDesignRequest(BaseModel):
    prompt: str = Field(..., description="The user's engineering request")
    system_prompt: str | None = None
