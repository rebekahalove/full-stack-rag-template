/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_NAME: string;
  readonly VITE_APP_MARK: string;
  readonly VITE_APP_TAGLINE: string;
  readonly VITE_APP_DESCRIPTION: string;
  readonly VITE_API_BASE_URL: string;
  readonly VITE_MAX_UPLOAD_SIZE_MB: string;
  readonly VITE_ALLOWED_UPLOAD_EXTENSIONS: string;
  readonly VITE_QUESTION_MAX_CHARACTERS: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
