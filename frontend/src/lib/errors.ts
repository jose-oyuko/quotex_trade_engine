import { ApiError } from '../api/client'

/** A message fit to show the owner, whatever was thrown. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : 'Something went wrong.'
}
