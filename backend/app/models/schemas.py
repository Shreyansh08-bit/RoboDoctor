import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_EXTENSIONS = ('.txt', '.log', '.yaml', '.yml', '.py', '.cpp', '.hpp')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class EvidenceFile(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=32_000)

    @field_validator('name')
    @classmethod
    def safe_name(cls, value: str) -> str:
        value = value.replace('\\', '/').split('/')[-1]
        value = re.sub(r'[^a-zA-Z0-9._ -]', '_', value)
        if not value.lower().endswith(ALLOWED_EXTENSIONS):
            raise ValueError('Unsupported file type')
        return value

    @field_validator('content')
    @classmethod
    def text_only(cls, value: str) -> str:
        if '\x00' in value:
            raise ValueError('Binary files are not supported')
        return value


class DiagnoseRequest(StrictModel):
    text: str = Field(default='', max_length=60_000)
    files: list[EvidenceFile] = Field(default_factory=list, max_length=8)
    mode: Literal['auto', 'rules'] = 'auto'

    @model_validator(mode='after')
    def check_evidence(self):
        contents = [self.text, *(f.content for f in self.files)]
        if not any(c.strip() for c in contents):
            raise ValueError('Provide terminal output or a non-empty file')
        if sum(len(c) for c in contents) > 60_000:
            raise ValueError('Combined evidence must be at most 60,000 characters')
        if any('\x00' in c for c in contents):
            raise ValueError('Binary evidence is not supported')
        return self

    def sources(self) -> list[tuple[str, str]]:
        return [('Terminal', self.text), *((f.name, f.content) for f in self.files)]


class RootCause(StrictModel):
    cause: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=2000)


class Command(StrictModel):
    command: str = Field(min_length=1, max_length=500)
    purpose: str = Field(min_length=1, max_length=1000)


class Diagnosis(StrictModel):
    summary: str = Field(min_length=1, max_length=1500)
    severity: Literal['critical', 'warning', 'informational']
    confidence: Literal['high', 'medium', 'low']
    confidence_reason: str = Field(min_length=1, max_length=1500)
    evidence: list[str] = Field(max_length=20)
    root_causes: list[RootCause] = Field(max_length=8)
    recommended_fix: list[str] = Field(max_length=10)
    commands: list[Command] = Field(max_length=12)
    explanation: str = Field(min_length=1, max_length=3000)
    additional_information_needed: list[str] = Field(max_length=10)

    @field_validator('evidence', 'recommended_fix', 'additional_information_needed')
    @classmethod
    def bounded_items(cls, values: list[str]) -> list[str]:
        if any(not v.strip() or len(v) > 2000 for v in values):
            raise ValueError('Items must be non-empty and at most 2,000 characters')
        return values


class Finding(StrictModel):
    code: str
    title: str
    source: str
    evidence: list[str]


class DiagnoseResponse(StrictModel):
    diagnosis: Diagnosis
    findings: list[Finding]
    engine: Literal['local-ai', 'rules', 'observed']
    model: str | None = None
    notice: str | None = None
    elapsed_ms: int
    status: Literal['problem', 'healthy', 'insufficient'] = 'problem'
    session_id: str | None = None
    execution_sequence: int | None = None
    issue_id: str | None = None
