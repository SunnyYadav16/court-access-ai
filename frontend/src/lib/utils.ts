import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Extract first name from user name or email
 * @param name - Full name (e.g., "Judge Thompson")
 * @param email - Email address (e.g., "sunny@gmail.com")
 * @returns First name, email username, or "User" as fallback
 */
export function getFirstName(
  name?: string | null,
  email?: string | null
): string {
  if (name && name.trim().length > 0) {
    return name.trim().split(/\s+/)[0]
  }
  if (email) {
    return email.split("@")[0]
  }
  return "User"
}

/**
 * Extract initials from user name or email
 * @param name - Full name (e.g., "Sunny Yadav" → "SY", "Ana Maria Garcia" → "AM")
 * @param email - Email address (e.g., "sunny@gmail.com" → "S")
 * @returns Initials (max 2 characters, uppercase)
 */
export function getInitials(
  name?: string | null,
  email?: string | null
): string {
  if (name && name.trim().length > 0) {
    const words = name.trim().split(/\s+/)
    if (words.length >= 2) {
      return (words[0][0] + words[1][0]).toUpperCase()
    }
    return words[0].slice(0, 2).toUpperCase()
  }
  if (email) {
    return email[0].toUpperCase()
  }
  return "U"
}
