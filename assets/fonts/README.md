# Fonts for Nova Autopilot Subtitles

Nova Autopilot renders animated subtitles (.ass burned into MP4 via FFmpeg) in Roman script for maximum mobile readability.

## Default macOS Font
By default, Nova uses system fonts already present on macOS:
- `Helvetica-Bold` (Pre-installed, ultra-clean vertical short readability)
- `Arial-Bold` or `SF Pro Display`

## Recommended Free Custom Fonts (Google Fonts)
For an even punchier bold social media aesthetic (like Alex Hormozi or Ali Abdaal style subtitles), download any of the following open-source fonts:

1. **Montserrat (ExtraBold / Black):**
   - Download from: [fonts.google.com/specimen/Montserrat](https://fonts.google.com/specimen/Montserrat)
   - Copy `Montserrat-Black.ttf` into this folder (`assets/fonts/Montserrat-Black.ttf`).
2. **Poppins (Black):**
   - Download from: [fonts.google.com/specimen/Poppins](https://fonts.google.com/specimen/Poppins)
   - Excellent rounded geometry for Hinglish romanized text.
3. **The Bold Font:**
   - Popular high-impact all-caps display font for shorts.

To activate a custom font, update `config/config.yaml`:
```yaml
video:
  subtitles:
    font_name: "Montserrat-Black" # or point to assets/fonts/Montserrat-Black.ttf
```
