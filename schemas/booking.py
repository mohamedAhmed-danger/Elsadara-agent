from pydantic import BaseModel, Field


class VisitReply(BaseModel):
    """
    Structured conversational output for the visit (home visit booking) node.
    The LLM MUST return this when it is NOT invoking `save_visit_tool` this turn
    (i.e. it's still asking for missing fields, answering a question, or the
    user hasn't confirmed yet).
    """

    reply: str = Field(
        ...,
        description=(
            "The natural language reply to send back to the patient. "
            "Egyptian Arabic by default, matching the patient's language/tone."
        ),
    )
    summary: str = Field(
        ...,
        description=(
            "The updated cumulative booking summary, following the "
            "SUMMARY GUIDELINES section of the system prompt exactly."
        ),
    )
