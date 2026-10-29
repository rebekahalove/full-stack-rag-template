function requireValue(name: string, value: string | undefined): string {
  const normalized = value?.trim();
  if (!normalized) throw new Error(`${name} is required. Copy .env.example to .env.`);
  return normalized;
}

function requirePositiveNumber(name: string, value: string | undefined): number {
  const parsed = Number(requireValue(name, value));
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive number.`);
  }
  return parsed;
}

export const frontendConfig = {
  appName: requireValue("VITE_APP_NAME", import.meta.env.VITE_APP_NAME),
  appMark: requireValue("VITE_APP_MARK", import.meta.env.VITE_APP_MARK),
  appTagline: requireValue("VITE_APP_TAGLINE", import.meta.env.VITE_APP_TAGLINE),
  apiBaseUrl: requireValue("VITE_API_BASE_URL", import.meta.env.VITE_API_BASE_URL).replace(
    /\/$/,
    "",
  ),
  maxUploadSizeMb: requirePositiveNumber(
    "VITE_MAX_UPLOAD_SIZE_MB",
    import.meta.env.VITE_MAX_UPLOAD_SIZE_MB,
  ),
  allowedUploadExtensions: requireValue(
    "VITE_ALLOWED_UPLOAD_EXTENSIONS",
    import.meta.env.VITE_ALLOWED_UPLOAD_EXTENSIONS,
  )
    .split(",")
    .map((value) => (value.trim().startsWith(".") ? value.trim() : `.${value.trim()}`))
    .filter(Boolean),
  questionMaxCharacters: requirePositiveNumber(
    "VITE_QUESTION_MAX_CHARACTERS",
    import.meta.env.VITE_QUESTION_MAX_CHARACTERS,
  ),
};
