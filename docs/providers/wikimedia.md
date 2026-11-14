# Wikimedia Commons Media Provider Review

- **Provider ID**: `wikimedia_commons`
- **Supported Media**: Images (JPEG, PNG, SVG), Video clips (WebM, MP4, OGG)
- **Authentication**: **Keyless** (`commons.wikimedia.org/w/api.php`)
- **Rate Limit**: 60 requests per minute with mandatory `User-Agent`
- **Cache Policy**: 48-hour response cache

### License Compliance Filter
Wikimedia Commons contains a mixture of free public domain assets, permissive attribution licenses, and restrictive copyleft/non-commercial licenses. Nova Autopilot parses `extmetadata.LicenseShortName` and `extmetadata.LicenseUrl` and strictly enforces:
- **ACCEPTED**: Public Domain, CC0 1.0, CC-BY 1.0/2.0/2.5/3.0/4.0.
- **REJECTED**: CC BY-SA (ShareAlike copyleft clause forces video to inherit sharealike license), CC-NC (NonCommercial restriction forbids monetized YouTube channels), CC-ND (NoDerivatives forbids motion cropping and subtitles).
