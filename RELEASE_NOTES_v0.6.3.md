# HanJoo IR 0.6.3

Stability release focused on the one-install architecture and recognition Brain.

Most important change: the Brain no longer uses Node SEA, which caused `require is not defined` on the user's HAOS system. Startup is now fail-fast and health-checked for all three internal services.

See `AUDIT_v0.6.3.md` for the full audit.
