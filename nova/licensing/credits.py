"""Credits and Attribution Compiler for YouTube/Instagram Descriptions."""

import json
from pathlib import Path
from nova.licensing.models import LicenseProof


class CreditsCompiler:
    """Generates credits.json and formatted video description attribution blocks."""

    @staticmethod
    def compile_credits(
        video_id: int,
        license_proofs: list[LicenseProof],
        output_dir: str | Path = "output",
    ) -> tuple[Path, str]:
        """Compiles credits.json and returns (credits_file_path, description_credit_text)."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        credits_file = out_path / f"credits_{video_id}.json"

        records = [p.to_dict() for p in license_proofs]
        with open(credits_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "video_id": video_id,
                    "total_assets": len(license_proofs),
                    "assets": records,
                },
                f,
                indent=2,
            )

        # Build description credit text
        lines = ["\n--- Stock Media & Visual Attributions ---"]
        unique_credits = set()

        for p in license_proofs:
            if p.attribution_text:
                unique_credits.add(p.attribution_text)
            elif p.attribution_required:
                unique_credits.add(f"'{p.asset_id}' by {p.creator_name} ({p.license_name}) - {p.landing_page_url}")

        if not unique_credits:
            lines.append("All visuals licensed via Pixabay, CC0 Public Domain, or custom procedural motion graphics.")
        else:
            for c in sorted(unique_credits):
                lines.append(f"• {c}")

        desc_text = "\n".join(lines)
        return credits_file, desc_text
