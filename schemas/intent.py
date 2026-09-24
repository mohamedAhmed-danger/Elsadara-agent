from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    VISIT = "visit"
    INQUIRY = "inquiry"
    COMPLAINT = "complaint"
    DIRECT = "direct"
    LABRESULTS = "labresults"


class RefinedQuery(BaseModel):
    query: str = Field(
        ...,
        description="Refined search query extracted from user message or OCR text, representing a distinct medical test or service."
    )

    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative names or synonyms for the laboratory service in both Arabic and English."
    )

    keywords: List[str] = Field(
        default_factory=list,
        description="Important domain keywords and medical terms related to the test."
    )

    description: Optional[str] = Field(
        default="",
        description="Optional brief summary or context of the laboratory service."
    )


class IntentResponse(BaseModel):
    intent: IntentType = Field(
        ...,
        description="The main intent classification of the user's message."
    )
    
    refined_queries: List[RefinedQuery] = Field(
        ...,
        description="REQUIRED LIST: MUST contain one RefinedQuery entry for EVERY lab test or medical analysis mentioned. If no tests are mentioned, return an empty list [], but YOU MUST INCLUDE THIS KEY."
    )
    
    is_bundle_query: bool = Field(
        default=False, 
        description="Set to True ONLY if the user is explicitly asking about bundles, checkup offers, or packages."
    )