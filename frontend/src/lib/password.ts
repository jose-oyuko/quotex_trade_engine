export const MIN_PASSWORD_LENGTH = 10

/** The problem with a new password that can be seen without asking the server, or null. */
export function passwordProblem(password: string, repeat: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `The password must be at least ${String(MIN_PASSWORD_LENGTH)} characters long.`
  }
  if (password !== repeat) return 'The two passwords are not the same.'
  return null
}
