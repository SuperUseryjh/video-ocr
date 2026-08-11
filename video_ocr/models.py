from dataclasses import dataclass


@dataclass
class OcrResult:
    timestamp_ms: int
    text: str
    confidence: float
