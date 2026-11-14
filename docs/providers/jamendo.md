# Jamendo Audio Provider Review & Decision Record

- **Provider ID**: `jamendo`
- **Supported Media**: Audio Tracks & Background Music (MP3)
- **Status**: **DISABLED BY DEFAULT** (`enabled: false`)

### Reason for Default Disabling
1. **Non-Commercial Developer Terms**: The free Jamendo Developer API license specifies that content obtained via the API may only be used for personal, non-commercial purposes.
2. **YouTube Content ID Copyright Strikes**: Many tracks in Jamendo's catalog are registered in YouTube's automated Content ID system by their composers. While permissible for personal listening, using them in YouTube Shorts generates automatic copyright claims, routing ad monetization away from the creator or blocking audio.
3. **Alternative**: Nova Autopilot uses local synthesized CC0 sound effects and royalty-free mood music managed by `MusicManager`.
