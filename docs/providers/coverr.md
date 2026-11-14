# Coverr Video Provider Review & Decision Record

- **Provider ID**: `coverr`
- **Supported Media**: Stock Video (MP4)
- **Status**: **DISABLED BY DEFAULT** (`enabled: false`)

### Reason for Default Disabling
1. **Commercial Terms Conflict**: Coverr's Free Developer API terms of service explicitly prohibit using footage in commercially monetized video channels or advertising without a paid enterprise tier.
2. **Watermark / Attribution Requirement**: Coverr's API terms mandate embedding an on-screen clickable logo overlay back to Coverr.co. On vertical short-form video (YouTube Shorts, Instagram Reels), on-screen logos obstruct karaoke captions and degrade retention.
3. **Override**: If the user holds a commercial enterprise agreement with Coverr, they may enable this provider via `python -m nova providers enable coverr` or via the Review Studio toggle.
