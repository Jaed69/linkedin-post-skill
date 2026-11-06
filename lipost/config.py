"""Credential loading: environment first, then a private KEY=VALUE env file."""

import os
import stat

KEYS = ("PUBLORA_API_KEY", "LIPOST_PLATFORM_ID")


class ConfigError(Exception):
    """A usage/configuration error (exit code 2)."""


def env_file_path(env):
    base = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME", "~"), ".config")
    return os.path.join(os.path.expanduser(base), "lipost", "env")


def read_env_file(path):
    st = os.stat(path)
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(f"{path} is accessible by group or others; "
                          f"fix it with: chmod 600 {path}")
    values = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_credentials(env):
    """Return {key: value} for KEYS; env vars win, the file fills gaps."""
    values = {k: env[k] for k in KEYS if env.get(k)}
    if len(values) < len(KEYS):
        path = env_file_path(env)
        if os.path.exists(path):
            file_values = read_env_file(path)
            for k in KEYS:
                values.setdefault(k, file_values.get(k, ""))
    if not values.get("PUBLORA_API_KEY"):
        raise ConfigError("PUBLORA_API_KEY is not set (environment or "
                          f"{env_file_path(env)})")
    return values
