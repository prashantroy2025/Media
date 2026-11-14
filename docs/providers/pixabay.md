# Pixabay Media Provider Review

- **Provider ID**: `pixabay`
- **Supported Media**: Video (Full HD / 4K MP4), Photo / Illustration (JPEG / PNG)
- **Authentication**: `PIXABAY_API_KEY` (Free key from [pixabay.com/api/docs/](https://pixabay.com/api/docs/))
- **Rate Limit**: 100 requests per minute
- **Cache Policy**: 24-hour mandatory response cache; download assets locally rather than hotlinking (honored by `ProviderResponseCache` and `BaseMediaProvider.download`).

### License Summary: Pixabay Content License
- **Commercial Use**: Allowed freely across all commercial digital platforms (YouTube, Instagram, TikTok).
- **Modifications**: Allowed (derivative cropping, subtitles, zoom/pan effects).
- **Attribution**: Not legally required, but polite credit compiled in `credits.json`.
- **Prohibited**: Do not resell or redistribute unaltered copies of Pixabay content as standalone wallpapers or stock items.
