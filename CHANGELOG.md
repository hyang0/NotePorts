# Changelog

## [Unreleased] - 2026-02-04

### Security
- Added input validation for configuration service names (keys) to prevent code injection.
  - Implemented whitelist regex: `^[\w\s\-\.\(\)\[\]/@#]+$`
  - Invalid service names are now logged and skipped during load.
  - API now returns 400 Bad Request for invalid service names.
- Added validation for port numbers.
  - Ensures ports are integers between 1 and 65535.
  - Invalid ports are logged and skipped.

