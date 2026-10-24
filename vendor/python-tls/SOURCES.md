# Python TLS sidecar

`codex-rejected-cas.pem` is public X.509 trust-policy data copied unchanged from
the supplied build Python's `Lib/` directory. It is not a private key or user
credential. Its SHA256 is
`c916ce1b14ed8ca69e9b5c9fab22799a900dd610d6d4ec9b1347f4fd48e53718`.

This build runtime's `ssl.SSLContext.__new__` loads the sidecar relative to
`ssl.__file__`. Both frozen executables retain that dependency and policy.
Stock CPython builds without that reference do not need it. The build rejects
missing or changed sidecar data; it never disables TLS or certificate checking.

The full source ZIP retains this data and its build checks. A build-runtime
policy update requires an explicit review and fingerprint update.
