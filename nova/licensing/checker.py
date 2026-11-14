"""Strict Automated License Compliance Checker."""

import logging
from pathlib import Path
from typing import Optional
import yaml
from nova.licensing.models import LicenseProof

logger = logging.getLogger("nova.licensing")


class LicenseComplianceEngine:
    """Evaluates asset licenses against commercial allow-lists and reject-lists."""

    def __init__(self, policy_path: str | Path = "config/license_policy.yaml"):
        self.policy_path = Path(policy_path)
        self.policy = self._load_policy()

    def _load_policy(self) -> dict:
        if not self.policy_path.exists():
            return {
                "allowed_licenses": [],
                "prohibited_licenses": [],
                "restrictions": {},
            }
        with open(self.policy_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def evaluate(
        self,
        raw_license: str,
        provider: str,
        asset_id: str,
        landing_page: str,
        creator: str = "",
        creator_url: str = "",
        title: str = "",
        raw_license_url: str = "",
    ) -> tuple[bool, Optional[LicenseProof], Optional[str]]:
        """Evaluates a raw license string and returns (is_allowed, proof_record, rejection_reason).

        Returns:
            (True, LicenseProof, None) if allowed.
            (False, None, rejection_reason) if rejected.
        """
        raw_norm = (raw_license or "").strip().lower()
        url_norm = (raw_license_url or "").strip().lower()

        # Check prohibited indicators first
        if any(bad in raw_norm for bad in ["by-sa", "sharealike", "share-alike", "sa-"]):
            return (
                False,
                None,
                "Rejected: CC BY-SA copyleft clause forces derivative video to inherit share-alike license.",
            )

        if any(bad in raw_norm for bad in ["-nc", "noncommercial", "non-commercial", "nc-"]):
            return (
                False,
                None,
                "Rejected: NonCommercial restriction prohibits use on monetized / ad-supported channel.",
            )

        if any(bad in raw_norm for bad in ["-nd", "noderivatives", "no-derivatives", "nd-"]):
            return (
                False,
                None,
                "Rejected: NoDerivatives restriction prohibits cropping, motion pan/zoom, or editing.",
            )

        if any(bad in raw_norm for bad in ["all rights reserved", "copyrighted", "editorial only", "editorial use"]):
            return (
                False,
                None,
                f"Rejected: Proprietary / Editorial restriction ({raw_license}).",
            )

        # Allow-list matching
        # 1. CC0 / Public Domain
        if any(ok in raw_norm for ok in ["cc0", "cc-0", "zero", "public domain", "publicdomain", "pdm"]):
            proof = LicenseProof(
                provider=provider,
                asset_id=asset_id,
                license_id="cc0",
                license_name="Creative Commons Zero / Public Domain",
                license_url=raw_license_url or "https://creativecommons.org/publicdomain/zero/1.0/",
                landing_page_url=landing_page,
                creator_name=creator or "Public Domain Contributor",
                creator_url=creator_url,
                attribution_required=False,
                attribution_text=f"Public Domain / CC0 via {provider.capitalize()}",
                commercial_use_ok=True,
                modifications_ok=True,
                is_public_domain=True,
            )
            return True, proof, None

        # 2. US Government Work / NASA
        if any(ok in raw_norm for ok in ["nasa", "pd-usgov", "usgov", "government work"]):
            creator_disp = creator or "NASA"
            proof = LicenseProof(
                provider=provider,
                asset_id=asset_id,
                license_id="pd_usgov",
                license_name="United States Government Work (Public Domain)",
                license_url="https://www.usa.gov/government-works",
                landing_page_url=landing_page,
                creator_name=creator_disp,
                creator_url=creator_url,
                attribution_required=True,
                attribution_text=f"Media courtesy of {creator_disp}",
                commercial_use_ok=True,
                modifications_ok=True,
                is_public_domain=True,
            )
            return True, proof, None

        # 3. Pixabay Content License
        if "pixabay" in raw_norm or provider.lower() == "pixabay":
            creator_disp = creator or "Stock Contributor"
            proof = LicenseProof(
                provider="pixabay",
                asset_id=asset_id,
                license_id="pixabay_license",
                license_name="Pixabay Content License",
                license_url="https://pixabay.com/service/license-summary/",
                landing_page_url=landing_page,
                creator_name=creator_disp,
                creator_url=creator_url,
                attribution_required=False,
                attribution_text=f"Media by {creator_disp} from Pixabay",
                commercial_use_ok=True,
                modifications_ok=True,
            )
            return True, proof, None

        # 4. Pexels License
        if "pexels" in raw_norm or provider.lower() == "pexels":
            creator_disp = creator or "Stock Contributor"
            proof = LicenseProof(
                provider="pexels",
                asset_id=asset_id,
                license_id="pexels_license",
                license_name="Pexels License",
                license_url="https://www.pexels.com/license/",
                landing_page_url=landing_page,
                creator_name=creator_disp,
                creator_url=creator_url,
                attribution_required=False,
                attribution_text=f"Video/Photo by {creator_disp} from Pexels",
                commercial_use_ok=True,
                modifications_ok=True,
            )
            return True, proof, None

        # 5. CC BY (with attribution)
        if any(ok in raw_norm for ok in ["cc-by", "cc by", "attribution", "by-2.0", "by-3.0", "by-4.0"]):
            creator_disp = creator or "Creative Commons Contributor"
            title_disp = title or f"Asset {asset_id}"
            proof = LicenseProof(
                provider=provider,
                asset_id=asset_id,
                license_id="cc_by",
                license_name="Creative Commons Attribution (CC BY)",
                license_url=raw_license_url or "https://creativecommons.org/licenses/by/4.0/",
                landing_page_url=landing_page,
                creator_name=creator_disp,
                creator_url=creator_url,
                attribution_required=True,
                attribution_text=f"'{title_disp}' by {creator_disp} (CC BY) via {landing_page}",
                commercial_use_ok=True,
                modifications_ok=True,
            )
            return True, proof, None

        # 6. Natural Earth
        if "natural earth" in raw_norm or provider.lower() == "generated_maps":
            proof = LicenseProof(
                provider="generated_maps",
                asset_id=asset_id,
                license_id="natural_earth_pd",
                license_name="Natural Earth Public Domain",
                license_url="https://www.naturalearthdata.com/about/terms-of-use/",
                landing_page_url="https://www.naturalearthdata.com/",
                creator_name="Natural Earth & Nova Motion",
                attribution_required=False,
                attribution_text="Map data from Natural Earth (Public Domain)",
                commercial_use_ok=True,
                modifications_ok=True,
                is_public_domain=True,
            )
            return True, proof, None

        # 7. Procedural / Generated Motion Graphics (Internal Public Domain / CC0 equivalent)
        if provider.lower() in ["procedural_motion", "procedural", "internal", "generated"] or any(
            ok in raw_norm for ok in ["procedural_motion", "procedural", "generated motion", "generated graphic", "internal"]
        ):
            proof = LicenseProof(
                provider="procedural_motion",
                asset_id=asset_id,
                license_id="procedural_motion",
                license_name="Procedural Data-Driven Motion Graphic (Public Domain / CC0)",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                landing_page_url=landing_page or "internal://procedural",
                creator_name=creator or "Nova Autopilot Motion Engine",
                creator_url="",
                attribution_required=False,
                attribution_text="Generated Motion Graphic by Nova Autopilot",
                commercial_use_ok=True,
                modifications_ok=True,
                is_public_domain=True,
            )
            return True, proof, None

        # If unknown or empty
        return (
            False,
            None,
            f"Rejected: Unrecognized or missing license specification '{raw_license}'. Commercial safety requires verified allow-list match.",
        )
