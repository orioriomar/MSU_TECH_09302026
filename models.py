"""This file defines the exact shapes of data the app accepts. If Gemini or a user sends
anything that doesn't fit these shapes, it is rejected before it can do any harm.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

FieldName = Literal['price_usd', 'availability', 'address', 'hours', 'policy']
QuestionKind = Literal['visibility', 'accuracy', 'stress']

class StrictModel(BaseModel):
    """This is the base shape: it rejects unexpected fields and trims extra spaces."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class QuestionSuggestion(StrictModel):
    """This is one question suggested by Gemini."""
    type: QuestionKind
    text: str = Field(min_length=12, max_length=500)
    product_id: str = ''
    target_field: str = ''
    context: str = ''

class QuestionBatch(StrictModel):
    """This is a list of questions suggested by Gemini."""
    questions: list[QuestionSuggestion] = Field(min_length=1, max_length=60)

class ExtractedClaim(StrictModel):
    """This is one factual claim pulled from an AI answer, with the exact quote that supports it."""
    product_id: str = Field(min_length=1)
    field: FieldName
    value: str = Field(min_length=1)
    context: str = ''
    quote: str = Field(min_length=1, description='Exact substring from answer supporting the claim')

class ClaimBatch(StrictModel):
    """This is every claim found in one answer, plus whether the business was named."""
    brand_mentioned: bool
    claims: list[ExtractedClaim] = Field(max_length=30)

class AnswerSubmission(StrictModel):
    """This is an AI answer pasted in by an analyst."""
    question_id: str
    answer: str = Field(min_length=3, max_length=20000)
    citations: list[str] = Field(default_factory=list, max_length=15)
    extraction: Literal['ollama', 'manual'] = 'ollama'  # ollama=legacy API label for configured AI formatter
    manual_claims: list[ExtractedClaim] = Field(default_factory=list)

class TicketDecision(StrictModel):
    """This is a person's decision on a ticket."""
    action: Literal['approve', 'reject', 'investigate']
    note: str = Field(default='', max_length=2000)

class QuestionGenerateRequest(StrictModel):
    """This is a request for Gemini to generate questions."""
    business_id: str = "juniper_bakery"
    visibility: int = Field(default=6, ge=0, le=20)
    accuracy: int = Field(default=7, ge=0, le=20)
    stress: int = Field(default=7, ge=0, le=20)

class NewQuestion(StrictModel):
    """This is a question added by hand."""
    business_id: str = "juniper_bakery"
    text: str = Field(min_length=12, max_length=500)
    type: QuestionKind
    product_id: str = ''
    target_field: str = ''
    context: str = ''
