/**
 * Application configuration.
 *
 * API base URL is read from the VITE_API_URL environment variable.
 * Defaults to http://localhost:8000 for local development.
 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_URL ?? "";

