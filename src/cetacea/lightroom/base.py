from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class VerifiedFile:
    asset_id: str
    abs_path: Path
    sha256: str
    size: int
    rel_path: str = ''
    order: str = ''
    photographer: str = ''

@dataclass
class RegisterResult:
    asset_id: str
    photo_id: str | None = None
    error: str | None = None
    mock: bool = False
    status: str | None = None

@dataclass
class PresetResult:
    asset_id: str
    error: str | None = None
    mock: bool = False

@dataclass
class ExportResult:
    asset_id: str
    output_path: Path | None = None
    error: str | None = None
    mock: bool = False

class LightroomAdapter(ABC):
    mock = False
    @abstractmethod
    def status(self): ...
    @abstractmethod
    def register(self, files: list[VerifiedFile]) -> list[RegisterResult]: ...
    @abstractmethod
    def apply_preset(self, photo_refs, preset) -> list[PresetResult]: ...
    @abstractmethod
    def export_jpeg(self, photo_refs, dest_dir, max_edge, quality) -> list[ExportResult]: ...
