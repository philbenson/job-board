// The variables Vite puts in import.meta.env, typed strictly so a misspelling
// fails the type check rather than reading as undefined.
interface ViteTypeOptions {
  strictImportMetaEnv: unknown
}

interface ImportMetaEnv {
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
