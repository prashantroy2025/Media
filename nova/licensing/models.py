"""License Compliance Models and Policy Definitions."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional


@dataclass
class LicenseProof:
    """Legal provenance and license record for a retrieved or used asset."""

    provider: str
    asset_id: str
    license_id: str
    license_name: str
    license_url: str
    landing_page_url: str
    creator_name: str
    creator_url: str = ""
    attribution_required: bool = False
    attribution_text: str = ""
    commercial_use_ok: bool = True
    modifications_ok: bool = True
    retrieved_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    terms_version_or_date: str = "2026-11-14"
    is_public_domain: bool = False

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "asset_id": self.asset_id,
            "license_id": self.license_id,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "landing_page_url": self.landing_page_url,
            "creator_name": self.creator_name,
            "creator_url": self.creator_url,
            "attribution_required": self.attribution_required,
            "attribution_text": self.attribution_text,
            "commercial_use_ok": self.commercial_use_ok,
            "modifications_ok": self.modifications_ok,
            "retrieved_at": self.retrieved_at,
            "terms_version_or_date": self.terms_version_or_date,
            "is_public_domain": self.is_public_domain,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LicenseProof":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
