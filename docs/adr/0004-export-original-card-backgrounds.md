# Export original Card Backgrounds

Only Apple Pay Cards are in scope, and only their original `cardBackgroundCombined` resources are exported. Existing files are copied byte-for-byte without PNG/PDF conversion, deduplication, or indexing. Name collisions receive numeric suffixes so that a rerun never overwrites an earlier export.
